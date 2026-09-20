"""
Technical Analyzer — Computes technical indicators from yfinance history data.

Indicators:
  - SMA 50 / SMA 200 (Simple Moving Averages)
  - EMA 20 (Exponential Moving Average)
  - Golden Cross / Death Cross detection
  - RSI (14) — Relative Strength Index
  - MACD (12, 26, 9) — Moving Average Convergence Divergence
  - Bollinger Bands (20, 2σ)
  - 52-Week High/Low + distance from extremes
  - Support / Resistance (pivot-based)
  - Volume Average (20D) + volume ratio
  - ATR (14) — Average True Range
  - Technical Verdict: STRONG_BUY → STRONG_SELL (indicator consensus)

All computed in pure Python — no external TA library needed.
Uses pandas (already available via yfinance dependency).
"""

import time
import logging
import asyncio
import math
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)

# Cache: key -> {data, expires_at}
_tech_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 900  # 15 minutes


def _get_yf_ticker(symbol: str, exchange: str = "NSE") -> str:
    clean = symbol.strip().upper()
    if clean.startswith("^"):
        return clean
    ex = exchange.upper()
    if ex == "NSE":
        return f"{clean}.NS"
    elif ex == "BSE":
        return f"{clean}.BO"
    return clean


def _safe(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Indicator computation functions (pure Python + pandas)
# ---------------------------------------------------------------------------

def _compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=window, min_periods=window).mean()


def _compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's method)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _compute_macd(series: pd.Series) -> Dict[str, pd.Series]:
    """MACD (12, 26, 9)."""
    ema12 = _compute_ema(series, 12)
    ema26 = _compute_ema(series, 26)
    macd_line = ema12 - ema26
    signal_line = _compute_ema(macd_line, 9)
    histogram = macd_line - signal_line
    return {
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
    }


def _compute_bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0):
    """Bollinger Bands (20-SMA ± 2σ)."""
    sma = _compute_sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = sma + (std * num_std)
    lower = sma - (std * num_std)
    return sma, upper, lower


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / period, min_periods=period).mean()
    return atr


