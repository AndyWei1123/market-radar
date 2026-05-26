"""族群熱力圖（PRD §5.1）— 兩階段：先看族群層全局 → 選定族群再看內部個股"""
from __future__ import annotations

import time

import pandas as pd
import plotly.express as px
import streamlit as st

from _common import (
    GLOSSARY, STATUS_SHORT, TYPE_LABEL, color_scheme_picker, conn,
    csv_download_button, ensure_db, get_available_metric_dates,
    get_member_perf_on_date, get_theme_metrics,
)

st.set_page_config(page_title="族群熱力圖", layout="wide", page_icon="🔥")
ensure_db()
scheme = color_scheme_picker()

st.title("🔥 族群熱力圖")
st.caption(
    "上半部 = 族群全局熱度（51 個族群一覽）　|　下半部 = 選定族群後看內部個股的漲跌"
)

dates = get_available_metric_dates()
if not dates:
    st.warning("尚無族群指標資料")
    st.stop()

# ───────── 控制列 ─────────
# 播放狀態存在 session_state
if "play_idx" not in st.session_state:
    st.session_state.play_idx = len(dates) - 1
if "playing" not in st.session_state:
    st.session_state.playing = False

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    pick_date = st.select_slider(
        "📅 時間軸（拖曳查看歷史某日的族群熱度）",
        options=dates,
        value=dates[st.session_state.play_idx],
        key="date_slider",
    )
    # 同步當前 idx
    st.session_state.play_idx = dates.index(pick_date)

    # 播放控制
    pc1, pc2, pc3, pc4 = st.columns([1, 1, 1, 2])
    with pc1:
        if st.button("⏮ 起點", use_container_width=True):
            st.session_state.play_idx = 0
            st.session_state.playing = False
            st.rerun()
    with pc2:
        if st.session_state.playing:
            if st.button("⏸ 暫停", use_container_width=True, type="primary"):
                st.session_state.playing = False
                st.rerun()
        else:
            if st.button("▶ 播放", use_container_width=True, type="primary"):
                if st.session_state.play_idx >= len(dates) - 1:
                    st.session_state.play_idx = 0
                st.session_state.playing = True
                st.rerun()
    with pc3:
        if st.button("⏭ 終點", use_container_width=True):
            st.session_state.play_idx = len(dates) - 1
            st.session_state.playing = False
            st.rerun()
    with pc4:
        speed = st.select_slider(
            "速度", options=["慢", "中", "快"], value="中", label_visibility="collapsed",
        )
with c2:
    color_metric = st.selectbox(
        "顏色依據",
        ["pct_change_5d", "pct_change_1d", "pct_change_20d", "rs_score"],
        format_func=lambda x: {
            "pct_change_1d": "1 日漲跌幅",
            "pct_change_5d": "5 日漲跌幅",
            "pct_change_20d": "20 日漲跌幅",
            "rs_score": "RS 強度",
        }[x],
        index=0,
    )
with c3:
    status_filter = st.multiselect(
        "族群狀態", ["rising", "candidate", "idle", "falling"],
        default=["rising", "candidate", "idle", "falling"],
        format_func=lambda x: STATUS_SHORT[x],
        help=GLOSSARY["status"],
    )

# ───────── 撈族群層資料 ─────────
df = get_theme_metrics(on_date=pick_date)
df = df[df["status"].isin(status_filter)].copy()

if df.empty:
    st.info(f"📅 {pick_date} 沒有符合條件的族群資料")
    st.stop()

for col in ["pct_change_1d", "pct_change_5d", "pct_change_20d", "pct_above_ma20"]:
    df[col + "_pct"] = (df[col] * 100).round(2)
df["type_label"] = df["type"].map(TYPE_LABEL).fillna(df["type"])
df["狀態"] = df["status"].map(STATUS_SHORT)


# ───────────────────────────────────────────────
# 上半部：族群層熱力圖（Tab 切換分類軸）
# ───────────────────────────────────────────────
st.subheader("① 族群全局熱度")

tabs = st.tabs(["📊 全部", "🏛️ 官方產業", "🔬 產業鏈細項", "💡 概念股", "🔗 供應鏈"])
filters = [None, "sector", "segment", "theme", "chain"]


