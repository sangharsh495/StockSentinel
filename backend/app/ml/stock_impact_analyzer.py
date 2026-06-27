"""
Stock Impact Analyzer — ML engine that reads news and determines:

1. Which stocks are affected (beyond simple word matching)
2. Dividend detection from headlines (auto-creates dividend entries)
3. Impact score (-1.0 to +1.0) for how market-moving the news is
4. Impact direction per affected stock (BULLISH / BEARISH / NEUTRAL)

Works 100% offline — uses VADER + keyword heuristics + fuzzy matching.
No external API calls required.
"""

import re
import logging
import json
from datetime import datetime, timezone, date
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.database import get_pool

logger = logging.getLogger(__name__)

# Initialize VADER once
_vader = SentimentIntensityAnalyzer()

# ---------------------------------------------------------------------------
# Dividend detection patterns
# ---------------------------------------------------------------------------
DIVIDEND_PATTERNS = [
    # "declares/announces/recommends dividend of Rs X"
    re.compile(
        r"(?:declare|announce|recommend|approve|propose)[sd]?\s+"
        r"(?:an?\s+)?(?:interim|final|special|total)?\s*dividend\s+"
        r"(?:of\s+)?(?:rs\.?|₹|inr|usd|\$)\s*(\d+\.?\d*)",
        re.IGNORECASE,
    ),
    # "dividend Rs X per share"
    re.compile(
        r"dividend\s+(?:of\s+)?(?:rs\.?|₹|inr)\s*(\d+\.?\d*)\s*(?:per\s+share)?",
        re.IGNORECASE,
    ),
    # "Rs X dividend" / "$X dividend"
    re.compile(
        r"(?:rs\.?|₹|inr|usd|\$)\s*(\d+\.?\d*)\s+(?:per\s+share\s+)?dividend",
        re.IGNORECASE,
    ),
    # "X% dividend"
    re.compile(
        r"(\d+\.?\d*)%?\s+(?:per\s+cent\s+)?dividend",
        re.IGNORECASE,
    ),
    # "dividend of X%"
    re.compile(
        r"dividend\s+of\s+(\d+\.?\d*)\s*%",
        re.IGNORECASE,
    ),
]

# Keywords that strongly indicate dividend news
DIVIDEND_KEYWORDS = [
    "ex-date", "ex date", "record date", "payment date",
    "declares dividend", "announces dividend", "interim dividend",
    "final dividend", "special dividend", "dividend payout",
    "dividend yield", "dividend announced", "dividend declared",
    "recommends dividend", "approves dividend",
]

# ---------------------------------------------------------------------------
# Sector / Industry keyword → stock mapping
# ---------------------------------------------------------------------------
SECTOR_KEYWORDS = {
    # Indian sectors
    "it sector": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    "banking": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BANKBARODA"],
    "bank stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
    "auto sector": ["MARUTI", "TATAMOTORS", "M&M", "HEROMOTOCO", "BAJAJ-AUTO", "EICHERMOT"],
    "auto stocks": ["MARUTI", "TATAMOTORS", "M&M", "HEROMOTOCO", "BAJAJ-AUTO"],
    "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP"],
    "pharma stocks": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"],
    "fmcg": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO"],
    "metal stocks": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "COALINDIA"],
    "oil and gas": ["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL"],
    "energy sector": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "ADANIGREEN"],
    "telecom": ["BHARTIARTL", "RELIANCE", "IDEA"],
    "real estate": ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "BRIGADE"],
    "cement": ["ULTRACEMCO", "SHREECEM", "AMBUJACEM", "ACC", "RAMCOCEM"],

    # US sectors
    "tech stocks": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "big tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
    "semiconductor": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM"],
    "chip stocks": ["NVDA", "AMD", "INTC", "TSM", "AVGO"],
    "ev stocks": ["TSLA", "RIVN", "LCID", "NIO", "LI"],
    "ai stocks": ["NVDA", "MSFT", "GOOGL", "META", "AMD", "PLTR"],
    "social media": ["META", "SNAP", "PINS", "RDDT"],
    "streaming": ["NFLX", "DIS", "PARA", "WBD"],
    "cloud computing": ["AMZN", "MSFT", "GOOGL", "CRM", "SNOW"],
}

