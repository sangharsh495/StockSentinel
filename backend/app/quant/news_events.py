"""
News event study — what actually happened to a stock after a news story.

For every (news, stock) pair the app tagged, we record the stock's move
1, 5 and 20 trading days later MINUS the market's move over the same days
("abnormal return"). This turns each news tag into a measured outcome, so:
- we can report, with confidence intervals, how often "BULLISH" tags were
  followed by out-performance, per news category;
- we can train and walk-forward-test a news model once enough outcomes
  have accumulated (see train_news_model).
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.quant.validation import evaluate, walk_forward, _r

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_IST_HOUR = 15.5
HORIZONS = (1, 5, 20)
MIN_SAMPLES_FOR_MODEL = 400


def yf_symbol(symbol: str, exchange: Optional[str]) -> str:
    ex = (exchange or "NSE").upper()
    if ex == "NSE":
        return f"{symbol}.NS"
    if ex == "BSE":
        return f"{symbol}.BO"
    return symbol


def benchmark_for(exchange: Optional[str]) -> str:
    return "^NSEI" if (exchange or "NSE").upper() in ("NSE", "BSE") else "^GSPC"


def event_day_index(cal: pd.DatetimeIndex, published_at: datetime) -> Optional[int]:
    """
    Index of the first trading session that could react to the news.
    News after 15:30 IST (or on a holiday) reacts on the next session.
    """
    ts = published_at.astimezone(IST)
    day = pd.Timestamp(ts.date())
    after_close = ts.hour + ts.minute / 60 >= MARKET_CLOSE_IST_HOUR
    pos = cal.searchsorted(day, side="right" if after_close else "left")
    return int(pos) if pos < len(cal) else None


def compute_outcome(
    close: pd.Series, open_: pd.Series, bench: pd.Series, published_at: datetime,
) -> Optional[Dict]:
    """Abnormal returns measured from the last close BEFORE the news."""
    close, bench = close.dropna(), bench.reindex(close.index).ffill()
    cal = close.index
    e = event_day_index(cal, published_at)
    if e is None or e == 0:
        return None
    base_i = e - 1
    out = {"event_date": cal[e].date(), "base_close": float(close.iloc[base_i])}
    for h in HORIZONS:
        j = base_i + h
        if j >= len(cal):
            out[f"ret_{h}d"] = out[f"abn_{h}d"] = None
            continue
        r = math.log(close.iloc[j] / close.iloc[base_i])
        m = math.log(bench.iloc[j] / bench.iloc[base_i])
        out[f"ret_{h}d"], out[f"abn_{h}d"] = r, r - m
    # Tradable version: you only see the news, then buy at the next open.
    o = open_.reindex(cal)
    j = e + 5
    if j < len(cal) and pd.notna(o.iloc[e]) and o.iloc[e] > 0:
        r = math.log(close.iloc[j] / o.iloc[e])
        m = math.log(bench.iloc[j] / bench.iloc[e])
        out["tradable_abn_5d"] = r - m
    else:
        out["tradable_abn_5d"] = None
    return out


async def update_news_outcomes(days_back: int = 45, max_pairs: int = 3000) -> int:
    """Scheduler job: fill/refresh outcomes for recent news-stock pairs."""
    import yfinance as yf
    from app.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT nsi.news_id, nsi.symbol, s.exchange, n.published_at
            FROM news_stock_impact nsi
            JOIN news n ON n.id = nsi.news_id
            LEFT JOIN stocks s ON s.id = nsi.stock_id
            LEFT JOIN news_outcomes o ON o.news_id = nsi.news_id AND o.symbol = nsi.symbol
            WHERE n.published_at IS NOT NULL
              AND n.published_at >= NOW() - ($1 || ' days')::interval
              AND n.published_at <= NOW() - INTERVAL '1 day'
              AND (o.news_id IS NULL OR o.abn_20d IS NULL)
            ORDER BY n.published_at DESC
            LIMIT $2
            """,
            str(days_back), max_pairs,
        )
    if not rows:
        return 0

    tickers = sorted({yf_symbol(r["symbol"], r["exchange"]) for r in rows}
                     | {benchmark_for(r["exchange"]) for r in rows})
    import asyncio
    raw = await asyncio.to_thread(
        lambda: yf.download(tickers, period="6mo", interval="1d", auto_adjust=True,
                            progress=False, group_by="column", threads=True)
    )
    if raw is None or raw.empty:
        return 0
    close, open_ = raw["Close"], raw["Open"]

    written = 0
    async with pool.acquire() as conn:
        for r in rows:
            t, b = yf_symbol(r["symbol"], r["exchange"]), benchmark_for(r["exchange"])
            if t not in close.columns or b not in close.columns:
                continue
            res = compute_outcome(close[t], open_[t], close[b], r["published_at"])
            if not res:
                continue
            await conn.execute(
                """
                INSERT INTO news_outcomes (news_id, symbol, event_date, base_close,
                    ret_1d, ret_5d, ret_20d, abn_1d, abn_5d, abn_20d, tradable_abn_5d, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())
                ON CONFLICT (news_id, symbol) DO UPDATE SET
                    ret_1d=EXCLUDED.ret_1d, ret_5d=EXCLUDED.ret_5d, ret_20d=EXCLUDED.ret_20d,
                    abn_1d=EXCLUDED.abn_1d, abn_5d=EXCLUDED.abn_5d, abn_20d=EXCLUDED.abn_20d,
                    tradable_abn_5d=EXCLUDED.tradable_abn_5d, updated_at=NOW()
                """,
                r["news_id"], r["symbol"], res["event_date"], res["base_close"],
                res["ret_1d"], res["ret_5d"], res["ret_20d"],
                res["abn_1d"], res["abn_5d"], res["abn_20d"], res["tradable_abn_5d"],
            )
            written += 1
    logger.info(f"News outcomes updated: {written}")
    return written


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def wilson_interval(hits: int, n: int, z: float = 1.96):
    if n == 0:
        return (None, None)
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - m, 4), round(c + m, 4))


