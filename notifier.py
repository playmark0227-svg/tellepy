"""Slack通知モジュール"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def notify_appointment(
    company_name: str,
    contact_name: str,
    appointment_datetime: str,
    phone_number: str,
    recording_url: str | None = None,
    notes: str | None = None,
) -> bool:
    """アポ確定時にSlack Webhookで通知する

    Args:
        company_name: 会社名
        contact_name: 担当者名
        appointment_datetime: 希望日時
        phone_number: 電話番号
        recording_url: 通話録音URL
        notes: 備考

    Returns:
        通知成功ならTrue
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL が設定されていません")
        return False

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📞 新規アポイント獲得！",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*会社名:*\n{company_name}"},
                {"type": "mrkdwn", "text": f"*担当者名:*\n{contact_name}"},
                {"type": "mrkdwn", "text": f"*希望日時:*\n{appointment_datetime}"},
                {"type": "mrkdwn", "text": f"*電話番号:*\n{phone_number}"},
            ],
        },
    ]

    if recording_url:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*録音URL:*\n<{recording_url}|録音を聴く>",
                },
            }
        )

    if notes:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*備考:*\n{notes}"},
            }
        )

    payload = {
        "text": f"新規アポイント: {company_name} / {contact_name}",
        "blocks": blocks,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("Slack通知送信完了: %s / %s", company_name, contact_name)
        return True
    except Exception:
        logger.exception("Slack通知送信エラー")
        return False


async def notify_error(error_message: str, context: str = "") -> bool:
    """エラー発生時にSlackへ通知する"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False

    payload = {
        "text": f"⚠️ tellepy エラー\n```{error_message}```\n{context}",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        return True
    except Exception:
        logger.exception("エラー通知送信失敗")
        return False
