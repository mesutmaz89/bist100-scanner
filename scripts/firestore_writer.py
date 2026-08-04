"""
firestore_writer.py
Sinyalleri Firestore'a yazar. Şema:

signals/{ticker}                (son durum - dashboard bunu okur)
signal_history/{ticker}_{ts}    (geçmiş kayıt - performans takibi için)
"""

import os
import json
import logging
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger("firestore_writer")

_app = None


def init_firebase():
    global _app
    if _app is not None:
        return _app

    cred_json = os.environ["FIREBASE_SERVICE_ACCOUNT"]  # GitHub Secret olarak JSON string
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
    _app = firebase_admin.initialize_app(cred)
    return _app


def write_signals(signals: list[dict], run_id: str | None = None):
    """
    signals: claude_analyzer.analyze_in_batches() çıktısı
    Sadece direction != "none" olanlar yazılır.
    """
    init_firebase()
    db = firestore.client()
    now = datetime.now(timezone.utc)
    run_id = run_id or now.strftime("%Y%m%d_%H%M%S")

    batch = db.batch()
    written = 0

    for sig in signals:
        if sig.get("direction") in (None, "none"):
            continue

        ticker = sig["ticker"]
        doc_data = {
            **sig,
            "updated_at": now,
            "run_id": run_id,
        }

        # son durum
        latest_ref = db.collection("signals").document(ticker)
        batch.set(latest_ref, doc_data)

        # geçmiş kayıt
        hist_ref = db.collection("signal_history").document(f"{ticker}_{run_id}")
        batch.set(hist_ref, doc_data)

        written += 1

    if written > 0:
        batch.commit()
        logger.info(f"{written} sinyal Firestore'a yazıldı (run_id={run_id})")
    else:
        logger.info("Yazılacak yeni sinyal yok (hepsi 'none')")

    return written
