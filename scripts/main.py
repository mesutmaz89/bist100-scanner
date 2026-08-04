"""
main.py — ÜCRETSİZ SÜRÜM (Claude API yok)
Uçtan uca akış:
  1. Watchlist'i oku
  2. Her hisse için OHLCV çek (YKB -> Yahoo fallback) — ücretsiz
  3. Teknik göstergeleri hesapla — ücretsiz
  4. Kural-bazlı karar motoruyla sinyal üret (entry/stop/hedef/confidence) — ücretsiz
  5. Firestore'a yaz — ücretsiz (Spark plan sınırları içinde)
  6. confidence=high ve yeni olan sinyaller için FCM push gönder — ücretsiz

Kullanım (GitHub Actions içinden):
  python scripts/main.py
"""

import os
import sys
import json
import logging

sys.path.append(os.path.dirname(__file__))

from data_fetcher import fetch_all
from indicators import compute_indicators
from decision_engine import build_all_signals
from firestore_writer import write_signals
from fcm_notifier import notify_new_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("main")

WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "watchlist.json")


def load_watchlist() -> list[str]:
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["tickers"]


def run():
    tickers = load_watchlist()
    logger.info(f"Watchlist yüklendi: {len(tickers)} hisse")

    raw_data = fetch_all(tickers)

    all_indicators = {}
    for ticker, df in raw_data.items():
        ind = compute_indicators(df)
        if ind is not None:
            all_indicators[ticker] = ind
    logger.info(f"{len(all_indicators)} hisse için gösterge hesaplandı")

    signals = build_all_signals(all_indicators)
    active_signals = [s for s in signals if s.get("direction") != "none"]
    logger.info(f"{len(active_signals)} aktif sinyal üretildi (toplam {len(signals)} hisse tarandı)")

    if not active_signals:
        logger.info("Aktif sinyal yok, çıkılıyor.")
        return

    notify_new_signals(active_signals)
    write_signals(active_signals)

    logger.info("Çalıştırma tamamlandı.")


if __name__ == "__main__":
    run()
