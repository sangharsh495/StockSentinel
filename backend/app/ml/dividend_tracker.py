"""
Dividend Tracker Engine — Monthly calendar, dividend yield calculations,
consistency ratings (⭐ 1-5), and year-over-year growth analysis.

Provides:
  - Monthly dividend calendar grouped by week
  - Dividend yield % for each stock
  - Consistency rating (1-5 stars) based on payment history
  - Dividend growth rate (YoY % change)
  - Complete company dividend data sheet (last 5 records)
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import date, datetime

from app.database import get_pool

logger = logging.getLogger(__name__)


class DividendTracker:
    """Monthly dividend calendar with yield analysis and consistency ratings."""

    async def get_monthly_calendar(
        self, month: int, year: int, limit: int = 200
    ) -> Dict[str, Any]:
        """
        Get all dividends for a specific month, grouped by week,
        with yield calculations and monthly stats.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Fetch all dividends in the target month
            dividends = await conn.fetch(
                """
                SELECT d.id, d.symbol, d.exchange, d.company_name, d.dividend_type,
                       d.amount, d.ex_date, d.record_date, d.payment_date, d.status,
                       s.current_price, s.market, s.sector, s.market_cap, s.currency,
                       s.change_pct
                FROM dividends d
                LEFT JOIN stocks s ON d.stock_id = s.id
                WHERE EXTRACT(MONTH FROM d.ex_date) = $1
                  AND EXTRACT(YEAR FROM d.ex_date) = $2
                ORDER BY d.ex_date ASC, d.amount DESC NULLS LAST
                LIMIT $3
                """,
                month,
                year,
                limit,
            )

            # Calculate yield for each and group by week
            items = []
            total_amount = 0.0
            yield_sum = 0.0
            yield_count = 0
            highest_yield_stock = None
            highest_yield = 0.0

            for d in dividends:
                amount = float(d["amount"]) if d["amount"] else 0
                price = float(d["current_price"]) if d["current_price"] else 0
                dividend_yield = (amount / price * 100) if price > 0 else 0

                total_amount += amount
                if dividend_yield > 0:
                    yield_sum += dividend_yield
                    yield_count += 1

                if dividend_yield > highest_yield:
                    highest_yield = dividend_yield
                    highest_yield_stock = d["symbol"]

                item = {
                    "id": d["id"],
                    "symbol": d["symbol"],
                    "exchange": d["exchange"],
                    "company_name": d["company_name"] or d["symbol"],
                    "dividend_type": d["dividend_type"] or "Dividend",
                    "amount": amount,
                    "ex_date": str(d["ex_date"]) if d["ex_date"] else None,
                    "record_date": str(d["record_date"]) if d["record_date"] else None,
                    "payment_date": str(d["payment_date"]) if d["payment_date"] else None,
                    "status": d["status"],
                    "current_price": price if price > 0 else None,
                    "market": d["market"],
                    "sector": d["sector"],
                    "currency": d["currency"] or "INR",
                    "change_pct": float(d["change_pct"]) if d["change_pct"] else None,
                    "dividend_yield_pct": round(dividend_yield, 2),
                    "week_number": d["ex_date"].isocalendar()[1] if d["ex_date"] else None,
                }
                items.append(item)

            # Group by week
            weeks: Dict[int, list] = {}
            for item in items:
                wk = item.get("week_number") or 0
                weeks.setdefault(wk, []).append(item)

            avg_yield = round(yield_sum / yield_count, 2) if yield_count > 0 else 0

            return {
                "month": month,
                "year": year,
                "total_dividends": len(items),
                "total_amount": round(total_amount, 2),
                "average_yield_pct": avg_yield,
                "highest_yield_pct": round(highest_yield, 2),
                "highest_yield_stock": highest_yield_stock,
                "weeks": {str(k): v for k, v in sorted(weeks.items())},
                "dividends": items,
            }

    async def get_dividend_history(self, symbol: str) -> Dict[str, Any]:
        """
        Full dividend payment history for a stock with yield trend,
        consistency rating (1-5 stars), and growth rate.
        """
        symbol_upper = symbol.strip().upper()

        pool = await get_pool()
        async with pool.acquire() as conn:
            # Get stock info
            stock = await conn.fetchrow(
                """
                SELECT id, symbol, name, exchange, market, current_price,
                       sector, currency
                FROM stocks
                WHERE UPPER(symbol) = $1
                ORDER BY market_cap DESC NULLS LAST
                LIMIT 1
                """,
                symbol_upper,
            )

            if not stock:
                return {"error": f"Stock '{symbol_upper}' not found", "symbol": symbol_upper}

            # Get all dividend records (ordered by ex_date desc)
            all_divs = await conn.fetch(
                """
                SELECT id, dividend_type, amount, ex_date, record_date,
                       payment_date, status, created_at
                FROM dividends
                WHERE UPPER(symbol) = $1
                ORDER BY ex_date DESC NULLS LAST
                """,
                symbol_upper,
            )

        current_price = float(stock["current_price"]) if stock["current_price"] else 0

        # Build history with yield per record
        history = []
        yearly_amounts: Dict[int, float] = {}

        for d in all_divs:
            amount = float(d["amount"]) if d["amount"] else 0
            div_yield = (amount / current_price * 100) if current_price > 0 else 0

            year = d["ex_date"].year if d["ex_date"] else None
            if year:
                yearly_amounts[year] = yearly_amounts.get(year, 0) + amount

            history.append({
                "id": d["id"],
                "dividend_type": d["dividend_type"],
                "amount": amount,
                "ex_date": str(d["ex_date"]) if d["ex_date"] else None,
                "record_date": str(d["record_date"]) if d["record_date"] else None,
                "payment_date": str(d["payment_date"]) if d["payment_date"] else None,
                "status": d["status"],
                "yield_pct": round(div_yield, 2),
            })

        # Consistency rating (stars 1-5)
        current_year = date.today().year
        check_years = list(range(current_year - 4, current_year + 1))
        years_with_dividend = sum(1 for y in check_years if y in yearly_amounts)
        consistency_rating = max(1, years_with_dividend)  # 1-5 stars

        # Calculate annual dividend yield
        total_annual = yearly_amounts.get(current_year, 0)
        if total_annual == 0 and yearly_amounts:
            # Use most recent year
            latest_year = max(yearly_amounts.keys())
            total_annual = yearly_amounts[latest_year]

        annual_yield = (total_annual / current_price * 100) if current_price > 0 else 0

        # Dividend growth rate (YoY)
        growth_rate = None
        sorted_years = sorted(yearly_amounts.keys())
        if len(sorted_years) >= 2:
            prev_year = sorted_years[-2]
            curr_year = sorted_years[-1]
            prev_amt = yearly_amounts[prev_year]
            curr_amt = yearly_amounts[curr_year]
            if prev_amt > 0:
                growth_rate = round(((curr_amt - prev_amt) / prev_amt) * 100, 1)

        # Yearly breakdown
        yearly_breakdown = []
        for year in sorted(yearly_amounts.keys(), reverse=True):
            amt = yearly_amounts[year]
            yld = (amt / current_price * 100) if current_price > 0 else 0
            yearly_breakdown.append({
                "year": year,
                "total_amount": round(amt, 2),
                "yield_pct": round(yld, 2),
                "payment_count": sum(
                    1 for d in all_divs
                    if d["ex_date"] and d["ex_date"].year == year
                ),
            })

        return {
            "symbol": stock["symbol"],
            "name": stock["name"],
            "exchange": stock["exchange"],
            "market": stock["market"],
            "sector": stock["sector"],
            "currency": stock["currency"] or "INR",
            "current_price": current_price if current_price > 0 else None,
            "total_records": len(history),
            "annual_dividend": round(total_annual, 2),
            "annual_yield_pct": round(annual_yield, 2),
            "consistency_rating": consistency_rating,  # 1-5 stars
            "consistency_label": self._consistency_label(consistency_rating),
            "dividend_growth_pct": growth_rate,
            "yearly_breakdown": yearly_breakdown[:5],
            "history": history[:20],  # last 20 records
        }

    @staticmethod
    def _consistency_label(rating: int) -> str:
        labels = {
            5: "Excellent — Paid every year (5/5)",
            4: "Very Good — Paid 4 of last 5 years",
            3: "Good — Paid 3 of last 5 years",
            2: "Fair — Irregular payments",
            1: "Poor — Rare dividend payer",
        }
        return labels.get(rating, "Unknown")


# Singleton
dividend_tracker = DividendTracker()
