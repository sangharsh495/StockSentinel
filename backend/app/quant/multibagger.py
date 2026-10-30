"""
Multibagger Radar: which liquid NSE stocks have the best odds of doubling.

Pipeline (each piece tested on data it never saw):

1. Panel: every month-end since 2021, every liquid stock, with point-in-time
   features (price trend, Kalman trend, trading flow, risk, fundamentals).
2. Targets: doubles within 1 year (primary), top-2% return in 1 year,
   triples within 2 years, +50% within 6 months.
3. Model zoo: 6 model families x 4 targets x 7 feature views = 168 model
   configurations; each trained on several bootstrap samples of past
   months (bagging), ~1000 fitted models per training round.
4. Walk-forward test: models are refitted every few months using only rows
   whose outcome was already known on that day (1-year gap), then scored
   on the following months.
5. Honest selection: the stack used in month m is built from the
   configurations that did best on months whose outcomes were known
   before m. Configurations are also tested one by one with Newey-West
   t-stats and a Benjamini-Hochberg false-discovery filter, because with
   168 tries some will look good by luck.
6. Live: today's ranking, an evidence ledger per stock (what pushes its odds
   up or down), a stage (Discovery / Confirmation / Momentum / Exit risk) and
   red flags. Every weekly list is logged and scored 6 and 12 months later.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from app.quant.fundamentals import FUND_FEATURES, latest_quarter_growth, point_in_time
from app.quant.state_space import kalman_trend, market_breadth, market_regime

logger = logging.getLogger(__name__)

MIN_TURNOVER_LACS = 50          # Rs 50 lakh median daily turnover: tradable
MIN_PRICE = 10
PRIMARY = "double_1y"
TARGETS = {                     # name: (trading days, rule)
    "double_1y": (250, "x2"),
    "top2_1y": (250, "top2"),
    "triple_2y": (500, "x3"),
    "x15_6m": (125, "x1.5"),
}
CAL_GAP = {250: 380, 500: 745, 125: 195}    # calendar days before a label is surely known

PRICE_FEATURES = ["mom12_1", "mom6", "mom1", "near_52w_high", "above_200dma", "max_ret_20d"]
TREND_FEATURES = ["kalman_velocity", "kalman_snr", "kalman_accel"]
FLOW_FEATURES = ["turnover_growth", "deliv_change", "deliv_level", "size_liq"]
RISK_FEATURES = ["vol60", "locked_days", "ret_1y"]
GROWTH = ["rev_growth", "rev_accel", "profit_growth", "margin_change", "turned_profitable"]
QUALITY_VALUE = ["op_margin", "roe", "debt_to_equity", "cash_conversion", "dilution", "fcf_positive",
                 "log_mcap", "earnings_yield", "sales_yield"]
ALL_FEATURES = PRICE_FEATURES + TREND_FEATURES + FLOW_FEATURES + RISK_FEATURES + GROWTH + QUALITY_VALUE
VIEWS = {
    "momentum": PRICE_FEATURES,
    "kalman_trend": TREND_FEATURES + ["near_52w_high", "vol60"],
    "flow": FLOW_FEATURES + ["mom1"],
    "risk_size": RISK_FEATURES + ["size_liq", "max_ret_20d", "log_mcap"],
    "growth": GROWTH + ["mom6", "log_mcap"],
    "quality_value": QUALITY_VALUE,
    "everything": ALL_FEATURES,
}
LABELS = {
    "mom12_1": "12-month price momentum", "mom6": "6-month price momentum", "mom1": "last month's move",
    "near_52w_high": "closeness to 52-week high", "above_200dma": "price vs 200-day average",
    "max_ret_20d": "biggest one-day jump (20 days)", "kalman_velocity": "Kalman trend speed",
    "kalman_snr": "Kalman trend certainty", "kalman_accel": "trend acceleration",
    "turnover_growth": "rising trading activity", "deliv_change": "rising delivery %",
    "deliv_level": "delivery % level", "size_liq": "trading liquidity", "vol60": "volatility",
    "locked_days": "circuit-locked days", "ret_1y": "1-year return", "rev_growth": "revenue growth",
    "rev_accel": "revenue growth speeding up", "profit_growth": "profit growth",
    "margin_change": "margin expansion", "turned_profitable": "turned profitable",
    "op_margin": "operating margin", "roe": "return on equity", "debt_to_equity": "debt / equity",
    "cash_conversion": "cash conversion (OCF / profit)", "dilution": "share dilution",
    "fcf_positive": "positive free cash flow", "log_mcap": "company size", "earnings_yield": "earnings yield (1/PE)",
    "sales_yield": "sales yield (1/PS)",
}


# --------------------------------------------------------------------- panel

def daily_features(W: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    C, T, D = W["Close"], W["TurnoverLacs"], W["DelivPct"]
    r = np.log(C).diff()
    kal = kalman_trend(C)
    locked = ((W["High"] == W["Low"]) & (r.abs() > 0.015)).astype(float).where(C.notna())
    return {
        "mom12_1": C.shift(21) / C.shift(250) - 1,
        "mom6": C / C.shift(125) - 1,
        "mom1": C / C.shift(21) - 1,
        "near_52w_high": C / C.rolling(250, min_periods=200).max(),
        "above_200dma": C / C.rolling(200, min_periods=150).mean(),
        "max_ret_20d": r.rolling(20).max(),
        "kalman_velocity": kal["velocity"], "kalman_snr": kal["snr"], "kalman_accel": kal["accel"],
        "turnover_growth": T.rolling(60).mean() / T.rolling(250, min_periods=200).mean(),
        "deliv_change": D.rolling(60).mean() - D.rolling(250, min_periods=200).mean(),
        "deliv_level": D.rolling(60, min_periods=40).mean(),
        "size_liq": np.log(T.rolling(60, min_periods=40).median().clip(lower=1)),
        "vol60": r.rolling(60).std(),
        "locked_days": locked.rolling(60, min_periods=40).mean(),
        "ret_1y": C / C.shift(250) - 1,
    }


def month_ends(index: pd.DatetimeIndex, start: str = "2021-01-01") -> List[pd.Timestamp]:
    s = pd.Series(index, index=index)
    ends = s.groupby(index.to_period("M")).last()
    return [d for d in ends if d >= pd.Timestamp(start)]


def build_panel(W: Dict[str, pd.DataFrame], fund: Optional[pd.DataFrame], dates: List[pd.Timestamp],
                daily: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
    """Long panel: one row per (date, symbol) for liquid stocks, raw features + targets."""
    C = W["Close"]
    daily = daily or daily_features(W)
    idx = pd.DatetimeIndex(dates)
    pit = point_in_time(fund, idx, C) if fund is not None and len(fund) else {}
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median()
    rows = []
    pos = C.index.get_indexer(idx)
    Cf = C.ffill(limit=5)
    for d, i in zip(idx, pos):
        p0 = C.iloc[i]
        elig = (liq.iloc[i] >= MIN_TURNOVER_LACS) & (p0 >= MIN_PRICE)
        syms = elig[elig].index
        if len(syms) < 50:
            continue
        df = pd.DataFrame(index=syms)
        for k, v in daily.items():
            df[k] = v.iloc[i][syms].values
        for k in FUND_FEATURES:
            df[k] = pit[k].loc[d, syms].values if k in pit else np.nan
        for name, (h, rule) in TARGETS.items():
            if i + h < len(C):
                p1 = Cf.iloc[i + h][syms]
                ret = (p1 / p0[syms]).values
                if rule == "top2":
                    rk = pd.Series(ret).rank(pct=True).values
                    y = (rk >= 0.98).astype(float)
                else:
                    y = (ret >= float(rule[1:])).astype(float)
                y[np.isnan(ret)] = np.nan
                df[name] = y
                if name == PRIMARY:
                    df["fwd_ret_1y"] = ret - 1
            else:
                df[name] = np.nan
        df["date"] = d
        rows.append(df.rename_axis("symbol").reset_index())
    panel = pd.concat(rows, ignore_index=True)
    for c in ALL_FEATURES:
        panel[c] = panel[c].astype("float32")
    return panel


def rank_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank of every feature within its own date: removes market-wide level shifts."""
    return panel.groupby("date")[ALL_FEATURES].rank(pct=True).astype("float32")