def _find_support_resistance(close: pd.Series, window: int = 20) -> Dict[str, Optional[float]]:
    """Simple pivot-based support/resistance from recent price action."""
    if len(close) < window:
        return {"support": None, "resistance": None}

    recent = close.tail(window)
    high = recent.max()
    low = recent.min()
    last = close.iloc[-1]

    # Support: most recent significant low
    # Resistance: most recent significant high
    return {
        "support": round(float(low), 2),
        "resistance": round(float(high), 2),
        "pivot": round(float((high + low + last) / 3), 2),
    }


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def _analyze_sync(yf_ticker: str) -> Optional[Dict[str, Any]]:
    """Run all technical analysis synchronously."""
    try:
        ticker = yf.Ticker(yf_ticker)
        # Fetch 1 year of daily data
        hist = ticker.history(period="1y", interval="1d")

        if hist.empty or len(hist) < 30:
            return None

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]

        current_price = float(close.iloc[-1])

        # --- Moving Averages ---
        sma_20 = _compute_sma(close, 20)
        sma_50 = _compute_sma(close, 50)
        sma_200 = _compute_sma(close, 200)
        ema_20 = _compute_ema(close, 20)

        sma_20_val = _safe(sma_20.iloc[-1])
        sma_50_val = _safe(sma_50.iloc[-1])
        sma_200_val = _safe(sma_200.iloc[-1])
        ema_20_val = _safe(ema_20.iloc[-1])

        # Golden Cross / Death Cross
        cross_signal = "NONE"
        if sma_50_val and sma_200_val:
            prev_sma50 = _safe(sma_50.iloc[-2]) if len(sma_50) > 1 else None
            prev_sma200 = _safe(sma_200.iloc[-2]) if len(sma_200) > 1 else None
            if prev_sma50 and prev_sma200:
                if prev_sma50 < prev_sma200 and sma_50_val > sma_200_val:
                    cross_signal = "GOLDEN_CROSS"
                elif prev_sma50 > prev_sma200 and sma_50_val < sma_200_val:
                    cross_signal = "DEATH_CROSS"

        # Price vs MA signals
        above_sma_50 = current_price > sma_50_val if sma_50_val else None
        above_sma_200 = current_price > sma_200_val if sma_200_val else None

        # --- RSI ---
        rsi_series = _compute_rsi(close, 14)
        rsi_val = _safe(rsi_series.iloc[-1])
        rsi_signal = "NEUTRAL"
        if rsi_val:
            if rsi_val > 70:
                rsi_signal = "OVERBOUGHT"
            elif rsi_val < 30:
                rsi_signal = "OVERSOLD"
            elif rsi_val > 60:
                rsi_signal = "BULLISH"
            elif rsi_val < 40:
                rsi_signal = "BEARISH"

        # --- MACD ---
        macd_data = _compute_macd(close)
        macd_val = _safe(macd_data["macd_line"].iloc[-1])
        macd_signal_val = _safe(macd_data["signal_line"].iloc[-1])
        macd_hist_val = _safe(macd_data["histogram"].iloc[-1])

        macd_signal = "NEUTRAL"
        if macd_val is not None and macd_signal_val is not None:
            if macd_val > macd_signal_val:
                macd_signal = "BULLISH"
            else:
                macd_signal = "BEARISH"

        # --- Bollinger Bands ---
        bb_mid, bb_upper, bb_lower = _compute_bollinger(close, 20, 2.0)
        bb_upper_val = _safe(bb_upper.iloc[-1])
        bb_lower_val = _safe(bb_lower.iloc[-1])
        bb_mid_val = _safe(bb_mid.iloc[-1])

        bb_signal = "NEUTRAL"
        if bb_upper_val and bb_lower_val:
            if current_price >= bb_upper_val:
                bb_signal = "OVERBOUGHT"
            elif current_price <= bb_lower_val:
                bb_signal = "OVERSOLD"

        # --- 52-Week Range ---
        high_52w = float(high.max())
        low_52w = float(low.min())
        pct_from_high = round(((current_price - high_52w) / high_52w) * 100, 2)
        pct_from_low = round(((current_price - low_52w) / low_52w) * 100, 2)

        # --- Volume Analysis ---
        vol_avg_20 = _safe(volume.tail(20).mean())
        vol_current = float(volume.iloc[-1]) if not volume.empty else 0
        vol_ratio = round(vol_current / vol_avg_20, 2) if vol_avg_20 and vol_avg_20 > 0 else None

        vol_signal = "NORMAL"
        if vol_ratio:
            if vol_ratio > 2.5:
                vol_signal = "BREAKOUT"
            elif vol_ratio > 1.5:
                vol_signal = "HIGH"
            elif vol_ratio < 0.5:
                vol_signal = "LOW"

        # --- ATR ---
        atr_series = _compute_atr(high, low, close, 14)
        atr_val = _safe(atr_series.iloc[-1])
        atr_pct = round((atr_val / current_price) * 100, 2) if atr_val and current_price > 0 else None

        # --- Support / Resistance ---
        sr = _find_support_resistance(close, 20)

        # --- Trend Assessment ---
        trend = "SIDEWAYS"
        if sma_50_val and sma_200_val:
            if current_price > sma_50_val > sma_200_val:
                trend = "STRONG_UPTREND"
            elif current_price > sma_50_val:
                trend = "UPTREND"
            elif current_price < sma_50_val < sma_200_val:
                trend = "STRONG_DOWNTREND"
            elif current_price < sma_50_val:
                trend = "DOWNTREND"

        # --- Technical Verdict (consensus) ---
        buy_signals = 0
        sell_signals = 0
        total_signals = 0

        # MA signals
        if above_sma_50 is not None:
            total_signals += 1
            if above_sma_50:
                buy_signals += 1
            else:
                sell_signals += 1

        if above_sma_200 is not None:
            total_signals += 1
            if above_sma_200:
                buy_signals += 1
            else:
                sell_signals += 1

        # RSI
        total_signals += 1
        if rsi_signal == "OVERSOLD":
            buy_signals += 1
        elif rsi_signal == "OVERBOUGHT":
            sell_signals += 1
        elif rsi_signal == "BULLISH":
            buy_signals += 0.5
        elif rsi_signal == "BEARISH":
            sell_signals += 0.5

        # MACD
        total_signals += 1
        if macd_signal == "BULLISH":
            buy_signals += 1
        elif macd_signal == "BEARISH":
            sell_signals += 1

        # Bollinger
        total_signals += 1
        if bb_signal == "OVERSOLD":
            buy_signals += 1
        elif bb_signal == "OVERBOUGHT":
            sell_signals += 1

        # Volume
        if vol_signal == "BREAKOUT":
            total_signals += 1
            if trend in ("UPTREND", "STRONG_UPTREND"):
                buy_signals += 1
            else:
                sell_signals += 1

        # Cross
        if cross_signal == "GOLDEN_CROSS":
            buy_signals += 2
            total_signals += 2
        elif cross_signal == "DEATH_CROSS":
            sell_signals += 2
            total_signals += 2

        # Determine verdict
        if total_signals > 0:
            buy_pct = buy_signals / total_signals
            sell_pct = sell_signals / total_signals
        else:
            buy_pct = sell_pct = 0

        if buy_pct >= 0.7:
            verdict = "STRONG_BUY"
        elif buy_pct >= 0.5:
            verdict = "BUY"
        elif sell_pct >= 0.7:
            verdict = "STRONG_SELL"
        elif sell_pct >= 0.5:
            verdict = "SELL"
        else:
            verdict = "NEUTRAL"

        # --- Build chart overlay data (last 60 data points for SMA lines) ---
        overlay_len = min(60, len(close))
        sma_50_overlay = [_safe(v) for v in sma_50.tail(overlay_len).tolist()]
        sma_200_overlay = [_safe(v) for v in sma_200.tail(overlay_len).tolist()]
        bb_upper_overlay = [_safe(v) for v in bb_upper.tail(overlay_len).tolist()]
        bb_lower_overlay = [_safe(v) for v in bb_lower.tail(overlay_len).tolist()]

        return {
            "current_price": round(current_price, 2),
            "trend": trend,
            "verdict": verdict,
            "buy_signal_pct": round(buy_pct * 100, 0),
            "sell_signal_pct": round(sell_pct * 100, 0),

            "moving_averages": {
                "sma_20": sma_20_val,
                "sma_50": sma_50_val,
                "sma_200": sma_200_val,
                "ema_20": ema_20_val,
                "above_sma_50": above_sma_50,
                "above_sma_200": above_sma_200,
                "cross_signal": cross_signal,
            },

            "rsi": {
                "value": rsi_val,
                "signal": rsi_signal,
            },

            "macd": {
                "macd_line": macd_val,
                "signal_line": macd_signal_val,
                "histogram": macd_hist_val,
                "signal": macd_signal,
            },

            "bollinger_bands": {
                "upper": bb_upper_val,
                "middle": bb_mid_val,
                "lower": bb_lower_val,
                "signal": bb_signal,
            },

            "fifty_two_week": {
                "high": round(high_52w, 2),
                "low": round(low_52w, 2),
                "pct_from_high": pct_from_high,
                "pct_from_low": pct_from_low,
            },

            "volume": {
                "current": int(vol_current),
                "average_20d": int(vol_avg_20) if vol_avg_20 else None,
                "ratio": vol_ratio,
                "signal": vol_signal,
            },

            "atr": {
                "value": atr_val,
                "pct_of_price": atr_pct,
            },

            "support_resistance": sr,

            # Chart overlay arrays (for drawing indicator lines on price chart)
            "chart_overlay": {
                "sma_50": sma_50_overlay,
                "sma_200": sma_200_overlay,
                "bollinger_upper": bb_upper_overlay,
                "bollinger_lower": bb_lower_overlay,
            },
        }

    except Exception as e:
        logger.warning(f"Technical analysis failed for {yf_ticker}: {e}")
        return None


class TechnicalAnalyzer:
    """Provides on-demand technical analysis for any stock."""

    async def analyze(self, symbol: str, exchange: str = "NSE") -> Dict[str, Any]:
        """Run full technical analysis for a stock."""
        yf_ticker = _get_yf_ticker(symbol, exchange)
        cache_key = f"tech_{yf_ticker}"
        now = time.time()

        # Check cache
        if cache_key in _tech_cache:
            cached = _tech_cache[cache_key]
            if now < cached["expires_at"]:
                return cached["data"]

        # Run in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _analyze_sync, yf_ticker)

        if not result:
            return {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "error": "Technical data unavailable",
                "verdict": "NEUTRAL",
            }

        result["symbol"] = symbol.upper()
        result["exchange"] = exchange.upper()

        # Cache
        _tech_cache[cache_key] = {
            "data": result,
            "expires_at": now + CACHE_TTL,
        }

        return result


# Singleton
technical_analyzer = TechnicalAnalyzer()
