"""
Trainer — runs the full test → backtest → final fit → predict pipeline.

Output of each model:
- metrics: out-of-sample accuracy, AUC, ranking skill, calibration
- backtest: cost-aware portfolio results vs Nifty, equal-weight, and a
  simple rule-based strategy (so you can see if ML adds anything)
- predictions: today's calibrated probability per stock, plus the
  historical outcome range of stocks that got similar probabilities
- edge_verified: False means "this model has not shown a reliable edge";
  the API passes that through so the app never oversells a number.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.quant.data import load_prices
from app.quant.features import HORIZONS, build_dataset, feature_columns, market_features
from app.quant.validation import (
    backtest, bucket_outcome, evaluate, fit_calibrator, predict_score, walk_forward, _r,
)

logger = logging.getLogger(__name__)

# Simple rule each ML strategy is compared against ("condition" strategies).
RULE_BASELINES = {
    "trader": ("rsi_14", True, "Buy the 10 most oversold stocks (lowest RSI-14)"),
    "swing": ("ret_250_skip20", False, "Buy the 10 strongest 12-month momentum stocks"),
    "investor": ("ret_250_skip20", False, "Buy the 10 strongest 12-month momentum stocks"),
}

STRATEGY_INFO = {
    "trader": "Short-term trader: 5-day hold. Chance a stock beats the median stock of the universe.",
    "swing": "Swing trader: 20-day hold. Chance a stock beats the median stock of the universe.",
    "investor": "Positional investor: 60-day hold. Chance a stock beats the median stock of the universe.",
}


def stock_model():
    # Learns to rank stocks by future return versus peers. Heavily
    # regularised because daily stock returns are mostly noise.
    return HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=2000,
        l2_regularization=5.0, max_features=0.7, random_state=7,
    )


def market_model():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500))


def train_stock_strategy(prices: Dict[str, pd.DataFrame], strategy: str) -> Dict:
    h = HORIZONS[strategy]
    df = build_dataset(prices, h)
    fc = feature_columns(df)
    labeled = df["fwd_excess"].notna()
    med = df.groupby(level="date")["fwd_excess"].transform("median")
    y = (df["fwd_excess"] > med).where(labeled)
    rank_target = df.groupby(level="date")["fwd_excess"].rank(pct=True) - 0.5

    wf = walk_forward(df, fc, y, h, model_factory=stock_model, fit_target=rank_target)
    metrics = evaluate(wf.oos, h)
    base_col, asc, rule_desc = RULE_BASELINES[strategy]
    bt = backtest(wf.oos, df, h, baseline_col=base_col, baseline_ascending=asc)
    bt["rule_description"] = rule_desc

    # Final model on all labelled history, then score the latest day.
    final = stock_model()
    final.fit(df.loc[labeled, fc].values, rank_target[labeled].values)
    calibrator = fit_calibrator(wf.oos)

    last_date = df.index.get_level_values("date").max()
    today = df.xs(last_date, level="date")
    raw = pd.Series(predict_score(final, today[fc].values), index=today.index)
    score = raw.rank(pct=True)
    preds = []
    for rank, sym in enumerate(raw.sort_values(ascending=False).index, start=1):
        row = today.loc[sym]
        preds.append({
            "symbol": sym, "as_of": str(last_date.date()), "rank": rank,
            "score_percentile": _r(score[sym] * 100, 1),
            "probability": _r(calibrator.predict([score[sym]])[0], 4),
            **bucket_outcome(calibrator, score[sym]),
            "signals": {
                "ret_20d_pct": _r(row["ret_20"] * 100, 2), "ret_1y_pct": _r(row["ret_250"] * 100, 2),
                "rsi_14": _r(row["rsi_14"], 1), "dist_52w_high_pct": _r(row["dist_52w_high"] * 100, 1),
                "volatility_pct": _r(row["vol_20"] * 100, 1), "volume_vs_avg": _r(np.exp(row["volume_z"]), 2),
            },
        })

    return {
        "model_key": f"stock_{strategy}", "strategy": strategy, "horizon_days": h,
        "description": STRATEGY_INFO[strategy], "model_type": "gradient_boosting_rank",
        "trained_at": datetime.now(timezone.utc).isoformat(), "data_end": str(last_date.date()),
        "edge_verified": metrics.get("edge_verified", False),
        "metrics": metrics, "backtest": bt, "folds": wf.folds, "predictions": preds,
    }


def train_market_outlook(prices: Dict[str, pd.DataFrame], horizon: int) -> Dict:
    m = market_features(prices).dropna()
    no = prices["nifty"]["Open"]
    fwd = np.log(no.shift(-1 - horizon) / no.shift(-1)).reindex(m.index)
    df = m.copy()
    df["fwd_ret"] = fwd
    df["fwd_excess"] = fwd
    df.index = pd.MultiIndex.from_arrays([df.index, ["NIFTY"] * len(df)], names=["date", "symbol"])
    fc = list(m.columns)
    y = (df["fwd_ret"] > 0).where(df["fwd_ret"].notna())

    wf = walk_forward(df, fc, y, horizon, model_factory=market_model, cross_sectional=False)
    metrics = evaluate(wf.oos, horizon, cross_sectional=False)
    labeled = y.notna()
    base_rate = float(y[labeled].mean())
    hist = df.loc[labeled, "fwd_ret"]

    final = market_model().fit(df.loc[labeled, fc].values, y[labeled].astype(int).values)
    last = df.iloc[[-1]]
    model_prob = float(fit_calibrator(wf.oos).predict(predict_score(final, last[fc].values))[0])
    edge = metrics.get("edge_verified", False)
    current = {k: _r(v, 4) for k, v in last[fc].iloc[0].items()}

    return {
        "model_key": f"market_{horizon}d", "strategy": "market", "horizon_days": horizon,
        "description": f"Chance the Nifty 50 is higher {horizon} trading days from now.",
        "model_type": "logistic_regression",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_end": str(df.index.get_level_values("date")[-1].date()),
        "edge_verified": edge, "metrics": metrics, "folds": wf.folds, "backtest": None,
        "predictions": [{
            "symbol": "NIFTY", "as_of": str(df.index.get_level_values("date")[-1].date()),
            # Without a proven edge, the honest number is the historical base rate.
            "probability": _r(model_prob if edge else base_rate, 4),
            "model_probability": _r(model_prob, 4),
            "historical_base_rate": _r(base_rate, 4),
            "source": "model" if edge else "historical_base_rate",
            "historical_avg_return_pct": _r(hist.mean() * 100, 2),
            "typical_range_pct": [_r(hist.quantile(0.1) * 100, 2), _r(hist.quantile(0.9) * 100, 2)],
            "current_regime": current,
        }],
    }


def run_all(strategies: Optional[List[str]] = None, period: str = "10y") -> List[Dict]:
    prices = load_prices(period=period)
    results = []
    for s in strategies or list(HORIZONS):
        logger.info(f"Training stock strategy: {s}")
        results.append(train_stock_strategy(prices, s))
    for h in (5, 20):
        logger.info(f"Training market outlook: {h}d")
        results.append(train_market_outlook(prices, h))
    return results
