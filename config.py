"""設定管理モジュール - config.jsonの読み書きと環境変数の同期"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

# config.jsonのキー → 環境変数名のマッピング
ENV_MAP = {
    "twilio_account_sid": "TWILIO_ACCOUNT_SID",
    "twilio_auth_token": "TWILIO_AUTH_TOKEN",
    "twilio_phone_number": "TWILIO_PHONE_NUMBER",
    "deepgram_api_key": "DEEPGRAM_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "supabase_url": "SUPABASE_URL",
    "supabase_key": "SUPABASE_KEY",
    "slack_webhook_url": "SLACK_WEBHOOK_URL",
    "base_url": "BASE_URL",
    "forward_phone_number": "FORWARD_PHONE_NUMBER",
}

DEFAULT_CONFIG = {k: "" for k in ENV_MAP}


def load_config() -> dict:
    """config.jsonを読み込む。なければデフォルトを返す。"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        return {**DEFAULT_CONFIG, **saved}
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """config.jsonに保存し、環境変数も更新する。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    sync_env(config)


def sync_env(config: dict) -> None:
    """config値を環境変数に反映する。"""
    for key, env_key in ENV_MAP.items():
        val = config.get(key, "")
        if val:
            os.environ[env_key] = val


def mask_value(value: str) -> str:
    """APIキーをマスクする（先頭4文字と末尾4文字だけ表示）"""
    if not value or len(value) < 10:
        return "*" * len(value) if value else ""
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def get_masked_config() -> dict:
    """マスク済みの設定を返す（UIの表示用）"""
    config = load_config()
    secret_keys = {
        "twilio_auth_token", "deepgram_api_key", "elevenlabs_api_key",
        "anthropic_api_key", "supabase_key", "slack_webhook_url",
    }
    masked = {}
    for k, v in config.items():
        masked[k] = mask_value(v) if k in secret_keys else v
    return masked


def is_configured(key: str) -> bool:
    """指定キーが設定済みかチェック"""
    return bool(load_config().get(key))
