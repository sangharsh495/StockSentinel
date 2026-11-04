"""
Analyst panel: 1,728 independent analyst models, graded on unseen months,
combined into one consensus per stock and holding period.

An analyst = one holding period (1w, 1m, 3m, 1y) x one company-size segment
(all, large, mid, small, by trading liquidity on each date) x one speciality
(trend, momentum, risk, flow, growth, quality, balance sheet, governance,
valuation, dividends, all 57 checks, raw numbers) x one model type
(2 logistic regressions, rank-sum factor, naive Bayes, linear discriminant,
2 gradient-boosting machines, extra trees, random forest).
4 x 4 x 12 x 9 = 1,728 analysts.

Honest grading (weekly): each analyst is refitted once a year on rows whose
outcome was already known, then scored on the following year. Its skill is
the spread between the stocks it is bullish on and the ones it is bearish on
(excess return vs the median stock), with a Newey-West t-stat. Only analysts
with t > 1 get a vote, weighted by (t - 1). The consensus for month m uses
weights from months whose outcomes were known before m, and is itself graded
the same way as the report cards (Buy >= 55%, Sell <= 45%).

Nightly: every analyst is refitted on all known history and votes on today's
stocks; the consensus uses the latest weekly weights.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.quant.multibagger import RankSum, clean_json, newey_west_t

logger = logging.getLogger(__name__)

HORIZONS = {"1w": 5, "1m": 21, "3m": 63, "1y": 250}
CAL_GAP = {5: 12, 21: 35, 63: 100, 250: 380}
SEGMENTS = ["all", "large", "mid", "small"]
SPECIALITIES = ["trend", "momentum", "risk", "flow", "growth", "quality", "balance_sheet", "governance",
                "valuation", "dividend", "all_checks", "raw_numbers"]
FAMILIES = ["logistic_weak", "logistic_strong", "rank_sum", "naive_bayes", "linear_discriminant",
            "boost_shallow", "boost_deep", "extra_trees", "random_forest"]
SPECIALITY_LABEL = {"balance_sheet": "balance sheet", "all_checks": "all 57 checks", "raw_numbers": "raw numbers"}
FAMILY_LABEL = {"logistic_weak": "cautious logistic", "logistic_strong": "logistic", "rank_sum": "factor score",
                "naive_bayes": "naive Bayes", "linear_discriminant": "linear discriminant",
                "boost_shallow": "light boosting", "boost_deep": "deep boosting", "extra_trees": "extra trees",
                "random_forest": "random forest"}
MAX_TRAIN_ROWS = 40000
BUY_P, SELL_P = 0.55, 0.45


@dataclass(frozen=True)
class Analyst:
    horizon: str
    segment: str
    speciality: str
    family: str

    @property
    def key(self) -> str:
        return f"{self.horizon}|{self.segment}|{self.speciality}|{self.family}"

    @property
    def name(self) -> str:
        seg = "all companies" if self.segment == "all" else f"{self.segment} caps"
        return (f"{SPECIALITY_LABEL.get(self.speciality, self.speciality).capitalize()} analyst · {seg} · "
                f"{FAMILY_LABEL[self.family]}")


def all_analysts() -> List[Analyst]:
    return [Analyst(h, s, sp, f) for h in HORIZONS for s in SEGMENTS for sp in SPECIALITIES for f in FAMILIES]


def _model(family: str, seed: int):
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.naive_bayes import GaussianNB

    return {
        "logistic_weak": lambda: LogisticRegression(C=0.05, max_iter=300),
        "logistic_strong": lambda: LogisticRegression(C=1.0, max_iter=300),
        "rank_sum": lambda: RankSum(),
        "naive_bayes": lambda: GaussianNB(),
        "linear_discriminant": lambda: LinearDiscriminantAnalysis(),
        "boost_shallow": lambda: HistGradientBoostingClassifier(max_depth=2, max_iter=60, learning_rate=0.1,
                                                                min_samples_leaf=300, random_state=seed),
        "boost_deep": lambda: HistGradientBoostingClassifier(max_depth=4, max_iter=80, learning_rate=0.06,
                                                             min_samples_leaf=150, random_state=seed),
        "extra_trees": lambda: ExtraTreesClassifier(n_estimators=40, max_depth=6, min_samples_leaf=100,
                                                    n_jobs=-1, random_state=seed),
        "random_forest": lambda: RandomForestClassifier(n_estimators=40, max_depth=6, min_samples_leaf=100,
                                                        max_features=0.5, n_jobs=-1, random_state=seed),
    }[family]()


# --------------------------------------------------------------------- inputs

RAW_EXCLUDE = {"date", "symbol"}


def feature_views(panel: pd.DataFrame, M: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Speciality -> feature matrix (float32, no NaN). Check views use pass/fail/neutral (+1/-1/0)."""
    from app.quant.report_card import CHECK_META

    views = {}
    for sp in SPECIALITIES[:10]:
        cols = [c for c in M.columns if CHECK_META[c]["category"] == sp]
        views[sp] = M[cols].values.astype(np.float32)
    views["all_checks"] = M.values.astype(np.float32)
    raw_cols = [c for c in panel.columns if c not in RAW_EXCLUDE and not c.startswith(("tr_", "ex_"))
                and pd.api.types.is_numeric_dtype(panel[c])]
    ranks = panel.groupby("date")[raw_cols].rank(pct=True)
    views["raw_numbers"] = ranks.fillna(0.5).values.astype(np.float32)
    return views


