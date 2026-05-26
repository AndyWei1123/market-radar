"""起漲偵測（PRD §4）。

每日針對每個族群計算：
  C1 族群指數 > 20MA
  C2 20MA 斜率 > 0
  C3 RS 強度（vs 大盤）為近 20 日新高
  C4 成分股 >50% 站上 20MA
  C5 近 5 日漲幅 >= 3%

狀態判定：
  條件達成數 >= rising_min_conditions (5) → 'rising'
  條件達成數 >= candidate_min_conditions (3) 且 C1+C2 必須達成 → 'candidate'
  族群指數 < 20MA → 'falling'
  其他 → 'idle'

rising_day_n：從最近一次「跌破 20MA → 重新站回 20MA」那天起算 Day 1。
"""
from __future__ import annotations

import logging
import sqlite3

import pandas as pd

from config import settings
from compute.theme_index import compute_theme_index

log = logging.getLogger(__name__)


def _load_benchmark(conn: sqlite3.Connection, index_id: str = "TWII") -> pd.Series:
    df = pd.read_sql(
        "SELECT date, close FROM market_index WHERE index_id = ? ORDER BY date",
        conn,
        params=(index_id,),
    )
    if df.empty:
        return pd.Series(dtype=float, name="bench")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"].rename("bench")


def _compute_rs(theme_index: pd.Series, bench: pd.Series) -> tuple[pd.Series, pd.Series]:
    """RS = (theme / bench) 正規化；rs_momentum = RS 的 20 日變化。"""
    if bench.empty:
        # 無基準時退化為「族群指數本身」
        rs = theme_index / theme_index.iloc[0] * 100
    else:
        aligned = pd.concat([theme_index.rename("t"), bench], axis=1).dropna()
        if aligned.empty:
            return pd.Series(dtype=float), pd.Series(dtype=float)
        ratio = aligned["t"] / aligned["bench"]
        rs = ratio / ratio.iloc[0] * 100
    rs_momentum = rs.pct_change(20)
    return rs, rs_momentum


def _rising_day_n(above_ma20: pd.Series) -> pd.Series:
    """連續站上 20MA 的天數；當天若沒站上 → 0。"""
    n = []
    run = 0
    for v in above_ma20:
        if pd.isna(v):
            n.append(0)
            continue
        if v:
            run += 1
        else:
            run = 0
        n.append(run)
    return pd.Series(n, index=above_ma20.index)


def compute_metrics_for_theme(
    conn: sqlite3.Connection, theme_id: str, bench: pd.Series
) -> pd.DataFrame:
    s = settings()["breakout_rules"]
    cond = s["conditions"]
    weighting = s.get("index_weighting", "equal")
    fallback = s.get("fallback_equal_if_members_below", 5)

    df = compute_theme_index(conn, theme_id, weighting=weighting)
    if df.empty:
        return df

    df = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    df.index.name = "date"

    # RS
    rs, rs_mom = _compute_rs(df["index_value"], bench)
    df["rs_score"] = rs
    df["rs_momentum"] = rs_mom
    # RS 20 日新高
    df["rs_20d_high"] = df["rs_score"] >= df["rs_score"].rolling(20).max()

    # 5 條件
    c1 = df["index_value"] > df["ma20"]
    c2 = df["ma20_slope"] > 0
    c3 = df["rs_20d_high"].fillna(False) if cond.get("c3_rs_20d_high", True) else True
    c4 = df["pct_above_ma20"] >= cond.get("c4_pct_above_ma20_threshold", 0.5)
    c5 = df["pct_change_5d"] >= cond.get("c5_5d_return_min", 0.03)

    score = c1.astype(int) + c2.astype(int) + c3.astype(int) + c4.astype(int) + c5.astype(int)

    rising_th = s["status_thresholds"]["rising_min_conditions"]
    cand_th = s["status_thresholds"]["candidate_min_conditions"]

    def label(row_idx: int) -> str:
        if pd.isna(df["ma20"].iloc[row_idx]):
            return "idle"
        sc = int(score.iloc[row_idx])
        c1_ok = bool(c1.iloc[row_idx])
        c2_ok = bool(c2.iloc[row_idx])
        if sc >= rising_th:
            return "rising"
        if sc >= cand_th and c1_ok and c2_ok:
            return "candidate"
        if not c1_ok:
            return "falling"
        return "idle"

    df["status"] = [label(i) for i in range(len(df))]
    df["rising_day_n"] = _rising_day_n(c1.fillna(False))
    # 若跌破 20MA 就 reset 為 0
    df.loc[~c1.fillna(False), "rising_day_n"] = 0

    df["theme_id"] = theme_id
    return df.reset_index()


def upsert_metrics(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = []
    for r in df.itertuples():
        rows.append((
            r.theme_id,
            r.date.strftime("%Y-%m-%d"),
            None if pd.isna(r.index_value) else float(r.index_value),
            None if pd.isna(r.pct_change_1d) else float(r.pct_change_1d),
            None if pd.isna(r.pct_change_5d) else float(r.pct_change_5d),
            None if pd.isna(r.pct_change_20d) else float(r.pct_change_20d),
            None if pd.isna(r.ma20) else float(r.ma20),
            None if pd.isna(r.ma60) else float(r.ma60),
            None if pd.isna(r.ma20_slope) else float(r.ma20_slope),
            None if pd.isna(r.rs_score) else float(r.rs_score),
            None if pd.isna(r.rs_momentum) else float(r.rs_momentum),
            None if pd.isna(r.pct_above_ma20) else float(r.pct_above_ma20),
            int(r.rising_day_n),
            str(r.status),
        ))
    conn.executemany(
        """INSERT INTO theme_daily_metrics
           (theme_id, date, index_value, pct_change_1d, pct_change_5d, pct_change_20d,
            ma20, ma60, ma20_slope, rs_score, rs_momentum, pct_above_ma20,
            rising_day_n, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(theme_id, date) DO UPDATE SET
             index_value=excluded.index_value,
             pct_change_1d=excluded.pct_change_1d,
             pct_change_5d=excluded.pct_change_5d,
             pct_change_20d=excluded.pct_change_20d,
             ma20=excluded.ma20,
             ma60=excluded.ma60,
             ma20_slope=excluded.ma20_slope,
             rs_score=excluded.rs_score,
             rs_momentum=excluded.rs_momentum,
             pct_above_ma20=excluded.pct_above_ma20,
             rising_day_n=excluded.rising_day_n,
             status=excluded.status
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def compute_all(conn: sqlite3.Connection) -> dict:
    bench = _load_benchmark(conn, settings()["benchmarks"]["TW"])
    if bench.empty:
        log.warning("benchmark TWII not found in market_index; RS will fall back to absolute index")

    cur = conn.execute("SELECT theme_id FROM themes ORDER BY theme_id")
    theme_ids = [r[0] for r in cur.fetchall()]

    totals = {"themes": 0, "rows": 0, "skipped": 0}
    for tid in theme_ids:
        df = compute_metrics_for_theme(conn, tid, bench)
        if df.empty:
            totals["skipped"] += 1
            continue
        n = upsert_metrics(conn, df)
        totals["themes"] += 1
        totals["rows"] += n
    return totals