# --------------------------------------------------------------------- zoo

class RankSum:
    """A transparent factor model: add up the ranks of features, each signed by its past correlation with the target."""

    def fit(self, X, y):
        Xc = X - X.mean(0)
        yc = y - y.mean()
        corr = (Xc * yc[:, None]).sum(0) / (np.sqrt((Xc ** 2).sum(0) * (yc ** 2).sum()) + 1e-12)
        self.w = np.where(np.abs(corr) > 0.005, np.sign(corr), 0.0)
        return self

    def predict_proba(self, X):
        s = X @ self.w / max(1, np.abs(self.w).sum())
        return np.c_[1 - s, s]


def _families(seed: int) -> Dict[str, Callable]:
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    return {
        "boost_shallow": lambda: HistGradientBoostingClassifier(max_depth=2, max_iter=80, learning_rate=0.08,
                                                                min_samples_leaf=300, random_state=seed),
        "boost_deep": lambda: HistGradientBoostingClassifier(max_depth=4, max_iter=100, learning_rate=0.05,
                                                             min_samples_leaf=150, l2_regularization=1.0,
                                                             random_state=seed),
        "logistic": lambda: LogisticRegression(C=0.3, max_iter=300),
        "extra_trees": lambda: ExtraTreesClassifier(n_estimators=40, max_depth=6, min_samples_leaf=100,
                                                    n_jobs=-1, random_state=seed),
        "random_forest": lambda: RandomForestClassifier(n_estimators=40, max_depth=6, min_samples_leaf=100,
                                                        max_features=0.5, n_jobs=-1, random_state=seed),
        "rank_sum": lambda: RankSum(),
    }


