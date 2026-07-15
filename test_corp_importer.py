"""corp_importer のオフライン単体テスト（ネットワーク不使用）

国税庁 法人番号 全件データ（30列・ヘッダ無し）を模したCSVを使って、
ストリーミング読み取り・履歴/除外/閉鎖フィルタ・都道府県絞り込み・
郵便番号整形・変換出力を検証する。
実行: python test_corp_importer.py
"""

import csv
import tempfile
from pathlib import Path

from corp_importer import (
    OUT_COLUMNS,
    _format_postal,
    _parse_prefectures,
    import_nta,
    iter_companies,
)


def make_row(corporate_number, name, pref, city="", street="", postcode="",
             close_date="", latest="1", hihyoji="0"):
    """国税庁 全件CSVの1行（30列）を組み立てる。"""
    row = [""] * 30
    row[1] = corporate_number
    row[6] = name
    row[8] = "301"          # 法人種別（ダミー）
    row[9] = pref
    row[10] = city
    row[11] = street
    row[15] = postcode
    row[18] = close_date
    row[23] = latest        # 最新履歴
    row[29] = hihyoji       # 検索対象除外
    return row


def write_csv(rows) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="nta_test_")) / "nta.csv"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for r in rows:
            writer.writerow(r)
    return tmp


def test_format_postal():
    assert _format_postal("1500001") == "150-0001"
    assert _format_postal("150-0001") == "150-0001"
    assert _format_postal("〒150-0001") == "150-0001"
    assert _format_postal("") == ""
    print("✓ 郵便番号の整形（7桁→ハイフン区切り）")


def test_basic_parse():
    rows = [
        make_row("1010001000001", "株式会社まごころ工務店", "東京都", "世田谷区", "北沢2-1-1", "1550031"),
    ]
    path = write_csv(rows)
    out = list(iter_companies(path))
    assert len(out) == 1, out
    c = out[0]
    assert c["法人番号"] == "1010001000001"
    assert c["法人名"] == "株式会社まごころ工務店"
    assert c["所在地"] == "東京都世田谷区北沢2-1-1", c["所在地"]
    assert c["郵便番号"] == "155-0031", c["郵便番号"]
    assert list(c.keys()) == OUT_COLUMNS
    print("✓ 基本パース（社名・所在地連結・郵便番号）")


def test_latest_and_hihyoji_filter():
    rows = [
        make_row("1", "最新の会社", "東京都", latest="1"),
        make_row("2", "旧履歴の会社", "東京都", latest="0"),      # 最新でない→除外
        make_row("3", "除外対象の会社", "東京都", hihyoji="1"),   # 検索対象除外→除外
    ]
    path = write_csv(rows)
    names = [c["法人名"] for c in iter_companies(path)]
    assert names == ["最新の会社"], names
    print("✓ 最新履歴フラグ・検索対象除外フラグでフィルタ")


def test_closed_filter():
    rows = [
        make_row("1", "現役の会社", "東京都"),
        make_row("2", "閉鎖済みの会社", "東京都", close_date="2020-03-31"),
    ]
    path = write_csv(rows)
    active = [c["法人名"] for c in iter_companies(path)]
    assert active == ["現役の会社"], active
    both = [c["法人名"] for c in iter_companies(path, include_closed=True)]
    assert set(both) == {"現役の会社", "閉鎖済みの会社"}, both
    print("✓ 登記閉鎖フィルタ（既定は除外・include_closedで含む）")


def test_prefecture_filter():
    rows = [
        make_row("1", "東京の会社", "東京都"),
        make_row("2", "神奈川の会社", "神奈川県"),
        make_row("3", "大阪の会社", "大阪府"),
    ]
    path = write_csv(rows)
    names = [c["法人名"] for c in iter_companies(path, prefectures={"東京都", "神奈川県"})]
    assert set(names) == {"東京の会社", "神奈川の会社"}, names
    print("✓ 都道府県フィルタ（一都三県などで絞れる）")


def test_short_row_skipped():
    # 列数不足の壊れた行はスキップ（例外を出さない）
    path = write_csv([["1", "2", "3"], make_row("1", "正常な会社", "東京都")])
    names = [c["法人名"] for c in iter_companies(path)]
    assert names == ["正常な会社"], names
    print("✓ 列数不足の行はスキップ")


def test_import_nta_writes_csv():
    rows = [
        make_row("1010001000001", "株式会社A建設", "東京都", "新宿区", "1-1", "1600001"),
        make_row("2020002000002", "有限会社B不動産", "神奈川県", "横浜市", "2-2", "2200001"),
        make_row("3", "旧履歴", "東京都", latest="0"),  # 除外される
    ]
    src = write_csv(rows)
    out = Path(tempfile.mkdtemp(prefix="nta_out_")) / "companies.csv"
    n = import_nta(src, out)
    assert n == 2, n
    # BOM付きUTF-8で書けているか & ヘッダ + 2件
    text = out.read_text(encoding="utf-8-sig")
    reader = list(csv.DictReader(text.splitlines()))
    assert len(reader) == 2, reader
    assert reader[0]["法人名"] == "株式会社A建設"
    assert reader[0]["所在地"] == "東京都新宿区1-1"
    assert reader[1]["郵便番号"] == "220-0001"
    print("✓ telepy形式CSVへの変換出力（件数・ヘッダ・内容）")


def test_parse_prefectures():
    assert _parse_prefectures("東京都,神奈川県") == ["東京都", "神奈川県"]
    assert _parse_prefectures("東京、神奈川") == ["東京都", "神奈川県"]  # 「都/県」補完・読点対応
    assert _parse_prefectures("千葉,埼玉") == ["千葉県", "埼玉県"]
    assert _parse_prefectures("存在しない県") == []  # 未知は無視
    print("✓ 都道府県引数のパース（略称補完・読点区切り）")


if __name__ == "__main__":
    tests = [
        test_format_postal,
        test_basic_parse,
        test_latest_and_hihyoji_filter,
        test_closed_filter,
        test_prefecture_filter,
        test_short_row_skipped,
        test_import_nta_writes_csv,
        test_parse_prefectures,
    ]
    for t in tests:
        t()
    print(f"\n全 {len(tests)} テスト成功 ✅")
