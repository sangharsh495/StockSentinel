"""
Valuation Engine — Intrinsic value computation using four complementary models.

Models:
  1. Discounted Cash Flow (DCF) — Future cash flow present value
  2. Graham Number — Conservative deep-value formula
  3. PEG Valuation — Growth-adjusted fair price (Peter Lynch)
  4. EV/EBITDA Relative — Sector-relative enterprise valuation

Each model returns:
  - Intrinsic/Fair value estimate
  - Margin of Safety % (positive = undervalued, negative = overvalued)
  - Verdict: DEEPLY_UNDERVALUED, UNDERVALUED, FAIRLY_VALUED, OVERVALUED, DEEPLY_OVERVALUED

Consensus combines all models into a single Buffett Score (0-100) and Value Grade (A+ to D).
"""

import math
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Sector median EV/EBITDA benchmarks (approximate)
SECTOR_EV_EBITDA = {
    "technology": 22,
    "financial services": 12,
    "healthcare": 16,
    "consumer cyclical": 14,
    "consumer defensive": 18,
    "industrials": 13,
    "energy": 8,
    "basic materials": 9,
    "utilities": 10,
    "real estate": 15,
    "communication services": 14,
    # Indian sectors
    "information technology": 22,
    "financials": 12,
    "pharma": 18,
    "fmcg": 35,
    "automobile": 14,
    "metals": 8,
    "oil & gas": 7,
    "banking": 10,
    "cement": 12,
    "telecom": 10,
}

# Discount rates by market/cap
DISCOUNT_RATES = {
    "IN_LARGE": 0.10,    # Indian large-cap: 10%
    "IN_MID": 0.12,      # Indian mid-cap: 12%
    "IN_SMALL": 0.14,    # Indian small-cap: 14%
    "US_LARGE": 0.08,    # US large-cap: 8%
    "US_MID": 0.10,      # US mid-cap: 10%
    "US_SMALL": 0.12,    # US small-cap: 12%
}

TERMINAL_GROWTH = 0.03  # 3% terminal growth (GDP proxy)

VERDICT_THRESHOLDS = [
    (30, "DEEPLY_UNDERVALUED"),
    (10, "UNDERVALUED"),
    (-10, "FAIRLY_VALUED"),
    (-30, "OVERVALUED"),
    (-999, "DEEPLY_OVERVALUED"),
]

VALUE_GRADES = [
    (85, "A+"), (75, "A"), (65, "B+"), (55, "B"),
    (45, "C+"), (35, "C"), (25, "D+"), (0, "D"),
]


def _margin_of_safety(fair_value: float, current_price: float) -> float:
    """Margin of Safety = (Fair Value - Price) / Fair Value × 100."""
    if fair_value <= 0:
        return 0
    return round(((fair_value - current_price) / fair_value) * 100, 1)


def _verdict_from_mos(mos: float) -> str:
    """Determine verdict from margin of safety percentage."""
    for threshold, verdict in VERDICT_THRESHOLDS:
        if mos >= threshold:
            return verdict
    return "DEEPLY_OVERVALUED"


def _get_discount_rate(market: str, market_cap: Optional[int]) -> float:
    """Get appropriate discount rate based on market and cap size."""
    prefix = "US" if market and market.upper() == "US" else "IN"
    if market_cap:
        if market_cap > 500_000_000_000:  # >500B = large
            size = "LARGE"
        elif market_cap > 50_000_000_000:  # >50B = mid
            size = "MID"
        else:
            size = "SMALL"
    else:
        size = "MID"
    return DISCOUNT_RATES.get(f"{prefix}_{size}", 0.10)


