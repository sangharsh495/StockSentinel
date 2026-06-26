"""
US Stock Scraper — fetches US stock prices via yfinance and stock lists via Finnhub.
"""

import logging
import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# Thread pool for blocking yfinance calls
_executor = ThreadPoolExecutor(max_workers=2)


def _fetch_us_prices_sync(symbols: list[str]) -> dict:
    """
    Synchronous yfinance batch download (runs in thread pool).
    Returns dict of {symbol: {price, prev_close, change_pct, ...}}
    """
    import yfinance as yf

    results = {}
    chunk_size = settings.YFINANCE_CHUNK_SIZE

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        try:
            tickers = yf.Tickers(" ".join(chunk))
            for sym in chunk:
                try:
                    ticker = tickers.tickers.get(sym)
                    if not ticker:
                        continue

                    info = ticker.fast_info
                    results[sym] = {
                        "current_price": getattr(info, "last_price", None),
                        "prev_close": getattr(info, "previous_close", None),
                        "day_high": getattr(info, "day_high", None),
                        "day_low": getattr(info, "day_low", None),
                        "open_price": getattr(info, "open", None),
                        "volume": getattr(info, "last_volume", None),
                        "market_cap": getattr(info, "market_cap", None),
                    }

                    # Calculate change percentage
                    price = results[sym]["current_price"]
                    prev = results[sym]["prev_close"]
                    if price and prev and prev > 0:
                        results[sym]["change_pct"] = round(
                            (price - prev) / prev * 100, 4
                        )
                    else:
                        results[sym]["change_pct"] = None

                except Exception as e:
                    logger.debug(f"Error fetching {sym}: {e}")

            import time
            time.sleep(1)  # Rate limit between chunks

        except Exception as e:
            logger.warning(f"yfinance chunk error: {e}")

    return results


async def fetch_us_stock_list():
    """
    Fetch the full list of US stocks from Finnhub.
    Only needs to run once or daily to populate the stock list.
    """
    logger.info("Fetching US stock list from Finnhub...")

    if not settings.FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set — skipping US stock list")
        return 0

    import finnhub

    try:
        client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)

        # Get US stock symbols
        symbols = client.stock_symbols("US")
        logger.info(f"Finnhub returned {len(symbols)} US symbols")

        pool = await get_pool()
        count = 0

        async with pool.acquire() as conn:
            for stock in symbols:
                try:
                    symbol = stock.get("symbol", "").strip()
                    name = stock.get("description", symbol)
                    mic = stock.get("mic", "")

                    # Skip OTC, warrants, etc.
                    s_type = stock.get("type", "").upper()
                    if s_type not in ("", "COMMON STOCK", "EQS", "ADR"):
                        continue

                    # Determine exchange
                    exchange = "NYSE"
                    if "XNAS" in mic or "NASDAQ" in mic.upper():
                        exchange = "NASDAQ"

                    await conn.execute(
                        """
                        INSERT INTO stocks (symbol, name, exchange, market, currency, is_active)
                        VALUES ($1, $2, $3, 'US', 'USD', TRUE)
                        ON CONFLICT (symbol, exchange)
                        DO UPDATE SET name = COALESCE(EXCLUDED.name, stocks.name)
                        """,
                        symbol,
                        name[:200],
                        exchange,
                    )
                    count += 1
                except Exception as e:
                    logger.debug(f"Error inserting US stock {stock.get('symbol')}: {e}")

        logger.info(f"US stock list populated: {count} stocks")
        return count

    except Exception as e:
        logger.error(f"Finnhub stock list fetch failed: {e}")
        return 0


async def fetch_us_prices():
    """Fetch latest US stock prices using yfinance."""
    logger.info("Fetching US stock prices...")

    pool = await get_pool()

    # Get all US stock symbols from database
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT symbol FROM stocks WHERE market = 'US' AND is_active = TRUE"
        )

    symbols = [row["symbol"] for row in rows]
    if not symbols:
        logger.info("No US stocks to update")
        return 0

    logger.info(f"Fetching prices for {len(symbols)} US stocks...")

    # Run yfinance in thread pool (it's blocking)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(_executor, _fetch_us_prices_sync, symbols)

    # Update database
    count = 0
    async with pool.acquire() as conn:
        for symbol, data in results.items():
            try:
                await conn.execute(
                    """
                    UPDATE stocks SET
                        current_price = $1,
                        prev_close = $2,
                        day_high = $3,
                        day_low = $4,
                        open_price = $5,
                        volume = $6,
                        market_cap = $7,
                        change_pct = $8,
                        last_updated = $9
                    WHERE symbol = $10 AND market = 'US'
                    """,
                    data.get("current_price"),
                    data.get("prev_close"),
                    data.get("day_high"),
                    data.get("day_low"),
                    data.get("open_price"),
                    data.get("volume"),
                    data.get("market_cap"),
                    data.get("change_pct"),
                    datetime.now(timezone.utc),
                    symbol,
                )
                count += 1
            except Exception as e:
                logger.debug(f"Error updating {symbol}: {e}")

    logger.info(f"US stock prices updated: {count}")
    return count


async def fetch_market_indices():
    """Fetch key market indices (NIFTY, SENSEX, S&P 500, NASDAQ Composite)."""
    logger.info("Fetching market indices...")

    indices = {
        "^NSEI": ("NIFTY 50", "IN", "NSE"),
        "^BSESN": ("SENSEX", "IN", "BSE"),
        "^GSPC": ("S&P 500", "US", "NYSE"),
        "^IXIC": ("NASDAQ Composite", "US", "NASDAQ"),
        "^DJI": ("Dow Jones", "US", "NYSE"),
    }

    symbols = list(indices.keys())
    results = await asyncio.get_event_loop().run_in_executor(
        _executor, _fetch_us_prices_sync, symbols
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        for symbol, data in results.items():
            name, market, exchange = indices.get(symbol, ("", "", ""))
            try:
                await conn.execute(
                    """
                    INSERT INTO stocks (symbol, name, exchange, market, current_price,
                                      prev_close, day_high, day_low, open_price,
                                      change_pct, currency, last_updated, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, TRUE)
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
                    name,
                    exchange,
                    market,
                    data.get("current_price"),
                    data.get("prev_close"),
                    data.get("day_high"),
                    data.get("day_low"),
                    data.get("open_price"),
                    data.get("change_pct"),
                    "INR" if market == "IN" else "USD",
                    datetime.now(timezone.utc),
                )
            except Exception as e:
                logger.debug(f"Error updating index {symbol}: {e}")

    logger.info(f"Market indices updated: {len(results)}")
    return len(results)
