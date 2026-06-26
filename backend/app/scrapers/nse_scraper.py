"""
NSE India Scraper — fetches stock prices and dividend data from NSE India.

Uses httpx with browser-like headers to access NSE's internal API endpoints.
Rate limited to avoid IP blocking.
"""

import logging
import asyncio
import httpx
from datetime import datetime, timezone
from app.database import fetch, execute, get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# NSE API endpoints (internal, used by the website)
NSE_BASE = "https://www.nseindia.com"
NSE_API = "https://www.nseindia.com/api"

# Browser-like headers required by NSE
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_nse_session():
    """Create an httpx client with NSE cookies."""
    async with httpx.AsyncClient(
        headers=NSE_HEADERS,
        timeout=30,
        follow_redirects=True,
    ) as client:
        # Hit main page first to get cookies
        try:
            await client.get(NSE_BASE)
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Failed to get NSE cookies: {e}")
        yield client


async def fetch_nse_equity_list():
    """Fetch all NSE equity stocks and update the database."""
    logger.info("Fetching NSE equity list...")

    try:
        async with get_nse_session() as client:
            # Fetch market status and equity data
            # NSE provides CSV/JSON data for all equities
            resp = await client.get(f"{NSE_API}/equity-stockIndices?index=SECURITIES%20IN%20F%26O")
            if resp.status_code != 200:
                # Fallback: try the broader equity list
                resp = await client.get(f"{NSE_API}/equity-stockIndices?index=BROAD%20MARKET%20INDICES")

            if resp.status_code != 200:
                logger.warning(f"NSE equity list returned {resp.status_code}")
                return 0

            data = resp.json()
            stocks = data.get("data", [])

            if not stocks:
                logger.warning("No stocks returned from NSE")
                return 0

            pool = await get_pool()
            count = 0

            async with pool.acquire() as conn:
                for stock in stocks:
                    try:
                        symbol = stock.get("symbol", "").strip()
                        if not symbol or symbol == "NIFTY 50":
                            continue

                        await conn.execute(
                            """
                            INSERT INTO stocks (symbol, name, exchange, market, current_price,
                                              prev_close, day_high, day_low, open_price,
                                              change_pct, currency, last_updated, is_active)
                            VALUES ($1, $2, 'NSE', 'IN', $3, $4, $5, $6, $7, $8, 'INR', $9, TRUE)
                            ON CONFLICT (symbol, exchange)
                            DO UPDATE SET
                                current_price = EXCLUDED.current_price,
                                prev_close = EXCLUDED.prev_close,
                                day_high = EXCLUDED.day_high,
                                day_low = EXCLUDED.day_low,
                                open_price = EXCLUDED.open_price,
                                change_pct = EXCLUDED.change_pct,
                                last_updated = EXCLUDED.last_updated
                            """,
                            symbol,
                            stock.get("companyName", symbol),
                            _to_decimal(stock.get("lastPrice")),
                            _to_decimal(stock.get("previousClose")),
                            _to_decimal(stock.get("dayHigh")),
                            _to_decimal(stock.get("dayLow")),
                            _to_decimal(stock.get("open")),
                            _to_decimal(stock.get("pChange")),
                            datetime.now(timezone.utc),
                        )
                        count += 1
                    except Exception as e:
                        logger.debug(f"Error inserting NSE stock {stock.get('symbol')}: {e}")

            logger.info(f"NSE equity update: {count} stocks")
            return count

    except Exception as e:
        logger.error(f"NSE equity fetch failed: {e}")
        return 0


async def fetch_nse_all_stocks():
    """
    Fetch broader NSE stock data using the equity market endpoint.
    This gets more stocks than just F&O.
    """
    logger.info("Fetching all NSE stocks via market data...")

    indices = [
        "NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200",
        "NIFTY 500", "NIFTY MIDCAP 50", "NIFTY MIDCAP 100",
        "NIFTY SMALLCAP 100", "NIFTY SMALLCAP 250",
    ]

    total_count = 0
    seen_symbols = set()

    try:
        async with get_nse_session() as client:
            for index_name in indices:
                try:
                    encoded = index_name.replace(" ", "%20").replace("&", "%26")
                    resp = await client.get(
                        f"{NSE_API}/equity-stockIndices?index={encoded}"
                    )

                    if resp.status_code != 200:
                        logger.debug(f"NSE index {index_name} returned {resp.status_code}")
                        continue

                    data = resp.json()
                    stocks = data.get("data", [])

                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        for stock in stocks:
                            symbol = stock.get("symbol", "").strip()
                            if not symbol or symbol in seen_symbols:
                                continue
                            if symbol.startswith("NIFTY"):
                                # This is an index, not a stock
                                continue

                            seen_symbols.add(symbol)
                            try:
                                await conn.execute(
                                    """
                                    INSERT INTO stocks (symbol, name, exchange, market, current_price,
                                                      prev_close, day_high, day_low, open_price,
                                                      change_pct, volume, currency, last_updated, is_active)
                                    VALUES ($1, $2, 'NSE', 'IN', $3, $4, $5, $6, $7, $8, $9, 'INR', $10, TRUE)
                                    ON CONFLICT (symbol, exchange)
                                    DO UPDATE SET
                                        name = COALESCE(EXCLUDED.name, stocks.name),
                                        current_price = EXCLUDED.current_price,
                                        prev_close = EXCLUDED.prev_close,
                                        day_high = EXCLUDED.day_high,
                                        day_low = EXCLUDED.day_low,
                                        open_price = EXCLUDED.open_price,
                                        change_pct = EXCLUDED.change_pct,
                                        volume = EXCLUDED.volume,
                                        last_updated = EXCLUDED.last_updated
                                    """,
                                    symbol,
                                    stock.get("companyName", symbol),
                                    _to_decimal(stock.get("lastPrice")),
                                    _to_decimal(stock.get("previousClose")),
                                    _to_decimal(stock.get("dayHigh")),
                                    _to_decimal(stock.get("dayLow")),
                                    _to_decimal(stock.get("open")),
                                    _to_decimal(stock.get("pChange")),
                                    _to_int(stock.get("totalTradedVolume")),
                                    datetime.now(timezone.utc),
                                )
                                total_count += 1
                            except Exception as e:
                                logger.debug(f"Error upserting {symbol}: {e}")

                    await asyncio.sleep(settings.NSE_REQUEST_DELAY)

                except Exception as e:
                    logger.warning(f"Error fetching NSE index {index_name}: {e}")
                    continue

    except Exception as e:
        logger.error(f"NSE all stocks fetch failed: {e}")

    logger.info(f"NSE total stocks updated: {total_count}")
    return total_count


