"""
Point-in-time features and forward-return labels.

Rules that keep the testing honest:
- A feature for day t uses only prices known at the close of day t.
- The trade is assumed to happen at the NEXT day's open (t+1) and exit at
  the open h trading days later. So the label never overlaps the data the
  feature saw, and the backtest doesn't assume impossible same-close fills.
"""

from typing import Dict, List

import numpy as np
import pandas as pd

HORIZONS = {"trader": 5, "swing": 20, "investor": 60}


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def market_features(prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per date: market regime features shared by all stocks."""
    n = prices["nifty"]["Close"]
    vix = prices["vix"].ffill()
    close = prices["Close"]
    sma50 = close.rolling(50, min_periods=40).mean()
    lr = np.log(n).diff()

    m = pd.DataFrame(index=n.index)
    m["mkt_ret_5"] = np.log(n / n.shift(5))
    m["mkt_ret_20"] = np.log(n / n.shift(20))
    m["mkt_ret_60"] = np.log(n / n.shift(60))
    m["mkt_dist_sma200"] = n / n.rolling(200, min_periods=150).mean() - 1
    m["mkt_vol_20"] = lr.rolling(20).std() * np.sqrt(252)
    m["vix"] = vix
    m["vix_chg_5"] = np.log(vix / vix.shift(5))
    m["vix_pct_1y"] = vix.rolling(252, min_periods=120).rank(pct=True)
    valid = close.notna() & sma50.notna()
    m["breadth_50"] = ((close > sma50) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    adv = (close.pct_change(fill_method=None) > 0).sum(axis=1)
    m["adv_ratio_10"] = (adv / close.notna().sum(axis=1).replace(0, np.nan)).rolling(10).mean()
    return m


def stock_features(prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Long panel indexed by (date, symbol) with per-stock features."""
    c, h, l, v = prices["Close"], prices["High"], prices["Low"], prices["Volume"]
    n = prices["nifty"]["Close"]
    lr = np.log(c).diff()

    f: Dict[str, pd.DataFrame] = {}
    for k in (1, 5, 20, 60, 120, 250):
        f[f"ret_{k}"] = np.log(c / c.shift(k))
    f["ret_250_skip20"] = np.log(c.shift(20) / c.shift(250))  # classic 12-1 momentum
    f["vol_20"] = lr.rolling(20).std() * np.sqrt(252)
    f["vol_60"] = lr.rolling(60).std() * np.sqrt(252)
    f["vol_ratio"] = f["vol_20"] / f["vol_60"]
    f["rsi_14"] = _rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    f["macd_hist"] = (macd - macd.ewm(span=9, adjust=False).mean()) / c
    for k in (20, 50, 200):
        f[f"dist_sma{k}"] = c / c.rolling(k, min_periods=int(k * 0.8)).mean() - 1
    f["dist_52w_high"] = c / c.rolling(252, min_periods=200).max() - 1
    f["dist_52w_low"] = c / c.rolling(252, min_periods=200).min() - 1
    tr = pd.concat({"a": h - l, "b": (h - c.shift()).abs(), "c": (l - c.shift()).abs()}).groupby(level=1).max()
    f["atr_14"] = tr.rolling(14).mean() / c
    dollar_vol = (c * v).replace(0, np.nan)
    f["volume_z"] = np.log(v.replace(0, np.nan) / v.rolling(20).mean().replace(0, np.nan))
    f["liquidity"] = np.log(dollar_vol.rolling(20).mean())
    nret = np.log(n / n.shift(1))
    for k in (20, 60):
        f[f"rel_str_{k}"] = f[f"ret_{k}"].sub(np.log(n / n.shift(k)), axis=0)
    # 60-day beta to the Nifty
    cov = lr.rolling(60).cov(nret)
    f["beta_60"] = cov.div(nret.rolling(60).var(), axis=0)

    # Cross-sectional ranks: "how does this stock compare with its peers today"
    for k in ("ret_20", "ret_60", "ret_250_skip20", "vol_20", "volume_z", "rel_str_60"):
        f[f"rank_{k}"] = f[k].rank(axis=1, pct=True)

    panel = pd.concat({k: df.stack(future_stack=True) for k, df in f.items()}, axis=1)
    panel.index.names = ["date", "symbol"]
    return panel


def forward_labels(prices: Dict[str, pd.DataFrame], horizon: int) -> pd.DataFrame:
    """
    Forward return from the next open (t+1) to the open h days after (t+1+h),
    for the stock and for the Nifty. Excess = stock minus Nifty.
    """
    o = prices["Open"].where(prices["Open"] > 0)
    no = prices["nifty"]["Open"].where(prices["nifty"]["Open"] > 0)
    entry, exit_ = o.shift(-1), o.shift(-1 - horizon)
    stock_ret = np.log(exit_ / entry)
    mkt_ret = np.log(no.shift(-1 - horizon) / no.shift(-1))
    excess = stock_ret.sub(mkt_ret, axis=0)
    lab = pd.concat(
        {"fwd_ret": stock_ret.stack(future_stack=True), "fwd_excess": excess.stack(future_stack=True)},
        axis=1,
    )
    lab.index.names = ["date", "symbol"]
    return lab


def build_dataset(prices: Dict[str, pd.DataFrame], horizon: int, extras: bool = True) -> pd.DataFrame:
    """
    Features + market regime + labels. Rows without a label are kept (they are 'today').
    extras=True adds delivery %, FII/DII positioning and results-surprise
    features where available (blank before 2020; the model handles blanks).
    """
    panel = stock_features(prices)
    mkt = market_features(prices)
    panel = panel.join(mkt, on="date")
    panel = panel.dropna(subset=list(panel.columns), how="any")
    if extras:
        from app.quant.delivery import delivery_features
        from app.quant.earnings import earnings_features
        from app.quant.participants import participant_features
        for extra in (delivery_features(prices), earnings_features(prices)):
            if extra is not None:
                panel = panel.join(extra, how="left")
        part = participant_features(prices["Close"].index)
        if part is not None:
            panel = panel.join(part, on="date")
    panel = panel.join(forward_labels(prices, horizon))
    return panel


def feature_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c not in ("fwd_ret", "fwd_excess")]
