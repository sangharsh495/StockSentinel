"""
Fundamentals Scraper — Fetches quarterly/annual financial data from yfinance.

Extracts:
  - Income Statement (Revenue, Net Income, EBITDA, Operating Income, EPS)
  - Balance Sheet (Total Assets, Debt, Equity, Cash, Current Assets/Liabilities)
  - Cash Flow (Operating CF, Free CF, CapEx)
  - Key info metrics (P/E, P/B, Beta, 52-week range, Book Value, Dividend Yield)

Design:
  - Uses same ThreadPoolExecutor pattern as live_quote_service.py
  - 6-hour in-memory TTL cache (financials don't change intraday)
  - Handles Indian (.NS/.BO) and US tickers
  - Graceful fallback: returns null fields, never crashes
"""

import time
import logging
import asyncio
import math
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import yfinance as yf

from app.database import get_pool

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)

# In-memory cache: key -> {data, expires_at}
_fundamentals_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 21600  # 6 hours


def _safe_int(val) -> Optional[int]:
    """Safely convert a value to int, handling NaN/None."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (ValueError, TypeError):
        return None


def _safe_float(val, decimals: int = 2) -> Optional[float]:
    """Safely convert a value to float, handling NaN/None."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, decimals)
    except (ValueError, TypeError):
        return None


def _get_yf_ticker(symbol: str, exchange: str = "NSE") -> str:
    """Resolve yfinance ticker identifier."""
    clean = symbol.strip().upper()
    if clean.startswith("^"):
        return clean
    ex = exchange.upper()
    if ex == "NSE":
        return f"{clean}.NS"
    elif ex == "BSE":
        return f"{clean}.BO"
    return clean  # US stocks


def _extract_financials_sync(yf_ticker: str) -> Optional[Dict[str, Any]]:
    """
    Synchronously fetch all financial data from yfinance.
    Returns structured dict with income_statement, balance_sheet, cash_flow, info.
    """
    try:
        ticker = yf.Ticker(yf_ticker)

        result = {
            "annual": [],
            "quarterly": [],
            "info": {},
        }

        # --- Income Statement ---
        annual_is = ticker.financials  # Annual income statement
        quarterly_is = ticker.quarterly_financials

        # --- Balance Sheet ---
        annual_bs = ticker.balance_sheet
        quarterly_bs = ticker.quarterly_balance_sheet

        # --- Cash Flow ---
        annual_cf = ticker.cashflow
        quarterly_cf = ticker.quarterly_cashflow

        # Process annual data
        if annual_is is not None and not annual_is.empty:
            for col_date in annual_is.columns[:5]:  # Last 5 years max
                period_end = col_date.date() if hasattr(col_date, 'date') else col_date
                record = _build_financial_record(
                    annual_is, annual_bs, annual_cf, col_date, period_end, "annual"
                )
                result["annual"].append(record)

        # Process quarterly data
        if quarterly_is is not None and not quarterly_is.empty:
            for col_date in quarterly_is.columns[:8]:  # Last 8 quarters max
                period_end = col_date.date() if hasattr(col_date, 'date') else col_date
                record = _build_financial_record(
                    quarterly_is, quarterly_bs, quarterly_cf, col_date, period_end, "quarterly"
                )
                result["quarterly"].append(record)

        # --- Key Info Metrics ---
        try:
            info = ticker.info or {}
            result["info"] = {
                "pe_ratio": _safe_float(info.get("trailingPE")),
                "forward_pe": _safe_float(info.get("forwardPE")),
                "pb_ratio": _safe_float(info.get("priceToBook")),
                "peg_ratio": _safe_float(info.get("pegRatio")),
                "beta": _safe_float(info.get("beta"), 3),
                "book_value": _safe_float(info.get("bookValue")),
                "eps": _safe_float(info.get("trailingEps")),
                "forward_eps": _safe_float(info.get("forwardEps")),
                "dividend_yield_pct": _safe_float(
                    (info.get("dividendYield") or 0) * 100, 2
                ) if info.get("dividendYield") else None,
                "fifty_two_week_high": _safe_float(info.get("fiftyTwoWeekHigh"), 4),
                "fifty_two_week_low": _safe_float(info.get("fiftyTwoWeekLow"), 4),
                "market_cap": _safe_int(info.get("marketCap")),
                "shares_outstanding": _safe_int(info.get("sharesOutstanding")),
                "enterprise_value": _safe_int(info.get("enterpriseValue")),
                "ev_ebitda": _safe_float(info.get("enterpriseToEbitda")),
                "revenue_growth": _safe_float(
                    (info.get("revenueGrowth") or 0) * 100, 2
                ) if info.get("revenueGrowth") else None,
                "earnings_growth": _safe_float(
                    (info.get("earningsGrowth") or 0) * 100, 2
                ) if info.get("earningsGrowth") else None,
                "profit_margin": _safe_float(
                    (info.get("profitMargins") or 0) * 100, 2
                ) if info.get("profitMargins") else None,
                "operating_margin": _safe_float(
                    (info.get("operatingMargins") or 0) * 100, 2
                ) if info.get("operatingMargins") else None,
                "roe": _safe_float(
                    (info.get("returnOnEquity") or 0) * 100, 2
                ) if info.get("returnOnEquity") else None,
                "roa": _safe_float(
                    (info.get("returnOnAssets") or 0) * 100, 2
                ) if info.get("returnOnAssets") else None,
                "debt_to_equity": _safe_float(info.get("debtToEquity"), 2),
                "current_ratio": _safe_float(info.get("currentRatio"), 2),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "full_name": info.get("longName") or info.get("shortName"),
            }
        except Exception as e:
            logger.debug(f"Failed to fetch info for {yf_ticker}: {e}")
            result["info"] = {}

        return result

    except Exception as e:
        logger.warning(f"Fundamentals fetch failed for {yf_ticker}: {e}")
        return None


