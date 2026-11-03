"""
How much to invest in one stock: three independent limits, and the
smallest one wins.

1. Risk budget: put at most `risk_pct` of the portfolio at risk. The stop is
   the low end of the stock's tested 80% price range for the holding period
   (the price falls below it only about 1 time in 10), so
   shares = (capital x risk_pct) / (price - stop).
2. Kelly: from the tested chance of beating the market (p) and the
   reward-to-risk ratio of the range (b), Kelly's fraction is p - (1 - p) / b.
   Full Kelly is far too aggressive for noisy estimates, so a quarter of it is used.
3. Caps from the evidence: 10% of the portfolio for a Buy in a verified holding
   period, 3% when there is no tested edge (Hold), 0% for Sell, red flags or
   weak governance (C halves the cap, D or no data means 0).
"""

import math
from typing import Dict, List, Optional


def position_size(price: float, stop: Optional[float], target: Optional[float], chance: Optional[float],
                  verdict: str, verified: bool, governance: Optional[str], red_flags: List[str],
                  capital: float, risk_pct: float) -> Dict:
    notes: List[str] = []
    out = {"capital": capital, "risk_pct": risk_pct, "price": price, "stop": stop, "target": target}
    if not price or price <= 0 or not stop or stop >= price:
        out.update({"amount": 0, "shares": 0, "weight_pct": 0.0,
                    "notes": ["No tested price range for this stock yet, so a safe stop can't be set."]})
        return out

    risk_per_share = price - stop
    qty_risk = math.floor(capital * risk_pct / 100 / risk_per_share)
    w_risk = qty_risk * price / capital
    notes.append(f"Risk budget {risk_pct:g}% of ₹{capital:,.0f} = ₹{capital * risk_pct / 100:,.0f}; "
                 f"stop ₹{stop:,.2f} is ₹{risk_per_share:,.2f} below the price → up to {qty_risk:,} shares "
                 f"({w_risk * 100:.1f}% of the portfolio).")

    b = (target - price) / risk_per_share if target and target > price else None
    kelly = None
    if chance is not None and b:
        kelly = chance - (1 - chance) / b
    w_kelly = max(0.0, kelly / 4) if kelly is not None else 0.0
    if kelly is not None:
        notes.append(f"Kelly: chance {chance * 100:.0f}%, reward/risk {b:.2f} → full Kelly {kelly * 100:.1f}%, "
                     f"a quarter of it {w_kelly * 100:.1f}%.")

    if verdict == "sell":
        cap, why = 0.0, "Sell verdict: no new position."
    elif verdict == "buy" and verified:
        cap, why = 0.10, "Buy in a tested holding period: at most 10% of the portfolio."
    else:
        cap, why = 0.03, "No tested edge for this holding period: a starter position of at most 3%."
    if red_flags:
        cap, why = 0.0, f"Red flags ({', '.join(f.replace('_', ' ') for f in red_flags)}): no new position."
    elif governance == "C":
        cap, why = cap / 2, why + " Governance grade C halves it."
    elif governance not in ("A", "B"):
        cap, why = 0.0, "Governance grade D or not enough data: no new position."
    notes.append(why)

    limits = {"risk_budget": w_risk, "quarter_kelly": w_kelly, "evidence_cap": cap}
    weight = max(0.0, min(limits.values()))
    shares = math.floor(weight * capital / price)
    binding = min(limits, key=limits.get)
    out.update({
        "amount": round(shares * price, 2), "shares": shares, "weight_pct": round(shares * price / capital * 100, 2),
        "limits_pct": {k: round(v * 100, 2) for k, v in limits.items()}, "binding_limit": binding,
        "loss_if_stopped": round(shares * risk_per_share, 2),
        "gain_if_target": round(shares * (target - price), 2) if target else None,
        "reward_to_risk": round(b, 2) if b else None, "kelly_pct": round(kelly * 100, 2) if kelly is not None else None,
        "notes": notes,
    })
    return out
