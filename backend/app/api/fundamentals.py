"""
Fundamentals API — endpoints for financial data, ratios, technicals,
valuation, and peer comparison.

Endpoints:
  GET /api/stocks/{symbol}/fundamentals  — Full financial data + ratios
  GET /api/stocks/{symbol}/ratios        — Quick-view ratio card
  GET /api/stocks/{symbol}/technicals    — Technical indicators + verdict
  GET /api/stocks/{symbol}/valuation     — Intrinsic value models + Buffett Score
  GET /api/stocks/{symbol}/compare       — Side-by-side peer comparison
"""

from fastapi import APIRouter, Query
from typing import Optional

from app.scrapers.fundamentals_scraper import fundamentals_scraper
from app.ml.ratio_calculator import ratio_calculator
from app.ml.technical_analyzer import technical_analyzer
from app.ml.valuation_engine import valuation_engine
from app.ml.moat_scorecard import moat_scorecard
from app.scrapers.shareholding_tracker import shareholding_tracker
from app.database import fetchrow

router = APIRouter()


@router.get("/stocks/{symbol}/fundamentals")
async def get_fundamentals(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
):
    """
    Complete financial data for a stock:
    - Income Statement (last 8 quarters + 5 years annual)
    - Balance Sheet
    - Cash Flow Statement
    - All key ratios with health grades
    - Overall financial grade (A+ to D)
    """
    # Detect exchange from DB if not specified
    if not exchange or exchange == "NSE":
        stock = await fetchrow(
            "SELECT exchange, market FROM stocks WHERE UPPER(symbol) = $1 ORDER BY market_cap DESC NULLS LAST LIMIT 1",
            symbol.upper(),
        )
        if stock:
            exchange = stock["exchange"]
            market = stock.get("market", "IN")
        else:
            market = "IN"
    else:
        market = "US" if exchange.upper() in ("NYSE", "NASDAQ") else "IN"

    # Fetch fundamentals from yfinance
    data = await fundamentals_scraper.get_fundamentals(symbol, exchange)

    if data.get("error"):
        return data

    # Compute graded ratios
    info = data.get("info") or {}
    annual = data.get("annual") or []
    ratio_card = ratio_calculator.compute_all_ratios(info, annual)

    # Merge
    data["ratio_card"] = ratio_card
    data["overall_financial_grade"] = ratio_card.get("overall_grade", "N/A")
    data["market"] = market

    return data


@router.get("/stocks/{symbol}/ratios")
async def get_ratios(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
):
    """
    Quick-view ratio card with color-coded grades.
    Returns P/E, P/B, ROE, D/E, margins, growth rates — each with a health grade.
    Lightweight endpoint for list views and cards.
    """
    if not exchange or exchange == "NSE":
        stock = await fetchrow(
            "SELECT exchange FROM stocks WHERE UPPER(symbol) = $1 ORDER BY market_cap DESC NULLS LAST LIMIT 1",
            symbol.upper(),
        )
        if stock:
            exchange = stock["exchange"]

    data = await fundamentals_scraper.get_fundamentals(symbol, exchange)

    if data.get("error"):
        return {"symbol": symbol.upper(), "error": data["error"], "ratios": {}}

    info = data.get("info") or {}
    annual = data.get("annual") or []
    ratio_card = ratio_calculator.compute_all_ratios(info, annual)

    return {
        "symbol": symbol.upper(),
        "exchange": exchange.upper() if exchange else "NSE",
        "current_price": info.get("market_cap"),  # Will be filled from live quote
        "ratios": ratio_card.get("ratios", {}),
        "overall_grade": ratio_card.get("overall_grade", "N/A"),
        "overall_score": ratio_card.get("overall_score", 0),
        "fifty_two_week": ratio_card.get("fifty_two_week", {}),
        "beta": ratio_card.get("beta"),
    }


@router.get("/stocks/{symbol}/technicals")
async def get_technicals(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
):
    """
    Complete technical analysis:
    - Moving Averages (SMA 20/50/200, EMA 20)
    - RSI (14) with overbought/oversold signal
    - MACD with signal crossover
    - Bollinger Bands with position
    - 52-week high/low with distance %
    - Volume analysis (20D average, ratio, breakout detection)
    - ATR (14) for volatility
    - Support/Resistance levels
    - Technical Verdict: STRONG_BUY → STRONG_SELL
    - Chart overlay arrays for drawing indicator lines
    """
    if not exchange or exchange == "NSE":
        stock = await fetchrow(
            "SELECT exchange FROM stocks WHERE UPPER(symbol) = $1 ORDER BY market_cap DESC NULLS LAST LIMIT 1",
            symbol.upper(),
        )
        if stock:
            exchange = stock["exchange"]

    result = await technical_analyzer.analyze(symbol, exchange)
    return result


