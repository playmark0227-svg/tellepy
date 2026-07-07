"""list_builder のオフライン単体テスト

外部API（gBizINFO / Claude）に接続せず、パース・フィルタ・CSV・デモ生成の
純粋ロジックを検証する。実行: python test_list_builder.py
"""

import asyncio
import csv
import io

from list_builder import (
    Company,
    InquiryParser,
    ListBuilder,
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
    call_rows = list(csv.reader(io.StringIO(call)))
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
    ]
    for t in tests:
        t()
    print(f"\n全 {len(tests)} テスト成功 ✅")
