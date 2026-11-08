"""
Indian stock prices without NSE's website API (which blocks cloud servers).

End of day: NSE's official public daily file (sec_bhavdata_full) has open,
high, low, close, previous close and volume for every EQ-series company.
Company names come from NSE's public listed-companies file. All ~2,000+
companies are written to the `stocks` table.

During market hours: Yahoo Finance prices (about 15 minutes delayed) for the
most-traded companies, refreshed every few minutes.
"""

import asyncio
import io
import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd

from app.database import get_pool

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
UA = "Mozilla/5.0 (compatible; StockSentinel/1.0; personal research app)"
INTRADAY_TOP_N = 250


def _num(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def parse_bhavcopy(text: str) -> List[Dict]:
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    df = df[df["SERIES"] == "EQ"]
    out = []
    for r in df.itertuples(index=False):
        d = r._asdict()
        close, prev = _num(d.get("CLOSE_PRICE")), _num(d.get("PREV_CLOSE"))
        if not close:
            continue
        out.append({
            "symbol": str(d["SYMBOL"]).strip(), "open": _num(d.get("OPEN_PRICE")),
            "high": _num(d.get("HIGH_PRICE")), "low": _num(d.get("LOW_PRICE")), "close": close,
            "prev_close": prev, "volume": int(_num(d.get("TTL_TRD_QNTY")) or 0),
            "change_pct": round((close / prev - 1) * 100, 4) if prev else None,
        })
    return out


def _fetch_latest_bhav(client: httpx.Client, today: date) -> Tuple[Optional[date], List[Dict]]:
    for back in range(0, 8):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        try:
            r = client.get(BHAV_URL.format(d=d.strftime("%d%m%Y")))
        except httpx.HTTPError as e:
            logger.warning(f"NSE daily file {d}: {e}")
            continue
        if r.status_code == 200 and "SYMBOL" in r.text[:200]:
            try:
                rows = parse_bhavcopy(r.text)
            except Exception as e:     # malformed file: try the previous day
                logger.warning(f"NSE daily file {d} unreadable: {e}")
                continue
            if rows:
                return d, rows
    return None, []


def _fetch_names(client: httpx.Client) -> Dict[str, str]:
    try:
        r = client.get(LIST_URL)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        return dict(zip(df["SYMBOL"].astype(str).str.strip(), df["NAME OF COMPANY"].astype(str).str.strip()))
    except Exception as e:
        logger.warning(f"NSE company list unavailable: {e}")
        return {}


async def fetch_nse_eod() -> int:
    """Write the latest NSE end-of-day prices for every EQ-series company."""
    today = datetime.now(IST).date()

    def fetch():
        with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as c:
            d, rows = _fetch_latest_bhav(c, today)
            return d, rows, (_fetch_names(c) if rows else {})

    day, rows, names = await asyncio.to_thread(fetch)
    if not rows:
        logger.warning("No NSE daily file found for the last week")
        return 0
    stamp = datetime.combine(day, dtime(15, 30), tzinfo=IST)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO stocks (symbol, name, exchange, market, current_price, prev_close, day_high,
                                day_low, open_price, volume, change_pct, currency, last_updated, is_active)
            VALUES ($1, $2, 'NSE', 'IN', $3, $4, $5, $6, $7, $8, $9, 'INR', $10, TRUE)
            ON CONFLICT (symbol, exchange) DO UPDATE SET
                name = CASE WHEN stocks.name = '' OR stocks.name = stocks.symbol THEN EXCLUDED.name ELSE stocks.name END,
                current_price = EXCLUDED.current_price, prev_close = EXCLUDED.prev_close,
                day_high = EXCLUDED.day_high, day_low = EXCLUDED.day_low, open_price = EXCLUDED.open_price,
                volume = EXCLUDED.volume, change_pct = EXCLUDED.change_pct, is_active = TRUE,
                last_updated = EXCLUDED.last_updated
            """,
            [(r["symbol"][:20], (names.get(r["symbol"]) or r["symbol"])[:200], r["close"], r["prev_close"],
              r["high"], r["low"], r["open"], r["volume"], r["change_pct"], stamp) for r in rows],
        )
    logger.info(f"NSE end-of-day prices for {day}: {len(rows)} companies")
    return len(rows)


def market_open(now: Optional[datetime] = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 35)


async def fetch_nse_intraday(force: bool = False) -> int:
    """Delayed live prices from Yahoo for the most-traded NSE companies (market hours only)."""
    if not force and not market_open():
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, prev_close FROM stocks
            WHERE exchange = 'NSE' AND market = 'IN' AND is_active AND current_price IS NOT NULL
            ORDER BY COALESCE(volume, 0) * COALESCE(current_price, 0) DESC LIMIT $1
            """,
            INTRADAY_TOP_N,
        )
        # Stocks on today's rating lists are always tracked live too.
        try:
            rated = await conn.fetch(
                """
                (SELECT symbol FROM quant_predictions WHERE model_key = 'stock_day' ORDER BY rank ASC LIMIT 50)
                UNION
                (SELECT symbol FROM quant_predictions WHERE model_key = 'stock_day' ORDER BY rank DESC LIMIT 50)
                """)
        except Exception:
            rated = []
    if not rows:
        return 0
    syms = [r["symbol"] for r in rows if not r["symbol"].startswith("^")]
    syms += [r["symbol"] for r in rated if r["symbol"] not in set(syms)]
    from app.scrapers.yf_util import yf_download
    data = await yf_download([f"{s}.NS" for s in syms], period="1d", interval="5m",
                             group_by="column", auto_adjust=False, threads=True)
    if data is None or data.empty:
        return 0
    updates = intraday_rows(data, syms, datetime.now(IST).date())
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            UPDATE stocks SET current_price = $2, open_price = COALESCE($3, open_price),
                day_high = COALESCE($4, day_high), day_low = COALESCE($5, day_low),
                change_pct = CASE WHEN prev_close > 0 THEN ($2 / prev_close - 1) * 100 ELSE change_pct END,
                last_updated = NOW()
            WHERE symbol = $1 AND exchange = 'NSE'
            """,
            updates,
        )
    logger.info(f"NSE intraday prices (Yahoo, delayed): {len(updates)} companies")
    return len(updates)


def intraday_rows(data, syms: List[str], today: date) -> List[Tuple]:
    """(symbol, last, today's open, high, low) from 5-minute bars of today's session only."""
    out = []
    if data is None or data.empty:
        return out
    idx = data.index
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(IST)
    today_mask = [ts.date() == today for ts in idx]
    for s in syms:
        col = f"{s}.NS"
        try:
            c = data["Close"][col][today_mask].dropna()
        except KeyError:
            continue
        if c.empty:
            continue

        def first(field, how):
            try:
                v = data[field][col][today_mask].dropna()
            except KeyError:
                return None
            if v.empty:
                return None
            return float(v.iloc[0] if how == "first" else (v.max() if how == "max" else v.min()))
        out.append((s, float(c.iloc[-1]), first("Open", "first"), first("High", "max"), first("Low", "min")))
    return out


async def eod_needed() -> bool:
    """True when the newest NSE price in the database is older than the last trading day's close."""
    now = datetime.now(IST)
    last_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now < last_close + timedelta(hours=3):      # today's file appears in the evening
        last_close -= timedelta(days=1)
    while last_close.weekday() >= 5:
        last_close -= timedelta(days=1)
    # Count how many companies are up to date: a single stock refreshed on demand
    # must not make the whole table look fresh.
    pool = await get_pool()
    async with pool.acquire() as conn:
        fresh = await conn.fetchval(
            "SELECT COUNT(*) FROM stocks WHERE exchange = 'NSE' AND market = 'IN' AND last_updated >= $1",
            last_close)
    return (fresh or 0) < 1000
