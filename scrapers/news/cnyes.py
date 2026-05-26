"""鉅亨網新聞 — 用 REST API（不需 token，公開）。

cnyes news API：https://api.cnyes.com/media/api/v1/newslist/category/tw_stock
參數：limit=30, page=1
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from scrapers.news import NewsItem

log = logging.getLogger(__name__)

API = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def fetch(limit: int = 30, pages: int = 1) -> list[NewsItem]:
    out: list[NewsItem] = []
    for page in range(1, pages + 1):
        r = requests.get(
            API, params={"limit": limit, "page": page},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (MarketRadar)"},
        )
        r.raise_for_status()
        data = r.json().get("items", {}).get("data", []) or []
        for d in data:
            url = f"https://news.cnyes.com/news/id/{d['newsId']}"
            ts = datetime.fromtimestamp(d.get("publishAt", 0), tz=timezone.utc)
            nid = hashlib.md5(url.encode()).hexdigest()
            out.append(NewsItem(
                news_id=nid, source="cnyes", url=url,
                title=d.get("title", "").strip(),
                published_at=ts,
            ))
    return out


if __name__ == "__main__":
    items = fetch(limit=20)
    print(f"got {len(items)} items")
    for x in items[:5]:
        print(x.published_at.strftime("%Y-%m-%d %H:%M"), "|", x.title)
