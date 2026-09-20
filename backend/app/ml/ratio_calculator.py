"""
Ratio Calculator — Computes derived financial ratios from raw data
and assigns health grades (Excellent / Good / Fair / Poor).

Key Ratios:
  - Valuation: P/E, P/B, PEG, EV/EBITDA
  - Profitability: ROE, ROCE, Net Margin, Operating Margin
  - Leverage: Debt-to-Equity, Current Ratio, Interest Coverage
  - Cash Flow: FCF Yield
  - Growth: Revenue CAGR (3Y), Profit CAGR (3Y)
  - Dividends: Payout Ratio

Each ratio is graded and the overall financial health is scored A+ through D.
"""

import math
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Grade thresholds per ratio (higher = better unless inverted)
# ---------------------------------------------------------------------------

RATIO_GRADES = {
    "pe_ratio": {
        # Lower P/E = cheaper (but not negative)
        "ranges": [(0, 12, "Excellent"), (12, 20, "Good"), (20, 35, "Fair"), (35, 999, "Poor")],
        "inverted": True,  # lower is better
        "negative_label": "Loss-Making",
    },
    "pb_ratio": {
        "ranges": [(0, 1.5, "Excellent"), (1.5, 3, "Good"), (3, 6, "Fair"), (6, 999, "Poor")],
        "inverted": True,
    },
    "roe_pct": {
        "ranges": [(20, 999, "Excellent"), (15, 20, "Good"), (8, 15, "Fair"), (0, 8, "Poor")],
        "inverted": False,
    },
    "roce_pct": {
        "ranges": [(20, 999, "Excellent"), (12, 20, "Good"), (6, 12, "Fair"), (0, 6, "Poor")],
        "inverted": False,
    },
    "net_margin_pct": {
        "ranges": [(20, 999, "Excellent"), (10, 20, "Good"), (5, 10, "Fair"), (0, 5, "Poor")],
        "inverted": False,
        "negative_label": "Negative Margin",
    },
    "debt_to_equity": {
        "ranges": [(0, 0.3, "Excellent"), (0.3, 0.8, "Good"), (0.8, 1.5, "Fair"), (1.5, 999, "Poor")],
        "inverted": True,
    },
    "current_ratio": {
        "ranges": [(2, 999, "Excellent"), (1.5, 2, "Good"), (1, 1.5, "Fair"), (0, 1, "Poor")],
        "inverted": False,
    },
    "interest_coverage": {
        "ranges": [(8, 999, "Excellent"), (4, 8, "Good"), (2, 4, "Fair"), (0, 2, "Poor")],
        "inverted": False,
    },
    "fcf_yield_pct": {
        "ranges": [(6, 999, "Excellent"), (3, 6, "Good"), (1, 3, "Fair"), (0, 1, "Poor")],
        "inverted": False,
        "negative_label": "Negative FCF",
    },
    "revenue_cagr_3y": {
        "ranges": [(20, 999, "Excellent"), (10, 20, "Good"), (5, 10, "Fair"), (0, 5, "Poor")],
        "inverted": False,
        "negative_label": "Declining Revenue",
    },
    "profit_cagr_3y": {
        "ranges": [(25, 999, "Excellent"), (12, 25, "Good"), (5, 12, "Fair"), (0, 5, "Poor")],
        "inverted": False,
        "negative_label": "Declining Profits",
    },
}

GRADE_SCORES = {"Excellent": 4, "Good": 3, "Fair": 2, "Poor": 1, "N/A": 0}
OVERALL_GRADES = [
    (3.5, "A+"), (3.0, "A"), (2.5, "B+"), (2.0, "B"),
    (1.5, "C+"), (1.0, "C"), (0.5, "D+"), (0, "D"),
]


def grade_ratio(ratio_name: str, value: Optional[float]) -> Dict[str, Any]:
    """Grade a single ratio and return value + grade + description."""
    if value is None:
        return {"value": None, "grade": "N/A", "description": "Data unavailable"}

    config = RATIO_GRADES.get(ratio_name)
    if not config:
        return {"value": value, "grade": "N/A", "description": "No grading criteria"}

    # Handle negative values
    if value < 0:
        label = config.get("negative_label", "Negative")
        return {"value": value, "grade": "Poor", "description": label}

    # Find matching range
    for low, high, grade in config["ranges"]:
        if low <= value < high:
            return {"value": value, "grade": grade, "description": f"{grade}"}

    return {"value": value, "grade": "Fair", "description": "Outside expected range"}


