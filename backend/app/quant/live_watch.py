"""
Market-hours tracking of the nightly watchlist.

Every 15 minutes while NSE is open, fetch the latest price for each
watchlist stock and compare it with the stock's 1-day 80% range from last
night. A stock outside that range is doing something that, by the range's
own track record, happens only about 1 day in 5 — worth a look.
"""

import asyncio
import json
import logging
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE = time(9, 15), time(15, 35)


def market_open(now: datetime = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    return now.weekday() < 5 and OPEN <= now.time() <= CLOSE


def classify(price: float, low: float, high: float) -> str:
    if price > high:
        return "above_range"
    if price < low:
        return "below_range"
    return "inside_range"


async def refresh_live_watch(force: bool = False) -> int:
    if not force and not market_open():
        return 0
    import yfinance as yf
    from app.database import execute_many, fetch

    rows = await fetch("SELECT symbol, payload FROM quant_predictions WHERE model_key = 'market_scanner'")
    picks = {}
    for r in rows:
        p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
        rng = (p.get("ranges") or {}).get("1d", {}).get("p80")
        if rng and p.get("last_close"):
            picks[r["symbol"]] = (float(p["last_close"]), float(rng[0]), float(rng[1]))
    if not picks:
        return 0
    tickers = [f"{s}.NS" for s in picks]
    data = await asyncio.to_thread(
        lambda: yf.download(tickers, period="1d", interval="5m", progress=False,
                            group_by="column", auto_adjust=False, threads=True))
    if data is None or data.empty:
        return 0
    close = data["Close"]
    out = []
    for sym, (prev, lo, hi) in picks.items():
        col = f"{sym}.NS"
        if col not in close.columns:
            continue
        series = close[col].dropna()
        if series.empty:
            continue
        price = float(series.iloc[-1])
        out.append((sym, price, (price / prev - 1) * 100, lo, hi, classify(price, lo, hi)))
    await execute_many(
        """
        INSERT INTO live_watch (symbol, price, change_pct, range_low, range_high, status, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, change_pct = EXCLUDED.change_pct,
            range_low = EXCLUDED.range_low, range_high = EXCLUDED.range_high,
            status = EXCLUDED.status, updated_at = NOW()
        """,
        out,
    )
    logger.info(f"Live watch updated: {len(out)} stocks, "
                f"{sum(1 for r in out if r[5] != 'inside_range')} outside their 80% range")
    return len(out)
