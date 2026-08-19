"""list_builder のオフライン単体テスト

外部API（gBizINFO / Claude）に接続せず、パース・フィルタ・CSV・デモ生成の
純粋ロジックを検証する。実行: python test_list_builder.py
"""

import asyncio
import csv
import io

import os
import tempfile

from list_builder import (
    Company,
    InquiryParser,
    ListBuilder,
    LocalDataSource,
    SearchCriteria,
    normalize_prefecture,
    to_call_csv,
    to_csv,
    _parse_capital,
    _demo_companies,
)

SAMPLE_INQUIRY = (
    "工務店、不動産のリスト作成をお願いしたくお繋ぎいただきました！\n"
    "規模感は、従業員数10-20名、資本金1000万円以下、東京と神奈川で1000件程お願いできますと幸いです。"
)


def test_prefecture_normalization():
    assert normalize_prefecture("東京都") == "13"
    assert normalize_prefecture("東京") == "13"
    assert normalize_prefecture("神奈川") == "14"
    assert normalize_prefecture("神奈川県") == "14"
    assert normalize_prefecture("大阪") == "27"
    assert normalize_prefecture("存在しない県") is None
    assert normalize_prefecture("") is None
    print("✓ 都道府県の正規化")


def test_capital_parsing():
    assert _parse_capital("資本金1000万円以下", "以下") == 10_000_000
    assert _parse_capital("資本金5000万円以下", "以下") == 50_000_000
    assert _parse_capital("資本金1億円以上", "以上") == 100_000_000
    assert _parse_capital("資本金1,000万円以下", "以下") == 10_000_000
    assert _parse_capital("従業員だけ", "以下") is None
    print("✓ 資本金のパース（万/億/カンマ）")


def test_heuristic_parse():
    """APIキーを渡さずヒューリスティックパースを検証"""
    parser = InquiryParser(api_key="")
    criteria = asyncio.run(parser.parse(SAMPLE_INQUIRY))

    assert "工務店" in criteria.industries, criteria.industries
    assert "不動産" in criteria.industries, criteria.industries
    assert "東京都" in criteria.prefectures, criteria.prefectures
    assert "神奈川県" in criteria.prefectures, criteria.prefectures
    assert criteria.employee_min == 10, criteria.employee_min
    assert criteria.employee_max == 20, criteria.employee_max
    assert criteria.capital_max == 10_000_000, criteria.capital_max
    assert criteria.target_count == 1000, criteria.target_count
    # name_keywords がプリセットから補完されている
    assert "工務店" in criteria.name_keywords
    assert "建設" in criteria.name_keywords
    # 都道府県コード変換
    assert set(criteria.prefecture_codes()) == {"13", "14"}
    print("✓ 依頼文のヒューリスティックパース（サンプル文）")


def test_filter_and_rank():
    builder = ListBuilder()
    criteria = SearchCriteria(employee_min=10, employee_max=20, capital_max=10_000_000)
    companies = [
        Company(corporate_number="1", name="A工務店", employee_number=15, capital_stock=5_000_000),  # 一致
        Company(corporate_number="2", name="B建設", employee_number=50, capital_stock=5_000_000),     # 従業員多すぎ→除外
        Company(corporate_number="3", name="C住宅", employee_number=None, capital_stock=8_000_000),   # 従業員不明
        Company(corporate_number="4", name="D不動産", employee_number=12, capital_stock=50_000_000),  # 資本金オーバー→除外
        Company(corporate_number="5", name="Eホーム", employee_number=None, capital_stock=None),       # 全て不明
    ]

    # 不明を含める
    kept = builder._filter_and_rank(companies, criteria, include_unknown_employee=True)
    names = [c.name for c in kept]
    assert "A工務店" in names
    assert "B建設" not in names, "従業員数オーバーは除外されるべき"
    assert "D不動産" not in names, "資本金オーバーは除外されるべき"
    assert "C住宅" in names, "従業員不明でも含めるべき"
    assert "Eホーム" in names
    # ランク: 従業員数一致(A)が先頭
    assert names[0] == "A工務店", names

    # 不明を除外
    kept2 = builder._filter_and_rank(companies, criteria, include_unknown_employee=False)
    names2 = [c.name for c in kept2]
    assert names2 == ["A工務店"], names2
    print("✓ フィルタ・ランク付け（従業員/資本金/不明の扱い）")


