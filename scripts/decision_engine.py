"""
decision_engine.py
Claude API kullanmadan, tamamen deterministik kural motoruyla sinyal üretir.
Girdi: indicators.py çıktısı. Çıktı: firestore_writer'ın beklediği sinyal formatı.

Mantık özeti:
  LONG  = trend yukarı (EMA50>EMA200, fiyat>EMA50) + ADX>20 (trend güçlü)
          + RSI 40-65 (aşırı alımda değil) + MACD histogram artıyor + hacim ortalama üstü
  SHORT = tersi (trend aşağı + momentum negatif + hacim teyidi)
  Stop/Hedef: ATR14 bazlı (fiyat aksiyonuna göre otomatik ölçeklenir)
"""


def _confidence_from_score(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def build_signal(ticker: str, indicators: dict) -> dict:
    """Tek bir hisse için tam sinyal üretir (entry/stop/hedef dahil)."""
    if indicators is None:
        return {"ticker": ticker, "direction": "none", "reasoning": "veri yok"}

    t, m, v = indicators["trend"], indicators["momentum"], indicators["volume"]
    close = indicators["close"]
    atr = indicators["volatility"].get("atr14")

    score = 0
    reasons = []

    # --- LONG puanlama ---
    long_score = 0
    if t.get("price_above_ema50") and t.get("ema50_above_ema200"):
        long_score += 2
        reasons.append("trend yukarı (EMA50>EMA200)")
    if t.get("adx14") and t["adx14"] > 20:
        long_score += 1
        reasons.append("ADX>20 trend güçlü")
    if m.get("rsi14") and 40 <= m["rsi14"] <= 65:
        long_score += 1
        reasons.append("RSI sağlıklı bölgede")
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

    # --- SHORT puanlama (basit ayna mantık) ---
    short_score = 0
    if t.get("price_above_ema50") is False and t.get("ema50_above_ema200") is False:
        short_score += 2
    if t.get("adx14") and t["adx14"] > 20 and long_score < 2:
        short_score += 1
    if m.get("rsi14") and m["rsi14"] > 70:
        short_score += 1
    if m.get("macd_hist") is not None and m["macd_hist"] < 0:
        short_score += 1
    if v.get("above_avg") and long_score < 2:
        short_score += 1

    if long_score >= 3 and long_score >= short_score:
        direction = "long"
        score = long_score
        entry = close
        stop_loss = round(entry - 1.5 * atr, 4) if atr else None
        take_profit = round(entry + 3.0 * atr, 4) if atr else None  # min 1:2 R/R
    elif short_score >= 3 and short_score > long_score:
        direction = "short"
        score = short_score
        entry = close
        stop_loss = round(entry + 1.5 * atr, 4) if atr else None
        take_profit = round(entry - 3.0 * atr, 4) if atr else None
    else:
        return {
            "ticker": ticker,
            "direction": "none",
            "reasoning": "net kurulum yok (skor eşiği altında)",
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
        "reasoning": ", ".join(reasons) if reasons else "kural bazlı skor eşiği geçildi",
        "score": score,
    }


def build_all_signals(all_indicators: dict) -> list[dict]:
    """all_indicators: {ticker: indicators_dict} -> sinyal listesi"""
    return [build_signal(ticker, ind) for ticker, ind in all_indicators.items()]
