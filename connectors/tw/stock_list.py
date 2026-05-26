"""抓取台股上市 + 上櫃股票清單。

資料源：證交所 ISIN 公告
  上市：https://isin.twse.com.tw/isin/C_public.jsp?strMode=2
  上櫃：https://isin.twse.com.tw/isin/C_public.jsp?strMode=4

這個端點不需要 token，回傳 HTML 表格。
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

URL_TWSE = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
URL_TPEX = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class StockInfo:
    stock_id: str
    market: str          # 'TW'
    name: str
    sector: str | None
    listing_date: str | None  # YYYY-MM-DD
    sub_market: str      # 'TWSE' / 'TPEX'


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    # 用 cp950（Windows Big5）而非標準 big5，才能正確解出「碁」、「堃」、「喆」、
    # 「奡」等不在標準 Big5 但常見於台灣人名 / 公司名的字。
    resp.encoding = "cp950"
    resp.raise_for_status()
    return resp.text


def _parse_table(html: str, sub_market: str) -> list[StockInfo]:
    # pandas.read_html 可以直接吃 HTML 表格
    dfs = pd.read_html(io.StringIO(html))
    df = dfs[0]
    # 第 1 欄是「有價證券代號及名稱」，需要拆解
    # 表格結構：第一列開始才是普通股，前面有 header / 大類 row
    rows: list[StockInfo] = []
    for _, row in df.iterrows():
        raw = str(row.iloc[0]).strip()
        if not raw or raw == "nan":
            continue
        # 形如 "2330　台積電"（全形空白）
        m = re.match(r"^(\d{4,6})[\s　]+(.+)$", raw)
        if not m:
            continue
        stock_id, name = m.group(1), m.group(2).strip()
        listing_date = str(row.iloc[2]).strip() if len(row) > 2 else None
        sector = str(row.iloc[4]).strip() if len(row) > 4 else None
        if listing_date == "nan":
            listing_date = None
        if sector in (None, "nan", ""):
            sector = None
        # 只抓 4 碼普通股（排除權證 / ETF / 特別股等 5-6 碼）
        if len(stock_id) != 4:
            continue
        rows.append(
            StockInfo(
                stock_id=stock_id,
                market="TW",
                name=name,
                sector=sector,
                listing_date=listing_date,
                sub_market=sub_market,
            )
        )
    return rows


def fetch_all() -> list[StockInfo]:
    """抓取上市 + 上櫃普通股清單。"""
    twse = _parse_table(_fetch_html(URL_TWSE), "TWSE")
    tpex = _parse_table(_fetch_html(URL_TPEX), "TPEX")
    return twse + tpex


if __name__ == "__main__":
    stocks = fetch_all()
    print(f"fetched {len(stocks)} stocks")
    for s in stocks[:5]:
        print(s)
