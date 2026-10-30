"""
State-space tools: a Kalman trend filter for every stock and a hidden
Markov model for the market's regime.

Kalman trend (local linear trend on log price)
    level_t    = level_(t-1) + velocity_(t-1) + noise
    velocity_t = velocity_(t-1) + small noise
    price_t    = level_t + measurement noise
The filter gives each stock's current trend speed (velocity) AND how sure
we are about it (its standard error). velocity / std-error is the trend's
signal-to-noise ratio: above about 2 the trend is real, not just noise.
Noise levels scale with each stock's own volatility, so a calm stock and a
wild one are judged on the same footing. Runs forward only: no peeking.

Market regime (Gaussian HMM, fitted with Baum-Welch EM)
Hidden states are learned from weekly market breadth (share of stocks above
their 200-day average, median 3-month return, share at 52-week highs). The
states are then named by their average breadth.
"""

from typing import Dict

import numpy as np
import pandas as pd


def kalman_trend(close: pd.DataFrame, vol_window: int = 60, q_ratio: float = 0.02) -> Dict[str, pd.DataFrame]:
    """Returns {"velocity": annualised trend (log units/year), "snr": velocity / std error, "accel": 60-day change in velocity}."""
    y = np.log(close.where(close > 0)).values
    T, N = y.shape
    r = np.log(close).diff()
    sig = r.rolling(vol_window, min_periods=20).std().bfill().fillna(0.03).values   # daily vol per stock
    lvl = np.full(N, np.nan)
    vel = np.zeros(N)
    P11 = np.full(N, 1.0)
    P12 = np.zeros(N)
    P22 = np.full(N, 1e-4)
    V = np.full((T, N), np.nan)
    S = np.full((T, N), np.nan)
    for t in range(T):
        obs = y[t]
        s2 = sig[t] ** 2
        q_l, q_v = s2 * 0.1, (q_ratio * sig[t]) ** 2 / 10
        start = np.isnan(lvl) & ~np.isnan(obs)
        lvl[start] = obs[start]
        vel[start] = 0.0
        P11[start], P12[start], P22[start] = s2[start], 0.0, (sig[t][start] / 5) ** 2
        # predict
        lvl_p = lvl + vel
        P11p = P11 + 2 * P12 + P22 + q_l
        P12p = P12 + P22
        P22p = P22 + q_v
        # update where observed
        has = ~np.isnan(obs) & ~np.isnan(lvl_p)
        Sinn = P11p + s2
        with np.errstate(invalid="ignore", divide="ignore"):
            K1, K2 = P11p / Sinn, P12p / Sinn
        innov = np.where(has, obs - lvl_p, 0.0)
        lvl = np.where(has, lvl_p + K1 * innov, lvl_p)
        vel = np.where(has, vel + K2 * innov, vel)
        P11 = np.where(has, (1 - K1) * P11p, P11p)
        P12 = np.where(has, (1 - K1) * P12p, P12p)
        P22 = np.where(has, P22p - K2 * P12p, P22p)
        V[t] = np.where(np.isnan(obs), np.nan, vel)
        S[t] = np.where(np.isnan(obs), np.nan, np.sqrt(np.maximum(P22, 1e-12)))
    velocity = pd.DataFrame(V * 250, index=close.index, columns=close.columns)
    snr = pd.DataFrame(V / S, index=close.index, columns=close.columns)
    return {"velocity": velocity, "snr": snr, "accel": velocity - velocity.shift(60)}


def market_breadth(close: pd.DataFrame, liquid: pd.DataFrame) -> pd.DataFrame:
    c = close.where(liquid)
    above = (close > close.rolling(200, min_periods=150).mean()).where(liquid)
    hi = (close >= close.rolling(250, min_periods=200).max() * 0.98).where(liquid)
    ret3m = (close / close.shift(63) - 1).where(liquid)
    out = pd.DataFrame({
        "pct_above_200dma": above.mean(axis=1),
        "median_3m_return": ret3m.median(axis=1),
        "pct_near_52w_high": hi.mean(axis=1),
    })
    out = out[c.notna().sum(axis=1) > 100]
    return out.dropna()


class GaussianHMM:
    """Small diagonal-covariance Gaussian HMM fitted by Baum-Welch EM (scaled forward-backward)."""

    def __init__(self, n_states: int = 3, n_iter: int = 200, seed: int = 0):
        self.k, self.n_iter, self.seed = n_states, n_iter, seed

    def _emis(self, X):
        d = X[:, None, :] - self.mu[None]
        logp = -0.5 * (np.log(2 * np.pi * self.var)[None] + d ** 2 / self.var[None]).sum(-1)
        return np.exp(logp - logp.max(1, keepdims=True)), logp.max(1)

    def _fb(self, X):
        B, _ = self._emis(X)
        T, k = B.shape
        a = np.zeros((T, k)); c = np.zeros(T)
        a[0] = self.pi * B[0]; c[0] = a[0].sum(); a[0] /= c[0]
        for t in range(1, T):
            a[t] = (a[t - 1] @ self.A) * B[t]; c[t] = a[t].sum(); a[t] /= c[t]
        b = np.ones((T, k))
        for t in range(T - 2, -1, -1):
            b[t] = (self.A @ (B[t + 1] * b[t + 1])) / c[t + 1]
        return a, b, B, c

    def fit(self, X: np.ndarray):
        X = np.asarray(X, float)
        T, d = X.shape
        k = self.k
        # start from quantiles of the first feature so states come out ordered
        order = np.argsort(X[:, 0])
        chunks = np.array_split(order, k)
        self.mu = np.array([X[c].mean(0) for c in chunks])
        self.var = np.array([X[c].var(0) + 1e-4 for c in chunks])
        self.A = np.full((k, k), 0.05 / (k - 1)); np.fill_diagonal(self.A, 0.95)
        self.pi = np.full(k, 1 / k)
        for _ in range(self.n_iter):
            a, b, B, c = self._fb(X)
            g = a * b
            g /= g.sum(1, keepdims=True)
            xi = np.zeros((k, k))
            for t in range(T - 1):
                m = a[t][:, None] * self.A * (B[t + 1] * b[t + 1])[None]
                xi += m / m.sum()
            self.pi = g[0]
            self.A = xi / xi.sum(1, keepdims=True)
            w = g.sum(0)[:, None]
            self.mu = (g.T @ X) / w
            self.var = (g.T @ X ** 2) / w - self.mu ** 2 + 1e-4
        return self

    def filtered(self, X: np.ndarray) -> np.ndarray:
        """P(state_t | data up to t): forward pass only, so no future data is used."""
        a, _, _, _ = self._fb(np.asarray(X, float))
        return a


REGIME_NAMES = {3: ["washout", "neutral", "broad rally"]}


def market_regime(breadth: pd.DataFrame, freq: str = "W-FRI") -> Dict:
    weekly = breadth.resample(freq).last().dropna()
    X = ((weekly - weekly.mean()) / weekly.std()).values
    hmm = GaussianHMM(3).fit(X)
    # name states by average breadth (low -> high)
    rank = np.argsort(hmm.mu[:, 0])
    names = {int(s): REGIME_NAMES[3][i] for i, s in enumerate(rank)}
    probs = pd.DataFrame(hmm.filtered(X), index=weekly.index).rename(columns=names)
    return {"weekly": weekly, "probs": probs, "names": names,
            "transition": pd.DataFrame(hmm.A, index=[names[i] for i in range(3)],
                                       columns=[names[i] for i in range(3)])}
