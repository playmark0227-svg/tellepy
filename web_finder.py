"""Web自動探索モジュール - telepy HPファインダー

条件（業種・地域など）を入れると、Webを検索して条件に合う企業の
公開ホームページ(HP)を自動で探し、会社名・電話番号・住所などを抽出して
リスト化する。gBizINFOやCSVを使わず、公開Webだけを情報源にする。

- 検索: DuckDuckGo（キー不要）を既定に、任意でSerper.dev等のAPIキーも使える
- 各HPを取得し、社名/電話/住所/都道府県を抽出。会社概要ページがあれば
  資本金・従業員数もベストエフォートで拾う
- 目標件数に達するか、検索クエリを使い切るまで探し続ける

※ 実際のWebアクセスは実行環境のネットワークで行われる（各サイトの利用規約・
   robots.txtを尊重し、常識的なアクセス頻度で使うこと）。
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

from list_builder import (
    BuildStats,
    Company,
    SearchCriteria,
    PREFECTURE_CODES,
    _as_int,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# 企業HPではない（ディレクトリ/ポータル/SNS/求人/地図/行政/ブログ等）ドメイン
EXCLUDE_DOMAINS = {
    "itp.ne.jp", "ekiten.jp", "mapion.co.jp", "navitime.co.jp", "its-mo.com",
    "google.com", "google.co.jp", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "linkedin.com", "wikipedia.org",
    "indeed.com", "en-japan.com", "mynavi.jp", "rikunabi.com", "townwork.net",
    "baitoru.com", "hellowork.mhlw.go.jp", "tabelog.com", "hotpepper.jp",
    "amazon.co.jp", "rakuten.co.jp", "yahoo.co.jp", "search.yahoo.co.jp",
    "homes.co.jp", "suumo.jp", "athome.co.jp", "e-aidem.com", "job-medley.com",
    "hatenablog.com", "ameblo.jp", "note.com", "fc2.com", "jimdo.com",
    "wantedly.com", "green-japan.com", "doda.jp", "type.jp", "gbiz.go.jp",
    "houjin.jp", "houjin-bangou.nta.go.jp", "baseconnect.in", "musubu.in",
    "ipros.jp", "bing.com", "duckduckgo.com", "goo.ne.jp", "biglobe.ne.jp",
    "wixsite.com", "shopify.com", "prtimes.jp", "value-press.com",
}

# 電話番号（日本の固定/フリーダイヤル/携帯）
PHONE_RE = re.compile(r"0(?:\d[-(). ]?){8,11}\d")
POSTAL_RE = re.compile(r"〒?\s*(\d{3})[-‐－ー]?(\d{4})")
CAPITAL_RE = re.compile(r"資本金[\s:：]*[\s]*([\d,，]+)\s*(億|万)?\s*円")
EMPLOYEE_RE = re.compile(r"(?:従業員数|社員数|従業員|スタッフ数)[\s:：（(]*(?:約|およそ)?\s*([\d,，]+)\s*(?:名|人)")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
OG_SITE_RE = re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
PROFILE_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(?:[^<]*)(?:会社概要|会社案内|会社情報|企業情報|company|about)',
    re.IGNORECASE,
)
# 電話番号は「お問い合わせ/アクセス」ページにしか無いことが多いので、そこも辿る
CONTACT_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(?:[^<]*)(?:お問い?合わせ|お問合せ|問い合わせ|contact|inquiry|アクセス|access|会社概要)',
    re.IGNORECASE,
)
# tel: リンクは最も確実な電話番号ソース
TEL_LINK_RE = re.compile(r'href=["\']tel:([+0-9().\- ]{9,})["\']', re.IGNORECASE)

_PREF_ALT = "|".join(re.escape(p) for p in PREFECTURE_CODES)
PREF_NEAR_POSTAL_RE = re.compile(r"〒?\s*\d{3}[-‐－ー]?\d{4}[^\n<]{0,8}?(" + _PREF_ALT + ")")
PREF_ANY_RE = re.compile("(" + _PREF_ALT + ")")


def domain_of(url: str) -> str:
    """URLから登録ドメイン相当（例: sub.example.co.jp → example.co.jp）を返す。"""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    parts = host.split(".")
    # co.jp / ne.jp / or.jp 等の2階層TLDを考慮して末尾3ラベルを残す
    two_level = {"co", "ne", "or", "go", "ac", "ad", "ed", "gr", "lg"}
    if len(parts) >= 3 and parts[-1] == "jp" and parts[-2] in two_level:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def is_excluded(url: str) -> bool:
    d = domain_of(url)
    if not d:
        return True
    if d in EXCLUDE_DOMAINS:
        return True
    # 行政ドメインは除外
    if d.endswith(".go.jp") or d.endswith(".lg.jp"):
        return True
    return False


def _clean_text(html_text: str) -> str:
    """タグを除いた素のテキスト（抽出用のざっくり版）。"""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t　]+", " ", text)
    return text


def _company_name(html_text: str, url: str) -> str:
    m = OG_SITE_RE.search(html_text)
    name = m.group(1).strip() if m else ""
    if not name:
        m = TITLE_RE.search(html_text)
        if m:
            name = _html.unescape(m.group(1)).strip()
    if not name:
        return domain_of(url)
    # タイトルの区切りで会社名らしい部分を優先
    for sep in ["｜", "|", "―", "‐", "-", "–", "—", "･", "・", "／", "/", "：", ":"]:
        if sep in name:
            parts = [p.strip() for p in name.split(sep) if p.strip()]
            # 「株式会社〜」を含む断片があればそれを採用
            for p in parts:
                if any(k in p for k in ("株式会社", "有限会社", "合同会社", "工務店", "不動産")):
                    return p[:60]
            name = parts[0]
            break
    return name[:60]


def _extract_prefecture(text: str) -> str:
    m = PREF_NEAR_POSTAL_RE.search(text)
    if m:
        return m.group(1)
    m = PREF_ANY_RE.search(text)
    return m.group(1) if m else ""


def _extract_phone(text: str) -> str:
    for m in PHONE_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if 10 <= len(digits) <= 11:
            return raw.strip()
    return ""


def _extract_address(text: str) -> str:
    m = POSTAL_RE.search(text)
    if m:
        # 郵便番号以降の住所を都道府県から40文字程度
        tail = text[m.end(): m.end() + 60]
        pm = PREF_ANY_RE.search(tail)
        if pm:
            return (tail[pm.start():]).strip()[:50]
    pm = PREF_ANY_RE.search(text)
    if pm:
        return text[pm.start(): pm.start() + 40].strip()
    return ""


def _extract_capital(text: str):
    m = CAPITAL_RE.search(text)
    if not m:
        return None
    num = float(m.group(1).replace(",", "").replace("，", ""))
    unit = m.group(2)
    if unit == "億":
        num *= 100_000_000
    elif unit == "万":
        num *= 10_000
    return int(num)


def _extract_employees(text: str):
    m = EMPLOYEE_RE.search(text)
    if not m:
        return None
    return _as_int(m.group(1).replace("，", ","))


def _extract_phone_from_html(html_text: str, text: str) -> str:
    """tel:リンクを最優先で、無ければ本文テキストから電話番号を拾う。"""
    m = TEL_LINK_RE.search(html_text)
    if m:
        digits = re.sub(r"\D", "", m.group(1))
        if 10 <= len(digits) <= 11:
            return m.group(1).strip()
    return _extract_phone(text)


def extract_company(url: str, html_text: str) -> Company:
    """HPのHTMLから会社情報を抽出する。"""
    text = _clean_text(html_text)
    location = _extract_address(text)
    return Company(
        name=_company_name(html_text, url),
        location=location,
        prefecture=_extract_prefecture(text),
        phone_number=_extract_phone_from_html(html_text, text),
        capital_stock=_extract_capital(text),
        employee_number=_extract_employees(text),
        company_url=url,
        match_reason="Web検索でHPを発見",
    )


def _resolve_url(base_url: str, href: str) -> str:
    href = _html.unescape(href).strip()
    if href.startswith("http"):
        return href
    p = urlparse(base_url)
    if href.startswith("//"):
        return f"{p.scheme}:{href}"
    if href.startswith("/"):
        return f"{p.scheme}://{p.netloc}{href}"
    base = base_url.rsplit("/", 1)[0]
    return f"{base}/{href}"


def find_profile_url(base_url: str, html_text: str) -> str:
    """会社概要ページへのリンクを見つけて絶対URLで返す。"""
    m = PROFILE_LINK_RE.search(html_text)
    return _resolve_url(base_url, m.group(1)) if m else ""


def find_contact_url(base_url: str, html_text: str) -> str:
    """お問い合わせ/アクセスページへのリンクを見つけて絶対URLで返す（電話番号狙い）。"""
    m = CONTACT_LINK_RE.search(html_text)
    return _resolve_url(base_url, m.group(1)) if m else ""


def _merge_company(dst: Company, src: Company) -> None:
    """補助ページ(src)の情報で、欠けている項目だけ dst を埋める。"""
    if dst.capital_stock is None:
        dst.capital_stock = src.capital_stock
    if dst.employee_number is None:
        dst.employee_number = src.employee_number
    if not dst.location:
        dst.location = src.location
    if not dst.prefecture:
        dst.prefecture = src.prefecture
    if not dst.phone_number:
        dst.phone_number = src.phone_number


def normalize_company_name(name: str) -> str:
    """会社名を照合用に正規化（法人格・記号・空白を除去）。"""
    if not name:
        return ""
    n = _html.unescape(name)
    for token in ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
                  "(株)", "（株）", "(有)", "（有）", "㈱", "㈲"):
        n = n.replace(token, "")
    n = re.sub(r"[\s　・･,，.。()（）「」【】]", "", n)
    return n.strip().lower()


def _name_matches(a: str, b: str) -> bool:
    """2つの会社名が実質同一かを、正規化後の包含関係でざっくり判定する。
    検索結果のHPが本当にその会社のものかを確かめる（誤エンリッチ防止）。"""
    na, nb = normalize_company_name(a), normalize_company_name(b)
    if not na or not nb:
        return False
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 短い方が3文字以上かつ長い方に含まれていれば同一とみなす
    return len(short) >= 3 and short in long


# 主要な市区（クエリの多様化用。1000件狙いで検索語を増やす）
CITY_HINTS = {
    "東京都": ["新宿区", "世田谷区", "大田区", "足立区", "練馬区", "杉並区", "板橋区",
              "江戸川区", "葛飾区", "江東区", "品川区", "北区", "中野区", "目黒区", "墨田区",
              "豊島区", "文京区", "荒川区", "八王子市", "町田市", "府中市", "調布市", "立川市"],
    "神奈川県": ["横浜市", "川崎市", "相模原市", "藤沢市", "横須賀市", "平塚市", "厚木市",
               "茅ヶ崎市", "大和市", "小田原市", "海老名市", "鎌倉市", "秦野市", "座間市"],
    "千葉県": ["千葉市", "船橋市", "松戸市", "市川市", "柏市", "市原市", "八千代市", "流山市",
             "習志野市", "浦安市", "成田市", "佐倉市", "木更津市", "我孫子市"],
    "埼玉県": ["さいたま市", "川口市", "川越市", "所沢市", "越谷市", "草加市", "春日部市",
             "上尾市", "熊谷市", "朝霞市", "新座市", "戸田市", "狭山市", "入間市"],
}


def generate_queries(criteria: SearchCriteria) -> list[str]:
    """業種×地域（市区で多様化）の検索クエリを生成する。"""
    industries = criteria.industries or criteria.name_keywords[:3] or ["工務店"]
    prefs = criteria.prefectures or ["東京都"]
    queries: list[str] = []
    for pref in prefs:
        cities = CITY_HINTS.get(pref, [""])
        for industry in industries:
            queries.append(f"{industry} {pref} 会社概要")
            for city in cities:
                loc = f"{pref}{city}" if city else pref
                queries.append(f"{industry} {loc}")
                queries.append(f"{industry} {loc} 公式")
    # 重複除去（順序維持）
    seen = set()
    out = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


# ---------------------------------------------------------------------------
# 検索プロバイダ
# ---------------------------------------------------------------------------


class SearchProvider:
    async def search(self, client: httpx.AsyncClient, query: str, max_results: int = 20) -> list[str]:
        raise NotImplementedError


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo HTML版をスクレイプ（APIキー不要）。"""

    URL = "https://html.duckduckgo.com/html/"

    async def search(self, client, query, max_results=20):
        try:
            resp = await client.post(
                self.URL, data={"q": query, "kl": "jp-jp"},
                headers={"User-Agent": USER_AGENT},
                timeout=20.0,
            )
        except httpx.HTTPError as e:
            logger.warning("DuckDuckGo検索失敗: %s", e)
            return []
        return self._parse(resp.text)[:max_results]

    @staticmethod
    def _parse(html_text: str) -> list[str]:
        urls = []
        seen = set()
        # DDGの結果リンクは //duckduckgo.com/l/?uddg=<encoded> 形式（protocol-relative含む）
        for m in re.finditer(r'href="([^"]*[?&]uddg=[^"]+)"', html_text):
            um = re.search(r"uddg=([^&]+)", m.group(1))
            if um:
                u = unquote(um.group(1))
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
        if not urls:
            # 直接リンク形式のフォールバック
            for m in re.finditer(r'class="result__a"[^>]*href="(https?://[^"]+)"', html_text):
                u = _html.unescape(m.group(1))
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
        return urls