FAMILIES = list(_families(0))

# Classic single-factor rankers with their textbook direction, fixed in
# advance (no fitting): they compete with the learned models under the same
# honest selection, so the zoo can only beat them, never hide them.
FACTORS = {"mom12_1": 1, "mom6": 1, "near_52w_high": 1, "kalman_velocity": 1, "vol60": -1,
           "rev_growth": 1, "profit_growth": 1, "roe": 1, "earnings_yield": 1, "sales_yield": 1,
           "deliv_change": 1, "turnover_growth": 1}


class FactorRank:
    def __init__(self, sign: int):
        self.sign = sign

    def predict_proba(self, X):
        s = (X[:, 0] - 0.5) * self.sign + 0.5
        return np.c_[1 - s, s]
# Missing values are filled with the neutral rank (0.5) for every family, never
# learned as their own branch: delisted companies have no fundamentals today,
# so "missing" would secretly mean "this company later died" (look-ahead).
NAN_OK: set = set()


@dataclass(frozen=True)
class Config:
    family: str
    target: str
    view: str

    @property
    def key(self) -> str:
        return f"{self.family}|{self.target}|{self.view}"


def all_configs(targets=None, views=None, families=None, factors: bool = True) -> List[Config]:
    out = [Config(f, t, v) for f in (families or FAMILIES) for t in (targets or TARGETS) for v in (views or VIEWS)]
    if factors:
        out += [Config("factor", PRIMARY, f) for f in FACTORS]
    return out


def fit_config(cfg: Config, R: pd.DataFrame, panel: pd.DataFrame, train_mask: np.ndarray, n_bags: int,
               rng: np.random.Generator):
    """Bagged fit on bootstrap samples of training dates. Returns a list of (model, columns) or None."""
    if cfg.family == "factor":
        return [FactorRank(FACTORS[cfg.view])], [cfg.view]
    y = panel[cfg.target].values
    m = train_mask & ~np.isnan(y)
    dates = panel["date"].values[m]
    uniq = np.unique(dates)
    if len(uniq) < 6 or np.nansum(y[m]) < 30:
        return None
    # keep only features that were actually observed in this training window
    # (fundamentals start later than prices)
    cols = [c for c in VIEWS[cfg.view] if R.loc[m, c].notna().mean() >= 0.05]
    if not cols:
        return None
    X = R.loc[m, cols].values
    if cfg.family not in NAN_OK:
        X = np.nan_to_num(X, nan=0.5)
    ym = y[m]
    fitted = []
    for b in range(n_bags):
        pick = rng.choice(uniq, size=max(4, int(len(uniq) * 0.6)), replace=False)
        sel = np.isin(dates, pick)
        if ym[sel].sum() < 10 or ym[sel].sum() == sel.sum():
            continue
        model = _families(int(rng.integers(1e9)))[cfg.family]()
        fitted.append(model.fit(X[sel], ym[sel]))
    return (fitted, cols) if fitted else None


def predict_config(fit, cfg: Config, R: pd.DataFrame, mask: np.ndarray) -> np.ndarray:
    models, cols = fit
    X = R.loc[mask, cols].values
    if cfg.family not in NAN_OK:
        X = np.nan_to_num(X, nan=0.5)
    return np.mean([m.predict_proba(X)[:, 1] for m in models], axis=0)


# --------------------------------------------------------------------- statistics

def newey_west_t(x: np.ndarray, lags: int) -> float:
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 4:
        return float("nan")
    d = x - x.mean()
    s = (d @ d) / n
    for L in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - L / (lags + 1)) * (d[L:] @ d[:-L]) / n
    return float(x.mean() / math.sqrt(max(s, 1e-18) / n))


def bh_fdr(pvals: Dict[str, float], q: float = 0.10) -> List[str]:
    """Benjamini-Hochberg: keys whose p-value survives a false-discovery rate of q."""
    items = sorted((p, k) for k, p in pvals.items() if not math.isnan(p))
    m = len(items)
    passed = 0
    for i, (p, _) in enumerate(items, 1):
        if p <= q * i / m:
            passed = i
    return [k for _, k in items[:passed]]


