"""分類體系同步到 DB（v0.3）。

四軸統一管理：sector / segment / theme / chain
每個 axis 都會：
  1. upsert 到 themes 表（帶 taxonomy_source 標記來源）
  2. 重建 theme_membership 表的對應關係

依賴的 yaml 檔由 config/taxonomy/<market>/ 提供：
  - sectors.yaml  自動產生（scripts/build_tw_taxonomy.py）
  - segments.yaml 自動產生
  - themes.yaml   手動維護
  - chains.yaml   手動維護
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from config import load_taxonomy
from db.init_db import get_conn

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MISSING_LOG = ROOT / "logs" / "missing_stocks.log"
MISSING_LOG.parent.mkdir(parents=True, exist_ok=True)


# ───────────────────────── helpers ─────────────────────────

def _existing_tw_stocks(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT stock_id FROM stocks WHERE market = 'TW'")
    return {r[0] for r in cur.fetchall()}


def _upsert_theme(conn: sqlite3.Connection, *, theme_id: str, name: str,
                  ctype: str, scope: str, source: str,
                  taxonomy_source: str,
                  parent_theme_id: str | None = None,
                  segment_stage: str | None = None,
                  external_code: str | None = None,
                  display_order: int = 0,
                  description: str = "") -> None:
    conn.execute(
        """INSERT INTO themes(
              theme_id, theme_name, classification_type, market_scope,
              description, source, taxonomy_source, parent_theme_id,
              segment_stage, external_code, display_order, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(theme_id) DO UPDATE SET
             theme_name = excluded.theme_name,
             classification_type = excluded.classification_type,
             market_scope = excluded.market_scope,
             description = excluded.description,
             source = excluded.source,
             taxonomy_source = excluded.taxonomy_source,
             parent_theme_id = excluded.parent_theme_id,
             segment_stage = excluded.segment_stage,
             external_code = excluded.external_code,
             display_order = excluded.display_order,
             updated_at = CURRENT_TIMESTAMP""",
        (theme_id, name, ctype, scope, description, source,
         taxonomy_source, parent_theme_id, segment_stage, external_code,
         display_order),
    )


def _replace_membership(conn: sqlite3.Connection, theme_id: str,
                        members: list[tuple[str, str]]) -> int:
    """members = [(stock_id, market), ...]"""
    conn.execute("DELETE FROM theme_membership WHERE theme_id = ?", (theme_id,))
    if not members:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO theme_membership(theme_id, stock_id, market, weight) "
        "VALUES (?, ?, ?, 1.0)",
        [(theme_id, sid, mkt) for sid, mkt in members],
    )
    return len(members)


def _filter_existing(members_by_market: dict, existing_tw: set[str],
                     theme_id: str, missing_buf: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    tw = members_by_market.get("TW", []) or []
    for sid in tw:
        sid = str(sid).strip()
        if sid in existing_tw:
            out.append((sid, "TW"))
        else:
            missing_buf.append(f"{theme_id}\tTW\t{sid}")
    for mkt in ("US", "JP", "HK"):
        for sid in members_by_market.get(mkt, []) or []:
            out.append((str(sid).strip(), mkt))
    return out


def _delete_stale(conn: sqlite3.Connection, taxonomy_source: str,
                  keep_ids: set[str]) -> int:
    """刪除某來源下不再出現的舊紀錄（避免 yaml 移除後 DB 殘留）。"""
    cur = conn.execute(
        "SELECT theme_id FROM themes WHERE taxonomy_source = ?", (taxonomy_source,)
    )
    stale = [r[0] for r in cur.fetchall() if r[0] not in keep_ids]
    if stale:
        ph = ",".join("?" * len(stale))
        conn.execute(f"DELETE FROM theme_membership WHERE theme_id IN ({ph})", stale)
        conn.execute(f"DELETE FROM themes WHERE theme_id IN ({ph})", stale)
    return len(stale)


# ───────────────────────── sync 各軸 ─────────────────────────

def sync_sectors(conn: sqlite3.Connection, market: str = "tw") -> int:
    """同步 TPEx 47 大產業（從 sectors.yaml）。"""
    items = load_taxonomy(market).get("sectors", [])
    if not items:
        log.info("[sectors] sectors.yaml 不存在或為空，跳過")
        return 0

    existing = _existing_tw_stocks(conn)
    missing: list[str] = []
    keep_ids: set[str] = set()
    n = 0
    for idx, it in enumerate(items):
        code = it["code"]
        theme_id = f"sector_tw_{code}"
        keep_ids.add(theme_id)
        _upsert_theme(
            conn,
            theme_id=theme_id,
            name=it["name"],
            ctype="sector",
            scope="TW",
            source="tpex",
            taxonomy_source="tpex_sector",
            external_code=code,
            display_order=idx,
            description=it.get("policy_summary", ""),
        )
        members = _filter_existing(
            {"TW": it.get("members", [])}, existing, theme_id, missing
        )
        _replace_membership(conn, theme_id, members)
        n += 1
    removed = _delete_stale(conn, "tpex_sector", keep_ids)
    conn.commit()
    if missing:
        with MISSING_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(missing) + "\n")
    log.info(f"[sectors] synced {n} TPEx sectors, removed {removed} stale, "
             f"{len(missing)} missing TW stocks")
    return n


def sync_segments(conn: sqlite3.Connection, market: str = "tw") -> int:
    """同步 TPEx 上中下游細項（從 segments.yaml）。"""
    items = load_taxonomy(market).get("segments", [])
    if not items:
        log.info("[segments] segments.yaml 不存在或為空，跳過")
        return 0

    existing = _existing_tw_stocks(conn)
    missing: list[str] = []
    keep_ids: set[str] = set()
    n = 0
    for idx, it in enumerate(items):
        code = it["code"]
        theme_id = f"segment_tw_{code}"
        keep_ids.add(theme_id)
        _upsert_theme(
            conn,
            theme_id=theme_id,
            name=it["name"],
            ctype="segment",
            scope="TW",
            source="tpex",
            taxonomy_source="tpex_segment",
            parent_theme_id=f"sector_tw_{it['parent_sector']}" if it.get("parent_sector") else None,
            segment_stage=it.get("stage") or None,
            external_code=code,
            display_order=idx,
        )
        members = _filter_existing(
            {"TW": it.get("members", [])}, existing, theme_id, missing
        )
        _replace_membership(conn, theme_id, members)
        n += 1
    removed = _delete_stale(conn, "tpex_segment", keep_ids)
    conn.commit()
    if missing:
        with MISSING_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(missing) + "\n")
    log.info(f"[segments] synced {n} TPEx segments, removed {removed} stale, "
             f"{len(missing)} missing TW stocks")
    return n


def sync_themes(conn: sqlite3.Connection, market: str = "tw") -> int:
    """同步手動概念股（從 themes.yaml）。"""
    items = load_taxonomy(market).get("themes", [])
    if not items:
        return 0

    existing = _existing_tw_stocks(conn)
    missing: list[str] = []
    keep_ids: set[str] = set()
    n = 0
    for idx, t in enumerate(items):
        theme_id = f"theme_{t['id']}"
        keep_ids.add(theme_id)
        _upsert_theme(
            conn,
            theme_id=theme_id,
            name=t["name"],
            ctype="theme",
            scope=t.get("market_scope", "TW"),
            source=t.get("source", "manual"),
            taxonomy_source="manual_theme",
            display_order=idx,
        )
        members = _filter_existing(t.get("members", {}), existing, theme_id, missing)
        _replace_membership(conn, theme_id, members)
        n += 1
    removed = _delete_stale(conn, "manual_theme", keep_ids)
    conn.commit()
    if missing:
        with MISSING_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(missing) + "\n")
    log.info(f"[themes] synced {n} themes, removed {removed} stale, "
             f"{len(missing)} missing TW stocks")
    return n


def sync_chains(conn: sqlite3.Connection, market: str = "tw") -> int:
    """同步手動供應鏈（從 chains.yaml）。"""
    items = load_taxonomy(market).get("chains", [])
    if not items:
        return 0

    existing = _existing_tw_stocks(conn)
    missing: list[str] = []
    keep_ids: set[str] = set()
    n = 0
    for idx, c in enumerate(items):
        theme_id = f"chain_{c['id']}"
        keep_ids.add(theme_id)
        _upsert_theme(
            conn,
            theme_id=theme_id,
            name=c["name"],
            ctype="chain",
            scope=c.get("market_scope", "GLOBAL"),
            source="manual",
            taxonomy_source="manual_chain",
            display_order=idx,
        )
        members = _filter_existing(c.get("members", {}), existing, theme_id, missing)
        _replace_membership(conn, theme_id, members)
        n += 1
    removed = _delete_stale(conn, "manual_chain", keep_ids)
    conn.commit()
    if missing:
        with MISSING_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(missing) + "\n")
    log.info(f"[chains] synced {n} chains, removed {removed} stale, "
             f"{len(missing)} missing TW stocks")
    return n


def cleanup_legacy_twse_listing_sectors(conn: sqlite3.Connection) -> int:
    """刪除舊 v0.2 的 sector_tw_<中文> 紀錄（taxonomy_source IS NULL 或 'official'）。

    新版 sector 一律用 sector_tw_<TPEx代碼>；舊命名會被當作 stale 殘留。
    """
    cur = conn.execute(
        """SELECT theme_id FROM themes
           WHERE classification_type='sector'
             AND (taxonomy_source IS NULL OR taxonomy_source = 'official' OR taxonomy_source = 'twse_listing')
             AND theme_id NOT LIKE 'sector_tw_____'  -- 4-char TPEx 代碼以外"""
    )
    # 上面的 like 條件用 4 個底線太脆弱，改用 Python 過濾
    cur = conn.execute(
        """SELECT theme_id FROM themes
           WHERE classification_type='sector'
             AND (taxonomy_source IS NULL OR taxonomy_source IN ('official','twse_listing'))"""
    )
    stale = [r[0] for r in cur.fetchall()]
    if stale:
        ph = ",".join("?" * len(stale))
        conn.execute(f"DELETE FROM theme_membership WHERE theme_id IN ({ph})", stale)
        conn.execute(f"DELETE FROM themes WHERE theme_id IN ({ph})", stale)
        conn.commit()
    log.info(f"[cleanup] removed {len(stale)} legacy sector themes")
    return len(stale)


# ───────────────────────── public API ─────────────────────────

def sync_all(market: str = "tw") -> dict[str, int]:
    """一次同步四個軸。"""
    with get_conn() as conn:
        # 先清掉舊版命名，避免新舊 sector 兩套並存
        cleanup_legacy_twse_listing_sectors(conn)
        return {
            "sectors":  sync_sectors(conn, market),
            "segments": sync_segments(conn, market),
            "themes":   sync_themes(conn, market),
            "chains":   sync_chains(conn, market),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(sync_all())
