"""抓台股個股日線（近 N 年）。

策略：用 yfinance（後綴 .TW / .TWO）為主，FinMind 為備援。
yfinance 適合一次回補長區間，且不需 token。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class PriceBar:
    stock_id: str
    market: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float


def _yf_symbol(stock_id: str, sub_market: str) -> str:
    """TWSE → .TW, TPEX → .TWO"""
    suffix = ".TW" if sub_market == "TWSE" else ".TWO"
    return f"{stock_id}{suffix}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def fetch_history(
    stock_id: str,
    sub_market: str,
    start: date,
    end: date,
) -> list[PriceBar]:
    """抓 [start, end] 區間的日線。end 為包含。"""
    symbol = _yf_symbol(stock_id, sub_market)
    df = yf.download(
        symbol,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df is None or df.empty:
        return []

    # yfinance 新版會回傳 MultiIndex 欄位 (field, ticker)，先攤平
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    out: list[PriceBar] = []
    for ts, row in df.iterrows():
        try:
            out.append(
                PriceBar(
                    stock_id=stock_id,
                    market="TW",
                    date=ts.date(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                    adj_close=float(row["Adj Close"]),
                )
            )
        except (ValueError, KeyError, TypeError):
            continue
    return out


def fetch_batch(
    symbols: list[tuple[str, str]],   # [(stock_id, sub_market), ...]
    start: date,
    end: date,
    sleep_sec: float = 0.3,
) -> dict[str, list[PriceBar]]:
    """批次抓取，回傳 {stock_id: [PriceBar, ...]}。

    yfinance 對台股似乎沒辦法穩定一次多檔（不同後綴混在一起會出狀況），
    所以這裡走逐檔模式，並加上輕量 sleep 避免被 throttle。
    """
    result: dict[str, list[PriceBar]] = {}
    for i, (sid, sm) in enumerate(symbols, 1):
        try:
            bars = fetch_history(sid, sm, start, end)
            result[sid] = bars
        except Exception as e:  # noqa: BLE001
            print(f"[daily_prices] {sid} failed: {e}")
            result[sid] = []
        if i % 50 == 0:
            print(f"[daily_prices] progress {i}/{len(symbols)}")
        time.sleep(sleep_sec)
    return result


if __name__ == "__main__":
    from connectors.tw.calendar import effective_trade_date

    end = effective_trade_date()
    start = end - timedelta(days=365)
    bars = fetch_history("2330", "TWSE", start, end)
    print(f"2330: {len(bars)} bars, last = {bars[-1] if bars else 'N/A'}")