class SerperProvider(SearchProvider):
    """Serper.dev（Google検索API・無料枠あり）。search_api_keyがある場合に使う。"""

    URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, client, query, max_results=20):
        try:
            resp = await client.post(
                self.URL,
                json={"q": query, "gl": "jp", "hl": "ja", "num": max_results},
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                timeout=20.0,
            )
            data = resp.json()
        except Exception as e:
            logger.warning("Serper検索失敗: %s", e)
            return []
        return [item.get("link") for item in data.get("organic", []) if item.get("link")]


def make_provider() -> SearchProvider:
    key = os.environ.get("SEARCH_API_KEY", "")
    if key:
        return SerperProvider(key)
    return DuckDuckGoProvider()


# ---------------------------------------------------------------------------
# AIフォールバック（迷った会社だけをHaikuで確認・抽出する。従量課金を最小化）
# ---------------------------------------------------------------------------

_AI_SYSTEM = (
    "あなたは企業の公式サイト判定と連絡先抽出のアシスタントです。"
    "与えられた会社名と、検索で見つかったWebページ候補（本文抜粋）から、"
    "その会社の公式サイトである候補を1つだけ選び、電話番号（日本の固定/フリーダイヤル/携帯）を"
    "抽出します。必ず次のJSONだけを出力してください（前後に説明文を付けない）:\n"
    '{"best_index": <該当候補の番号 or 該当なしは-1>, "phone_number": "<電話番号 or 空文字>"}'
)


