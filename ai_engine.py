"""Claude API連携・返答生成モジュール"""

import logging
import os
from enum import Enum

import anthropic
import yaml

logger = logging.getLogger(__name__)


class CallResult(str, Enum):
    """AI判定結果"""
    CONTINUE = "continue"       # 会話継続
    APPOINTED = "appointed"     # アポ確定
    REJECTED = "rejected"       # 断られた
    HANDOFF = "handoff"         # 人間にハンドオフ要求


class AIEngine:
    """Claude APIを使った会話エンジン"""

    def __init__(self, script_path: str):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.script = self._load_script(script_path)
        self.system_prompt = self._build_system_prompt()

    def _load_script(self, path: str) -> dict:
        """YAMLスクリプトを読み込む"""
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_system_prompt(self) -> str:
        """システムプロンプトを構築する"""
        objection_section = ""
        for obj in self.script.get("objection_responses", []):
            objection_section += (
                f"- 相手が「{obj['trigger']}」と言った場合:\n"
                f"  {obj['response']}\n"
            )

        return f"""あなたは「{self.script['client_name']}」のテレアポAIアシスタントです。
電話で「{self.script['target']}」に対して「{self.script['product']}」を案内し、
商談アポイントを獲得することが目的です。

## 重要なルール
- 自然な日本語の敬語で話してください。
- 一度に話す内容は短く簡潔にしてください（2〜3文以内）。
- 電話口での会話であることを意識し、聞き取りやすい言葉を選んでください。
- 相手の発言を必ず受け止めてから返答してください。
- 相手が「人間と話したい」「担当者に代わって」「AIじゃなくて人と話したい」と言った場合、
  即座にハンドオフしてください。

## 挨拶テンプレート
{self.script.get('greeting', '')}

## 商材説明テンプレート
{self.script.get('pitch', '')}

## 断り返しパターン
{objection_section}

## クロージングテンプレート
{self.script.get('closing', '')}

## 終話テンプレート
{self.script.get('farewell', '')}

## 返答フォーマット
必ず以下のJSON形式で返答してください:
{{
  "response": "相手に話す内容",
  "result": "continue / appointed / rejected / handoff",
  "contact_name": "判明した担当者名（不明なら null）",
  "appointment_datetime": "アポ日時（未確定なら null）",
  "notes": "補足情報（なければ null）"
}}
"""

    async def generate_response(
        self,
        conversation_history: list[dict],
        current_state: str,
    ) -> dict:
        """会話履歴をもとにAIの返答を生成する

        Args:
            conversation_history: これまでの会話履歴
                [{"role": "assistant", "content": "..."}, {"role": "user", "content": "..."}]
            current_state: 現在の通話ステート（GREETING, QUALIFYING, etc.）

        Returns:
            {
                "response": str,       # 相手に話す内容
                "result": CallResult,  # 判定結果
                "contact_name": str | None,
                "appointment_datetime": str | None,
                "notes": str | None,
            }
        """
        state_instruction = f"\n\n現在の通話ステート: {current_state}\nこのステートに適した応対をしてください。"

        messages = []
        for msg in conversation_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=self.system_prompt + state_instruction,
                messages=messages,
            )

            raw_text = response.content[0].text
            parsed = self._parse_response(raw_text)
            logger.info(
                "AI応答生成: state=%s, result=%s", current_state, parsed["result"]
            )
            return parsed

        except Exception:
            logger.exception("AI応答生成エラー")
            return {
                "response": "申し訳ございません、少々お待ちください。",
                "result": CallResult.CONTINUE,
                "contact_name": None,
                "appointment_datetime": None,
                "notes": None,
            }

    def _parse_response(self, raw_text: str) -> dict:
        """AIの返答をパースする"""
        import json

        # JSON部分を抽出
        try:
            # ```json ... ``` で囲まれている場合に対応
            if "```json" in raw_text:
                json_str = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                json_str = raw_text.split("```")[1].split("```")[0].strip()
            elif "{" in raw_text:
                start = raw_text.index("{")
                end = raw_text.rindex("}") + 1
                json_str = raw_text[start:end]
            else:
                json_str = raw_text

            data = json.loads(json_str)
            return {
                "response": data.get("response", raw_text),
                "result": CallResult(data.get("result", "continue")),
                "contact_name": data.get("contact_name"),
                "appointment_datetime": data.get("appointment_datetime"),
                "notes": data.get("notes"),
            }
        except (json.JSONDecodeError, ValueError, KeyError):
            logger.warning("AI応答のパースに失敗、テキストをそのまま返します")
            return {
                "response": raw_text,
                "result": CallResult.CONTINUE,
                "contact_name": None,
                "appointment_datetime": None,
                "notes": None,
            }

    def get_greeting(self) -> str:
        """初回挨拶テキストを返す"""
        return (
            "AIアシスタントがご案内します。"
            + self.script.get("greeting", "お世話になっております。")
        )
