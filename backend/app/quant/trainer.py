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
from app.quant.ensemble import LiveEnsemble, market_candidates, multi_walk_forward, stock_candidates
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

    cands = stock_candidates()
    wf, mm = multi_walk_forward(df, fc, y, h, cands, fit_target=rank_target)
    metrics = evaluate(wf.oos, h)
    base_col, asc, rule_desc = RULE_BASELINES[strategy]
    bt = backtest(wf.oos, df, h, baseline_col=base_col, baseline_ascending=asc)
    bt["rule_description"] = rule_desc

    # Final model on all labelled history, then score the latest day.
    final = LiveEnsemble(cands, mm["chosen_live"]).fit(
        df.loc[labeled, fc].values, rank_target[labeled].values)
    calibrator = fit_calibrator(wf.oos)

    last_date = df.index.get_level_values("date").max()
    today = df.xs(last_date, level="date")
    raw = pd.Series(final.score(today[fc].values), index=today.index)
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
        "description": STRATEGY_INFO[strategy], "model_type": f"multi_model:{mm['chosen_live']}",
        "trained_at": datetime.now(timezone.utc).isoformat(), "data_end": str(last_date.date()),
        "edge_verified": _useful_edge(metrics, bt),
        "metrics": {**metrics, "ranking_skill_verified": metrics.get("edge_verified", False),
                    "multi_model": mm},
        "backtest": bt, "folds": wf.folds, "predictions": preds,
    }


def _useful_edge(metrics: Dict, bt: Dict) -> bool:
    """
    A stock model counts as having an edge only if (1) its ranking skill is
    statistically significant AND (2) its top-10 portfolio, after trading
    costs, beat simply holding the whole universe equally weighted.
    Skill that trading costs eat is not useful to an investor.
    """
    m, ew = (bt.get("model") or {}), (bt.get("equal_weight") or {})
    return bool(metrics.get("edge_verified") and m.get("cagr_pct") is not None
                and ew.get("cagr_pct") is not None and m["cagr_pct"] > ew["cagr_pct"])


def train_investor_factor(prices: Dict[str, pd.DataFrame], horizon: int = 60) -> Dict:
    """
    Transparent investor score — no fitting: equal-weight blend of three
    well-documented factors (12-1 month momentum, low volatility, EPS
    growth), each as a cross-sectional rank. Because nothing is fitted, the
    whole backtest period is out-of-sample; it is still checked against
    the equal-weight basket after costs.
    """
    df = build_dataset(prices, horizon)
    d = df[df.index.get_level_values("date") >= "2020-11-01"].copy()
    rk = lambda c: d.groupby(level="date")[c].rank(pct=True) - 0.5  # noqa: E731
    d["f_momentum"] = rk("ret_250_skip20")
    d["f_low_vol"] = -rk("vol_60")
    d["f_eps_growth"] = rk("eps_yoy_growth").fillna(0) if "eps_yoy_growth" in d else 0.0
    d["factor_score"] = d["f_momentum"] + d["f_low_vol"] + d["f_eps_growth"]

    lab = d.dropna(subset=["fwd_excess"])
    med = lab.groupby(level="date")["fwd_excess"].transform("median")
    oos = lab[["fwd_ret", "fwd_excess"]].copy()
    oos["prob_raw"] = lab["factor_score"]
    oos["y"] = (lab["fwd_excess"] > med).astype(int)
    oos["fold"] = 0
    oos["score"] = oos.groupby(level="date")["prob_raw"].rank(pct=True)
    oos["prob"] = np.nan
    metrics = evaluate(oos.assign(prob=0.5), horizon)
    for k in ("accuracy", "accuracy_always_majority", "brier", "brier_skill_vs_base_rate", "calibration"):
        metrics.pop(k, None)
    bt = backtest(oos, d, horizon, baseline_col="ret_250_skip20")
    bt["rule_description"] = "Buy the 10 strongest 12-month momentum stocks"
    calibrator = fit_calibrator(oos)

    last = d.index.get_level_values("date").max()
    today = d.xs(last, level="date")
    score = today["factor_score"].rank(pct=True)
    preds = []
    for rank, sym in enumerate(today["factor_score"].sort_values(ascending=False).index, start=1):
        r = today.loc[sym]
        preds.append({
            "symbol": sym, "as_of": str(last.date()), "rank": rank,
            "score_percentile": _r(score[sym] * 100, 1),
            "probability": _r(calibrator.predict([score[sym]])[0], 4),
            **bucket_outcome(calibrator, score[sym]),
            "factors": {"momentum_pct": _r((r["f_momentum"] + 0.5) * 100, 0),
                        "low_volatility_pct": _r((r["f_low_vol"] + 0.5) * 100, 0),
                        "eps_growth_pct": _r((r["f_eps_growth"] + 0.5) * 100, 0)},
            "signals": {"ret_1y_pct": _r(r["ret_250"] * 100, 2), "volatility_pct": _r(r["vol_60"] * 100, 1),
                        "eps_yoy_growth_pct": _r(r.get("eps_yoy_growth", np.nan) * 100, 1),
                        "last_surprise_pct": _r(r.get("last_surprise_pct", np.nan), 1),
                        "dist_52w_high_pct": _r(r["dist_52w_high"] * 100, 1)},
        })
    return {
        "model_key": "stock_investor_factor", "strategy": "investor_factor", "horizon_days": horizon,
        "description": "Investor factor score: momentum + low volatility + EPS growth, rebalanced every 60 days.",
        "model_type": "transparent_factor_blend", "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_end": str(last.date()), "edge_verified": _useful_edge(metrics, bt),
        "metrics": {**metrics, "ranking_skill_verified": metrics.get("edge_verified", False)},
        "backtest": bt, "folds": None, "predictions": preds,
    }


