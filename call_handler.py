"""通話フロー制御・会話ステート管理モジュール（強化版）

変更点:
- 感情・関心度トラッキング追加
- AIの判定をより信頼し、固定ステートマシンに縛られない柔軟な遷移
- 通話終了後の学習フィードバック
- 会話品質のリアルタイム監視
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional

from ai_engine import AIEngine, CallResult

logger = logging.getLogger(__name__)


class CallState(str, Enum):
    """通話の状態遷移"""
    GREETING = "GREETING"
    QUALIFYING = "QUALIFYING"
    PITCHING = "PITCHING"
    OBJECTION = "OBJECTION"
    CLOSING = "CLOSING"
    HANDOFF = "HANDOFF"
    REJECTED = "REJECTED"


class CallSession:
    """1通話分のセッションを管理するクラス（強化版）

    旧版との違い:
    - interest_history: 関心度の推移を記録
    - mood_history: 感情の推移を記録
    - objections_log: 断り内容と対応を記録
    - strategy_history: AIが選んだ戦略を記録
    - 通話終了後にlearning.pyへ自動フィードバック
    """

    MAX_OBJECTIONS = 3  # 2→3に増加。AIが賢くなったので粘れる

    def __init__(self, ai_engine: AIEngine, call_sid: str, phone_number: str):
        self.ai_engine = ai_engine
        self.call_sid = call_sid
        self.phone_number = phone_number
        self.state = CallState.GREETING
        self.conversation_history: list = []
        self.objection_count = 0
        self.contact_name: Optional[str] = None
        self.appointment_datetime: Optional[str] = None
        self.notes: Optional[str] = None

        # --- 強化トラッキング ---
        self.interest_history: list = []      # [(turn, level), ...]
        self.mood_history: list = []           # [(turn, mood), ...]
        self.objections_log: list = []         # [{"objection": ..., "response": ..., "result": ...}]
        self.strategy_history: list = []       # [(turn, strategy), ...]
        self.state_history: list = []          # [(turn, state), ...]
        self.start_time: float = time.time()
        self.turn_count = 0

    async def start(self) -> str:
        """通話開始"""
        greeting = self.ai_engine.get_greeting()
        self.conversation_history.append(
            {"role": "assistant", "content": greeting}
        )
        self.state_history.append((0, self.state.value))
        logger.info("通話開始: %s (SID: %s)", self.phone_number, self.call_sid)
        return greeting

    async def process_speech(self, user_speech: str) -> dict:
        """相手の発言を処理し、次の応答を生成する"""
        self.turn_count += 1

        self.conversation_history.append(
            {"role": "user", "content": user_speech}
        )

        # 「人間と話したい」チェック
        if self._wants_human(user_speech):
            return await self._transition_to_handoff("相手が人間との会話を希望")

        # --- AI応答を生成（学習インサイトを注入） ---
        learning_context = self._get_learning_context()
        ai_result = await self.ai_engine.generate_response(
            self.conversation_history,
            self.state.value,
            learning_context=learning_context,
        )

        # --- メタ情報の更新 ---
        if ai_result.get("contact_name"):
            self.contact_name = ai_result["contact_name"]
        if ai_result.get("appointment_datetime"):
            self.appointment_datetime = ai_result["appointment_datetime"]
        if ai_result.get("notes"):
            self.notes = ai_result["notes"]

        # --- トラッキング記録 ---
        interest = ai_result.get("interest_level", 3)
        mood = ai_result.get("detected_mood", "neutral")
        strategy = ai_result.get("strategy", "")

        self.interest_history.append((self.turn_count, interest))
        self.mood_history.append((self.turn_count, mood))
        if strategy:
            self.strategy_history.append((self.turn_count, strategy))

        # --- 状態遷移の判定 ---
        response_text = ai_result["response"]
        result = ai_result["result"]

        # ハンドオフ
        if result == CallResult.HANDOFF:
            return await self._transition_to_handoff("AI判定によるハンドオフ")

        # アポ確定
        if result == CallResult.APPOINTED:
            return self._transition_to(
                CallState.HANDOFF, response_text, finished=True
            )

        # 断り → 関心度に基づいて判断
        if result == CallResult.REJECTED:
            return self._handle_rejection(response_text, interest, user_speech)

        # --- 通常の状態遷移（AIの判定を尊重） ---
        self._advance_state_smart(result, interest)

        self.conversation_history.append(
            {"role": "assistant", "content": response_text}
        )
        self.state_history.append((self.turn_count, self.state.value))

        return {
            "response": response_text,
            "state": self.state,
            "is_finished": False,
        }

    def _handle_rejection(self, response_text: str, interest: int, user_speech: str) -> dict:
        """断りの処理 - 関心度とコンテキストで判断"""

        # 関心度が残っている & まだ粘れる → OBJECTION
        if interest >= 2 and self.objection_count < self.MAX_OBJECTIONS:
            self.objection_count += 1
            self.state = CallState.OBJECTION

            self.objections_log.append({
                "turn": self.turn_count,
                "objection": user_speech,
                "response": response_text,
                "interest_at_time": interest,
            })

            logger.info(
                "断り返し %d/%d (関心度:%d): %s",
                self.objection_count, self.MAX_OBJECTIONS,
                interest, self.call_sid,
            )

            self.conversation_history.append(
                {"role": "assistant", "content": response_text}
            )
            self.state_history.append((self.turn_count, self.state.value))

            return {
                "response": response_text,
                "state": self.state,
                "is_finished": False,
            }

        # 完全拒否
        self.objections_log.append({
            "turn": self.turn_count,
            "objection": user_speech,
            "response": response_text,
            "interest_at_time": interest,
            "final": True,
        })

        return self._transition_to(
            CallState.REJECTED, response_text, finished=True
        )

    def _advance_state_smart(self, result: CallResult, interest: int):
        """AIの判定と関心度に基づいてスマートに状態遷移"""

        if result != CallResult.CONTINUE:
            return

        # GREETING → 相手が応答したら次へ
        if self.state == CallState.GREETING:
            self.state = CallState.QUALIFYING
            return

        # OBJECTION → 断り返しが成功（会話継続）→ 関心度に応じて戻る
        if self.state == CallState.OBJECTION:
            if interest >= 3:
                self.state = CallState.PITCHING  # 興味が戻ったらピッチへ
            elif interest >= 2:
                self.state = CallState.QUALIFYING  # まだ探りが必要

        # QUALIFYING → 十分な情報が得られたらピッチへ
        # （AIが"continue"を返し続ける間はQUALIFYINGに留まる）
        # ターン数で自然に進める
        qualifying_turns = sum(
            1 for _, s in self.state_history if s == "QUALIFYING"
        )
        if self.state == CallState.QUALIFYING and qualifying_turns >= 2:
            self.state = CallState.PITCHING

        # PITCHING → 関心度が高まったらクロージングへ
        if self.state == CallState.PITCHING and interest >= 4:
            self.state = CallState.CLOSING

    def _get_learning_context(self) -> str:
        """学習モジュールからインサイトを取得"""
        try:
            from learning import CallAnalyzer
            analyzer = CallAnalyzer()
            return analyzer.get_insights_for_prompt("default")
        except Exception:
            return ""

    def _transition_to(
        self, state: CallState, response: str, finished: bool = False
    ) -> dict:
        prev = self.state
        self.state = state
        self.conversation_history.append(
            {"role": "assistant", "content": response}
        )
        self.state_history.append((self.turn_count, state.value))
        logger.info("状態遷移: %s -> %s (%s)", prev.value, state.value, self.call_sid)

        if finished:
            self._record_to_learning()

        return {
            "response": response,
            "state": self.state,
            "is_finished": finished,
        }

    async def _transition_to_handoff(self, reason: str) -> dict:
        logger.info("ハンドオフ: %s (%s)", reason, self.call_sid)
        response = "かしこまりました。ただいま担当者におつなぎいたします。少々お待ちくださいませ。"
        return self._transition_to(CallState.HANDOFF, response, finished=True)

    def _wants_human(self, text: str) -> bool:
        keywords = [
            "人間と話したい", "人と話したい", "担当者に代わって",
            "担当者と話したい", "AIじゃなくて", "人に代わって",
            "生身の人間", "ロボットじゃなくて", "機械じゃなくて",
            "オペレーター", "人間に代えて", "人に替えて",
        ]
        return any(kw in text for kw in keywords)

    def _record_to_learning(self):
        """通話終了時に学習モジュールへ記録"""
        try:
            from learning import CallAnalyzer
            analyzer = CallAnalyzer()

            call_data = {
                "call_sid": self.call_sid,
                "phone_number": self.phone_number,
                "outcome": self.get_status(),
                "conversation_log": self.conversation_history,
                "duration_seconds": time.time() - self.start_time,
                "turn_count": self.turn_count,
                "objection_count": self.objection_count,
                "objections_log": self.objections_log,
                "interest_history": self.interest_history,
                "mood_history": self.mood_history,
                "strategy_history": self.strategy_history,
                "state_history": self.state_history,
                "contact_name": self.contact_name,
                "appointment_datetime": self.appointment_datetime,
                "final_interest": self.interest_history[-1][1] if self.interest_history else None,
                "script_used": "default",
            }

            analyzer.record_call(call_data)
            logger.info("学習データ記録完了: %s -> %s", self.call_sid, self.get_status())
        except Exception:
            logger.exception("学習データ記録エラー")

    def get_status(self) -> str:
        if self.state == CallState.HANDOFF:
            return "appointed" if self.appointment_datetime else "handoff"
        if self.state == CallState.REJECTED:
            return "rejected"
        return "in_progress"

    def get_summary(self) -> dict:
        current_interest = self.interest_history[-1][1] if self.interest_history else None
        current_mood = self.mood_history[-1][1] if self.mood_history else None

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
            "interest_level": current_interest,
            "mood": current_mood,
            "duration_seconds": round(time.time() - self.start_time),
            "turn_count": self.turn_count,
        }
