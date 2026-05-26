"""族群 RS 強度排行榜（PRD §5.4）"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from _common import (
    GLOSSARY, STATUS_COLORS_BASE, STATUS_SHORT, TYPE_LABEL,
    color_scheme_picker, conn, csv_download_button, ensure_db,
    get_available_metric_dates, get_theme_metrics,
)

st.set_page_config(page_title="RS 強度排行", layout="wide", page_icon="📊")
ensure_db()
color_scheme_picker()

st.title("📊 族群 RS 強度排行榜")
st.caption("RS = 族群相對加權指數的強弱比；RS 動能 = 近 20 日 RS 變化")

with st.expander("ℹ️ RS 是什麼？"):
    st.markdown(GLOSSARY["rs"])
    st.markdown("---")
    st.markdown(GLOSSARY["rs_momentum"])

dates = get_available_metric_dates()
if not dates:
    st.warning("尚無族群指標資料")
    st.stop()

c1, c2 = st.columns([1, 3])
with c1:
    type_filter = st.multiselect(
        "分類軸", ["sector", "segment", "theme", "chain"],
        default=["sector", "theme", "chain"],  # segment 數量多，預設不開
        format_func=lambda x: TYPE_LABEL[x],
        help=GLOSSARY["type"] + "\n\n*產業鏈細項 (segment) 共 ~400 個，預設不勾選；勾選後可看 IC設計 / IC封測 / ABF載板等子層級*",
    )
with c2:
    lookback_n = st.slider(
        "RS 排名變化比較天數", 1, 20, 5,
        help="比較今日 RS 排名與 N 個交易日前的差異",
    )

today = dates[-1]
past_idx = max(0, len(dates) - 1 - lookback_n)
past_date = dates[past_idx]

df_today = get_theme_metrics(on_date=today)
df_past = get_theme_metrics(on_date=past_date)

df_today = df_today[df_today["type"].isin(type_filter)].copy()
df_past = df_past[df_past["type"].isin(type_filter)].copy()

if df_today.empty:
    st.info("沒有符合條件的族群")
    st.stop()

df_today["rs_rank"] = df_today["rs_score"].rank(ascending=False, method="min")
df_past["rs_rank_past"] = df_past["rs_score"].rank(ascending=False, method="min")

merged = df_today.merge(
    df_past[["theme_id", "rs_rank_past", "rs_score"]].rename(
        columns={"rs_score": "rs_past"}),
    on="theme_id", how="left",
)
merged["rank_delta"] = merged["rs_rank_past"] - merged["rs_rank"]
merged["rs_delta"] = merged["rs_score"] - merged["rs_past"]
merged = merged.sort_values("rs_score", ascending=False)
merged["軸"] = merged["type"].map(TYPE_LABEL)
merged["狀態"] = merged["status"].map(STATUS_SHORT)

sc1, sc2, sc3 = st.columns(3)
sc1.metric("族群總數", len(merged))
sc2.metric("RS > 100（強過大盤）", int((merged["rs_score"] > 100).sum()),
           help="RS > 100 表示該族群表現超越加權指數")
sc3.metric("起漲中（起漲確認 + 候選）",
           int(merged["status"].isin(["rising", "candidate"]).sum()))

st.divider()

disp = merged.copy()
disp["RS"] = disp["rs_score"].round(2)
disp["RS過去"] = disp["rs_past"].round(2)
disp["RSΔ"] = disp["rs_delta"].round(2)
disp["排名"] = disp["rs_rank"].astype(int)
disp["排名Δ"] = disp["rank_delta"].fillna(0).astype(int)
disp["5日%"] = (disp["pct_change_5d"] * 100).round(2)
disp["RS動能%"] = (disp["rs_momentum"] * 100).round(2)

def arrow(n: int) -> str:
    if n > 0: return f"↑{n}"
    if n < 0: return f"↓{abs(n)}"
    return "—"

disp["排名變化"] = disp["排名Δ"].apply(arrow)
disp["上中下游"] = disp["segment_stage"].fillna("—")
disp["所屬大產業"] = disp["parent_name"].fillna("—")

# 若使用者勾了 segment，多顯示 stage / parent 欄
show_seg_cols = "segment" in type_filter
cols_to_show = ["排名", "排名變化", "theme_name", "軸"]
if show_seg_cols:
    cols_to_show += ["所屬大產業", "上中下游"]
cols_to_show += ["狀態", "rising_day_n", "RS", "RSΔ", "RS動能%", "5日%",
                 "members", "theme_id"]

st.subheader(f"排行榜（vs {lookback_n} 日前 {past_date}）")
csv_download_button(
    disp[cols_to_show],
    f"RS排行_{today}.csv", "⬇️ 下載排行榜",
)
st.dataframe(
    disp[cols_to_show]
        .rename(columns={"theme_name": "族群", "rising_day_n": "起漲Day",
                         "members": "成員", "theme_id": "族群ID"}),
    use_container_width=True, hide_index=True, height=520,
)

st.divider()

st.subheader("🌀 族群輪動象限（RS 強度 × RS 動能）",
             help="右上=領漲、左上=改善、左下=落後、右下=轉弱")
st.caption("觀察資金正從哪裡輪到哪裡 — 點數較大代表族群成員多")

plot_df = merged.dropna(subset=["rs_score", "rs_momentum"]).copy()
plot_df["rs_momentum_pct"] = plot_df["rs_momentum"] * 100

# 軌跡選項
trail_c1, trail_c2, trail_c3 = st.columns([1, 1, 2])
with trail_c1:
    show_trail = st.checkbox("顯示軌跡", value=False,
                             help="連接近 N 週的點，看資金輪動方向")
with trail_c2:
    trail_weeks = st.slider("軌跡週數", 2, 12, 6, disabled=not show_trail)
with trail_c3:
    # 軌跡只給「強勢」/「轉強」族群會比較好看，否則太亂
    if show_trail:
        focus_pick = st.multiselect(
            "為哪些族群畫軌跡（建議 ≤ 5 個，否則太亂）",
            options=plot_df["theme_id"].tolist(),
            default=plot_df.sort_values("rs_score", ascending=False)
                          .head(5)["theme_id"].tolist(),
            format_func=lambda x: plot_df.loc[plot_df.theme_id==x, "theme_name"].iloc[0],
            max_selections=10,
        )
    else:
        focus_pick = []

fig = go.Figure()
for status, color in STATUS_COLORS_BASE.items():
    sub = plot_df[plot_df["status"] == status]
    if sub.empty:
        continue
    fig.add_trace(go.Scatter(
        x=sub["rs_score"], y=sub["rs_momentum_pct"],
        mode="markers+text", text=sub["theme_name"],
        textposition="top center",
        name=STATUS_SHORT[status],
        marker=dict(size=10 + sub["members"].clip(0, 30), color=color,
                    opacity=0.7, line=dict(width=1, color="white")),
        hovertemplate=("<b>%{text}</b><br>RS=%{x:.2f}<br>"
                       "RS動能=%{y:.2f}%<extra></extra>"),
    ))

# ───── 軌跡 ─────
if show_trail and focus_pick:
    days_back = trail_weeks * 5  # 5 個交易日 / 週
    # 用 last N 個 dates 等距取樣 7 個點，避免太密
    sample_n = min(7, days_back)
    trail_dates = [dates[max(0, len(dates) - 1 - int(days_back * i / (sample_n - 1)))]
                   for i in range(sample_n)] if sample_n > 1 else [dates[-1]]
    trail_dates = sorted(set(trail_dates))
    # 取每個 focus theme 在這幾個日期的 RS / RS momentum
    placeholders = ",".join("?" * len(focus_pick))
    date_ph = ",".join("?" * len(trail_dates))
    with conn() as cn:
        trail = pd.read_sql(
            f"""SELECT m.theme_id, t.theme_name, m.date,
                       m.rs_score, m.rs_momentum
                FROM theme_daily_metrics m
                JOIN themes t ON t.theme_id = m.theme_id
                WHERE m.theme_id IN ({placeholders})
                  AND m.date IN ({date_ph})
                ORDER BY m.theme_id, m.date""",
            cn, params=(*focus_pick, *trail_dates),
        )
    if not trail.empty:
        trail["rs_momentum_pct"] = trail["rs_momentum"] * 100
        # 為每個族群畫一條線
        colormap = ["#e91e63", "#9c27b0", "#3f51b5", "#03a9f4", "#009688",
                    "#ff9800", "#795548", "#607d8b", "#f44336", "#4caf50"]
        for i, (tid, g) in enumerate(trail.groupby("theme_id")):
            color = colormap[i % len(colormap)]
            g = g.sort_values("date")
            fig.add_trace(go.Scatter(
                x=g["rs_score"], y=g["rs_momentum_pct"],
                mode="lines+markers",
                name=f"📍 {g['theme_name'].iloc[0]} 軌跡",
                line=dict(color=color, width=1, dash="dot"),
                marker=dict(size=5, color=color),
                hovertemplate="<b>%{text}</b><br>%{customdata}<br>"
                              "RS=%{x:.2f}<br>動能=%{y:.2f}%<extra></extra>",
                text=g["theme_name"],
                customdata=g["date"],
                showlegend=True,
                legendgroup=f"trail_{tid}",
            ))
            # 最後一個點加箭頭表示「目前位置」
            last_row = g.iloc[-1]
            fig.add_annotation(
                x=last_row["rs_score"], y=last_row["rs_momentum_pct"],
                ax=g.iloc[-2]["rs_score"] if len(g) > 1 else last_row["rs_score"],
                ay=g.iloc[-2]["rs_momentum_pct"] if len(g) > 1 else last_row["rs_momentum_pct"],
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowcolor=color, arrowwidth=1.5,
            )

fig.add_hline(y=0, line_color="#999", line_width=1)
fig.add_vline(x=plot_df["rs_score"].median(), line_color="#999",
              line_dash="dash", line_width=1)
fig.update_layout(
    height=500, margin=dict(l=10, r=10, t=30, b=10),
    xaxis_title="RS 強度", yaxis_title="RS 動能（%）",
    hovermode="closest",
)
# 在四角加象限說明標註
fig.add_annotation(xref="paper", yref="paper", x=0.98, y=0.98,
                   text="<b>領漲</b>（強且加強）",
                   showarrow=False, font=dict(color="#4caf50", size=11),
                   xanchor="right", yanchor="top")
fig.add_annotation(xref="paper", yref="paper", x=0.02, y=0.98,
                   text="<b>改善</b>（弱但動能轉強）",
                   showarrow=False, font=dict(color="#2196f3", size=11),
                   xanchor="left", yanchor="top")
fig.add_annotation(xref="paper", yref="paper", x=0.02, y=0.02,
                   text="<b>落後</b>",
                   showarrow=False, font=dict(color="#9e9e9e", size=11),
                   xanchor="left", yanchor="bottom")
fig.add_annotation(xref="paper", yref="paper", x=0.98, y=0.02,
                   text="<b>轉弱</b>（仍強但動能下滑）",
                   showarrow=False, font=dict(color="#f44336", size=11),
                   xanchor="right", yanchor="bottom")
st.plotly_chart(fig, use_container_width=True)
