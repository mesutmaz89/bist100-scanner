"""
fcm_notifier.py
Kişisel kullanım için basitleştirildi: topic yerine tek cihaz token'ı kullanılır.
Token, PWA dashboard tarayıcıdan bildirim izni alındığında Firestore'daki
config/fcm_token dokümanına yazılır; bu script onu okuyup push gönderir.

Sadece confidence=high ve YENİ (önceki çalıştırmadan farklı) sinyaller için push gönderir.
"""

import logging
from firebase_admin import messaging, firestore

logger = logging.getLogger("fcm_notifier")


def _get_device_token(db):
    doc = db.collection("config").document("fcm_token").get()
    if not doc.exists:
        return None
    return doc.to_dict().get("token")


def _get_previous_signal(db, ticker: str):
    doc = db.collection("signals").document(ticker).get()
    return doc.to_dict() if doc.exists else None


def notify_new_signals(signals: list[dict]):
    db = firestore.client()
    token = _get_device_token(db)

    if not token:
        logger.info("Kayıtlı FCM token yok, bildirim atlanıyor (PWA'dan bildirim izni verilmeli).")
        return 0

    sent = 0

    for sig in signals:
        if sig.get("confidence") != "high" or sig.get("direction") in (None, "none"):
            continue

        ticker = sig["ticker"]
        prev = _get_previous_signal(db, ticker)

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
            token=token,
        )

        try:
            messaging.send(message)
            sent += 1
            logger.info(f"Bildirim gönderildi: {title}")
        except Exception as e:
            logger.error(f"FCM gönderim hatası ({ticker}): {e}")

    logger.info(f"Toplam {sent} yeni bildirim gönderildi")
    return sent
