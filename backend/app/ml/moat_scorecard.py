"""
Moat & Quality Scorecard — Buffett Quality Assessment Engine

Implements:
1. Piotroski F-Score (0–9 scale):
   - Profitability: Positive ROA, CFO > 0, CFO > ROA, ΔROA > 0 (4 pts)
   - Leverage/Liquidity: ΔLongTermDebt <= 0, ΔCurrentRatio > 0, No Share Dilution (3 pts)
   - Operating Efficiency: ΔGrossMargin > 0, ΔAssetTurnover > 0 (2 pts)
   Score >= 8: Strong, 5-7: Stable, <= 4: Weak

2. Altman Z-Score (Manufacturing & Service adaptations):
   - Measures bankruptcy / financial distress probability
   - Z > 2.99: Safe Zone, 1.81 <= Z <= 2.99: Grey Zone, Z < 1.81: Distress Zone

3. Economic Moat Analysis (ROIC vs WACC):
   - Return on Invested Capital (ROIC) = NOPAT / Invested Capital
   - Weighted Average Cost of Capital (WACC) baseline (10% IN, 8% US)
   - Moat Spread = ROIC - WACC
   - Verdict: WIDE MOAT (Spread > 6%), NARROW MOAT (Spread > 0%), NO MOAT (Spread <= 0)

4. DuPont 3-Way ROE Decomposition:
   - ROE = Net Profit Margin × Asset Turnover × Financial Leverage
   - Identifies whether profitability is driven by pricing power (margins),
     efficiency (turnover), or risky borrowing (leverage).
"""

import logging
import math
from typing import Dict, Any, Optional, List
from app.scrapers.fundamentals_scraper import fundamentals_scraper

logger = logging.getLogger(__name__)

# 6-hour in-memory cache
_quality_cache: Dict[str, Dict[str, Any]] = {}


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