def _build_financial_record(
    income_stmt, balance_sheet, cash_flow, col_date, period_end, period_type: str
) -> Dict[str, Any]:
    """Build a single period's financial record from dataframes."""

    def _get(df, row_name):
        """Safely get a value from a DataFrame."""
        if df is None or df.empty:
            return None
        # Try multiple naming conventions
        names = [row_name]
        if " " in row_name:
            names.append(row_name.replace(" ", ""))
        for name in names:
            if name in df.index and col_date in df.columns:
                return _safe_int(df.loc[name, col_date])
        return None

    return {
        "period_type": period_type,
        "period_end": str(period_end),
        # Income Statement
        "revenue": _get(income_stmt, "Total Revenue"),
        "net_income": _get(income_stmt, "Net Income"),
        "ebitda": _get(income_stmt, "EBITDA"),
        "operating_income": _get(income_stmt, "Operating Income"),
        "interest_expense": _get(income_stmt, "Interest Expense"),
        # Balance Sheet
        "total_assets": _get(balance_sheet, "Total Assets"),
        "total_debt": _get(balance_sheet, "Total Debt"),
        "total_equity": (
            _get(balance_sheet, "Total Stockholders Equity")
            or _get(balance_sheet, "Stockholders Equity")
            or _get(balance_sheet, "Total Equity Gross Minority Interest")
        ),
        "cash_and_equivalents": (
            _get(balance_sheet, "Cash And Cash Equivalents")
            or _get(balance_sheet, "Cash Cash Equivalents And Short Term Investments")
        ),
        "current_assets": _get(balance_sheet, "Current Assets"),
        "current_liabilities": _get(balance_sheet, "Current Liabilities"),
        # Cash Flow
        "operating_cash_flow": (
            _get(cash_flow, "Operating Cash Flow")
            or _get(cash_flow, "Cash Flow From Continuing Operating Activities")
        ),
        "free_cash_flow": _get(cash_flow, "Free Cash Flow"),
        "capex": _get(cash_flow, "Capital Expenditure"),
    }


