"""共用 UI 工具 — 各頁面 import 使用。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# 在 Streamlit Cloud 上自動把壓縮 DB 解開（本機已有 DB 會跳過）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from bootstrap_db import ensure_db as _bootstrap_db
    _bootstrap_db()
except Exception as _e:
    # 本機若沒有壓縮檔也沒關係 — 下面 ensure_db() 會檢查並提示
    pass

DB_PATH = ROOT / "data" / "market.db"


def ensure_db() -> bool:
    """頁面開頭呼叫，DB 不存在 / 空時提示並停。"""
    if not DB_PATH.exists():
        st.error("資料庫未初始化 — 請確認 data/market.db 或 data/market.db.gz 存在")
        st.stop()
    with sqlite3.connect(DB_PATH) as conn:
        n = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    if n == 0:
        st.warning("資料庫尚無資料")
        st.stop()
    return True


def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


# ───────── 共用查詢 ─────────
@st.cache_data(ttl=60)
def get_overview() -> dict:
    with conn() as c:
        stocks_total = c.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        ingested = c.execute("SELECT COUNT(DISTINCT stock_id) FROM daily_prices").fetchone()[0]
        dmin, dmax = c.execute("SELECT MIN(date), MAX(date) FROM daily_prices").fetchone()
        bars = c.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        themes_n = c.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
        metrics_dates = c.execute(
            "SELECT COUNT(DISTINCT date) FROM theme_daily_metrics"
        ).fetchone()[0]
    return dict(stocks_total=stocks_total, ingested=ingested,
                date_min=dmin, date_max=dmax, bars=bars,
                themes_n=themes_n, metrics_dates=metrics_dates)


@st.cache_data(ttl=60)
def get_theme_metrics(on_date: str | None = None) -> pd.DataFrame:
    """讀指定日期所有族群指標；on_date=None → 最新日。

    包含 v0.3 新欄位：segment_stage、parent_theme_id（給 segment 視覺化用）。
    """
    sql = """
        SELECT t.theme_id, t.theme_name, t.classification_type AS type,
               t.segment_stage, t.parent_theme_id, t.external_code,
               pt.theme_name AS parent_name,
               m.date, m.index_value, m.ma20, m.ma60,
               m.pct_change_1d, m.pct_change_5d, m.pct_change_20d,
               m.rs_score, m.rs_momentum,
               m.pct_above_ma20, m.rising_day_n, m.status,
               (SELECT COUNT(*) FROM theme_membership tm WHERE tm.theme_id = t.theme_id)
                 AS members
        FROM theme_daily_metrics m
        JOIN themes t ON t.theme_id = m.theme_id
        LEFT JOIN themes pt ON pt.theme_id = t.parent_theme_id
    """
    params: tuple = ()
    if on_date:
        sql += " WHERE m.date = ?"
        params = (on_date,)
    else:
        sql += " WHERE m.date = (SELECT MAX(date) FROM theme_daily_metrics)"
    with conn() as c:
        return pd.read_sql(sql, c, params=params)


@st.cache_data(ttl=60)
def get_available_metric_dates() -> list[str]:
    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT date FROM theme_daily_metrics ORDER BY date"
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def get_theme_history(theme_id: str) -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql(
            "SELECT * FROM theme_daily_metrics WHERE theme_id = ? ORDER BY date",
            c, params=(theme_id,),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=60)
def get_benchmark(index_id: str = "TWII") -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql(
            "SELECT date, close, volume FROM market_index WHERE index_id = ? ORDER BY date",
            c, params=(index_id,),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=60)
def get_theme_members(theme_id: str) -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql(
            """SELECT tm.stock_id, s.name, s.sector
               FROM theme_membership tm
               LEFT JOIN stocks s ON s.stock_id = tm.stock_id AND s.market = tm.market
               WHERE tm.theme_id = ? AND tm.market = 'TW'""",
            c, params=(theme_id,),
        )


@st.cache_data(ttl=60)
def get_stock_list_full() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql(
            "SELECT stock_id, name, sector, market FROM stocks ORDER BY stock_id", c
        )


@st.cache_data(ttl=60)
def get_inst_market_total(on_date: str | None = None) -> pd.DataFrame:
    """全市場三大法人合計（最新日）。"""
    if on_date is None:
        with conn() as c:
            d = c.execute("SELECT MAX(date) FROM institutional_flow").fetchone()[0]
        if not d:
            return pd.DataFrame()
        on_date = d
    with conn() as c:
        df = pd.read_sql(
            """SELECT date,
                      SUM(foreign_net) AS foreign_net,
                      SUM(trust_net)   AS trust_net,
                      SUM(dealer_net)  AS dealer_net,
                      COUNT(*)         AS stocks
               FROM institutional_flow
               WHERE date = ?
               GROUP BY date""",
            c, params=(on_date,),
        )
    return df


@st.cache_data(ttl=60)
def get_inst_top_stocks(direction: str = "buy", limit: int = 10) -> pd.DataFrame:
    """法人合計買 / 賣超 Top N。direction='buy' or 'sell'"""
    order = "DESC" if direction == "buy" else "ASC"
    with conn() as c:
        return pd.read_sql(
            f"""SELECT i.stock_id, s.name, s.sector,
                       i.foreign_net + i.trust_net + i.dealer_net AS total_net,
                       i.foreign_net, i.trust_net, i.dealer_net
                FROM institutional_flow i
                LEFT JOIN stocks s ON s.stock_id=i.stock_id AND s.market=i.market
                WHERE i.date = (SELECT MAX(date) FROM institutional_flow)
                ORDER BY total_net {order}
                LIMIT ?""",
            c, params=(limit,),
        )


@st.cache_data(ttl=60)
def get_news_for_stocks(stock_ids: tuple[str, ...], limit: int = 30) -> pd.DataFrame:
    if not stock_ids:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(stock_ids))
    with conn() as c:
        return pd.read_sql(
            f"""SELECT DISTINCT n.news_id, n.source, n.url, n.title, n.published_at
                FROM news n
                JOIN news_stock_link l ON l.news_id=n.news_id
                WHERE l.stock_id IN ({placeholders})
                ORDER BY n.published_at DESC
                LIMIT ?""",
            c, params=(*stock_ids, limit),
        )


# ───────── 中文化字典 ─────────
TYPE_LABEL = {
    "sector":  "官方產業",
    "segment": "產業鏈細項",
    "theme":   "概念股",
    "chain":   "供應鏈",
}

STATUS_LABEL = {
    "rising": "🟢 起漲確認",
    "candidate": "🟡 起漲候選",
    "idle": "⚪ 觀察中",
    "falling": "🔴 走弱",
}

STATUS_SHORT = {
    "rising": "起漲確認",
    "candidate": "起漲候選",
    "idle": "觀察中",
    "falling": "走弱",
}


def status_badge(status: str) -> str:
    return STATUS_LABEL.get(status, status)


# ───────── 名詞定義（tooltip 用） ─────────
GLOSSARY = {
    "status": (
        "**族群狀態**（依 5 條件判定）\n\n"
        "- 🟢 **起漲確認**：5 條件全部達成（C1 站上 20MA、C2 20MA 上揚、"
        "C3 RS 創 20 日新高、C4 成分股 >50% 站上 20MA、C5 5 日漲幅 ≥3%）\n"
        "- 🟡 **起漲候選**：達成 C1+C2 + 任一其他條件，準備發動\n"
        "- ⚪ **觀察中**：勉強站上 20MA，但動能不足\n"
        "- 🔴 **走弱**：跌破 20MA"
    ),
    "rs": (
        "**RS（相對強弱指標 Relative Strength）**\n\n"
        "族群指數相對加權指數的強弱比。\n"
        "計算方式：(族群指數 / 加權指數) 標準化為 base=100。\n\n"
        "- **RS > 100**：族群表現比大盤強\n"
        "- **RS < 100**：族群表現比大盤弱\n"
        "- **RS 創 20 日新高**：相對動能轉強的訊號"
    ),
    "rs_momentum": (
        "**RS 動能（RS Momentum）**\n\n"
        "RS 過去 20 個交易日的變化率。\n\n"
        "- **動能 > 0**：相對強度仍在上升 → 可能是新領漲族群\n"
        "- **動能 < 0**：相對強度在下滑 → 可能要轉弱\n\n"
        "「RS 強且動能正」是最理想的起漲狀態（右上象限）"
    ),
    "rising_day": (
        "**起漲第幾天**\n\n"
        "從族群指數最近一次「跌破 20MA → 重新站回 20MA」那天起算 Day 1。\n"
        "若再次跌破 20MA 則歸零。\n\n"
        "Day 數越大代表趨勢延續越久，但也意味著相對追高風險。"
    ),
    "pct_above_ma20": (
        "**成分股站上 20MA 比例**\n\n"
        "族群中有多少比例的成員股票，當前收盤價站在自身 20 日均線之上。\n\n"
        "- **>50%**：多數成員參與上漲 → 起漲訊號之一（C4）\n"
        "- **<30%**：族群整體疲弱"
    ),
    "ma20": "**20 日移動平均線**：近 20 個交易日的平均收盤價，代表短期趨勢。",
    "ma60": "**60 日移動平均線**：近 60 個交易日的平均收盤價，代表中期趨勢。",
    "ma20_slope": "**20MA 斜率**：MA20 的近 5 日變化，正值代表均線上揚。",
    "members": "**成員數**：該族群包含的股票檔數。",
    "type": ("**分類軸**：\n"
             "- 🏛️ **官方產業** — TPEx 證交所 47 大產業（自動更新）\n"
             "- 🔬 **產業鏈細項** — 上中下游 ~400 個 segment（IC設計 / IC封測 / ABF載板 …）\n"
             "- 💡 **概念股** — AI、CoWoS、HBM、矽光子…（手動維護）\n"
             "- 🔗 **供應鏈** — NVDA 鏈、台積電鏈、Apple 鏈…（手動維護，跨市場）"),
    "pct_change_5d": "**5 日漲跌幅**：（今日收盤 / 5 個交易日前收盤 − 1）× 100%",
    "index_value": "**族群指數**：族群成員的等權報酬指數（base=100）",
    "color_scheme": (
        "**漲跌顏色配色**\n\n"
        "- **紅漲綠跌**：台股 / 港股 / A股 慣用配色\n"
        "- **綠漲紅跌**：美股 / 歐股 慣用配色"
    ),
}


def info(key: str) -> str:
    """取出名詞解釋，給 st.help / help= 用。"""
    return GLOSSARY.get(key, "")


# ───────── 漲跌顏色（全局） ─────────
COLOR_SCHEMES = {
    "紅漲綠跌（台股）": {
        "up": "#d32f2f", "down": "#2e7d32", "neutral": "#ffffff",
        "scale": ["#2e7d32", "#ffffff", "#d32f2f"],
    },
    "綠漲紅跌（美股）": {
        "up": "#2e7d32", "down": "#d32f2f", "neutral": "#ffffff",
        "scale": ["#d32f2f", "#ffffff", "#2e7d32"],
    },
}

STATUS_COLORS_BASE = {
    "rising": "#4caf50",  # 起漲不分台美都用綠色（正面 = 起漲）
    "candidate": "#ffc107",
    "idle": "#9e9e9e",
    "falling": "#f44336",
}


def color_scheme_picker():
    """側欄放一個全局漲跌顏色切換；回傳當前 scheme dict。"""
    if "color_scheme" not in st.session_state:
        st.session_state["color_scheme"] = "紅漲綠跌（台股）"
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🎨 顯示設定")
        st.radio(
            "漲跌顏色",
            list(COLOR_SCHEMES.keys()),
            key="color_scheme",
            help=GLOSSARY["color_scheme"],
        )
    return COLOR_SCHEMES[st.session_state["color_scheme"]]


def stock_detail_url(stock_id: str) -> str:
    """跨頁跳轉到個股詳細頁的相對 URL。"""
    return f"/個股詳細頁?stock_id={stock_id}"


def csv_download_button(df: pd.DataFrame, filename: str, label: str = "⬇️ 下載 CSV") -> None:
    """通用 CSV 匯出按鈕（utf-8-sig 確保 Excel 開啟中文不亂碼）。"""
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=label, data=csv, file_name=filename, mime="text/csv",
        key=f"csv_{filename}",
    )


def chart_rangebreaks(dates) -> list:
    """讓 Plotly 時間序列圖跳過所有沒有資料的日期（週末 + 假日）。

    用法：
        fig.update_xaxes(rangebreaks=chart_rangebreaks(df['date']))
    """
    if dates is None or len(dates) == 0:
        return [dict(bounds=["sat", "mon"])]
    s = pd.to_datetime(pd.Series(dates)).dt.normalize().dropna().unique()
    if len(s) == 0:
        return [dict(bounds=["sat", "mon"])]
    start, end = min(s), max(s)
    full = pd.date_range(start, end, freq="D")
    have = set(pd.Timestamp(x) for x in s)
    # 工作日中但無資料 → 假日
    missing_weekday = [
        d.strftime("%Y-%m-%d") for d in full
        if d not in have and d.weekday() < 5
    ]
    return [
        dict(bounds=["sat", "mon"]),
        dict(values=missing_weekday),
    ]


def color_for_pct(scheme: dict, pct: float) -> str:
    """單一值對應顏色（給 cell 著色用）。"""
    if pct is None or pd.isna(pct):
        return scheme["neutral"]
    if pct > 0:
        return scheme["up"]
    if pct < 0:
        return scheme["down"]
    return scheme["neutral"]


# ───────── 個股詳細頁查詢 ─────────
@st.cache_data(ttl=120)
def get_company_profile(stock_id: str) -> pd.Series | None:
    with conn() as c:
        df = pd.read_sql(
            "SELECT * FROM company_profile WHERE stock_id=? AND market='TW'",
            c, params=(stock_id,),
        )
    return df.iloc[0] if not df.empty else None


@st.cache_data(ttl=60)
def get_stock_prices(stock_id: str, days: int = 365) -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql(
            """SELECT date, open, high, low, close, volume
               FROM daily_prices
               WHERE stock_id=? AND market='TW'
                 AND date >= date((SELECT MAX(date) FROM daily_prices WHERE stock_id=?), ?)
               ORDER BY date""",
            c, params=(stock_id, stock_id, f"-{days} days"),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()
    return df


@st.cache_data(ttl=60)
def get_stock_inst_flow(stock_id: str, days: int = 60) -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql(
            """SELECT date, foreign_net, trust_net, dealer_net,
                      (foreign_net + trust_net + dealer_net) AS total_net
               FROM institutional_flow
               WHERE stock_id=? AND market='TW'
                 AND date >= date((SELECT MAX(date) FROM institutional_flow), ?)
               ORDER BY date""",
            c, params=(stock_id, f"-{days} days"),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=60)
def get_stock_margin(stock_id: str, days: int = 60) -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql(
            """SELECT date, margin_bal, short_bal
               FROM margin_balance
               WHERE stock_id=? AND market='TW'
                 AND date >= date((SELECT MAX(date) FROM margin_balance), ?)
               ORDER BY date""",
            c, params=(stock_id, f"-{days} days"),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=60)
def get_stock_themes(stock_id: str) -> pd.DataFrame:
    """該股所屬族群 + 各族群最新狀態與漲幅。

    v0.3 起包含 segment_stage 與 parent_name（給 segment 軸分區展示用）。
    """
    with conn() as c:
        return pd.read_sql(
            """SELECT t.theme_id, t.theme_name,
                      t.classification_type AS type,
                      t.segment_stage, t.parent_theme_id,
                      pt.theme_name AS parent_name,
                      m.status, m.rising_day_n,
                      ROUND(m.pct_change_5d*100, 2) AS pct5d,
                      ROUND(m.rs_score, 2) AS rs
               FROM theme_membership tm
               JOIN themes t ON t.theme_id = tm.theme_id
               LEFT JOIN themes pt ON pt.theme_id = t.parent_theme_id
               LEFT JOIN theme_daily_metrics m
                 ON m.theme_id = t.theme_id
                 AND m.date = (SELECT MAX(date) FROM theme_daily_metrics
                               WHERE theme_id = t.theme_id)
               WHERE tm.stock_id=? AND tm.market='TW'
               ORDER BY m.pct_change_5d DESC NULLS LAST""",
            c, params=(stock_id,),
        )


@st.cache_data(ttl=60)
def get_stock_news(stock_id: str, limit: int = 30) -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql(
            """SELECT DISTINCT n.news_id, n.source, n.url, n.title, n.published_at
               FROM news n
               JOIN news_stock_link l ON l.news_id = n.news_id
               WHERE l.stock_id=? AND l.market='TW'
               ORDER BY n.published_at DESC
               LIMIT ?""",
            c, params=(stock_id, limit),
        )
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"])
    return df


# ───────── 個股漲跌幅查詢（給熱力圖下鑽用） ─────────
@st.cache_data(ttl=60)
def get_member_perf_on_date(on_date: str | None = None) -> pd.DataFrame:
    """查指定日期所有 TW 股票的 1/5/20 日漲跌幅 + 收盤價。

    用 SQL window function 一次撈完整序列，再用 pandas 算 pct_change，
    這樣不論 on_date 是哪一天都能正確算出當天的 N 日漲幅。
    """
    with conn() as c:
        if on_date is None:
            on_date = c.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
        df = pd.read_sql(
            """SELECT stock_id, date, close
               FROM daily_prices
               WHERE market='TW'
                 AND date <= ?
                 AND date >= date(?, '-60 days')
               ORDER BY stock_id, date""",
            c, params=(on_date, on_date),
        )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["stock_id", "date"])
    df["pct1d"] = df.groupby("stock_id")["close"].pct_change(1)
    df["pct5d"] = df.groupby("stock_id")["close"].pct_change(5)
    df["pct20d"] = df.groupby("stock_id")["close"].pct_change(20)
    # 取每檔 <= on_date 的最後一筆
    last = df.groupby("stock_id").tail(1).copy()
    return last[["stock_id", "close", "pct1d", "pct5d", "pct20d"]]
