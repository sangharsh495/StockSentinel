"""
IPO Scraper — fetches upcoming IPOs from Chittorgarh (India) and Finnhub (US).
"""

import logging
import asyncio
import httpx
from datetime import datetime, timezone, date
from bs4 import BeautifulSoup
from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_india_ipos():
    """Scrape upcoming Indian IPOs from Chittorgarh."""
    logger.info("Fetching India IPO data from Chittorgarh...")

    url = "https://www.chittorgarh.com/report/mainboard-ipo-list-in-india-702/1/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                logger.warning(f"Chittorgarh returned {resp.status_code}")
                return 0

            soup = BeautifulSoup(resp.text, "lxml")

            # Find the IPO table
            tables = soup.find_all("table", class_="table")
            if not tables:
                tables = soup.find_all("table")

            pool = await get_pool()
            count = 0

            for table in tables:
                rows = table.find_all("tr")[1:]  # Skip header

                async with pool.acquire() as conn:
                    for row in rows:
                        cols = row.find_all("td")
                        if len(cols) < 4:
                            continue

                        try:
                            company_name = cols[0].get_text(strip=True)
                            if not company_name:
                                continue

                            # Parse dates
                            open_date = _parse_ipo_date(cols[1].get_text(strip=True) if len(cols) > 1 else "")
                            close_date = _parse_ipo_date(cols[2].get_text(strip=True) if len(cols) > 2 else "")

                            # Parse price band
                            price_text = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                            price_low, price_high = _parse_price_band(price_text)

                            # Parse lot size
                            lot_size = _safe_int(cols[4].get_text(strip=True)) if len(cols) > 4 else None

                            # Parse issue size
                            issue_size = cols[5].get_text(strip=True) if len(cols) > 5 else None

                            # Determine status
                            status = _determine_ipo_status(open_date, close_date)

                            await conn.execute(
                                """
                                INSERT INTO ipos (company_name, market, exchange, price_band_low,
                                                 price_band_high, lot_size, issue_size,
                                                 open_date, close_date, status, source, updated_at)
                                VALUES ($1, 'IN', 'NSE', $2, $3, $4, $5, $6, $7, $8, 'chittorgarh', NOW())
                                ON CONFLICT (company_name, market, open_date)
                                DO UPDATE SET
                                    price_band_low = COALESCE(EXCLUDED.price_band_low, ipos.price_band_low),
                                    price_band_high = COALESCE(EXCLUDED.price_band_high, ipos.price_band_high),
                                    lot_size = COALESCE(EXCLUDED.lot_size, ipos.lot_size),
                                    issue_size = COALESCE(EXCLUDED.issue_size, ipos.issue_size),
                                    close_date = COALESCE(EXCLUDED.close_date, ipos.close_date),
                                    status = EXCLUDED.status,
                                    updated_at = NOW()
                                """,
                                company_name[:200],
                                price_low,
                                price_high,
                                lot_size,
                                issue_size,
                                open_date,
                                close_date,
                                status,
                            )
                            count += 1

                        except Exception as e:
                            logger.debug(f"Error parsing IPO row: {e}")

            # Also try SME IPO page
            await asyncio.sleep(2)
            sme_url = "https://www.chittorgarh.com/report/sme-ipo-list-in-india-702/83/"
            try:
                resp2 = await client.get(sme_url, headers=headers)
                if resp2.status_code == 200:
                    soup2 = BeautifulSoup(resp2.text, "lxml")
                    # Similar parsing logic for SME IPOs
                    sme_tables = soup2.find_all("table", class_="table")
                    if not sme_tables:
                        sme_tables = soup2.find_all("table")

                    async with pool.acquire() as conn:
                        for table in sme_tables:
                            for row in table.find_all("tr")[1:]:
                                cols = row.find_all("td")
                                if len(cols) < 4:
                                    continue
                                try:
                                    name = cols[0].get_text(strip=True)
                                    if not name:
                                        continue
                                    open_d = _parse_ipo_date(cols[1].get_text(strip=True) if len(cols) > 1 else "")
                                    close_d = _parse_ipo_date(cols[2].get_text(strip=True) if len(cols) > 2 else "")
                                    price_t = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                                    p_low, p_high = _parse_price_band(price_t)

                                    await conn.execute(
                                        """
                                        INSERT INTO ipos (company_name, market, exchange, price_band_low,
                                                         price_band_high, open_date, close_date, status,
                                                         source, updated_at)
                                        VALUES ($1, 'IN', 'BSE', $2, $3, $4, $5, $6, 'chittorgarh', NOW())
                                        ON CONFLICT (company_name, market, open_date)
                                        DO UPDATE SET status = EXCLUDED.status, updated_at = NOW()
                                        """,
                                        name[:200], p_low, p_high, open_d, close_d,
                                        _determine_ipo_status(open_d, close_d),
                                    )
                                    count += 1
                                except Exception:
                                    pass
            except Exception:
                pass

            logger.info(f"India IPOs updated: {count}")
            return count

    except Exception as e:
        logger.error(f"India IPO fetch failed: {e}")
        return 0


