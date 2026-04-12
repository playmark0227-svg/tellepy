"""Deepgram STT / ElevenLabs TTS モジュール"""

import io
import logging
import os
import tempfile
from pathlib import Path

import httpx
from deepgram import DeepgramClient, PrerecordedOptions

logger = logging.getLogger(__name__)

# 一時音声ファイルの保存先
AUDIO_DIR = Path(tempfile.gettempdir()) / "telepy_audio"
AUDIO_DIR.mkdir(exist_ok=True)


class SpeechToText:
    """Deepgramを使った音声認識"""

    def __init__(self):
        self.client = DeepgramClient(os.environ["DEEPGRAM_API_KEY"])

    async def transcribe_url(self, audio_url: str) -> str:
        """音声URLからテキストに変換する（Twilioの録音URLなど）

        Args:
            audio_url: 音声ファイルのURL

        Returns:
            認識結果テキスト
        """
        try:
            options = PrerecordedOptions(
                model="nova-2",
                language="ja",
                smart_format=True,
            )
            source = {"url": audio_url}
            response = self.client.listen.rest.v("1").transcribe_url(
                source, options
            )
            transcript = (
                response.results.channels[0].alternatives[0].transcript
            )
            logger.info("STT完了: %s...", transcript[:50])
            return transcript
        except Exception:
            logger.exception("STTエラー (URL: %s)", audio_url)
            return ""

    async def transcribe_bytes(self, audio_data: bytes) -> str:
        """音声バイトデータからテキストに変換する

        Args:
            audio_data: 音声バイトデータ

        Returns:
            認識結果テキスト
        """
        try:
            options = PrerecordedOptions(
                model="nova-2",
                language="ja",
                smart_format=True,
            )
            source = {"buffer": audio_data, "mimetype": "audio/wav"}
            response = self.client.listen.rest.v("1").transcribe_file(
                source, options
            )
            transcript = (
                response.results.channels[0].alternatives[0].transcript
            )
            logger.info("STT完了: %s...", transcript[:50])
            return transcript
        except Exception:
            logger.exception("STTエラー (bytes)")
            return ""


class TextToSpeech:
    """ElevenLabsを使った音声合成"""

    ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self):
        self.api_key = os.environ["ELEVENLABS_API_KEY"]
        self.voice_id = os.environ["ELEVENLABS_VOICE_ID"]

    async def synthesize(self, text: str, output_filename: str | None = None) -> Path:
        """テキストを音声に変換し、一時ファイルに保存する

        Args:
            text: 読み上げるテキスト
            output_filename: 出力ファイル名（省略時は自動生成）

        Returns:
            生成された音声ファイルのパス
        """
        if output_filename is None:
            import uuid
            output_filename = f"{uuid.uuid4().hex}.mp3"

        output_path = AUDIO_DIR / output_filename

        url = f"{self.ELEVENLABS_API_URL}/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.8,
                "style": 0.2,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()

            output_path.write_bytes(resp.content)
            logger.info("TTS完了: %s (%d bytes)", output_path, len(resp.content))
            return output_path
        except Exception:
            logger.exception("TTSエラー: %s...", text[:30])
            raise

    async def synthesize_to_bytes(self, text: str) -> bytes:
        """テキストを音声に変換し、バイトデータで返す"""
        url = f"{self.ELEVENLABS_API_URL}/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.8,
                "style": 0.2,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

        return resp.content


def cleanup_audio_files():
    """一時音声ファイルを削除する"""
    for f in AUDIO_DIR.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    logger.info("一時音声ファイルを削除しました")