def summarize(df: pd.DataFrame, horizon: str = "abn_5d", min_n: int = 10) -> List[Dict]:
    """
    Per (direction, category): how often the tagged direction was right,
    the average abnormal move, a 95% interval on the hit rate, and a t-stat.
    """
    d = df.dropna(subset=[horizon]).copy()
    if d.empty:
        return []
    d["category"] = d["category"].fillna("general")
    sign = d["impact_direction"].map({"BULLISH": 1, "BEARISH": -1}).fillna(0)
    d["correct"] = np.where(sign == 0, np.nan, (np.sign(d[horizon]) == sign).astype(float))
    out = []
    for (direction, cat), g in d.groupby(["impact_direction", "category"]):
        n = len(g)
        if n < min_n:
            continue
        x = g[horizon]
        t = x.mean() / (x.std(ddof=1) / math.sqrt(n)) if n > 2 and x.std(ddof=1) > 0 else None
        hits = int(g["correct"].sum()) if direction in ("BULLISH", "BEARISH") else None
        out.append({
            "direction": direction, "category": cat, "samples": n,
            "avg_abnormal_move_pct": _r(x.mean() * 100, 3),
            "median_abnormal_move_pct": _r(x.median() * 100, 3),
            "typical_range_pct": [_r(x.quantile(0.1) * 100, 2), _r(x.quantile(0.9) * 100, 2)],
            "direction_correct_pct": _r(hits / n * 100, 1) if hits is not None else None,
            "direction_correct_95ci": wilson_interval(hits, n) if hits is not None else None,
            "t_stat": _r(t, 2),
            "significant": bool(t is not None and abs(t) > 2),
        })
    return sorted(out, key=lambda r: -r["samples"])


async def load_outcomes_frame(days: int = 365) -> pd.DataFrame:
    from app.database import fetch
    rows = await fetch(
        """
        SELECT o.*, nsi.impact_direction, nsi.impact_score, n.category, n.source,
               n.sentiment_score, n.published_at
        FROM news_outcomes o
        JOIN news_stock_impact nsi ON nsi.news_id = o.news_id AND nsi.symbol = o.symbol
        JOIN news n ON n.id = o.news_id
        WHERE o.event_date >= CURRENT_DATE - $1::int
        """,
        days,
    )
    df = pd.DataFrame(rows)
    for c in ("ret_1d", "ret_5d", "ret_20d", "abn_1d", "abn_5d", "abn_20d", "tradable_abn_5d",
              "impact_score", "sentiment_score"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def train_news_model(df: pd.DataFrame) -> Dict:
    """
    Learn which news (category, tagged direction, impact, sentiment, source)
    is actually followed by out-performance over 5 days, using the
    tradable outcome (buy at the first open after the news).
    Walk-forward tested; refuses to train with too little data.
    """
    d = df.dropna(subset=["tradable_abn_5d"]).copy() if not df.empty else df
    if len(d) < MIN_SAMPLES_FOR_MODEL:
        return {"model_key": "news_5d", "status": "collecting_data", "samples": int(len(d)),
                "samples_needed": MIN_SAMPLES_FOR_MODEL, "edge_verified": False}

    from sklearn.ensemble import HistGradientBoostingClassifier
    d["event_date"] = pd.to_datetime(d["event_date"])
    X = pd.DataFrame(index=d.index)
    X["impact_score"] = d["impact_score"].fillna(0)
    X["sentiment_score"] = d["sentiment_score"].fillna(0)
    X["dir"] = d["impact_direction"].map({"BULLISH": 1, "BEARISH": -1}).fillna(0)
    for cat in d["category"].fillna("general").value_counts().index[:12]:
        X[f"cat_{cat}"] = (d["category"].fillna("general") == cat).astype(int)
    for src in d["source"].fillna("").value_counts().index[:10]:
        X[f"src_{src}"] = (d["source"].fillna("") == src).astype(int)
    X["fwd_ret"] = d["ret_5d"]
    X["fwd_excess"] = d["tradable_abn_5d"]
    X.index = pd.MultiIndex.from_arrays([d["event_date"], d["symbol"]], names=["date", "symbol"])
    X = X.sort_index()
    fc = [c for c in X.columns if c not in ("fwd_ret", "fwd_excess")]
    y = (X["fwd_excess"] > 0).astype(float)

    wf = walk_forward(
        X, fc, y, horizon=5, min_train_days=60, test_days=20, cross_sectional=False,
        model_factory=lambda: HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=40,
            l2_regularization=3.0, random_state=7),
    )
    if wf.oos.empty:
        return {"model_key": "news_5d", "status": "collecting_data", "samples": int(len(d)),
                "samples_needed": MIN_SAMPLES_FOR_MODEL, "edge_verified": False}
    metrics = evaluate(wf.oos, 5, cross_sectional=False)
    return {
        "model_key": "news_5d", "status": "trained", "samples": int(len(d)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "edge_verified": metrics["edge_verified"], "metrics": metrics, "folds": wf.folds,
    }