def segment_masks(panel: pd.DataFrame) -> Dict[str, np.ndarray]:
    liq = panel.groupby("date")["size_liq"].rank(pct=True).fillna(0.5).values
    return {"all": np.ones(len(panel), bool), "large": liq > 2 / 3,
            "mid": (liq > 1 / 3) & (liq <= 2 / 3), "small": liq <= 1 / 3}


def _fit(a: Analyst, X: np.ndarray, y: np.ndarray, rng: np.random.Generator):
    if len(y) > MAX_TRAIN_ROWS:
        idx = rng.choice(len(y), MAX_TRAIN_ROWS, replace=False)
        X, y = X[idx], y[idx]
    if len(y) < 500 or y.min() == y.max():
        return None
    try:
        return _model(a.family, int(rng.integers(1e9))).fit(X, y)
    except Exception as e:      # a degenerate view (e.g. a constant column) must not stop the panel
        logger.debug(f"analyst {a.key} failed to fit: {e}")
        return None


def _predict(model, X: np.ndarray) -> np.ndarray:
    p = model.predict_proba(X)[:, 1]
    return np.clip(p, 0.0, 1.0)


# --------------------------------------------------------------------- weekly grading

def grade(panel: pd.DataFrame, M: pd.DataFrame, first: str = "2022-07-01", refit_months: int = 12,
          seed: int = 0, log: Callable = logger.info) -> Dict:
    """Walk-forward grade every analyst, then test the weighted consensus on unseen months."""
    t0 = datetime.now(timezone.utc)
    rng = np.random.default_rng(seed)
    views = feature_views(panel, M)
    segs = segment_masks(panel)
    dates = panel["date"].values
    analysts = all_analysts()
    weights, skill, consensus_tests, fits = {}, {}, {}, 0
    for hname, h in HORIZONS.items():
        ex = panel[f"ex_{hname}"].values
        lab = ~np.isnan(ex)
        y = (ex > 0).astype(np.int8)
        group = [a for a in analysts if a.horizon == hname]
        test_dates = sorted(d for d in np.unique(dates[lab]) if d >= np.datetime64(first))
        if not test_dates:
            continue
        refits = pd.date_range(first, pd.Timestamp(test_dates[-1]) + pd.Timedelta(days=1), freq=f"{refit_months}MS")
        P = np.full((len(panel), len(group)), np.nan, dtype=np.float32)
        for j, R0 in enumerate(refits):
            R1 = refits[j + 1] if j + 1 < len(refits) else pd.Timestamp.max
            train_t = lab & (dates <= np.datetime64(R0 - pd.Timedelta(days=CAL_GAP[h])))
            block_t = lab & (dates >= np.datetime64(R0)) & (dates < np.datetime64(R1))
            if train_t.sum() < 2000 or not block_t.any():
                continue
            for k, a in enumerate(group):
                tr, te = train_t & segs[a.segment], block_t & segs[a.segment]
                if not te.any():
                    continue
                m = _fit(a, views[a.speciality][tr], y[tr], rng)
                if m is None:
                    continue
                fits += 1
                P[te, k] = _predict(m, views[a.speciality][te])
            log(f"Analysts {hname}: refit {R0.date()} done ({fits} fits so far)")

        # monthly long-short spread per analyst
        test_mask = lab & (dates >= np.datetime64(first))
        months = np.unique(dates[test_mask])
        spread = np.full((len(months), len(group)), np.nan)
        for i, d in enumerate(months):
            rows = test_mask & (dates == d)
            p, e = P[rows], ex[rows]
            for k in range(len(group)):
                pk = p[:, k]
                ok = ~np.isnan(pk)
                if ok.sum() < 30:
                    continue
                bull, bear = ok & (pk > 0.5), ok & (pk <= 0.5)
                if bull.sum() >= 10 and bear.sum() >= 10:
                    spread[i, k] = e[bull].mean() - e[bear].mean()
        lags = max(1, math.ceil(h / 21))
        for k, a in enumerate(group):
            col = spread[:, k]
            col = col[~np.isnan(col)]
            t = newey_west_t(col, lags) if len(col) >= 6 else float("nan")
            skill[a.key] = {"months": int(len(col)), "spread_pct": round(float(col.mean()) * 100, 3) if len(col) else None,
                            "t": None if math.isnan(t) else round(t, 2)}
            weights[a.key] = round(max(0.0, (t if not math.isnan(t) else 0.0) - 1.0), 4)

        # honest consensus: month m uses weights from months known before m
        gap = pd.Timedelta(days=CAL_GAP[h])
        cons = np.full(len(panel), np.nan)
        for i, d in enumerate(months):
            known = months <= d - np.timedelta64(gap)
            if known.sum() < 6:
                continue
            w = []
            for k in range(len(group)):
                col = spread[known, k]
                col = col[~np.isnan(col)]
                t = newey_west_t(col, lags) if len(col) >= 6 else float("nan")
                w.append(max(0.0, (t if not math.isnan(t) else 0.0) - 1.0))
            w = np.array(w)
            if w.sum() <= 0:
                continue
            rows = test_mask & (dates == d)
            p = P[rows].astype(float)
            ww = np.where(np.isnan(p), 0.0, w)
            num = np.nansum(np.nan_to_num(p) * ww, axis=1)
            den = ww.sum(axis=1)
            cons[rows] = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
        consensus_tests[hname] = test_consensus(cons, ex, dates, lags)
        log(f"Analysts {hname}: consensus {consensus_tests[hname]}")
        del P

    skilled = sum(1 for w in weights.values() if w > 0)
    board = sorted(((k, v) for k, v in skill.items() if v["t"] is not None), key=lambda kv: -kv[1]["t"])[:25]
    by_key = {a.key: a for a in analysts}
    return clean_json({
        "model_key": "analyst_panel", "strategy": "analysts", "horizon_days": 250,
        "description": f"{len(analysts)} analyst models graded on unseen months; skilled ones vote on every stock.",
        "model_type": "analyst_panel", "trained_at": t0.isoformat(),
        "data_end": str(pd.Timestamp(panel["date"].max()).date()),
        "edge_verified": any(v.get("verified") for v in consensus_tests.values()),
        "metrics": {
            "analysts": len(analysts), "fits": fits, "skilled_analysts": skilled,
            "segments": SEGMENTS, "specialities": SPECIALITIES, "families": FAMILIES,
            "consensus_tests": consensus_tests,
            "skilled_by_horizon": {h: sum(1 for k, w in weights.items() if k.startswith(h + "|") and w > 0)
                                   for h in HORIZONS},
            "leaderboard": [{"analyst": by_key[k].name, "horizon": by_key[k].horizon, **v} for k, v in board],
            "weights": weights,
            "minutes": round((datetime.now(timezone.utc) - t0).total_seconds() / 60, 1),
        },
        "backtest": None, "folds": None, "predictions": [],
    })


