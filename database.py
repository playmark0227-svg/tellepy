"""Firebase Firestore連携・ログ保存モジュール"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_db = None


def get_db():
    """Firestoreクライアントのシングルトン取得"""
    global _db
    if _db is not None:
        return _db

    import firebase_admin
    from firebase_admin import credentials, firestore

    cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "")
    if not cred_path or not Path(cred_path).exists():
        raise RuntimeError(
            "FIREBASE_CREDENTIALS_PATH が未設定、またはファイルが見つかりません: "
            + repr(cred_path)
        )

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

    _db = firestore.client()
    logger.info("Firestore接続完了")
    return _db


async def save_call_log(
    phone_number: str,
    client_id: str,
    status: str,
    conversation_log: list,
    recording_url: Optional[str] = None,
    contact_name: Optional[str] = None,
    appointment_datetime: Optional[str] = None,
) -> dict:
    """通話ログをFirestoreに保存する"""
    try:
        record = {
            "called_at": datetime.now(timezone.utc).isoformat(),
            "phone_number": phone_number,
            "client_id": client_id,
            "status": status,
            "conversation_log": conversation_log,
            "recording_url": recording_url,
            "contact_name": contact_name,
            "appointment_datetime": appointment_datetime,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db = get_db()
        doc_ref = db.collection("call_logs").add(record)
        doc_id = doc_ref[1].id
        logger.info("通話ログ保存完了: %s -> %s (ID: %s)", phone_number, status, doc_id)
        return {"id": doc_id, **record}
    except Exception:
        logger.exception("通話ログ保存エラー: %s", phone_number)
        return {}


async def update_call_status(call_id: str, status: str, **kwargs) -> dict:
    """通話ステータスを更新する"""
    try:
        db = get_db()
        doc_ref = db.collection("call_logs").document(call_id)
        update_data = {"status": status, **kwargs}
        doc_ref.update(update_data)
        logger.info("通話ステータス更新: %s -> %s", call_id, status)
        return {"id": call_id, **update_data}
    except Exception:
        logger.exception("通話ステータス更新エラー: %s", call_id)
        return {}


async def get_call_logs(
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list:
    """通話ログを取得する"""
    try:
        db = get_db()
        query = db.collection("call_logs")

        if client_id:
            query = query.where("client_id", "==", client_id)
        if status:
            query = query.where("status", "==", status)

        query = query.order_by("called_at", direction="DESCENDING").limit(limit)
        docs = query.stream()

        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)

        return results
    except Exception:
        logger.exception("通話ログ取得エラー")
        return []
