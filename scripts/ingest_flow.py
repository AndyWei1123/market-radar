"""法人 + 融資融券抓取入口（W4-1 / W4-2）。

用法：
    python -m scripts.ingest_flow                   # 抓最新交易日
    python -m scripts.ingest_flow --days 5          # 回補近 5 個交易日
"""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta
from pathlib import Path

from rich.logging import RichHandler

from connectors.tw import institutional, margin
from connectors.tw.calendar import effective_trade_date
from db.init_db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "ingest_flow.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO, format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False),
              logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("ingest_flow")


def upsert_inst(conn, rows: list[institutional.InstFlow]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO institutional_flow(date, stock_id, market,
              foreign_net, trust_net, dealer_net)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(date, stock_id, market) DO UPDATE SET
             foreign_net=excluded.foreign_net,
             trust_net=excluded.trust_net,
             dealer_net=excluded.dealer_net""",
        [(r.date.isoformat(), r.stock_id, r.market,
          r.foreign_net, r.trust_net, r.dealer_net) for r in rows],
    )
    conn.commit()
    return len(rows)


def upsert_margin(conn, rows: list[margin.MarginRow]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO margin_balance(date, stock_id, market,
              margin_buy, margin_sell, margin_bal,
              short_sell, short_cover, short_bal)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date, stock_id, market) DO UPDATE SET
             margin_buy=excluded.margin_buy, margin_sell=excluded.margin_sell,
             margin_bal=excluded.margin_bal,
             short_sell=excluded.short_sell, short_cover=excluded.short_cover,
             short_bal=excluded.short_bal""",
        [(r.date.isoformat(), r.stock_id, r.market,
          r.margin_buy, r.margin_sell, r.margin_bal,
          r.short_sell, r.short_cover, r.short_bal) for r in rows],
    )
    conn.commit()
    return len(rows)


def run(days: int) -> None:
    init_db(reset=False)
    end = effective_trade_date()
    dates = []
    d = end
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    dates = sorted(dates)

    total_i = total_m = 0
    for on_d in dates:
        log.info(f"=== {on_d} ===")
        i_rows = institutional.fetch_all(on_d)
        m_rows = margin.fetch_all(on_d)
        with get_conn() as conn:
            ni = upsert_inst(conn, i_rows)
            nm = upsert_margin(conn, m_rows)
        total_i += ni
        total_m += nm
        log.info(f"  inst: {ni}, margin: {nm}")
    log.info(f"✅ done. inst={total_i}, margin={total_m}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=1, help="回補近 N 個交易日")
    args = p.parse_args()
    run(args.days)


if __name__ == "__main__":
    main()
