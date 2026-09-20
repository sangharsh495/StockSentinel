"""
Live Quote Service — Real-time on-demand market data synchronization.
Fetches live market quotes for stocks and indices via yfinance with
caching and background database synchronization.
"""

import time
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List
import yfinance as yf

from app.database import execute, fetchrow

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)

# In-memory fast cache: ticker -> {quote, expires_at}
_live_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 180  # 3 minutes for live quotes


class LiveQuoteService:
    """Provides up-to-date, live market price fetching."""

    INDEX_SYMBOLS = [
        ("^NSEI", "NIFTY 50", "IN", "INR"),
        ("^BSESN", "SENSEX", "IN", "INR"),
        ("^GSPC", "S&P 500", "US", "USD"),
        ("^IXIC", "NASDAQ", "US", "USD"),
    ]

    @staticmethod
    def get_yf_ticker(symbol: str, exchange: str = "NSE") -> str:
        clean = symbol.strip().upper()
        if clean.startswith("^"):
            return clean
        if exchange.upper() == "NSE":
            return f"{clean}.NS"
        elif exchange.upper() == "BSE":
            return f"{clean}.BO"
        return clean

    def _sync_fetch_quote(self, yf_ticker: str) -> Optional[Dict[str, Any]]:
        """Synchronously fetch quote from yfinance."""
        try:
            ticker = yf.Ticker(yf_ticker)
            fast = ticker.fast_info

            price = getattr(fast, "last_price", None)
            prev_close = getattr(fast, "previous_close", None)
            day_high = getattr(fast, "day_high", None)
            day_low = getattr(fast, "day_low", None)
            volume = getattr(fast, "last_volume", None)

            if price is None:
                # Try regular history 1d
                hist = ticker.history(period="2d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
                    day_high = float(hist["High"].iloc[-1])
                    day_low = float(hist["Low"].iloc[-1])
                    volume = int(hist["Volume"].iloc[-1])

            if price is None:
                return None

            change_pct = 0.0
            if prev_close and prev_close > 0:
                change_pct = round(((price - prev_close) / prev_close) * 100, 2)

            return {
                "current_price": round(float(price), 2),
                "prev_close": round(float(prev_close), 2) if prev_close else round(float(price), 2),
                "change_pct": change_pct,
                "day_high": round(float(day_high), 2) if day_high else None,
                "day_low": round(float(day_low), 2) if day_low else None,
                "volume": int(volume) if volume else None,
                "is_live": True,
            }
        except Exception as e:
            logger.debug(f"Live quote fetch failed for {yf_ticker}: {e}")
            return None

    async def get_live_quote(self, symbol: str, exchange: str = "NSE") -> Optional[Dict[str, Any]]:
        """
        Fetch real-time live market quote.
        Updates local cache and syncs with database.
        """
        yf_ticker = self.get_yf_ticker(symbol, exchange)
        now = time.time()

        # Check memory cache
        if yf_ticker in _live_cache:
            entry = _live_cache[yf_ticker]
            if now < entry["expires_at"]:
                return entry["data"]

        # Run in thread pool
        loop = asyncio.get_event_loop()
        quote = await loop.run_in_executor(_executor, self._sync_fetch_quote, yf_ticker)

        if quote:
            _live_cache[yf_ticker] = {
                "data": quote,
                "expires_at": now + CACHE_TTL,
            }
            # Background DB update
            asyncio.create_task(self._update_db_price(symbol, exchange, quote))

        return quote

    async def _update_db_price(self, symbol: str, exchange: str, quote: Dict[str, Any]):
        """Persist live price in the stocks table."""
        try:
            await execute(
                """
                UPDATE stocks
                SET current_price = $1,
                    prev_close = $2,
                    change_pct = $3,
                    day_high = COALESCE($4, day_high),
                    day_low = COALESCE($5, day_low),
                    volume = COALESCE($6, volume),
                    last_updated = NOW()
                WHERE UPPER(symbol) = $7 AND UPPER(exchange) = $8
                """,
                quote["current_price"],
                quote["prev_close"],
                quote["change_pct"],
                quote.get("day_high"),
                quote.get("day_low"),
                quote.get("volume"),
                symbol.upper(),
                exchange.upper(),
            )
        except Exception as e:
            logger.debug(f"Failed to update live price in DB for {symbol}: {e}")

    async def get_live_indices(self) -> List[Dict[str, Any]]:
        """Get live quotes for major market indices."""
        INDEX_DEFAULTS = {
            "^NSEI": (25385.50, 25290.00, 0.38),
            "^BSESN": (82920.80, 82610.20, 0.35),
            "^GSPC": (5685.20, 5640.10, 0.80),
            "^IXIC": (17950.40, 17820.00, 0.90),
        }

        results = []
        for symbol, name, market, currency in self.INDEX_SYMBOLS:
            quote = await self.get_live_quote(symbol, exchange="INDEX")
            if not quote or quote.get("current_price") is None:
                # Fallback to database
                row = await fetchrow(
                    "SELECT current_price, prev_close, change_pct, last_updated FROM stocks WHERE symbol = $1",
                    symbol,
                )
                if row and row.get("current_price") is not None:
                    quote = {
                        "current_price": float(row["current_price"]),
                        "prev_close": float(row["prev_close"]) if row.get("prev_close") else None,
                        "change_pct": float(row["change_pct"]) if row.get("change_pct") else 0.0,
                        "is_live": False,
                    }
                else:
                    def_p, def_prev, def_chg = INDEX_DEFAULTS.get(symbol, (25000.0, 24900.0, 0.40))
                    quote = {
                        "current_price": def_p,
                        "prev_close": def_prev,
                        "change_pct": def_chg,
                        "is_live": False,
                    }

            cp = float(quote["current_price"]) if quote.get("current_price") is not None else None
            prev_c = float(quote["prev_close"]) if quote.get("prev_close") is not None else None
            chg = float(quote["change_pct"]) if quote.get("change_pct") is not None else 0.0

            item = {
                "symbol": symbol,
                "name": name,
                "market": market,
                "currency": currency,
                "current_price": cp,
                "prev_close": prev_c,
                "change_pct": chg,
                "is_live": quote.get("is_live", False),
            }
            results.append(item)

        return results


live_quote_service = LiveQuoteService()
