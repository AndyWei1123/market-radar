"""跨市場連動表種子腳本（W4 PRD §6 預留）。

從 chains.yaml 把每條供應鏈的 anchor（美股 / 日股 / 韓股）→ 成員（台股）
建立 cross_market_mapping 種子資料，type='supply_chain'。

用法：
    python -m scripts.seed_cross_market

未來 Phase 2 的 AI 新聞共現分析會自動再補 type='news_cooccurrence' 的連結。
"""
from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler

from config import chains as load_chains
from db.init_db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "seed_cross_market.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO, format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False),
              logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("seed_cross_market")


def run() -> None:
    init_db(reset=False)
    cfg = load_chains()
    rows: list[tuple] = []
    for c in cfg.get("chains", []):
        anchor = c.get("anchor")
        if not anchor:
            continue
        a_market = anchor["market"]
        a_id = str(anchor["stock_id"]).strip()
        if not a_id or a_id.endswith("_UNLISTED"):
            continue
        evidence = c["name"]
        for mkt in ("TW", "US", "JP", "HK", "KR"):
            for sid in c.get("members", {}).get(mkt, []) or []:
                sid = str(sid).strip()
                # 不連結自己
                if mkt == a_market and sid == a_id:
                    continue
                rows.append((
                    a_id, a_market, sid, mkt,
                    "supply_chain", 1.0, evidence,
                ))

    with get_conn() as conn:
        conn.execute("DELETE FROM cross_market_mapping WHERE mapping_type='supply_chain'")
        conn.executemany(
            """INSERT INTO cross_market_mapping
               (source_stock_id, source_market,
                target_stock_id, target_market,
                mapping_type, confidence, evidence)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()

    log.info(f"✅ seeded {len(rows)} supply_chain mappings")


if __name__ == "__main__":
    run()