def _norm_sf(t: float) -> float:
    return 0.5 * math.erfc(t / math.sqrt(2))


# --------------------------------------------------------------------- walk-forward

def walk_forward_zoo(panel: pd.DataFrame, R: pd.DataFrame, configs: List[Config], refit_months: int = 6,
                     n_bags: int = 6, first_refit: str = "2022-07-01", seed: int = 0,
                     log: Callable = logger.info):
    """
    Returns (scores, refits): scores is a DataFrame indexed like the test rows of
    `panel` with one column per config key (NaN where a config had no model).
    """
    rng = np.random.default_rng(seed)
    dates = np.array(sorted(panel["date"].unique()))
    pdates = panel["date"].values
    labelled = dates[~panel.groupby("date")[PRIMARY].apply(lambda s: s.isna().all()).reindex(dates).values]
    test_dates = [d for d in labelled if d >= np.datetime64(first_refit)]
    refits = list(pd.date_range(first_refit, pd.Timestamp(test_dates[-1]) + pd.Timedelta(days=1),
                                freq=f"{refit_months}MS")) if test_dates else []
    test_mask = np.isin(pdates, test_dates)
    scores = pd.DataFrame(np.nan, index=panel.index[test_mask], columns=[c.key for c in configs], dtype=float)
    n_fit = 0
    for j, R0 in enumerate(refits):
        R1 = refits[j + 1] if j + 1 < len(refits) else pd.Timestamp.max
        block = test_mask & (pdates >= np.datetime64(R0)) & (pdates < np.datetime64(R1))
        if not block.any():
            continue
        for cfg in configs:
            gap = pd.Timedelta(days=CAL_GAP[TARGETS[cfg.target][0]])
            train = pdates <= np.datetime64(R0 - gap)
            fit = fit_config(cfg, R, panel, train, n_bags, rng)
            if fit is None:
                continue
            if cfg.family != "factor":
                n_fit += len(fit[0])
            scores.loc[panel.index[block], cfg.key] = predict_config(fit, cfg, R, block)
        log(f"Zoo refit {R0.date()}: {n_fit} models fitted so far")
    return scores, n_fit


def config_monthly(panel: pd.DataFrame, scores: pd.DataFrame, top_frac: float = 0.1) -> pd.DataFrame:
    """Excess primary-target hit rate of each config's top decile, per test month."""
    test = panel.loc[scores.index, ["date", PRIMARY]]
    out = {}
    for d, g in test.groupby("date"):
        y = g[PRIMARY].values
        base = np.nanmean(y)
        n_top = max(1, int(len(g) * top_frac))
        s = scores.loc[g.index]
        row = {}
        for k in s.columns:
            v = s[k].values
            if np.isnan(v).all():
                continue
            top = np.argsort(-np.nan_to_num(v, nan=-1))[:n_top]
            row[k] = np.nanmean(y[top]) - base
        out[d] = row
    return pd.DataFrame(out).T.sort_index()


def _pct_rank(v: np.ndarray) -> np.ndarray:
    return pd.Series(v).rank(pct=True).values


def honest_stack(panel: pd.DataFrame, scores: pd.DataFrame, monthly: pd.DataFrame, top_k: int = 10,
                 min_months: int = 6) -> pd.Series:
    """
    Stack score per test row. For month m the stack averages the ranks of the
    top_k configs judged on months whose outcomes were known before m (1-year
    gap). Until enough months are known it averages every config (zoo average).
    """
    test = panel.loc[scores.index, ["date"]]
    out = pd.Series(np.nan, index=scores.index)
    chosen_log = {}
    for d, g in test.groupby("date"):
        known = monthly.loc[monthly.index <= d - pd.Timedelta(days=CAL_GAP[250])]
        s = scores.loc[g.index]
        if len(known) >= min_months:
            perf = known.mean().dropna()
            keys = [k for k in perf.sort_values(ascending=False).index[:top_k] if s[k].notna().any()]
        else:
            keys = [k for k in s.columns if s[k].notna().any()]
        chosen_log[d] = keys
        ranks = np.column_stack([_pct_rank(s[k].values) for k in keys])
        out.loc[g.index] = np.nanmean(ranks, axis=1)
    out.attrs["chosen"] = chosen_log
    return out


