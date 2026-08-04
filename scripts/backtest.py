"""
backtest.py
Decision Engine stratejisini BIST100 hisseleri üzerinde 1 yıllık geçmiş veriyle test eder.
"""

import os
import json
import logging
import pandas as pd
import yfinance as yf
import indicators
import decision_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("backtest")


def apply_indicators(df):
    """indicators.py modülünü dinamik olarak çağırır."""
    if hasattr(indicators, "add_all_indicators"):
        return indicators.add_all_indicators(df)
    elif hasattr(indicators, "calculate_indicators"):
        return indicators.calculate_indicators(df)
    elif hasattr(indicators, "add_indicators"):
        return indicators.add_indicators(df)
    else:
        if hasattr(indicators, "add_rsi"): df = indicators.add_rsi(df)
        if hasattr(indicators, "add_macd"): df = indicators.add_macd(df)
        if hasattr(indicators, "add_adx"): df = indicators.add_adx(df)
        if hasattr(indicators, "add_ema"): df = indicators.add_ema(df)
        if hasattr(indicators, "add_obv"): df = indicators.add_obv(df)
        return df


def run_decision_engine(df):
    """decision_engine.py içindeki analiz fonksiyonunu dinamik olarak bulur ve çalıştırır."""
    if hasattr(decision_engine, "evaluate_stock"):
        return decision_engine.evaluate_stock(df)
    elif hasattr(decision_engine, "evaluate"):
        return decision_engine.evaluate(df)
    elif hasattr(decision_engine, "analyze_stock"):
        return decision_engine.analyze_stock(df)
    elif hasattr(decision_engine, "analyze"):
        return decision_engine.analyze(df)
    elif hasattr(decision_engine, "generate_signal"):
        return decision_engine.generate_signal(df)
    return None


def load_watchlist():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "watchlist.json")
    raw_tickers = []
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            raw_tickers = json.load(f).get("tickers", [])
    if not raw_tickers:
        raw_tickers = ["THYAO.IS", "GARAN.IS", "ASELS.IS", "EREGL.IS", "AKBNK.IS"]
    
    # BIST sembollerinin sonuna .IS eklenmesini garantiye alıyoruz
    formatted_tickers = []
    for t in raw_tickers:
        t = t.strip().upper()
        if not t.endswith(".IS"):
            t += ".IS"
        formatted_tickers.append(t)
    return formatted_tickers


def run_backtest(period="1y"):
    tickers = load_watchlist()
    logger.info(f"{len(tickers)} hisse için {period} süresince backtest başlatılıyor...")

    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    total_return_pct = 0.0

    for ticker in tickers:
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False)
            if df.empty or len(df) < 50:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = apply_indicators(df)

            in_position = False
            entry_price = 0.0
            stop_loss = 0.0
            take_profit = 0.0
            direction = None

            for i in range(35, len(df)):
                sub_df = df.iloc[:i+1]
                current_bar = df.iloc[i]
                current_high = float(current_bar["High"])
                current_low = float(current_bar["Low"])

                if not in_position:
                    sig = run_decision_engine(sub_df)
                    if sig and sig.get("direction") in ["long", "short"]:
                        in_position = True
                        direction = sig["direction"]
                        entry_price = sig.get("entry", current_bar["Close"])
                        stop_loss = sig.get("stop_loss", 0.0)
                        take_profit = sig.get("take_profit", 0.0)
                else:
                    trade_closed = False
                    profit_pct = 0.0

                    if direction == "long":
                        if stop_loss > 0 and current_low <= stop_loss:
                            profit_pct = ((stop_loss - entry_price) / entry_price) * 100
                            trade_closed = True
                            losing_trades += 1
                        elif take_profit > 0 and current_high >= take_profit:
                            profit_pct = ((take_profit - entry_price) / entry_price) * 100
                            trade_closed = True
                            winning_trades += 1
                    elif direction == "short":
                        if stop_loss > 0 and current_high >= stop_loss:
                            profit_pct = ((entry_price - stop_loss) / entry_price) * 100
                            trade_closed = True
                            losing_trades += 1
                        elif take_profit > 0 and current_low <= take_profit:
                            profit_pct = ((entry_price - take_profit) / entry_price) * 100
                            trade_closed = True
                            winning_trades += 1

                    if trade_closed:
                        total_trades += 1
                        total_return_pct += profit_pct
                        in_position = False

        except Exception as e:
            logger.error(f"{ticker} hatası: {e}")

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    print("\n" + "="*45)
    print(" 📊 BACKTEST SONUÇLARI (1 YILLIK SIMÜLASYON)")
    print("="*45)
    print(f" Toplam Açılan İşlem  : {total_trades}")
    print(f" Başarılı İşlemler    : {winning_trades}")
    print(f" Başarısız İşlemler   : {losing_trades}")
    print(f" Başarı Oranı (WinRate): %{win_rate:.2f}")
    print(f" Kümülatif Getiri     : %{total_return_pct:.2f}")
    print("="*45 + "\n")


if __name__ == "__main__":
    run_backtest()
