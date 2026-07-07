"""企業リスト作成モジュール - telepy リストビルダー

依頼文（自然言語）から検索条件を抽出し、経産省 gBizINFO の法人情報APIを使って
条件に合致する企業リストを作成する。テレアポ代行の「商材→会社探し」の姉妹機能。

データソース: gBizINFO REST API v2 (https://api.info.gbiz.go.jp/hojin)
  - 無料・商用利用可。利用申請でAPIトークンを取得し X-hojinInfo-api-token ヘッダに設定する
  - 検索は 資本金範囲 / 従業員数範囲 / 都道府県 / 法人種別 で絞り込み可能
  - 「業種」は検索パラメータに無いため、社名キーワード検索 + 詳細レスポンスの
    industry フィールドでマッチングする
  - 電話番号はAPIに含まれないため、CSVでは空欄（別途エンリッチ）となる
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

GBIZ_BASE_URL = "https://api.info.gbiz.go.jp/hojin"
GBIZ_SEARCH_MAX_PAGE = 10  # v2はpage 1-10まで
GBIZ_SEARCH_MAX_LIMIT = 5000  # 1ページ最大件数

# 都道府県名 → JIS X 0401 コード（gBizINFOのprefectureパラメータ用）
PREFECTURE_CODES = {
    "北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
    "山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
    "埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
    "富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
    "岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
    "京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
    "鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
    "徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
    "佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
    "鹿児島県": "46", "沖縄県": "47",
}

# 業種（ユーザー語）→ 社名検索に使うキーワード群のプリセット。
# gBizINFO v2には業種の検索パラメータが無いので、社名の部分一致で母集団を集める。
# 「工務店」「不動産」など業種名が社名に含まれる業界と特に相性が良い。
INDUSTRY_KEYWORD_PRESETS = {
    "工務店": ["工務店", "建設", "建築", "住宅", "ホーム", "ハウス", "リフォーム", "土木"],
    "建設": ["建設", "建築", "工務店", "土木", "工業", "総合建設"],
    "不動産": ["不動産", "住宅", "ハウジング", "エステート", "地所", "都市開発", "リアルティ"],
    "リフォーム": ["リフォーム", "リノベーション", "住宅", "ホーム", "工務店"],
    "建築": ["建築", "設計", "工務店", "建設"],
}


def normalize_prefecture(name: str) -> Optional[str]:
    """都道府県名（省略形も可）をJISコードに変換する。見つからなければNone。"""
    name = (name or "").strip()
    if not name:
        return None
    if name in PREFECTURE_CODES:
        return PREFECTURE_CODES[name]
    # 「東京」「神奈川」「大阪」等の省略形に対応
    for full, code in PREFECTURE_CODES.items():
        stem = full.rstrip("都道府県")
        if name == stem or name == full:
            return code
    return None


def prefecture_name_from_code(code: str) -> str:
    for name, c in PREFECTURE_CODES.items():
        if c == code:
            return name
    return ""


# ---------------------------------------------------------------------------
# 検索条件
# ---------------------------------------------------------------------------


@dataclass
class SearchCriteria:
    """依頼文から抽出した検索条件"""

    industries: list[str] = field(default_factory=list)  # 例: ["工務店", "不動産"]
    name_keywords: list[str] = field(default_factory=list)  # 社名検索キーワード
    prefectures: list[str] = field(default_factory=list)  # 都道府県名（表示用）
    employee_min: Optional[int] = None
    employee_max: Optional[int] = None
    capital_min: Optional[int] = None  # 円
    capital_max: Optional[int] = None  # 円
    target_count: int = 100
    notes: str = ""

    def prefecture_codes(self) -> list[str]:
        codes = []
        for p in self.prefectures:
            code = normalize_prefecture(p)
            if code and code not in codes:
                codes.append(code)
        return codes

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SearchCriteria":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class Company:
    """検索結果の1社分"""

    corporate_number: str = ""
    name: str = ""
    prefecture: str = ""
    location: str = ""
    postal_code: str = ""
    capital_stock: Optional[int] = None  # 円
    employee_number: Optional[int] = None
    industry: str = ""
    founding_year: Optional[int] = None
    representative_name: str = ""
    company_url: str = ""
    phone_number: str = ""  # gBizINFOには無いため空（別途エンリッチ）
    match_reason: str = ""  # なぜリストに入ったか（enriched/keyword/unknown等）

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 依頼文パーサ
# ---------------------------------------------------------------------------

_PARSE_SYSTEM_PROMPT = """\
あなたは営業リスト作成の依頼文を構造化するアシスタントです。
与えられた依頼文から検索条件を抽出し、指定のJSON形式のみで回答してください。前後に説明文を付けないこと。

