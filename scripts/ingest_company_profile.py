"""公司基本資料抓取入口（MOPS t05st03）。

抓取範圍模式：
  - 預設子集：watchlist + rising/candidate 族群的所有成員（< 1 分鐘）
  - --all：全市場（約 20–30 分鐘）
  - --stock 2330：單檔
  - --industry 半導體業：單一產業

用法：
    python -m scripts.ingest_company_profile                  # 子集（推薦）
    python -m scripts.ingest_company_profile --all            # 全市場
    python -m scripts.ingest_company_profile --stock 2330
    python -m scripts.ingest_company_profile --industry 半導體業
    python -m scripts.ingest_company_profile --force          # 忽略 30 天快取，全部重抓

預設增量：updated_at < 30 天前的才重抓。
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from rich.logging import RichHandler

from connectors.tw.company_profile import CompanyProfile, fetch_one
from db.init_db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "ingest_company_profile.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO, format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False),
              logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("ingest_company_profile")


PROFILE_COLUMNS = [
    "stock_id", "market", "full_name", "short_name_en", "full_name_en",
    "industry", "foreign_country", "address", "address_en", "phone",
    "fax", "email", "website", "main_business", "established",
    "listing_date", "otc_listing_date", "emerging_date", "public_offering_date",
    "tax_id", "par_value", "capital", "shares_outstanding", "shares_private",
    "preferred_shares", "has_preferred", "has_corporate_bonds",
    "dividend_frequency", "dividend_decision_lv", "chairman", "ceo",
    "spokesperson", "spokesperson_title", "spokesperson_phone",
    "deputy_spokesperson", "ir_contact", "ir_title", "ir_phone", "ir_email",
    "stakeholder_url", "governance_url", "transfer_agent",
    "transfer_agent_phone", "transfer_agent_addr", "audit_firm",
    "auditor_1", "auditor_2", "former_name", "former_short_name",
    "fiscal_year_month", "report_type", "raw_html",
]


def upsert(conn: sqlite3.Connection, p: CompanyProfile) -> None:
    d = asdict(p)
    cols = PROFILE_COLUMNS
    placeholders = ",".join("?" * len(cols))
    set_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("stock_id", "market"))
    sql = (
        f"INSERT INTO company_profile({','.join(cols)}, updated_at) "
        f"VALUES ({placeholders}, CURRENT_TIMESTAMP) "
        f"ON CONFLICT(stock_id, market) DO UPDATE SET "
        f"{set_clause}, updated_at=CURRENT_TIMESTAMP"
    )
    conn.execute(sql, tuple(d.get(c) for c in cols))
    conn.commit()


def get_subset_stocks(conn: sqlite3.Connection, top_n: int = 10) -> list[str]:
    """子集 = watchlist + top N 強勢「概念股 / 供應鏈」族群的成員
    （排除官方產業，因為單一 sector 通常上百檔太大）。"""
    cur = conn.execute(f"""
        SELECT DISTINCT stock_id FROM (
            SELECT stock_id FROM watchlist WHERE market='TW'
            UNION
            SELECT tm.stock_id FROM theme_membership tm
            WHERE tm.market='TW' AND tm.theme_id IN (
                SELECT m.theme_id FROM theme_daily_metrics m
                JOIN themes t ON t.theme_id = m.theme_id
                WHERE m.date = (SELECT MAX(date) FROM theme_daily_metrics)
                  AND t.classification_type IN ('theme', 'chain')
                ORDER BY m.pct_change_5d DESC NULLS LAST
                LIMIT {top_n}
            )
        )
    """)
    return [r[0] for r in cur.fetchall()]


def get_stocks_to_fetch(conn: sqlite3.Connection, mode: str,
                       single_id: str | None, industry: str | None,
                       skip_recent: bool) -> list[str]:
    if single_id:
        return [single_id]
    if industry:
        cur = conn.execute(
            "SELECT stock_id FROM stocks WHERE market='TW' AND sector = ?",
            (industry,),
        )
        candidates = [r[0] for r in cur.fetchall()]
    elif mode == "all":
        cur = conn.execute("SELECT stock_id FROM stocks WHERE market='TW' ORDER BY stock_id")
        candidates = [r[0] for r in cur.fetchall()]
    else:  # subset
        candidates = get_subset_stocks(conn)

    if skip_recent:
        # 過濾掉 30 天內已抓過的
        existing = set()
        cur = conn.execute(
            "SELECT stock_id FROM company_profile "
            "WHERE market='TW' AND updated_at > datetime('now', '-30 days')"
        )
        existing = {r[0] for r in cur.fetchall()}
        candidates = [s for s in candidates if s not in existing]
    return candidates


def run(mode: str, single_id: str | None, industry: str | None,
        sleep_sec: float, force: bool) -> None:
    init_db(reset=False)
    with get_conn() as conn:
        targets = get_stocks_to_fetch(
            conn, mode, single_id, industry, skip_recent=not force,
        )

    if not targets:
        log.info("沒有需要抓取的股票（可能都在 30 天快取內，用 --force 強制重抓）")
        return

    log.info(f"📋 共 {len(targets)} 檔股票要抓")
    ok = fail = 0
    for i, sid in enumerate(targets, 1):
        try:
            p = fetch_one(sid)
            if p:
                with get_conn() as conn:
                    upsert(conn, p)
                ok += 1
                if i % 20 == 0 or i == len(targets):
                    log.info(f"  {i}/{len(targets)}  ✅ {sid} {p.full_name or '?'}")
            else:
                fail += 1
                log.warning(f"  {i}/{len(targets)}  ⚠️ {sid} 無資料")
        except Exception as e:  # noqa: BLE001
            fail += 1
            log.warning(f"  {i}/{len(targets)}  ❌ {sid} {e}")
        time.sleep(sleep_sec)

    log.info(f"✅ done. success={ok}, fail={fail}")


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--all", dest="mode_all", action="store_true",
                   help="全市場（約 20–30 分鐘）")
    g.add_argument("--stock", help="只抓單一股票代號")
    g.add_argument("--industry", help="只抓特定產業（如：半導體業）")
    p.add_argument("--sleep", type=float, default=0.6,
                   help="每檔間隔秒數（避免被 MOPS 擋）")
    p.add_argument("--force", action="store_true",
                   help="忽略 30 天快取，強制重抓")
    args = p.parse_args()

    mode = "all" if args.mode_all else "subset"
    run(mode=mode, single_id=args.stock, industry=args.industry,
        sleep_sec=args.sleep, force=args.force)


if __name__ == "__main__":
    main()
