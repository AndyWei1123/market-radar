"""新聞抓取入口 — 跑所有 news source，寫入 news + news_stock_link 表。

用法：
    python -m scripts.ingest_news
    python -m scripts.ingest_news --sources cnyes,yahoo_tw
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rich.logging import RichHandler

from db.init_db import get_conn, init_db
from scrapers.news import NewsItem
from scrapers.news.linker import build_links

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "ingest_news.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False),
              logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("ingest_news")


# 各 source 的 fetcher 與 link builder
def _src_cnyes():
    from scrapers.news.cnyes import fetch
    return fetch(limit=30, pages=2), []  # links 留空，靠標題比對


def _src_yahoo_tw():
    from scrapers.news.yahoo_tw import fetch
    return fetch(limit=50), []


def _src_udn_money():
    from scrapers.news.udn_money import fetch
    return fetch(limit=50), []


def _src_mops():
    from scrapers.news.mops import fetch
    items, mops_links = fetch()
    return items, mops_links


SOURCES = {
    "cnyes": _src_cnyes,
    "yahoo_tw": _src_yahoo_tw,
    "udn_money": _src_udn_money,
    "mops": _src_mops,
}


def upsert_news(conn, items: list[NewsItem]) -> int:
    if not items:
        return 0
    conn.executemany(
        """INSERT INTO news(news_id, source, url, title, published_at, fetched_at)
           VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)
           ON CONFLICT(news_id) DO UPDATE SET
             title=excluded.title, source=excluded.source""",
        [(it.news_id, it.source, it.url, it.title,
          it.published_at.isoformat() if it.published_at else None)
         for it in items],
    )
    conn.commit()
    return len(items)


def upsert_links(conn, links: list[tuple[str, str]]) -> int:
    if not links:
        return 0
    conn.executemany(
        """INSERT OR IGNORE INTO news_stock_link(news_id, stock_id, market)
           VALUES (?, ?, 'TW')""",
        links,
    )
    conn.commit()
    return len(links)


def run(sources: list[str]) -> None:
    init_db(reset=False)
    total_items = 0
    total_links = 0
    for src_name in sources:
        fn = SOURCES.get(src_name)
        if not fn:
            log.warning(f"unknown source: {src_name}")
            continue
        log.info(f"[{src_name}] fetching...")
        try:
            items, explicit_links = fn()
        except Exception as e:  # noqa: BLE001
            log.warning(f"[{src_name}] failed: {e}")
            continue
        log.info(f"[{src_name}] got {len(items)} items")
        if not items:
            continue
        with get_conn() as conn:
            n = upsert_news(conn, items)
            total_items += n

            # auto-link 標題比對
            auto_links: list[tuple[str, str]] = []
            for it in items:
                auto_links.extend(build_links(conn, it.news_id, it.title))
            # explicit links（如 MOPS）
            all_links = auto_links + explicit_links
            ln = upsert_links(conn, all_links)
            total_links += ln
            log.info(f"[{src_name}] linked {ln} (auto={len(auto_links)}, "
                     f"explicit={len(explicit_links)})")

    log.info(f"✅ done. {total_items} news, {total_links} stock-links.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", default=",".join(SOURCES.keys()),
                   help=f"逗號分隔，可選：{','.join(SOURCES.keys())}")
    args = p.parse_args()
    run(args.sources.split(","))


if __name__ == "__main__":
    main()