def test_csv_output():
    companies = [
        Company(
            corporate_number="1234567890123", name="株式会社テスト工務店",
            prefecture="東京都", location="東京都新宿区1-2-3", postal_code="160-0001",
            capital_stock=5_000_000, employee_number=15, industry="建設",
            founding_year=2000, representative_name="山田太郎",
            company_url="https://example.com", match_reason="属性一致",
        ),
    ]
    detail = to_csv(companies)
    assert detail.startswith("﻿"), "Excel互換のためBOM付きであるべき"
    rows = list(csv.reader(io.StringIO(detail.lstrip("﻿"))))
    assert rows[0][0] == "会社名"
    assert rows[1][0] == "株式会社テスト工務店"
    assert "5000000" in rows[1]

    call = to_call_csv(companies)
    assert call.startswith("﻿"), "Excelで社名が化けないようBOM付きであるべき"
    call_rows = list(csv.reader(io.StringIO(call.lstrip("﻿"))))
    assert call_rows[0] == ["phone_number", "company_name"]
    assert call_rows[1][1] == "株式会社テスト工務店"
    assert call_rows[1][0] == "", "電話番号は空（gBizINFOに無い）"
    print("✓ CSV出力（詳細CSV / 架電用CSV）")


def test_demo_build():
    """デモモードで条件どおりのサンプルが生成される"""
    parser = InquiryParser(api_key="")
    criteria = asyncio.run(parser.parse(SAMPLE_INQUIRY))
    builder = ListBuilder()
    companies, stats = asyncio.run(builder.build(criteria, demo=True))
    assert stats.demo is True
    assert len(companies) > 0
    for c in companies:
        assert c.employee_number is not None
        assert criteria.employee_min <= c.employee_number <= criteria.employee_max
        assert c.capital_stock <= criteria.capital_max
        assert c.prefecture in criteria.prefectures
    print(f"✓ デモモードのビルド（{len(companies)}社生成）")


def test_criteria_roundtrip():
    c = SearchCriteria(industries=["工務店"], prefectures=["東京都"], target_count=500)
    d = c.to_dict()
    c2 = SearchCriteria.from_dict(d)
    assert c2.industries == ["工務店"]
    assert c2.target_count == 500
    # 余計なキーが混ざっても無視される
    c3 = SearchCriteria.from_dict({**d, "unknown_field": 123})
    assert c3.target_count == 500
    print("✓ SearchCriteria の辞書変換（余計なキーを無視）")


def test_target_count_guard():
    parser = InquiryParser(api_key="")
    c = asyncio.run(parser.parse("東京の工務店を99999件"))
    assert c.target_count == 5000, "暴走防止で上限5000にクランプされるべき"
    print("✓ 目標件数の上限ガード")


SAMPLE_CSV = (
    "法人番号,法人名,所在地,資本金,従業員数,業種\n"
    "1,株式会社あおば工務店,東京都新宿区1-1,5000000,14,建設業\n"
    "2,みなと不動産株式会社,神奈川県横浜市西区2-2,8000000,18,不動産取引業\n"
    "3,株式会社おおて住宅,東京都千代田区3-3,300000000,800,総合建設業\n"  # 大企業→従業員/資本金で除外
    "4,大阪ホーム株式会社,大阪府大阪市4-4,4000000,12,建設業\n"  # 地域外→除外
    "5,株式会社かんとう住宅,東京都足立区5-5,,,建設業\n"  # 資本金・従業員数不明
)


def _write_csv(dirpath, name, content, encoding="utf-8"):
    path = os.path.join(dirpath, name)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(content)
    return path