@router.get("/stocks/{symbol}/valuation")
async def get_valuation(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
):
    """
    Intrinsic value analysis using 4 models:
    1. Discounted Cash Flow (DCF)
    2. Graham Number
    3. PEG Valuation (Peter Lynch)
    4. EV/EBITDA Relative Valuation

    Returns consensus value, Margin of Safety %, Buffett Score (0-100), and Value Grade.
    """
    if not exchange or exchange == "NSE":
        stock = await fetchrow(
            "SELECT exchange, market, current_price FROM stocks WHERE UPPER(symbol) = $1 ORDER BY market_cap DESC NULLS LAST LIMIT 1",
            symbol.upper(),
        )
        if stock:
            exchange = stock["exchange"]
            market = stock.get("market", "IN")
            db_price = float(stock["current_price"]) if stock.get("current_price") else None
        else:
            market = "IN"
            db_price = None
    else:
        market = "US" if exchange.upper() in ("NYSE", "NASDAQ") else "IN"
        db_price = None

    # Get fundamentals (needed for valuation)
    data = await fundamentals_scraper.get_fundamentals(symbol, exchange)

    if data.get("error"):
        return {
            "symbol": symbol.upper(),
            "error": data["error"],
            "valuation_models": {},
            "consensus_verdict": "INSUFFICIENT_DATA",
            "buffett_score": 0,
        }

    info = data.get("info") or {}
    annual = data.get("annual") or []

    # Determine current price
    # Priority: yfinance info > DB price
    current_price = None
    if info.get("market_cap") and info.get("shares_outstanding"):
        # Don't use market_cap directly; use live price
        pass

    # Get live price
    from app.ml.live_quote_service import live_quote_service
    live = await live_quote_service.get_live_quote(symbol, exchange)
    if live:
        current_price = live["current_price"]
    elif db_price:
        current_price = db_price

    if not current_price or current_price <= 0:
        return {
            "symbol": symbol.upper(),
            "error": "Current price unavailable",
            "valuation_models": {},
            "consensus_verdict": "INSUFFICIENT_DATA",
            "buffett_score": 0,
        }

    result = valuation_engine.compute_valuation(
        symbol=symbol,
        current_price=current_price,
        info=info,
        annual_financials=annual,
        market=market,
    )

    return result


@router.get("/stocks/{symbol}/compare")
async def compare_stocks(
    symbol: str,
    symbols: str = Query(..., description="Comma-separated symbols to compare (e.g., TCS,WIPRO,INFY)"),
    exchange: Optional[str] = Query("NSE", description="Exchange for all symbols"),
):
    """
    Side-by-side comparison of 2-5 stocks.
    Returns key ratios, grades, and valuation metrics for each stock in a table-ready format.
    """
    # Parse comparison symbols
    compare_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    all_symbols = [symbol.upper()] + [s for s in compare_list if s != symbol.upper()]
    all_symbols = all_symbols[:5]  # Max 5

    results = []
    for sym in all_symbols:
        # Detect exchange
        ex = exchange
        stock = await fetchrow(
            "SELECT exchange, market, current_price, name, sector, market_cap FROM stocks WHERE UPPER(symbol) = $1 ORDER BY market_cap DESC NULLS LAST LIMIT 1",
            sym,
        )
        if stock:
            ex = stock["exchange"]

        data = await fundamentals_scraper.get_fundamentals(sym, ex)
        info = data.get("info") or {} if not data.get("error") else {}
        annual = data.get("annual") or [] if not data.get("error") else []
        ratio_card = ratio_calculator.compute_all_ratios(info, annual)

        entry = {
            "symbol": sym,
            "name": (stock["name"] if stock else sym),
            "sector": (stock["sector"] if stock else info.get("sector")),
            "market_cap": (stock["market_cap"] if stock else info.get("market_cap")),
            "current_price": float(stock["current_price"]) if stock and stock.get("current_price") else None,
            "pe_ratio": info.get("pe_ratio"),
            "pb_ratio": info.get("pb_ratio"),
            "roe_pct": info.get("roe"),
            "net_margin_pct": info.get("profit_margin"),
            "debt_to_equity": info.get("debt_to_equity"),
            "dividend_yield_pct": info.get("dividend_yield_pct"),
            "beta": info.get("beta"),
            "fifty_two_week_high": info.get("fifty_two_week_high"),
            "fifty_two_week_low": info.get("fifty_two_week_low"),
            "overall_grade": ratio_card.get("overall_grade", "N/A"),
            "overall_score": ratio_card.get("overall_score", 0),
        }
        results.append(entry)

    # Sort by overall_score descending
    results.sort(key=lambda x: x.get("overall_score", 0), reverse=True)

    return {
        "count": len(results),
        "comparison": results,
    }


@router.get("/stocks/{symbol}/quality")
async def get_quality_scorecard(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
):
    """
    Buffett Moat & Financial Quality Scorecard:
    - Piotroski F-Score (0-9 points across Profitability, Leverage, Operating Efficiency)
    - Altman Z-Score (Distress / Grey / Safe zone)
    - Economic Moat (ROIC vs WACC spread & rating)
    - DuPont 3-Way ROE Decomposition (Margins, Turnover, Leverage driver)
    - Composite Buffett Quality Score & Verdict
    """
    return await moat_scorecard.get_quality_scorecard(symbol, exchange or "NSE")


@router.get("/stocks/{symbol}/shareholding")
async def get_shareholding(
    symbol: str,
    exchange: Optional[str] = Query("NSE", description="NSE, BSE, NYSE, NASDAQ"),
):
    """
    Shareholding & Ownership Distribution:
    - Promoter / Insider holding %
    - Institutional holding % (FII / DII)
    - Public / Retail Float %
    - Top 5 institutional holders
    - Buffett Skin-in-the-game assessment
    """
    return await shareholding_tracker.get_shareholding(symbol, exchange or "NSE")