def _parse_json_obj(text: str):
    """モデル出力から最初のJSONオブジェクトを取り出す（緩めにパース）。"""
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


class AIExtractor:
    """正規表現/名寄せで判断がつかない会社だけを、AI(Haiku)で確認・抽出する。

    - 既定モデルは Claude Haiku 4.5（現行で最安。$1/$5 per MTok）
    - ANTHROPIC_API_KEY が無ければ enabled=False となり、一切APIを叩かない（＝従量課金ゼロ）
    - 候補は最大3件・各本文1500字までに切り詰めて渡すので、1回あたりのコストは小さい
    """

    MODEL = "claude-haiku-4-5"
    MAX_CANDIDATES = 3
    SNIPPET_CHARS = 1500

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or self.MODEL
        self._client = None
        self.calls = 0  # 実際にAPIを叩いた回数（コスト可視化用）

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def pick_and_extract(self, company_name: str, candidates: list) -> dict:
        """candidates: [(url, cleaned_text), ...] から公式HPを選び電話番号を抽出する。

        戻り値: {"url": str, "phone": str} または None（該当なし/未設定/失敗時）。
        """
        if not self.enabled or not candidates:
            return None
        cands = candidates[: self.MAX_CANDIDATES]
        blocks = []
        for i, (url, text) in enumerate(cands):
            snippet = (text or "")[: self.SNIPPET_CHARS]
            blocks.append(f"[候補{i}] URL: {url}\n本文抜粋: {snippet}")
        user = (
            f"会社名: {company_name}\n\n"
            "次の候補から、この会社の公式サイトを1つ選び、電話番号を抽出してください。"
            "該当が無ければ best_index を -1 にしてください。\n\n"
            + "\n\n".join(blocks)
        )
        try:
            client = self._get_client()
            resp = await client.messages.create(
                model=self.model,
                max_tokens=200,
                system=_AI_SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
            self.calls += 1
        except Exception as e:  # SDK未導入・キー不正・通信失敗など
            logger.warning("AI抽出に失敗（無料分の結果のみ使用）: %s", e)
            return None
        text = ""
        for b in resp.content:
            if getattr(b, "type", "") == "text":
                text = b.text
                break
        data = _parse_json_obj(text)
        if not data:
            return None
        idx = data.get("best_index", -1)
        if idx is None or idx < 0 or idx >= len(cands):
            return None
        return {"url": cands[idx][0], "phone": (data.get("phone_number") or "").strip()}


# ---------------------------------------------------------------------------
# 探索本体
# ---------------------------------------------------------------------------

ProgressCallback = "callable"


class WebFinder:
    """条件に合う企業HPをWebから探してリスト化する。"""

    def __init__(self, provider: SearchProvider = None):
        self.provider = provider or make_provider()

    async def find(
        self,
        criteria: SearchCriteria,
        *,
        fetch_profile: bool = True,
        include_unknown_employee: bool = True,
        strict_capital: bool = False,
        progress=None,
        max_queries: int = 1200,
    ) -> tuple[list[Company], BuildStats]:
        stats = BuildStats()
        target = criteria.target_count
        found: dict[str, Company] = {}  # domain -> Company
        prefs = set(criteria.prefectures)
        queries = generate_queries(criteria)[:max_queries]
        sem = asyncio.Semaphore(4)

        async def emit(phase, detail=""):
            if progress:
                await progress({
                    "phase": phase, "found": len(found), "scanned": stats.candidates,
                    "target": target, "detail": detail,
                })

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for q in queries:
                if len(found) >= target:
                    break
                urls = await self.provider.search(client, q, max_results=20)
                await emit("web", f"検索: {q}")
                # 各URLを処理（同一ドメインは1件）
                async def handle(u):
                    d = domain_of(u)
                    if not d or d in found or is_excluded(u):
                        return
                    async with sem:
                        comp = await self._fetch_and_extract(client, u, fetch_profile)
                    if comp is None:
                        return
                    stats.candidates += 1
                    if prefs and comp.prefecture and comp.prefecture not in prefs:
                        return
                    if not self._passes(comp, criteria, include_unknown_employee, strict_capital):
                        return
                    if d not in found and len(found) < target:
                        found[d] = comp

                await asyncio.gather(*(handle(u) for u in urls))
                await emit("web", f"検索: {q}")
                if len(found) >= target:
                    break

        companies = list(found.values())[:target]
        stats.candidates = max(stats.candidates, len(companies))
        stats.matched = len(companies)
        stats.unknown_employee = sum(1 for c in companies if c.employee_number is None)
        if progress:
            await progress({
                "phase": "done", "found": len(companies), "matched": len(companies),
                "target": target, "exhausted": len(companies) < target,
            })
        return companies, stats

    async def _fetch_and_extract(self, client, url, fetch_profile):
        comp, _ = await self._fetch_and_extract_full(client, url, fetch_profile)
        return comp

    async def _fetch_and_extract_full(self, client, url, fetch_profile):
        """(Company, トップページの本文テキスト) を返す。AIフォールバック用に本文も残す。"""
        try:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=15.0)
            if resp.status_code >= 400 or "text/html" not in resp.headers.get("content-type", "text/html"):
                return None, ""
            html_text = resp.text
        except httpx.HTTPError:
            return None, ""
        comp = extract_company(url, html_text)
        top_text = _clean_text(html_text)
        # 会社概要ページで資本金・従業員数・住所を補完
        if fetch_profile and (comp.capital_stock is None or comp.employee_number is None or not comp.location):
            prof_url = find_profile_url(url, html_text)
            if prof_url and prof_url != url:
                p = await self._fetch_extract_one(client, prof_url)
                if p:
                    _merge_company(comp, p)
        # 電話番号がまだ取れていなければ、お問い合わせ/アクセスページも辿る
        if fetch_profile and not comp.phone_number:
            contact_url = find_contact_url(url, html_text)
            if contact_url and contact_url != url:
                p = await self._fetch_extract_one(client, contact_url)
                if p:
                    _merge_company(comp, p)
        return comp, top_text

    async def _fetch_extract_one(self, client, url):
        """1ページ取得して会社情報を抽出（補助ページ用・失敗時None）。"""
        try:
            r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=15.0)
            if r.status_code >= 400:
                return None
            return extract_company(url, r.text)
        except httpx.HTTPError:
            return None

    # ------------------------------------------------------------------
    # ローカル母集団の無料エンリッチ（社名+住所 → HP/電話番号）
    # ------------------------------------------------------------------

    async def enrich_companies(
        self,
        companies: list[Company],
        *,
        progress=None,
        concurrency: int = 4,
        ai_extractor: "AIExtractor" = None,
    ) -> tuple[list[Company], BuildStats]:
        """社名（＋所在地）だけ分かっている会社に、公開HPと電話番号を無料で補完する。

        既にcompany_urlが分かっていれば検索せずそのHPを取得（検索コストゼロ）。
        無ければ無料のWeb検索で公式HPを探し、社名が一致したものだけ採用する。
        既存の社名・所在地（＝母集団の正）は上書きしない。

        ai_extractor を渡すと、正規表現/名寄せで判断がつかなかった会社「だけ」を
        Haikuで確認・抽出する（ハイブリッド）。大半は無料で片付くので従量課金は小さい。
        """
        stats = BuildStats()
        total = len(companies)
        sem = asyncio.Semaphore(concurrency)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            async def one(comp):
                async with sem:
                    await self._enrich_one(client, comp, ai_extractor)
                stats.candidates += 1
                if comp.phone_number:
                    stats.enriched += 1
                if progress and stats.candidates % 10 == 0:
                    await progress({
                        "phase": "enrich", "found": stats.candidates,
                        "enriched": stats.enriched, "target": total,
                        "ai_calls": ai_extractor.calls if ai_extractor else 0,
                    })
            await asyncio.gather(*(one(c) for c in companies))

        stats.matched = total
        if ai_extractor:
            stats.ai_calls = ai_extractor.calls
        if progress:
            await progress({
                "phase": "done", "found": total, "matched": total,
                "enriched": stats.enriched, "target": total,
                "ai_calls": stats.ai_calls,
            })
        return companies, stats

    async def _enrich_one(self, client, comp: Company, ai_extractor: "AIExtractor" = None):
        page = None
        candidates = []  # (url, top_text) 未解決の候補（AIフォールバック用）
        if comp.company_url:
            page, text = await self._fetch_and_extract_full(client, comp.company_url, True)
            if page and not page.phone_number:
                candidates.append((comp.company_url, text))
        else:
            query = f"{comp.name} {comp.prefecture or ''} 公式".strip()
            try:
                urls = await self.provider.search(client, query, max_results=10)
            except Exception:
                urls = []
            for u in urls:
                if is_excluded(u):
                    continue
                cand, text = await self._fetch_and_extract_full(client, u, True)
                if not cand:
                    continue
                if _name_matches(comp.name, cand.name):
                    comp.company_url = u
                    page = cand
                    if not cand.phone_number:
                        candidates.append((u, text))  # 一致したが電話が無い→AIで拾う
                    break
                # 名寄せで確定できない候補も、AIフォールバック用に控えておく
                if len(candidates) < AIExtractor.MAX_CANDIDATES:
                    candidates.append((u, text))
        if page:
            if not comp.phone_number:
                comp.phone_number = page.phone_number
            if not comp.company_url:
                comp.company_url = page.company_url
            if comp.capital_stock is None:
                comp.capital_stock = page.capital_stock
            if comp.employee_number is None:
                comp.employee_number = page.employee_number
            comp.match_reason = comp.match_reason or "HP・電話番号を補完"

        # 無料の範囲でHPが確定しない or 電話番号が取れなかった会社だけAIに確認させる
        need_ai = ai_extractor and ai_extractor.enabled and candidates and (
            not comp.company_url or not comp.phone_number
        )
        if need_ai:
            result = await ai_extractor.pick_and_extract(comp.name, candidates)
            if result:
                if not comp.company_url and result.get("url"):
                    comp.company_url = result["url"]
                if not comp.phone_number and result.get("phone"):
                    comp.phone_number = result["phone"]
                comp.match_reason = comp.match_reason or "AIでHP・電話番号を確認"

    @staticmethod
    def _passes(c: Company, criteria: SearchCriteria, include_unknown_employee: bool, strict_capital: bool) -> bool:
        if c.capital_stock is not None:
            if criteria.capital_max is not None and c.capital_stock > criteria.capital_max:
                return False
            if criteria.capital_min is not None and c.capital_stock < criteria.capital_min:
                return False
        elif strict_capital and (criteria.capital_max is not None or criteria.capital_min is not None):
            return False
        if c.employee_number is not None:
            if criteria.employee_min is not None and c.employee_number < criteria.employee_min:
                return False
            if criteria.employee_max is not None and c.employee_number > criteria.employee_max:
                return False
        else:
            if (criteria.employee_min is not None or criteria.employee_max is not None) \
                    and not include_unknown_employee:
                return False
        return True
