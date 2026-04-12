"""会話学習・分析モジュール - 過去の通話データから学習しAIの応対品質を向上させる"""

from __future__ import annotations

import fcntl
import json
import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "learning"

CALL_RESULTS_PATH = DATA_DIR / "call_results.json"
INSIGHTS_PATH = DATA_DIR / "insights.json"
EFFECTIVE_RESPONSES_PATH = DATA_DIR / "effective_responses.json"

MAX_RECORDS = 1000  # 各JSONファイルの最大レコード数

# 既知の反論パターン（正規化用）
KNOWN_OBJECTIONS = [
    "間に合っています",
    "必要ありません",
    "忙しい",
    "結構です",
    "興味がない",
    "予算がない",
    "上に確認しないと",
    "資料だけ送って",
    "他社を使っている",
    "担当者不在",
    "かけ直してください",
]

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# ファイルI/Oヘルパー（ロック付き）
# ---------------------------------------------------------------------------

def _ensure_data_dir() -> None:
    """データディレクトリが無ければ作成する。"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("データディレクトリの作成に失敗しました")


def _read_json(path: Path) -> list[dict]:
    """JSONファイルを読み込む。存在しなければ空リストを返す。"""
    try:
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        if isinstance(data, list):
            return data
        logger.warning("JSONファイルの形式が不正です（リストではありません）: %s", path)
        return []
    except (json.JSONDecodeError, OSError):
        logger.exception("JSONファイルの読み込みに失敗しました: %s", path)
        return []


def _write_json(path: Path, data: list[dict]) -> None:
    """JSONファイルに書き込む（排他ロック付き）。古いレコードを自動ローテーション。"""
    _ensure_data_dir()
    # 最大件数を超えたら古い方から削除
    if len(data) > MAX_RECORDS:
        data = data[-MAX_RECORDS:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        logger.exception("JSONファイルの書き込みに失敗しました: %s", path)


def _append_record(path: Path, record: dict) -> None:
    """レコードを1件追加する。"""
    records = _read_json(path)
    records.append(record)
    _write_json(path, records)


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """現在時刻をISO形式（JST）で返す。"""
    return datetime.now(JST).isoformat()


def _normalize_objection(text: str) -> str:
    """反論テキストを既知パターンに正規化する。一致しなければそのまま返す。"""
    for pattern in KNOWN_OBJECTIONS:
        if pattern in text:
            return pattern
    return text


def _safe_division(numerator: float, denominator: float) -> float:
    """ゼロ除算を防いで割り算する。"""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _extract_hour(iso_str: str) -> int | None:
    """ISO形式の日時文字列から時（hour）を取り出す。"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.hour
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# CallAnalyzer
# ---------------------------------------------------------------------------

