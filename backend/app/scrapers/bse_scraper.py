"""
BSE India Scraper — fetches stock prices from BSE India.

Uses the BSE API endpoints with browser-like headers.
Only adds stocks NOT already in NSE to avoid duplicates.
"""

import logging
import asyncio
import httpx
from datetime import datetime, timezone
from app.database import fetch, get_pool
from app.config import settings

logger = logging.getLogger(__name__)

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api"

BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


async def fetch_bse_stocks():
    """Fetch BSE stock data and update database."""
    logger.info("Fetching BSE stock data...")

    try:
        async with httpx.AsyncClient(headers=BSE_HEADERS, timeout=30) as client:
            # BSE gainers endpoint gives us active stocks with prices
            categories = ["A", "B", "T", "S", "TS"]
            total_count = 0

            for category in categories:
                try:
                    resp = await client.get(
                        f"{BSE_API}/StockReachGraph/w",
                        params={
                            "scripcode": "",
                            "flag": "0",
                            "fromdate": "",
                            "todate": "",
                            "seriesid": "",
                        },
                    )

                    # Alternative: Use the getScripHeaderData for individual stocks
                    # This is more reliable but slower
                    await asyncio.sleep(settings.BSE_REQUEST_DELAY)

                except Exception as e:
                    logger.debug(f"BSE category {category} fetch error: {e}")
                    continue

            # Fetch top gainers/losers which give us actively traded stocks
            for endpoint in ["getGainersAndLosersData"]:
                try:
                    resp = await client.get(
                        f"{BSE_API}/{endpoint}",
                        params={
                            "Type": "EQ",
                            "flag": "0",
                        },
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            table = data.get("Table", [])
                        elif isinstance(data, list):
                            table = data
                        else:
                            continue

                        pool = await get_pool()
                        async with pool.acquire() as conn:
                            for stock in table:
                                try:
                                    scrip_code = stock.get("scrip_cd") or stock.get("ScripCode")
                                    name = stock.get("scrip_name") or stock.get("LongName", "")
                                    symbol = stock.get("SCRIP_CD") or stock.get("scrip_cd") or str(scrip_code)
                                    ltp = stock.get("ltradert") or stock.get("LTP")
                                    change = stock.get("change") or stock.get("Chg")
                                    pchange = stock.get("pchange") or stock.get("PcntChg")

                                    if not symbol or not name:
                                        continue

                                    # Check if already in NSE
                                    existing = await conn.fetchrow(
                                        "SELECT id FROM stocks WHERE symbol = $1 AND exchange = 'NSE'",
                                        symbol.strip().upper(),
                                    )

                                    if existing:
                                        # Already tracked via NSE, skip
                                        continue

                                    await conn.execute(
                                        """
                                        INSERT INTO stocks (symbol, name, exchange, market, current_price,
                                                          change_pct, currency, last_updated, is_active)
                                        VALUES ($1, $2, 'BSE', 'IN', $3, $4, 'INR', $5, TRUE)
                                        ON CONFLICT (symbol, exchange)
                                        DO UPDATE SET
                                            current_price = EXCLUDED.current_price,
                                            change_pct = EXCLUDED.change_pct,
                                            last_updated = EXCLUDED.last_updated
                                        """,
                                        symbol.strip().upper(),
                                        name.strip(),
                                        _safe_float(ltp),
                                        _safe_float(pchange),
                                        datetime.now(timezone.utc),
                                    )
                                    total_count += 1
                                except Exception as e:
                                    logger.debug(f"Error inserting BSE stock: {e}")

                except Exception as e:
                    logger.warning(f"BSE {endpoint} fetch error: {e}")

            logger.info(f"BSE stocks updated: {total_count}")
            return total_count

    except Exception as e:
        logger.error(f"BSE stock fetch failed: {e}")
        return 0


def _safe_float(value):
    """Safely convert to float."""
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