def test_consensus(cons: np.ndarray, ex: np.ndarray, dates: np.ndarray, lags: int) -> Dict:
    ok = ~np.isnan(cons) & ~np.isnan(ex)
    rows = []
    for d in np.unique(dates[ok]):
        m = ok & (dates == d)
        b, s = m & (cons >= BUY_P), m & (cons <= SELL_P)
        if b.sum() < 5 or s.sum() < 5:
            continue
        rows.append((ex[b].mean(), ex[s].mean(), (ex[b] > 0).mean(), (ex[s] > 0).mean(), b.sum()))
    if len(rows) < 6:
        return {"months": len(rows), "verified": False}
    a = np.array(rows)
    t = newey_west_t(a[:, 0] - a[:, 1], lags)
    return {"months": int(len(a)), "buy_beat_market_pct": round(float(a[:, 2].mean()) * 100, 1),
            "sell_beat_market_pct": round(float(a[:, 3].mean()) * 100, 1),
            "buy_minus_sell_pct": round(float((a[:, 0] - a[:, 1]).mean()) * 100, 2),
            "buy_minus_sell_t": None if math.isnan(t) else round(t, 2),
            "avg_buy_picks": round(float(a[:, 4].mean()), 1),
            "verified": bool(len(a) >= 12 and not math.isnan(t) and t > 2 and a[:, 2].mean() > 0.5)}