出力するJSONの形式:
{
  "industries": ["工務店", "不動産"],
  "name_keywords": ["工務店", "建設", "住宅", "不動産", "ホーム", "リフォーム"],
  "prefectures": ["東京都", "神奈川県"],
  "employee_min": 10,
  "employee_max": 20,
  "capital_min": null,
  "capital_max": 10000000,
  "target_count": 1000,
  "notes": "抽出時の補足があれば"
}

ルール:
- industries: 依頼された業種を日本語の一般名で（例: 工務店, 不動産, リフォーム, 建設）
- name_keywords: その業種の会社の社名に含まれやすい単語を広めに列挙（社名部分一致検索に使う）。
  例: 工務店→[工務店,建設,建築,住宅,ホーム,リフォーム]、不動産→[不動産,住宅,エステート,地所,ハウジング]
- prefectures: 「東京」→「東京都」、「神奈川」→「神奈川県」のように正式名称にする
- employee_min/max: 「従業員数10-20名」→ min=10, max=20。指定なければ null
- capital_min/max: 金額は必ず「円」に換算した整数。「資本金1000万円以下」→ capital_max=10000000。
  「以下」は max、「以上」は min。指定なければ null
- target_count: 「1000件」→ 1000。指定なければ 100
- 不明な項目は null（数値）または [] （配列）にする
"""


class InquiryParser:
    """依頼文を SearchCriteria に変換する。Claude API 優先、失敗時はヒューリスティック。"""

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def parse(self, text: str) -> SearchCriteria:
        criteria = None
        if self.api_key:
            try:
                criteria = await asyncio.to_thread(self._parse_with_claude, text)
            except Exception:
                logger.exception("依頼文のClaudeパースに失敗、ヒューリスティックにフォールバック")
        if criteria is None:
            criteria = self._parse_heuristic(text)
        self._backfill(criteria, text)
        return criteria

    # -- Claude --

    def _parse_with_claude(self, text: str) -> Optional[SearchCriteria]:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.MODEL,
            max_tokens=1000,
            system=_PARSE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = resp.content[0].text
        data = _extract_json(raw)
        if not data:
            return None
        return SearchCriteria(
            industries=_as_str_list(data.get("industries")),
            name_keywords=_as_str_list(data.get("name_keywords")),
            prefectures=_as_str_list(data.get("prefectures")),
            employee_min=_as_int(data.get("employee_min")),
            employee_max=_as_int(data.get("employee_max")),
            capital_min=_as_int(data.get("capital_min")),
            capital_max=_as_int(data.get("capital_max")),
            target_count=_as_int(data.get("target_count")) or 100,
            notes=str(data.get("notes") or ""),
        )

    # -- ヒューリスティック（APIキー無し・失敗時のフォールバック） --

    def _parse_heuristic(self, text: str) -> SearchCriteria:
        c = SearchCriteria()

        # 業種
        for industry in INDUSTRY_KEYWORD_PRESETS:
            if industry in text:
                c.industries.append(industry)

        # 都道府県
        for full in PREFECTURE_CODES:
            stem = full.rstrip("都道府県")
            if full in text or (len(stem) >= 2 and stem in text):
                if full not in c.prefectures:
                    c.prefectures.append(full)

        # 従業員数レンジ  「10-20名」「10〜20人」「10名以上」等
        emp_range = re.search(r"従業員[数]?[^\d]{0,6}?(\d+)\s*[-〜~ー]\s*(\d+)", text)
        if emp_range:
            c.employee_min = int(emp_range.group(1))
            c.employee_max = int(emp_range.group(2))
        else:
            m_max = re.search(r"従業員[数]?[^\d]{0,6}?(\d+)\s*(?:名|人)?\s*以下", text)
            m_min = re.search(r"従業員[数]?[^\d]{0,6}?(\d+)\s*(?:名|人)?\s*以上", text)
            if m_max:
                c.employee_max = int(m_max.group(1))
            if m_min:
                c.employee_min = int(m_min.group(1))

        # 資本金  「1000万円以下」「1億円以上」等
        c.capital_max = _parse_capital(text, "以下")
        c.capital_min = _parse_capital(text, "以上")

        # 件数  「1000件」「500社」
        m_count = re.search(r"(\d[\d,]*)\s*(?:件|社)", text)
        if m_count:
            c.target_count = int(m_count.group(1).replace(",", ""))

        return c

    def _backfill(self, c: SearchCriteria, text: str) -> None:
        """欠けている補助情報を埋める。"""
        if not c.target_count or c.target_count <= 0:
            c.target_count = 100
        # 上限ガード（暴走防止）
        c.target_count = min(c.target_count, 5000)

        # name_keywords が空なら業種プリセットから補完
        if not c.name_keywords:
            kws: list[str] = []
            for industry in c.industries:
                kws.extend(INDUSTRY_KEYWORD_PRESETS.get(industry, [industry]))
            # プリセットに無い業種はその語自体をキーワードにする
            for industry in c.industries:
                if industry not in kws:
                    kws.append(industry)
            c.name_keywords = _dedupe(kws)

        # industries が空でも name_keywords があれば industries を推定
        if not c.industries and c.name_keywords:
            c.industries = c.name_keywords[:1]


def _parse_capital(text: str, suffix: str) -> Optional[int]:
    """「1000万円<suffix>」「1億円<suffix>」から円換算の整数を返す。"""
    m = re.search(r"資本金[^\d]{0,6}?(\d[\d,\.]*)\s*(億|万)?\s*円?\s*" + suffix, text)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2)
    if unit == "億":
        num *= 100_000_000
    elif unit == "万":
        num *= 10_000
    return int(num)


# ---------------------------------------------------------------------------
# gBizINFO クライアント
# ---------------------------------------------------------------------------


class GBizINFOError(Exception):
    pass


class GBizClient:
    """gBizINFO REST API v2 の薄いラッパー"""

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        base_url: str = GBIZ_BASE_URL,
        timeout: float = 30.0,
        max_concurrency: int = 3,
        request_interval: float = 0.35,
    ) -> None:
        self.token = token or os.environ.get("GBIZINFO_API_TOKEN", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._sem = asyncio.Semaphore(max_concurrency)
        self._interval = request_interval
        self._last_request = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        headers = {"X-hojinInfo-api-token": self.token, "Accept": "application/json"}
        for attempt in range(4):
            async with self._sem:
                await self._throttle()
                try:
                    resp = await client.get(
                        self.base_url + path, params=params, headers=headers, timeout=self.timeout
                    )
                except httpx.HTTPError as e:
                    if attempt == 3:
                        raise GBizINFOError(f"通信エラー: {e}") from e
                    await asyncio.sleep(2 ** attempt)
                    continue
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                logger.warning("gBizINFO レート制限。%s秒待機", wait)
                await asyncio.sleep(min(wait, 60))
                continue
            if resp.status_code == 401 or resp.status_code == 403:
                raise GBizINFOError("APIトークンが無効か未設定です（401/403）")
            if resp.status_code == 404:
                return {}
            if resp.status_code >= 500:
                if attempt == 3:
                    raise GBizINFOError(f"サーバエラー: {resp.status_code}")
                await asyncio.sleep(2 ** attempt)
                continue
            try:
                return resp.json()
            except Exception as e:
                raise GBizINFOError(f"JSONパース失敗: {e}") from e
        raise GBizINFOError("リトライ上限に達しました")

    async def _throttle(self) -> None:
        loop = asyncio.get_event_loop()
        now = loop.time()
        delta = now - self._last_request
        if delta < self._interval:
            await asyncio.sleep(self._interval - delta)
        self._last_request = asyncio.get_event_loop().time()

    async def search_page(
        self,
        client: httpx.AsyncClient,
        *,
        name: Optional[str] = None,
        prefecture: Optional[str] = None,
        capital_stock_from: Optional[int] = None,
        capital_stock_to: Optional[int] = None,
        employee_number_from: Optional[int] = None,
        employee_number_to: Optional[int] = None,
        page: int = 1,
        limit: int = 1000,
    ) -> list[dict]:
        params: dict = {"page": page, "limit": min(limit, GBIZ_SEARCH_MAX_LIMIT)}
        if name:
            params["name"] = name
        if prefecture:
            params["prefecture"] = prefecture
        if capital_stock_from is not None:
            params["capital_stock_from"] = capital_stock_from
        if capital_stock_to is not None:
            params["capital_stock_to"] = capital_stock_to
        if employee_number_from is not None:
            params["employee_number_from"] = employee_number_from
        if employee_number_to is not None:
            params["employee_number_to"] = employee_number_to
        data = await self._get(client, "/v2/hojin", params)
        return data.get("hojin-infos", []) or data.get("hojinInfos", []) or []

    async def detail(self, client: httpx.AsyncClient, corporate_number: str) -> Optional[dict]:
        data = await self._get(client, f"/v2/hojin/{corporate_number}", {})
        infos = data.get("hojin-infos", []) or data.get("hojinInfos", [])
        if infos:
            return infos[0]
        return None


def _company_from_search(item: dict) -> Company:
    return Company(
        corporate_number=str(item.get("corporate_number", "")),
        name=item.get("name", ""),
        location=item.get("location", ""),
        postal_code=item.get("postal_code", ""),
        prefecture=_prefecture_from_location(item.get("location", "")),
    )


def _enrich_company(c: Company, detail: dict) -> None:
    c.capital_stock = _as_int(detail.get("capital_stock"))
    c.employee_number = _as_int(detail.get("employee_number"))
    industry = detail.get("industry")
    if isinstance(industry, list):
        c.industry = " / ".join(str(x) for x in industry if x)
    elif industry:
        c.industry = str(industry)
    c.founding_year = _as_int(detail.get("founding_year") or detail.get("date_of_establishment"))
    c.representative_name = detail.get("representative_name", "") or ""
    c.company_url = detail.get("company_url", "") or ""
    if not c.location:
        c.location = detail.get("location", "") or ""
    if not c.prefecture:
        c.prefecture = _prefecture_from_location(c.location)


def _prefecture_from_location(location: str) -> str:
    if not location:
        return ""
    for full in PREFECTURE_CODES:
        if location.startswith(full):
            return full
    return ""


# ---------------------------------------------------------------------------
# リストビルダー本体
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[dict], Awaitable[None]]


@dataclass
class BuildStats:
    candidates: int = 0
    enriched: int = 0
    matched: int = 0
    unknown_employee: int = 0
    demo: bool = False


class ListBuilder:
    """検索条件から企業リストを組み立てる"""

    def __init__(self, gbiz: Optional[GBizClient] = None) -> None:
        self.gbiz = gbiz or GBizClient()

    async def build(
        self,
        criteria: SearchCriteria,
        *,
        enrich: bool = True,
        detail_budget: int = 1500,
        include_unknown_employee: bool = True,
        strict_capital: bool = True,
        demo: bool = False,
        progress: Optional[ProgressCallback] = None,
    ) -> tuple[list[Company], BuildStats]:
        """リストを作成する。

        Args:
            enrich: 各社の詳細API（資本金・従業員数・業種・URL）を取得するか
            detail_budget: 詳細取得する最大件数（レート制限対策の上限）
            include_unknown_employee: 従業員数が不明な会社をリストに含めるか
            strict_capital: 検索時にサーバ側で資本金上限フィルタをかけるか
                （Trueで精度重視。資本金未登録の小規模企業は除外される）
            demo: APIを使わずデモ用サンプルデータを生成する
        """
        if demo or not self.gbiz.configured:
            companies = _demo_companies(criteria)
            stats = BuildStats(
                candidates=len(companies), matched=len(companies), demo=True
            )
            if progress:
                await progress({"phase": "done", "found": len(companies), "target": criteria.target_count, "demo": True})
            return companies[: criteria.target_count], stats

        stats = BuildStats()
        candidates: dict[str, Company] = {}
        pref_codes = criteria.prefecture_codes() or [None]  # type: ignore[list-item]
        keywords = criteria.name_keywords or [""]
        cap_to = criteria.capital_max if strict_capital else None
        cap_from = criteria.capital_min if strict_capital else None
        candidate_ceiling = max(criteria.target_count * 3, criteria.target_count + 200)

        async with httpx.AsyncClient() as client:
            # --- フェーズ1: 検索で母集団を集める ---
            for pref in pref_codes:
                for kw in keywords:
                    if len(candidates) >= candidate_ceiling:
                        break
                    for page in range(1, GBIZ_SEARCH_MAX_PAGE + 1):
                        try:
                            items = await self.gbiz.search_page(
                                client,
                                name=kw or None,
                                prefecture=pref,
                                capital_stock_from=cap_from,
                                capital_stock_to=cap_to,
                                page=page,
                                limit=1000,
                            )
                        except GBizINFOError:
                            logger.exception("検索エラー kw=%s pref=%s page=%s", kw, pref, page)
                            break
                        for item in items:
                            comp = _company_from_search(item)
                            if comp.corporate_number and comp.corporate_number not in candidates:
                                comp.match_reason = f"社名一致:{kw}" if kw else "地域一致"
                                candidates[comp.corporate_number] = comp
                        if progress:
                            await progress({
                                "phase": "search",
                                "found": len(candidates),
                                "target": criteria.target_count,
                                "detail": f"{prefecture_name_from_code(pref) if pref else '全国'} / {kw}",
                            })
                        if len(items) < 1000:
                            break  # 最終ページ
                        if len(candidates) >= candidate_ceiling:
                            break
            stats.candidates = len(candidates)

            # --- フェーズ2: 詳細取得（従業員数・業種・URL） ---
            cand_list = list(candidates.values())
            if enrich:
                to_enrich = cand_list[:detail_budget]
                for idx, comp in enumerate(to_enrich):
                    try:
                        detail = await self.gbiz.detail(client, comp.corporate_number)
                    except GBizINFOError:
                        logger.exception("詳細取得エラー: %s", comp.corporate_number)
                        detail = None
                    if detail:
                        _enrich_company(comp, detail)
                        stats.enriched += 1
                    if progress and idx % 10 == 0:
                        await progress({
                            "phase": "enrich",
                            "found": len(candidates),
                            "enriched": stats.enriched,
                            "target": criteria.target_count,
                        })

        # --- フェーズ3: フィルタ・ランク付け・件数調整 ---
        selected = self._filter_and_rank(
            cand_list, criteria, include_unknown_employee=include_unknown_employee
        )
        stats.matched = len(selected)
        stats.unknown_employee = sum(1 for c in selected if c.employee_number is None)
        result = selected[: criteria.target_count]
        if progress:
            await progress({
                "phase": "done",
                "found": len(result),
                "matched": stats.matched,
                "target": criteria.target_count,
            })
        return result, stats

    def _filter_and_rank(
        self,
        companies: list[Company],
        criteria: SearchCriteria,
        *,
        include_unknown_employee: bool,
    ) -> list[Company]:
        emp_min, emp_max = criteria.employee_min, criteria.employee_max
        cap_min, cap_max = criteria.capital_min, criteria.capital_max
        kept: list[Company] = []
        for c in companies:
            # 資本金フィルタ（判明している場合のみ厳格に判定）
            if c.capital_stock is not None:
                if cap_max is not None and c.capital_stock > cap_max:
                    continue
                if cap_min is not None and c.capital_stock < cap_min:
                    continue
            # 従業員数フィルタ
            if c.employee_number is not None:
                if emp_min is not None and c.employee_number < emp_min:
                    continue
                if emp_max is not None and c.employee_number > emp_max:
                    continue
                c.match_reason = "属性一致（従業員数確認済み）"
            else:
                if (emp_min is not None or emp_max is not None) and not include_unknown_employee:
                    continue
                c.match_reason = c.match_reason or "従業員数不明（社名・地域一致）"
            kept.append(c)
        kept.sort(key=lambda c: self._rank_key(c, criteria))
        return kept

    @staticmethod
    def _rank_key(c: Company, criteria: SearchCriteria) -> tuple:
        # 小さいほど優先。従業員数がレンジ内で判明 > 資本金判明 > URLあり > 不明
        emp_in_range = 0
        if c.employee_number is not None:
            in_range = True
            if criteria.employee_min is not None and c.employee_number < criteria.employee_min:
                in_range = False
            if criteria.employee_max is not None and c.employee_number > criteria.employee_max:
                in_range = False
            emp_in_range = 0 if in_range else 1
        else:
            emp_in_range = 2
        has_capital = 0 if c.capital_stock is not None else 1
        has_url = 0 if c.company_url else 1
        return (emp_in_range, has_capital, has_url, c.name)


# ---------------------------------------------------------------------------
# CSV 出力
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    ("company_name", "会社名"),
    ("corporate_number", "法人番号"),
    ("prefecture", "都道府県"),
    ("location", "所在地"),
    ("postal_code", "郵便番号"),
    ("capital_stock", "資本金(円)"),
    ("employee_number", "従業員数"),
    ("industry", "業種"),
    ("founding_year", "設立年"),
    ("representative_name", "代表者"),
    ("company_url", "URL"),
    ("phone_number", "電話番号"),
    ("match_reason", "選定理由"),
]


def to_csv(companies: list[Company]) -> str:
    """詳細付きCSV（BOM付きUTF-8でExcel互換）"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in CSV_COLUMNS])
    for c in companies:
        d = c.to_dict()
        writer.writerow([
            c.name,
            c.corporate_number,
            c.prefecture,
            c.location,
            c.postal_code,
            c.capital_stock if c.capital_stock is not None else "",
            c.employee_number if c.employee_number is not None else "",
            c.industry,
            c.founding_year if c.founding_year is not None else "",
            c.representative_name,
            c.company_url,
            c.phone_number,
            c.match_reason,
        ])
    return "﻿" + buf.getvalue()