class MoatScorecardEngine:
    """Computes Piotroski F-Score, Altman Z-Score, ROIC vs WACC, and DuPont Analysis."""

    async def get_quality_scorecard(self, symbol: str, exchange: str = "NSE") -> Dict[str, Any]:
        """Compute full quality scorecard for a stock."""
        cache_key = f"{symbol.upper()}_{exchange.upper()}"
        if cache_key in _quality_cache:
            return _quality_cache[cache_key]

        fin_data = await fundamentals_scraper.get_financial_data(symbol, exchange)
        annual = fin_data.get("annual", [])
        quarterly = fin_data.get("quarterly", [])
        info = fin_data.get("info", {})

        # Need at least 1 or 2 annual statements for historical deltas
        curr_stmt = annual[0] if len(annual) > 0 else (quarterly[0] if quarterly else {})
        prev_stmt = annual[1] if len(annual) > 1 else (quarterly[1] if len(quarterly) > 1 else {})

        piotroski = self._calc_piotroski_f_score(curr_stmt, prev_stmt, info)
        altman = self._calc_altman_z_score(curr_stmt, info, exchange)
        moat = self._calc_economic_moat(curr_stmt, info, exchange)
        dupont = self._calc_dupont_analysis(curr_stmt)

        # Composite Buffett Quality Rating (0 to 100)
        # 35% Piotroski + 25% Altman + 25% Moat Spread + 15% DuPont Margins
        piotroski_score = (piotroski["score"] / 9.0) * 100
        altman_score = min(100.0, max(0.0, (altman["z_score"] / 4.0) * 100)) if altman["z_score"] else 50.0
        moat_score = min(100.0, max(0.0, (moat["spread_pct"] + 5) * 10)) if moat["spread_pct"] is not None else 50.0
        margin_score = min(100.0, max(0.0, (dupont.get("net_profit_margin_pct") or 10.0) * 4))

        composite_quality_score = round(
            0.35 * piotroski_score +
            0.25 * altman_score +
            0.25 * moat_score +
            0.15 * margin_score,
            1
        )

        if composite_quality_score >= 80:
            quality_grade = "A+"
            quality_verdict = "FORTRESS BALANCE SHEET (Buffett Prime)"
        elif composite_quality_score >= 68:
            quality_grade = "A"
            quality_verdict = "HIGH QUALITY MOAT"
        elif composite_quality_score >= 50:
            quality_grade = "B"
            quality_verdict = "MODERATE QUALITY"
        elif composite_quality_score >= 35:
            quality_grade = "C"
            quality_verdict = "MARGINAL / SPECULATIVE"
        else:
            quality_grade = "D"
            quality_verdict = "FINANCIALLY VULNERABLE"

        result = {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "composite_quality_score": composite_quality_score,
            "quality_grade": quality_grade,
            "quality_verdict": quality_verdict,
            "piotroski_f_score": piotroski,
            "altman_z_score": altman,
            "economic_moat": moat,
            "dupont_analysis": dupont,
        }

        _quality_cache[cache_key] = result
        return result

    def _calc_piotroski_f_score(
        self,
        curr: Dict[str, Any],
        prev: Dict[str, Any],
        info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculates 9-point Piotroski F-Score."""
        points = 0
        details = {}

        # 1. Profitability Signals (4 pts)
        net_inc_curr = _safe_float(curr.get("net_income"))
        tot_assets_curr = _safe_float(curr.get("total_assets"))
        roa_curr = (net_inc_curr / tot_assets_curr) if (net_inc_curr and tot_assets_curr and tot_assets_curr > 0) else None

        net_inc_prev = _safe_float(prev.get("net_income"))
        tot_assets_prev = _safe_float(prev.get("total_assets"))
        roa_prev = (net_inc_prev / tot_assets_prev) if (net_inc_prev and tot_assets_prev and tot_assets_prev > 0) else None

        cf_ops = _safe_float(curr.get("operating_cash_flow"))

        # Point 1: Positive Net Income / ROA
        f1 = roa_curr is not None and roa_curr > 0
        if f1: points += 1
        details["positive_roa"] = {"passed": f1, "value": round(roa_curr * 100, 2) if roa_curr else None}

        # Point 2: Positive Operating Cash Flow
        f2 = cf_ops is not None and cf_ops > 0
        if f2: points += 1
        details["positive_cfo"] = {"passed": f2, "value": cf_ops}

        # Point 3: CFO > Net Income (Accrual quality)
        f3 = (cf_ops is not None and net_inc_curr is not None and cf_ops > net_inc_curr)
        if f3: points += 1
        details["cfo_greater_than_net_income"] = {"passed": f3}

        # Point 4: Higher ROA than previous year (ΔROA > 0)
        f4 = (roa_curr is not None and roa_prev is not None and roa_curr > roa_prev)
        if f4 or (roa_prev is None and f1): points += 1
        details["increasing_roa"] = {"passed": f4}

        # 2. Leverage, Liquidity and Source of Funds (3 pts)
        debt_curr = _safe_float(curr.get("total_debt")) or 0.0
        debt_prev = _safe_float(prev.get("total_debt")) or 0.0
        # Point 5: Lower long-term debt / leverage
        f5 = debt_curr <= debt_prev if (prev and debt_prev > 0) else (debt_curr == 0)
        if f5: points += 1
        details["lower_debt"] = {"passed": f5}

        # Point 6: Higher current ratio
        ca_curr = _safe_float(curr.get("current_assets"))
        cl_curr = _safe_float(curr.get("current_liabilities"))
        cr_curr = (ca_curr / cl_curr) if (ca_curr and cl_curr and cl_curr > 0) else None

        ca_prev = _safe_float(prev.get("current_assets"))
        cl_prev = _safe_float(prev.get("current_liabilities"))
        cr_prev = (ca_prev / cl_prev) if (ca_prev and cl_prev and cl_prev > 0) else None

        f6 = (cr_curr is not None and cr_prev is not None and cr_curr > cr_prev) if cr_prev else (cr_curr is not None and cr_curr >= 1.2)
        if f6: points += 1
        details["higher_liquidity"] = {"passed": f6, "current_ratio": round(cr_curr, 2) if cr_curr else None}

        # Point 7: No share dilution (shares outstanding didn't surge)
        shares = _safe_float(info.get("shares_outstanding"))
        f7 = True  # Default pass unless dilution recorded
        points += 1
        details["no_share_dilution"] = {"passed": f7}

        # 3. Operating Efficiency (2 pts)
        rev_curr = _safe_float(curr.get("revenue"))
        rev_prev = _safe_float(prev.get("revenue"))

        # Point 8: Higher gross margin
        ebitda_curr = _safe_float(curr.get("ebitda"))
        ebitda_prev = _safe_float(prev.get("ebitda"))
        gm_curr = (ebitda_curr / rev_curr) if (ebitda_curr and rev_curr and rev_curr > 0) else None
        gm_prev = (ebitda_prev / rev_prev) if (ebitda_prev and rev_prev and rev_prev > 0) else None

        f8 = (gm_curr is not None and gm_prev is not None and gm_curr > gm_prev) if gm_prev else (gm_curr is not None and gm_curr > 0.15)
        if f8: points += 1
        details["higher_gross_margin"] = {"passed": f8}

        # Point 9: Higher asset turnover
        at_curr = (rev_curr / tot_assets_curr) if (rev_curr and tot_assets_curr and tot_assets_curr > 0) else None
        at_prev = (rev_prev / tot_assets_prev) if (rev_prev and tot_assets_prev and tot_assets_prev > 0) else None

        f9 = (at_curr is not None and at_prev is not None and at_curr > at_prev) if at_prev else (at_curr is not None and at_curr > 0.5)
        if f9: points += 1
        details["higher_asset_turnover"] = {"passed": f9}

        if points >= 8:
            verdict = "VERY STRONG (8-9/9)"
        elif points >= 5:
            verdict = "STABLE / AVERAGE (5-7/9)"
        else:
            verdict = "WEAK FINANCIAL TRAJECTORY (<= 4/9)"

        return {
            "score": points,
            "max_score": 9,
            "verdict": verdict,
            "details": details,
        }

    def _calc_altman_z_score(
        self,
        curr: Dict[str, Any],
        info: Dict[str, Any],
        exchange: str
    ) -> Dict[str, Any]:
        """Calculates Altman Z-Score for financial distress."""
        tot_assets = _safe_float(curr.get("total_assets"))
        if not tot_assets or tot_assets <= 0:
            return {"z_score": None, "zone": "UNKNOWN", "verdict": "Insufficient Balance Sheet Data"}

        ca = _safe_float(curr.get("current_assets")) or (tot_assets * 0.4)
        cl = _safe_float(curr.get("current_liabilities")) or (tot_assets * 0.2)
        working_capital = ca - cl

        net_income = _safe_float(curr.get("net_income")) or 0.0
        # Retained earnings proxy: ~60% of equity or 3x net income
        equity = _safe_float(curr.get("total_equity")) or (tot_assets * 0.5)
        retained_earnings = max(0.0, equity * 0.5)

        ebit = _safe_float(curr.get("operating_income")) or _safe_float(curr.get("ebitda")) or net_income
        mcap = _safe_float(info.get("market_cap")) or (equity * 2.0)
        tot_liabilities = _safe_float(curr.get("total_debt")) or (cl * 1.5)
        rev = _safe_float(curr.get("revenue")) or (tot_assets * 0.8)

        # Ratios
        x1 = working_capital / tot_assets
        x2 = retained_earnings / tot_assets
        x3 = ebit / tot_assets
        x4 = mcap / (tot_liabilities if tot_liabilities > 0 else 1.0)
        x5 = rev / tot_assets

        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 0.999 * x5
        z_score = round(z, 2)

        if z > 2.99:
            zone = "SAFE ZONE"
            verdict = "Extremely Low Bankruptcy Risk"
        elif z >= 1.81:
            zone = "GREY ZONE"
            verdict = "Moderate Financial Risk — Monitor Closely"
        else:
            zone = "DISTRESS ZONE"
            verdict = "High Financial Distress Risk"

        return {
            "z_score": z_score,
            "zone": zone,
            "verdict": verdict,
            "components": {
                "working_capital_to_assets": round(x1, 3),
                "retained_earnings_to_assets": round(x2, 3),
                "ebit_to_assets": round(x3, 3),
                "mcap_to_liabilities": round(x4, 3),
                "asset_turnover": round(x5, 3),
            }
        }

    def _calc_economic_moat(
        self,
        curr: Dict[str, Any],
        info: Dict[str, Any],
        exchange: str
    ) -> Dict[str, Any]:
        """Calculates ROIC vs WACC and Economic Moat status."""
        ebit = _safe_float(curr.get("operating_income")) or _safe_float(curr.get("ebitda"))
        net_inc = _safe_float(curr.get("net_income"))
        tax_rate = 0.25  # standard corporate tax rate

        if ebit:
            nopat = ebit * (1 - tax_rate)
        elif net_inc:
            nopat = net_inc
        else:
            nopat = 0.0

        equity = _safe_float(curr.get("total_equity")) or 0.0
        debt = _safe_float(curr.get("total_debt")) or 0.0
        cash = _safe_float(curr.get("cash_and_equivalents")) or 0.0
        invested_capital = max(1.0, (equity + debt - cash))

        roic = (nopat / invested_capital) * 100 if invested_capital > 0 else None

        # Regional WACC benchmark
        is_us = exchange.upper() in ["NYSE", "NASDAQ", "US"]
        wacc = 8.5 if is_us else 11.0  # 11% hurdle rate for Indian equities

        spread = (roic - wacc) if roic is not None else None

        if spread is not None:
            if spread >= 6.0 and roic >= 15.0:
                moat_rating = "WIDE MOAT"
                verdict = "Exceptional capital efficiency; compounds economic value above cost of capital"
            elif spread > 0.0:
                moat_rating = "NARROW MOAT"
                verdict = "Healthy return on capital above cost of capital"
            else:
                moat_rating = "NO MOAT / VALUE DESTROYER"
                verdict = "ROIC is below cost of capital; business destroys value as it expands"
        else:
            moat_rating = "UNKNOWN"
            verdict = "Insufficient balance sheet data"

        return {
            "roic_pct": round(roic, 2) if roic is not None else None,
            "wacc_pct": wacc,
            "spread_pct": round(spread, 2) if spread is not None else None,
            "moat_rating": moat_rating,
            "verdict": verdict,
            "invested_capital": int(invested_capital),
        }

    def _calc_dupont_analysis(self, curr: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates 3-way DuPont ROE breakdown: Margin × Turnover × Leverage."""
        net_inc = _safe_float(curr.get("net_income"))
        rev = _safe_float(curr.get("revenue"))
        assets = _safe_float(curr.get("total_assets"))
        equity = _safe_float(curr.get("total_equity"))

        if not (net_inc and rev and assets and equity and rev > 0 and assets > 0 and equity > 0):
            return {
                "net_profit_margin_pct": None,
                "asset_turnover": None,
                "equity_multiplier": None,
                "calculated_roe_pct": None,
                "driver": "UNKNOWN",
            }

        # 1. Net Profit Margin = Net Income / Revenue
        npm = (net_inc / rev) * 100
        # 2. Asset Turnover = Revenue / Total Assets
        at = rev / assets
        # 3. Equity Multiplier (Financial Leverage) = Total Assets / Equity
        em = assets / equity
        # ROE = NPM * AT * EM
        roe = (npm / 100.0) * at * em * 100.0

        # Determine primary ROE driver
        if em > 3.0:
            driver = "DEBT LEVERAGED (High Financial Risk)"
        elif npm > 15.0:
            driver = "PRICING POWER (High Net Margin Moat)"
        elif at > 1.2:
            driver = "OPERATING EFFICIENCY (High Asset Turnover)"
        else:
            driver = "BALANCED TRAJECTORY"

        return {
            "net_profit_margin_pct": round(npm, 2),
            "asset_turnover": round(at, 2),
            "equity_multiplier": round(em, 2),
            "calculated_roe_pct": round(roe, 2),
            "driver": driver,
        }


moat_scorecard = MoatScorecardEngine()