async def fetch_us_ipos():
    """Fetch upcoming US IPOs from Finnhub."""
    logger.info("Fetching US IPO data from Finnhub...")

    if not settings.FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set — skipping US IPOs")
        return 0

    try:
        import finnhub

        client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)

        # Get IPO calendar
        from datetime import timedelta
        today = date.today()
        from_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=60)).strftime("%Y-%m-%d")

        ipo_calendar = client.ipo_calendar(_from=from_date, to=to_date)
        ipos = ipo_calendar.get("ipoCalendar", [])

        pool = await get_pool()
        count = 0

        async with pool.acquire() as conn:
            for ipo in ipos:
                try:
                    company = ipo.get("name", "Unknown")
                    ipo_date_str = ipo.get("date", "")
                    price_low = ipo.get("priceLow")
                    price_high = ipo.get("priceHigh")
                    shares = ipo.get("numberOfShares")
                    total_value = ipo.get("totalSharesValue")

                    ipo_date = None
                    if ipo_date_str:
                        try:
                            ipo_date = datetime.strptime(ipo_date_str, "%Y-%m-%d").date()
                        except ValueError:
                            pass

                    status = "upcoming"
                    if ipo_date:
                        if ipo_date < today:
                            status = "listed"
                        elif ipo_date == today:
                            status = "open"

                    issue_size_str = None
                    if total_value:
                        if total_value >= 1_000_000_000:
                            issue_size_str = f"${total_value / 1_000_000_000:.1f}B"
                        elif total_value >= 1_000_000:
                            issue_size_str = f"${total_value / 1_000_000:.1f}M"

                    await conn.execute(
                        """
                        INSERT INTO ipos (company_name, market, exchange, price_band_low,
                                         price_band_high, issue_size, open_date, listing_date,
                                         status, source, updated_at)
                        VALUES ($1, 'US', $2, $3, $4, $5, $6, $6, $7, 'finnhub', NOW())
                        ON CONFLICT (company_name, market, open_date)
                        DO UPDATE SET
                            price_band_low = COALESCE(EXCLUDED.price_band_low, ipos.price_band_low),
                            price_band_high = COALESCE(EXCLUDED.price_band_high, ipos.price_band_high),
                            issue_size = COALESCE(EXCLUDED.issue_size, ipos.issue_size),
                            status = EXCLUDED.status,
                            updated_at = NOW()
                        """,
                        company[:200],
                        ipo.get("exchange", "NASDAQ"),
                        price_low,
                        price_high,
                        issue_size_str,
                        ipo_date,
                        status,
                    )
                    count += 1
                except Exception as e:
                    logger.debug(f"Error inserting US IPO: {e}")

        logger.info(f"US IPOs updated: {count}")
        return count

    except Exception as e:
        logger.error(f"US IPO fetch failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_ipo_date(text: str):
    """Parse date from Chittorgarh format."""
    if not text or text == "-" or text.lower() == "n/a":
        return None
    import re
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    for fmt in ("%b %d, %Y", "%d %b %Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_price_band(text: str) -> tuple:
    """Parse price band like '₹371 to ₹390' or '$15-$20'."""
    import re
    if not text:
        return None, None

    # Remove currency symbols
    cleaned = text.replace("₹", "").replace("$", "").replace(",", "").strip()
    # Try 'X to Y' or 'X-Y' or 'X – Y'
    parts = re.split(r'\s*(?:to|–|-)\s*', cleaned)
    if len(parts) >= 2:
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            pass
    elif len(parts) == 1:
        try:
            val = float(parts[0].strip())
            return val, val
        except ValueError:
            pass
    return None, None


def _safe_int(text: str):
    """Safely parse integer."""
    if not text:
        return None
    import re
    cleaned = re.sub(r'[^\d]', '', text)
    try:
        return int(cleaned) if cleaned else None
    except ValueError:
        return None


def _determine_ipo_status(open_date, close_date) -> str:
    """Determine IPO status from dates."""
    today = date.today()
    if not open_date:
        return "upcoming"
    if open_date > today:
        return "upcoming"
    if close_date and close_date >= today and open_date <= today:
        return "open"
    if close_date and close_date < today:
        return "closed"
    return "upcoming"
