"""
firestore_writer.py
Aktif sinyalleri Firestore 'signals' koleksiyonuna yazar/günceller.
"""

import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger("firestore_writer")


def init_firebase():
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
    init_firebase()
    db = firestore.client()
    batch = db.batch()

    for s in signals:
        ticker = s.get("ticker")
        if not ticker:
            continue
        doc_ref = db.collection("signals").document(ticker)
        batch.set(doc_ref, s, merge=True)

    batch.commit()
    logger.info(f"{len(signals)} sinyal Firestore'a yazıldı.")