def test_capital_units_and_prefecture_extraction():
    """資本金の単位換算と、実データにありがちな住所からの都道府県判定"""
    from list_builder import _as_yen, _prefecture_from_location
    # 単位を無視すると4〜8桁ずれた金額で絞り込んでしまう
    assert _as_yen("1,000万円") == 10_000_000
    assert _as_yen("1億円") == 100_000_000
    assert _as_yen("1億2000万円") == 120_000_000
    assert _as_yen("10000000") == 10_000_000
    assert _as_yen("非公開") is None and _as_yen("") is None
    # 〒や空白が前置された住所でも都道府県を取りこぼさない
    assert _prefecture_from_location("東京都新宿区1-1") == "東京都"
    assert _prefecture_from_location("〒160-0022 東京都新宿区") == "東京都"
    assert _prefecture_from_location("京都府京都市中京区") == "京都府"
    assert _prefecture_from_location("新宿区西新宿1-1") == ""
    print("✓ 資本金の単位換算と住所からの都道府県判定")


def test_heuristic_kyoto_not_dropped():
    """「京都」を含む依頼文で京都府が落ちない（rstripで'京'になる不具合の再発防止）"""
    parser = InquiryParser(api_key="")
    c = asyncio.run(parser.parse("京都の工務店を50件お願いします"))
    assert "京都府" in c.prefectures, c.prefectures
    assert "東京都" not in c.prefectures, c.prefectures
    print("✓ 「京都」の依頼で京都府を正しく抽出（東京都と誤認しない）")


def test_local_dedupes_across_files():
    """複数CSVに同じ会社がいても1件にまとめる（同じ会社に2回架電しないため）"""
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "a.csv", SAMPLE_CSV)
        _write_csv(d, "b.csv", SAMPLE_CSV)  # まったく同じ内容をもう1ファイル
        src = LocalDataSource(data_dir=d)
        criteria = SearchCriteria(
            name_keywords=["工務店", "不動産", "住宅"],
            prefectures=["東京都", "神奈川県"], target_count=100,
        )
        cand, _ = src.search(criteria)
        names = [c.name for c in cand]
        assert len(names) == len(set(names)), names
    print(f"✓ 複数CSVをまたいだ重複排除（{len(names)}社・重複なし）")


def test_capital_filter_skipped_when_no_capital_column():
    """資本金の列が無いデータ（国税庁）で資本金条件により0件になってしまわない"""
    def nta_row(cn, name, pref, city):
        row = [""] * 30
        row[1] = cn; row[6] = name; row[8] = "301"
        row[9] = pref; row[10] = city; row[15] = "1000001"; row[23] = "1"
        return ",".join(row)

    raw = "\n".join([
        nta_row("1010001000001", "株式会社まごころ工務店", "東京都", "世田谷区"),
        nta_row("2020002000002", "ハマノ不動産株式会社", "神奈川県", "横浜市"),
    ]) + "\n"
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "nta_13.csv", raw)
        criteria = SearchCriteria(
            name_keywords=["工務店", "不動産"], prefectures=["東京都", "神奈川県"],
            capital_max=10_000_000, employee_min=10, employee_max=20, target_count=1000,
        )
        builder = ListBuilder(local=LocalDataSource(data_dir=d))
        companies, stats = asyncio.run(builder.build(
            criteria, mode="local", include_unknown_employee=True, strict_capital=True,
        ))
        assert len(companies) == 2, f"資本金の列が無いのに絞り込まれて{len(companies)}件"
        assert stats.capital_filter_skipped is True
    print("✓ 資本金の列が無いデータでは資本金条件を適用しない（0件化を防止）")


