"""
BSE prices from BSE's official public end-of-day file (BhavCopy, UDiFF format).

BSE's website API blocks cloud servers, so the old live scraper saved nothing.
The daily file lists every traded BSE company. Companies also listed on NSE
already get NSE prices, so only BSE-only companies are written (exchange 'BSE').
"""

import asyncio
import io
import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd

from app.database import get_pool
from app.scrapers.nse_prices import IST, UA, _num

logger = logging.getLogger(__name__)

BSE_BHAV_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d}_F_0000.CSV"
# Debt, government securities and institutional-only series are not company shares.
SKIP_SERIES = {"F", "G", "IF", "IT", "E"}


def parse_bse_bhav(text: str) -> List[Dict]:
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df[(df["FinInstrmTp"].str.strip() == "STK") & ~df["SctySrs"].str.strip().isin(SKIP_SERIES)]
    out = []
    for r in df.to_dict("records"):
        close, prev = _num(r.get("ClsPric")), _num(r.get("PrvsClsgPric"))
        sym = str(r.get("TckrSymb") or "").strip()
        if not close or not sym:
            continue
        out.append({
            "symbol": sym, "name": str(r.get("FinInstrmNm") or sym).strip(), "isin": str(r.get("ISIN") or "").strip(),
            "open": _num(r.get("OpnPric")), "high": _num(r.get("HghPric")), "low": _num(r.get("LwPric")),
            "close": close, "prev_close": prev, "volume": int(_num(r.get("TtlTradgVol")) or 0),
            "change_pct": round((close / prev - 1) * 100, 4) if prev else None,
        })
    return out


def _fetch_latest(client: httpx.Client, today: date) -> Tuple[Optional[date], List[Dict]]:
    for back in range(0, 8):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        try:
            r = client.get(BSE_BHAV_URL.format(d=d.strftime("%Y%m%d")))
        except httpx.HTTPError as e:
            logger.warning(f"BSE daily file {d}: {e}")
            continue
        if r.status_code == 200 and r.text.startswith("TradDt"):
            try:
                rows = parse_bse_bhav(r.text)
            except Exception as e:
                logger.warning(f"BSE daily file {d} unreadable: {e}")
                continue
            if rows:
                return d, rows
    return None, []


async def fetch_bse_stocks() -> int:
    """Write the latest BSE end-of-day prices for companies not listed on NSE."""
    today = datetime.now(IST).date()

    def fetch():
        with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as c:
            return _fetch_latest(c, today)

    day, rows = await asyncio.to_thread(fetch)
    if not rows:
        logger.warning("No BSE daily file found for the last week")
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        nse = {r["symbol"] for r in await conn.fetch("SELECT symbol FROM stocks WHERE exchange = 'NSE'")}
        rows = [r for r in rows if r["symbol"] not in nse]
        stamp = datetime.combine(day, dtime(15, 30), tzinfo=IST)
        await conn.executemany(
            """
            INSERT INTO stocks (symbol, name, exchange, market, current_price, prev_close, day_high,
                                day_low, open_price, volume, change_pct, currency, last_updated, is_active)
            VALUES ($1, $2, 'BSE', 'IN', $3, $4, $5, $6, $7, $8, $9, 'INR', $10, TRUE)
            ON CONFLICT (symbol, exchange) DO UPDATE SET
                current_price = EXCLUDED.current_price, prev_close = EXCLUDED.prev_close,
                day_high = EXCLUDED.day_high, day_low = EXCLUDED.day_low, open_price = EXCLUDED.open_price,
                volume = EXCLUDED.volume, change_pct = EXCLUDED.change_pct, is_active = TRUE,
                last_updated = EXCLUDED.last_updated
            """,
            [(r["symbol"][:20], r["name"][:200], r["close"], r["prev_close"], r["high"], r["low"],
              r["open"], r["volume"], r["change_pct"], stamp) for r in rows],
        )
    logger.info(f"BSE end-of-day prices for {day}: {len(rows)} BSE-only companies")
    return len(rows)
