"""
main.py — ÜCRETSİZ SÜRÜM (Claude API yok)
Uçtan uca akış:
  1. XU100 (BIST100 endeksi) verisini çek, genel piyasa trendini belirle
  2. Watchlist'i oku
  3. Her hisse için OHLCV çek (YKB -> Yahoo fallback) — ücretsiz
  4. Teknik göstergeleri hesapla — ücretsiz
  5. Kural-bazlı karar motoruyla sinyal üret (endeks filtresi dahil) — ücretsiz
  6. Firestore'a yaz — ücretsiz
  7. confidence=high ve yeni olan sinyaller için FCM push gönder — ücretsiz

Kullanım (GitHub Actions içinden):
  python scripts/main.py
"""

import os
import sys
import json
import logging
import pandas as pd
import yfinance as yf

sys.path.append(os.path.dirname(__file__))

from data_fetcher import fetch_all
from indicators import compute_indicators
from decision_engine import build_signal, check_index_trend
from firestore_writer import write_signals, resolve_open_signals, cleanup_stale_signals
from fcm_notifier import notify_new_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("main")

WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "watchlist.json")


def load_watchlist() -> list[str]:
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["tickers"]


def fetch_index_trend() -> bool:
    """BIST100 (XU100) endeksinin genel trendini kontrol eder (EMA50 üstü mü)."""
    try:
        index_df = yf.download("XU100.IS", period="250d", interval="1d", progress=False)
        if index_df.empty:
            logger.warning("XU100 verisi alınamadı, endeks filtresi pas geçiliyor.")
            return True
        if isinstance(index_df.columns, pd.MultiIndex):
            index_df.columns = index_df.columns.get_level_values(0)
        index_df["EMA_50"] = index_df["Close"].ewm(span=50, adjust=False).mean()
        uptrend = check_index_trend(index_df)
        logger.info(f"XU100 genel trend: {'YÜKSELIŞ' if uptrend else 'DÜŞÜŞ'} (EMA50 referansı)")
        return uptrend
    except Exception as e:
        logger.warning(f"XU100 kontrolü başarısız ({e}), endeks filtresi pas geçiliyor.")
        return True


def run():
    index_uptrend = fetch_index_trend()

    tickers = load_watchlist()
    logger.info(f"Watchlist yüklendi: {len(tickers)} hisse")

    raw_data = fetch_all(tickers)

    all_indicators = {}
    for ticker, df in raw_data.items():
        ind = compute_indicators(df)
        if ind is not None:
            all_indicators[ticker] = ind
    logger.info(f"{len(all_indicators)} hisse için gösterge hesaplandı")

    signals = [
        build_signal(ticker, ind, index_uptrend=index_uptrend)
        for ticker, ind in all_indicators.items()
    ]
    active_signals = [s for s in signals if s.get("direction") != "none"]
    logger.info(f"{len(active_signals)} aktif sinyal üretildi (toplam {len(signals)} hisse tarandı)")

    # Açık geçmiş sinyalleri bugünün kapanış fiyatlarına göre çözümle (hedef/stop kontrolü)
    current_closes = {ticker: ind["close"] for ticker, ind in all_indicators.items()}
    resolve_open_signals(current_closes)

    # Artık geçerli olmayan sinyalleri temizle (skor düştü VEYA eski SHORT kalıntısı)
    # -- bu, yeni aktif sinyal olmasa bile HER ZAMAN çalışmalı
    cleanup_stale_signals(
        all_scanned_tickers=list(all_indicators.keys()),
        active_tickers=[s["ticker"] for s in active_signals],
    )

    if not active_signals:
        logger.info("Yeni aktif sinyal yok, çıkılıyor.")
        return

    notify_new_signals(active_signals)
    write_signals(active_signals)

    logger.info("Çalıştırma tamamlandı.")


if __name__ == "__main__":
    run()