def test_capital_filter_is_per_file_not_per_directory():
    """資本金列のあるCSVを1つ足しても、国税庁データ由来の母集団が消えない

    判定をディレクトリ単位でやると、gBizINFOのCSVを1本置いた瞬間に
    「資本金の列がある」と見なされ、資本金未登録の国税庁データ数百万社が
    まとめて捨てられる（＝ファイルを足したのにリストが激減する）。
    """
    def nta_row(cn, name, city):
        row = [""] * 30
        row[1] = cn; row[6] = name; row[8] = "301"
        row[9] = "東京都"; row[10] = city; row[15] = "1000001"; row[23] = "1"
        return ",".join(row)

    criteria = SearchCriteria(
        name_keywords=["工務店"], prefectures=["東京都"],
        capital_max=10_000_000, target_count=1000,
    )
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "nta_13.csv", "\n".join([
            nta_row("1010001000001", "あい工務店", "港区"),
            nta_row("1010001000002", "かき工務店", "港区"),
        ]) + "\n")
        build = lambda: asyncio.run(ListBuilder(local=LocalDataSource(data_dir=d)).build(
            criteria, mode="local", include_unknown_employee=True, strict_capital=True,
        ))
        before = sorted(c.name for c in build()[0])
        assert before == ["あい工務店", "かき工務店"], before

        # 資本金の列を持つCSVを1本追加（資本金5,000万円＝条件オーバーの1社）
        _write_csv(d, "gbiz.csv", (
            "法人番号,法人名,所在地,資本金,従業員数\n"
            "9000000000001,ビッグ工務店株式会社,東京都港区2-2-2,50000000,300\n"
        ))
        after, stats = build()
        names = sorted(c.name for c in after)
        assert names == before, f"ファイルを足したら母集団が消えた: {names}"
        assert "ビッグ工務店株式会社" not in names, "資本金列のある行は条件どおり除外されるべき"
        assert stats.capital_filter_skipped is True
    print("✓ 資本金の絞り込みはファイル単位で判定（混在ディレクトリで母集団が消えない）")


def test_sample_data_is_marked_as_fake():
    """お試し用データしか無いときは、行にも統計にも『架空』と分かる印が付く"""
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "sample_companies.csv", SAMPLE_CSV)
        criteria = SearchCriteria(
            name_keywords=["工務店"], prefectures=["東京都"], target_count=10,
        )
        companies, stats = asyncio.run(
            ListBuilder(local=LocalDataSource(data_dir=d)).build(
                criteria, mode="local", include_unknown_employee=True,
            )
        )
        assert companies, "お試し用データが検索できていない"
        assert stats.using_sample_data is True, "お試し用データを使ったのに統計に出ない"
        assert all(c.from_sample_data for c in companies)
        assert all("お試し" in c.match_reason for c in companies), \
            [c.match_reason for c in companies]

        # 実データがあるときは印が付かない（本物のリストを汚さない）
        _write_csv(d, "real.csv", SAMPLE_CSV)
        companies2, stats2 = asyncio.run(
            ListBuilder(local=LocalDataSource(data_dir=d)).build(
                criteria, mode="local", include_unknown_employee=True,
            )
        )
        assert stats2.using_sample_data is False
        assert not any(c.from_sample_data for c in companies2)
    print("✓ お試し用データは行・統計の両方で『架空』と分かる")


def test_local_progress_reports_scanned_rows():
    """進捗が「走査行数」で刻まれる（該当0件のまま固まって見えないように）"""
    rows = ["法人名,所在地"]
    for i in range(12000):
        rows.append(f"無関係な会社{i},大阪府大阪市北区{i}")
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "big.csv", "\n".join(rows) + "\n")
        seen = []
        criteria = SearchCriteria(name_keywords=["工務店"], prefectures=["東京都"], target_count=10)
        LocalDataSource(data_dir=d).search(criteria, progress=lambda s, f: seen.append(s))
        assert seen, "1件も該当しないと進捗が一度も呼ばれない"
        assert max(seen) >= 10000, seen[-3:]
    print(f"✓ 該当0件でも走査進捗を通知（{len(seen)}回・最大{max(seen):,}行）")


def test_sample_data_excluded_from_real_search():
    """同梱デモの架空企業が本物の架電リストに混ざらない"""
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "sample_companies.csv",
                   "法人名,所在地,電話番号\n株式会社デモ工務店,東京都渋谷区1-1,03-0000-0000\n")
        src = LocalDataSource(data_dir=d)
        # サンプルしか無ければお試しとして使える
        assert [p.name for p in src.available_files()] == ["sample_companies.csv"]
        # 実データを置いたら、サンプルは対象から外れる
        _write_csv(d, "nta_13.csv", "法人名,所在地\n株式会社ほんもの工務店,東京都新宿区1-1\n")
        names = [p.name for p in src.available_files()]
        assert names == ["nta_13.csv"], names
        criteria = SearchCriteria(name_keywords=["工務店"], prefectures=["東京都"], target_count=100)
        got = [c.name for c in src.search(criteria)[0]]
        assert got == ["株式会社ほんもの工務店"], got
    print("✓ 実データがある時はデモCSVを検索対象から除外")


