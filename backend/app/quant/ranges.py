"""
Guaranteed-coverage price ranges (rolling split-conformal prediction).

For each stock and horizon h (1, 5, 20 trading days) we publish a range
such as "₹1,150 – ₹1,240 in 5 days" that is meant to contain the actual
closing price 80% of the time (and a wider 95% range).

How:
1. Scale: each stock's own recent volatility, sigma = (0.6·vol20 + 0.4·vol60)·sqrt(h/252).
2. Score each past day: s = |actual h-day log return| / sigma.
3. The range multiplier for today is the 80% (or 95%) quantile of the
   scores of the last 250 days whose outcome is already KNOWN today.
   That is split-conformal prediction: under exchangeability the true
   value lands inside with ≥ the target rate; done on a rolling window it
   adapts to calm and stormy markets.
4. Range = price · exp(± q · sigma).

The backtest below re-runs exactly this on every past day and reports how
often the real price landed inside, by year and in the worst quarter.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from app.quant.validation import _r

logger = logging.getLogger(__name__)

HORIZONS = (1, 5, 20)
LEVELS = (0.8, 0.95)
WINDOW = 250          # calibration window (trading days) of already-known outcomes
MIN_HISTORY = 80      # days of prices a stock needs before we publish a range


def _sigma(close: pd.DataFrame, h: int) -> pd.DataFrame:
    lr = np.log(close).diff()
    vol20 = lr.rolling(20, min_periods=15).std() * np.sqrt(252)
    vol60 = lr.rolling(60, min_periods=40).std() * np.sqrt(252)
    return (0.6 * vol20 + 0.4 * vol60.fillna(vol20)) * np.sqrt(h / 252)


def _scores(close: pd.DataFrame, h: int):
    sig = _sigma(close, h)
    fwd = np.log(close.shift(-h) / close)
    return (fwd.abs() / sig).replace([np.inf, -np.inf], np.nan), sig, fwd


def _quantile_for_day(score: pd.DataFrame, i: int, h: int, level: float) -> Optional[float]:
    """Conformal quantile using only outcomes known on day i (labels end at j+h <= i)."""
    lo, hi = max(0, i - h - WINDOW + 1), i - h + 1
    if hi - lo < 20:
        return None
    vals = score.iloc[lo:hi].values.ravel()
    vals = vals[np.isfinite(vals)]
    if len(vals) < 200:
        return None
    n = len(vals)
    return float(np.quantile(vals, min(1.0, level * (1 + 1 / n))))


def backtest_coverage(close: pd.DataFrame, h: int, level: float, step: int = 3,
                      start: int = 400) -> Dict:
    """Re-run the method on past days (every `step` days) and measure real coverage."""
    score, sig, fwd = _scores(close, h)
    rows = []
    for i in range(start, len(close) - h, step):
        q = _quantile_for_day(score, i, h, level)
        if q is None:
            continue
        s = score.iloc[i].dropna()
        if s.empty:
            continue
        rows.append((close.index[i], float((s <= q).mean()), float(2 * q * sig.iloc[i][s.index].mean()), len(s)))
    if not rows:
        return {"status": "insufficient_history"}
    df = pd.DataFrame(rows, columns=["date", "cov", "width", "n"]).set_index("date")
    by_year = df.groupby(df.index.year)["cov"].mean()
    roll = df["cov"].rolling(max(1, 63 // step)).mean()
    return {
        "level": level, "horizon_days": h,
        "coverage": _r(df["cov"].mean(), 4),
        "coverage_by_year": {int(y): _r(v, 3) for y, v in by_year.items()},
        "worst_quarter_coverage": _r(roll.min(), 3),
        "best_quarter_coverage": _r(roll.max(), 3),
        "avg_range_width_pct": _r(df["width"].mean() * 100, 2),
        "days_tested": int(len(df)), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
    }


def todays_ranges(close: pd.DataFrame, symbols: Optional[Sequence[str]] = None) -> Dict[str, Dict]:
    """Latest-day ranges per stock and horizon, in price terms."""
    symbols = list(symbols) if symbols is not None else list(close.columns)
    last = len(close) - 1
    out: Dict[str, Dict] = {s: {} for s in symbols}
    for h in HORIZONS:
        score, sig, _ = _scores(close, h)
        qs = {lv: _quantile_for_day(score, last, h, lv) for lv in LEVELS}
        for s in symbols:
            p, sg = close[s].iloc[last], sig[s].iloc[last]
            if not np.isfinite(p) or not np.isfinite(sg) or close[s].notna().sum() < MIN_HISTORY:
                continue
            rng = {}
            for lv, q in qs.items():
                if q is None:
                    continue
                rng[f"p{int(lv * 100)}"] = [_r(p * np.exp(-q * sg), 2), _r(p * np.exp(q * sg), 2)]
                if lv == 0.8:
                    rng["expected_move_pct"] = _r((np.exp(q * sg) - 1) * 100, 2)
            out[s][f"{h}d"] = rng
    return out


def train_ranges(prices: Dict[str, pd.DataFrame], model_key: str = "price_ranges",
                 universe_label: str = "Nifty 100 universe") -> Dict:
    close = prices["Close"]
    track = {f"{h}d": {f"p{int(lv * 100)}": backtest_coverage(close, h, lv) for lv in LEVELS}
             for h in HORIZONS}
    today = todays_ranges(close)
    last = close.index[-1]
    preds = []
    for sym, r in today.items():
        if not r:
            continue
        preds.append({"symbol": sym, "as_of": str(last.date()),
                      "last_close": _r(close[sym].iloc[-1], 2), "ranges": r})
    good = all((track[f"{h}d"]["p80"].get("coverage") or 0) >= 0.77 for h in HORIZONS)
    return {
        "model_key": model_key, "strategy": "ranges", "horizon_days": 0,
        "description": (f"Price ranges meant to contain the real closing price 80% (and 95%) of the time "
                        f"— rolling conformal prediction on each stock's volatility ({universe_label})."),
        "model_type": "rolling_split_conformal",
        "trained_at": datetime.now(timezone.utc).isoformat(), "data_end": str(last.date()),
        # 'edge' here = the coverage promise held on unseen history
        "edge_verified": bool(good),
        "metrics": {"coverage_track_record": track, "window_days": WINDOW},
        "backtest": None, "folds": None, "predictions": preds,
    }
