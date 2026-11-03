"""
Current Indian IPOs from investorgain.com (price, GMP, dates, subscription
and financials), written to the `ipos` table that the app's IPO tab reads.

Chittorgarh's IPO list is now built in the browser with JavaScript, so a
plain request gets no table; investorgain serves its data in the page.
Also refreshes every IPO's status from its dates, so a finished IPO never
stays "open".
"""

import asyncio
import json
import logging
from datetime import date

from app.database import get_pool

logger = logging.getLogger(__name__)

DETAIL_KEYS = ("sector", "pe_ratio", "post_pe_ratio", "price_to_book", "roe", "roce", "debt_equity",
               "pat_margin", "market_cap_cr", "promoter_pre", "promoter_post", "fresh_issue_amt",
               "ofs_amt", "total_issue_amt", "min_order_amount", "incorporated", "url")


def ipo_status(open_d, close_d, listing_d, today=None) -> str:
    today = today or date.today()
    if listing_d and listing_d <= today:
        return "listed"
    if close_d and close_d < today:
        return "closed"
    if open_d and open_d <= today and (close_d is None or close_d >= today):
        return "open"
    return "upcoming"


def to_row(r: dict) -> dict:
    price = r.get("issue_price")
    lot = None
    if price and r.get("min_order_amount"):
        lot = int(round(r["min_order_amount"] / price))
    size = r.get("issue_size_cr")
    return {
        "company_name": (r.get("name") or "").strip()[:200],
        "price_band_high": price,
        "lot_size": lot,
        "issue_size": f"₹{size:,.0f} Cr" if size else None,
        "open_date": r.get("issue_open_date"),
        "close_date": r.get("issue_close_date"),
        "listing_date": r.get("listing_date"),
        "gmp": r.get("gmp"),
        "subscription_status": {"total": r["subscription_x"]} if r.get("subscription_x") is not None else None,
        "status": ipo_status(r.get("issue_open_date"), r.get("issue_close_date"), r.get("listing_date")),
        "details": {k: r.get(k) for k in DETAIL_KEYS if r.get(k) is not None},
    }


async def fetch_india_ipos_live() -> int:
    from app.scrapers.ipo_history import scrape_current

    rows = [to_row(r) for r in await asyncio.to_thread(scrape_current)]
    rows = [r for r in rows if r["company_name"]]
    pool = await get_pool()
    async with pool.acquire() as conn:
        for r in rows:
            await conn.execute(
                """
                INSERT INTO ipos (company_name, market, exchange, price_band_low, price_band_high, lot_size,
                                  issue_size, open_date, close_date, listing_date, gmp, subscription_status,
                                  status, details, source, updated_at)
                VALUES ($1, 'IN', 'NSE', $2, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb,
                        'investorgain', NOW())
                ON CONFLICT (company_name, market, open_date) DO UPDATE SET
                    price_band_high = COALESCE(EXCLUDED.price_band_high, ipos.price_band_high),
                    price_band_low = COALESCE(ipos.price_band_low, EXCLUDED.price_band_low),
                    lot_size = COALESCE(EXCLUDED.lot_size, ipos.lot_size),
                    issue_size = COALESCE(EXCLUDED.issue_size, ipos.issue_size),
                    close_date = COALESCE(EXCLUDED.close_date, ipos.close_date),
                    listing_date = COALESCE(EXCLUDED.listing_date, ipos.listing_date),
                    gmp = COALESCE(EXCLUDED.gmp, ipos.gmp),
                    subscription_status = COALESCE(EXCLUDED.subscription_status, ipos.subscription_status),
                    status = EXCLUDED.status, details = EXCLUDED.details,
                    source = 'investorgain', updated_at = NOW()
                """,
                r["company_name"], r["price_band_high"], r["lot_size"], r["issue_size"], r["open_date"],
                r["close_date"], r["listing_date"], r["gmp"],
                json.dumps(r["subscription_status"]) if r["subscription_status"] else None,
                r["status"], json.dumps(r["details"]),
            )
        await refresh_statuses(conn)
    logger.info(f"IPOs from investorgain: {len(rows)} current issues saved")
    return len(rows)


async def refresh_statuses(conn) -> None:
    """Re-derive every Indian IPO's status from its dates (old rows stuck at 'open' get fixed)."""
    await conn.execute(
        """
        UPDATE ipos SET status = CASE
            WHEN listing_date IS NOT NULL AND listing_date <= CURRENT_DATE THEN 'listed'
            WHEN close_date IS NOT NULL AND close_date < CURRENT_DATE THEN 'closed'
            WHEN open_date IS NOT NULL AND open_date <= CURRENT_DATE THEN 'open'
            ELSE 'upcoming' END
        WHERE market = 'IN'
        """
    )
