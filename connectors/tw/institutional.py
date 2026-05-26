"""三大法人買賣超抓取 — 來自 TWSE / TPEx 官方 CSV。

TWSE T86 端點：每日全市場上市股票三大法人買賣超
TPEx 端點：每日全市場上櫃股票三大法人買賣超
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

TWSE_T86 = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?date={ymd}&selectType=ALLBUT0999&response=csv"
)
TPEX_INST = (
    "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
    "3itrade_hedge_result.php?l=zh-tw&se=AL&d={roc_ymd}&t=D&o=csv"
)


@dataclass
class InstFlow:
    date: date
    stock_id: str
    market: str
    foreign_net: int
    trust_net: int
    dealer_net: int


def _to_int(v) -> int:
    """處理千分位逗號 / 空字串 / NaN。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    s = str(v).strip().replace(",", "").replace('"', "")
    if not s or s in ("--", "—"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def fetch_twse(on_date: date) -> list[InstFlow]:
    url = TWSE_T86.format(ymd=on_date.strftime("%Y%m%d"))
    r = requests.get(url, timeout=20,
                     headers={"User-Agent": "Mozilla/5.0 (MarketRadar)"})
    r.encoding = "cp950"
    text = r.text
    if "證券代號" not in text:
        return []  # 假日或無資料
    # CSV 含多段標頭，找正確開頭
    lines = text.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if "證券代號" in ln), -1)
    if header_idx == -1:
        return []
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), thousands=",")
    df.columns = [c.strip().replace('"', "") for c in df.columns]
    out: list[InstFlow] = []
    for _, row in df.iterrows():
        sid = str(row.get("證券代號", "")).strip().strip('"').strip("=").strip('"')
        if not sid or not sid[:1].isalnum():
            continue
        foreign = _to_int(row.get("外陸資買賣超股數(不含外資自營商)") or
                          row.get("外資買賣超股數"))
        trust = _to_int(row.get("投信買賣超股數"))
        dealer = _to_int(row.get("自營商買賣超股數") or
                         row.get("自營商買賣超股數(自行買賣)"))
        out.append(InstFlow(
            date=on_date, stock_id=sid, market="TW",
            foreign_net=foreign, trust_net=trust, dealer_net=dealer,
        ))
    return out


def _roc_date(d: date) -> str:
    """西元 → 民國 yyy/mm/dd"""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=15))
def fetch_tpex(on_date: date) -> list[InstFlow]:
    url = TPEX_INST.format(roc_ymd=_roc_date(on_date))
    # SSL 偶發失敗：先試 verify=True，再降級
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (MarketRadar)"})
    try:
        r = sess.get(url, timeout=30)
    except requests.exceptions.SSLError:
        log.warning("[inst] TPEx SSL error, retry with verify=False")
        r = sess.get(url, timeout=30, verify=False)
    r.encoding = "cp950"
    text = r.text
    if "代號" not in text:
        return []
    lines = text.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if "代號" in ln and "名稱" in ln), -1)
    if header_idx == -1:
        return []
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), thousands=",")
    df.columns = [c.strip().replace('"', "") for c in df.columns]

    # 寬鬆比對：任何含「外資」/「投信」/「自營」的欄位，並排除「鉅額」、「比率」、「百分比」、「占比」
    def _pick_col(keyword: str) -> str | None:
        for c in df.columns:
            cl = str(c)
            if keyword in cl and not any(
                x in cl for x in ("鉅額", "比率", "占比", "百分比", "%", "公司家數")
            ):
                if "買賣超" in cl or "淨" in cl:
                    return c
        # 退而求其次：只要含 keyword + 「買賣超」即可
        for c in df.columns:
            if keyword in str(c) and "買賣超" in str(c):
                return c
        return None

    col_foreign = _pick_col("外資")
    col_trust = _pick_col("投信")
    col_dealer = _pick_col("自營")
    if not (col_foreign or col_trust or col_dealer):
        log.warning(f"[inst] TPEx {on_date}: 找不到法人欄位，columns={list(df.columns)[:10]}")
        return []

    out: list[InstFlow] = []
    for _, row in df.iterrows():
        sid_raw = row.get("代號")
        if sid_raw is None:
            continue
        sid = str(sid_raw).strip().strip('"').strip("=").strip('"')
        if not sid or not sid[:1].isalnum():
            continue
        out.append(InstFlow(
            date=on_date, stock_id=sid, market="TW",
            foreign_net=_to_int(row.get(col_foreign)) if col_foreign else 0,
            trust_net=_to_int(row.get(col_trust)) if col_trust else 0,
            dealer_net=_to_int(row.get(col_dealer)) if col_dealer else 0,
        ))
    return out


def fetch_all(on_date: date) -> list[InstFlow]:
    """同時抓上市 + 上櫃，回傳合併清單。"""
    out: list[InstFlow] = []
    try:
        out.extend(fetch_twse(on_date))
    except Exception as e:  # noqa: BLE001
        log.warning(f"[inst] TWSE {on_date} failed: {e}")
    try:
        out.extend(fetch_tpex(on_date))
    except Exception as e:  # noqa: BLE001
        log.warning(f"[inst] TPEx {on_date} failed: {e}")
    return out


def daterange(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


if __name__ == "__main__":
    from connectors.tw.calendar import effective_trade_date

    d = effective_trade_date()
    rows = fetch_all(d)
    print(f"{d}: got {len(rows)} institutional rows")
    if rows:
        print(rows[0])
