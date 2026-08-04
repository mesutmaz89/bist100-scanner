"""
fcm_notifier.py
Sadece confidence=high ve YENİ (önceki çalıştırmadan farklı) sinyaller için push gönderir.
Spam'i önlemek amacıyla aynı ticker+direction kombinasyonu tekrar bildirim üretmez.
"""

import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, messaging, firestore

logger = logging.getLogger("fcm_notifier")


def init_firebase():
    """Firebase SDK zaten başlatılmamışsa başlatır."""
    if not firebase_admin._apps:
        creds_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if creds_json:
            cred_dict = json.loads(creds_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        elif os.path.exists("firebase-key.json"):
            cred = credentials.Certificate("firebase-key.json")
            firebase_admin.initialize_app(cred)


def _get_previous_signal(db, ticker: str) -> dict | None:
    doc = db.collection("signals").document(ticker).get()
    return doc.to_dict() if doc.exists else None


def notify_new_signals(signals: list[dict], topic: str = "bist100_signals"):
    """
    signals: bu çalıştırmada üretilen ham sinyaller (Firestore'a yazılmadan ÖNCE çağrılmalı,
    çünkü karşılaştırma için 'önceki' değeri okuyoruz)
    """
    init_firebase()
    db = firestore.client()
    sent = 0

    for sig in signals:
        if sig.get("confidence") != "high" or sig.get("direction") in (None, "none"):
            continue

        ticker = sig["ticker"]
        prev = _get_previous_signal(db, ticker)

        # Aynı yön zaten bildirilmişse tekrar gönderme
        if prev and prev.get("direction") == sig["direction"]:
            continue

        direction_tr = "AL (Long)" if sig["direction"] == "long" else "SAT (Short)"
        title = f"{ticker} — {direction_tr} sinyali"
        body = (
            f"Giriş: {sig.get('entry')} | Stop: {sig.get('stop_loss')} | "
            f"Hedef: {sig.get('take_profit')} | R/R: {sig.get('risk_reward')}"
        )

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={
                "ticker": ticker,
                "direction": sig["direction"],
                "confidence": sig["confidence"],
            },
            topic=topic,
        )

        try:
            messaging.send(message)
            sent += 1
            logger.info(f"Bildirim gönderildi: {title}")
        except Exception as e:
            logger.error(f"FCM gönderim hatası ({ticker}): {e}")

    logger.info(f"Toplam {sent} yeni bildirim gönderildi")
    return sent
