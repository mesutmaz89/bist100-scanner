"""
backtest.py
Decision Engine + Trailing Stop + BIST100 Endeks Filtresini BIST hisselerinde simüle eder.
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
    """indicators.py ile AYNI hesaplama mantığını kullanır (add_indicator_columns)."""
    return indicators.add_indicator_columns(df)


def parse_row_to_indicators_dict(sub_df):
    """
    indicators.add_indicator_columns() tarafından eklenen GERÇEK kolonları okur.
    (Önceden pandas_ta stili kolon isimleri aranıyordu ve hiçbiri eşleşmiyordu;
    bu yüzden backtest sabit varsayılan değerlerle çalışıyordu. Artık düzeltildi.)
    """
    if len(sub_df) < 2:
        return None

    row = sub_df.iloc[-1]
    prev_row = sub_df.iloc[-2]

    if pd.isna(row.get("EMA50")) or pd.isna(row.get("ATR14")):
        return None  # yeterli geçmiş yok, bu barı atla

    close = float(row["Close"])
    ema50 = float(row["EMA50"])
    ema200 = float(row["EMA200"]) if not pd.isna(row["EMA200"]) else ema50
    adx14 = float(row["ADX14"]) if not pd.isna(row["ADX14"]) else 0.0
    rsi14 = float(row["RSI14"]) if not pd.isna(row["RSI14"]) else 50.0

    macd_hist = float(row["MACD_HIST"]) if not pd.isna(row["MACD_HIST"]) else 0.0
    macd_hist_prev = float(prev_row["MACD_HIST"]) if not pd.isna(prev_row["MACD_HIST"]) else 0.0

    volume = float(row["Volume"])
    vol_sma = float(row["VOL_AVG20"]) if not pd.isna(row["VOL_AVG20"]) else volume
    obv = float(row["OBV"])
    obv_prev = float(prev_row["OBV"])

    atr14 = float(row["ATR14"])

    lookback = sub_df.iloc[-10:]
    bearish_div = bool(
        len(lookback) >= 10
        and not lookback["RSI14"].isna().all()
        and close >= lookback["Close"].max() * 0.999
        and rsi14 < lookback["RSI14"].max() - 3
    )

    return {
        "close": close,
        "trend": {
            "price_above_ema50": close > ema50,
            "ema50_above_ema200": ema50 > ema200,
            "adx14": adx14
        },
        "momentum": {
            "rsi14": rsi14,
            "macd_hist": macd_hist,
            "macd_hist_prev": macd_hist_prev,
            "bearish_rsi_divergence": bearish_div
        },
        "volume": {
            "above_avg": volume > vol_sma,
            "obv_rising": obv > obv_prev
        },
        "volatility": {
            "atr14": atr14
        }
    }


def load_watchlist():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "watchlist.json")
    raw_tickers = []
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            raw_tickers = json.load(f).get("tickers", [])
    if not raw_tickers:
        raw_tickers = ["THYAO.IS", "GARAN.IS", "ASELS.IS", "EREGL.IS", "AKBNK.IS"]
    
    formatted_tickers = []
    for t in raw_tickers:
        t = t.strip().upper()
        if not t.endswith(".IS"):
            t += ".IS"
        formatted_tickers.append(t)
    return formatted_tickers


def run_backtest(period="1y"):
    # 1. BIST100 Endeks verisini indir ve hazırla
    logger.info("BIST100 (XU100) endeks verisi indiriliyor...")
    index_df = yf.download("XU100.IS", period=period, interval="1d", progress=False)
    if not index_df.empty:
        if isinstance(index_df.columns, pd.MultiIndex):
            index_df.columns = index_df.columns.get_level_values(0)
        index_df["EMA_50"] = index_df["Close"].ewm(span=50).mean()

    tickers = load_watchlist()
    logger.info(f"{len(tickers)} hisse için {period} süresince Trailing Stop backtest'i başlatılıyor...")

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
            highest_price = 0.0
            atr_val = 0.0
            direction = None

            for i in range(35, len(df)):
                sub_df = df.iloc[:i+1]
                current_bar = df.iloc[i]
                current_high = float(current_bar["High"])
                current_low = float(current_bar["Low"])
                current_close = float(current_bar["Close"])

                # O güne denk gelen endeks durumunu kontrol et
                index_sub = index_df.iloc[:i+1] if not index_df.empty and i < len(index_df) else None
                index_uptrend = decision_engine.check_index_trend(index_sub) if index_sub is not None else True

                if not in_position:
                    ind_dict = parse_row_to_indicators_dict(sub_df)
                    if ind_dict:
                        sig = decision_engine.build_signal(ticker, ind_dict, index_uptrend=index_uptrend)
                        if sig and sig.get("direction") in ["long", "short"]:
                            in_position = True
                            direction = sig["direction"]
                            entry_price = sig.get("entry", current_close)
                            stop_loss = sig.get("stop_loss", 0.0)
                            highest_price = current_high
                            atr_val = sig.get("atr", entry_price * 0.02)
                else:
                    trade_closed = False
                    profit_pct = 0.0

                    if direction == "long":
                        # Zirve fiyatı güncelle
                        if current_high > highest_price:
                            highest_price = current_high
                            
                            # TRailing STOP GÜNCELLEME: Fiyat tepe yaptıkça stop'u yukarı çek
                            # +1.0 ATR kâra ulaşınca stop'u giriş fiyatına (başabaş) getir
                            if (highest_price - entry_price) >= (1.0 * atr_val):
                                candidate_stop = highest_price - (1.0 * atr_val)
                                if candidate_stop > stop_loss:
                                    stop_loss = candidate_stop

                        # Stop Kontrolü
                        if current_low <= stop_loss:
                            profit_pct = ((stop_loss - entry_price) / entry_price) * 100
                            trade_closed = True
                            if profit_pct > 0:
                                winning_trades += 1
                            else:
                                losing_trades += 1

                    if trade_closed:
                        total_trades += 1
                        total_return_pct += profit_pct
                        in_position = False

        except Exception as e:
            logger.error(f"{ticker} hatası: {e}")

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    print("\n" + "="*45)
    print(" 📊 BACKTEST SONUÇLARI (TRAILING STOP & ENDEKS FİLTRESİ)")
    print("="*45)
    print(f" Toplam Açılan İşlem  : {total_trades}")
    print(f" Başarılı İşlemler    : {winning_trades}")
    print(f" Başarısız İşlemler   : {losing_trades}")
    print(f" Başarı Oranı (WinRate): %{win_rate:.2f}")
    print(f" Kümülatif Getiri     : %{total_return_pct:.2f}")
    print("="*45 + "\n")


if __name__ == "__main__":
    run_backtest()
