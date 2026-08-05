"""
portfolio_tracker.py
Firestore üzerindeki canlı kullanıcı pozisyonlarını okur,
ATR Trailing Stop, Kademeli Kar Satışı ve Ekleme uyarılarını hesaplayarak yazar.
"""

import os
import logging
import pandas as pd
import yfinance as yf
import firebase_admin
from firebase_admin import credentials, firestore
import indicators

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("portfolio_tracker")

# Firebase Başlatma
def init_firestore():
    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firestore.client()


def get_open_positions(db):
    """Firestore'dan aktif açık pozisyonları çeker."""
    docs = db.collection("user_positions").where("status", "==", "OPEN").stream()
    positions = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        positions.append(data)
    return positions


def evaluate_position(position):
    raw_ticker = position["ticker"]
    ticker = raw_ticker if raw_ticker.endswith(".IS") else f"{raw_ticker}.IS"
    entry_price = float(position["entry_price"])
    qty = float(position.get("quantity", 0))

    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 20:
            return None

        # MultiIndex sütun yapısını temizle
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # indicators.py ile AYNI hesaplama mantığı (main.py ve backtest.py ile tutarlı)
        df = indicators.add_indicator_columns(df)

        close_series = df["Close"].squeeze()
        high_series = df["High"].squeeze()

        current_close = float(close_series.iloc[-1])
        recent_max_high = float(high_series.tail(10).max())

        last = df.iloc[-1]
        atr14 = float(last["ATR14"]) if not pd.isna(last["ATR14"]) else float(current_close * 0.02)
        ema20 = float(last["EMA20"]) if not pd.isna(last["EMA20"]) else float(close_series.ewm(span=20).mean().iloc[-1])
        rsi14 = float(last["RSI14"]) if not pd.isna(last["RSI14"]) else 50.0

        pnl_pct = ((current_close - entry_price) / entry_price) * 100
        pnl_amount = (current_close - entry_price) * qty
        trailing_stop_price = round(recent_max_high - (1.2 * atr14), 2)

        action = "HOLD"
        alert_level = "INFO"
        reasoning = "Pozisyon sağlıklı, trend devam ediyor."

        if current_close <= trailing_stop_price or current_close <= (entry_price - 1.2 * atr14):
            action = "EXIT_ALL"
            alert_level = "HIGH"
            reasoning = f"Fiyat Trailing Stop seviyesine ({trailing_stop_price} TL) geriledi. Pozisyondan çık!"
        elif current_close >= (entry_price + 1.8 * atr14):
            action = "TAKE_PROFIT_HALF"
            alert_level = "MEDIUM"
            reasoning = f"Hisse +1.8 ATR kâra ulaştı (%{pnl_pct:.1f}). %50 kâr satışı yap."
        elif entry_price <= current_close <= (entry_price + 0.5 * atr14) and abs(current_close - ema20) / ema20 < 0.015 and rsi14 < 55:
            action = "BUY_MORE"
            alert_level = "MEDIUM"
            reasoning = "Hisse trend desteğinde. Kademeli ekleme yapılabilir."

        return {
            "position_id": position["id"],
            "ticker": ticker,
            "entry_price": entry_price,
            "current_price": round(current_close, 2),
            "quantity": qty,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
            "action": action,
            "alert_level": alert_level,
            "trailing_stop_price": trailing_stop_price,
            "reasoning": reasoning,
            "updated_at": firestore.SERVER_TIMESTAMP
        }
    except Exception as e:
        logger.error(f"{ticker} analiz hatası: {e}")
        return None


def run_tracker():
    try:
        db = init_firestore()
        positions = get_open_positions(db)
        logger.info(f"{len(positions)} aktif pozisyon taranıyor...")

        for pos in positions:
            res = evaluate_position(pos)
            if res:
                db.collection("portfolio_alerts").document(pos["id"]).set(res)
                logger.info(f"Güncellendi: {res['ticker']} -> {res['action']}")

    except Exception as e:
        logger.error(f"Tracker hatası: {e}")


if __name__ == "__main__":
    run_tracker()
