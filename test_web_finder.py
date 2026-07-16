"""web_finder のオフライン単体テスト（ネットワーク不使用）

実際のWebアクセスは実行環境で行うため、ここでは抽出・判定・クエリ生成・
検索結果パースといった純ロジックをフィクスチャで検証する。
実行: python test_web_finder.py
"""

import asyncio

from list_builder import Company, SearchCriteria
from web_finder import (
    DuckDuckGoProvider,
    WebFinder,
    _name_matches,
    domain_of,
    extract_company,
    find_contact_url,
    find_profile_url,
    generate_queries,
    is_excluded,
    normalize_company_name,
)

SAMPLE_HP = """
<html><head>
<title>株式会社まごころ工務店｜東京都世田谷区の注文住宅・リフォーム</title>
<meta property="og:site_name" content="株式会社まごころ工務店">
</head><body>
<header>ようこそ</header>
<div class="info">〒155-0031 東京都世田谷区北沢2-1-1 まごころビル3F</div>
<div>TEL：03-1234-5678 / FAX：03-1234-5679</div>
<section id="company">
  <p>資本金：800万円</p>
  <p>従業員数 14名</p>
</section>
<a href="/company/about.html">会社概要はこちら</a>
</body></html>
"""

# 会社概要が別ページにある例（トップには資本金/従業員なし）
TOP_NO_PROFILE = """
<html><head><title>ハマノ不動産 - 横浜の不動産</title></head><body>
<p>神奈川県横浜市港北区新横浜1-2-3</p>
<p>お問い合わせ 045-999-8888</p>
<a href="https://hamano.example.jp/about">会社案内</a>
</body></html>
"""


def test_domain_of():
    assert domain_of("https://www.example.co.jp/path") == "example.co.jp"
    assert domain_of("https://sub.foo.co.jp/") == "foo.co.jp"
    assert domain_of("http://example.com") == "example.com"
    assert domain_of("https://shop.example.jp") == "example.jp"
    print("✓ ドメイン抽出（co.jp/サブドメイン/.com）")


def test_is_excluded():
    assert is_excluded("https://itp.ne.jp/xxx") is True          # タウンページ
    assert is_excluded("https://www.city.yokohama.lg.jp/") is True  # 行政
    assert is_excluded("https://indeed.com/jobs") is True          # 求人
    assert is_excluded("https://magokoro-koumuten.co.jp/") is False  # 企業HP
    print("✓ 除外ドメイン判定（ディレクトリ/行政/求人を除外）")


def test_extract_company():
    c = extract_company("https://magokoro-koumuten.co.jp/", SAMPLE_HP)
    assert c.name == "株式会社まごころ工務店", c.name
    assert c.prefecture == "東京都", c.prefecture
    assert c.phone_number.replace(" ", "") == "03-1234-5678", c.phone_number
    assert c.capital_stock == 8_000_000, c.capital_stock
    assert c.employee_number == 14, c.employee_number
    assert "東京都世田谷区" in c.location, c.location
    assert c.company_url == "https://magokoro-koumuten.co.jp/"
    print("✓ HPから会社情報抽出（社名/電話/住所/資本金/従業員数）")


def test_find_profile_url():
    assert find_profile_url("https://ex.co.jp/", SAMPLE_HP) == "https://ex.co.jp/company/about.html"
    assert find_profile_url("https://x.jp/", TOP_NO_PROFILE) == "https://hamano.example.jp/about"
    print("✓ 会社概要ページのURL解決（相対/絶対）")


def test_phone_prefecture_only_top():
    c = extract_company("https://hamano.example.jp/", TOP_NO_PROFILE)
    assert c.name == "ハマノ不動産", c.name
    assert c.prefecture == "神奈川県"
    assert c.phone_number.replace(" ", "") == "045-999-8888"
    assert c.capital_stock is None and c.employee_number is None  # トップには無い
    print("✓ トップに資本金/従業員が無いHPの抽出（電話・都道府県は取得）")


def test_generate_queries():
    c = SearchCriteria(industries=["工務店", "不動産"], prefectures=["東京都", "神奈川県"])
    qs = generate_queries(c)
    assert any("工務店 東京都" in q for q in qs)
    assert any("不動産 神奈川県横浜市" in q for q in qs)
    assert any("会社概要" in q for q in qs)
    assert len(qs) == len(set(qs)), "重複が無い"
    assert len(qs) > 20, "地域×業種で十分な数のクエリ"
    print(f"✓ 検索クエリ生成（{len(qs)}クエリ・業種×地域）")