class CallAnalyzer:
    """通話データの記録・分析・インサイト生成を行うクラス。

    全メソッドはデータ0件でも安全に動作し、ファイルI/Oエラーでクラッシュしない。
    """

    def __init__(self) -> None:
        _ensure_data_dir()

    # ------------------------------------------------------------------
    # 記録
    # ------------------------------------------------------------------

    def record_call(self, call_data: dict) -> None:
        """完了した通話を記録する。

        Parameters
        ----------
        call_data : dict
            必須キー:
                conversation_log : list[dict]  -- 会話ログ
                outcome : str                  -- "appointed" / "rejected" / "absent"
            任意キー:
                duration : float               -- 通話秒数
                objections_encountered : list[str]
                objection_responses_used : list[dict]
                    各要素: {"objection": str, "response": str}
                interest_levels_over_time : list[float]
                final_interest_level : float
                script_used : str
                phone_number : str
                call_sid : str
                contact_name : str
                appointment_datetime : str
                notes : str
        """
        try:
            record = {
                "id": str(uuid.uuid4()),
                "recorded_at": _now_iso(),
                "conversation_log": call_data.get("conversation_log", []),
                "outcome": call_data.get("outcome", "unknown"),
                "duration": call_data.get("duration"),
                "objections_encountered": call_data.get("objections_encountered", []),
                "objection_responses_used": call_data.get("objection_responses_used", []),
                "interest_levels_over_time": call_data.get("interest_levels_over_time", []),
                "final_interest_level": call_data.get("final_interest_level"),
                "script_used": call_data.get("script_used"),
                "phone_number": call_data.get("phone_number"),
                "call_sid": call_data.get("call_sid"),
                "contact_name": call_data.get("contact_name"),
                "appointment_datetime": call_data.get("appointment_datetime"),
                "notes": call_data.get("notes"),
            }
            _append_record(CALL_RESULTS_PATH, record)

            # 成功した通話から有効な応答を自動抽出して保存
            if record["outcome"] == "appointed":
                self._save_effective_responses(record)

            logger.info(
                "通話記録を保存しました: outcome=%s, duration=%s",
                record["outcome"],
                record["duration"],
            )
        except Exception:
            logger.exception("通話記録の保存に失敗しました")

    def _save_effective_responses(self, record: dict) -> None:
        """アポ成功した通話から反論対応の有効レスポンスを抽出して保存する。"""
        try:
            for item in record.get("objection_responses_used", []):
                objection = item.get("objection", "")
                response = item.get("response", "")
                if not objection or not response:
                    continue
                entry = {
                    "id": str(uuid.uuid4()),
                    "recorded_at": _now_iso(),
                    "objection": _normalize_objection(objection),
                    "response": response,
                    "outcome": "appointed",
                    "script_used": record.get("script_used"),
                    "call_id": record.get("id"),
                }
                _append_record(EFFECTIVE_RESPONSES_PATH, entry)
        except Exception:
            logger.exception("有効レスポンスの保存に失敗しました")

    # ------------------------------------------------------------------
    # 単一通話の分析
    # ------------------------------------------------------------------

    def analyze_call(self, conversation_log: list[dict], outcome: str) -> dict:
        """1通話を分析し、何が良かったか・悪かったかを返す。

        Returns
        -------
        dict
            {
                "outcome": str,
                "turn_count": int,
                "what_worked": list[str],
                "what_didnt_work": list[str],
                "key_moments": list[str],
                "suggestions": list[str],
                "detected_objections": list[str],
            }
        """
        try:
            turn_count = len(conversation_log)
            detected_objections: list[str] = []
            what_worked: list[str] = []
            what_didnt_work: list[str] = []
            key_moments: list[str] = []
            suggestions: list[str] = []

            for i, msg in enumerate(conversation_log):
                content = msg.get("content", "")
                role = msg.get("role", "")

                # 反論の検出
                if role == "user":
                    for pattern in KNOWN_OBJECTIONS:
                        if pattern in content:
                            detected_objections.append(pattern)
                            key_moments.append(
                                f"ターン{i + 1}: 相手が「{pattern}」と発言"
                            )

            # アポ成功時の分析
            if outcome == "appointed":
                what_worked.append("最終的にアポイント獲得に成功")
                if turn_count <= 8:
                    what_worked.append("短い会話でアポを獲得（効率的）")
                if detected_objections:
                    what_worked.append(
                        f"反論（{', '.join(detected_objections)}）を乗り越えてアポ獲得"
                    )

            # 拒否時の分析
            elif outcome == "rejected":
                if turn_count <= 4:
                    what_didnt_work.append("会話が短すぎた（商材説明前に断られた可能性）")
                    suggestions.append("挨拶後すぐに相手のメリットを伝える工夫を検討")
                if detected_objections:
                    what_didnt_work.append(
                        f"反論（{', '.join(detected_objections)}）を克服できなかった"
                    )
                    suggestions.append(
                        "反論への返答を改善してください。"
                        "get_best_response_for() で有効な返答を確認できます"
                    )
                if not detected_objections and turn_count >= 6:
                    what_didnt_work.append(
                        "明確な反論はなかったが成約に至らなかった"
                    )
                    suggestions.append("クロージングのタイミングや表現を見直してください")

            # 不在時の分析
            elif outcome == "absent":
                what_didnt_work.append("相手に繋がらなかった")
                suggestions.append("架電時間帯の見直しを検討してください")

            # 共通の提案
            if turn_count > 12:
                suggestions.append(
                    "会話が長い傾向があります。要点を絞った簡潔な応対を心がけてください"
                )

            return {
                "outcome": outcome,
                "turn_count": turn_count,
                "what_worked": what_worked,
                "what_didnt_work": what_didnt_work,
                "key_moments": key_moments,
                "suggestions": suggestions,
                "detected_objections": detected_objections,
            }
        except Exception:
            logger.exception("通話分析に失敗しました")
            return {
                "outcome": outcome,
                "turn_count": len(conversation_log),
                "what_worked": [],
                "what_didnt_work": [],
                "key_moments": [],
                "suggestions": [],
                "detected_objections": [],
            }

    # ------------------------------------------------------------------
    # パターン分析（全通話横断）
    # ------------------------------------------------------------------

    def get_success_patterns(self) -> dict:
        """全通話データを横断分析し、成功パターンを抽出する。

        Returns
        -------
        dict
            {
                "total_calls": int,
                "success_rate": float,
                "best_time_slots": list[dict],
                "optimal_turn_count": dict,
                "effective_objection_responses": list[dict],
                "common_objections": list[dict],
                "script_performance": list[dict],
            }
        """
        try:
            records = _read_json(CALL_RESULTS_PATH)
            if not records:
                return self._empty_patterns()

            total = len(records)
            appointed = [r for r in records if r.get("outcome") == "appointed"]
            rejected = [r for r in records if r.get("outcome") == "rejected"]
            success_rate = _safe_division(len(appointed), total) * 100

            # --- 時間帯別成功率 ---
            hour_total: Counter[int] = Counter()
            hour_success: Counter[int] = Counter()
            for r in records:
                hour = _extract_hour(r.get("recorded_at", ""))
                if hour is not None:
                    hour_total[hour] += 1
                    if r.get("outcome") == "appointed":
                        hour_success[hour] += 1

            best_time_slots = sorted(
                [
                    {
                        "hour": h,
                        "total": hour_total[h],
                        "success": hour_success.get(h, 0),
                        "rate": round(
                            _safe_division(hour_success.get(h, 0), hour_total[h]) * 100, 1
                        ),
                    }
                    for h in hour_total
                    if hour_total[h] >= 3  # 最低3件以上のデータがある時間帯のみ
                ],
                key=lambda x: x["rate"],
                reverse=True,
            )

            # --- 最適会話ターン数 ---
            success_turns = [
                len(r.get("conversation_log", []))
                for r in appointed
                if r.get("conversation_log")
            ]
            rejected_turns = [
                len(r.get("conversation_log", []))
                for r in rejected
                if r.get("conversation_log")
            ]
            optimal_turn_count = {
                "success_avg": round(
                    _safe_division(sum(success_turns), len(success_turns)), 1
                )
                if success_turns
                else 0,
                "rejected_avg": round(
                    _safe_division(sum(rejected_turns), len(rejected_turns)), 1
                )
                if rejected_turns
                else 0,
            }

            # --- 反論別の成功率 ---
            objection_total: Counter[str] = Counter()
            objection_success: Counter[str] = Counter()
            for r in records:
                for obj in r.get("objections_encountered", []):
                    normalized = _normalize_objection(obj)
                    objection_total[normalized] += 1
                    if r.get("outcome") == "appointed":
                        objection_success[normalized] += 1

            common_objections = sorted(
                [
                    {
                        "objection": obj,
                        "count": objection_total[obj],
                        "success_count": objection_success.get(obj, 0),
                        "success_rate": round(
                            _safe_division(
                                objection_success.get(obj, 0), objection_total[obj]
                            )
                            * 100,
                            1,
                        ),
                    }
                    for obj in objection_total
                ],
                key=lambda x: x["count"],
                reverse=True,
            )

            # --- 有効な反論返答 ---
            effective_responses = _read_json(EFFECTIVE_RESPONSES_PATH)
            response_by_objection: dict[str, list[dict]] = defaultdict(list)
            for er in effective_responses:
                key = _normalize_objection(er.get("objection", ""))
                response_by_objection[key].append(er)

            effective_objection_responses = [
                {
                    "objection": obj,
                    "best_responses": [
                        r.get("response", "") for r in resps
                    ][:5],  # 上位5件まで
                    "sample_count": len(resps),
                }
                for obj, resps in response_by_objection.items()
            ]

            # --- スクリプト別成績 ---
            script_total: Counter[str] = Counter()
            script_success: Counter[str] = Counter()
            for r in records:
                script = r.get("script_used") or "不明"
                script_total[script] += 1
                if r.get("outcome") == "appointed":
                    script_success[script] += 1

            script_performance = sorted(
                [
                    {
                        "script": s,
                        "total": script_total[s],
                        "success": script_success.get(s, 0),
                        "rate": round(
                            _safe_division(script_success.get(s, 0), script_total[s])
                            * 100,
                            1,
                        ),
                    }
                    for s in script_total
                ],
                key=lambda x: x["rate"],
                reverse=True,
            )

            return {
                "total_calls": total,
                "success_rate": round(success_rate, 1),
                "best_time_slots": best_time_slots,
                "optimal_turn_count": optimal_turn_count,
                "effective_objection_responses": effective_objection_responses,
                "common_objections": common_objections,
                "script_performance": script_performance,
            }
        except Exception:
            logger.exception("成功パターン分析に失敗しました")
            return self._empty_patterns()

    def _empty_patterns(self) -> dict:
        """データ0件時のデフォルト値。"""
        return {
            "total_calls": 0,
            "success_rate": 0.0,
            "best_time_slots": [],
            "optimal_turn_count": {"success_avg": 0, "rejected_avg": 0},
            "effective_objection_responses": [],
            "common_objections": [],
            "script_performance": [],
        }

    # ------------------------------------------------------------------
    # プロンプト注入用インサイト生成
    # ------------------------------------------------------------------

    def get_insights_for_prompt(self, script_name: str) -> str:
        """AIのシステムプロンプトに注入するインサイトテキストを生成する。

        過去の通話データから学んだ教訓を自然言語で返す。
        データが不足している場合は汎用的なアドバイスを返す。

        Parameters
        ----------
        script_name : str
            対象スクリプト名

        Returns
        -------
        str
            プロンプトに挿入可能なテキスト
        """
        try:
            records = _read_json(CALL_RESULTS_PATH)
            effective = _read_json(EFFECTIVE_RESPONSES_PATH)

            # 対象スクリプトのデータに絞り込み（データがあれば）
            script_records = [
                r for r in records if r.get("script_used") == script_name
            ]
            # スクリプト指定のデータが少ない場合は全データを使用
            if len(script_records) < 10:
                target_records = records
                scope_label = "全スクリプト"
            else:
                target_records = script_records
                scope_label = f"スクリプト「{script_name}」"

            if len(target_records) < 5:
                return self._default_insights()

            lines: list[str] = []
            lines.append(f"## 過去の通話データからの学習（{scope_label}、{len(target_records)}件分析済み）")
            lines.append("")

            # --- 全体成功率 ---
            total = len(target_records)
            appointed_count = sum(
                1 for r in target_records if r.get("outcome") == "appointed"
            )
            success_rate = _safe_division(appointed_count, total) * 100
            lines.append(f"- 現在のアポ獲得率: {success_rate:.1f}%（{appointed_count}/{total}件）")

            # --- 反論別の有効返答 ---
            objection_stats: dict[str, dict[str, int]] = defaultdict(
                lambda: {"total": 0, "success": 0}
            )
            for r in target_records:
                for obj in r.get("objections_encountered", []):
                    normalized = _normalize_objection(obj)
                    objection_stats[normalized]["total"] += 1
                    if r.get("outcome") == "appointed":
                        objection_stats[normalized]["success"] += 1

            # 有効返答のデータベースから引く
            response_by_objection: dict[str, list[str]] = defaultdict(list)
            for er in effective:
                key = _normalize_objection(er.get("objection", ""))
                resp = er.get("response", "")
                if resp and resp not in response_by_objection[key]:
                    response_by_objection[key].append(resp)

            if objection_stats:
                lines.append("")
                lines.append("### 反論への対応ヒント")

                for obj, stats in sorted(
                    objection_stats.items(),
                    key=lambda x: x[1]["total"],
                    reverse=True,
                )[:5]:  # 上位5つの反論
                    rate = _safe_division(stats["success"], stats["total"]) * 100
                    lines.append(
                        f"- 「{obj}」（出現{stats['total']}回、突破率{rate:.0f}%）"
                    )
                    best_responses = response_by_objection.get(obj, [])
                    if best_responses:
                        lines.append(
                            f"  → 有効だった返答例: 「{best_responses[0]}」"
                        )

            # --- 最適会話長 ---
            appointed_records = [
                r for r in target_records if r.get("outcome") == "appointed"
            ]
            if appointed_records:
                avg_turns = _safe_division(
                    sum(
                        len(r.get("conversation_log", []))
                        for r in appointed_records
                    ),
                    len(appointed_records),
                )
                lines.append("")
                lines.append(
                    f"### 会話の長さ目安"
                )
                lines.append(
                    f"- アポ成功時の平均会話ターン数: {avg_turns:.0f}ターン。"
                    f"この前後を目安にクロージングに入ってください。"
                )

            # --- 時間帯ヒント ---
            hour_total: Counter[int] = Counter()
            hour_success: Counter[int] = Counter()
            for r in target_records:
                hour = _extract_hour(r.get("recorded_at", ""))
                if hour is not None:
                    hour_total[hour] += 1
                    if r.get("outcome") == "appointed":
                        hour_success[hour] += 1

            best_hours = sorted(
                [
                    (h, _safe_division(hour_success.get(h, 0), hour_total[h]))
                    for h in hour_total
                    if hour_total[h] >= 3
                ],
                key=lambda x: x[1],
                reverse=True,
            )[:3]

            if best_hours:
                hour_str = "、".join(f"{h}時台" for h, _ in best_hours)
                lines.append("")
                lines.append(f"### 架電タイミング")
                lines.append(f"- 成功率が高い時間帯: {hour_str}")

            # --- インサイトをファイルにも保存 ---
            insight_record = {
                "id": str(uuid.uuid4()),
                "generated_at": _now_iso(),
                "script_name": script_name,
                "total_records_analyzed": len(target_records),
                "content": "\n".join(lines),
            }
            _append_record(INSIGHTS_PATH, insight_record)

            return "\n".join(lines)

        except Exception:
            logger.exception("インサイト生成に失敗しました")
            return self._default_insights()

    def _default_insights(self) -> str:
        """データ不足時の汎用アドバイス。"""
        return (
            "## 通話のヒント（データ蓄積中）\n"
            "- 挨拶は明るく簡潔にし、相手の名前を早めに確認してください。\n"
            "- 反論には共感を示してから、具体的な数字やメリットで返してください。\n"
            "- 会話が長くなりすぎないよう、適切なタイミングでクロージングに入ってください。\n"
            "- データが蓄積されると、ここに具体的なインサイトが表示されます。"
        )

    # ------------------------------------------------------------------
    # 統計ダッシュボード用
    # ------------------------------------------------------------------

    def get_stats(self, days: int = 30) -> dict:
        """ダッシュボード表示用の統計情報を返す。

        Parameters
        ----------
        days : int
            過去何日分のデータを対象にするか（デフォルト30日）

        Returns
        -------
        dict
            {
                "period_days": int,
                "total_calls": int,
                "appointed": int,
                "rejected": int,
                "absent": int,
                "success_rate": float,
                "avg_conversation_turns": float,
                "avg_duration_seconds": float | None,
                "best_time_slots": list[dict],
                "common_objections": list[dict],
                "daily_breakdown": list[dict],
                "trend": str,
            }
        """
        try:
            records = _read_json(CALL_RESULTS_PATH)
            if not records:
                return self._empty_stats(days)

            # 期間フィルタ
            cutoff = datetime.now(JST) - timedelta(days=days)
            filtered: list[dict] = []
            for r in records:
                try:
                    rec_dt = datetime.fromisoformat(r.get("recorded_at", ""))
                    if rec_dt >= cutoff:
                        filtered.append(r)
                except (ValueError, TypeError):
                    # 日時パースできないレコードは含める（データ欠損対策）
                    filtered.append(r)

            if not filtered:
                return self._empty_stats(days)

            total = len(filtered)
            appointed = sum(1 for r in filtered if r.get("outcome") == "appointed")
            rejected = sum(1 for r in filtered if r.get("outcome") == "rejected")
            absent = sum(1 for r in filtered if r.get("outcome") == "absent")
            success_rate = _safe_division(appointed, total) * 100

            # 平均会話ターン数
            turn_counts = [
                len(r.get("conversation_log", []))
                for r in filtered
                if r.get("conversation_log")
            ]
            avg_turns = (
                round(_safe_division(sum(turn_counts), len(turn_counts)), 1)
                if turn_counts
                else 0.0
            )

            # 平均通話時間
            durations = [
                r["duration"]
                for r in filtered
                if r.get("duration") is not None
            ]
            avg_duration = (
                round(_safe_division(sum(durations), len(durations)), 1)
                if durations
                else None
            )

            # 時間帯別
            hour_total: Counter[int] = Counter()
            hour_success: Counter[int] = Counter()
            for r in filtered:
                hour = _extract_hour(r.get("recorded_at", ""))
                if hour is not None:
                    hour_total[hour] += 1
                    if r.get("outcome") == "appointed":
                        hour_success[hour] += 1

            best_time_slots = sorted(
                [
                    {
                        "hour": h,
                        "total": hour_total[h],
                        "success": hour_success.get(h, 0),
                        "rate": round(
                            _safe_division(hour_success.get(h, 0), hour_total[h])
                            * 100,
                            1,
                        ),
                    }
                    for h in hour_total
                ],
                key=lambda x: x["rate"],
                reverse=True,
            )

            # 反論統計
            obj_counter: Counter[str] = Counter()
            for r in filtered:
                for obj in r.get("objections_encountered", []):
                    obj_counter[_normalize_objection(obj)] += 1

            common_objections = [
                {"objection": obj, "count": cnt}
                for obj, cnt in obj_counter.most_common(10)
            ]

            # 日別ブレイクダウン
            daily: dict[str, dict[str, int]] = defaultdict(
                lambda: {"total": 0, "appointed": 0, "rejected": 0, "absent": 0}
            )
            for r in filtered:
                try:
                    day = datetime.fromisoformat(
                        r.get("recorded_at", "")
                    ).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                daily[day]["total"] += 1
                outcome = r.get("outcome", "")
                if outcome in ("appointed", "rejected", "absent"):
                    daily[day][outcome] += 1

            daily_breakdown = [
                {"date": d, **counts}
                for d, counts in sorted(daily.items())
            ]

            # トレンド判定（直近半分 vs 前半分）
            trend = self._calculate_trend(filtered)

            return {
                "period_days": days,
                "total_calls": total,
                "appointed": appointed,
                "rejected": rejected,
                "absent": absent,
                "success_rate": round(success_rate, 1),
                "avg_conversation_turns": avg_turns,
                "avg_duration_seconds": avg_duration,
                "best_time_slots": best_time_slots,
                "common_objections": common_objections,
                "daily_breakdown": daily_breakdown,
                "trend": trend,
            }
        except Exception:
            logger.exception("統計情報の取得に失敗しました")
            return self._empty_stats(days)

    def _calculate_trend(self, records: list[dict]) -> str:
        """レコードを前半・後半に分けて成功率のトレンドを判定する。"""
        if len(records) < 6:
            return "データ不足"

        mid = len(records) // 2
        first_half = records[:mid]
        second_half = records[mid:]

        first_rate = _safe_division(
            sum(1 for r in first_half if r.get("outcome") == "appointed"),
            len(first_half),
        )
        second_rate = _safe_division(
            sum(1 for r in second_half if r.get("outcome") == "appointed"),
            len(second_half),
        )

        diff = second_rate - first_rate
        if diff > 0.05:
            return "改善傾向"
        elif diff < -0.05:
            return "低下傾向"
        return "横ばい"

    def _empty_stats(self, days: int) -> dict:
        """データ0件時のデフォルト統計。"""
        return {
            "period_days": days,
            "total_calls": 0,
            "appointed": 0,
            "rejected": 0,
            "absent": 0,
            "success_rate": 0.0,
            "avg_conversation_turns": 0.0,
            "avg_duration_seconds": None,
            "best_time_slots": [],
            "common_objections": [],
            "daily_breakdown": [],
            "trend": "データなし",
        }

    # ------------------------------------------------------------------
    # 反論別ベストレスポンス検索
    # ------------------------------------------------------------------

    def get_best_response_for(self, objection: str) -> str | None:
        """指定した反論に対する最も有効な返答を返す。

        有効な返答が見つからなければ None を返す。

        Parameters
        ----------
        objection : str
            反論テキスト（例: "間に合っています"）

        Returns
        -------
        str | None
        """
        try:
            effective = _read_json(EFFECTIVE_RESPONSES_PATH)
            if not effective:
                return None

            normalized = _normalize_objection(objection)

            # 完全一致を優先
            exact_matches = [
                er
                for er in effective
                if _normalize_objection(er.get("objection", "")) == normalized
            ]

            if exact_matches:
                # 最新のものを返す（末尾が最新）
                return exact_matches[-1].get("response")

            # 部分一致フォールバック
            for er in reversed(effective):
                er_obj = er.get("objection", "")
                if objection in er_obj or er_obj in objection:
                    return er.get("response")

            return None
        except Exception:
            logger.exception("ベストレスポンスの検索に失敗しました")
            return None

    # ------------------------------------------------------------------
    # 一括操作
    # ------------------------------------------------------------------

    def clear_all_data(self) -> None:
        """全データを削除する（テスト・リセット用）。"""
        try:
            for path in (CALL_RESULTS_PATH, INSIGHTS_PATH, EFFECTIVE_RESPONSES_PATH):
                if path.exists():
                    path.unlink()
            logger.info("全学習データを削除しました")
        except OSError:
            logger.exception("学習データの削除に失敗しました")

    def export_data(self) -> dict[str, Any]:
        """全データをエクスポートする（バックアップ用）。"""
        return {
            "call_results": _read_json(CALL_RESULTS_PATH),
            "insights": _read_json(INSIGHTS_PATH),
            "effective_responses": _read_json(EFFECTIVE_RESPONSES_PATH),
            "exported_at": _now_iso(),
        }

    def import_data(self, data: dict[str, Any]) -> None:
        """エクスポートしたデータをインポートする（リストア用）。"""
        try:
            if "call_results" in data:
                _write_json(CALL_RESULTS_PATH, data["call_results"])
            if "insights" in data:
                _write_json(INSIGHTS_PATH, data["insights"])
            if "effective_responses" in data:
                _write_json(EFFECTIVE_RESPONSES_PATH, data["effective_responses"])
            logger.info("学習データをインポートしました")
        except Exception:
            logger.exception("学習データのインポートに失敗しました")