def evaluate_stack(panel: pd.DataFrame, score: pd.Series, name: str) -> Dict:
    test = panel.loc[score.index].assign(score=score.values)
    rows = []
    for d, g in test.groupby("date"):
        g = g.dropna(subset=["score"])
        if len(g) < 50:
            continue
        base = g[PRIMARY].mean()
        top10 = g.nlargest(max(1, len(g) // 10), "score")
        top20 = g.nlargest(20, "score")
        rows.append({"date": d, "base": base, "top_decile": top10[PRIMARY].mean(), "top20": top20[PRIMARY].mean(),
                     "top20_median_ret": top20["fwd_ret_1y"].median(),
                     "all_median_ret": g["fwd_ret_1y"].median()})
    r = pd.DataFrame(rows)
    if r.empty:
        return {"name": name, "months": 0}
    ex = (r["top_decile"] - r["base"]).values
    t = newey_west_t(ex, lags=12)
    return {
        "name": name, "months": int(len(r)),
        "avg_base_rate_pct": round(r["base"].mean() * 100, 2),
        "top_decile_hit_pct": round(r["top_decile"].mean() * 100, 2),
        "top20_hit_pct": round(r["top20"].mean() * 100, 2),
        "lift_top_decile": round(r["top_decile"].mean() / max(r["base"].mean(), 1e-9), 2),
        "months_top_decile_beat_base_pct": round(float((ex > 0).mean() * 100), 1),
        "newey_west_t": round(t, 2) if not math.isnan(t) else None,
        "top20_median_1y_return_pct": round(r["top20_median_ret"].mean() * 100, 1),
        "all_median_1y_return_pct": round(r["all_median_ret"].mean() * 100, 1),
        "by_month": [{"date": str(x.date.date()), "base_pct": round(x.base * 100, 1),
                      "top_decile_pct": round(x.top_decile * 100, 1), "top20_pct": round(x.top20 * 100, 1)}
                     for x in r.itertuples()],
    }


def lift_table(panel: pd.DataFrame, score: pd.Series) -> List[Dict]:
    """Doubling rate by stack-score bucket (relative to that month's base rate), from the walk-forward."""
    test = panel.loc[score.index].assign(score=score.values).dropna(subset=["score"])
    test["pct"] = test.groupby("date")["score"].rank(pct=True)
    test["base"] = test.groupby("date")[PRIMARY].transform("mean")
    edges = [0, 0.5, 0.8, 0.9, 0.95, 0.98, 1.0001]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = test[(test["pct"] > lo) & (test["pct"] <= hi)]
        if len(g):
            out.append({"from_pct": round(lo * 100), "to_pct": min(100, round(hi * 100)), "rows": int(len(g)),
                        "doubling_rate_pct": round(g[PRIMARY].mean() * 100, 2),
                        "lift": round(g[PRIMARY].mean() / max(g["base"].mean(), 1e-9), 2)})
    return out


# --------------------------------------------------------------------- stages, flags, evidence

def stage_of(row) -> str:
    if row.get("red_flag_count", 0) >= 2 or (row.get("ret_1y", 0) > 3 and row.get("kalman_snr", 0) < 0):
        return "exit_risk"
    snr, hi = row.get("kalman_snr", np.nan), row.get("near_52w_high", np.nan)
    if snr >= 2 and hi >= 0.9:
        return "momentum"
    if snr >= 0.5:
        return "confirmation"
    return "discovery"


FLAG_RULES = {
    "circuit_locked_often": ("locked_days", lambda v: v >= 0.15, "price often locked at circuit limits (thin, operator-prone trading)"),
    "heavy_dilution": ("dilution", lambda v: v > 0.10, "share count up more than 10% in a year"),
    "high_debt": ("debt_to_equity", lambda v: v > 2, "debt more than 2x equity"),
    "cash_burn": ("cash_conversion", lambda v: v < 0, "operating cash flow negative"),
    "already_5x": ("ret_1y", lambda v: v > 4, "already up 5x in a year"),
}


def red_flags(row) -> List[str]:
    out = []
    for name, (col, rule, _) in FLAG_RULES.items():
        v = row.get(col, np.nan)
        if v is not None and not (isinstance(v, float) and math.isnan(v)) and rule(v):
            out.append(name)
    return out


def red_flag_study(panel: pd.DataFrame) -> Dict:
    """Does each flag really raise the odds of a crash (1-year return of -40% or worse)? Uses every labelled row."""
    lab = panel.dropna(subset=["fwd_ret_1y"])
    crash = (lab["fwd_ret_1y"] <= -0.4).astype(float)
    base_c = lab.groupby("date").apply(lambda g: (g["fwd_ret_1y"] <= -0.4).mean())
    out = {"base_crash_rate_pct": round(float(crash.mean() * 100), 2)}
    for name, (col, rule, desc) in FLAG_RULES.items():
        v = lab[col]
        m = v.notna() & v.apply(lambda x: bool(rule(x)) if pd.notna(x) else False)
        if m.sum() < 30:
            out[name] = {"meaning": desc, "rows": int(m.sum()), "verified": False}
            continue
        rate = crash[m].mean()
        exp = base_c.reindex(lab.loc[m, "date"]).mean()
        dbl = lab.loc[m, PRIMARY].mean()
        out[name] = {"meaning": desc, "rows": int(m.sum()), "crash_rate_pct": round(rate * 100, 1),
                     "crash_lift": round(rate / max(exp, 1e-9), 2), "doubling_rate_pct": round(dbl * 100, 1),
                     "verified": bool(rate / max(exp, 1e-9) > 1.2 and m.sum() >= 100)}
    return out


def fit_explainer(panel: pd.DataFrame, R: pd.DataFrame):
    from sklearn.linear_model import LogisticRegression

    m = panel[PRIMARY].notna().values
    X = np.nan_to_num(R.loc[m, ALL_FEATURES].values - 0.5, nan=0.0)
    model = LogisticRegression(C=0.3, max_iter=500).fit(X, panel.loc[m, PRIMARY].values)
    return model.coef_[0]


def evidence(coef: np.ndarray, ranks: pd.Series, raw: pd.Series, n_pos: int = 4, n_neg: int = 2) -> List[Dict]:
    """Per-stock evidence ledger: each feature's push on the odds, as a multiplier."""
    c = coef * np.nan_to_num(ranks[ALL_FEATURES].values.astype(float) - 0.5, nan=0.0)
    order = np.argsort(c)
    picks = [i for i in order[::-1][:n_pos] if c[i] > 0.01] + [i for i in order[:n_neg] if c[i] < -0.01]
    out = []
    for i in picks:
        f = ALL_FEATURES[i]
        v = raw.get(f)
        out.append({"feature": f, "label": LABELS.get(f, f), "odds_multiplier": round(float(np.exp(c[i])), 2),
                    "value": None if v is None or pd.isna(v) else round(float(v), 4),
                    "percentile": None if pd.isna(ranks[f]) else int(round(float(ranks[f]) * 100))})
    return out


def stage_track_record(panel: pd.DataFrame, score: pd.Series) -> Dict:
    test = panel.loc[score.index].assign(score=score.values).dropna(subset=["score"])
    test["pct"] = test.groupby("date")["score"].rank(pct=True)
    top = test[test["pct"] >= 0.9].copy()
    top["red_flag_count"] = top.apply(lambda r: len(red_flags(r)), axis=1)
    top["stage"] = top.apply(stage_of, axis=1)
    out = {}
    for s, g in top.groupby("stage"):
        out[s] = {"picks": int(len(g)), "doubling_rate_pct": round(g[PRIMARY].mean() * 100, 1),
                  "median_1y_return_pct": round(g["fwd_ret_1y"].median() * 100, 1)}
    return out


def regime_summary(W, panel: pd.DataFrame) -> Dict:
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median() >= MIN_TURNOVER_LACS
    reg = market_regime(market_breadth(W["Close"], liq))
    probs = reg["probs"]
    now = probs.iloc[-1]
    by_month = panel.dropna(subset=[PRIMARY]).groupby("date")[PRIMARY].mean()
    state_at = probs.reindex(by_month.index, method="ffill").dropna().idxmax(axis=1)
    rates = by_month.reindex(state_at.index).groupby(state_at).agg(["mean", "count"])
    return {
        "current": now.idxmax(), "probabilities": {k: round(float(v), 3) for k, v in now.items()},
        "as_of": str(probs.index[-1].date()),
        "doubling_rate_by_regime_at_entry": {k: {"avg_pct": round(float(v["mean"]) * 100, 1), "months": int(v["count"])}
                                             for k, v in rates.iterrows()},
        "typical_doubling_rate_pct": round(float(by_month.median()) * 100, 1),
        "range_doubling_rate_pct": [round(float(by_month.quantile(0.1)) * 100, 1),
                                    round(float(by_month.quantile(0.9)) * 100, 1)],
        "note": "Regime model is fitted on all history (descriptive); the market has had only about one full cycle since 2020.",
        "weekly_breadth_latest": {k: round(float(v), 3) for k, v in reg["weekly"].iloc[-1].items()},
    }


# --------------------------------------------------------------------- run

def run_multibagger(W: Dict[str, pd.DataFrame], fund: Optional[pd.DataFrame], n_bags: int = 6,
                    refit_months: int = 6, top_n: int = 25, configs: Optional[List[Config]] = None) -> Dict:
    t0 = datetime.now(timezone.utc)
    configs = configs or all_configs()
    daily = daily_features(W)
    C = W["Close"]
    dates = month_ends(C.index)
    if dates[-1] != C.index[-1]:
        dates.append(C.index[-1])          # today (unlabelled) for live scoring
    panel = build_panel(W, fund, dates, daily)
    R = rank_features(panel)
    logger.info(f"Multibagger panel: {len(panel)} rows, {panel['date'].nunique()} months")

    scores, n_fit = walk_forward_zoo(panel, R, configs, refit_months=refit_months, n_bags=n_bags)
    monthly = config_monthly(panel, scores)

    # each config on its own, with multiple-testing control
    lags = 12
    pvals, leaderboard = {}, []
    for k in monthly.columns:
        x = monthly[k].dropna().values
        t = newey_west_t(x, lags)
        pvals[k] = _norm_sf(t) if not math.isnan(t) else float("nan")
        leaderboard.append({"config": k, "months": int(len(x)), "avg_excess_hit_pct": round(float(np.mean(x)) * 100, 2) if len(x) else None,
                            "t": None if math.isnan(t) else round(t, 2)})
    survivors = bh_fdr(pvals, 0.10)
    leaderboard.sort(key=lambda r: -(r["avg_excess_hit_pct"] or -99))

    stack = honest_stack(panel, scores, monthly)
    zoo_avg = pd.Series(np.nanmean(np.column_stack([
        panel.loc[scores.index].assign(v=scores[k].values).groupby("date")["v"].rank(pct=True).values
        for k in scores.columns if scores[k].notna().any()]), axis=1), index=scores.index)
    price_only = [c for c in configs if c.family != "factor" and c.view in ("momentum", "kalman_trend", "flow", "risk_size")]
    po = pd.Series(np.nanmean(np.column_stack([
        panel.loc[scores.index].assign(v=scores[c.key].values).groupby("date")["v"].rank(pct=True).values
        for c in price_only if scores[c.key].notna().any()]), axis=1), index=scores.index)
    ev_stack = evaluate_stack(panel, stack, "honest_top10_stack")
    ev_avg = evaluate_stack(panel, zoo_avg, "zoo_average")
    ev_price = evaluate_stack(panel, po, "price_and_flow_models_only")
    mom = pd.Series(panel.loc[scores.index, "mom12_1"].values, index=scores.index)
    ev_mom = evaluate_stack(panel, mom, "momentum_12m_alone")
    lifts = lift_table(panel, stack)
    stages = stage_track_record(panel, stack)
    flags = red_flag_study(panel)

    # ---- live: refit the chosen configs on everything known today
    today = panel["date"].max()
    known = monthly.loc[monthly.index <= today - pd.Timedelta(days=CAL_GAP[250])]
    perf = known.mean().dropna().sort_values(ascending=False)
    chosen_keys = list(perf.index[:10]) if len(known) >= 6 else [c.key for c in configs]
    by_key = {c.key: c for c in configs}
    rng = np.random.default_rng(1)
    live_mask = (panel["date"] == today).values
    live_ranks = []
    for k in chosen_keys:
        cfg = by_key[k]
        train = (panel["date"] <= today - pd.Timedelta(days=CAL_GAP[TARGETS[cfg.target][0]])).values
        fit = fit_config(cfg, R, panel, train, n_bags, rng)
        if fit is None:
            continue
        if cfg.family != "factor":
            n_fit += len(fit[0])
        live_ranks.append(_pct_rank(predict_config(fit, cfg, R, live_mask)))
    live = panel.loc[live_mask].copy()
    live["score"] = np.nanmean(np.column_stack(live_ranks), axis=1) if live_ranks else np.nan
    live["pct"] = live["score"].rank(pct=True)
    coef = fit_explainer(panel, R)
    regime = regime_summary(W, panel)
    quarters = latest_quarter_growth(fund) if fund is not None and len(fund) else {}

    def lift_for(p):
        for b in lifts:
            if b["from_pct"] / 100 < p <= b["to_pct"] / 100 + 1e-9:
                return b["lift"]
        return None

    live["red_flags"] = live.apply(red_flags, axis=1)
    live["red_flag_count"] = live["red_flags"].apply(len)
    live["stage"] = live.apply(stage_of, axis=1)
    verified_flags = {k for k, v in flags.items() if isinstance(v, dict) and v.get("verified")}
    cand = live[live["red_flags"].apply(lambda f: not (set(f) & verified_flags))]
    picks = []
    typical = regime["typical_doubling_rate_pct"] / 100
    lo, hi = (x / 100 for x in regime["range_doubling_rate_pct"])
    for rank, (_, r) in enumerate(cand.nlargest(top_n, "score").iterrows(), 1):
        lift = lift_for(r["pct"])
        row_ranks = R.loc[r.name]
        picks.append({
            "symbol": r["symbol"], "as_of": str(today.date()), "rank": rank,
            "probability": round(min(0.95, typical * (lift or 1)), 4), "stage": r["stage"],
            "score_percentile": round(float(r["pct"]) * 100, 1),
            "odds_vs_average_stock": lift,
            "chance_double_1y_pct": {"typical_year": round(min(0.95, typical * (lift or 1)) * 100, 1),
                                     "weak_year": round(min(0.95, lo * (lift or 1)) * 100, 1),
                                     "strong_year": round(min(0.95, hi * (lift or 1)) * 100, 1)},
            "evidence": evidence(coef, row_ranks, r),
            "red_flags": r["red_flags"],
            "kalman": {"trend_per_year_pct": round(float(np.expm1(r["kalman_velocity"])) * 100, 1)
                       if pd.notna(r["kalman_velocity"]) else None,
                       "certainty_snr": round(float(r["kalman_snr"]), 2) if pd.notna(r["kalman_snr"]) else None},
            "return_1y_pct": round(float(r["ret_1y"]) * 100, 1) if pd.notna(r["ret_1y"]) else None,
            "latest_quarter": quarters.get(r["symbol"]),
            "has_fundamentals": bool(pd.notna(r["rev_growth"])),
        })

    edge = ev_stack.get("months", 0) >= 12 and (ev_stack.get("newey_west_t") or 0) > 2 and \
        (ev_stack.get("lift_top_decile") or 0) > 1.2
    n_cfg_models = len([k for k in scores.columns if scores[k].notna().any()])
    return clean_json({
        "model_key": "multibagger_radar", "strategy": "multibagger", "horizon_days": 250,
        "description": "Stocks with the best tested odds of doubling within a year, from a model zoo plus classic factors.",
        "model_type": "model_zoo_stack", "trained_at": t0.isoformat(), "data_end": str(today.date()),
        "edge_verified": bool(edge),
        "metrics": {
            "model_configurations": len(configs), "configurations_with_models": n_cfg_models,
            "fitted_models": int(n_fit), "bags_per_configuration": n_bags,
            "families": FAMILIES + ["factor"], "classic_factors": list(FACTORS), "targets": list(TARGETS), "views": list(VIEWS),
            "panel_rows": int(len(panel)), "panel_months": int(panel["date"].nunique()),
            "stocks_with_fundamentals_today": int(live["rev_growth"].notna().sum()),
            "honest_stack": ev_stack, "zoo_average": ev_avg, "price_and_flow_only": ev_price,
            "momentum_12m_alone": ev_mom,
            "beats_momentum_baseline": bool((ev_stack.get("top_decile_hit_pct") or 0) > (ev_mom.get("top_decile_hit_pct") or 0)),
            "fdr_survivors": survivors, "fdr_q": 0.10, "leaderboard_top": leaderboard[:15],
            "lift_by_score_bucket": lifts, "stage_track_record": stages, "red_flag_study": flags,
            "regime": regime, "live_stack_configs": chosen_keys,
            "minutes": round((datetime.now(timezone.utc) - t0).total_seconds() / 60, 1),
        },
        "backtest": None, "folds": None, "predictions": picks,
    })


def clean_json(obj):
    """numpy scalars -> plain Python, NaN -> None, so results store cleanly as JSON."""
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def score_ledger(W: Dict[str, pd.DataFrame], rows: List[dict]) -> Dict:
    """Score logged radar picks: 6-month and 1-year results vs the median liquid stock."""
    C = W["Close"].ffill(limit=5)
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median() >= MIN_TURNOVER_LACS
    out = {"6m": [], "1y": []}
    for r in rows:
        d = pd.Timestamp(r["date"])
        i = C.index.searchsorted(d, side="right") - 1
        if i < 0 or r["symbol"] not in C.columns:
            continue
        for name, h in (("6m", 125), ("1y", 250)):
            if i + h >= len(C):
                continue
            ret = C.iloc[i + h] / C.iloc[i] - 1
            med = ret[liq.iloc[i]].median()
            rr = ret.get(r["symbol"])
            if pd.notna(rr):
                out[name].append((rr, med, r.get("stage")))
    res = {"status": "ok" if out["6m"] else "waiting", "logged_picks": len(rows)}
    for name, xs in out.items():
        if xs:
            a = np.array([(x[0], x[1]) for x in xs])
            res[name] = {"scored": len(xs), "median_return_pct": round(float(np.median(a[:, 0])) * 100, 1),
                         "beat_median_stock_pct": round(float((a[:, 0] > a[:, 1]).mean()) * 100, 1),
                         "doubled_pct": round(float((a[:, 0] >= 1).mean()) * 100, 1)}
    return res
