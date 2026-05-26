"""把新聞標題與個股做自動連結。

策略：
  1. 標題中出現「股票名稱」→ link
  2. 標題中出現 4–6 位股票代號（如「(2330)」、「2330」）→ link
  3. MOPS 自帶 stock_id，直接寫入
"""
from __future__ import annotations

import re
import sqlite3

NUM_PATTERN = re.compile(r"(?<![\d/])\b(\d{4,6}[A-Z]?)\b(?!\d)")


def build_links(conn: sqlite3.Connection, news_id: str, title: str) -> list[tuple[str, str]]:
    """回傳 [(news_id, stock_id), ...]"""
    # 一次抓全部股票名稱與 ID
    cur = conn.execute("SELECT stock_id, name FROM stocks WHERE market='TW'")
    pairs = [(r[0], r[1] or "") for r in cur.fetchall()]
    name_to_id = {n: sid for sid, n in pairs if len(n) >= 2}
    id_set = {sid for sid, _ in pairs}

    found: set[str] = set()

    # 1. 股票名稱比對
    for name, sid in name_to_id.items():
        if name and name in title:
            found.add(sid)

    # 2. 4–6 位數字代號
    for m in NUM_PATTERN.findall(title):
        if m in id_set:
            found.add(m)

    return [(news_id, sid) for sid in found]