# Market-wide keywords
MARKET_KEYWORDS_BULLISH = [
    "rally", "surge", "soar", "jump", "gain", "record high", "all-time high",
    "breakout", "bull run", "strong earnings", "beat estimates", "upgrade",
    "outperform", "buy rating", "rate cut", "stimulus", "recovery",
    "expansion", "growth", "profit surge", "revenue beat", "market rally",
]

MARKET_KEYWORDS_BEARISH = [
    "crash", "plunge", "slump", "tank", "drop", "sell-off", "selloff",
    "bear market", "recession", "downgrade", "underperform", "sell rating",
    "rate hike", "inflation surge", "layoff", "fraud", "scandal",
    "default", "bankruptcy", "shutdown", "loss widens", "miss estimates",
    "market crash", "correction", "profit warning",
]


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------
class StockImpactAnalyzer:
    """Analyzes news headlines for stock impact, dividend detection, and sentiment."""

    def __init__(self):
        self._stock_cache = {}       # {symbol_upper: stock_id}
        self._name_cache = {}        # {name_upper: symbol}
        self._cache_loaded = False

    async def _load_stock_cache(self):
        """Load all stock symbols and names into memory for fast matching."""
        if self._cache_loaded:
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, symbol, name FROM stocks WHERE is_active = TRUE"
            )

        self._stock_cache = {}
        self._name_cache = {}
        for row in rows:
            sym = row["symbol"].upper()
            self._stock_cache[sym] = row["id"]
            if row["name"] and len(row["name"]) > 3:
                self._name_cache[row["name"].upper()] = sym

        self._cache_loaded = True
        logger.info(f"Stock cache loaded: {len(self._stock_cache)} symbols, {len(self._name_cache)} names")

    def _find_affected_stocks(self, title: str) -> list[dict]:
        """
        Find stocks affected by this headline using multiple strategies:
        1. Exact symbol match (word boundary)
        2. Company name substring match
        3. Sector/industry keyword mapping
        """
        title_upper = title.upper()
        found = {}  # symbol → {stock_id, reason}

        # Strategy 1: Exact symbol match (word boundary check)
        words = re.findall(r'\b[A-Z][A-Z0-9&.-]{1,19}\b', title_upper)
        for word in words:
            cleaned = word.strip(".,;:!?()[]")
            if cleaned in self._stock_cache and len(cleaned) >= 2:
                # Skip very common English words that happen to be tickers
                if cleaned in {"AN", "IT", "IS", "AT", "IN", "ON", "TO", "OR",
                              "BE", "DO", "GO", "NO", "SO", "UP", "US", "AM",
                              "AS", "BY", "IF", "OF", "HE", "ME", "WE"}:
                    continue
                found[cleaned] = {
                    "stock_id": self._stock_cache[cleaned],
                    "reason": "mentioned in headline",
                }

        # Strategy 2: Company name substring match
        for name, symbol in self._name_cache.items():
            if len(name) > 4 and name in title_upper:
                if symbol not in found:
                    found[symbol] = {
                        "stock_id": self._stock_cache.get(symbol),
                        "reason": f"company name '{name.title()}' matched",
                    }

        # Strategy 3: Sector/industry keyword mapping
        title_lower = title.lower()
        for keyword, symbols in SECTOR_KEYWORDS.items():
            if keyword in title_lower:
                for sym in symbols[:3]:  # Max 3 stocks per sector mention
                    if sym in self._stock_cache and sym not in found:
                        found[sym] = {
                            "stock_id": self._stock_cache[sym],
                            "reason": f"sector '{keyword}' mentioned",
                        }

        return [
            {"symbol": sym, "stock_id": data["stock_id"], "reason": data["reason"]}
            for sym, data in found.items()
        ][:10]  # Max 10 affected stocks per headline

    def _detect_dividend(self, title: str) -> dict | None:
        """
        Detect dividend information from a headline.
        Returns {amount, type, detected: True} or None.
        """
        title_lower = title.lower()

        # Check for dividend keywords
        has_dividend_keyword = any(kw in title_lower for kw in DIVIDEND_KEYWORDS)
        if not has_dividend_keyword and "dividend" not in title_lower:
            return None

        # Try to extract amount
        amount = None
        for pattern in DIVIDEND_PATTERNS:
            match = pattern.search(title)
            if match:
                try:
                    amount = float(match.group(1))
                except (ValueError, IndexError):
                    pass
                break

        # Determine type
        div_type = "INTERIM"
        if "final" in title_lower:
            div_type = "FINAL"
        elif "special" in title_lower:
            div_type = "SPECIAL"

        return {
            "detected": True,
            "amount": amount,
            "type": div_type,
        }

    def _calculate_impact_score(self, title: str, sentiment: str | None) -> float:
        """
        Calculate how market-moving this news is (0.0 to 1.0).
        Combines VADER intensity + keyword analysis.
        """
        title_lower = title.lower()

        # VADER compound score (absolute value = intensity)
        vader_scores = _vader.polarity_scores(title)
        vader_intensity = abs(vader_scores["compound"])

        # Keyword boost
        keyword_boost = 0.0
        for kw in MARKET_KEYWORDS_BULLISH + MARKET_KEYWORDS_BEARISH:
            if kw in title_lower:
                keyword_boost += 0.1

        # Dividend news gets a boost
        if "dividend" in title_lower:
            keyword_boost += 0.15

        # IPO / listing news gets a boost
        if any(w in title_lower for w in ["ipo", "listing", "debut"]):
            keyword_boost += 0.1

        # Earnings / results get a boost
        if any(w in title_lower for w in ["earnings", "results", "revenue", "profit", "loss"]):
            keyword_boost += 0.1

        # Combine: 60% VADER + 40% keyword, capped at 1.0
        score = min(vader_intensity * 0.6 + keyword_boost * 0.4, 1.0)
        return round(score, 4)

    def _determine_impact_direction(self, title: str, stock_symbol: str) -> str:
        """Determine BULLISH/BEARISH/NEUTRAL impact on a specific stock."""
        title_lower = title.lower()

        bullish_count = sum(1 for kw in MARKET_KEYWORDS_BULLISH if kw in title_lower)
        bearish_count = sum(1 for kw in MARKET_KEYWORDS_BEARISH if kw in title_lower)

        # VADER for overall tone
        vader = _vader.polarity_scores(title)
        if vader["compound"] >= 0.15:
            bullish_count += 1
        elif vader["compound"] <= -0.15:
            bearish_count += 1

        if bullish_count > bearish_count:
            return "BULLISH"
        elif bearish_count > bullish_count:
            return "BEARISH"
        return "NEUTRAL"

    async def analyze_news_batch(self, news_ids: list[int] | None = None, limit: int = 100):
        """
        Analyze a batch of unprocessed news articles.
        If news_ids is None, fetches all unanalyzed news.

        For each article:
        1. Finds affected stocks
        2. Detects dividends
        3. Calculates impact score
        4. Saves results to DB
        """
        await self._load_stock_cache()

        pool = await get_pool()

        # Fetch unanalyzed news
        async with pool.acquire() as conn:
            if news_ids:
                rows = await conn.fetch(
                    """
                    SELECT id, title, sentiment FROM news
                    WHERE id = ANY($1)
                    """,
                    news_ids,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, title, sentiment FROM news
                    WHERE affected_stocks = '[]'::jsonb
                      AND published_at > NOW() - INTERVAL '3 days'
                    ORDER BY published_at DESC
                    LIMIT $1
                    """,
                    limit,
                )

        if not rows:
            logger.info("No news to analyze for stock impact")
            return 0

        logger.info(f"Analyzing stock impact for {len(rows)} articles")

        count = 0
        dividend_count = 0

        async with pool.acquire() as conn:
            for row in rows:
                try:
                    news_id = row["id"]
                    title = row["title"]
                    sentiment = row.get("sentiment")

                    # 1. Find affected stocks
                    affected = self._find_affected_stocks(title)

                    # 2. Detect dividend
                    div_info = self._detect_dividend(title)
                    dividend_detected = div_info is not None

                    # 3. Calculate impact score
                    impact_score = self._calculate_impact_score(title, sentiment)

                    # 4. Build affected_stocks JSON with impact direction
                    affected_json = []
                    for stock in affected:
                        direction = self._determine_impact_direction(title, stock["symbol"])
                        affected_json.append({
                            "symbol": stock["symbol"],
                            "impact": impact_score,
                            "direction": direction,
                            "reason": stock["reason"],
                        })

                    # 5. Update news record
                    await conn.execute(
                        """
                        UPDATE news SET
                            impact_score = $1,
                            affected_stocks = $2::jsonb,
                            dividend_detected = $3,
                            related_symbols = $4
                        WHERE id = $5
                        """,
                        impact_score,
                        json.dumps(affected_json),
                        dividend_detected,
                        [s["symbol"] for s in affected][:5],
                        news_id,
                    )

                    # 6. Insert into news_stock_impact junction table
                    for stock in affected:
                        direction = self._determine_impact_direction(title, stock["symbol"])
                        try:
                            await conn.execute(
                                """
                                INSERT INTO news_stock_impact
                                    (news_id, stock_id, symbol, impact_direction, impact_score, reason)
                                VALUES ($1, $2, $3, $4, $5, $6)
                                ON CONFLICT (news_id, symbol) DO UPDATE SET
                                    impact_direction = EXCLUDED.impact_direction,
                                    impact_score = EXCLUDED.impact_score
                                """,
                                news_id,
                                stock.get("stock_id"),
                                stock["symbol"],
                                direction,
                                impact_score,
                                stock["reason"][:200],
                            )
                        except Exception as e:
                            logger.debug(f"Error inserting stock impact: {e}")

                    # 7. Auto-create dividend entry if detected
                    if dividend_detected and affected:
                        await self._auto_create_dividend(conn, title, affected, div_info)
                        dividend_count += 1

                    count += 1

                except Exception as e:
                    logger.debug(f"Error analyzing news {row.get('id')}: {e}")

        logger.info(
            f"Stock impact analysis complete: {count} articles analyzed, "
            f"{dividend_count} dividends detected"
        )
        return count

    async def _auto_create_dividend(self, conn, title: str, affected: list[dict], div_info: dict):
        """Auto-create a dividend entry when news headline mentions a dividend."""
        for stock in affected[:1]:  # Primary stock only
            symbol = stock["symbol"]
            stock_id = stock.get("stock_id")

            # Check if this dividend already exists (avoid duplicates)
            existing = await conn.fetchrow(
                """
                SELECT id FROM dividends
                WHERE symbol = $1
                  AND created_at > NOW() - INTERVAL '7 days'
                  AND company_name ILIKE $2
                """,
                symbol,
                f"%{symbol}%",
            )

            if existing:
                continue

            # Get stock's exchange
            stock_row = await conn.fetchrow(
                "SELECT exchange, name FROM stocks WHERE id = $1",
                stock_id,
            )

            try:
                await conn.execute(
                    """
                    INSERT INTO dividends (stock_id, symbol, exchange, company_name,
                                          dividend_type, amount, status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'upcoming')
                    ON CONFLICT DO NOTHING
                    """,
                    stock_id,
                    symbol,
                    stock_row["exchange"] if stock_row else "NSE",
                    stock_row["name"] if stock_row else symbol,
                    div_info.get("type", "INTERIM"),
                    div_info.get("amount"),
                )
                logger.info(
                    f"Auto-created dividend entry: {symbol} "
                    f"({div_info.get('type')}, ₹{div_info.get('amount', 'TBD')})"
                )
            except Exception as e:
                logger.debug(f"Error auto-creating dividend for {symbol}: {e}")


# Module-level singleton
_analyzer = StockImpactAnalyzer()


async def run_stock_impact_analysis(limit: int = 100) -> int:
    """Entry point for the scheduler — analyzes unprocessed news."""
    return await _analyzer.analyze_news_batch(limit=limit)