def render_theme_treemap(sub: pd.DataFrame, key: str, axis_type: str | None = None):
    color_col = color_metric + "_pct" if color_metric != "rs_score" else "rs_score"
    sub = sub.copy()
    sub["display_name"] = sub.apply(
        lambda r: f"{r['theme_name']}<br>{r['pct_change_5d_pct']:+.2f}%  "
                  f"Day{int(r['rising_day_n'])}",
        axis=1,
    )

    # ─── segment 軸：以「大產業 → 上中下游 → segment」三層 path 呈現 ───
    if axis_type == "segment":
        sub["parent_name"] = sub["parent_name"].fillna("（未分類大產業）")
        sub["segment_stage"] = sub["segment_stage"].fillna("").replace("", "未分上中下游")
        path_cols = [px.Constant("產業鏈細項"), "parent_name", "segment_stage", "display_name"]
    else:
        path_cols = [px.Constant("全部"), "type_label", "display_name"]

    fig = px.treemap(
        sub,
        path=path_cols,
        values="members",
        color=color_col,
        color_continuous_scale=scheme["scale"],
        color_continuous_midpoint=0 if color_metric != "rs_score" else 100,
        custom_data=["theme_id"],
        hover_data={
            "theme_name": True, "狀態": True, "rising_day_n": True,
            "pct_change_1d_pct": ":.2f", "pct_change_5d_pct": ":.2f",
            "pct_change_20d_pct": ":.2f", "pct_above_ma20_pct": ":.1f",
            "rs_score": ":.2f", "members": True,
            "display_name": False, "type_label": False,
            "parent_name": False, "segment_stage": False,
        },
    )
    fig.update_traces(textfont_size=13, textposition="middle center")
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10),
                      clickmode="event+select")

    # 點擊事件：選中族群 → 寫到 session_state，下方 selectbox 會自動切換
    event = st.plotly_chart(
        fig, use_container_width=True, key=key,
        on_select="rerun", selection_mode=("points",),
    )

    # 解析 event：treemap 的 point 通常含 label / customdata / pointNumber
    pts = []
    if event is not None:
        # event 可能是 dict-like 或 attribute-like
        sel = None
        try:
            sel = event.selection
        except AttributeError:
            try:
                sel = event["selection"]
            except (KeyError, TypeError):
                sel = None
        if sel is not None:
            try:
                pts = sel.get("points", []) if hasattr(sel, "get") else getattr(sel, "points", [])
            except Exception:  # noqa: BLE001
                pts = []
            pts = pts or []


    # 從 sub 建立 theme_name → theme_id 的映射，給 label 反查用
    name_to_id = dict(zip(sub["theme_name"], sub["theme_id"]))

    for pt in pts:
        if not isinstance(pt, dict):
            continue
        # 嘗試 customdata（最可靠）
        tid = None
        cd = pt.get("customdata")
        if cd:
            tid = cd[0] if isinstance(cd, (list, tuple)) else cd
        # 退而求其次：label「theme_name<br>+x% DayN」反查
        if not tid:
            label = str(pt.get("label", ""))
            theme_name = label.split("<br>")[0].strip() if label else ""
            tid = name_to_id.get(theme_name)
        # 跳過分類層（如「全部」、「官方產業」等不是族群本體）
        if tid and isinstance(tid, str) and tid in name_to_id.values():
            if st.session_state.get("picked_theme") != tid:
                st.session_state["picked_theme"] = tid
                st.rerun()
            break


for tab, ftype in zip(tabs, filters):
    with tab:
        sub = df if ftype is None else df[df["type"] == ftype]
        if sub.empty:
            st.info("此分類軸下沒有符合條件的族群")
            continue
        if ftype == "segment":
            st.caption("📍 路徑：大產業 → 上中下游 → 細項。點細項可下鑽看內部個股。")
        render_theme_treemap(sub, f"tm_{ftype}", axis_type=ftype)


# ───────────────────────────────────────────────
# 下半部：點上方族群 → 看內部個股
# ───────────────────────────────────────────────
st.divider()
st.subheader("內部個股漲跌")

# 預設選 5 日漲幅最大的族群；若上方點過族群，優先用點選的
sort_default = df.sort_values("pct_change_5d", ascending=False)
options = sort_default["theme_id"].tolist()

picked = st.session_state.get("picked_theme")
pick_theme = picked if (picked and picked in options) else options[0]

# 該族群成員 + 個股 perf
theme_row = df[df["theme_id"] == pick_theme].iloc[0]
with conn() as c:
    members = pd.read_sql(
        """SELECT tm.stock_id, s.name AS stock_name, s.sector
           FROM theme_membership tm
           LEFT JOIN stocks s ON s.stock_id=tm.stock_id AND s.market=tm.market
           WHERE tm.theme_id = ? AND tm.market='TW'""",
        c, params=(pick_theme,),
    )
perf = get_member_perf_on_date(pick_date)
if members.empty or perf.empty:
    st.info("此族群目前沒有成員股價資料")
