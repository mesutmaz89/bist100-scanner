"""
backtest.py
Decision Engine + Trailing Stop + BIST100 Endeks Filtresini BIST hisselerinde simüle eder.

Parametreleri dışarıdan vererek farklı çıkış senaryolarını karşılaştırabilirsin:
  python scripts/backtest.py --trail-trigger 1.0 --trail-dist 1.0
  python scripts/backtest.py --trail-trigger 1.8 --trail-dist 1.5
  python scripts/backtest.py --period 2y

GitHub Actions'tan (workflow_dispatch inputs) da aynı parametreler geçilebilir.
"""

import os
import sys
import json
import logging
import argparse
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
    """indicators.add_indicator_columns() tarafından eklenen GERÇEK kolonları okur."""
    if len(sub_df) < 2:
        return None

    row = sub_df.iloc[-1]
    prev_row = sub_df.iloc[-2]

    if pd.isna(row.get("EMA50")) or pd.isna(row.get("ATR14")):
        return None

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


def run_backtest(period="1y", trail_trigger_atr=1.0, trail_dist_atr=1.0, exit_mode="trailing"):
    """
    trail_trigger_atr: kaç ATR kâra ulaşınca trailing stop devreye girsin
    trail_dist_atr   : trailing stop, zirveden kaç ATR geride tutulsun
    exit_mode        : "trailing" (varsayılan) veya "fixed_tp"
                        (fixed_tp: decision_engine'in take_profit seviyesinde sabit çıkış,
                         trailing hiç kullanılmaz — hangi çıkış tarzının daha iyi
                         beklenti verdiğini karşılaştırmak için)
    """
    logger.info(f"Parametreler: period={period}, trail_trigger={trail_trigger_atr}ATR, "
                f"trail_dist={trail_dist_atr}ATR, exit_mode={exit_mode}")

    logger.info("BIST100 (XU100) endeks verisi indiriliyor...")
    index_df = yf.download("XU100.IS", period=period, interval="1d", progress=False)
    if not index_df.empty:
        if isinstance(index_df.columns, pd.MultiIndex):
            index_df.columns = index_df.columns.get_level_values(0)
        index_df["EMA_50"] = index_df["Close"].ewm(span=50).mean()

    tickers = load_watchlist()
    logger.info(f"{len(tickers)} hisse için {period} süresince backtest başlatılıyor...")

    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    r_multiples = []
    r_by_direction = {"long": [], "short": []}
    RISK_PER_TRADE_PCT = 1.0
    equity = 100.0

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
            initial_risk = 0.0
            extreme_price = 0.0
            atr_val = 0.0
            direction = None

            for i in range(35, len(df)):
                sub_df = df.iloc[:i + 1]
                current_bar = df.iloc[i]
                current_high = float(current_bar["High"])
                current_low = float(current_bar["Low"])
                current_close = float(current_bar["Close"])

                index_sub = index_df.iloc[:i + 1] if not index_df.empty and i < len(index_df) else None
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
                            take_profit = sig.get("take_profit", 0.0)
                            initial_risk = abs(entry_price - stop_loss) or (entry_price * 0.01)
                            extreme_price = current_high if direction == "long" else current_low
                            atr_val = sig.get("atr", entry_price * 0.02)
                else:
                    trade_closed = False
                    exit_price = None

                    if direction == "long":
                        if exit_mode == "fixed_tp":
                            if current_high >= take_profit:
                                exit_price = take_profit
                                trade_closed = True
                            elif current_low <= stop_loss:
                                exit_price = stop_loss
                                trade_closed = True
                        else:  # trailing
                            if current_high > extreme_price:
                                extreme_price = current_high
                                if (extreme_price - entry_price) >= (trail_trigger_atr * atr_val):
                                    candidate_stop = extreme_price - (trail_dist_atr * atr_val)
                                    if candidate_stop > stop_loss:
                                        stop_loss = candidate_stop
                            if current_low <= stop_loss:
                                exit_price = stop_loss
                                trade_closed = True

                    elif direction == "short":
                        if exit_mode == "fixed_tp":
                            if current_low <= take_profit:
                                exit_price = take_profit
                                trade_closed = True
                            elif current_high >= stop_loss:
                                exit_price = stop_loss
                                trade_closed = True
                        else:  # trailing
                            if current_low < extreme_price:
                                extreme_price = current_low
                                if (entry_price - extreme_price) >= (trail_trigger_atr * atr_val):
                                    candidate_stop = extreme_price + (trail_dist_atr * atr_val)
                                    if candidate_stop < stop_loss:
                                        stop_loss = candidate_stop
                            if current_high >= stop_loss:
                                exit_price = stop_loss
                                trade_closed = True

                    if trade_closed:
                        if direction == "long":
                            r = (exit_price - entry_price) / initial_risk
                        else:
                            r = (entry_price - exit_price) / initial_risk

                        r_multiples.append(r)
                        r_by_direction[direction].append(r)
                        total_trades += 1
                        if r > 0:
                            winning_trades += 1
                        else:
                            losing_trades += 1

                        equity *= (1 + (RISK_PER_TRADE_PCT / 100) * r)
                        in_position = False

        except Exception as e:
            logger.error(f"{ticker} hatası: {e}")

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0
    avg_win_r = sum(r for r in r_multiples if r > 0) / winning_trades if winning_trades else 0.0
    avg_loss_r = sum(r for r in r_multiples if r <= 0) / losing_trades if losing_trades else 0.0
    equity_return_pct = equity - 100.0

    def _dir_stats(rs):
        if not rs:
            return "işlem yok"
        wins = [r for r in rs if r > 0]
        wr = len(wins) / len(rs) * 100
        return f"{len(rs)} işlem, WinRate %{wr:.1f}, Beklenti {sum(rs)/len(rs):+.2f}R"

    print("\n" + "=" * 50)
    print(f" 📊 BACKTEST SONUÇLARI  [exit_mode={exit_mode}, "
          f"trigger={trail_trigger_atr}ATR, dist={trail_dist_atr}ATR, period={period}]")
    print("=" * 50)
    print(f" Toplam Açılan İşlem   : {total_trades}")
    print(f" Başarılı İşlemler     : {winning_trades}")
    print(f" Başarısız İşlemler    : {losing_trades}")
    print(f" Başarı Oranı (WinRate): %{win_rate:.2f}")
    print(f" Ortalama Kazanç (R)   : {avg_win_r:+.2f}R")
    print(f" Ortalama Kayıp (R)    : {avg_loss_r:+.2f}R")
    print(f" Beklenti (Expectancy) : {avg_r:+.2f}R / işlem")
    print(f" Bileşik Getiri (%{RISK_PER_TRADE_PCT} risk/işlem): %{equity_return_pct:+.2f}")
    print("-" * 50)
    print(f" LONG  : {_dir_stats(r_by_direction['long'])}")
    print(f" SHORT : {_dir_stats(r_by_direction['short'])}")
    print("=" * 50)
    print(" Not: 'Beklenti' negatifse, kazanma oranı yüksek olsa bile strateji")
    print(" ortalamada para kaybettiriyor demektir (kayıplar kazançlardan büyük).")
    print("=" * 50 + "\n")

    return {
        "total_trades": total_trades, "win_rate": win_rate,
        "avg_win_r": avg_win_r, "avg_loss_r": avg_loss_r,
        "expectancy": avg_r, "equity_return_pct": equity_return_pct,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="1y")
    parser.add_argument("--trail-trigger", type=float, default=1.0,
                         help="Kaç ATR kârda trailing stop devreye girsin")
    parser.add_argument("--trail-dist", type=float, default=1.0,
                         help="Trailing stop zirveden kaç ATR geride tutulsun")
    parser.add_argument("--exit-mode", choices=["trailing", "fixed_tp"], default="trailing")
    args = parser.parse_args()

    run_backtest(
        period=args.period,
        trail_trigger_atr=args.trail_trigger,
        trail_dist_atr=args.trail_dist,
        exit_mode=args.exit_mode,
    )
