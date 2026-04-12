"""通話フロー制御・会話ステート管理モジュール"""

import logging
from enum import Enum

from ai_engine import AIEngine, CallResult

logger = logging.getLogger(__name__)


class CallState(str, Enum):
    """通話の状態遷移"""
    GREETING = "GREETING"         # AIアシスタントであることを伝えつつ挨拶
    QUALIFYING = "QUALIFYING"     # 担当者確認・ヒアリング
    PITCHING = "PITCHING"         # 商材の簡単な説明
    OBJECTION = "OBJECTION"       # 断り返し（最大2回まで）
    CLOSING = "CLOSING"           # アポ日程の打診
    HANDOFF = "HANDOFF"           # アポ確定 → Slack通知して終了
    REJECTED = "REJECTED"         # 丁寧に終話


class CallSession:
    """1通話分のセッションを管理するクラス"""

    MAX_OBJECTIONS = 2

    def __init__(self, ai_engine: AIEngine, call_sid: str, phone_number: str):
        self.ai_engine = ai_engine
        self.call_sid = call_sid
        self.phone_number = phone_number
        self.state = CallState.GREETING
        self.conversation_history: list[dict] = []
        self.objection_count = 0
        self.contact_name: str | None = None
        self.appointment_datetime: str | None = None
        self.notes: str | None = None

    async def start(self) -> str:
        """通話開始 - 初回挨拶を返す"""
        greeting = self.ai_engine.get_greeting()
        self.conversation_history.append(
            {"role": "assistant", "content": greeting}
        )
        logger.info("通話開始: %s (SID: %s)", self.phone_number, self.call_sid)
        return greeting

    async def process_speech(self, user_speech: str) -> dict:
        """相手の発言を処理し、次の応答を生成する

        Args:
            user_speech: 相手の発言テキスト

        Returns:
            {
                "response": str,        # AIの応答テキスト
                "state": CallState,     # 現在の状態
                "is_finished": bool,    # 通話終了かどうか
            }
        """
        # 会話履歴に追加
        self.conversation_history.append(
            {"role": "user", "content": user_speech}
        )

        # 「人間と話したい」系のキーワードを即座にチェック
        if self._wants_human(user_speech):
            return await self._transition_to_handoff("相手が人間との会話を希望")

        # AI応答を生成
        ai_result = await self.ai_engine.generate_response(
            self.conversation_history, self.state.value
        )

        # メタ情報の更新
        if ai_result.get("contact_name"):
            self.contact_name = ai_result["contact_name"]
        if ai_result.get("appointment_datetime"):
            self.appointment_datetime = ai_result["appointment_datetime"]
        if ai_result.get("notes"):
            self.notes = ai_result["notes"]

        # 状態遷移の判定
        response_text = ai_result["response"]
        result = ai_result["result"]

        if result == CallResult.HANDOFF:
            return await self._transition_to_handoff("AI判定によるハンドオフ")

        if result == CallResult.APPOINTED:
            return self._transition_to(CallState.HANDOFF, response_text, finished=True)

        if result == CallResult.REJECTED:
            if self.state == CallState.OBJECTION and self.objection_count < self.MAX_OBJECTIONS:
                self.objection_count += 1
                logger.info(
                    "断り返し %d/%d: %s",
                    self.objection_count,
                    self.MAX_OBJECTIONS,
                    self.call_sid,
                )
            else:
                return self._transition_to(CallState.REJECTED, response_text, finished=True)

        # 通常の状態遷移
        self._advance_state(result)

        self.conversation_history.append(
            {"role": "assistant", "content": response_text}
        )

        return {
            "response": response_text,
            "state": self.state,
            "is_finished": False,
        }

    def _advance_state(self, result: CallResult):
        """AIの判定結果に基づいて状態を進める"""
        transitions = {
            CallState.GREETING: CallState.QUALIFYING,
            CallState.QUALIFYING: CallState.PITCHING,
            CallState.PITCHING: CallState.CLOSING,
            CallState.CLOSING: CallState.HANDOFF,
        }

        if result == CallResult.REJECTED and self.state != CallState.OBJECTION:
            if self.objection_count < self.MAX_OBJECTIONS:
                self.state = CallState.OBJECTION
                self.objection_count += 1
                return

        if result == CallResult.CONTINUE and self.state in transitions:
            # GREETINGからは次に進む、それ以外はAIが判断するまで留まる
            if self.state == CallState.GREETING:
                self.state = transitions[self.state]

    def _transition_to(
        self, state: CallState, response: str, finished: bool = False
    ) -> dict:
        """指定した状態に遷移して結果を返す"""
        self.state = state
        self.conversation_history.append(
            {"role": "assistant", "content": response}
        )
        logger.info("状態遷移: %s -> %s (%s)", self.state, state, self.call_sid)
        return {
            "response": response,
            "state": self.state,
            "is_finished": finished,
        }

    async def _transition_to_handoff(self, reason: str) -> dict:
        """ハンドオフ状態に遷移する"""
        logger.info("ハンドオフ: %s (%s)", reason, self.call_sid)
        response = "かしこまりました。ただいま担当者におつなぎいたします。少々お待ちくださいませ。"
        return self._transition_to(CallState.HANDOFF, response, finished=True)

    def _wants_human(self, text: str) -> bool:
        """相手が人間との会話を求めているかチェック"""
        keywords = [
            "人間と話したい",
            "人と話したい",
            "担当者に代わって",
            "担当者と話したい",
            "AIじゃなくて",
            "人に代わって",
            "生身の人間",
            "ロボットじゃなくて",
            "機械じゃなくて",
        ]
        return any(kw in text for kw in keywords)

    def get_status(self) -> str:
        """現在の通話ステータスを返す"""
        if self.state == CallState.HANDOFF:
            return "appointed" if self.appointment_datetime else "handoff"
        if self.state == CallState.REJECTED:
            return "rejected"
        return "in_progress"

    def get_summary(self) -> dict:
        """通話のサマリーを返す"""
        return {
            "call_sid": self.call_sid,
            "phone_number": self.phone_number,
            "state": self.state.value,
            "status": self.get_status(),
            "contact_name": self.contact_name,
            "appointment_datetime": self.appointment_datetime,
            "notes": self.notes,
            "objection_count": self.objection_count,
            "message_count": len(self.conversation_history),
        }