else:
    inner = members.merge(perf, on="stock_id", how="left")
    inner["1日%"] = (inner["pct1d"] * 100).round(2)
    inner["5日%"] = (inner["pct5d"] * 100).round(2)
    inner["20日%"] = (inner["pct20d"] * 100).round(2)

    metric_map = {
        "pct_change_1d": "1日%",
        "pct_change_5d": "5日%",
        "pct_change_20d": "20日%",
        "rs_score": "5日%",  # rs 沒有個股版本，退化用 5 日%
    }
    color_col = metric_map[color_metric]
    inner_plot = inner.dropna(subset=[color_col]).copy()
    inner_plot["display"] = inner_plot["stock_id"].astype(str) + "<br>" + \
                            inner_plot["stock_name"].fillna("") + "<br>" + \
                            inner_plot[color_col].astype(str) + "%"

    if inner_plot.empty:
        st.info("此族群成員缺少價格資料，無法顯示個股熱力圖")
    else:
        st.caption(
            f"族群【{theme_row['theme_name']}】共 {len(members)} 檔成員，"
            f"有 {len(inner_plot)} 檔有價格資料。"
            f"族群層 5 日漲幅 {theme_row['pct_change_5d_pct']:+.2f}%，"
            f"狀態 {theme_row['狀態']}，起漲第 {int(theme_row['rising_day_n'])} 天。"
        )

        fig = px.treemap(
            inner_plot,
            path=[px.Constant(theme_row["theme_name"]), "display"],
            values=None,  # leaf 等大
            color=color_col,
            color_continuous_scale=scheme["scale"],
            color_continuous_midpoint=0,
            hover_data={
                "stock_id": True, "stock_name": True, "sector": True,
                "close": ":.2f",
                "1日%": ":.2f", "5日%": ":.2f", "20日%": ":.2f",
                "display": False,
            },
        )
        fig.update_traces(textfont_size=12, textposition="middle center")
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10),
                          coloraxis_colorbar=dict(title="個股 " + color_col))
        st.plotly_chart(fig, use_container_width=True, key="inner_treemap")

        # 個股表格（依顏色 metric 排序）
        st.markdown("##### 個股明細（依漲幅排序）")
        st.dataframe(
            inner.sort_values(color_col, ascending=False)
                 [["stock_id", "stock_name", "sector", "close",
                   "1日%", "5日%", "20日%"]]
                 .rename(columns={"stock_id": "代號", "stock_name": "名稱",
                                  "sector": "產業", "close": "收盤"}),
            use_container_width=True, hide_index=True, height=360,
        )


# ───────────────────────────────────────────────
# 族群明細表（整體）
# ───────────────────────────────────────────────
st.divider()
st.subheader(f"📅 {pick_date} 全族群明細（共 {len(df)} 個）")
csv_download_button(
    df[["theme_id", "theme_name", "type_label", "members", "狀態",
        "rising_day_n", "index_value", "pct_change_5d_pct",
        "pct_change_20d_pct", "rs_score"]],
    f"族群明細_{pick_date}.csv",
)
disp = df.sort_values(color_metric, ascending=False).copy()
disp["pct_above_ma20_pct"] = disp["pct_above_ma20_pct"].round(1)
disp["rs_score"] = disp["rs_score"].round(2)
disp["index_value"] = disp["index_value"].round(2)
st.dataframe(
    disp[["theme_name", "type_label", "members", "狀態", "rising_day_n",
          "index_value", "pct_change_1d_pct", "pct_change_5d_pct",
          "pct_change_20d_pct", "pct_above_ma20_pct", "rs_score", "theme_id"]]
        .rename(columns={
            "theme_name": "族群", "type_label": "軸", "members": "成員",
            "rising_day_n": "起漲Day", "index_value": "指數",
            "pct_change_1d_pct": "1日%", "pct_change_5d_pct": "5日%",
            "pct_change_20d_pct": "20日%", "pct_above_ma20_pct": "站上20MA%",
            "rs_score": "RS", "theme_id": "族群ID",
        }),
    use_container_width=True, hide_index=True, height=420,
)

with st.expander("ℹ️ 名詞解釋"):
    st.markdown("**狀態**" + "\n\n" + GLOSSARY["status"])
    st.markdown("---")
    st.markdown(GLOSSARY["rs"])
    st.markdown("---")
    st.markdown(GLOSSARY["rising_day"])
    st.markdown("---")
    st.markdown(GLOSSARY["pct_above_ma20"])

# ───────── 播放動畫驅動 ─────────
if st.session_state.playing and st.session_state.play_idx < len(dates) - 1:
    interval = {"慢": 1.5, "中": 0.7, "快": 0.3}[speed]
    time.sleep(interval)
    st.session_state.play_idx += 1
    st.rerun()
elif st.session_state.playing and st.session_state.play_idx >= len(dates) - 1:
    st.session_state.playing = False