def to_call_csv(companies: list[Company]) -> str:
    """telepy一括架電フォーマット（phone_number, company_name）。

    gBizINFOに電話番号は無いため phone_number は空欄。別途エンリッチして埋める。
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["phone_number", "company_name"])
    for c in companies:
        writer.writerow([c.phone_number, c.name])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# デモデータ（APIトークン未設定時の動作確認用）
# ---------------------------------------------------------------------------


def _demo_companies(criteria: SearchCriteria) -> list[Company]:
    """条件に沿った疑似サンプルを決定的に生成する（乱数不使用）。"""
    prefs = criteria.prefectures or ["東京都", "神奈川県"]
    industries = criteria.industries or ["工務店", "不動産"]
    suffixes = {
        "工務店": ["工務店", "建設", "住宅", "ホーム", "リフォーム"],
        "不動産": ["不動産", "住宅販売", "エステート", "地所", "ハウジング"],
    }
    cities = {
        "東京都": ["新宿区", "世田谷区", "大田区", "足立区", "練馬区", "杉並区"],
        "神奈川県": ["横浜市港北区", "川崎市中原区", "相模原市中央区", "藤沢市", "厚木市"],
    }
    base_names = ["山田", "佐藤", "鈴木", "高橋", "田中", "渡辺", "伊藤", "中村", "小林", "加藤"]
    emp_min = criteria.employee_min or 10
    emp_max = criteria.employee_max or 20
    cap_max = criteria.capital_max or 10_000_000

    companies: list[Company] = []
    i = 0
    target = min(criteria.target_count, 300)
    while len(companies) < target:
        pref = prefs[i % len(prefs)]
        industry = industries[i % len(industries)]
        sfx_list = suffixes.get(industry, [industry])
        sfx = sfx_list[i % len(sfx_list)]
        base = base_names[i % len(base_names)]
        city_list = cities.get(pref, ["中央区"])
        city = city_list[i % len(city_list)]
        emp = emp_min + (i % (max(emp_max - emp_min, 1) + 1))
        cap = min(3_000_000 + (i % 8) * 1_000_000, cap_max)
        companies.append(Company(
            corporate_number=f"{1000000000000 + i}",
            name=f"株式会社{base}{sfx}",
            prefecture=pref,
            location=f"{pref}{city}{1 + i % 5}-{1 + i % 20}-{1 + i % 30}",
            postal_code=f"{100 + i % 200:03d}-{1000 + i % 9000:04d}",
            capital_stock=cap,
            employee_number=emp,
            industry=industry,
            founding_year=1985 + (i % 35),
            representative_name=f"{base} {['太郎','一郎','健','誠','浩'][i % 5]}",
            company_url=f"https://example-{i}.co.jp",
            phone_number="",
            match_reason="デモデータ",
        ))
        i += 1
    return companies


# ---------------------------------------------------------------------------
# 小さなユーティリティ
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    # ```json ... ``` を除去
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def _as_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            value = re.sub(r"[^\d\-]", "", value)
            if value == "" or value == "-":
                return None
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _as_str_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(x) for x in value if x]


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
