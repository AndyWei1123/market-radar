"""台股交易日 / 盤中盤後判斷。

核心邏輯：
  - 系統用「effective_trade_date」概念，回答「現在這個時間點，最新可用的收盤資料是哪一天」
  - 若現在是交易日且時間 < close_cutoff（預設 15:00）→ 用前一交易日
  - 若現在是交易日且 ≥ close_cutoff           → 用今天
  - 若不是交易日                              → 用最近一個交易日

註：MVP 階段不接入官方休市表，只用「週六/週日 = 非交易日」近似。
   未來可加 holidays_tw.yaml 處理國定假日。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from config import settings


def _cfg():
    return settings()["ingestion"]["tw_market"]


def is_trading_day(d: date) -> bool:
    trading_days = set(_cfg()["trading_days"])
    return d.weekday() in trading_days


def previous_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def effective_trade_date(now: datetime | None = None) -> date:
    """回傳目前可用的最新收盤資料日期。

    這是「盤中抓昨日收盤」邏輯的核心入口。
    """
    cfg = _cfg()
    tz = ZoneInfo(cfg["timezone"])
    now_local = (now or datetime.now(tz)).astimezone(tz)
    today = now_local.date()

    cutoff_hour, cutoff_min = map(int, cfg["close_cutoff"].split(":"))
    cutoff_time = time(cutoff_hour, cutoff_min)

    if is_trading_day(today) and now_local.time() >= cutoff_time:
        return today
    return previous_trading_day(today)


def trading_days_between(start: date, end: date) -> list[date]:
    out = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


if __name__ == "__main__":
    print("now effective date:", effective_trade_date())
