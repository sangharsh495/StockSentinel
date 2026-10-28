"""
Walk-forward validation, accuracy metrics and cost-aware backtests.

How a model is tested:
1. Train on years 1..k, skip an "embargo" gap as long as the holding
   period (so no training label peeks into the test window), then predict
   the next half-year it has never seen. Slide forward and repeat.
2. Only these out-of-sample (OOS) predictions are used for every metric
   and backtest below. In-sample numbers are never reported.
3. The edge is "verified" only if the ranking skill (information
   coefficient) is statistically above zero on non-overlapping periods
   AND AUC beats a coin flip.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
RISK_FREE = 0.065          # approx. Indian T-bill yield, for Sharpe
COST_PER_SIDE = 0.002      # STT + stamp + exchange + slippage on delivery trades


def make_model(seed: int = 7) -> HistGradientBoostingClassifier:
    # Market data is noisy: shallow trees, big leaves, strong L2 to avoid
    # memorising noise.
    return HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=400,
        l2_regularization=2.0, max_features=0.7, early_stopping=False, random_state=seed,
    )


def predict_score(model, X) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    return model.predict(X)


@dataclass
class WalkForwardResult:
    oos: pd.DataFrame                    # rows: date, symbol, prob_raw, label cols
    folds: List[Dict] = field(default_factory=list)


def walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    target: pd.Series,
    horizon: int,
    min_train_days: int = 750,
    test_days: int = 126,
    model_factory: Callable = make_model,
    fit_target: Optional[pd.Series] = None,
    cross_sectional: bool = True,
) -> WalkForwardResult:
    """
    target: binary outcome used for every metric (1 = good outcome).
    fit_target: optional continuous target the model trains on instead
    (e.g. return rank). Its predictions are treated as a score and are
    turned into probabilities later by the calibrator.
    """
    mask = target.notna()
    labeled = df[mask]
    y = target[mask].astype(int)
    fy = (fit_target[mask] if fit_target is not None else y).astype(float)
    dates = labeled.index.get_level_values("date")
    udates = np.array(sorted(dates.unique()))
    embargo = horizon + 1

    oos_parts, folds = [], []
    for start in range(min_train_days, len(udates), test_days):
        test_d = udates[start:start + test_days]
        train_end = udates[start - embargo]
        tr = dates <= train_end
        te = (dates >= test_d[0]) & (dates <= test_d[-1])
        if te.sum() == 0 or y[tr].nunique() < 2:
            continue
        model = model_factory()
        model.fit(labeled.loc[tr, feature_cols].values, fy[tr].values)
        p = predict_score(model, labeled.loc[te, feature_cols].values)
        part = labeled.loc[te, ["fwd_ret", "fwd_excess"]].copy()
        part["y"] = y[te].values
        part["prob_raw"] = p
        part["fold"] = len(folds)
        oos_parts.append(part)
        auc = roc_auc_score(part["y"], p) if part["y"].nunique() == 2 else np.nan
        folds.append({
            "test_start": str(pd.Timestamp(test_d[0]).date()),
            "test_end": str(pd.Timestamp(test_d[-1]).date()),
            "train_rows": int(tr.sum()), "test_rows": int(te.sum()), "auc": _r(auc),
        })
        logger.info(f"fold {folds[-1]['test_start']}..{folds[-1]['test_end']} AUC={auc:.3f}")

    oos = pd.concat(oos_parts) if oos_parts else pd.DataFrame()
    if not oos.empty:
        # Stock models: calibrate on the day's rank of the score (scale-free,
        # so the final model's scores map the same way as the fold models').
        oos["score"] = (oos.groupby(level="date")["prob_raw"].rank(pct=True)
                        if cross_sectional else oos["prob_raw"])
        oos["prob"] = _sequential_calibration(oos)
    return WalkForwardResult(oos=oos, folds=folds)


class BucketCalibrator:
    """
    Score -> probability by measured history: split past scores into
    equal-sized buckets and use each bucket's real hit rate, shrunk toward
    the overall rate when a bucket is small. Also keeps each bucket's
    realised return range, used to show the 'expected move'.
    """

    def __init__(self, n_buckets: int = 10, shrink: int = 50):
        self.n_buckets, self.shrink = n_buckets, shrink

    def fit(self, score, y, excess=None):
        score, y = np.asarray(score, float), np.asarray(y, float)
        edges = np.unique(np.quantile(score, np.linspace(0, 1, self.n_buckets + 1)))
        self.inner = edges[1:-1]
        b = np.searchsorted(self.inner, score, side="right")
        prior = y.mean()
        df = pd.DataFrame({"b": b, "y": y, "x": np.asarray(excess, float) if excess is not None else np.nan})
        g = df.groupby("b")
        st = g.agg(hits=("y", "sum"), n=("y", "size"), avg_excess=("x", "mean"),
                   p10=("x", lambda v: v.quantile(0.1)), p90=("x", lambda v: v.quantile(0.9)))
        st["hit"] = st["hits"] / st["n"]
        st["prob"] = (st["hits"] + self.shrink * prior) / (st["n"] + self.shrink)
        self.stats = st.reindex(range(len(self.inner) + 1))
        self.stats["prob"] = self.stats["prob"].fillna(prior)
        return self

    def bucket(self, score):
        return np.searchsorted(self.inner, np.asarray(score, float), side="right")

    def predict(self, score) -> np.ndarray:
        return self.stats["prob"].values[self.bucket(score)]


def _sequential_calibration(oos: pd.DataFrame) -> pd.Series:
    """
    Turn scores into probabilities without peeking: the calibrator for
    fold k is fitted only on folds before k. The first fold has no history
    and gets NaN (excluded from probability metrics).
    """
    prob = pd.Series(np.nan, index=oos.index)
    for k in sorted(oos["fold"].unique())[1:]:
        hist = oos[oos["fold"] < k]
        cal = BucketCalibrator().fit(hist["score"].values, hist["y"].values)
        cur = oos["fold"] == k
        prob[cur] = cal.predict(oos.loc[cur, "score"].values)
    return prob


def _r(x, d=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def _non_overlapping_dates(dates: pd.Index, step: int) -> np.ndarray:
    u = np.array(sorted(pd.Index(dates).unique()))
    return u[::step]


def evaluate(oos: pd.DataFrame, horizon: int, cross_sectional: bool = True) -> Dict:
    """Accuracy, calibration and ranking-skill metrics on OOS predictions."""
    y, p = oos["y"].values, oos["prob_raw"].values
    # Probability metrics use the sequentially calibrated column, and the
    # reference forecast is the base rate known from earlier data only.
    pc_df = oos.dropna(subset=["prob"])
    yc, pc = pc_df["y"].values, pc_df["prob"].values
    base = float(y.mean())
    g = oos.groupby("fold")["y"].agg(["sum", "count"]).cumsum().shift(1)
    prior = (g["sum"] / g["count"]).reindex(pc_df["fold"]).values
    prior = np.where(np.isnan(prior), base, prior)
    brier = brier_score_loss(yc, pc)
    brier_ref = brier_score_loss(yc, prior)
    metrics = {
        "oos_rows": int(len(oos)),
        "oos_start": str(oos.index.get_level_values("date").min().date()),
        "oos_end": str(oos.index.get_level_values("date").max().date()),
        "base_rate": _r(base),
        "auc": _r(roc_auc_score(y, p)),
        "accuracy": _r(((pc >= 0.5) == yc).mean()),
        "accuracy_always_majority": _r(max(yc.mean(), 1 - yc.mean())),
        "brier": _r(brier),
        "brier_skill_vs_base_rate": _r(1 - brier / brier_ref),
    }

    # Calibration: when the model says 60%, does it happen ~60% of the time?
    bins = np.clip((pc * 10).astype(int), 0, 9)
    cal = (
        pd.DataFrame({"bin": bins, "p": pc, "y": yc})
        .groupby("bin").agg(predicted=("p", "mean"), actual=("y", "mean"), n=("y", "size"))
    )
    metrics["calibration"] = [
        {"predicted": _r(r.predicted, 3), "actual": _r(r.actual, 3), "n": int(r.n)}
        for r in cal.itertuples() if r.n >= 50
    ]

    if cross_sectional:
        # Rank IC per date: does a higher probability mean a higher return
        # than peers on the same day? t-stat uses non-overlapping dates only.
        ic = oos.groupby(level="date").apply(
            lambda g: g["prob_raw"].corr(g["fwd_excess"], method="spearman") if len(g) >= 20 else np.nan
        ).dropna()
        ic_no = ic.loc[ic.index.isin(_non_overlapping_dates(ic.index, horizon))]
        t = ic_no.mean() / (ic_no.std(ddof=1) / np.sqrt(len(ic_no))) if len(ic_no) > 5 else np.nan
        metrics["rank_ic_mean"] = _r(ic.mean())
        metrics["rank_ic_tstat"] = _r(t, 2)
        metrics["rank_ic_positive_pct"] = _r((ic_no > 0).mean(), 3)

        # Decile table: realised returns by predicted-probability decile (per day)
        dec = oos.groupby(level="date")["prob_raw"].transform(
            lambda s: pd.qcut(s.rank(method="first"), 10, labels=False) if len(s) >= 20 else np.nan
        )
        d = oos.assign(decile=dec).dropna(subset=["decile"])
        tab = d.groupby("decile").agg(
            avg_excess=("fwd_excess", "mean"), hit_rate=("y", "mean"), n=("y", "size")
        )
        metrics["deciles"] = [
            {"decile": int(i) + 1, "avg_excess_return_pct": _r(r.avg_excess * 100, 3),
             "beat_market_pct": _r(r.hit_rate * 100, 2), "n": int(r.n)}
            for i, r in tab.iterrows()
        ]
        if len(tab) == 10:
            metrics["top_minus_bottom_decile_pct"] = _r(
                (tab["avg_excess"].iloc[-1] - tab["avg_excess"].iloc[0]) * 100, 3)
        metrics["edge_verified"] = bool(
            metrics["auc"] is not None and metrics["auc"] > 0.51
            and metrics["rank_ic_tstat"] is not None and metrics["rank_ic_tstat"] > 2.0
        )
    else:
        # Single time series (e.g. market direction): t-stat on per-fold-free
        # bootstrap of AUC using non-overlapping dates.
        dts = oos.index.get_level_values("date")
        idx = np.asarray(dts.isin(_non_overlapping_dates(dts, horizon)))
        yy, pp = y[idx], p[idx]
        rng = np.random.default_rng(0)
        boots = []
        for _ in range(500):
            s = rng.integers(0, len(yy), len(yy))
            if len(np.unique(yy[s])) == 2:
                boots.append(roc_auc_score(yy[s], pp[s]))
        lo = float(np.percentile(boots, 5)) if boots else np.nan
        metrics["auc_non_overlapping"] = _r(roc_auc_score(yy, pp)) if len(np.unique(yy)) == 2 else None
        metrics["auc_90pct_lower_bound"] = _r(lo)
        metrics["edge_verified"] = bool(np.isfinite(lo) and lo > 0.5)
    return metrics


def fit_calibrator(oos: pd.DataFrame) -> BucketCalibrator:
    """Calibrator on ALL out-of-sample history — used for live predictions."""
    return BucketCalibrator().fit(oos["score"].values, oos["y"].values, oos["fwd_excess"].values)


def bucket_outcome(cal: BucketCalibrator, score: float) -> Dict:
    r = cal.stats.iloc[int(cal.bucket([score])[0])]
    return {
        "expected_excess_pct": _r(r["avg_excess"] * 100, 2),
        "typical_range_pct": [_r(r["p10"] * 100, 2), _r(r["p90"] * 100, 2)],
        "historical_hit_rate_pct": _r(r["hit"] * 100, 1),
        "historical_samples": int(r["n"]) if pd.notna(r["n"]) else 0,
    }


def _perf(period_rets: pd.Series, horizon: int) -> Dict:
    if period_rets.empty:
        return {}
    per_year = TRADING_DAYS / horizon
    eq = (1 + period_rets).cumprod()
    years = len(period_rets) / per_year
    cagr = eq.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = period_rets.std(ddof=1) * np.sqrt(per_year)
    dd = (eq / eq.cummax() - 1).min()
    return {
        "cagr_pct": _r(cagr * 100, 2), "volatility_pct": _r(vol * 100, 2),
        "sharpe": _r((cagr - RISK_FREE) / vol, 2) if vol > 0 else None,
        "max_drawdown_pct": _r(dd * 100, 2), "win_periods_pct": _r((period_rets > 0).mean() * 100, 1),
        "total_return_pct": _r((eq.iloc[-1] - 1) * 100, 1),
    }


def backtest(
    oos: pd.DataFrame,
    features: pd.DataFrame,
    horizon: int,
    top_n: int = 10,
    baseline_col: Optional[str] = None,
    baseline_ascending: bool = False,
) -> Dict:
    """
    Every `horizon` days, buy the top_n stocks by model probability at the
    next open, hold `horizon` days, pay costs on what changed. Compared
    against the Nifty, an equal-weight basket of the whole universe, and
    a simple rule-based strategy (baseline_col).
    """
    rebal = _non_overlapping_dates(oos.index.get_level_values("date"), horizon)
    rows = {"model": [], "rule": [], "equal_weight": [], "nifty": []}
    prev = {"model": set(), "rule": set()}
    dates_out = []
    for d in rebal:
        g = oos.xs(d, level="date")
        if len(g) < top_n * 2:
            continue
        mkt = float(np.exp(g["fwd_ret"].iloc[0] - g["fwd_excess"].iloc[0]) - 1)
        simple = np.exp(g["fwd_ret"]) - 1
        picks = {"model": g["prob_raw"].nlargest(top_n).index}
        if baseline_col is not None:
            fb = features.xs(d, level="date").reindex(g.index)[baseline_col].dropna()
            picks["rule"] = (fb.nsmallest(top_n) if baseline_ascending else fb.nlargest(top_n)).index
        for k, idx in picks.items():
            turnover = 1 - len(prev[k] & set(idx)) / top_n
            rows[k].append(simple.loc[idx].mean() - 2 * COST_PER_SIDE * turnover)
            prev[k] = set(idx)
        rows["equal_weight"].append(simple.mean())
        rows["nifty"].append(mkt)
        dates_out.append(d)

    idx = pd.DatetimeIndex(dates_out)
    series = {k: pd.Series(v, index=idx) for k, v in rows.items() if v}
    out = {k: _perf(s, horizon) for k, s in series.items()}
    if "model" in series:
        out["model"]["beat_nifty_periods_pct"] = _r((series["model"] > series["nifty"]).mean() * 100, 1)
        out["model"]["beat_equal_weight_periods_pct"] = _r(
            (series["model"] > series["equal_weight"]).mean() * 100, 1)
        eq = (1 + pd.DataFrame(series)).cumprod()
        step = max(1, len(eq) // 60)
        out["equity_curve"] = [
            {"date": str(d.date()), **{k: _r(v, 4) for k, v in r.items()}}
            for d, r in eq.iloc[::step].iterrows()
        ]
    out["settings"] = {"top_n": top_n, "rebalance_every_days": horizon,
                       "cost_per_side_pct": COST_PER_SIDE * 100, "periods": len(dates_out)}
    return out
