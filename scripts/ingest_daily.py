"""每日資料抓取入口（MVP）。

執行流程：
  1. 確認 effective_trade_date（盤中時自動回退到昨日）
  2. 抓全市場股票清單 → upsert stocks 表
  3. 為每檔股票抓近 N 年日線 → upsert daily_prices 表
  4. 寫入 ingestion_log

用法：
    python -m scripts.ingest_daily                  # 初次：抓近 365 天
    python -m scripts.ingest_daily --days 90        # 自訂回溯天數
    python -m scripts.ingest_daily --incremental    # 只補齊缺失日（每日跑）
    python -m scripts.ingest_daily --limit 20       # 測試用：只跑前 20 檔
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from rich.logging import RichHandler

from config import settings
from connectors.tw import daily_prices, market_index, stock_list
from connectors.tw.calendar import effective_trade_date
from db.init_db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "ingest_daily.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True, show_path=False),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("ingest_daily")


# ─────────────────────────────────────────────────────────
# DB 操作
# ─────────────────────────────────────────────────────────
def upsert_stocks(conn: sqlite3.Connection, rows: list[stock_list.StockInfo]) -> int:
    sql = """
        INSERT INTO stocks (stock_id, market, name, sector, listing_date, is_active, updated_at)
        VALUES (?, 'TW', ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(stock_id, market) DO UPDATE SET
            name = excluded.name,
            sector = excluded.sector,
            listing_date = excluded.listing_date,
            is_active = 1,
            updated_at = CURRENT_TIMESTAMP
    """
    cur = conn.executemany(
        sql, [(s.stock_id, s.name, s.sector, s.listing_date) for s in rows]
    )
    conn.commit()
    return cur.rowcount


def upsert_prices(conn: sqlite3.Connection, bars: list[daily_prices.PriceBar]) -> int:
    if not bars:
        return 0
    sql = """
        INSERT INTO daily_prices (stock_id, market, date, open, high, low, close, volume, adj_close)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_id, market, date) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low  = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            adj_close = excluded.adj_close
    """
    rows = [
        (b.stock_id, b.market, b.date.isoformat(),
         b.open, b.high, b.low, b.close, b.volume, b.adj_close)
        for b in bars
    ]
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def last_price_date(conn: sqlite3.Connection, stock_id: str) -> date | None:
    cur = conn.execute(
        "SELECT MAX(date) AS d FROM daily_prices WHERE stock_id = ? AND market = 'TW'",
        (stock_id,),
    )
    row = cur.fetchone()
    if not row or not row["d"]:
        return None
    return date.fromisoformat(row["d"])


def log_ingestion(conn: sqlite3.Connection, job: str, status: str, rows: int, msg: str):
    conn.execute(
        "INSERT INTO ingestion_log (job_name, finished_at, status, rows, message) "
        "VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?)",
        (job, status, rows, msg),
    )
    conn.commit()


# ─────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────
def run(days: int, incremental: bool, limit: int | None) -> None:
    init_db(reset=False)
    end_date = effective_trade_date()
    default_start = end_date - timedelta(days=days)
    log.info(f"effective trade date = {end_date}, default start = {default_start}")

    # 1) 股票清單
    log.info("[1/2] fetching stock list...")
    stocks = stock_list.fetch_all()
    log.info(f"got {len(stocks)} stocks from TWSE+TPEX")
    with get_conn() as conn:
        n = upsert_stocks(conn, stocks)
        log_ingestion(conn, "stock_list", "success", n, f"upserted {n} rows")

    if limit:
        stocks = stocks[:limit]
        log.info(f"--limit applied → only processing {len(stocks)} stocks")

    # 2) 日線
    log.info(f"[2/2] fetching daily prices for {len(stocks)} stocks...")
    symbols = [(s.stock_id, s.sub_market) for s in stocks]

    # 增量模式：start 取每檔股票最後一筆 +1 天
    if incremental:
        with get_conn() as conn:
            symbol_ranges = []
            for sid, sm in symbols:
                last = last_price_date(conn, sid)
                start = (last + timedelta(days=1)) if last else default_start
                if start > end_date:
                    continue
                symbol_ranges.append((sid, sm, start))
        log.info(f"incremental mode: {len(symbol_ranges)} stocks need update")

        total_bars = 0
        for sid, sm, start in symbol_ranges:
            bars = daily_prices.fetch_history(sid, sm, start, end_date)
            with get_conn() as conn:
                total_bars += upsert_prices(conn, bars)
    else:
        # 全量回補
        result = daily_prices.fetch_batch(symbols, default_start, end_date)
        total_bars = 0
        with get_conn() as conn:
            for sid, bars in result.items():
                total_bars += upsert_prices(conn, bars)

    log.info(f"done. total bars upserted = {total_bars}")
    with get_conn() as conn:
        log_ingestion(
            conn, "daily_prices", "success", total_bars,
            f"window={default_start}..{end_date}, incremental={incremental}, limit={limit}"
        )

    # 3) 大盤指數 TWII（給 RS 計算用）
    log.info("[3/3] fetching TWII benchmark...")
    try:
        idx_bars = market_index.fetch_index("TWII", default_start, end_date)
        with get_conn() as conn:
            if idx_bars:
                conn.executemany(
                    """INSERT INTO market_index(index_id, market, date, close, volume)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(index_id, date) DO UPDATE SET
                         close=excluded.close, volume=excluded.volume""",
                    [(b.index_id, b.market, b.date.isoformat(), b.close, b.volume)
                     for b in idx_bars],
                )
                conn.commit()
        log.info(f"  → upserted {len(idx_bars)} TWII bars")
    except Exception as e:  # noqa: BLE001
        log.warning(f"TWII fetch failed: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int,
                        default=settings()["ingestion"]["initial_lookback_days"],
                        help="回溯天數（預設讀 settings.yaml）")
    parser.add_argument("--incremental", action="store_true",
                        help="只補齊缺失日（每日 cron 用）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只處理前 N 檔（測試用）")
    parser.add_argument("--skip-flow", action="store_true",
                        help="跳過法人 / 融資融券抓取")
    parser.add_argument("--skip-news", action="store_true",
                        help="跳過新聞抓取")
    args = parser.parse_args()
    run(days=args.days, incremental=args.incremental, limit=args.limit)

    if not args.skip_flow:
        log.info("─── ingest_flow ───")
        from scripts import ingest_flow
        ingest_flow.run(days=1)

    if not args.skip_news:
        log.info("─── ingest_news ───")
        from scripts import ingest_news
        ingest_news.run(["cnyes", "yahoo_tw", "udn_money"])  # MOPS 留待手動


if __name__ == "__main__":
    main()
