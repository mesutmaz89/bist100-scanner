"""
firestore_writer.py
Hesaplanan sinyalleri Firestore'a yazar ve geçmiş sinyallerin sonucunu (hedef/stop) izler.

Koleksiyonlar:
  signals/{ticker}         -> o hissenin GÜNCEL/aktif sinyali (dashboard "Sinyaller" sekmesi bunu okur)
  signal_history/{doc_id}  -> her üretilen sinyalin kalıcı kaydı, status alanı ile takip edilir:
                               "open"  -> henüz hedef/stop'a ulaşmadı
                               "win"   -> take_profit'e ulaştı
                               "loss"  -> stop_loss'a ulaştı
                             (dashboard "Geçmiş" sekmesi bunu okuyup isabet oranını hesaplar)
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
    """
    Aktif sinyalleri hem 'signals' (güncel durum) hem 'signal_history' (kalıcı log,
    status='open') koleksiyonlarına yazar.
    """
    init_firebase()
    if not firebase_admin._apps:
        logger.error("Firebase başlatılamadı. Kredansiyelleri kontrol edin.")
        return

    db = firestore.client()
    batch = db.batch()
    count = 0
    now = firestore.SERVER_TIMESTAMP

    for sig in signals:
        ticker = sig.get("ticker")
        if not ticker:
            continue

        doc_data = {**sig, "updated_at": now}

        # Güncel durum (dashboard'un "Sinyaller" sekmesi)
        latest_ref = db.collection("signals").document(ticker)
        batch.set(latest_ref, doc_data, merge=True)

        # Kalıcı geçmiş kaydı — bu ticker için zaten "open" bir kayıt varsa TEKRAR EKLEME
        # (aksi halde aynı sinyal her taramada yeniden loglanır, isabet oranı hesabı bozulur)
        if not has_open_history_entry(ticker):
            import time
            hist_id = f"{ticker}_{int(time.time())}"
            hist_ref = db.collection("signal_history").document(hist_id)
            batch.set(hist_ref, {**doc_data, "status": "open"})

        count += 1
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()

    if count % 400 != 0:
        batch.commit()

    logger.info(f"{count} adet sinyal Firestore'a yazıldı (signals + signal_history).")


def cleanup_stale_signals(all_scanned_tickers: list, active_tickers: list):
    """
    Artık geçerli olmayan sinyalleri 'signals' koleksiyonundan siler:
      1) Bu taramada değerlendirilip artık aktif olmayan hisseler (skor eşiği altına düştü)
      2) direction='short' olan HER kayıt (SHORT sinyal üretimi tamamen kapatıldı,
         bu eski bir kural değişikliğinden kalma "hayalet" kayıtları temizler)
    """
    init_firebase()
    if not firebase_admin._apps:
        return 0

    db = firestore.client()
    active_set = set(active_tickers)
    deleted = 0
    batch = db.batch()

    # 1) Artık aktif olmayan taranmış hisseler
    for ticker in all_scanned_tickers:
        if ticker not in active_set:
            doc_ref = db.collection("signals").document(ticker)
            if doc_ref.get().exists:
                batch.delete(doc_ref)
                deleted += 1

    # 2) Her ihtimale karşı: hâlâ direction='short' olan (artık üretilmeyen) kayıtlar
    for doc_snap in db.collection("signals").where("direction", "==", "short").stream():
        batch.delete(doc_snap.reference)
        deleted += 1

    if deleted > 0:
        batch.commit()
        logger.info(f"{deleted} adet geçersiz/eski sinyal 'signals' koleksiyonundan temizlendi.")
    return deleted


def has_open_history_entry(ticker: str) -> bool:
    """Bu ticker için zaten 'open' durumda bir geçmiş kaydı var mı? (main.py tekrar loglamamak için kullanır)"""
    init_firebase()
    if not firebase_admin._apps:
        return False
    db = firestore.client()
    query = (
        db.collection("signal_history")
        .where("ticker", "==", ticker)
        .where("status", "==", "open")
        .limit(1)
    )
    return len(list(query.stream())) > 0


def resolve_open_signals(current_closes: dict):
    """
    current_closes: {ticker: son_kapanis_fiyati}
    status='open' olan geçmiş sinyalleri kontrol eder:
      - close >= take_profit (long)  -> status='win'
      - close <= stop_loss (long)    -> status='loss'
      - aksi halde açık kalır
    """
    init_firebase()
    if not firebase_admin._apps:
        logger.error("Firebase başlatılamadı, geçmiş sinyaller çözümlenemedi.")
        return 0

    db = firestore.client()
    open_docs = db.collection("signal_history").where("status", "==", "open").stream()

    batch = db.batch()
    resolved = 0
    checked = 0

    for doc_snap in open_docs:
        data = doc_snap.to_dict()
        ticker = data.get("ticker")
        close = current_closes.get(ticker)
        if close is None:
            continue

        checked += 1
        take_profit = data.get("take_profit")
        stop_loss = data.get("stop_loss")
        new_status = None

        if data.get("direction") == "long":
            if take_profit and close >= take_profit:
                new_status = "win"
            elif stop_loss and close <= stop_loss:
                new_status = "loss"

        if new_status:
            batch.update(doc_snap.reference, {
                "status": new_status,
                "exit_price": close,
                "closed_at": firestore.SERVER_TIMESTAMP,
            })
            resolved += 1

    if resolved > 0:
        batch.commit()

    logger.info(f"Geçmiş sinyal kontrolü: {checked} açık kayıt tarandı, {resolved} tanesi sonuçlandı.")
    return resolved
