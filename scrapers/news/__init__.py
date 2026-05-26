"""新聞抓取（標題層級）— 多來源。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NewsItem:
    news_id: str          # hash of url
    source: str           # 'cnyes' / 'yahoo_tw' / 'mops' / ...
    url: str
    title: str
    published_at: datetime
