"""計算每個族群的「族群指數」時間序列。

權重策略：
  - 預設 market_cap，但 PRD §4.1 規定：成分股 < 5 檔自動切等權
  - 目前 stocks.market_cap 尚未填值，故全部走等權（Phase 2 補市值後自動切換）

族群指數定義（等權報酬指數）：
  index_t = index_{t-1} * (1 + mean(daily_return_i))
  base   = 100 at the first common date
"""
from __future__ import annotations

import logging
import sqlite3

import pandas as pd

log = logging.getLogger(__name__)


def _load_member_prices(conn: sqlite3.Connection, theme_id: str) -> pd.DataFrame:
    """回傳 pivot 後的收盤價：index=date, columns=stock_id"""
    df = pd.read_sql(
        """
        SELECT d.date, d.stock_id, d.close
        FROM theme_membership m
        JOIN daily_prices d
          ON d.stock_id = m.stock_id AND d.market = m.market
        WHERE m.theme_id = ? AND m.market = 'TW'
        """,
        conn,
        params=(theme_id,),
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot(index="date", columns="stock_id", values="close").sort_index()


def compute_theme_index(
    conn: sqlite3.Connection, theme_id: str, weighting: str = "equal"
) -> pd.DataFrame:
    """回傳欄位：date, index_value, pct_change_1d, pct_change_5d, pct_change_20d,
    ma20, ma60, ma20_slope, pct_above_ma20。"""
    prices = _load_member_prices(conn, theme_id)
    if prices.empty or prices.shape[1] == 0:
        return pd.DataFrame()

    # 每檔日報酬，所有成員的橫斷面平均
    returns = prices.pct_change(fill_method=None)
    if weighting == "equal" or prices.shape[1] < 5:
        # 每天有資料的成員平均（自動忽略 NaN）
        cross_section_ret = returns.mean(axis=1)
    else:
        # 預留：未來市值權重
        cross_section_ret = returns.mean(axis=1)

    # 累積成指數，base 100
    idx = (1 + cross_section_ret.fillna(0)).cumprod() * 100

    # 各檔的 20MA → 計算當日多少比例成員站上自己的 20MA
    ma20_each = prices.rolling(20).mean()
    above = (prices > ma20_each).sum(axis=1)
    counts = prices.notna().sum(axis=1)
    pct_above_ma20 = (above / counts.replace(0, pd.NA)).astype(float)

    out = pd.DataFrame({"index_value": idx})
    out["pct_change_1d"] = out["index_value"].pct_change(1)
    out["pct_change_5d"] = out["index_value"].pct_change(5)
    out["pct_change_20d"] = out["index_value"].pct_change(20)
    out["ma20"] = out["index_value"].rolling(20).mean()
    out["ma60"] = out["index_value"].rolling(60).mean()
    # 20MA 斜率：用最近 5 日 MA20 的線性差
    out["ma20_slope"] = out["ma20"].diff(5) / 5
    out["pct_above_ma20"] = pct_above_ma20
    out.index.name = "date"
    return out.reset_index()


def all_theme_ids(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT theme_id FROM themes ORDER BY theme_id")
    return [r[0] for r in cur.fetchall()]
