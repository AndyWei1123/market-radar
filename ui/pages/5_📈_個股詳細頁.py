"""個股詳細頁 — K 線 + 法人/融資 + 所屬族群 + 公司資料 + 相關新聞。

支援 URL 參數：?stock_id=2330
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from _common import (
    GLOSSARY, STATUS_SHORT, TYPE_LABEL, chart_rangebreaks, color_scheme_picker,
    ensure_db, get_company_profile, get_stock_inst_flow, get_stock_list_full,
    get_stock_margin, get_stock_news, get_stock_prices, get_stock_themes,
)

st.set_page_config(page_title="個股詳細頁", layout="wide", page_icon="📈")
ensure_db()
scheme = color_scheme_picker()

# ───────── 選股 ─────────
qp = st.query_params
default_id = qp.get("stock_id", "2330")

stocks = get_stock_list_full()
if stocks.empty:
    st.error("尚無股票資料")
    st.stop()

# 嘗試用 default_id 找預設
opts = stocks["stock_id"].tolist()
try:
    default_idx = opts.index(default_id)
except ValueError:
    default_idx = 0

pick = st.selectbox(
    "🔍 選擇股票（或從其他頁面點代號跳過來）",
    options=opts,
    index=default_idx,
    format_func=lambda x: (
        f"{x}  "
        f"{stocks.loc[stocks.stock_id==x, 'name'].iloc[0] or ''}  "
        f"({stocks.loc[stocks.stock_id==x, 'sector'].iloc[0] or ''})"
    ),
)
# 同步到 URL
if pick != qp.get("stock_id"):
    st.query_params["stock_id"] = pick

profile = get_company_profile(pick)
stock_name = (
    profile["full_name"] if profile is not None and profile["full_name"]
    else stocks.loc[stocks.stock_id == pick, "name"].iloc[0]
)
stock_short = stocks.loc[stocks.stock_id == pick, "name"].iloc[0]

# ───────── 標題與 KPI ─────────
st.title(f"📈 {pick}　{stock_short}")
st.caption(stock_name if stock_name != stock_short else "")

prices = get_stock_prices(pick, days=365)
if prices.empty:
    st.warning("無價格資料")
    st.stop()

last = prices.iloc[-1]
prev = prices.iloc[-2] if len(prices) > 1 else last
delta = last["close"] - prev["close"]
pct = delta / prev["close"] * 100 if prev["close"] else 0

market_cap = None
if profile is not None and pd.notna(profile.get("shares_outstanding")):
    market_cap = float(last["close"]) * float(profile["shares_outstanding"])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("收盤", f"{last['close']:.2f}", f"{delta:+.2f} ({pct:+.2f}%)")
c2.metric("成交量", f"{int(last['volume']):,}")
c3.metric("資料日期", str(last["date"].date()))
if market_cap:
    if market_cap >= 1e12:
        cap_str = f"{market_cap/1e12:.2f} 兆"
    elif market_cap >= 1e8:
        cap_str = f"{market_cap/1e8:.0f} 億"
    else:
        cap_str = f"{market_cap:,.0f}"
    c4.metric("市值（推估）", cap_str,
              help="收盤 × 已發行普通股數")
else:
    c4.metric("市值（推估）", "—")
if profile is not None and pd.notna(profile.get("capital")):
    c5.metric("股本", f"{profile['capital']/1e8:.1f} 億")
else:
    c5.metric("股本", "—")

st.divider()

# ───────── K 線圖 ─────────
st.subheader("K 線走勢")
ranges = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
r1, r2 = st.columns([3, 1])
with r2:
    range_pick = st.radio("區間", list(ranges.keys()), index=2, horizontal=True)
days = ranges[range_pick]
plot_df = prices.tail(int(days * 5 / 7)).copy()  # 約 days 個交易日

fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.75, 0.25], vertical_spacing=0.03,
    subplot_titles=("價格 + 均線", "成交量"),
)

# 蠟燭：依用戶顏色喜好設定漲跌顏色
up_color = scheme["up"]
down_color = scheme["down"]
fig.add_trace(go.Candlestick(
    x=plot_df["date"], open=plot_df["open"], high=plot_df["high"],
    low=plot_df["low"], close=plot_df["close"],
    increasing_line_color=up_color, increasing_fillcolor=up_color,
    decreasing_line_color=down_color, decreasing_fillcolor=down_color,
    name=pick, showlegend=False,
), row=1, col=1)
for ma, color in [("ma5", "#ff9800"), ("ma20", "#2196f3"), ("ma60", "#9c27b0")]:
    fig.add_trace(go.Scatter(
        x=plot_df["date"], y=plot_df[ma], mode="lines",
        name=ma.upper(), line=dict(width=1, color=color),
    ), row=1, col=1)

# 成交量
colors_vol = [
    up_color if c >= o else down_color
    for c, o in zip(plot_df["close"], plot_df["open"])
]
fig.add_trace(go.Bar(
    x=plot_df["date"], y=plot_df["volume"], name="成交量",
    marker_color=colors_vol, showlegend=False,
), row=2, col=1)

fig.update_layout(
    height=560, margin=dict(l=10, r=10, t=30, b=10),
    xaxis_rangeslider_visible=False, hovermode="x unified",
)
fig.update_xaxes(rangebreaks=chart_rangebreaks(plot_df["date"]))
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ───────── 法人 + 融資 ─────────
st.subheader("法人買賣超與融資融券（近 60 個交易日）")
inst = get_stock_inst_flow(pick, days=90)
margin_df = get_stock_margin(pick, days=90)

ic1, ic2 = st.columns(2)
with ic1:
    if inst.empty:
        st.info("無法人資料")
    else:
        fig_i = go.Figure()
        # 法人合計（柱狀，依顏色喜好）
        bar_colors = [up_color if v >= 0 else down_color for v in inst["total_net"]]
        fig_i.add_trace(go.Bar(
            x=inst["date"], y=inst["total_net"] / 1000,  # 千股
            name="三大法人合計", marker_color=bar_colors,
        ))
        fig_i.add_trace(go.Scatter(
            x=inst["date"], y=(inst["foreign_net"] / 1000).cumsum(),
            mode="lines", name="外資累計", yaxis="y2",
            line=dict(color="#2196f3", width=1),
        ))
        fig_i.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            title="三大法人買賣超（千股）",
            yaxis=dict(title="日合計（千股）"),
            yaxis2=dict(title="外資累計", overlaying="y", side="right"),
            hovermode="x unified",
            legend=dict(orientation="h", y=1.1),
        )
        fig_i.update_xaxes(rangebreaks=chart_rangebreaks(inst["date"]))
        st.plotly_chart(fig_i, use_container_width=True)

with ic2:
    if margin_df.empty:
        st.info("無融資融券資料")
    else:
        fig_m = go.Figure()
        fig_m.add_trace(go.Scatter(
            x=margin_df["date"], y=margin_df["margin_bal"],
            mode="lines+markers", name="融資餘額（張）",
            line=dict(color="#ff9800", width=2),
        ))
        fig_m.add_trace(go.Scatter(
            x=margin_df["date"], y=margin_df["short_bal"],
            mode="lines+markers", name="融券餘額（張）",
            line=dict(color="#9c27b0", width=2), yaxis="y2",
        ))
        fig_m.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            title="融資 / 融券餘額",
            yaxis=dict(title="融資（張）"),
            yaxis2=dict(title="融券（張）", overlaying="y", side="right"),
            hovermode="x unified",
            legend=dict(orientation="h", y=1.1),
        )
        fig_m.update_xaxes(rangebreaks=chart_rangebreaks(margin_df["date"]))
        st.plotly_chart(fig_m, use_container_width=True)

st.divider()

# ───────── 所屬族群 ─────────
st.subheader("🏷️ 所屬族群", help=GLOSSARY["type"])
themes = get_stock_themes(pick)
if themes.empty:
    st.info("此股未對應任何族群")
else:
    themes["軸"] = themes["type"].map(TYPE_LABEL).fillna(themes["type"])
    themes["狀態"] = themes["status"].map(STATUS_SHORT).fillna("—")

    def _render_chip(r) -> str:
        badge = r.狀態 or "—"
        pct = f"{r.pct5d:+.2f}%" if pd.notna(r.pct5d) else "—"
        rs = f"RS {r.rs:.1f}" if pd.notna(r.rs) else ""
        stage_tag = ""
        if r.type == "segment" and r.segment_stage:
            stage_tag = f"<span style='color:#4caf50;font-size:11px;'>　[{r.segment_stage}]</span>"
        return (
            f"<div style='padding:8px 10px;margin:2px 0;"
            f"border:1px solid #444;border-radius:8px;'>"
            f"<b><a href='/族群詳細頁?theme_id={r.theme_id}' "
            f"target='_self'>{r.theme_name}</a></b>{stage_tag}<br>"
            f"<span style='color:#888;font-size:12px;'>{badge} ・ {pct} ・ {rs}</span>"
            f"</div>"
        )

    # 四軸分區顯示（segment 軸再依 parent_sector 分群）
    for ax in ["sector", "segment", "theme", "chain"]:
        sub = themes[themes["type"] == ax]
        if sub.empty:
            continue
        st.markdown(f"**{TYPE_LABEL[ax]}**（{len(sub)}）")

        if ax == "segment":
            # 依大產業分組（同一檔股票可能在多個大產業下都有 segment）
            for parent_name, group in sub.groupby("parent_name", dropna=False):
                pn = parent_name if pd.notna(parent_name) else "（未分類）"
                st.markdown(f"<span style='color:#888;font-size:13px;'>└─ {pn}</span>",
                            unsafe_allow_html=True)
                cols = st.columns(min(4, max(1, len(group))))
                for i, r in enumerate(group.itertuples()):
                    with cols[i % len(cols)]:
                        st.markdown(_render_chip(r), unsafe_allow_html=True)
        else:
            cols = st.columns(min(4, max(1, len(sub))))
            for i, r in enumerate(sub.itertuples()):
                with cols[i % len(cols)]:
                    st.markdown(_render_chip(r), unsafe_allow_html=True)

st.divider()

# ───────── 公司基本資料 ─────────
st.subheader("🏢 公司基本資料")
if profile is None:
    st.info(f"此股 ({pick}) 暫無公司資料")
else:
    # 介紹 + 業務範圍
    if profile["main_business"]:
        st.markdown(f"**主要經營業務**")
        st.markdown(
            f"<div style='background:#1e1e1e;color:#ffffff;padding:12px;"
            f"border-radius:6px;white-space:pre-wrap;line-height:1.7;"
            f"font-size:14px;'>{profile['main_business']}</div>",
            unsafe_allow_html=True,
        )
        st.write("")

    # 兩欄基本資料
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("##### 📌 基本資訊")
        rows = [
            ("公司全名", profile.get("full_name")),
            ("英文簡稱", profile.get("short_name_en")),
            ("英文全名", profile.get("full_name_en")),
            ("產業類別", profile.get("industry")),
            ("成立日期", profile.get("established")),
            ("上市日期", profile.get("listing_date")),
            ("公開發行日期", profile.get("public_offering_date")),
            ("統一編號", profile.get("tax_id")),
            ("會計年度", profile.get("fiscal_year_month") or "曆年制"),
        ]
        for k, v in rows:
            if v:
                st.markdown(f"- **{k}**：{v}")
    with bc2:
        st.markdown("##### 💰 股本與股利")
        cap = profile.get("capital")
        shares = profile.get("shares_outstanding")
        rows = [
            ("實收資本額", f"{cap/1e8:.2f} 億元" if cap else None),
            ("已發行普通股數", f"{shares:,} 股" if shares else None),
            ("每股面額", f"{profile.get('par_value')} 元"
             if profile.get('par_value') else None),
            ("特別股", "有" if profile.get("has_preferred") else "無"),
            ("公司債", "有" if profile.get("has_corporate_bonds") else "無"),
            ("股利分派頻率", profile.get("dividend_frequency")),
            ("股利決議層級", profile.get("dividend_decision_lv")),
        ]
        for k, v in rows:
            if v:
                st.markdown(f"- **{k}**：{v}")

    # 聯絡資訊
    st.markdown("##### 📞 聯絡資訊")
    cc1, cc2 = st.columns(2)
    with cc1:
        if profile["address"]:
            st.markdown(f"- **地址**：{profile['address']}")
        if profile["phone"]:
            st.markdown(f"- **總機**：{profile['phone']}")
        if profile["fax"]:
            st.markdown(f"- **傳真**：{profile['fax']}")
        if profile["email"]:
            st.markdown(f"- **Email**：{profile['email']}")
    with cc2:
        if profile["website"]:
            st.markdown(f"- **公司網址**：[{profile['website']}]({profile['website']})")
        if profile["governance_url"]:
            st.markdown(f"- **公司治理專區**：[連結]({profile['governance_url']})")
        if profile["stakeholder_url"]:
            st.markdown(f"- **利害關係人專區**：[連結]({profile['stakeholder_url']})")

    # 人事 / 投資人關係
    pc1, pc2 = st.columns(2)
    with pc1:
        st.markdown("##### 👥 經營團隊")
        rows = [
            ("董事長", profile.get("chairman")),
            ("總經理", profile.get("ceo")),
            ("發言人", profile.get("spokesperson")),
            ("發言人職稱", profile.get("spokesperson_title")),
            ("代理發言人", profile.get("deputy_spokesperson")),
        ]
        for k, v in rows:
            if v:
                st.markdown(f"- **{k}**：{v}")
    with pc2:
        st.markdown("##### 💼 投資人關係 / 會計師")
        rows = [
            ("IR 聯絡人", profile.get("ir_contact")),
            ("IR 職稱", profile.get("ir_title")),
            ("IR 電話", profile.get("ir_phone")),
            ("IR Email", profile.get("ir_email")),
            ("簽證會計師事務所", profile.get("audit_firm")),
            ("簽證會計師", " / ".join(
                x for x in [profile.get("auditor_1"), profile.get("auditor_2")] if x
            ) or None),
        ]
        for k, v in rows:
            if v:
                st.markdown(f"- **{k}**：{v}")

st.divider()

# ───────── 相關新聞 ─────────
st.subheader("📰 相關新聞")
news = get_stock_news(pick, limit=30)
if news.empty:
    st.caption("尚無相關新聞")
else:
    for r in news.itertuples():
        ts = r.published_at.strftime("%m-%d %H:%M") if pd.notna(r.published_at) else "—"
        st.markdown(f"`{ts}` **[{r.source}]** [{r.title}]({r.url})")
