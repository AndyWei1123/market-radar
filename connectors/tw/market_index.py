"""抓台股大盤 / 櫃買指數，作為 RS 計算的基準。

支援 index_id：
  - TWII : 加權指數 ^TWII
  - OTC  : 櫃買指數 ^TWOII (yfinance 代碼)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

INDEX_SYMBOLS = {
    "TWII": "^TWII",
    "OTC": "^TWOII",
}


@dataclass
class IndexBar:
    index_id: str
    market: str
    date: date
    close: float
    volume: int


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
def fetch_index(index_id: str, start: date, end: date) -> list[IndexBar]:
    symbol = INDEX_SYMBOLS.get(index_id)
    if not symbol:
        raise ValueError(f"unknown index_id: {index_id}")
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
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    out: list[IndexBar] = []
    for ts, row in df.iterrows():
        try:
            out.append(
                IndexBar(
                    index_id=index_id,
                    market="TW",
                    date=ts.date(),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                )
            )
        except (ValueError, KeyError, TypeError):
            continue
    return out


if __name__ == "__main__":
    from connectors.tw.calendar import effective_trade_date

    end = effective_trade_date()
    start = end - timedelta(days=30)
    bars = fetch_index("TWII", start, end)
    print(f"TWII: {len(bars)} bars, last = {bars[-1] if bars else 'N/A'}")
