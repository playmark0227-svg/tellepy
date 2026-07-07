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
import logging
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


def extract_company(url: str, html_text: str) -> Company:
    """HPのHTMLから会社情報を抽出する。"""
    text = _clean_text(html_text)
    location = _extract_address(text)
    return Company(
        name=_company_name(html_text, url),
        location=location,
        prefecture=_extract_prefecture(text),
        phone_number=_extract_phone(text),
        capital_stock=_extract_capital(text),
        employee_number=_extract_employees(text),
        company_url=url,
        match_reason="Web検索でHPを発見",
    )


def find_profile_url(base_url: str, html_text: str) -> str:
    """会社概要ページへのリンクを見つけて絶対URLで返す。"""
    m = PROFILE_LINK_RE.search(html_text)
    if not m:
        return ""
    href = _html.unescape(m.group(1)).strip()
    if href.startswith("http"):
        return href
    p = urlparse(base_url)
    if href.startswith("//"):
        return f"{p.scheme}:{href}"
    if href.startswith("/"):
        return f"{p.scheme}://{p.netloc}{href}"
    base = base_url.rsplit("/", 1)[0]
    return f"{base}/{href}"


# 主要な市区（クエリの多様化用。1000件狙いで検索語を増やす）
CITY_HINTS = {
    "東京都": ["新宿区", "世田谷区", "大田区", "足立区", "練馬区", "杉並区", "板橋区",
              "江戸川区", "葛飾区", "江東区", "品川区", "北区", "中野区", "八王子市", "町田市"],
    "神奈川県": ["横浜市", "川崎市", "相模原市", "藤沢市", "横須賀市", "平塚市", "厚木市",
               "茅ヶ崎市", "大和市", "小田原市"],
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
    import os
    key = os.environ.get("SEARCH_API_KEY", "")
    if key:
        return SerperProvider(key)
    return DuckDuckGoProvider()


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
        max_queries: int = 400,
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
        try:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=15.0)
            if resp.status_code >= 400 or "text/html" not in resp.headers.get("content-type", "text/html"):
                return None
            html_text = resp.text
        except httpx.HTTPError:
            return None
        comp = extract_company(url, html_text)
        # 会社概要ページで資本金・従業員数・住所を補完
        if fetch_profile and (comp.capital_stock is None or comp.employee_number is None or not comp.location):
            prof_url = find_profile_url(url, html_text)
            if prof_url and prof_url != url:
                try:
                    r2 = await client.get(prof_url, headers={"User-Agent": USER_AGENT}, timeout=15.0)
                    if r2.status_code < 400:
                        p = extract_company(prof_url, r2.text)
                        comp.capital_stock = comp.capital_stock if comp.capital_stock is not None else p.capital_stock
                        comp.employee_number = comp.employee_number if comp.employee_number is not None else p.employee_number
                        comp.location = comp.location or p.location
                        comp.prefecture = comp.prefecture or p.prefecture
                        comp.phone_number = comp.phone_number or p.phone_number
                except httpx.HTTPError:
                    pass
        return comp

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
