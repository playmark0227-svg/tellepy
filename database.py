"""Supabase連携・ログ保存モジュール"""

import logging
import os
from datetime import datetime, timezone

from supabase import create_client, Client

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    """Supabaseクライアントのシングルトン取得"""
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


async def save_call_log(
    phone_number: str,
    client_id: str,
    status: str,
    conversation_log: list[dict],
    recording_url: str | None = None,
    contact_name: str | None = None,
    appointment_datetime: str | None = None,
) -> dict:
    """通話ログをSupabaseに保存する

    Args:
        phone_number: 架電先電話番号
        client_id: クライアントID（YAMLファイル名など）
        status: 通話ステータス（appointed / rejected / absent / error）
        conversation_log: 会話ログ（全文）
        recording_url: Twilio録音URL
        contact_name: 担当者名
        appointment_datetime: アポ日時
    """
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
        }
        result = get_client().table("call_logs").insert(record).execute()
        logger.info("通話ログ保存完了: %s -> %s", phone_number, status)
        return result.data[0] if result.data else {}
    except Exception:
        logger.exception("通話ログ保存エラー: %s", phone_number)
        return {}


async def update_call_status(call_id: str, status: str, **kwargs) -> dict:
    """通話ステータスを更新する"""
    try:
        update_data = {"status": status, **kwargs}
        result = (
            get_client()
            .table("call_logs")
            .update(update_data)
            .eq("id", call_id)
            .execute()
        )
        logger.info("通話ステータス更新: %s -> %s", call_id, status)
        return result.data[0] if result.data else {}
    except Exception:
        logger.exception("通話ステータス更新エラー: %s", call_id)
        return {}


async def get_call_logs(
    client_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """通話ログを取得する"""
    try:
        query = get_client().table("call_logs").select("*")
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        result = query.order("called_at", desc=True).limit(limit).execute()
        return result.data or []
    except Exception:
        logger.exception("通話ログ取得エラー")
        return []