def test_partial_conversion_file_ignored():
    """変換途中の一時ファイル(.csv.part)を検索対象にしない"""
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "nta_13.csv", "法人名,所在地\n株式会社かんせい,東京都新宿区1-1\n")
        _write_csv(d, "nta_14.csv.part", "法人名,所在地\n株式会社とちゅう,東京都新宿区2-2\n")
        names = [p.name for p in LocalDataSource(data_dir=d).available_files()]
        assert names == ["nta_13.csv"], names
    print("✓ 変換途中の一時ファイルは読み込まない")


def test_local_nta_raw_csv():
    """国税庁 全件CSV（ヘッダ無し30列）を data/ に置くだけで検索できる"""
    def nta_row(cn, name, pref, city, street, latest="1", hihyoji="0", close=""):
        row = [""] * 30
        row[1] = cn; row[6] = name; row[8] = "301"
        row[9] = pref; row[10] = city; row[11] = street
        row[15] = "1550031"; row[18] = close; row[23] = latest; row[29] = hihyoji
        return ",".join(row)

    raw = "\n".join([
        nta_row("1010001000001", "株式会社まごころ工務店", "東京都", "世田谷区", "北沢2-1"),
        nta_row("1010001000002", "旧履歴工務店", "東京都", "新宿区", "1-1", latest="0"),
        nta_row("1010001000003", "閉鎖工務店", "東京都", "港区", "2-2", close="2020-01-01"),
        nta_row("1010001000004", "除外工務店", "東京都", "北区", "3-3", hihyoji="1"),
        nta_row("2020002000005", "ハマノ不動産株式会社", "神奈川県", "横浜市", "港北1-2"),
        nta_row("2720002000006", "大阪工務店", "大阪府", "大阪市", "北区1-1"),
    ]) + "\n"

    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "nta_13.csv", raw)
        src = LocalDataSource(data_dir=d)
        criteria = SearchCriteria(
            name_keywords=["工務店", "不動産"],
            prefectures=["東京都", "神奈川県"],
            target_count=100,
        )
        cand, scanned = src.search(criteria)
        names = sorted(c.name for c in cand)
        assert names == ["ハマノ不動産株式会社", "株式会社まごころ工務店"], names
        assert scanned == 6, scanned
        comp = [c for c in cand if "まごころ" in c.name][0]
        assert comp.prefecture == "東京都"
        assert comp.postal_code == "155-0031", comp.postal_code
        assert comp.corporate_number == "1010001000001"
    print("✓ 国税庁 全件CSV（ヘッダ無し）を直接ローカル検索（履歴・閉鎖・除外をフィルタ）")


def test_local_search_and_build():
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "companies.csv", SAMPLE_CSV)
        src = LocalDataSource(data_dir=d)
        assert src.configured

        criteria = SearchCriteria(
            name_keywords=["工務店", "不動産", "住宅"],
            prefectures=["東京都", "神奈川県"],
            employee_min=10, employee_max=20, capital_max=10_000_000,
            target_count=100,
        )
        # 1次フィルタ（社名キーワード＋都道府県）: 大阪ホームは地域外で落ちる
        cand, scanned = src.search(criteria)
        names = [c.name for c in cand]
        assert scanned == 5
        assert "株式会社あおば工務店" in names
        assert "みなと不動産株式会社" in names
        assert "大阪ホーム株式会社" not in names, "大阪は対象外"
        assert "株式会社かんとう住宅" in names

        # ビルド（従業員数レンジ・資本金上限を適用）
        builder = ListBuilder(local=src)
        companies, stats = asyncio.run(
            builder.build(criteria, mode="local", include_unknown_employee=True, strict_capital=True)
        )
        got = [c.name for c in companies]
        assert "株式会社あおば工務店" in got
        assert "みなと不動産株式会社" in got
        assert "株式会社おおて住宅" not in got, "従業員800名・資本金3億は範囲外で除外"
        # 資本金不明＋従業員不明の会社は strict_capital で除外される
        assert "株式会社かんとう住宅" not in got, "資本金未登録は厳密モードで除外"
        assert stats.candidates == 4
        print(f"✓ ローカルCSV検索とビルド（{len(companies)}社）")