class ValuationEngine:
    """Computes intrinsic value using multiple valuation models."""

    def compute_valuation(
        self,
        symbol: str,
        current_price: float,
        info: Dict[str, Any],
        annual_financials: List[Dict[str, Any]],
        market: str = "IN",
    ) -> Dict[str, Any]:
        """
        Run all 4 valuation models and produce consensus.

        Args:
            symbol: Stock symbol
            current_price: Current market price
            info: yfinance info dict (P/E, EPS, book_value, etc.)
            annual_financials: List of annual financial records
            market: "IN" or "US"
        """
        if current_price <= 0:
            return self._empty_result(symbol, current_price, "Invalid price")

        market_cap = info.get("market_cap")
        discount_rate = _get_discount_rate(market, market_cap)

        models = {}

        # --- Model 1: DCF ---
        dcf = self._dcf_valuation(
            current_price, annual_financials, info, discount_rate
        )
        if dcf:
            models["dcf"] = dcf

        # --- Model 2: Graham Number ---
        graham = self._graham_valuation(current_price, info)
        if graham:
            models["graham"] = graham

        # --- Model 3: PEG Valuation ---
        peg = self._peg_valuation(current_price, info)
        if peg:
            models["peg"] = peg

        # --- Model 4: EV/EBITDA Relative ---
        ev = self._ev_ebitda_valuation(current_price, info, annual_financials)
        if ev:
            models["ev_ebitda"] = ev

        # --- Consensus ---
        if models:
            values = [m["intrinsic_value"] for m in models.values() if m.get("intrinsic_value")]
            if values:
                consensus_value = round(sum(values) / len(values), 2)
                consensus_mos = _margin_of_safety(consensus_value, current_price)
                consensus_verdict = _verdict_from_mos(consensus_mos)
            else:
                consensus_value = None
                consensus_mos = 0
                consensus_verdict = "INSUFFICIENT_DATA"
        else:
            consensus_value = None
            consensus_mos = 0
            consensus_verdict = "INSUFFICIENT_DATA"

        # --- Buffett Score (0-100) ---
        buffett_score = self._compute_buffett_score(
            consensus_mos, info, annual_financials, models
        )

        # Value Grade
        value_grade = "D"
        for threshold, grade in VALUE_GRADES:
            if buffett_score >= threshold:
                value_grade = grade
                break

        return {
            "symbol": symbol.upper(),
            "current_price": current_price,
            "discount_rate_pct": round(discount_rate * 100, 1),
            "valuation_models": models,
            "consensus_value": consensus_value,
            "consensus_margin_of_safety_pct": consensus_mos,
            "consensus_verdict": consensus_verdict,
            "buffett_score": buffett_score,
            "value_grade": value_grade,
            "models_used": len(models),
        }

    def _dcf_valuation(
        self,
        current_price: float,
        annual: List[Dict],
        info: Dict,
        discount_rate: float,
    ) -> Optional[Dict]:
        """
        Discounted Cash Flow model.
        Uses Free Cash Flow with growth projection.
        """
        # Get latest FCF
        fcf = None
        if annual:
            fcf = annual[0].get("free_cash_flow")
        if not fcf or fcf <= 0:
            # Fallback to operating cash flow
            if annual:
                fcf = annual[0].get("operating_cash_flow")
            if not fcf or fcf <= 0:
                return None

        shares = info.get("shares_outstanding")
        if not shares or shares <= 0:
            return None

        fcf_per_share = fcf / shares

        # Determine growth rate from historical data
        growth_rate = 0.08  # Default 8%
        earnings_growth = info.get("earnings_growth")
        revenue_growth = info.get("revenue_growth")

        if earnings_growth and earnings_growth > 0:
            growth_rate = min(earnings_growth / 100, 0.20)  # Cap at 20%
        elif revenue_growth and revenue_growth > 0:
            growth_rate = min(revenue_growth / 100, 0.15)  # Cap at 15%

        # Project FCF for 10 years + terminal value
        projection_years = 10
        total_pv = 0.0

        for year in range(1, projection_years + 1):
            # Decay growth rate gradually
            year_growth = growth_rate * (1 - (year - 1) * 0.05)  # Slow decay
            year_growth = max(year_growth, TERMINAL_GROWTH)  # Floor at terminal

            projected_fcf = fcf_per_share * ((1 + year_growth) ** year)
            pv = projected_fcf / ((1 + discount_rate) ** year)
            total_pv += pv

        # Terminal value (Gordon Growth Model)
        terminal_fcf = fcf_per_share * ((1 + growth_rate) ** projection_years) * (1 + TERMINAL_GROWTH)
        terminal_value = terminal_fcf / (discount_rate - TERMINAL_GROWTH)
        terminal_pv = terminal_value / ((1 + discount_rate) ** projection_years)

        intrinsic_value = round(total_pv + terminal_pv, 2)

        # Sanity check: DCF shouldn't be more than 5x or less than 0.1x current price
        if intrinsic_value > current_price * 5 or intrinsic_value < current_price * 0.1:
            return None

        mos = _margin_of_safety(intrinsic_value, current_price)

        return {
            "model": "Discounted Cash Flow",
            "intrinsic_value": intrinsic_value,
            "margin_of_safety_pct": mos,
            "verdict": _verdict_from_mos(mos),
            "assumptions": {
                "growth_rate_pct": round(growth_rate * 100, 1),
                "discount_rate_pct": round(discount_rate * 100, 1),
                "terminal_growth_pct": round(TERMINAL_GROWTH * 100, 1),
                "projection_years": projection_years,
                "fcf_per_share": round(fcf_per_share, 2),
            },
        }

    def _graham_valuation(
        self, current_price: float, info: Dict
    ) -> Optional[Dict]:
        """
        Graham Number = √(22.5 × EPS × Book Value per Share).
        """
        eps = info.get("eps")
        book_value = info.get("book_value")

        if not eps or not book_value or eps <= 0 or book_value <= 0:
            return None

        graham_value = math.sqrt(22.5 * eps * book_value)
        graham_value = round(graham_value, 2)

        mos = _margin_of_safety(graham_value, current_price)

        return {
            "model": "Graham Number",
            "intrinsic_value": graham_value,
            "margin_of_safety_pct": mos,
            "verdict": _verdict_from_mos(mos),
            "assumptions": {
                "eps": eps,
                "book_value": book_value,
                "multiplier": 22.5,
            },
        }

    def _peg_valuation(
        self, current_price: float, info: Dict
    ) -> Optional[Dict]:
        """
        PEG-based Fair Price: Fair P/E = Growth Rate, Fair Price = Fair P/E × EPS.
        """
        eps = info.get("eps")
        pe = info.get("pe_ratio")
        earnings_growth = info.get("earnings_growth")

        if not eps or eps <= 0 or not pe or pe <= 0:
            return None

        # Use earnings growth, or fall back to revenue growth
        growth = earnings_growth
        if not growth or growth <= 0:
            growth = info.get("revenue_growth")
        if not growth or growth <= 0:
            return None

        # Peter Lynch: Fair P/E ≈ Growth Rate
        fair_pe = growth  # growth is already in % from scraper
        if fair_pe < 5:
            fair_pe = 5  # Floor
        if fair_pe > 50:
            fair_pe = 50  # Cap

        fair_price = round(fair_pe * eps, 2)

        if fair_price <= 0:
            return None

        mos = _margin_of_safety(fair_price, current_price)

        return {
            "model": "PEG Valuation (Peter Lynch)",
            "intrinsic_value": fair_price,
            "margin_of_safety_pct": mos,
            "verdict": _verdict_from_mos(mos),
            "assumptions": {
                "eps": eps,
                "earnings_growth_pct": growth,
                "fair_pe": fair_pe,
                "current_pe": pe,
            },
        }

    def _ev_ebitda_valuation(
        self,
        current_price: float,
        info: Dict,
        annual: List[Dict],
    ) -> Optional[Dict]:
        """
        EV/EBITDA Relative Valuation: Fair Price based on sector median.
        """
        # Get EBITDA
        ebitda = None
        if annual:
            ebitda = annual[0].get("ebitda")
        if not ebitda or ebitda <= 0:
            return None

        shares = info.get("shares_outstanding")
        if not shares or shares <= 0:
            return None

        # Get sector median
        sector = (info.get("sector") or "").lower()
        industry = (info.get("industry") or "").lower()
        sector_median = (
            SECTOR_EV_EBITDA.get(sector)
            or SECTOR_EV_EBITDA.get(industry)
            or 15  # Default fallback
        )

        # Fair EV = Sector Median EV/EBITDA × Company EBITDA
        total_debt = 0
        cash = 0
        if annual:
            total_debt = annual[0].get("total_debt") or 0
            cash = annual[0].get("cash_and_equivalents") or 0

        fair_ev = sector_median * ebitda
        fair_equity = fair_ev - total_debt + cash
        fair_price = round(fair_equity / shares, 2)

        if fair_price <= 0:
            return None

        mos = _margin_of_safety(fair_price, current_price)

        # Current EV/EBITDA
        current_ev = info.get("enterprise_value") or (info.get("market_cap", 0) + total_debt - cash)
        current_ev_ebitda = round(current_ev / ebitda, 2) if ebitda > 0 else None

        return {
            "model": "EV/EBITDA Relative",
            "intrinsic_value": fair_price,
            "margin_of_safety_pct": mos,
            "verdict": _verdict_from_mos(mos),
            "assumptions": {
                "sector": sector.title() or "Unknown",
                "sector_median_ev_ebitda": sector_median,
                "current_ev_ebitda": current_ev_ebitda,
                "ebitda": ebitda,
            },
        }

    def _compute_buffett_score(
        self,
        consensus_mos: float,
        info: Dict,
        annual: List[Dict],
        models: Dict,
    ) -> int:
        """
        Composite 0-100 Buffett Value Score.
        Factors:
          - Margin of Safety (30%): How far below intrinsic value
          - Financial Quality (25%): ROE, margins, growth
          - Debt Safety (20%): Debt-to-equity, interest coverage
          - Consistency (15%): Earnings stability
          - Dividend (10%): Yield and payout
        """
        score = 0.0

        # --- Factor 1: Margin of Safety (30%) ---
        mos_score = 50  # neutral
        if consensus_mos >= 30:
            mos_score = 100
        elif consensus_mos >= 20:
            mos_score = 85
        elif consensus_mos >= 10:
            mos_score = 70
        elif consensus_mos >= 0:
            mos_score = 55
        elif consensus_mos >= -15:
            mos_score = 35
        else:
            mos_score = 15
        score += mos_score * 0.30

        # --- Factor 2: Financial Quality (25%) ---
        quality_score = 50
        roe = info.get("roe")
        margin = info.get("profit_margin")
        if roe and roe > 20:
            quality_score += 15
        elif roe and roe > 12:
            quality_score += 8
        if margin and margin > 15:
            quality_score += 15
        elif margin and margin > 8:
            quality_score += 8
        # Growth bonus
        growth = info.get("earnings_growth")
        if growth and growth > 15:
            quality_score += 10
        elif growth and growth > 5:
            quality_score += 5
        quality_score = min(quality_score, 100)
        score += quality_score * 0.25

        # --- Factor 3: Debt Safety (20%) ---
        debt_score = 50
        d2e = info.get("debt_to_equity")
        if d2e is not None:
            d2e_norm = d2e / 100 if d2e > 5 else d2e
            if d2e_norm < 0.3:
                debt_score = 95
            elif d2e_norm < 0.7:
                debt_score = 75
            elif d2e_norm < 1.2:
                debt_score = 50
            else:
                debt_score = 20
        cr = info.get("current_ratio")
        if cr and cr > 2:
            debt_score += 10
        elif cr and cr > 1.5:
            debt_score += 5
        debt_score = min(debt_score, 100)
        score += debt_score * 0.20

        # --- Factor 4: Consistency (15%) ---
        consistency_score = 50
        if annual and len(annual) >= 3:
            # Check if profitable in all years
            profitable_years = sum(
                1 for a in annual if (a.get("net_income") or 0) > 0
            )
            consistency_score = (profitable_years / len(annual)) * 100
        score += consistency_score * 0.15

        # --- Factor 5: Dividend (10%) ---
        div_score = 30  # No dividend isn't terrible
        div_yield = info.get("dividend_yield_pct")
        if div_yield and div_yield > 0:
            if div_yield > 4:
                div_score = 90
            elif div_yield > 2:
                div_score = 75
            elif div_yield > 0.5:
                div_score = 55
        score += div_score * 0.10

        return min(100, max(0, int(round(score))))

    def _empty_result(
        self, symbol: str, price: float, reason: str
    ) -> Dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "current_price": price,
            "valuation_models": {},
            "consensus_value": None,
            "consensus_margin_of_safety_pct": 0,
            "consensus_verdict": "INSUFFICIENT_DATA",
            "buffett_score": 0,
            "value_grade": "N/A",
            "models_used": 0,
            "error": reason,
        }


# Singleton
valuation_engine = ValuationEngine()