# --------------------------------------------------------------------- nightly votes

def vote(panel: pd.DataFrame, M: pd.DataFrame, graded: Optional[Dict] = None, seed: int = 1,
         log: Callable = logger.info) -> Dict:
    """Refit every analyst on all known history and let the skilled ones vote on today's stocks."""
    t0 = datetime.now(timezone.utc)
    rng = np.random.default_rng(seed)
    gm = (graded or {}).get("metrics") or {}
    weights = gm.get("weights") or {}
    tests = gm.get("consensus_tests") or {}
    views = feature_views(panel, M)
    segs = segment_masks(panel)
    dates = panel["date"].values
    today = dates.max()
    live = dates == today
    analysts = all_analysts()
    by_key = {a.key: a for a in analysts}
    n_live = int(live.sum())
    syms = panel.loc[live, "symbol"].values
    out = {s: {} for s in syms}
    fits = 0
    for hname, h in HORIZONS.items():
        ex = panel[f"ex_{hname}"].values
        train_all = ~np.isnan(ex) & (dates <= today - np.timedelta64(CAL_GAP[h], "D"))
        y = (ex > 0).astype(np.int8)
        group = [a for a in analysts if a.horizon == hname]
        # without a weekly grade yet, every analyst counts equally (flagged as unverified)
        w = np.array([weights.get(a.key, 0.0) if weights else 1.0 for a in group])
        votes = np.full((n_live, len(group)), np.nan, dtype=np.float32)
        for k, a in enumerate(group):
            if w[k] <= 0:
                continue
            tr = train_all & segs[a.segment]
            te = live & segs[a.segment]
            if not te.any():
                continue
            m = _fit(a, views[a.speciality][tr], y[tr], rng)
            if m is None:
                continue
            fits += 1
            p = np.full(len(panel), np.nan, dtype=np.float32)
            p[te] = _predict(m, views[a.speciality][te])
            votes[:, k] = p[live]
        log(f"Analysts {hname}: {int((w > 0).sum())} voting, {fits} fits so far")
        verified = bool((tests.get(hname) or {}).get("verified")) and bool(weights)
        for i, s in enumerate(syms):
            v = votes[i]
            ok = ~np.isnan(v)
            if not ok.any():
                continue
            wi = w * ok
            prob = float(np.nansum(np.nan_to_num(v) * wi) / max(wi.sum(), 1e-12))
            bull = float((wi * (np.nan_to_num(v) > 0.5)).sum() / max(wi.sum(), 1e-12))
            top_idx = np.argsort(-wi)[:3]
            verdict = ("buy" if prob >= BUY_P else "sell" if prob <= SELL_P else "hold") if verified else "hold"
            out[s][hname] = {
                "chance_beat_market_pct": round(prob * 100, 1), "verdict": verdict, "verified": verified,
                "analysts_voting": int(ok.sum()), "bullish_weight_pct": round(bull * 100, 1),
                "bullish_analysts": int((ok & (v > 0.5)).sum()),
                "top_analysts": [{"name": by_key[group[j].key].name, "chance_pct": round(float(v[j]) * 100, 1)}
                                 for j in top_idx if ok[j] and wi[j] > 0],
            }
    preds = [{"symbol": s, "as_of": str(pd.Timestamp(today).date()), "rank": 0,
              "probability": (out[s].get("1y") or out[s].get("3m") or {}).get("chance_beat_market_pct", 50) / 100,
              "consensus": out[s]} for s in syms if out[s]]
    preds.sort(key=lambda p: -p["probability"])
    for i, p in enumerate(preds, 1):
        p["rank"] = i
    return clean_json({
        "model_key": "analyst_consensus", "strategy": "analysts", "horizon_days": 250,
        "description": "Weighted consensus of the analyst models that proved themselves on unseen months.",
        "model_type": "analyst_consensus", "trained_at": t0.isoformat(),
        "data_end": str(pd.Timestamp(today).date()),
        "edge_verified": any((tests.get(h) or {}).get("verified") for h in HORIZONS) and bool(weights),
        "metrics": {"analysts": len(analysts), "fits": fits, "graded": bool(weights),
                    "consensus_tests": tests, "skilled_by_horizon": gm.get("skilled_by_horizon"),
                    "graded_at": (graded or {}).get("trained_at"),
                    "minutes": round((datetime.now(timezone.utc) - t0).total_seconds() / 60, 1)},
        "backtest": None, "folds": None, "predictions": preds,
    })
