"""W2 一鍵跑：

  1. 抓 / 更新大盤指數 TWII（作為 RS 基準）
  2. 同步族群定義（sector + theme + chain）到 DB
  3. 計算每個族群的每日指數 + 起漲指標 + 狀態
  4. 寫入 theme_daily_metrics

用法：
    python -m scripts.compute_themes              # 完整跑
    python -m scripts.compute_themes --no-index   # 跳過大盤指數抓取
    python -m scripts.compute_themes --days 365   # 指定回溯天數
"""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta
from pathlib import Path

from rich.logging import RichHandler

from compute import breakout, taxonomy_loader
from config import settings
from connectors.tw import market_index
from connectors.tw.calendar import effective_trade_date
from db.init_db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "compute_themes.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True, show_path=False),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("compute_themes")


def fetch_and_store_index(days: int) -> int:
    end = effective_trade_date()
    start = end - timedelta(days=days)
    bars = market_index.fetch_index("TWII", start, end)
    if not bars:
        log.warning("no TWII data fetched")
        return 0
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO market_index(index_id, market, date, close, volume)
               VALUES (?,?,?,?,?)
               ON CONFLICT(index_id, date) DO UPDATE SET
                 close=excluded.close, volume=excluded.volume""",
            [(b.index_id, b.market, b.date.isoformat(), b.close, b.volume) for b in bars],
        )
        conn.commit()
    return len(bars)


def run(skip_index: bool, days: int) -> None:
    init_db(reset=False)

    if not skip_index:
        log.info("[1/3] fetching TWII benchmark...")
        n = fetch_and_store_index(days)
        log.info(f"  → upserted {n} TWII bars")
    else:
        log.info("[1/3] (skipped) TWII fetch")

    log.info("[2/3] syncing taxonomy (sectors / segments / themes / chains)...")
    res = taxonomy_loader.sync_all()
    log.info(f"  → {res}")

    log.info("[3/3] computing theme metrics + breakout status...")
    with get_conn() as conn:
        totals = breakout.compute_all(conn)
    log.info(f"  → {totals}")
    log.info("✅ done.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-index", action="store_true", help="跳過大盤指數抓取")
    p.add_argument("--days", type=int,
                   default=settings()["ingestion"]["initial_lookback_days"])
    args = p.parse_args()
    run(skip_index=args.no_index, days=args.days)


if __name__ == "__main__":
    main()
