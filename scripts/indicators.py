"""
indicators.py
OHLCV verisinden teknik göstergeleri hesaplar.

İki giriş noktası var:
  - add_indicator_columns(df): TÜM geçmişe gösterge kolonları ekler (backtest ve
    portfolio_tracker için gerekli — her bar için ayrı ayrı doğru/causal değer verir)
  - compute_indicators(df): add_indicator_columns'ı çağırır, SADECE son satırı
    özet dict olarak döner (main.py'nin canlı tarama akışı için)

Böylece tüm scriptler (main, backtest, portfolio_tracker) AYNI gösterge
hesaplama mantığını kullanır — tutarsızlık riski ortadan kalkar.
"""

import pandas as pd
import numpy as np


def add_indicator_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    df: OHLCV DataFrame (Open, High, Low, Close, Volume kolonları)
    Dönen: aynı df + hesaplanmış gösterge kolonları eklenmiş hali.
    Rolling/ewm hesaplamalar causal'dır (her satır sadece kendine kadar olan veriyi kullanır),
    bu yüzden backtest'te ileriye bakma (lookahead) hatası oluşturmaz.
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df.columns = [c.capitalize() for c in df.columns]

    # --- Trend (EMA) ---
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

    # --- ADX (14) ---
    high_diff = df["High"].diff()
    low_diff = -df["Low"].diff()

    pos_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
    neg_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)

    tr = np.maximum(
        df["High"] - df["Low"],
        np.maximum(
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs()
        )
    )

    tr_smooth = pd.Series(tr, index=df.index).ewm(alpha=1 / 14, adjust=False).mean()
    pos_di = 100 * (pd.Series(pos_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / tr_smooth)
    neg_di = 100 * (pd.Series(neg_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / tr_smooth)

    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di)
    df["ADX14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    # --- Momentum (RSI & MACD) ---
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI14"] = 100 - (100 / (1 + rs))

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    # --- Volatilite (ATR & Bollinger Bands) ---
    df["ATR14"] = tr_smooth

    bb_middle = df["Close"].rolling(window=20).mean()
    bb_std = df["Close"].rolling(window=20).std()
    df["BB_UPPER"] = bb_middle + (bb_std * 2)
    df["BB_LOWER"] = bb_middle - (bb_std * 2)
    df["BB_WIDTH"] = (df["BB_UPPER"] - df["BB_LOWER"]) / df["Close"]

    # --- Hacim (OBV & VOL_AVG) ---
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()

    obv_change = np.sign(df["Close"].diff()).fillna(0)
    df["OBV"] = (obv_change * df["Volume"]).cumsum()

    return df


def _bearish_rsi_divergence(df: pd.DataFrame, lookback: int = 10) -> bool:
    """Son `lookback` barda fiyat yeni yüksek yaparken RSI yapmadıysa True."""
    if len(df) < lookback:
        return False
    window = df.iloc[-lookback:]
    last = df.iloc[-1]
    if pd.isna(last["RSI14"]) or window["RSI14"].isna().all():
        return False
    return bool(
        last["Close"] >= window["Close"].max() * 0.999
        and last["RSI14"] < window["RSI14"].max() - 3
    )


def compute_indicators(df: pd.DataFrame) -> dict:
    """
    df: en az 60 barlık günlük OHLCV verisi (EMA200 için en az 200 satır önerilir)
    Dönen dict: main.py'nin canlı taramada kullandığı özet gösterge yapısı.
    """
    if df is None or len(df) < 60:
        return None

    df = add_indicator_columns(df)
    if len(df) < 2:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    bearish_div = _bearish_rsi_divergence(df)

    obv_slope = np.nan
    if len(df) >= 6:
        obv_slope = df["OBV"].iloc[-1] - df["OBV"].iloc[-6]

    result = {
        "close": round(float(last["Close"]), 4),
        "trend": {
            "ema20": round(float(last["EMA20"]), 4) if not pd.isna(last["EMA20"]) else None,
            "ema50": round(float(last["EMA50"]), 4) if not pd.isna(last["EMA50"]) else None,
            "ema200": round(float(last["EMA200"]), 4) if not pd.isna(last["EMA200"]) else None,
            "adx14": round(float(last["ADX14"]), 2) if not pd.isna(last["ADX14"]) else None,
            "price_above_ema50": bool(last["Close"] > last["EMA50"]) if not pd.isna(last["EMA50"]) else None,
            "ema50_above_ema200": bool(last["EMA50"] > last["EMA200"]) if not pd.isna(last["EMA200"]) else None,
        },
        "momentum": {
            "rsi14": round(float(last["RSI14"]), 2) if not pd.isna(last["RSI14"]) else None,
            "macd": round(float(last["MACD"]), 4) if not pd.isna(last["MACD"]) else None,
            "macd_signal": round(float(last["MACD_SIGNAL"]), 4) if not pd.isna(last["MACD_SIGNAL"]) else None,
            "macd_hist": round(float(last["MACD_HIST"]), 4) if not pd.isna(last["MACD_HIST"]) else None,
            "macd_hist_prev": round(float(prev["MACD_HIST"]), 4) if not pd.isna(prev["MACD_HIST"]) else None,
            "bearish_rsi_divergence": bearish_div,
        },
        "volatility": {
            "atr14": round(float(last["ATR14"]), 4) if not pd.isna(last["ATR14"]) else None,
            "bb_upper": round(float(last["BB_UPPER"]), 4) if not pd.isna(last["BB_UPPER"]) else None,
            "bb_lower": round(float(last["BB_LOWER"]), 4) if not pd.isna(last["BB_LOWER"]) else None,
            "bb_width_pct": round(float(last["BB_WIDTH"]) * 100, 2) if not pd.isna(last["BB_WIDTH"]) else None,
        },
        "volume": {
            "current": int(last["Volume"]),
            "avg20": int(last["VOL_AVG20"]) if not pd.isna(last["VOL_AVG20"]) else None,
            "above_avg": bool(last["Volume"] > last["VOL_AVG20"]) if not pd.isna(last["VOL_AVG20"]) else None,
            "obv_rising": bool(obv_slope > 0) if not pd.isna(obv_slope) else None,
        },
    }
    return result


def rule_based_prefilter(indicators: dict) -> dict:
    """Kullanılmıyor olabilir ama geriye dönük uyumluluk için tutuldu."""
    if indicators is None:
        return {"score": 0, "direction": "neutral", "reasons": ["yetersiz veri"]}

    score = 0
    reasons = []
    t, m, v = indicators["trend"], indicators["momentum"], indicators["volume"]

    if t.get("price_above_ema50") and t.get("ema50_above_ema200"):
        score += 2
        reasons.append("trend_uyumu_yukselis")
    if t.get("adx14") and t["adx14"] > 20:
        score += 1
        reasons.append("trend_gucu_var")
    if m.get("rsi14") and 40 <= m["rsi14"] <= 65:
        score += 1
        reasons.append("rsi_saglikli_bolge")
    if m.get("macd_hist") is not None and m.get("macd_hist_prev") is not None:
        if m["macd_hist"] > 0 and m["macd_hist"] > m["macd_hist_prev"]:
            score += 1
            reasons.append("macd_momentum_artiyor")
    if v.get("above_avg"):
        score += 1
        reasons.append("hacim_ortalamanin_uzerinde")
    if m.get("bearish_rsi_divergence"):
        score -= 2
        reasons.append("negatif_rsi_uyumsuzlugu")

    direction = "bullish" if score >= 3 else ("bearish" if score <= -1 else "neutral")
    return {"score": score, "direction": direction, "reasons": reasons}
