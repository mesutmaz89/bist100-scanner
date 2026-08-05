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


def check_index_trend(index_df) -> bool:
    """
    BIST100 (XU100) endeksinin yükseliş trendinde olup olmadığını kontrol eder.
    Endeks fiyatı EMA50 üzerindeyse True döner.
    """
    if index_df is None or index_df.empty or len(index_df) < 50:
        return True  # Veri yoksa filtreyi pas geç
    
    close = float(index_df["Close"].iloc[-1])
    ema50 = float(index_df["EMA_50"].iloc[-1]) if "EMA_50" in index_df.columns else float(index_df["Close"].ewm(span=50).mean().iloc[-1])
    
    return close >= ema50


def build_signal(ticker: str, indicators: dict, index_uptrend: bool = True) -> dict:
    """Tek bir hisse için tam sinyal üretir (entry/stop/hedef dahil)."""
    if indicators is None:
        return {"ticker": ticker, "direction": "none", "reasoning": "veri yok"}

    # Piyasa geneli düşüş trendindeyse yeni alım sinyali üretme
    if not index_uptrend:
        return {
            "ticker": ticker,
            "direction": "none",
            "reasoning": "BIST100 endeksi düşüş trendinde (EMA50 altı) - Risk Filtresi Aktif",
        }

    t, m, v = indicators["trend"], indicators["momentum"], indicators["volume"]
    close = indicators["close"]
    atr = indicators["volatility"].get("atr14")

    reasons = []

    # --- LONG puanlama ---
    long_score = 0
    if t.get("price_above_ema50") and t.get("ema50_above_ema200"):
        long_score += 2
        reasons.append("trend yukarı (EMA50>EMA200)")
    
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
    # NOT: Backtest sonuçlarına göre (1y ve 2y, fixed_tp) SHORT sinyalleri sürekli
    # negatif beklenti üretiyor (-0.11R ile -0.16R arası) ve LONG'un beklentisini
    # aşağı çekiyor. Bu yüzden SHORT sinyal üretimi devre dışı bırakıldı.
    # short_score hâlâ hesaplanıyor (ileride yeniden değerlendirilebilir/loglanabilir)
    # ama build_signal artık asla "short" döndürmüyor.
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

    if long_score >= 4:
        direction = "long"
        score = long_score
        entry = close
        # Backtest'te doğrulanan sabit hedef/stop oranı (fixed_tp, trailing DEĞİL):
        # Stop: 1.2 ATR / Hedef: 2.5 ATR -> ~2.08:1 R/R, backtest'te +0.21/+0.25R
        # beklenti verdi (2y, LONG-only, fixed_tp senaryosu)
        stop_loss = round(entry - 1.2 * atr, 4) if atr else None
        take_profit = round(entry + 2.5 * atr, 4) if atr else None
    else:
        return {
            "ticker": ticker,
            "direction": "none",
            "reasoning": "net kurulum yok (skor eşiği altında) veya SHORT filtrelendi",
            "short_score_debug": short_score,
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
        "atr": atr
    }