def test_local_column_autodetect_and_encoding():
    # 英語ヘッダ + Shift_JIS でも読めること
    csv_en = (
        "corporate_number,name,location,capital_stock,employee_number\n"
        "1,株式会社テスト工務店,東京都港区1-1,5000000,15\n"
    )
    with tempfile.TemporaryDirectory() as d:
        _write_csv(d, "sjis.csv", csv_en, encoding="cp932")
        src = LocalDataSource(data_dir=d)
        criteria = SearchCriteria(name_keywords=["工務店"], prefectures=["東京都"], target_count=10)
        cand, _ = src.search(criteria)
        assert len(cand) == 1
        assert cand[0].name == "株式会社テスト工務店"
        assert cand[0].capital_stock == 5000000
        assert cand[0].employee_number == 15
        assert cand[0].prefecture == "東京都"
        print("✓ 列名の自動判定 + Shift_JIS読み込み")


def test_resolve_mode():
    # ローカルデータが無ければ demo（gBizトークンも無い前提）
    with tempfile.TemporaryDirectory() as d:
        builder = ListBuilder(local=LocalDataSource(data_dir=d))
        # トークン未設定なら auto は demo
        assert builder.resolve_mode("auto") in ("demo", "api")
        assert builder.resolve_mode("local") == "local"
        # ローカルにCSVを置けば auto は local
        _write_csv(d, "x.csv", SAMPLE_CSV)
        assert builder.resolve_mode("auto") == "local"
    print("✓ 検索モードの自動判定")


class FakeGBiz:
    """gBizINFO APIのモック。ネットワークを使わずに探索botのループを検証する。"""

    def __init__(self, per_page, employee_fn=None):
        self.token = "fake-token"
        self.per_page = per_page
        self.employee_fn = employee_fn
        self._counter = 0
        self.detail_calls = 0

    @property
    def configured(self):
        return True

    async def search_page(self, client, *, name=None, prefecture=None,
                          capital_stock_from=None, capital_stock_to=None,
                          employee_number_from=None, employee_number_to=None,
                          page=1, limit=1000):
        if page != 1:
            return []  # 1ページ目だけデータを返す
        pref_name = "東京都" if prefecture == "13" else "神奈川県"
        out = []
        for _ in range(self.per_page):
            self._counter += 1
            cn = f"{self._counter:013d}"
            out.append({
                "corporate_number": cn,
                "name": f"株式会社{name or ''}{cn}",
                "location": f"{pref_name}新宿区1-1",
                "postal_code": "",
            })
        return out

    async def detail(self, client, corporate_number):
        self.detail_calls += 1
        emp = 15
        if self.employee_fn:
            emp = self.employee_fn(int(corporate_number))
        return {"capital_stock": 5000000, "employee_number": emp, "industry": "建設業"}


def test_gbiz_no_token_and_auth_guard():
    """トークン未設定なら接続テストは失敗、APIモードのbuildは明確なエラーになる"""
    from list_builder import GBizClient, GBizAuthError

    client = GBizClient(token="")
    assert client.configured is False
    res = asyncio.run(client.test_connection())
    assert res["ok"] is False
    assert "トークン" in res["message"]

    builder = ListBuilder(gbiz=GBizClient(token=""))
    criteria = SearchCriteria(name_keywords=["工務店"], prefectures=["東京都"], target_count=10)
    raised = False
    try:
        asyncio.run(builder.build(criteria, mode="api"))
    except GBizAuthError as e:
        raised = True
        assert "トークン" in str(e)
    assert raised, "トークン未設定のAPIモードは GBizAuthError を出すべき"
    print("✓ トークン未設定: 接続テスト失敗＆APIモードは明確にエラー")


def _run_build(builder, criteria, **kw):
    progresses = []
    async def prog(p):
        progresses.append(p)
    companies, stats = asyncio.run(builder.build(criteria, progress=prog, **kw))
    return companies, stats, progresses


