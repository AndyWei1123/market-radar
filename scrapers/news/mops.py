"""公開資訊觀測站 MOPS — 重大訊息抓取。

⚠️ 限制：MOPS 站台已改為 JS 動態渲染，直接 POST ajax 端點難以穩定取得當日列表。
本檔保留 endpoint 嘗試 + 優雅 fallback（拿不到時回空 list，不噴錯誤），
等未來改用瀏覽器自動化（playwright / selenium）或官方公開 API 再強化。
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Iterable

import requests

from scrapers.news import NewsItem

log = logging.getLogger(__name__)

API = "https://mops.twse.com.tw/mops/web/ajax_t05st02"


def fetch(today_only: bool = True) -> tuple[list[NewsItem], list[tuple[str, str]]]:
    """回傳 (news_items, links)，links 為 [(news_id, stock_id)]"""
    try:
        r = requests.post(
            API,
            data={
                "step": "0", "firstin": "true", "off": "1",
                "TYPEK": "all", "co_id": "", "year": "",
                "month": "", "b_date": "", "e_date": "",
            },
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (MarketRadar)"},
        )
        if r.status_code != 200 or "公司代號" not in r.text:
            return [], []
    except Exception as e:  # noqa: BLE001
        log.warning(f"[mops] fetch failed: {e}")
        return [], []

    # MOPS 回傳 HTML 表格，我們先用最寬鬆方式抓取列
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    rows = soup.select("table tr")
    items: list[NewsItem] = []
    links: list[tuple[str, str]] = []
    for tr in rows:
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < 5:
            continue
        # 常見欄位順序：公司代號 / 公司簡稱 / 發言日期 / 發言時間 / 主旨
        stock_id = tds[0]
        name = tds[1]
        date_s = tds[2] if len(tds) > 2 else ""
        time_s = tds[3] if len(tds) > 3 else ""
        subject = tds[4] if len(tds) > 4 else ""
        if not stock_id.isdigit() and not (stock_id and stock_id[:1].isalnum()):
            continue
        try:
            # 民國年 yyy/mm/dd
            y, m, d = date_s.split("/")
            year = int(y) + 1911
            ts = datetime.strptime(f"{year}-{int(m):02d}-{int(d):02d} {time_s}",
                                   "%Y-%m-%d %H:%M:%S")
        except Exception:
            ts = datetime.now()
        url = f"https://mops.twse.com.tw/mops/web/t05st01_{stock_id}_{ts.date()}"
        nid = hashlib.md5(f"mops_{stock_id}_{ts.isoformat()}_{subject}".encode()).hexdigest()
        items.append(NewsItem(
            news_id=nid, source="mops", url=url,
            title=f"【{stock_id} {name}】{subject}",
            published_at=ts,
        ))
        links.append((nid, stock_id))
    return items, links


if __name__ == "__main__":
    items, links = fetch()
    print(f"got {len(items)} mops items, {len(links)} links")
    for x in items[:5]:
        print(x.published_at.strftime("%Y-%m-%d %H:%M"), "|", x.title[:80])
