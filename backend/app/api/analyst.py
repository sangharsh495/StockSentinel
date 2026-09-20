"""
Analyst API — endpoints for weekly market movers, extreme news catalysts,
AI research dossiers, stock screener, dividend calendar, IPO reports,
daily news rankings, and full research reports.
"""

from fastapi import APIRouter, Query
from typing import Optional

from app.database import fetch
from app.ml.weekly_movers import weekly_movers_engine
from app.ml.ai_analyst import ai_analyst, generate_full_research_report
from app.ml.chart_service import chart_service
from app.ml.catalyst_analyzer import catalyst_analyzer
from app.ml.stock_screener import stock_screener
from app.ml.dividend_tracker import dividend_tracker
from app.ml.ipo_researcher import ipo_researcher
from app.ml.news_ranker import news_ranker

router = APIRouter()


# ---------------------------------------------------------------------------
# Existing Endpoints
# ---------------------------------------------------------------------------

@router.get("/analyst/weekly-movers")
async def get_weekly_movers(limit: int = Query(10, ge=1, le=50)):
    """
    Get top stocks positioned to move sharply this week based on
    breaking news catalysts, upcoming corporate dates (dividends/results),
    and volume/price momentum.
    """
    movers = await weekly_movers_engine.get_weekly_movers(limit=limit)
    return {
        "count": len(movers),
        "as_of": "This Week",
        "movers": movers,
    }


@router.get("/analyst/extreme-news")
async def get_extreme_news(
    catalyst: Optional[str] = Query(None, description="CONTRACT_WIN, DIVIDEND_BONUS, EARNINGS_CATALYST, LEGAL_REGULATORY, DEAL_MERGER"),
    limit: int = Query(25, ge=1, le=100),
):
    """
    Filtered stream of extreme, market-moving news headlines with
    catalyst badges and projected trend direction.
    """
    rows = await fetch(
        """
        SELECT id, title, url, source, published_at, sentiment,
               impact_score, affected_stocks, dividend_detected, summary
        FROM news
        WHERE published_at >= NOW() - INTERVAL '7 days'
        ORDER BY published_at DESC
        LIMIT 150
        """
    )

    results = []
    for r in rows:
        analysis = catalyst_analyzer.analyze_headline(r["title"], r.get("summary") or "")

        # Filter by catalyst if specified
        if catalyst and analysis["catalyst_type"] != catalyst.upper():
            continue

        # Keep extreme or catalyst-matched news
        if analysis["is_extreme"] or analysis["catalyst_type"] != "GENERAL_NEWS":
            item = dict(r)
            item.update(analysis)
            results.append(item)

        if len(results) >= limit:
            break

    return {"count": len(results), "news": results}


@router.get("/stocks/{symbol}/dossier")
async def get_stock_dossier(symbol: str):
    """
    Get on-demand AI institutional research dossier for any stock.
    Synthesizes emerging news catalysts, trend forecast, corporate calendar,
    and bull vs. bear conviction rating.
    """
    dossier = await ai_analyst.generate_dossier(symbol)
    return dossier


@router.get("/stocks/{symbol}/chart")
async def get_stock_chart(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
    range: str = Query("1M", description="1D, 1W, 1M, 1Y"),
):
    """
    Get multi-timeframe price points for interactive stock charts.
    """
    data = await chart_service.get_chart_data(symbol, exchange=exchange, range_key=range)
    return data


# ---------------------------------------------------------------------------
# NEW: Stock Screener (Feature 1 + Feature 5)
# ---------------------------------------------------------------------------

@router.get("/analyst/screener")
async def screener(
    sector: Optional[str] = Query(None, description="Filter by sector (IT, Pharma, Banking, etc.)"),
    market: Optional[str] = Query(None, description="IN or US"),
    min_market_cap: Optional[int] = Query(None, description="Minimum market cap in rupees"),
    min_score: float = Query(0, ge=0, le=100, description="Minimum research score"),
    has_catalyst: bool = Query(False, description="Only stocks with recent catalyst news"),
    has_dividend: bool = Query(False, description="Only dividend-paying stocks"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    AI-powered stock screener that ranks stocks using multi-factor composite
    research scoring (0-100) with research grades (A+ to D).
    """
    results = await stock_screener.screen(
        sector=sector,
        market=market,
        min_market_cap=min_market_cap,
        min_score=min_score,
        has_catalyst=has_catalyst,
        has_dividend=has_dividend,
        limit=limit,
    )
    return {
        "count": len(results),
        "filters": {
            "sector": sector,
            "market": market,
            "min_score": min_score,
            "has_catalyst": has_catalyst,
            "has_dividend": has_dividend,
        },
        "stocks": results,
    }


# ---------------------------------------------------------------------------
# NEW: Dividend Calendar & History (Feature 2)
# ---------------------------------------------------------------------------

@router.get("/analyst/dividend-calendar")
async def get_dividend_calendar(
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    year: int = Query(..., ge=2020, le=2030, description="Year"),
    limit: int = Query(200, ge=1, le=500),
):
    """
    Monthly dividend calendar with yield calculations, consistency ratings,
    and weekly groupings.
    """
    return await dividend_tracker.get_monthly_calendar(month, year, limit)


@router.get("/analyst/dividend-history/{symbol}")
async def get_dividend_history(symbol: str):
    """
    Full dividend payment history for a stock including yield trend,
    consistency rating (1-5 stars), and YoY growth rate.
    """
    return await dividend_tracker.get_dividend_history(symbol)


# ---------------------------------------------------------------------------
# NEW: IPO Research Report (Feature 3)
# ---------------------------------------------------------------------------

@router.get("/analyst/ipo-report/{ipo_id}")
async def get_ipo_report(ipo_id: int):
    """
    AI-generated comprehensive IPO research report with company overview,
    financial data, strengths/risks, and buy/don't-buy verdict.
    """
    return await ipo_researcher.generate_report(ipo_id)


# ---------------------------------------------------------------------------
# NEW: Daily News Ranking (Feature 4)
# ---------------------------------------------------------------------------

@router.get("/analyst/daily-news-ranked")
async def get_daily_news_ranked(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (default: today)"),
):
    """
    Get top 10 rated news for a specific date, ranked by Market Impact
    Rating (1-10). Each article includes rating, reason, and action flag.
    """
    return await news_ranker.get_daily_top_10(date)


@router.get("/analyst/daily-news-ranked/archive")
async def get_news_archive(
    days: int = Query(7, ge=1, le=30, description="Number of past days to retrieve"),
):
    """
    Archive of daily top-10 ranked news lists for the last N days.
    """
    return await news_ranker.get_archive(days)


# ---------------------------------------------------------------------------
# NEW: Full Research Report (Feature 6)
# ---------------------------------------------------------------------------

@router.get("/stocks/{symbol}/research-report")
async def get_research_report(symbol: str):
    """
    Industry-standard equity research report with financial scorecard,
    peer comparison, shareholding pattern, investment thesis, and research grade.
    """
    return await generate_full_research_report(symbol)
