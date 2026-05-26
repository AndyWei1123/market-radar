"""Yahoo Finance TW 新聞 — 從 RSS 抓。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from scrapers.news import NewsItem

log = logging.getLogger(__name__)

RSS_URLS = [
    "https://tw.stock.yahoo.com/rss?category=tw-market",
    "https://tw.stock.yahoo.com/rss?category=tw-news",
]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=2, max=8))
def fetch(limit: int = 30) -> list[NewsItem]:
    import xml.etree.ElementTree as ET

    out: list[NewsItem] = []
    seen: set[str] = set()
    for url in RSS_URLS:
        try:
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0 (MarketRadar)"})
            if r.status_code != 200 or not r.text:
                continue
            root = ET.fromstring(r.text)
            for item in root.iter("item"):
                link = (item.findtext("link") or "").strip()
                title = (item.findtext("title") or "").strip()
                pub = item.findtext("pubDate") or ""
                if not link or link in seen:
                    continue
                seen.add(link)
                try:
                    ts = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z")
                except ValueError:
                    ts = datetime.now()
                nid = hashlib.md5(link.encode()).hexdigest()
                out.append(NewsItem(
                    news_id=nid, source="yahoo_tw", url=link,
                    title=title, published_at=ts,
                ))
                if len(out) >= limit:
                    break
        except Exception as e:  # noqa: BLE001
            log.warning(f"[yahoo_tw] {url} failed: {e}")
            continue
    return out


if __name__ == "__main__":
    items = fetch()
    print(f"got {len(items)}")
    for x in items[:5]:
        print(x.published_at.strftime("%Y-%m-%d %H:%M"), "|", x.title[:60])
