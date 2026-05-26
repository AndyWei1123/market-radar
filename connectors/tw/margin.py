"""融資融券餘額抓取 — TWSE / TPEx 官方 CSV。"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

TWSE_MARGIN = (
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    "?date={ymd}&selectType=ALL&response=csv"
)
TPEX_MARGIN = (
    "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php"
    "?l=zh-tw&d={roc_ymd}&o=csv"
)


@dataclass
class MarginRow:
    date: date
    stock_id: str
    market: str
    margin_buy: int
    margin_sell: int
    margin_bal: int
    short_sell: int
    short_cover: int
    short_bal: int


def _i(v) -> int:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    s = str(v).strip().replace(",", "").replace('"', "")
    if not s or s in ("--", "—"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _roc(d: date) -> str:
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def fetch_twse(on_date: date) -> list[MarginRow]:
    """TWSE 融資融券彙總（全部）的 CSV 標頭是分段重複的：
       代號, 名稱, 買進, 賣出, 現金償還, 前日餘額, 今日餘額, 次一營業日限額,
                  買進, 賣出, 現券償還, 前日餘額, 今日餘額, 次一營業日限額,
       資券互抵, 註記
       前 6 個是融資（idx 2..6），後 6 個是融券（idx 8..12）。
       這裡用「以逗號 split + 位置索引」避開重複欄名問題。
    """
    url = TWSE_MARGIN.format(ymd=on_date.strftime("%Y%m%d"))
    r = requests.get(url, timeout=20,
                     headers={"User-Agent": "Mozilla/5.0 (MarketRadar)"})
    r.encoding = "cp950"
    text = r.text
    out: list[MarginRow] = []
    import re
    # 有效行可能是：="0050","元大..." 或 "1472","三洋..."
    # 用 regex 抓所有 "xxx" 區塊（含 = 前綴可選）
    row_re = re.compile(r'(?:=)?"([^"]*)"')
    for ln in text.splitlines():
        if not (ln.startswith('"') or ln.startswith('="')):
            continue
        parts = row_re.findall(ln)
        if len(parts) < 14:
            continue
        sid = parts[0].strip()
        # 過濾標頭 / 統計列
        if not sid or not sid[:1].isalnum() or sid in ("代號", "股票代號", "證券代號"):
            continue
        try:
            out.append(MarginRow(
                date=on_date, stock_id=sid, market="TW",
                margin_buy=_i(parts[2]),
                margin_sell=_i(parts[3]),
                margin_bal=_i(parts[6]),
                short_sell=_i(parts[9]),
                short_cover=_i(parts[8]),
                short_bal=_i(parts[12]),
            ))
        except (IndexError, ValueError):
            continue
    return out


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=15))
def fetch_tpex(on_date: date) -> list[MarginRow]:
    """TPEx CSV 欄位（依位置）：
       0 代號  1 名稱  2 前資餘額  3 資買  4 資賣  5 現償  6 資餘額  7-9 屬證金/使用率/限額
       10 前券餘額  11 券賣  12 券買  13 券償  14 券餘額  ...
    """
    import re
    url = TPEX_MARGIN.format(roc_ymd=_roc(on_date))
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (MarketRadar)"})
    try:
        r = sess.get(url, timeout=30)
    except requests.exceptions.SSLError:
        log.warning("[margin] TPEx SSL error, retry with verify=False")
        r = sess.get(url, timeout=30, verify=False)
    r.encoding = "cp950"
    text = r.text
    out: list[MarginRow] = []
    row_re = re.compile(r'(?:=)?"([^"]*)"')
    for ln in text.splitlines():
        if not (ln.startswith('"') or ln.startswith('="')):
            continue
        parts = row_re.findall(ln)
        if len(parts) < 15:
            continue
        sid = parts[0].strip()
        if not sid or not sid[:1].isalnum() or sid == "代號":
            continue
        try:
            out.append(MarginRow(
                date=on_date, stock_id=sid, market="TW",
                margin_buy=_i(parts[3]),
                margin_sell=_i(parts[4]),
                margin_bal=_i(parts[6]),
                short_sell=_i(parts[11]),
                short_cover=_i(parts[12]),
                short_bal=_i(parts[14]),
            ))
        except (IndexError, ValueError):
            continue
    return out


def fetch_all(on_date: date) -> list[MarginRow]:
    out: list[MarginRow] = []
    try:
        out.extend(fetch_twse(on_date))
    except Exception as e:  # noqa: BLE001
        log.warning(f"[margin] TWSE {on_date} failed: {e}")
    try:
        out.extend(fetch_tpex(on_date))
    except Exception as e:  # noqa: BLE001
        log.warning(f"[margin] TPEx {on_date} failed: {e}")
    return out


if __name__ == "__main__":
    from connectors.tw.calendar import effective_trade_date

    d = effective_trade_date()
    rows = fetch_all(d)
    print(f"{d}: got {len(rows)} margin rows")
    if rows:
        print(rows[0])
