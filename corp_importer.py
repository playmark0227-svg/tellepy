"""国税庁 法人番号 全件データ取り込みモジュール（従量課金ゼロの母集団づくり）

国税庁「法人番号公表サイト」の全件データ（ダウンロード無料・APIトークン不要）を、
telepy のローカル検索が使えるCSV（法人番号 / 法人名 / 所在地 / 郵便番号）に変換する。
これで「自前の企業母集団」を1円もかけずに用意できる。

- 入手先: https://www.houjin-bangou.nta.go.jp/download/zenken/
  （全国版 or 都道府県別。UTF-8版 / Shift_JIS版どちらでも可。zip/csvどちらでも可）
- 電話番号・業種・資本金・従業員数は国税庁データには含まれない（社名+所在地のみ）。
  電話番号やHPは web_finder の無料エンリッチで各社サイトから補完する想定。

CLI:
  python corp_importer.py <path.csv|path.zip|dir> [--out data/companies.csv]
      [--pref 東京都,神奈川県] [--include-closed]
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator, Optional

from list_builder import PREFECTURE_CODES, _open_text_auto

logger = logging.getLogger(__name__)

# 国税庁 全件データCSVの列位置（ヘッダ無し・30列固定, 0始まり）
# 仕様: https://www.houjin-bangou.nta.go.jp/documents/csv-format.pdf
COL_CORPORATE_NUMBER = 1   # 法人番号(13桁)
COL_NAME = 6               # 商号又は名称
COL_KIND = 8              # 法人種別
COL_PREFECTURE = 9        # 国内所在地(都道府県)
COL_CITY = 10            # 国内所在地(市区町村)
COL_STREET = 11         # 国内所在地(丁目番地等)
COL_POSTCODE = 15       # 郵便番号
COL_CLOSE_DATE = 18     # 登記記録の閉鎖等年月日（埋まっていれば閉鎖）
COL_LATEST = 23         # 最新履歴（"1"=最新）
COL_HIHYOJI = 29        # 検索対象除外（"1"=除外）
NTA_MIN_COLS = 24       # これ未満の行は不正としてスキップ

OUT_COLUMNS = ["法人番号", "法人名", "所在地", "郵便番号"]


def looks_like_nta_row(row: list) -> bool:
    """国税庁 全件CSV（ヘッダ無し30列）の行っぽいか（先頭行の形式判定用）。"""
    if len(row) < NTA_MIN_COLS:
        return False
    cn = (row[COL_CORPORATE_NUMBER] or "").strip()
    return len(cn) == 13 and cn.isdigit()


def nta_row_to_fields(
    row: list,
    *,
    include_closed: bool = False,
    latest_only: bool = True,
) -> Optional[dict]:
    """国税庁CSVの1行を会社フィールドの辞書に変換する。対象外の行はNone。

    ローカル検索（list_builder.LocalDataSource）が生の全件CSVを直接読むときにも使う。
    """
    if len(row) < NTA_MIN_COLS:
        return None
    if latest_only and row[COL_LATEST].strip() != "1":
        return None
    if row[COL_HIHYOJI].strip() == "1":
        return None  # 検索対象除外
    if not include_closed and row[COL_CLOSE_DATE].strip():
        return None  # 登記閉鎖済み
    name = row[COL_NAME].strip()
    if not name:
        return None
    pref = row[COL_PREFECTURE].strip()
    return {
        "corporate_number": row[COL_CORPORATE_NUMBER].strip(),
        "name": name,
        "prefecture": pref,
        "location": pref + row[COL_CITY].strip() + row[COL_STREET].strip(),
        "postal_code": _format_postal(row[COL_POSTCODE]),
    }


def _iter_source_files(src: Path) -> Iterator[Path]:
    """入力（csv / zip / ディレクトリ）から実CSVパスを列挙する。
    zip はメモリ上で展開せず、呼び出し側が open できるよう一時展開する。"""
    if src.is_dir():
        for p in sorted(src.glob("**/*.csv")):
            yield p
    elif src.suffix.lower() == ".zip":
        # zip内のcsvを一時ディレクトリに展開して渡す
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="nta_"))
        with zipfile.ZipFile(src) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".csv"):
                    out = tmp / Path(name).name
                    with zf.open(name) as zsrc, open(out, "wb") as dst:
                        dst.write(zsrc.read())
                    yield out
    else:
        yield src


def _format_postal(raw: str) -> str:
    d = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(d) == 7:
        return f"{d[:3]}-{d[3:]}"
    return raw.strip()


def iter_companies(
    src: Path,
    *,
    prefectures: Optional[Iterable[str]] = None,
    include_closed: bool = False,
    latest_only: bool = True,
) -> Iterator[dict]:
    """国税庁CSVを1行ずつ読み、telepy形式の辞書を yield する（ストリーミング）。"""
    pref_set = set(prefectures) if prefectures else None
    for path in _iter_source_files(src):
        f = _open_text_auto(path)
        try:
            reader = csv.reader(f)
            for row in reader:
                fields = nta_row_to_fields(row, include_closed=include_closed, latest_only=latest_only)
                if fields is None:
                    continue
                if pref_set is not None and fields["prefecture"] not in pref_set:
                    continue
                yield {
                    "法人番号": fields["corporate_number"],
                    "法人名": fields["name"],
                    "所在地": fields["location"],
                    "郵便番号": fields["postal_code"],
                }
        finally:
            f.close()


def import_nta(
    src: Path,
    out: Path,
    *,
    prefectures: Optional[Iterable[str]] = None,
    include_closed: bool = False,
    progress_every: int = 100_000,
) -> int:
    """国税庁CSVを telepy 形式CSVに変換して書き出す。書き出した件数を返す。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # Excel互換のためBOM付きUTF-8で出力
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        for comp in iter_companies(src, prefectures=prefectures, include_closed=include_closed):
            writer.writerow(comp)
            count += 1
            if progress_every and count % progress_every == 0:
                logger.info("変換中... %s件", f"{count:,}")
    return count


def _parse_prefectures(arg: str) -> list[str]:
    out = []
    for token in arg.replace("、", ",").split(","):
        name = token.strip()
        if not name:
            continue
        # 「東京」→「東京都」等の補完
        if name in PREFECTURE_CODES:
            out.append(name)
        else:
            for full in PREFECTURE_CODES:
                if full.rstrip("都道府県") == name:
                    out.append(full)
                    break
            else:
                logger.warning("未知の都道府県: %s（無視）", name)
    return out


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="国税庁 法人番号 全件CSVを telepy のローカル検索用CSVに変換する（無料）",
    )
    parser.add_argument("src", help="国税庁CSV / zip / それらを含むディレクトリのパス")
    parser.add_argument("--out", default="data/companies.csv", help="出力先CSV（既定: data/companies.csv）")
    parser.add_argument("--pref", default="", help="都道府県で絞る（カンマ区切り。例: 東京都,神奈川県）")
    parser.add_argument("--include-closed", action="store_true", help="登記閉鎖済みの法人も含める")
    args = parser.parse_args(argv)

    src = Path(args.src)
    if not src.exists():
        logger.error("入力が見つかりません: %s", src)
        return 1
    prefs = _parse_prefectures(args.pref) if args.pref else None
    out = Path(args.out)
    logger.info("変換開始: %s → %s%s", src, out, f"（{'/'.join(prefs)}のみ）" if prefs else "")
    n = import_nta(src, out, prefectures=prefs, include_closed=args.include_closed)
    logger.info("完了: %s件を %s に書き出しました。管理画面のローカルCSV検索で使えます。", f"{n:,}", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
