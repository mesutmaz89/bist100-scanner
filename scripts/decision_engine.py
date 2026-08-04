"""
decision_engine.py
Claude API kullanmadan, tamamen deterministik kural motoruyla sinyal üretir.
Girdi: indicators.py çıktısı. Çıktı: firestore_writer'ın beklediği sinyal formatı.
"""


def _confidence_from_score(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def build_signal(ticker: str, indicators: dict) -> dict:
    """Tek bir hisse için tam sinyal üretir (entry/stop/hedef dahil)."""
    if indicators is None:
        return {"ticker": ticker, "direction": "none", "reasoning": "veri yok"}

    t, m, v = indicators["trend"], indicators["momentum"], indicators["volume"]
    close = indicators["close"]
    atr = indicators["volatility"].get("atr14")

    reasons = []

    # --- LONG puanlama ---
    long_score = 0
    if t.get("price_above_ema50") and t.get("ema50_above_ema200"):
        long_score += 2
        reasons.append("trend yukarı (EMA50>EMA200)")
    
    # ADX Eşiği 20'den 25'e çıkarıldı (Yatay piyasaları elemek için)
    if t.get("adx14") and t["adx14"] >= 25:
        long_score += 1
        reasons.append("ADX>=25 (güçlü trend)")
        
    if m.get("rsi14") and 42 <= m["rsi14"] <= 62:
        long_score += 1
        reasons.append("RSI ideal bölgede")
        
    if m.get("macd_hist") is not None and m.get("macd_hist_prev") is not None:
        if m["macd_hist"] > 0 and m["macd_hist"] > m["macd_hist_prev"]:
            long_score += 1
            reasons.append("MACD momentum artıyor")
            
    if v.get("above_avg"):
        long_score += 1
        reasons.append("hacim ortalama üstü")
        
    if v.get("obv_rising"):
        long_score += 1
        reasons.append("OBV yükseliyor")
        
    if m.get("bearish_rsi_divergence"):
        long_score -= 2
        reasons.append("negatif RSI uyumsuzluğu (risk)")

    # --- SHORT puanlama ---
    short_score = 0
    if t.get("price_above_ema50") is False and t.get("ema50_above_ema200") is False:
        short_score += 2
    if t.get("adx14") and t["adx14"] >= 25 and long_score < 2:
        short_score += 1
    if m.get("rsi14") and m["rsi14"] > 68:
        short_score += 1
    if m.get("macd_hist") is not None and m["macd_hist"] < 0:
        short_score += 1
    if v.get("above_avg") and long_score < 2:
        short_score += 1

    # Skor eşiği 3 yerine 4 yapıldı (daha kaliteli kurulumlar)
    if long_score >= 4 and long_score >= short_score:
        direction = "long"
        score = long_score
        entry = close
        # R/R oranı 1.0 ATR Stop / 2.0 ATR Hedef olarak optimize edildi
        stop_loss = round(entry - 1.0 * atr, 4) if atr else None
        take_profit = round(entry + 2.0 * atr, 4) if atr else None
    elif short_score >= 4 and short_score > long_score:
        direction = "short"
        score = short_score
        entry = close
        stop_loss = round(entry + 1.0 * atr, 4) if atr else None
        take_profit = round(entry - 2.0 * atr, 4) if atr else None
    else:
        return {
            "ticker": ticker,
            "direction": "none",
            "reasoning": "net kurulum yok (yüksek kalite skor eşiği altında)",
        }

    risk = abs(entry - stop_loss) if stop_loss else None
    reward = abs(take_profit - entry) if take_profit else None
    risk_reward = round(reward / risk, 2) if risk and reward and risk > 0 else None

    return {
        "ticker": ticker,
        "direction": direction,
        "entry": round(entry, 4),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
        "confidence": _confidence_from_score(score),
        "reasoning": ", ".join(reasons) if reasons else "seçici kural bazlı skor geçildi",
        "score": score,
    }


def build_all_signals(all_indicators: dict) -> list[dict]:
    return [build_signal(ticker, ind) for ticker, ind in all_indicators.items()]