async def fetch_nse_dividends():
    """Fetch upcoming corporate actions (dividends) from NSE."""
    logger.info("Fetching NSE dividend data...")

    try:
        async with get_nse_session() as client:
            resp = await client.get(
                f"{NSE_API}/corporates-corporateActions",
                params={"index": "equities", "from_date": "", "to_date": ""},
            )

            if resp.status_code != 200:
                logger.warning(f"NSE dividends returned {resp.status_code}")
                return 0

            actions = resp.json()
            if not isinstance(actions, list):
                actions = actions.get("data", []) if isinstance(actions, dict) else []

            pool = await get_pool()
            count = 0

            async with pool.acquire() as conn:
                for action in actions:
                    try:
                        purpose = action.get("subject", "").lower()
                        if "dividend" not in purpose:
                            continue

                        symbol = action.get("symbol", "").strip()
                        ex_date = _parse_date(action.get("exDate"))
                        record_date = _parse_date(action.get("recDate"))

                        # Extract amount from purpose string
                        amount = _extract_dividend_amount(purpose)

                        # Determine dividend type
                        div_type = "INTERIM"
                        if "final" in purpose:
                            div_type = "FINAL"
                        elif "special" in purpose:
                            div_type = "SPECIAL"

                        # Get stock_id
                        stock = await conn.fetchrow(
                            "SELECT id FROM stocks WHERE symbol = $1 AND exchange = 'NSE'",
                            symbol,
                        )

                        await conn.execute(
                            """
                            INSERT INTO dividends (stock_id, symbol, exchange, company_name,
                                                  dividend_type, amount, ex_date, record_date, status)
                            VALUES ($1, $2, 'NSE', $3, $4, $5, $6, $7, $8)
                            ON CONFLICT DO NOTHING
                            """,
                            stock["id"] if stock else None,
                            symbol,
                            action.get("comp", symbol),
                            div_type,
                            amount,
                            ex_date,
                            record_date,
                            _dividend_status(ex_date),
                        )
                        count += 1
                    except Exception as e:
                        logger.debug(f"Error inserting dividend: {e}")

            logger.info(f"NSE dividends updated: {count}")
            return count

    except Exception as e:
        logger.error(f"NSE dividend fetch failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _to_decimal(value):
    """Convert a value to Decimal, returning None if invalid."""
    if value is None or value == "" or value == "-":
        return None
    try:
        cleaned = str(value).replace(",", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _to_int(value):
    """Convert a value to int, returning None if invalid."""
    if value is None or value == "" or value == "-":
        return None
    try:
        cleaned = str(value).replace(",", "").strip()
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _parse_date(date_str):
    """Parse various date formats from NSE."""
    if not date_str or date_str == "-":
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            from datetime import date
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _extract_dividend_amount(purpose: str) -> float | None:
    """Extract dividend amount from purpose string like 'dividend rs 5 per share'."""
    import re
    # Match patterns like "Rs. 5", "Rs 5.50", "₹ 5"
    patterns = [
        r"rs\.?\s*(\d+\.?\d*)",
        r"₹\s*(\d+\.?\d*)",
        r"(\d+\.?\d*)\s*(?:per|/)\s*(?:share|shr)",
        r"(\d+\.?\d*)\s*%",
    ]
    for pattern in patterns:
        match = re.search(pattern, purpose, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _dividend_status(ex_date) -> str:
    """Determine dividend status based on ex-date."""
    if not ex_date:
        return "upcoming"
    from datetime import date
    today = date.today()
    if ex_date > today:
        return "upcoming"
    elif ex_date == today:
        return "pending"
    else:
        return "paid"