def test_api_bot_reaches_target():
    """候補が十分あれば目標件数に達したら止まる（それ以上取りすぎない）"""
    fake = FakeGBiz(per_page=20)  # 2県×3キーワード×20 = 120候補
    builder = ListBuilder(gbiz=fake)
    criteria = SearchCriteria(
        name_keywords=["工務店", "建設", "不動産"],
        prefectures=["東京都", "神奈川県"],
        capital_max=10_000_000, target_count=50,
    )
    companies, stats, progresses = _run_build(builder, criteria, mode="api", enrich=False)
    assert len(companies) == 50, len(companies)
    assert stats.candidates == 50, "目標到達で即停止、余分に取得しない"
    done = progresses[-1]
    assert done["phase"] == "done"
    assert done.get("exhausted") in (False, None) or done["found"] == 50
    print(f"✓ 自動巡回bot: 目標到達で停止（{len(companies)}/50, 走査{stats.candidates}）")


def test_api_bot_continues_until_exhausted():
    """候補が足りなければ、取れるだけ取って（枯渇するまで）止まらない"""
    fake = FakeGBiz(per_page=5)  # 2県×3キーワード×5 = 30候補しかない
    builder = ListBuilder(gbiz=fake)
    criteria = SearchCriteria(
        name_keywords=["工務店", "建設", "不動産"],
        prefectures=["東京都", "神奈川県"],
        capital_max=10_000_000, target_count=100,
    )
    companies, stats, progresses = _run_build(builder, criteria, mode="api", enrich=False)
    assert len(companies) == 30, "全候補30件を集めきる"
    assert progresses[-1].get("exhausted") is True, "枯渇フラグが立つ"
    print(f"✓ 自動巡回bot: 枯渇まで探索（{len(companies)}件で全ソース使い切り）")


def test_api_bot_skips_out_of_range_and_keeps_going():
    """従業員数が範囲外の会社は飛ばして、範囲内だけで目標に達するまで続ける"""
    # 偶数法人番号は従業員15（範囲内）、奇数は50（範囲外）
    fake = FakeGBiz(per_page=40, employee_fn=lambda n: 15 if n % 2 == 0 else 50)
    builder = ListBuilder(gbiz=fake)
    criteria = SearchCriteria(
        name_keywords=["工務店", "建設", "不動産"],
        prefectures=["東京都", "神奈川県"],
        employee_min=10, employee_max=20, capital_max=10_000_000, target_count=30,
    )
    companies, stats, _ = _run_build(
        builder, criteria, mode="api", enrich=True, include_unknown_employee=False,
    )
    assert len(companies) == 30, len(companies)
    for c in companies:
        assert c.employee_number == 15, "範囲外(50)は含まれない"
    assert stats.candidates >= 60, "範囲外を飛ばした分だけ多く走査している"
    print(f"✓ 自動巡回bot: 範囲外を飛ばし条件一致で目標達成（走査{stats.candidates}→{len(companies)}）")


if __name__ == "__main__":
    tests = [
        test_prefecture_normalization,
        test_capital_parsing,
        test_heuristic_parse,
        test_filter_and_rank,
        test_csv_output,
        test_demo_build,
        test_criteria_roundtrip,
        test_target_count_guard,
        test_local_search_and_build,
        test_local_column_autodetect_and_encoding,
        test_local_nta_raw_csv,
        test_sample_data_excluded_from_real_search,
        test_partial_conversion_file_ignored,
        test_capital_units_and_prefecture_extraction,
        test_heuristic_kyoto_not_dropped,
        test_local_dedupes_across_files,
        test_capital_filter_skipped_when_no_capital_column,
        test_capital_filter_is_per_file_not_per_directory,
        test_sample_data_is_marked_as_fake,
        test_local_progress_reports_scanned_rows,
        test_resolve_mode,
        test_api_bot_reaches_target,
        test_api_bot_continues_until_exhausted,
        test_api_bot_skips_out_of_range_and_keeps_going,
        test_gbiz_no_token_and_auth_guard,
    ]
    for t in tests:
        t()
    print(f"\n全 {len(tests)} テスト成功 ✅")
