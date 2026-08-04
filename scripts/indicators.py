"""
indicators.py
OHLCV verisinden teknik göstergeleri hesaplar.
Girdi: pandas DataFrame (columns: Open, High, Low, Close, Volume)
Çıktı: göstergelerin son değerlerini içeren dict
"""

import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator


def compute_indicators(df: pd.DataFrame) -> dict:
    """
    df: en az 210 barlık günlük OHLCV verisi (EMA200 için yeterli geçmiş gerekir)
    Dönen dict: Özet göstergeler
    """
    if df is None or len(df) < 60:
        return None

    df = df.copy()
    df.columns = [c.capitalize() for c in df.columns]

    # --- Trend ---
    df["EMA20"] = EMAIndicator(close=df["Close"], window=20).ema_indicator()
    df["EMA50"] = EMAIndicator(close=df["Close"], window=50).ema_indicator()
    df["EMA200"] = EMAIndicator(close=df["Close"], window=200).ema_indicator() if len(df) >= 200 else np.nan

    adx_ind = ADXIndicator(high=df["High"], low=df["Low"], close=df["Close"], window=14)
    df["ADX14"] = adx_ind.adx()

    # --- Momentum ---
    df["RSI14"] = RSIIndicator(close=df["Close"], window=14).rsi()
    
    macd_ind = MACD(close=df["Close"], window_slow=26, window_fast=12, window_sign=9)
    df["MACD"] = macd_ind.macd()
    df["MACD_SIGNAL"] = macd_ind.macd_signal()
    df["MACD_HIST"] = macd_ind.macd_diff()

    # --- Volatilite ---
    df["ATR14"] = AverageTrueRange(high=df["High"], low=df["Low"], close=df["Close"], window=14).average_true_range()
    
    bb_ind = BollingerBands(close=df["Close"], window=20, window_dev=2)
    df["BB_UPPER"] = bb_ind.bollinger_hband()
    df["BB_LOWER"] = bb_ind.bollinger_lband()
    df["BB_WIDTH"] = (df["BB_UPPER"] - df["BB_LOWER"]) / df["Close"]

    # --- Hacim ---
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["OBV"] = OnBalanceVolumeIndicator(close=df["Close"], volume=df["Volume"]).on_balance_volume()
    
    obv_slope = np.nan
    if len(df) >= 6:
        obv_slope = df["OBV"].iloc[-1] - df["OBV"].iloc[-6]

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # RSI divergence (basit kontrol: son 10 barda fiyat yeni yüksek yaptı ama RSI yapmadı)
    lookback = df.iloc[-10:]
    bearish_div = (
        last["Close"] >= lookback["Close"].max() * 0.999
        and last["RSI14"] < lookback["RSI14"].max() - 3
    )

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
            "bearish_rsi_divergence": bool(bearish_div),
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
    """
    Claude'a göndermeden önce ucuz/hızlı bir ön filtre.
    Sadece 'ilgi çekici' adayları Claude'a gönderip maliyeti düşürmek için kullanılır.
    Dönen: {"score": int, "direction": "bullish"/"bearish"/"neutral", "reasons": [...]}
    """
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
