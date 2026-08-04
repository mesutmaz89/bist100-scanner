"""
firestore_writer.py
Hesaplanan sinyalleri Firestore 'signals' koleksiyonuna yazar.
"""

import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger("firestore_writer")


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


def write_signals(signals: list[dict]):
    """
    Sinyalleri Firestore'a toplu (batch) veya tek tek kaydeder.
    """
    init_firebase()

    if not firebase_admin._apps:
        logger.error("Firebase başlatılamadı. Kredansiyelleri kontrol edin.")
        return

    db = firestore.client()
    batch = db.batch()
    count = 0

    for sig in signals:
        ticker = sig.get("ticker")
        if not ticker:
            continue

        doc_ref = db.collection("signals").document(ticker)
        batch.set(doc_ref, sig, merge=True)
        count += 1

        # Firestore batch limiti 500 dokümandır
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()

    if count % 400 != 0:
        batch.commit()

    logger.info(f"{count} adet sinyal Firestore'a başarıyla yazıldı.")