def test_ddg_parse():
    ddg_html = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fmagokoro-koumuten.co.jp%2F&rut=aaa">まごころ工務店</a>
    </div>
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fhamano.example.jp%2F&rut=bbb">ハマノ不動産</a>
    </div>
    """
    urls = DuckDuckGoProvider._parse(ddg_html)
    assert "https://magokoro-koumuten.co.jp/" in urls, urls
    assert "https://hamano.example.jp/" in urls, urls
    assert len(urls) == 2
    print("✓ DuckDuckGo検索結果のパース（uddgデコード）")


def test_passes_filter():
    c = SearchCriteria(employee_min=10, employee_max=20, capital_max=10_000_000)
    from web_finder import WebFinder as WF
    ok = extract_company("https://magokoro-koumuten.co.jp/", SAMPLE_HP)  # emp14, cap800万
    assert WF._passes(ok, c, include_unknown_employee=True, strict_capital=False) is True
    ng = extract_company("https://hamano.example.jp/", TOP_NO_PROFILE)   # emp/cap不明
    assert WF._passes(ng, c, include_unknown_employee=True, strict_capital=False) is True
    assert WF._passes(ng, c, include_unknown_employee=False, strict_capital=False) is False
    print("✓ 条件判定（会社概要が取れた社は厳密判定・不明は含む/除外を選択）")


def test_web_find_with_fake_provider():
    """検索プロバイダとHTTPをモックして、探索ループが目標件数まで集めることを確認"""
    import httpx

    class FakeProvider:
        def __init__(self):
            self.n = 0

        async def search(self, client, query, max_results=20):
            # クエリごとに個別ドメインのHPを3つ返す
            out = []
            for _ in range(3):
                self.n += 1
                out.append(f"https://company{self.n}.com/")
            return out

    def handler(request):
        url = str(request.url)
        num = int("".join(ch for ch in url if ch.isdigit()) or "0")
        pref = "東京都世田谷区" if num % 2 == 0 else "神奈川県横浜市港北区"
        body = f"""<html><head><title>株式会社テスト{num}</title></head>
        <body><p>〒155-0031 {pref}1-2-3</p><p>TEL 03-1111-2222</p>
        <p>従業員数 15名</p><p>資本金 500万円</p></body></html>"""
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    async def run():
        finder = WebFinder(provider=FakeProvider())
        # httpxのトランスポートをモックに差し替える
        transport = httpx.MockTransport(handler)
        orig = httpx.AsyncClient

        def patched(*a, **k):
            k["transport"] = transport
            return orig(*a, **k)

        httpx.AsyncClient = patched
        try:
            criteria = SearchCriteria(
                industries=["工務店"], prefectures=["東京都", "神奈川県"],
                employee_min=10, employee_max=20, capital_max=10_000_000, target_count=15,
            )
            companies, stats = await finder.find(criteria, fetch_profile=False)
        finally:
            httpx.AsyncClient = orig
        return companies, stats

    companies, stats = asyncio.run(run())
    assert len(companies) == 15, len(companies)
    for c in companies:
        assert c.company_url and c.phone_number == "03-1111-2222"
        assert c.prefecture in ("東京都", "神奈川県")
    print(f"✓ 探索ループ（モックWeb）で目標到達（{len(companies)}社・電話番号付き）")


# tel:リンクがある例（本文先頭のフリーダイヤルより tel: の代表番号を優先）
TEL_LINK_HP = """
<html><head><title>株式会社サンプル建設</title></head><body>
<p>フリーダイヤル 0120-000-111（受付窓口）</p>
<p>本社代表: <a href="tel:03-3999-8888">お電話はこちら</a></p>
</body></html>
"""

# 電話番号がトップに無く、お問い合わせページにある例
TOP_NO_PHONE = """
<html><head><title>ミライ工務店｜埼玉</title></head><body>
<p>埼玉県さいたま市大宮区1-1</p>
<a href="/contact/">お問い合わせはこちら</a>
</body></html>
"""
CONTACT_PAGE = """
<html><head><title>お問い合わせ｜ミライ工務店</title></head><body>
<p>電話：<a href="tel:048-555-1234">048-555-1234</a></p>
</body></html>
"""


def test_tel_link_phone():
    c = extract_company("https://sample-kensetsu.co.jp/", TEL_LINK_HP)
    # tel:リンクの番号を優先して拾う（フリーダイヤルの誤検出を避ける）
    assert c.phone_number.replace(" ", "") == "03-3999-8888", c.phone_number
    print("✓ tel:リンクを最優先で電話番号抽出")


def test_find_contact_url():
    assert find_contact_url("https://mirai.co.jp/", TOP_NO_PHONE) == "https://mirai.co.jp/contact/"
    print("✓ お問い合わせページのURL解決")


def test_normalize_company_name():
    assert normalize_company_name("株式会社 まごころ工務店") == "まごころ工務店"
    assert normalize_company_name("（株）ハマノ不動産") == "ハマノ不動産"
    assert normalize_company_name("有限会社 山田・建設") == "山田建設"
    print("✓ 会社名の正規化（法人格・記号・空白除去）")


def test_name_matches():
    assert _name_matches("株式会社まごころ工務店", "まごころ工務店") is True
    assert _name_matches("ハマノ不動産", "株式会社ハマノ不動産｜横浜") is True  # 包含関係で一致
    assert _name_matches("株式会社まごころ工務店", "田中不動産") is False
    assert _name_matches("株式会社A", "株式会社A") is False  # 正規化後3文字未満は不一致
    print("✓ 会社名の一致判定（誤エンリッチ防止）")


class _StubProvider:
    async def search(self, client, query, max_results=20):
        return []


def test_contact_page_follow():
    """トップに電話が無く、お問い合わせページを辿って電話番号を補完する"""
    import httpx

    def handler(request):
        url = str(request.url)
        body = CONTACT_PAGE if "contact" in url else TOP_NO_PHONE
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    async def run():
        finder = WebFinder(provider=_StubProvider())
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            return await finder._fetch_and_extract(client, "https://mirai.co.jp/", True)

    comp = asyncio.run(run())
    assert comp is not None
    assert comp.phone_number.replace(" ", "") == "048-555-1234", comp.phone_number
    print("✓ お問い合わせページを辿って電話番号を補完")


def test_enrich_companies():
    """社名だけの母集団に、無料Web検索でHP・電話番号を補完する"""
    import httpx

    class FakeProvider:
        async def search(self, client, query, max_results=20):
            # 「まごころ工務店」の検索はHPを返す。ダミー社名の検索は無関係サイト。
            if "まごころ" in query:
                return ["https://magokoro-koumuten.co.jp/"]
            return ["https://unrelated.example.com/"]

    def handler(request):
        url = str(request.url)
        if "magokoro" in url:
            body = SAMPLE_HP
        else:
            body = "<html><head><title>無関係な会社</title></head><body>別の会社です</body></html>"
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    async def run():
        finder = WebFinder(provider=FakeProvider())
        transport = httpx.MockTransport(handler)
        orig = httpx.AsyncClient

        def patched(*a, **k):
            k["transport"] = transport
            return orig(*a, **k)

        httpx.AsyncClient = patched
        try:
            companies = [
                Company(name="株式会社まごころ工務店", prefecture="東京都", location="東京都世田谷区"),
                Company(name="実在しないダミー商店", prefecture="東京都"),
            ]
            return await finder.enrich_companies(companies)
        finally:
            httpx.AsyncClient = orig

    companies, stats = asyncio.run(run())
    magokoro = companies[0]
    assert magokoro.company_url == "https://magokoro-koumuten.co.jp/", magokoro.company_url
    assert magokoro.phone_number.replace(" ", "") == "03-1234-5678", magokoro.phone_number
    # 名前が一致しないサイトはエンリッチしない（company_urlは空のまま）
    assert companies[1].company_url == "", companies[1].company_url
    assert stats.enriched == 1, stats.enriched
    print("✓ ローカル母集団の無料エンリッチ（社名一致のみHP採用）")


def test_ai_extractor_gating():
    """AIフォールバックはキー未設定なら無効（＝従量課金ゼロ）。JSONパースも確認。"""
    from web_finder import AIExtractor, _parse_json_obj
    assert AIExtractor(api_key="").enabled is False       # キー無し→AIを叩かない
    assert AIExtractor(api_key="sk-xxx").enabled is True
    assert _parse_json_obj('{"best_index": 1, "phone_number": "03-1-2"}')["best_index"] == 1
    # 前後に説明文が付いても最初のJSONを拾う
    assert _parse_json_obj('答え: {"best_index": -1, "phone_number": ""} です')["best_index"] == -1
    assert _parse_json_obj("not json") is None
    print("✓ AIフォールバックの有効/無効判定（キー未設定なら従量課金ゼロ）")


def test_ai_fallback_enrich():
    """名寄せで確定できない会社だけAI(モック)で確認し、HP・電話番号を補完する"""
    import httpx

    class FakeProvider:
        async def search(self, client, query, max_results=20):
            return ["https://kaitai-test.co.jp/"]

    def handler(request):
        # 社名がタイトルに出ず、電話番号も無いページ（無料の名寄せ・正規表現では確定できない）
        body = ("<html><head><title>解体・スクラップのケンセツ</title></head>"
                "<body><p>東京都墨田区で解体工事を承ります</p></body></html>")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    class FakeAI:
        """Haikuの代わりに、候補の先頭を公式と判定して電話番号を返すモック。"""
        MAX_CANDIDATES = 3
        enabled = True

        def __init__(self):
            self.calls = 0

        async def pick_and_extract(self, name, candidates):
            self.calls += 1
            return {"url": candidates[0][0], "phone": "03-5555-0000"}

    async def run():
        ai = FakeAI()
        finder = WebFinder(provider=FakeProvider())
        transport = httpx.MockTransport(handler)
        orig = httpx.AsyncClient

        def patched(*a, **k):
            k["transport"] = transport
            return orig(*a, **k)

        httpx.AsyncClient = patched
        try:
            companies = [Company(name="株式会社テスト解体", prefecture="東京都")]
            comps, stats = await finder.enrich_companies(companies, ai_extractor=ai)
        finally:
            httpx.AsyncClient = orig
        return comps, stats, ai

    comps, stats, ai = asyncio.run(run())
    c = comps[0]
    assert c.company_url == "https://kaitai-test.co.jp/", c.company_url
    assert c.phone_number == "03-5555-0000", c.phone_number
    assert ai.calls == 1, ai.calls           # 迷った1社だけAIを叩いた
    assert stats.ai_calls == 1, stats.ai_calls
    print("✓ AIフォールバック（迷った会社だけHaikuで確認・電話番号を補完）")


def test_ai_not_used_when_free_resolves():
    """無料の名寄せ＋tel:で確定できる会社にはAIを一切使わない（＝コストをかけない）"""
    import httpx

    class FakeProvider:
        async def search(self, client, query, max_results=20):
            return ["https://magokoro-koumuten.co.jp/"]

    def handler(request):
        return httpx.Response(200, text=SAMPLE_HP, headers={"content-type": "text/html"})

    class CountingAI:
        MAX_CANDIDATES = 3
        enabled = True

        def __init__(self):
            self.calls = 0

        async def pick_and_extract(self, name, candidates):
            self.calls += 1
            return None

    async def run():
        ai = CountingAI()
        finder = WebFinder(provider=FakeProvider())
        transport = httpx.MockTransport(handler)
        orig = httpx.AsyncClient

        def patched(*a, **k):
            k["transport"] = transport
            return orig(*a, **k)

        httpx.AsyncClient = patched
        try:
            companies = [Company(name="株式会社まごころ工務店", prefecture="東京都")]
            comps, stats = await finder.enrich_companies(companies, ai_extractor=ai)
        finally:
            httpx.AsyncClient = orig
        return comps, stats, ai

    comps, stats, ai = asyncio.run(run())
    assert comps[0].phone_number.replace(" ", "") == "03-1234-5678"
    assert ai.calls == 0, ai.calls           # 無料で片付いたのでAIは未使用
    print("✓ 無料で確定できる会社にはAIを使わない（従量課金を最小化）")


if __name__ == "__main__":
    tests = [
        test_domain_of,
        test_is_excluded,
        test_extract_company,
        test_find_profile_url,
        test_phone_prefecture_only_top,
        test_generate_queries,
        test_ddg_parse,
        test_passes_filter,
        test_web_find_with_fake_provider,
        test_tel_link_phone,
        test_find_contact_url,
        test_normalize_company_name,
        test_name_matches,
        test_contact_page_follow,
        test_enrich_companies,
        test_ai_extractor_gating,
        test_ai_fallback_enrich,
        test_ai_not_used_when_free_resolves,
    ]
    for t in tests:
        t()
    print(f"\n全 {len(tests)} テスト成功 ✅")