def train_market_outlook(prices: Dict[str, pd.DataFrame], horizon: int) -> Dict:
    m = market_features(prices).dropna()
    from app.quant.participants import participant_features
    part = participant_features(m.index)
    if part is not None:
        # Logistic regression needs complete rows: fill pre-2020 positioning
        # with the neutral (median) value and flag it.
        part = part.reindex(m.index)
        m["has_positioning"] = part.notna().all(axis=1).astype(float)
        m = m.join(part.fillna(part.median()))
    no = prices["nifty"]["Open"]
    fwd = np.log(no.shift(-1 - horizon) / no.shift(-1)).reindex(m.index)
    df = m.copy()
    df["fwd_ret"] = fwd
    df["fwd_excess"] = fwd
    df.index = pd.MultiIndex.from_arrays([df.index, ["NIFTY"] * len(df)], names=["date", "symbol"])
    fc = list(m.columns)
    y = (df["fwd_ret"] > 0).where(df["fwd_ret"].notna())

    cands = market_candidates()
    wf, mm = multi_walk_forward(df, fc, y, horizon, cands, cross_sectional=False)
    metrics = evaluate(wf.oos, horizon, cross_sectional=False)
    labeled = y.notna()
    base_rate = float(y[labeled].mean())
    hist = df.loc[labeled, "fwd_ret"]

    final = LiveEnsemble(cands, mm["chosen_live"]).fit(
        df.loc[labeled, fc].values, y[labeled].astype(int).values)
    last = df.iloc[[-1]]
    model_prob = float(fit_calibrator(wf.oos).predict(final.raw(last[fc].values))[0])
    edge = metrics.get("edge_verified", False)
    current = {k: _r(v, 4) for k, v in last[fc].iloc[0].items()}

    return {
        "model_key": f"market_{horizon}d", "strategy": "market", "horizon_days": horizon,
        "description": f"Chance the Nifty 50 is higher {horizon} trading days from now.",
        "model_type": f"multi_model:{mm['chosen_live']}",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_end": str(df.index.get_level_values("date")[-1].date()),
        "edge_verified": edge, "metrics": {**metrics, "multi_model": mm}, "folds": wf.folds, "backtest": None,
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


def run_all(strategies: Optional[List[str]] = None, period: str = "10y",
            include_ipo: bool = True) -> List[Dict]:
    from app.quant.data_checks import build_report, price_check

    prices = load_prices(period=period)
    try:
        pcheck = price_check(prices)
    except Exception as e:  # a failed check must never stop training
        pcheck = {"status": "error", "detail": str(e)[:200]}
    flagged = (pcheck.get("disagree") or {}) if isinstance(pcheck, dict) else {}
    results = []
    for s in strategies or list(HORIZONS):
        logger.info(f"Training stock strategy: {s}")
        results.append(train_stock_strategy(prices, s))
    logger.info("Scoring investor factor blend")
    results.append(train_investor_factor(prices))
    # Cross-source check: flag picks whose latest price differs between Yahoo and NSE
    for r in results:
        for p in r.get("predictions") or []:
            if p["symbol"] in flagged:
                p["data_warning"] = (f"Yahoo and NSE closing prices differ by {flagged[p['symbol']]:+.2f}%; "
                                     "this stock's signals may be off.")
    for h in (5, 20):
        logger.info(f"Training market outlook: {h}d")
        results.append(train_market_outlook(prices, h))
    ipo_summary = None
    if include_ipo:
        try:
            ipo_result, ipo_summary = train_ipo(prices)
            results.append(ipo_result)
        except Exception as e:  # source site down: keep the stock models
            logger.warning(f"IPO model skipped: {e}")
    report = build_report(None, ipo_summary)
    report["prices"] = pcheck
    results.append({
        "model_key": "data_quality", "strategy": "data", "horizon_days": 0,
        "description": "Cross-source checks: Yahoo vs NSE official prices, investorgain vs ipowatch GMP.",
        "model_type": "data_checks", "trained_at": report["checked_at"],
        "data_end": pcheck.get("date") if isinstance(pcheck, dict) else None,
        "edge_verified": False, "metrics": report, "backtest": None, "folds": None, "predictions": [],
    })
    logger.info(f"Data checks: prices={pcheck.get('status')} gmp={ipo_summary}")
    return results


def train_ipo(prices: Dict[str, pd.DataFrame]):
    from app.quant.ipo_model import train_ipo_model
    from app.scrapers.ipo_history import scrape_current, scrape_history

    logger.info("Scraping IPO history (cached) and current IPOs")
    hist = scrape_history(2019)
    cur = scrape_current()
    from app.quant.data_checks import attach_gmp_checks

    listed = {r["ig_id"] for r in hist}
    cur = [c for c in cur if c["ig_id"] not in listed]
    summary = attach_gmp_checks(cur)
    return train_ipo_model(hist, cur, prices), summary
