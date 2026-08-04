"""
data_fetcher.py
Öncelik: Yapı Kredi API (henüz key yok -> pas geçiliyor)
Fallback: Yahoo Finance (yfinance), BIST tickerları için '.IS' suffix kullanılır.
"""

import os
import time
import logging
import pandas as pd
import yfinance as yf
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_fetcher")

YKB_API_KEY = os.environ.get("YKB_API_KEY")  # ileride doldurulacak
YKB_BASE_URL = os.environ.get("YKB_BASE_URL", "")  # ileride doldurulacak


def fetch_from_ykb(ticker: str, lookback_days: int = 250) -> pd.DataFrame | None:
    """
    Yapı Kredi API entegrasyonu için placeholder.
    API erişimi alındığında burada gerçek endpoint çağrısı yapılacak.
    Şu an key yoksa None döner, main.py otomatik Yahoo Finance'a düşer.
    """
    if not YKB_API_KEY or not YKB_BASE_URL:
        return None

    try:
        # TODO: Gerçek Yapı Kredi API endpoint'i ile değiştirilecek.
        # Örnek iskelet:
        # resp = requests.get(
        #     f"{YKB_BASE_URL}/marketdata/ohlcv",
        #     params={"symbol": ticker, "days": lookback_days},
        #     headers={"Authorization": f"Bearer {YKB_API_KEY}"},
        #     timeout=10,
        # )
        # resp.raise_for_status()
        # data = resp.json()
        # df = pd.DataFrame(data["bars"])
        # df["Date"] = pd.to_datetime(df["date"])
        # df = df.set_index("Date")[["open", "high", "low", "close", "volume"]]
        # df.columns = ["Open", "High", "Low", "Close", "Volume"]
        # return df
        return None
    except Exception as e:
        logger.warning(f"YKB API hatası ({ticker}): {e}")
        return None


def fetch_from_yahoo(ticker: str, lookback_days: int = 250) -> pd.DataFrame | None:
    """BIST tickerları Yahoo Finance'de '.IS' suffix ile bulunur (örn. THYAO.IS)."""
    symbol = f"{ticker}.IS"
    try:
        df = yf.download(
            symbol,
            period=f"{lookback_days}d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            logger.warning(f"Yahoo Finance boş veri döndürdü: {symbol}")
            return None
        # yfinance bazen MultiIndex kolon döner (tek ticker'da bile), düzelt
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        logger.warning(f"Yahoo Finance hatası ({symbol}): {e}")
        return None


def fetch_ohlcv(ticker: str, lookback_days: int = 250, retry: int = 2) -> pd.DataFrame | None:
    """Ana giriş noktası: önce YKB, olmazsa Yahoo Finance. Retry ile birlikte."""
    df = fetch_from_ykb(ticker, lookback_days)
    if df is not None:
        return df

    for attempt in range(retry):
        df = fetch_from_yahoo(ticker, lookback_days)
        if df is not None:
            return df
        time.sleep(1.5)

    logger.error(f"Veri alınamadı: {ticker}")
    return None


def fetch_all(tickers: list[str], lookback_days: int = 250, pause: float = 0.3) -> dict:
    """Watchlist'teki tüm hisseler için veri çeker. Yahoo rate-limit'e takılmamak için pause kullanılır."""
    results = {}
    for i, ticker in enumerate(tickers):
        df = fetch_ohlcv(ticker, lookback_days)
        results[ticker] = df
        if (i + 1) % 10 == 0:
            logger.info(f"{i + 1}/{len(tickers)} hisse çekildi")
        time.sleep(pause)
    return results
