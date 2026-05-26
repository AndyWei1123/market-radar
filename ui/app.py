"""Market Radar 主頁：大盤 / 資金流向總覽（W3 §5.3）。"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import date as _date

from _common import (
    GLOSSARY, STATUS_COLORS_BASE, STATUS_LABEL, STATUS_SHORT, TYPE_LABEL,
    chart_rangebreaks, color_scheme_picker, csv_download_button, ensure_db,
    get_benchmark, get_inst_market_total, get_inst_top_stocks, get_overview,
    get_theme_metrics, stock_detail_url,
)

st.set_page_config(page_title="市場雷達", layout="wide", page_icon="📈")
ensure_db()
scheme = color_scheme_picker()

st.title("📈 市場雷達 — 全球族群起漲偵測")
st.caption("左側選單切換頁面　|　🎨 漲跌顏色可在左側設定中切換")

ov = get_overview()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("股票檔數", f"{ov['stocks_total']:,}", help="DB 中現有的台股（上市+上櫃）總數")
c2.metric("已抓日線", f"{ov['ingested']:,}", help="實際已下載 OHLCV 的股票檔數")
c3.metric("資料區間", f"{ov['date_min']} → {ov['date_max']}" if ov['date_min'] else "—")
c4.metric("族群數", f"{ov['themes_n']:,}", help=GLOSSARY["type"])
c5.metric("指標日數", f"{ov['metrics_dates']:,}", help="有完整族群指標的交易日數")

if ov["ingested"] < 200:
    st.info(f"目前只有 {ov['ingested']} 檔股票的日線資料")

st.divider()

# ───────── TAIEX 走勢 ─────────
bench = get_benchmark("TWII")
if bench.empty:
    st.warning("尚未抓加權指數資料")
else:
    last = bench.iloc[-1]
    prev = bench.iloc[-2] if len(bench) > 1 else last
    delta = last["close"] - prev["close"]
    pct = delta / prev["close"] * 100

    cleft, cright = st.columns([1, 3])
    with cleft:
        st.subheader("加權指數 TAIEX")
        st.metric(
            "最新收盤", f"{last['close']:,.2f}",
            f"{delta:+.2f}  ({pct:+.2f}%)",
        )
        st.caption(f"日期：{last['date'].date()}")
        st.caption(f"成交量：{int(last['volume']):,}")
    with cright:
        fig = go.Figure()
        # 大盤線：依用戶喜好上色（漲日紅 / 跌日綠，等下也可以用單色）
        fig.add_trace(go.Scatter(
            x=bench["date"], y=bench["close"], name="TAIEX",
            line=dict(color=scheme["up"], width=2),
        ))
        ma20 = bench["close"].rolling(20).mean()
        ma60 = bench["close"].rolling(60).mean()
        fig.add_trace(go.Scatter(x=bench["date"], y=ma20, name="MA20",
                                 line=dict(color="#2196f3", width=1, dash="dash")))
        fig.add_trace(go.Scatter(x=bench["date"], y=ma60, name="MA60",
                                 line=dict(color="#9c27b0", width=1, dash="dot")))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          hovermode="x unified", showlegend=True)
        fig.update_xaxes(rangebreaks=chart_rangebreaks(bench["date"]))
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# ───────── 族群狀態分布 ─────────
st.subheader("族群狀態總覽（最新日）", help=GLOSSARY["status"])
metrics = get_theme_metrics()
if metrics.empty:
    st.warning("尚無族群指標資料")
else:
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric("有指標族群", len(metrics))
    sc2.metric("🟢 起漲確認", int((metrics["status"] == "rising").sum()),
               help="達成全部 5 條件（最強訊號）")
    sc3.metric("🟡 起漲候選", int((metrics["status"] == "candidate").sum()),
               help="C1+C2 已達成，準備發動")
    sc4.metric("⚪ 觀察中", int((metrics["status"] == "idle").sum()),
               help="勉強站上 20MA，動能不足")
    sc5.metric("🔴 走弱", int((metrics["status"] == "falling").sum()),
               help="跌破 20MA")

    # 三軸狀態堆疊
    by_type = metrics.groupby(["type", "status"]).size().unstack(fill_value=0)
    for s in ("rising", "candidate", "idle", "falling"):
        if s not in by_type.columns:
            by_type[s] = 0
    by_type = by_type[["rising", "candidate", "idle", "falling"]]
    by_type.index = [TYPE_LABEL.get(i, i) for i in by_type.index]
    by_type.columns = [STATUS_SHORT[c] for c in by_type.columns]

    fig2 = go.Figure()
    status_color_map = {STATUS_SHORT[k]: v for k, v in STATUS_COLORS_BASE.items()}
    for status in by_type.columns:
        fig2.add_trace(go.Bar(
            name=status, x=by_type.index, y=by_type[status],
            marker_color=status_color_map[status],
        ))
    fig2.update_layout(
        barmode="stack", height=280,
        margin=dict(l=10, r=10, t=20, b=10),
        title="各分類軸的族群狀態分布",
    )
    st.plotly_chart(fig2, use_container_width=True)

    # 中文欄位先建好（CSV 與下方表格共用）
    metrics["狀態"] = metrics["status"].map(STATUS_SHORT)
    metrics["軸"] = metrics["type"].map(TYPE_LABEL)

    # 全族群明細 CSV
    csv_download_button(
        metrics.assign(
            五日漲幅=(metrics["pct_change_5d"] * 100).round(2),
            RS=metrics["rs_score"].round(2),
        )[["theme_name", "軸", "members", "狀態", "rising_day_n",
           "五日漲幅", "RS"]],
        f"族群清單_{_date.today().isoformat()}.csv",
        "⬇️ 下載全族群明細",
    )

    # 強勢族群 Top 10
    cleft, cright = st.columns(2)
    with cleft:
        st.subheader("🚀 起漲族群 Top 10（依 5 日漲幅）",
                     help=GLOSSARY["pct_change_5d"])
        top = metrics.sort_values("pct_change_5d", ascending=False).head(10).copy()
        top["5日%"] = (top["pct_change_5d"] * 100).round(2)
        top["RS"] = top["rs_score"].round(2)
        st.dataframe(
            top[["theme_name", "軸", "狀態", "rising_day_n", "5日%", "RS", "members"]]
              .rename(columns={"theme_name": "族群", "rising_day_n": "起漲Day",
                               "members": "成員數"}),
            use_container_width=True, hide_index=True,
        )
    with cright:
        st.subheader("📉 弱勢族群 Top 10")
        bot = metrics.sort_values("pct_change_5d", ascending=True).head(10).copy()
        bot["5日%"] = (bot["pct_change_5d"] * 100).round(2)
        bot["RS"] = bot["rs_score"].round(2)
        st.dataframe(
            bot[["theme_name", "軸", "狀態", "5日%", "RS", "members"]]
              .rename(columns={"theme_name": "族群", "members": "成員數"}),
            use_container_width=True, hide_index=True,
        )

st.divider()

# ───────── 三大法人 ─────────
st.subheader("💰 三大法人買賣超",
             help="外資、投信、自營商當日合計買賣超股數（正=買超，負=賣超）")
inst_total = get_inst_market_total()
if inst_total.empty:
    st.info("尚無法人資料")
else:
    row = inst_total.iloc[0]
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric("日期", str(row["date"]))

    def fmt(n: float) -> str:
        n = float(n)
        if abs(n) >= 1e8:
            return f"{n/1e8:+.2f} 億股"
        if abs(n) >= 1e4:
            return f"{n/1e4:+.1f} 萬股"
        return f"{n:+.0f} 股"

    ic2.metric("外資", fmt(row["foreign_net"]), help="外國機構投資人")
    ic3.metric("投信", fmt(row["trust_net"]), help="國內證券投資信託基金")
    ic4.metric("自營商", fmt(row["dealer_net"]), help="證券商自有資金")

    link_col_cfg = {
        "詳細": st.column_config.LinkColumn("個股頁", display_text="📈"),
    }
    # 法人 Top 50 CSV
    top50_buy = get_inst_top_stocks("buy", 50).copy()
    top50_sell = get_inst_top_stocks("sell", 50).copy()
    inst_full = pd.concat([top50_buy.assign(類型="買超"), top50_sell.assign(類型="賣超")])
    csv_download_button(
        inst_full[["類型", "stock_id", "name", "sector",
                   "total_net", "foreign_net", "trust_net", "dealer_net"]],
        f"法人買賣超Top50_{row['date']}.csv",
        "⬇️ 下載法人 Top 50",
    )

    bcol, scol = st.columns(2)
    with bcol:
        st.markdown("##### 🟢 法人合計買超 Top 10")
        top_buy = get_inst_top_stocks("buy", 10).copy()
        top_buy["合計"] = top_buy["total_net"].apply(fmt)
        top_buy["詳細"] = top_buy["stock_id"].apply(stock_detail_url)
        st.dataframe(
            top_buy[["stock_id", "name", "sector", "合計", "詳細"]]
                .rename(columns={"stock_id": "代號", "name": "名稱", "sector": "產業"}),
            use_container_width=True, hide_index=True,
            column_config=link_col_cfg,
        )
    with scol:
        st.markdown("##### 🔴 法人合計賣超 Top 10")
        top_sell = get_inst_top_stocks("sell", 10).copy()
        top_sell["合計"] = top_sell["total_net"].apply(fmt)
        top_sell["詳細"] = top_sell["stock_id"].apply(stock_detail_url)
        st.dataframe(
            top_sell[["stock_id", "name", "sector", "合計", "詳細"]]
                .rename(columns={"stock_id": "代號", "name": "名稱", "sector": "產業"}),
            use_container_width=True, hide_index=True,
            column_config=link_col_cfg,
        )

st.caption("💡 融資融券、北向資金、新聞情緒等將在 Phase 2 視覺化。")
