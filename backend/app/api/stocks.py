"""
Stocks API — list, search, detail, top gainers/losers.
"""

from fastapi import APIRouter, Query
from typing import Optional
from app.database import fetch, fetchrow, fetchval

router = APIRouter()


@router.get("/stocks")
async def list_stocks(
    market: Optional[str] = Query(None, description="IN or US"),
    exchange: Optional[str] = Query(None, description="NSE, BSE, NYSE, NASDAQ"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List stocks with optional filtering by market/exchange."""
    conditions = []
    params = []
    param_idx = 1

    if market:
        conditions.append(f"market = ${param_idx}")
        params.append(market.upper())
        param_idx += 1

    if exchange:
        conditions.append(f"exchange = ${param_idx}")
        params.append(exchange.upper())
        param_idx += 1

    conditions.append("is_active = TRUE")
    where = " AND ".join(conditions)

    query = f"""
        SELECT id, symbol, name, exchange, market, sector, current_price,
               prev_close, day_high, day_low, open_price, volume, market_cap,
               change_pct, currency, last_updated
        FROM stocks
        WHERE {where}
        ORDER BY market_cap DESC NULLS LAST
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])

    stocks = await fetch(query, *params)

    # Get total count
    count_query = f"SELECT COUNT(*) FROM stocks WHERE {where}"
    total = await fetchval(count_query, *params[:-2])

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "stocks": stocks,
    }