class FundamentalsScraper:
    """Fetches and caches financial data from yfinance."""

    async def get_fundamentals(
        self, symbol: str, exchange: str = "NSE"
    ) -> Dict[str, Any]:
        """
        Fetch complete financial data for a stock.
        Returns annual + quarterly financials + key info metrics.
        """
        yf_ticker = _get_yf_ticker(symbol, exchange)
        cache_key = f"fundamentals_{yf_ticker}"
        now = time.time()

        # Check cache
        if cache_key in _fundamentals_cache:
            cached = _fundamentals_cache[cache_key]
            if now < cached["expires_at"]:
                return cached["data"]

        # Fetch in thread pool
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            _executor, _extract_financials_sync, yf_ticker
        )

        if not data:
            return {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "error": "Financial data unavailable",
                "annual": [],
                "quarterly": [],
                "info": {},
            }

        result = {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "annual": data["annual"],
            "quarterly": data["quarterly"],
            "info": data["info"],
        }

        # Cache it
        _fundamentals_cache[cache_key] = {
            "data": result,
            "expires_at": now + CACHE_TTL,
        }

        return result

    async def persist_fundamentals(self, symbol: str, exchange: str = "NSE") -> int:
        """Fetch fundamentals and persist to database. Returns records saved."""
        data = await self.get_fundamentals(symbol, exchange)
        if data.get("error"):
            return 0

        pool = await get_pool()
        count = 0

        # Get stock_id
        async with pool.acquire() as conn:
            stock = await conn.fetchrow(
                "SELECT id FROM stocks WHERE UPPER(symbol) = $1 AND UPPER(exchange) = $2",
                symbol.upper(),
                exchange.upper(),
            )
            stock_id = stock["id"] if stock else None

            # Save financial records
            for period_list in [data["annual"], data["quarterly"]]:
                for record in period_list:
                    if not record.get("period_end"):
                        continue
                    try:
                        await conn.execute(
                            """
                            INSERT INTO stock_financials
                                (stock_id, symbol, exchange, period_type, period_end,
                                 revenue, net_income, ebitda, operating_income, interest_expense,
                                 total_assets, total_debt, total_equity, cash_and_equivalents,
                                 current_assets, current_liabilities,
                                 operating_cash_flow, free_cash_flow, capex)
                            VALUES ($1,$2,$3,$4,$5::date, $6,$7,$8,$9,$10, $11,$12,$13,$14,$15,$16, $17,$18,$19)
                            ON CONFLICT (symbol, exchange, period_type, period_end) DO UPDATE SET
                                revenue = EXCLUDED.revenue,
                                net_income = EXCLUDED.net_income,
                                ebitda = EXCLUDED.ebitda,
                                operating_income = EXCLUDED.operating_income,
                                interest_expense = EXCLUDED.interest_expense,
                                total_assets = EXCLUDED.total_assets,
                                total_debt = EXCLUDED.total_debt,
                                total_equity = EXCLUDED.total_equity,
                                cash_and_equivalents = EXCLUDED.cash_and_equivalents,
                                current_assets = EXCLUDED.current_assets,
                                current_liabilities = EXCLUDED.current_liabilities,
                                operating_cash_flow = EXCLUDED.operating_cash_flow,
                                free_cash_flow = EXCLUDED.free_cash_flow,
                                capex = EXCLUDED.capex,
                                fetched_at = NOW()
                            """,
                            stock_id,
                            symbol.upper(),
                            exchange.upper(),
                            record["period_type"],
                            record["period_end"],
                            record.get("revenue"),
                            record.get("net_income"),
                            record.get("ebitda"),
                            record.get("operating_income"),
                            record.get("interest_expense"),
                            record.get("total_assets"),
                            record.get("total_debt"),
                            record.get("total_equity"),
                            record.get("cash_and_equivalents"),
                            record.get("current_assets"),
                            record.get("current_liabilities"),
                            record.get("operating_cash_flow"),
                            record.get("free_cash_flow"),
                            record.get("capex"),
                        )
                        count += 1
                    except Exception as e:
                        logger.debug(f"Failed to save financial record: {e}")

            # Save ratios/info to stock_ratios
            info = data.get("info") or {}
            if info:
                try:
                    await conn.execute(
                        """
                        INSERT INTO stock_ratios
                            (stock_id, symbol, exchange,
                             pe_ratio, pb_ratio, peg_ratio, ev_ebitda, forward_pe,
                             roe_pct, net_margin_pct, operating_margin_pct,
                             debt_to_equity, current_ratio,
                             beta, book_value, fifty_two_week_high, fifty_two_week_low,
                             dividend_yield_pct, shares_outstanding)
                        VALUES ($1,$2,$3, $4,$5,$6,$7,$8, $9,$10,$11, $12,$13, $14,$15,$16,$17,$18,$19)
                        ON CONFLICT (symbol, exchange) DO UPDATE SET
                            pe_ratio = EXCLUDED.pe_ratio,
                            pb_ratio = EXCLUDED.pb_ratio,
                            peg_ratio = EXCLUDED.peg_ratio,
                            ev_ebitda = EXCLUDED.ev_ebitda,
                            forward_pe = EXCLUDED.forward_pe,
                            roe_pct = EXCLUDED.roe_pct,
                            net_margin_pct = EXCLUDED.net_margin_pct,
                            operating_margin_pct = EXCLUDED.operating_margin_pct,
                            debt_to_equity = EXCLUDED.debt_to_equity,
                            current_ratio = EXCLUDED.current_ratio,
                            beta = EXCLUDED.beta,
                            book_value = EXCLUDED.book_value,
                            fifty_two_week_high = EXCLUDED.fifty_two_week_high,
                            fifty_two_week_low = EXCLUDED.fifty_two_week_low,
                            dividend_yield_pct = EXCLUDED.dividend_yield_pct,
                            shares_outstanding = EXCLUDED.shares_outstanding,
                            calculated_at = NOW()
                        """,
                        stock_id,
                        symbol.upper(),
                        exchange.upper(),
                        info.get("pe_ratio"),
                        info.get("pb_ratio"),
                        info.get("peg_ratio"),
                        info.get("ev_ebitda"),
                        info.get("forward_pe"),
                        info.get("roe"),
                        info.get("profit_margin"),
                        info.get("operating_margin"),
                        info.get("debt_to_equity"),
                        info.get("current_ratio"),
                        info.get("beta"),
                        info.get("book_value"),
                        info.get("fifty_two_week_high"),
                        info.get("fifty_two_week_low"),
                        info.get("dividend_yield_pct"),
                        info.get("shares_outstanding"),
                    )
                    count += 1
                except Exception as e:
                    logger.debug(f"Failed to save stock ratios: {e}")

        logger.info(f"Persisted {count} financial records for {symbol}")
        return count


# Singleton
fundamentals_scraper = FundamentalsScraper()


async def fetch_fundamentals_batch(limit: int = 100) -> int:
    """
    Scheduler entry point: fetch fundamentals for top stocks by market cap.
    Runs nightly to keep financial data fresh.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        stocks = await conn.fetch(
            """
            SELECT symbol, exchange FROM stocks
            WHERE is_active = TRUE AND current_price IS NOT NULL
            ORDER BY market_cap DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )

    total = 0
    for stock in stocks:
        try:
            count = await fundamentals_scraper.persist_fundamentals(
                stock["symbol"], stock["exchange"]
            )
            total += count
            # Rate limit: 2 second delay between tickers
            await asyncio.sleep(2)
        except Exception as e:
            logger.debug(f"Failed fundamentals for {stock['symbol']}: {e}")

    logger.info(f"Fundamentals batch complete: {total} records for {len(stocks)} stocks")
    return total
