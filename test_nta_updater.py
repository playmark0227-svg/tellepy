"""nta_updater のオフライン単体テスト（ネットワーク不使用）

国税庁の公開ページとzip配布をhttpxのMockTransportで模擬し、
リンク抽出 → ダウンロード → 変換 → 状態記録 → スキップ判定 を検証する。
実行: python test_nta_updater.py
"""

import asyncio
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

import httpx

# テスト用のdataディレクトリに差し替え
_tmp_data = Path(tempfile.mkdtemp(prefix="nta_upd_data_"))
os.environ["LOCAL_DATA_DIR"] = str(_tmp_data)

import list_builder  # noqa: E402
import nta_updater  # noqa: E402
from nta_updater import check_and_update, load_state, parse_zenken_links, status  # noqa: E402

# list_builder.DATA_DIR は環境変数で差し替わるが、nta_updater が import 済みの
# 定数を持つため明示的に上書きする
nta_updater.STATE_PATH = _tmp_data / "nta_state.json"
_orig_out_path = nta_updater._out_path
nta_updater._out_path = lambda code: _tmp_data / f"nta_{code}.csv"


PAGE_HTML = """
<html><body>
<h2>都道府県別（CSV形式・Unicode）</h2>
<a href="/download/zenken/u/11_saitama_all_20260630.zip">埼玉県</a>
<a href="/download/zenken/u/12_chiba_all_20260630.zip">千葉県</a>
<a href="/download/zenken/u/13_tokyo_all_20260630.zip">東京都</a>
<a href="/download/zenken/u/14_kanagawa_all_20260630.zip">神奈川県</a>
<h2>都道府県別（CSV形式・Shift-JIS）</h2>
<a href="/download/zenken/s/13_tokyo_all_20260531.zip">東京都(旧)</a>
</body></html>
"""


def make_row(cn, name, pref, city, street, postcode, latest="1", hihyoji="0", close=""):
    row = [""] * 30
    row[1] = cn; row[6] = name; row[8] = "301"
    row[9] = pref; row[10] = city; row[11] = street
    row[15] = postcode; row[18] = close; row[23] = latest; row[29] = hihyoji
    return row


def make_zip(rows) -> bytes:
    buf_csv = io.StringIO()
    w = csv.writer(buf_csv)
    for r in rows:
        w.writerow(r)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", buf_csv.getvalue())
    return buf.getvalue()


ZIP_DATA = {
    "13": make_zip([
        make_row("1010001000001", "株式会社まごころ工務店", "東京都", "世田谷区", "北沢2-1", "1550031"),
        make_row("1010001000002", "旧履歴の会社", "東京都", "新宿区", "1-1", "1600022", latest="0"),
    ]),
    "14": make_zip([
        make_row("2020002000001", "ハマノ不動産株式会社", "神奈川県", "横浜市", "港北1-2", "2220033"),
    ]),
    "12": make_zip([make_row("3030003000001", "さくら工務店", "千葉県", "船橋市", "本町3", "2730005")]),
    "11": make_zip([make_row("4040004000001", "むさし建設株式会社", "埼玉県", "川口市", "本町1", "3320012")]),
}

request_log = []


def handler(request):
    url = str(request.url)
    request_log.append(url)
    if url.rstrip("/").endswith("zenken"):
        return httpx.Response(200, text=PAGE_HTML, headers={"content-type": "text/html"})
    for code, data in ZIP_DATA.items():
        if f"/{code}_" in url:
            return httpx.Response(200, content=data, headers={
                "content-type": "application/zip",
                "content-length": str(len(data)),
            })
    return httpx.Response(404, text="not found")


def run_update(**kw):
    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://www.houjin-bangou.nta.go.jp",
        ) as client:
            return await check_and_update(http_client=client, **kw)
    return asyncio.run(go())


def test_parse_links():
    links = parse_zenken_links(PAGE_HTML, "https://www.houjin-bangou.nta.go.jp/download/zenken/")
    assert set(links) == {"11", "12", "13", "14"}, links
    url, date = links["13"]
    assert date == "20260630", "新しい日付（Unicode版）を優先: " + date
    assert url.startswith("https://www.houjin-bangou.nta.go.jp/download/zenken/u/"), url
    print("✓ 公開ページからzipリンク抽出（県コード・最新日付を採用）")


def test_first_update_downloads_all():
    result = run_update()
    assert len(result["updated"]) == 4, result
    assert not result["errors"], result["errors"]
    for code in ("11", "12", "13", "14"):
        out = _tmp_data / f"nta_{code}.csv"
        assert out.exists(), out
    # 東京都は「旧履歴」を除外して1社だけ
    tokyo = (_tmp_data / "nta_13.csv").read_text(encoding="utf-8-sig")
    assert "まごころ工務店" in tokyo and "旧履歴" not in tokyo
    st = load_state()
    assert st["東京都"]["date"] == "20260630" and st["東京都"]["rows"] == 1, st["東京都"]
    print("✓ 初回更新: 4県ダウンロード→変換→state記録（履歴フィルタも適用）")


def test_second_update_skips():
    request_log.clear()
    result = run_update()
    assert len(result["skipped"]) == 4, result
    assert not result["updated"]
    # ページ確認の1リクエストのみ（zipは再ダウンロードしない）
    zips = [u for u in request_log if u.endswith(".zip")]
    assert not zips, zips
    print("✓ 2回目: 同じ日付ならダウンロードせずスキップ（差分チェックのみ）")


def test_force_redownloads():
    result = run_update(force=True)
    assert len(result["updated"]) == 4, result
    print("✓ force=True で強制再取得")


def test_status_and_local_search_integration():
    st = status()
    assert st["auto_update"] is True
    assert len([i for i in st["items"] if i["file_exists"]]) == 4, st
    # 変換されたCSVがそのままローカル検索の母集団になる
    src = list_builder.LocalDataSource(data_dir=_tmp_data)
    criteria = list_builder.SearchCriteria(
        name_keywords=["工務店", "不動産", "建設"],
        prefectures=["東京都", "神奈川県", "千葉県", "埼玉県"],
        target_count=100,
    )
    companies, scanned = src.search(criteria)
    names = sorted(c.name for c in companies)
    assert "株式会社まごころ工務店" in names and "ハマノ不動産株式会社" in names, names
    assert len(companies) == 4, names
    print(f"✓ status API＋変換CSVでローカル検索が動く（{len(companies)}社）")


def test_prefecture_config():
    os.environ["NTA_PREFECTURES"] = "東京, 大阪府"
    try:
        prefs = nta_updater.configured_prefectures()
        assert prefs == ["東京都", "大阪府"], prefs
    finally:
        os.environ.pop("NTA_PREFECTURES", None)
    assert nta_updater.configured_prefectures() == ["東京都", "神奈川県", "千葉県", "埼玉県"]
    os.environ["NTA_AUTO_UPDATE"] = "0"
    try:
        assert nta_updater.auto_update_enabled() is False
    finally:
        os.environ.pop("NTA_AUTO_UPDATE", None)
    assert nta_updater.auto_update_enabled() is True
    print("✓ 都道府県・自動更新の設定読み取り（略称補完・既定値）")


if __name__ == "__main__":
    tests = [
        test_parse_links,
        test_first_update_downloads_all,
        test_second_update_skips,
        test_force_redownloads,
        test_status_and_local_search_integration,
        test_prefecture_config,
    ]
    for t in tests:
        t()
    print(f"\n全 {len(tests)} テスト成功 ✅")