@router.get("/stocks/search")
async def search_stocks(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search stocks by symbol or company name.
    Queries the local database — not an external API.
    """
    search_term = f"%{q.upper()}%"

    stocks = await fetch(
        """
        SELECT id, symbol, name, exchange, market, current_price,
               change_pct, currency, last_updated
        FROM stocks
        WHERE (UPPER(symbol) LIKE $1 OR UPPER(name) LIKE $1)
          AND is_active = TRUE
        ORDER BY
            CASE WHEN UPPER(symbol) = $2 THEN 0
                 WHEN UPPER(symbol) LIKE $3 THEN 1
                 ELSE 2
            END,
            market_cap DESC NULLS LAST
        LIMIT $4
        """,
        search_term,
        q.upper(),
        f"{q.upper()}%",
        limit,
    )

    return {"query": q, "count": len(stocks), "stocks": stocks}


@router.get("/stocks/top-gainers")
async def top_gainers(
    market: Optional[str] = Query(None, description="IN or US"),
    limit: int = Query(10, ge=1, le=50),
):
    """Top gaining stocks by percentage change."""
    if market:
        stocks = await fetch(
            """
            SELECT id, symbol, name, exchange, market, current_price,
                   prev_close, change_pct, volume, currency, last_updated
            FROM stocks
            WHERE change_pct IS NOT NULL AND change_pct > 0
              AND market = $1 AND is_active = TRUE
            ORDER BY change_pct DESC
            LIMIT $2
            """,
            market.upper(),
            limit,
        )
    else:
        stocks = await fetch(
            """
            SELECT id, symbol, name, exchange, market, current_price,
                   prev_close, change_pct, volume, currency, last_updated
            FROM stocks
            WHERE change_pct IS NOT NULL AND change_pct > 0
              AND is_active = TRUE
            ORDER BY change_pct DESC
            LIMIT $1
            """,
            limit,
        )

    return {"stocks": stocks}


@router.get("/stocks/top-losers")
async def top_losers(
    market: Optional[str] = Query(None, description="IN or US"),
    limit: int = Query(10, ge=1, le=50),
):
    """Top losing stocks by percentage change."""
    if market:
        stocks = await fetch(
            """
            SELECT id, symbol, name, exchange, market, current_price,
                   prev_close, change_pct, volume, currency, last_updated
            FROM stocks
            WHERE change_pct IS NOT NULL AND change_pct < 0
              AND market = $1 AND is_active = TRUE
            ORDER BY change_pct ASC
            LIMIT $2
            """,
            market.upper(),
            limit,
        )
    else:
        stocks = await fetch(
            """
            SELECT id, symbol, name, exchange, market, current_price,
                   prev_close, change_pct, volume, currency, last_updated
            FROM stocks
            WHERE change_pct IS NOT NULL AND change_pct < 0
              AND is_active = TRUE
            ORDER BY change_pct ASC
            LIMIT $1
            """,
            limit,
        )

    return {"stocks": stocks}


from app.ml.live_quote_service import live_quote_service

@router.get("/stocks/indices")
async def market_indices():
    """Get live real-time market indices — NIFTY 50, SENSEX, S&P 500, NASDAQ."""
    indices = await live_quote_service.get_live_indices()
    return {"indices": indices}


@router.get("/stocks/count/summary")
async def stock_count():
    """Get count of stocks by market/exchange."""
    counts = await fetch(
        """
        SELECT market, exchange, COUNT(*) as count
        FROM stocks WHERE is_active = TRUE
        GROUP BY market, exchange
        ORDER BY market, exchange
        """
    )
    total = sum(row["count"] for row in counts)
    return {"total": total, "breakdown": counts}


@router.get("/stocks/{symbol}")
async def get_stock(symbol: str, exchange: Optional[str] = None):
    """
    Get detailed info for a single stock with guaranteed live, up-to-date pricing.
    """
    if exchange:
        stock = await fetchrow(
            """
            SELECT * FROM stocks
            WHERE UPPER(symbol) = $1 AND exchange = $2
            """,
            symbol.upper(),
            exchange.upper(),
        )
    else:
        stock = await fetchrow(
            """
            SELECT * FROM stocks
            WHERE UPPER(symbol) = $1
            ORDER BY market_cap DESC NULLS LAST
            LIMIT 1
            """,
            symbol.upper(),
        )

    if not stock:
        # Check if live quote can be resolved for ticker directly
        live_q = await live_quote_service.get_live_quote(symbol, exchange or "NSE")
        if live_q:
            return {
                "stock": {
                    "symbol": symbol.upper(),
                    "name": symbol.upper(),
                    "exchange": exchange or "NSE",
                    "market": "IN" if (exchange or "NSE").upper() in ("NSE", "BSE") else "US",
                    "current_price": live_q["current_price"],
                    "prev_close": live_q["prev_close"],
                    "change_pct": live_q["change_pct"],
                    "day_high": live_q.get("day_high"),
                    "day_low": live_q.get("day_low"),
                    "volume": live_q.get("volume"),
                    "is_live": True,
                }
            }
        return {"error": "Stock not found", "symbol": symbol}

    stock_dict = dict(stock)

    # Sync live quote if missing or older than 5 minutes
    ex = stock_dict.get("exchange") or exchange or "NSE"
    live_q = await live_quote_service.get_live_quote(symbol, ex)
    if live_q:
        stock_dict["current_price"] = live_q["current_price"]
        stock_dict["prev_close"] = live_q["prev_close"]
        stock_dict["change_pct"] = live_q["change_pct"]
        if live_q.get("day_high"):
            stock_dict["day_high"] = live_q["day_high"]
        if live_q.get("day_low"):
            stock_dict["day_low"] = live_q["day_low"]
        if live_q.get("volume"):
            stock_dict["volume"] = live_q["volume"]
        stock_dict["is_live"] = True

    return {"stock": stock_dict}


@router.get("/stocks/{symbol}/news")
async def get_stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
):
    """Get all news affecting a specific stock — with ML impact scores."""
    items = await fetch(
        """
        SELECT nsi.impact_direction, nsi.impact_score, nsi.reason,
               n.id as news_id, n.title, n.url, n.source, n.published_at,
               n.sentiment, n.sentiment_score, n.dividend_detected
        FROM news_stock_impact nsi
        JOIN news n ON nsi.news_id = n.id
        WHERE nsi.symbol = $1
        ORDER BY n.published_at DESC
        LIMIT $2
        """,
        symbol.upper(),
        limit,
    )

    return {"symbol": symbol.upper(), "count": len(items), "news": items}

