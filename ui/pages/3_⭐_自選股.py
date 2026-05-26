"""自選股追蹤頁（PRD §5.2）— 含 CSV 匯入 / 匯出"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from _common import (
    STATUS_SHORT, TYPE_LABEL, color_scheme_picker, conn, ensure_db,
    get_stock_list_full,
)

st.set_page_config(page_title="自選股", layout="wide", page_icon="⭐")
ensure_db()
color_scheme_picker()

st.title("⭐ 自選股追蹤")
st.caption("自選股 + 所屬族群 + 最新族群狀態。支援 CSV 匯入 / 匯出")

USER = "default"


# ───────── DB helpers ─────────
def load_watchlist() -> pd.DataFrame:
    sql = """
    SELECT w.stock_id, w.market, s.name, s.sector,
           w.group_name, w.note, w.added_at,
           (SELECT d.close FROM daily_prices d
            WHERE d.stock_id=w.stock_id AND d.market=w.market
            ORDER BY d.date DESC LIMIT 1) AS last_close,
           (SELECT d.date FROM daily_prices d
            WHERE d.stock_id=w.stock_id AND d.market=w.market
            ORDER BY d.date DESC LIMIT 1) AS last_date
    FROM watchlist w
    LEFT JOIN stocks s ON s.stock_id=w.stock_id AND s.market=w.market
    WHERE w.user_id = ?
    ORDER BY w.group_name, w.stock_id
    """
    with conn() as c:
        return pd.read_sql(sql, c, params=(USER,))


def load_stock_themes(stock_id: str) -> pd.DataFrame:
    """該股所屬族群 + 各族群最新狀態。"""
    sql = """
    SELECT t.theme_id, t.theme_name, t.classification_type AS type,
           m.status, m.rising_day_n,
           ROUND(m.pct_change_5d*100, 2) AS pct5d, ROUND(m.rs_score, 2) AS rs
    FROM theme_membership tm
    JOIN themes t ON t.theme_id = tm.theme_id
    LEFT JOIN theme_daily_metrics m
      ON m.theme_id = t.theme_id
      AND m.date = (SELECT MAX(date) FROM theme_daily_metrics WHERE theme_id=t.theme_id)
    WHERE tm.stock_id = ? AND tm.market = 'TW'
    ORDER BY m.pct_change_5d DESC NULLS LAST
    """
    with conn() as c:
        return pd.read_sql(sql, c, params=(stock_id,))


def add_stock(stock_id: str, group: str, note: str) -> bool:
    try:
        with conn() as c:
            c.execute(
                """INSERT INTO watchlist(user_id, stock_id, market, group_name, note)
                   VALUES (?, ?, 'TW', ?, ?)
                   ON CONFLICT(user_id, stock_id, market) DO UPDATE SET
                     group_name=excluded.group_name, note=excluded.note""",
                (USER, stock_id, group, note),
            )
            c.commit()
        return True
    except Exception as e:  # noqa: BLE001
        st.error(f"加入失敗：{e}")
        return False


def remove_stock(stock_id: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM watchlist WHERE user_id=? AND stock_id=? AND market='TW'",
                  (USER, stock_id))
        c.commit()


def import_csv(df: pd.DataFrame, mode: str) -> int:
    required = {"stock_id"}
    if not required.issubset(df.columns):
        st.error(f"CSV 缺少欄位：{required - set(df.columns)}")
        return 0
    df = df.copy()
    for col, default in [("group_name", "default"), ("note", ""), ("market", "TW")]:
        if col not in df.columns:
            df[col] = default
    df["stock_id"] = df["stock_id"].astype(str).str.strip()

    with conn() as c:
        if mode == "覆蓋":
            c.execute("DELETE FROM watchlist WHERE user_id=?", (USER,))
        rows = [(USER, r.stock_id, r.market or "TW", r.group_name or "default", r.note or "")
                for r in df.itertuples()]
        c.executemany(
            """INSERT INTO watchlist(user_id, stock_id, market, group_name, note)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, stock_id, market) DO UPDATE SET
                 group_name=excluded.group_name, note=excluded.note""",
            rows,
        )
        c.commit()
    return len(rows)


# ───────── 加入新股 ─────────
with st.expander("➕ 加入自選股", expanded=False):
    stocks = get_stock_list_full()
    if stocks.empty:
        st.warning("尚未有股票資料")
    else:
        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            options = [f"{r.stock_id}  {r.name or ''}" for r in stocks.itertuples()]
            pick = st.selectbox("選擇股票", options, key="add_stock_select")
            sid = pick.split()[0]
        with c2:
            grp = st.text_input("分組名稱", value="default", key="add_group")
        with c3:
            note = st.text_input("備註（選填）", key="add_note")
        if st.button("加入自選"):
            if add_stock(sid, grp, note):
                st.success(f"已加入 {pick} → {grp}")
                st.cache_data.clear()
                st.rerun()


# ───────── CSV 匯入 / 匯出 ─────────
with st.expander("📂 CSV 匯入 / 匯出"):
    cleft, cright = st.columns(2)
    with cleft:
        st.markdown("**📤 匯出**")
        wl = load_watchlist()
        if wl.empty:
            st.caption("目前無自選股")
        else:
            csv_bytes = wl[["stock_id", "market", "group_name", "note", "added_at"]].to_csv(
                index=False
            ).encode("utf-8-sig")
            st.download_button(
                f"⬇️ 下載 watchlist_{date.today().isoformat()}.csv",
                csv_bytes,
                file_name=f"watchlist_{date.today().isoformat()}.csv",
                mime="text/csv",
            )
    with cright:
        st.markdown("**📥 匯入**")
        st.caption("CSV 必須含 `stock_id` 欄位；可選 `group_name`、`note`、`market`")
        up = st.file_uploader("選 CSV", type=["csv"], key="csv_upload")
        mode = st.radio("匯入模式", ["合併", "覆蓋"], horizontal=True, key="import_mode")
        if up is not None:
            try:
                df_in = pd.read_csv(io.BytesIO(up.getvalue()))
                st.dataframe(df_in.head(10), use_container_width=True, hide_index=True)
                if st.button("✅ 確認匯入"):
                    n = import_csv(df_in, mode)
                    st.success(f"匯入完成，共處理 {n} 筆")
                    st.cache_data.clear()
                    st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"讀取失敗：{e}")


st.divider()

# ───────── 自選股清單 ─────────
wl = load_watchlist()
if wl.empty:
    st.info("目前沒有自選股。請從上方「➕ 加入自選股」開始。")
    st.stop()

groups = sorted(wl["group_name"].fillna("default").unique().tolist())
selected_groups = st.multiselect("顯示分組", groups, default=groups)
wl_show = wl[wl["group_name"].isin(selected_groups)]

st.subheader(f"自選股清單（{len(wl_show)} 檔）")

# 每檔展開顯示族群歸屬
for grp in selected_groups:
    sub = wl_show[wl_show["group_name"] == grp]
    if sub.empty:
        continue
    st.markdown(f"#### 📁 {grp}（{len(sub)} 檔）")
    for r in sub.itertuples():
        cols = st.columns([1, 2, 1, 1, 1, 1])
        cols[0].markdown(f"**{r.stock_id}**")
        cols[1].markdown(f"{r.name or '—'}  ／ {r.sector or '—'}")
        cols[2].markdown(f"`{r.last_close if r.last_close else '—'}`")
        cols[3].caption(str(r.last_date) if r.last_date else "—")
        cols[4].caption(r.note or "")
        if cols[5].button("🗑️", key=f"rm_{r.stock_id}_{grp}"):
            remove_stock(r.stock_id)
            st.cache_data.clear()
            st.rerun()

        with st.expander(f"📌 {r.stock_id} 所屬族群與最新狀態"):
            themes = load_stock_themes(r.stock_id)
            if themes.empty:
                st.caption("此股未對應任何族群")
            else:
                themes["狀態"] = themes["status"].map(STATUS_SHORT).fillna(themes["status"])
                themes["軸"] = themes["type"].map(TYPE_LABEL).fillna(themes["type"])
                st.dataframe(
                    themes[["theme_name", "軸", "狀態", "rising_day_n", "pct5d", "rs"]]
                        .rename(columns={"theme_name": "族群",
                                         "rising_day_n": "起漲Day",
                                         "pct5d": "5日%", "rs": "RS"}),
                    use_container_width=True, hide_index=True,
                )
