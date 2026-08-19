#!/usr/bin/env python3
"""内蔵データ（seed）を作る — ブラウザ版を「開いた瞬間に使える」状態にする

国税庁「法人番号公表サイト」の全件データ（無料・トークン不要）から、
よく使う業種×地域だけを抜き出して gzip 圧縮し、docs/seed/ に置く。
GitHub Pages に載るとブラウザ版が起動時に読み込み、利用者は
zipのダウンロードも解凍も一切しないでリストを作れるようになる。

    python scripts/build_seed.py                     # 国税庁から取得して作る
    python scripts/build_seed.py --from-zip a.zip b.zip
    python scripts/build_seed.py --pref 東京都,神奈川県 --industry 工務店,不動産

出力:
    docs/seed/manifest.json   目録（社数・版・出所）— 軽いので毎回読む
    docs/seed/<name>.csv.gz   実体（起動時ではなく、使うときに読む）

注意: 完成した seed はリポジトリにコミットして初めて公開されます。
      月次の自動更新は .github/workflows/build-seed.yml が行います。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json
import logging
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corp_importer import import_nta  # noqa: E402
from list_builder import INDUSTRY_KEYWORD_PRESETS, REGION_ALIASES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_seed")

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "docs" / "seed"

# 出力する列（ブラウザ版の列名自動判別に合う名前にする）
OUT_COLUMNS = ["法人番号", "法人名", "所在地", "郵便番号"]


def keywords_for(industries: list[str]) -> list[str]:
    kws: list[str] = []
    for ind in industries:
        for k in INDUSTRY_KEYWORD_PRESETS.get(ind, []) + [ind]:
            if k and k not in kws:
                kws.append(k)
    return kws


def filter_to_seed(src_csv: Path, out_gz: Path, keywords: list[str]) -> int:
    """telepy形式CSVから、社名キーワードに当たる行だけを gzip で書き出す。"""
    out_gz.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_gz.with_suffix(out_gz.suffix + ".part")
    kept = 0
    try:
        with open(src_csv, encoding="utf-8-sig", newline="") as fin, \
             gzip.open(tmp, "wt", encoding="utf-8", newline="", compresslevel=9) as fout:
            reader = csv.DictReader(fin)
            writer = csv.DictWriter(fout, fieldnames=OUT_COLUMNS)
            writer.writeheader()
            for row in reader:
                name = (row.get("法人名") or "").strip()
                if not name or not any(k and k in name for k in keywords):
                    continue
                writer.writerow({
                    "法人番号": (row.get("法人番号") or "").strip(),
                    "法人名": name,
                    "所在地": (row.get("所在地") or "").strip(),
                    "郵便番号": (row.get("郵便番号") or "").strip(),
                })
                kept += 1
        tmp.replace(out_gz)
    finally:
        if tmp.exists():
            tmp.unlink()
    return kept


async def fetch_nta(prefectures: list[str], workdir: Path) -> dict[str, Path]:
    """国税庁から全件データを取得して telepy 形式CSVに変換する。"""
    from nta_updater import ZENKEN_PAGE, USER_AGENT, parse_zenken_links, _download_to
    from list_builder import PREFECTURE_CODES
    import httpx

    out: dict[str, Path] = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(ZENKEN_PAGE, headers={"User-Agent": USER_AGENT}, timeout=60.0)
        resp.raise_for_status()
        links = parse_zenken_links(resp.text)
        if not links:
            raise RuntimeError("国税庁ページから全件データのリンクを見つけられませんでした")
        for pref in prefectures:
            code = PREFECTURE_CODES.get(pref)
            if not code or code not in links:
                logger.warning("%s のリンクが見つかりません（飛ばします）", pref)
                continue
            url, dt = links[code]
            zip_path = workdir / f"{code}.zip"
            logger.info("%s をダウンロード中… (%s版)", pref, dt)
            await _download_to(client, url, zip_path, None, pref)
            csv_path = workdir / f"{code}.csv"
            rows = import_nta(zip_path, csv_path, prefectures=[pref])
            logger.info("%s: %s社を変換", pref, f"{rows:,}")
            out[pref] = csv_path
            zip_path.unlink(missing_ok=True)
            out.setdefault("_date", dt)  # type: ignore[arg-type]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ブラウザ版の内蔵データ（seed）を作る")
    ap.add_argument("--pref", default="一都三県",
                    help="対象の都道府県。まとめ言葉も可（既定: 一都三県）")
    ap.add_argument("--industry", default="工務店,不動産,建設,リフォーム",
                    help="対象の業種（既定: 工務店,不動産,建設,リフォーム）")
    ap.add_argument("--from-zip", nargs="*", default=None,
                    help="ダウンロード済みの国税庁zip/csvを使う（ネットに出ない）")
    ap.add_argument("--label", default="", help="画面に出す名前（既定は自動生成）")
    ap.add_argument("--out", default=str(SEED_DIR), help="出力先ディレクトリ")
    args = ap.parse_args(argv)

    prefs: list[str] = []
    for tok in args.pref.replace("、", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        prefs.extend(REGION_ALIASES.get(tok, [tok]))
    industries = [s.strip() for s in args.industry.replace("、", ",").split(",") if s.strip()]
    keywords = keywords_for(industries)
    logger.info("対象: %s / 業種: %s / 社名キーワード %d語", "・".join(prefs), "・".join(industries), len(keywords))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="seed_"))
    version = date.today().strftime("%Y-%m")
    try:
        if args.from_zip:
            sources = {}
            for i, raw in enumerate(args.from_zip):
                csv_path = workdir / f"src{i}.csv"
                rows = import_nta(Path(raw), csv_path, prefectures=prefs)
                logger.info("%s: %s社を変換", raw, f"{rows:,}")
                sources[f"src{i}"] = csv_path
        else:
            got = asyncio.run(fetch_nta(prefs, workdir))
            version = str(got.pop("_date", version))[:6] or version
            if len(version) == 6:
                version = version[:4] + "-" + version[4:]
            sources = got
        if not sources:
            logger.error("変換できたデータがありませんでした")
            return 1

        files, total = [], 0
        for key, csv_path in sources.items():
            name = f"{key}.csv.gz"
            kept = filter_to_seed(csv_path, out_dir / name, keywords)
            logger.info("%s → %s（%s社）", key, name, f"{kept:,}")
            files.append({"path": name, "companies": kept, "prefecture": key})
            total += kept

        label = args.label or ("・".join(industries) + "系（" + args.pref + "）")
        manifest = {
            "label": label,
            "companies": total,
            "version": version,
            "source": f"国税庁 法人番号データ {version}版",
            "prefectures": prefs,
            "industries": industries,
            "keywords": keywords,
            "files": files,
            "note": "社名・所在地・郵便番号のみ。電話番号・資本金・従業員数は含まれません。",
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        size = sum((out_dir / f["path"]).stat().st_size for f in files) / 1048576
        logger.info("完成: %s社 / %.1fMB → %s", f"{total:,}", size, out_dir)
        if size > 90:
            logger.warning("90MBを超えています。業種か地域を絞ってください（GitHubの制限に当たります）")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
