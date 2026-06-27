"""
News Scraper — fetches headlines from 10+ RSS feeds.
"""

import logging
import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import feedparser
from app.database import get_pool

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)

RSS_FEEDS = {
    # --- India Financial News (direct, fast) ---
    "Moneycontrol": "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "ET Markets": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "LiveMint": "https://www.livemint.com/rss/markets",
    "Mint Markets": "https://www.livemint.com/rss/money",
    "CNBC TV18": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market-buzz.xml",
    "CNBC TV18 Markets": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "Financial Express": "https://www.financialexpress.com/market/feed/",
    "NDTV Profit": "https://feeds.feedburner.com/ndtvprofit-latest",

    # --- US/International ---
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "MarketWatch": "https://feeds.marketwatch.com/marketwatch/topstories/",

    # --- Google News (real-time aggregated) ---
    "Google News NSE": "https://news.google.com/rss/search?q=NSE+stocks+India&hl=en-IN&gl=IN&ceid=IN:en",
    "Google News Nifty": "https://news.google.com/rss/search?q=Nifty+Sensex+market&hl=en-IN&gl=IN&ceid=IN:en",
    "Google News US": "https://news.google.com/rss/search?q=US+stock+market+S%26P+NASDAQ&hl=en-US&gl=US&ceid=US:en",
}


def _parse_feeds_sync() -> list[dict]:
    """Parse all RSS feeds synchronously (runs in thread pool)."""
    import urllib.request
    articles = []

    for source, url in RSS_FEEDS.items():
        try:
            # feedparser with timeout to prevent hanging
            feed = feedparser.parse(url, request_headers={
                "User-Agent": "Mozilla/5.0 (StockSentinel/1.0)"
            })
            # Skip feeds that returned errors
            if feed.bozo and not feed.entries:
                logger.warning(f"Feed {source} returned error, skipping")
                continue
            for entry in feed.entries[:20]:  # Max 20 per source
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()

                if not title or not link:
                    continue

                # Parse published date
                published = None
                for date_field in ("published_parsed", "updated_parsed"):
                    parsed = entry.get(date_field)
                    if parsed:
                        try:
                            import time
                            published = datetime.fromtimestamp(
                                time.mktime(parsed), tz=timezone.utc
                            )
                        except Exception:
                            pass
                        break

                if not published:
                    published = datetime.now(timezone.utc)

                # Extract summary
                summary = entry.get("summary", "")
                if summary:
                    from bs4 import BeautifulSoup
                    summary = BeautifulSoup(summary, "html.parser").get_text()[:300]

                articles.append({
                    "title": title[:500],
                    "url": link[:1000],
                    "source": source,
                    "published_at": published,
                    "summary": summary,
                })

        except Exception as e:
            logger.warning(f"Error parsing RSS feed {source}: {e}")

    return articles


async def fetch_news():
    """Fetch news from all RSS feeds and insert into database."""
    logger.info("Fetching news from RSS feeds...")

    loop = asyncio.get_event_loop()
    articles = await loop.run_in_executor(_executor, _parse_feeds_sync)

    if not articles:
        logger.warning("No articles fetched from RSS feeds")
        return 0

    logger.info(f"Parsed {len(articles)} articles from RSS feeds")

    pool = await get_pool()
    count = 0

    async with pool.acquire() as conn:
        for article in articles:
            try:
                # Insert, skip if URL already exists
                result = await conn.execute(
                    """
                    INSERT INTO news (title, url, source, published_at, summary, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    ON CONFLICT (url) DO NOTHING
                    """,
                    article["title"],
                    article["url"],
                    article["source"],
                    article["published_at"],
                    article.get("summary"),
                )
                if "INSERT" in result:
                    count += 1
            except Exception as e:
                logger.debug(f"Error inserting article: {e}")

    logger.info(f"New articles inserted: {count}")
    return count


async def extract_related_symbols():
    """
    Post-process: match stock symbols mentioned in headlines.
    Runs after news fetch to tag related stocks.
    """
    logger.info("Extracting related stock symbols from headlines...")

    pool = await get_pool()

    async with pool.acquire() as conn:
        # Get untagged news
        news_items = await conn.fetch(
            """
            SELECT id, title FROM news
            WHERE related_symbols IS NULL
            ORDER BY published_at DESC
            LIMIT 100
            """
        )

        if not news_items:
            return 0

        # Get all stock symbols for matching
        stocks = await conn.fetch(
            "SELECT symbol, name FROM stocks WHERE is_active = TRUE"
        )

        symbol_set = {s["symbol"].upper() for s in stocks}
        name_map = {s["name"].upper(): s["symbol"] for s in stocks if s["name"]}

        count = 0
        for item in news_items:
            title_upper = item["title"].upper()
            found_symbols = []

            # Check for exact symbol matches (words)
            words = title_upper.split()
            for word in words:
                cleaned = word.strip(".,;:!?()[]")
                if cleaned in symbol_set and len(cleaned) >= 2:
                    found_symbols.append(cleaned)

            # Check for company name matches
            for name, symbol in name_map.items():
                if len(name) > 4 and name in title_upper:
                    if symbol not in found_symbols:
                        found_symbols.append(symbol)

            if found_symbols:
                await conn.execute(
                    "UPDATE news SET related_symbols = $1 WHERE id = $2",
                    found_symbols[:5],  # Max 5 symbols per article
                    item["id"],
                )
                count += 1
            else:
                # Mark as processed (empty array)
                await conn.execute(
                    "UPDATE news SET related_symbols = $1 WHERE id = $2",
                    [],
                    item["id"],
                )

    logger.info(f"Tagged {count} articles with related symbols")
    return count


async def cleanup_old_news():
    """Delete news older than retention period to keep DB small."""
    from app.config import settings

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM news
            WHERE created_at < NOW() - $1 * INTERVAL '1 day'
            """,
            settings.NEWS_RETENTION_DAYS,
        )
        deleted = int(result.split()[-1]) if result else 0
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old news articles")
        return deleted