class RatioCalculator:
    """Computes and grades all financial ratios for a stock."""

    def compute_all_ratios(
        self,
        info: Dict[str, Any],
        annual_financials: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Compute all ratios from yfinance info + raw financial data.
        Returns a comprehensive ratio card with grades.
        """
        ratios = {}

        # --- Valuation Ratios (from yfinance info) ---
        ratios["pe_ratio"] = grade_ratio("pe_ratio", info.get("pe_ratio"))
        ratios["pb_ratio"] = grade_ratio("pb_ratio", info.get("pb_ratio"))
        ratios["peg_ratio"] = grade_ratio(
            "pe_ratio",  # Use same grading logic
            info.get("peg_ratio"),
        )
        # Override PEG grade specifically
        peg = info.get("peg_ratio")
        if peg is not None:
            if peg < 1:
                ratios["peg_ratio"] = {"value": peg, "grade": "Excellent", "description": "Undervalued relative to growth"}
            elif peg < 1.5:
                ratios["peg_ratio"] = {"value": peg, "grade": "Good", "description": "Fairly valued relative to growth"}
            elif peg < 2.5:
                ratios["peg_ratio"] = {"value": peg, "grade": "Fair", "description": "Slightly overvalued"}
            else:
                ratios["peg_ratio"] = {"value": peg, "grade": "Poor", "description": "Overvalued relative to growth"}
        else:
            ratios["peg_ratio"] = {"value": None, "grade": "N/A", "description": "Growth data unavailable"}

        ratios["ev_ebitda"] = grade_ratio("pe_ratio", info.get("ev_ebitda"))  # Similar scale
        ev = info.get("ev_ebitda")
        if ev is not None:
            if ev < 10:
                ratios["ev_ebitda"] = {"value": ev, "grade": "Excellent", "description": "Attractive enterprise valuation"}
            elif ev < 18:
                ratios["ev_ebitda"] = {"value": ev, "grade": "Good", "description": "Reasonable enterprise valuation"}
            elif ev < 30:
                ratios["ev_ebitda"] = {"value": ev, "grade": "Fair", "description": "Premium enterprise valuation"}
            else:
                ratios["ev_ebitda"] = {"value": ev, "grade": "Poor", "description": "Expensive enterprise valuation"}
        else:
            ratios["ev_ebitda"] = {"value": None, "grade": "N/A", "description": "Data unavailable"}

        # --- Profitability ---
        ratios["roe_pct"] = grade_ratio("roe_pct", info.get("roe"))
        ratios["net_margin_pct"] = grade_ratio("net_margin_pct", info.get("profit_margin"))
        ratios["operating_margin_pct"] = grade_ratio("net_margin_pct", info.get("operating_margin"))

        # Compute ROCE from financials if available
        roce = self._compute_roce(annual_financials)
        ratios["roce_pct"] = grade_ratio("roce_pct", roce)

        # --- Leverage ---
        d2e = info.get("debt_to_equity")
        if d2e is not None:
            # yfinance returns D/E as percentage (e.g., 45.5 = 0.455 ratio)
            d2e_ratio = d2e / 100 if d2e > 5 else d2e  # Normalize
            ratios["debt_to_equity"] = grade_ratio("debt_to_equity", d2e_ratio)
        else:
            ratios["debt_to_equity"] = {"value": None, "grade": "N/A", "description": "Data unavailable"}

        ratios["current_ratio"] = grade_ratio("current_ratio", info.get("current_ratio"))

        # Interest coverage from financials
        int_cov = self._compute_interest_coverage(annual_financials)
        ratios["interest_coverage"] = grade_ratio("interest_coverage", int_cov)

        # --- Cash Flow ---
        fcf_yield = self._compute_fcf_yield(annual_financials, info.get("market_cap"))
        ratios["fcf_yield_pct"] = grade_ratio("fcf_yield_pct", fcf_yield)

        # --- Growth ---
        rev_cagr = self._compute_cagr(annual_financials, "revenue")
        profit_cagr = self._compute_cagr(annual_financials, "net_income")
        ratios["revenue_cagr_3y"] = grade_ratio("revenue_cagr_3y", rev_cagr)
        ratios["profit_cagr_3y"] = grade_ratio("profit_cagr_3y", profit_cagr)

        # --- Dividend Payout Ratio ---
        payout = self._compute_payout_ratio(annual_financials, info)
        ratios["dividend_payout_pct"] = {
            "value": payout,
            "grade": "Good" if payout and 20 <= payout <= 60 else ("Fair" if payout else "N/A"),
            "description": f"{payout:.0f}% of earnings paid as dividends" if payout else "Data unavailable",
        }

        # --- Overall Financial Grade ---
        scores = [GRADE_SCORES.get(r["grade"], 0) for r in ratios.values() if r["grade"] != "N/A"]
        avg_score = sum(scores) / len(scores) if scores else 0
        overall_grade = "D"
        for threshold, grade in OVERALL_GRADES:
            if avg_score >= threshold:
                overall_grade = grade
                break

        # --- 52-week position ---
        high_52w = info.get("fifty_two_week_high")
        low_52w = info.get("fifty_two_week_low")
        price = info.get("market_cap")  # We'll get current price separately

        return {
            "ratios": ratios,
            "overall_grade": overall_grade,
            "overall_score": round(avg_score, 2),
            "graded_count": len(scores),
            "fifty_two_week": {
                "high": high_52w,
                "low": low_52w,
            },
            "beta": info.get("beta"),
        }

    def _compute_roce(self, annual: List[Dict]) -> Optional[float]:
        """ROCE = EBIT / (Total Assets - Current Liabilities)."""
        if not annual:
            return None
        latest = annual[0]
        ebit = latest.get("operating_income")
        total_assets = latest.get("total_assets")
        curr_liab = latest.get("current_liabilities")
        if ebit and total_assets and curr_liab:
            capital_employed = total_assets - curr_liab
            if capital_employed > 0:
                return round((ebit / capital_employed) * 100, 2)
        return None

    def _compute_interest_coverage(self, annual: List[Dict]) -> Optional[float]:
        """Interest Coverage = EBIT / Interest Expense."""
        if not annual:
            return None
        latest = annual[0]
        ebit = latest.get("operating_income")
        interest = latest.get("interest_expense")
        if ebit and interest and interest != 0:
            # Interest expense is typically negative in yfinance
            return round(abs(ebit / interest), 2)
        return None

    def _compute_fcf_yield(self, annual: List[Dict], market_cap: Optional[int]) -> Optional[float]:
        """FCF Yield = Free Cash Flow / Market Cap × 100."""
        if not annual or not market_cap or market_cap <= 0:
            return None
        latest = annual[0]
        fcf = latest.get("free_cash_flow")
        if fcf:
            return round((fcf / market_cap) * 100, 2)
        return None

    def _compute_cagr(self, annual: List[Dict], field: str) -> Optional[float]:
        """Compute 3-year CAGR for a field (revenue or net_income)."""
        if len(annual) < 3:
            return None
        latest_val = annual[0].get(field)
        oldest_val = annual[-1].get(field) if len(annual) >= 3 else annual[2].get(field)
        if not latest_val or not oldest_val or oldest_val <= 0 or latest_val <= 0:
            return None
        years = min(len(annual) - 1, 4)  # Use actual span
        try:
            cagr = ((latest_val / oldest_val) ** (1 / years) - 1) * 100
            return round(cagr, 2)
        except (ValueError, ZeroDivisionError):
            return None

    def _compute_payout_ratio(self, annual: List[Dict], info: Dict) -> Optional[float]:
        """Dividend Payout Ratio = Dividends / Net Income × 100."""
        if not annual:
            return None
        net_income = annual[0].get("net_income")
        div_yield = info.get("dividend_yield_pct")
        market_cap = info.get("market_cap")
        if net_income and div_yield and market_cap and net_income > 0:
            total_dividends = market_cap * (div_yield / 100)
            return round((total_dividends / net_income) * 100, 1)
        return None


# Singleton
ratio_calculator = RatioCalculator()
