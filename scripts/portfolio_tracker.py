"""
portfolio_tracker.py
Kullanıcının canlı/açık pozisyonlarını takip eder.
Dinamik ATR Trailing Stop, Kademeli Kar Satışı ve Ekleme uyarıları üretir.
"""

import os
import json
import logging
import pandas as pd
import yfinance as yf
import indicators

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("portfolio_tracker")


def load_portfolio():
    """Açık pozisyonları okur (Varsayılan olarak config/portfolio.json kullanır)."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "portfolio.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f).get("positions", [])
    
    # Dosya yoksa örnek pozisyonlar döner
    return [
        {"ticker": "THYAO.IS", "entry_price": 300.50, "quantity": 100, "entry_date": "2026-08-01"},
        {"ticker": "GARAN.IS", "entry_price": 115.00, "quantity": 250, "entry_date": "2026-08-02"}
    ]


def evaluate_position(position):
    """
    Tek bir pozisyon için canlı piyasa verisini analiz eder ve aksiyon uyarısı üretir.
    """
    raw_ticker = position["ticker"]
    ticker = raw_ticker if raw_ticker.endswith(".IS") else f"{raw_ticker}.IS"
    entry_price = float(position["entry_price"])
    qty = position.get("quantity", 0)

    try:
        df = yf.download(ticker, period="3m", interval="1d", progress=False)
        if df.empty or len(df) < 20:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Indikatörleri ekle
        if hasattr(indicators, "add_all_indicators"):
            df = indicators.add_all_indicators(df)

        current_close = float(df["Close"].iloc[-1])
        current_high = float(df["High"].iloc[-1])
        recent_max_high = float(df["High"].tail(10).max())
        
        atr14 = float(df.get("ATRr_14", df["Close"] * 0.02).iloc[-1])
        ema20 = float(df.get("EMA_20", df["Close"].ewm(span=20).mean()).iloc[-1])
        rsi14 = float(df.get("RSI_14", 50).iloc[-1])

        pnl_pct = ((current_close - entry_price) / entry_price) * 100
        pnl_amount = (current_close - entry_price) * qty

        # Trailing Stop Çizgisi: Zirveden 1.2 ATR aşağısı
        trailing_stop_price = round(recent_max_high - (1.2 * atr14), 2)

        action = "HOLD"  # Varsayılan: Pozisyonu koru
        alert_level = "INFO"
        reasoning = "Pozisyon sağlıklı, trend devam ediyor."

        # 1. 🔴 TRAILING STOP / TAM ÇIKIŞ UYARISI
        if current_close <= trailing_stop_price or current_close <= (entry_price - 1.2 * atr14):
            action = "EXIT_ALL"
            alert_level = "HIGH"
            reasoning = f"Fiyat Trailing Stop seviyesine ({trailing_stop_price} TL) geriledi. Pozisyondan tamamen çık!"

        # 2. 🟢 KADEMELİ KAR SATIŞI (PARTIAL TP)
        elif current_close >= (entry_price + 1.8 * atr14):
            action = "TAKE_PROFIT_HALF"
            alert_level = "MEDIUM"
            reasoning = f"Hisse +1.8 ATR kâra ulaştı (%{pnl_pct:.1f}). Pozisyonun %50'sini satıp kârı kilitle."

        # 3. 🔵 KADEMELİ EKLEME (DİP / DÜZELTME ALIMI)
        elif entry_price <= current_close <= (entry_price + 0.5 * atr14) and abs(current_close - ema20) / ema20 < 0.015 and rsi14 < 55:
            action = "BUY_MORE"
            alert_level = "MEDIUM"
            reasoning = "Hisse trend desteğine (EMA20) çekildi. Güçlü trendde kademeli ekleme yapılabilir."

        return {
            "ticker": ticker,
            "entry_price": entry_price,
            "current_price": round(current_close, 2),
            "quantity": qty,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
            "action": action,
            "alert_level": alert_level,
            "trailing_stop_price": trailing_stop_price,
            "reasoning": reasoning
        }

    except Exception as e:
        logger.error(f"{ticker} analiz edilirken hata: {e}")
        return None


def run_portfolio_tracker():
    positions = load_portfolio()
    logger.info(f"{len(positions)} adet açık pozisyon taranıyor...\n")

    print("="*65)
    print(" 📋 CANLI PORTFÖY VE DİNAMİK UYARI PANELİ")
    print("="*65)

    alerts = []
    for pos in positions:
        result = evaluate_position(pos)
        if result:
            alerts.append(result)
            icon = "🟢" if result["pnl_pct"] >= 0 else "🔴"
            print(f"{icon} {result['ticker']} | Alış: {result['entry_price']} TL | Güncel: {result['current_price']} TL")
            print(f"   Kâr/Zarar: %{result['pnl_pct']} ({result['pnl_amount']} TL)")
            print(f"   Aksiyon  : [{result['action']}] -> {result['reasoning']}")
            print(f"   Iz Süren Stop: {result['trailing_stop_price']} TL")
            print("-" * 65)

    return alerts


if __name__ == "__main__":
    run_portfolio_tracker()
