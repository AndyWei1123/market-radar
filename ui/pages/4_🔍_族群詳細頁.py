"""族群詳細頁（PRD §5.5）— 走勢 + 5 條件 + 成員"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _common import (
    GLOSSARY, STATUS_SHORT, TYPE_LABEL, chart_rangebreaks, color_scheme_picker,
    conn, csv_download_button, ensure_db, get_benchmark, get_news_for_stocks,
    get_theme_history, get_theme_members, stock_detail_url,
)

st.set_page_config(page_title="族群詳細頁", layout="wide", page_icon="🔍")
ensure_db()
scheme = color_scheme_picker()

st.title("🔍 族群詳細頁")

# 從 query param 讀（之後可從熱力圖點擊跳過來）
qp = st.query_params
default_id = qp.get("theme_id", "")

with conn() as c:
    theme_options = pd.read_sql(
        """SELECT t.theme_id, t.theme_name, t.classification_type AS type,
                  (SELECT COUNT(*) FROM theme_membership tm WHERE tm.theme_id=t.theme_id) AS members
           FROM themes t ORDER BY t.classification_type, t.theme_name""",
        c,
    )

if theme_options.empty:
    st.warning("尚無族群定義")
    st.stop()

idx_default = 0
if default_id:
    try:
        idx_default = theme_options["theme_id"].tolist().index(default_id)
    except ValueError:
        pass

pick = st.selectbox(
    "選擇族群",
    options=theme_options["theme_id"].tolist(),
    index=idx_default,
    format_func=lambda x: (
        f"[{TYPE_LABEL.get(theme_options.loc[theme_options.theme_id==x, 'type'].iloc[0], '?')}] "
        f"{theme_options.loc[theme_options.theme_id==x, 'theme_name'].iloc[0]} "
        f"({theme_options.loc[theme_options.theme_id==x, 'members'].iloc[0]} 檔)"
    ),
)

hist = get_theme_history(pick)
members = get_theme_members(pick)

if hist.empty:
    st.warning("此族群尚無指標資料")
    st.write("**成員清單：**")
    st.dataframe(members, use_container_width=True, hide_index=True)
    st.stop()

# ───────── 頂部 KPI ─────────
last = hist.iloc[-1]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("最新狀態", STATUS_SHORT.get(last["status"], last["status"]),
          help=GLOSSARY["status"])
c2.metric("起漲第幾天", int(last["rising_day_n"]), help=GLOSSARY["rising_day"])
c3.metric("族群指數", f"{last['index_value']:.2f}",
          f"{last['pct_change_1d']*100:+.2f}%" if pd.notna(last['pct_change_1d']) else "",
          help=GLOSSARY["index_value"])
c4.metric("5 日漲幅",
          f"{last['pct_change_5d']*100:+.2f}%" if pd.notna(last['pct_change_5d']) else "—",
          help=GLOSSARY["pct_change_5d"])
c5.metric("RS", f"{last['rs_score']:.2f}" if pd.notna(last['rs_score']) else "—",
          f"{last['rs_momentum']*100:+.2f}%" if pd.notna(last['rs_momentum']) else "",
          help=GLOSSARY["rs"])

st.divider()

# ───────── 走勢圖 ─────────
bench = get_benchmark("TWII")
if not bench.empty:
    bench = bench.copy()
    bench["norm"] = bench["close"] / bench["close"].iloc[0] * 100

fig = go.Figure()
fig.add_trace(go.Scatter(x=hist["date"], y=hist["index_value"], name="族群指數",
                         line=dict(color=scheme["up"], width=2)))
fig.add_trace(go.Scatter(x=hist["date"], y=hist["ma20"], name="MA20",
                         line=dict(color="#2196f3", width=1, dash="dash")))
fig.add_trace(go.Scatter(x=hist["date"], y=hist["ma60"], name="MA60",
                         line=dict(color="#9c27b0", width=1, dash="dot")))
if not bench.empty:
    fig.add_trace(go.Scatter(x=bench["date"], y=bench["norm"], name="TWII (normalized)",
                             line=dict(color="#888", width=1)))
rising = hist[hist["status"] == "rising"]
if not rising.empty:
    fig.add_trace(go.Scatter(
        x=rising["date"], y=rising["index_value"], mode="markers",
        name="🟢 起漲確認",
        marker=dict(color="#4caf50", size=8, symbol="triangle-up"),
    ))
cand = hist[hist["status"] == "candidate"]
if not cand.empty:
    fig.add_trace(go.Scatter(
        x=cand["date"], y=cand["index_value"], mode="markers",
        name="🟡 起漲候選",
        marker=dict(color="#ffc107", size=6),
    ))
fig.update_layout(height=480, margin=dict(l=10, r=10, t=30, b=10),
                  hovermode="x unified")
fig.update_xaxes(rangebreaks=chart_rangebreaks(hist["date"]))
st.plotly_chart(fig, use_container_width=True)

# ───────── 5 條件 ─────────
st.subheader("起漲 5 條件達成狀況", help=GLOSSARY["status"])
cc = st.columns(5)
prev_ma20 = hist["ma20"].iloc[-6] if len(hist) > 5 else None
c1_ok = pd.notna(last["ma20"]) and last["index_value"] > last["ma20"]
c2_ok = prev_ma20 is not None and pd.notna(prev_ma20) and last["ma20"] > prev_ma20
c4_ok = pd.notna(last["pct_above_ma20"]) and last["pct_above_ma20"] >= 0.5
c5_ok = pd.notna(last["pct_change_5d"]) and last["pct_change_5d"] >= 0.03
cc[0].metric("C1 站上 20MA", "✅" if c1_ok else "❌",
             help=GLOSSARY["ma20"])
cc[1].metric("C2 20MA 上揚", "✅" if c2_ok else "❌",
             help=GLOSSARY["ma20_slope"])
cc[2].metric("C3 RS 創 20 日新高",
             "（看上方走勢圖）", help=GLOSSARY["rs"])
cc[3].metric("C4 成分股 >50% 站上 20MA",
             f"{last['pct_above_ma20']*100:.0f}%" if pd.notna(last['pct_above_ma20']) else "—",
             "✅" if c4_ok else "❌",
             help=GLOSSARY["pct_above_ma20"])
cc[4].metric("C5 5 日漲幅 ≥3%",
             f"{last['pct_change_5d']*100:+.2f}%" if pd.notna(last['pct_change_5d']) else "—",
             "✅" if c5_ok else "❌",
             help=GLOSSARY["pct_change_5d"])

st.divider()

# ───────── 成員清單 + 個股最新價 ─────────
st.subheader(f"族群成員（{len(members)} 檔）")
if members.empty:
    st.caption("此族群無成員資料")
else:
    with conn() as c:
        prices = pd.read_sql(
            f"""SELECT d.stock_id, d.close,
                       (d.close / LAG(d.close, 5) OVER (PARTITION BY d.stock_id ORDER BY d.date) - 1) AS pct5d
                FROM daily_prices d
                WHERE d.market='TW'
                  AND d.stock_id IN ({','.join('?' * len(members))})
                  AND d.date >= date((SELECT MAX(date) FROM daily_prices), '-10 days')""",
            c, params=tuple(members["stock_id"]),
        )
    # 取每檔最新一筆
    if not prices.empty:
        latest = prices.dropna(subset=["pct5d"]).groupby("stock_id").tail(1)
        out = members.merge(latest, on="stock_id", how="left")
        out["5日%"] = (out["pct5d"] * 100).round(2)
        out["詳細"] = out["stock_id"].apply(stock_detail_url)
        out = out.sort_values("5日%", ascending=False)
        csv_download_button(
            out[["stock_id", "name", "sector", "close", "5日%"]],
            f"族群成員_{pick}.csv", "⬇️ 下載成員清單",
        )
        st.caption("👉 點「詳細」欄的箭頭可跳轉到該股的個股詳細頁")
        st.dataframe(
            out[["stock_id", "name", "sector", "close", "5日%", "詳細"]]
                .rename(columns={"stock_id": "代號", "name": "名稱",
                                 "sector": "產業", "close": "收盤"}),
            use_container_width=True, hide_index=True, height=400,
            column_config={
                "詳細": st.column_config.LinkColumn(
                    "個股頁", display_text="📈 看明細",
                ),
            },
        )
    else:
        st.dataframe(members, use_container_width=True, hide_index=True)

st.divider()

# ───────── 相關新聞時間軸 ─────────
st.subheader("📰 相關新聞（依族群成員自動歸類）")
news = get_news_for_stocks(tuple(members["stock_id"].tolist()), limit=50)
if news.empty:
    st.caption("尚無相關新聞")
else:
    src_filter = st.multiselect(
        "新聞來源", sorted(news["source"].unique().tolist()),
        default=sorted(news["source"].unique().tolist()),
    )
    nf = news[news["source"].isin(src_filter)].copy()
    nf["published_at"] = pd.to_datetime(nf["published_at"])
    nf = nf.sort_values("published_at", ascending=False)
    for r in nf.itertuples():
        ts = r.published_at.strftime("%m-%d %H:%M") if pd.notna(r.published_at) else "—"
        st.markdown(
            f"`{ts}` **[{r.source}]** "
            f"[{r.title}]({r.url})"
        )
