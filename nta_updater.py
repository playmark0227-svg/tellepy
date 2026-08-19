"""国税庁 法人番号 全件データの自動更新モジュール（常に最新の母集団を保つ）

国税庁「法人番号公表サイト」の全件データ（月次更新・無料・トークン不要）を
自動でダウンロードし、telepy形式CSVに変換して data/ に置く。

- 起動時＋1日1回、公開ページを確認し、新しい月次データが出ていれば自動で差し替える
- 対象の都道府県は NTA_PREFECTURES（既定: 東京都,神奈川県,千葉県,埼玉県）
- 取得状況は data/nta_state.json に記録され、管理画面から確認・手動更新できる
- サイト構成が変わって自動取得できない場合は、明確なエラーを返す
  （その場合も、手動でダウンロードしたCSVを data/ に置けば従来どおり動く）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from corp_importer import import_nta
from list_builder import DATA_DIR, PREFECTURE_CODES, prefecture_stem

logger = logging.getLogger(__name__)

ZENKEN_PAGE = "https://www.houjin-bangou.nta.go.jp/download/zenken/"
STATE_PATH = DATA_DIR / "nta_state.json"
DEFAULT_PREFECTURES = ["東京都", "神奈川県", "千葉県", "埼玉県"]

USER_AGENT = "telepy-nta-updater/1.0 (company list builder; contact: local user)"

# 全件データのzipリンク（例: .../13_tokyo_all_20260630.zip）
ZIP_LINK_RE = re.compile(
    r'href="([^"]*?(\d{2})_[a-z]+_all_(\d{8})\.zip)"', re.IGNORECASE
)


def configured_prefectures() -> list[str]:
    raw = os.environ.get("NTA_PREFECTURES", "")
    if not raw:
        return list(DEFAULT_PREFECTURES)
    out = []
    for token in raw.replace("、", ",").split(","):
        name = token.strip()
        if not name:
            continue
        if name in PREFECTURE_CODES:
            out.append(name)
        else:
            for full in PREFECTURE_CODES:
                if prefecture_stem(full) == name:
                    out.append(full)
                    break
    return out or list(DEFAULT_PREFECTURES)


def auto_update_enabled() -> bool:
    return os.environ.get("NTA_AUTO_UPDATE", "1").strip().lower() not in ("0", "false", "no", "off")


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def parse_zenken_links(html: str, base_url: str = ZENKEN_PAGE) -> dict:
    """公開ページのHTMLから 都道府県コード → (zipのURL, データ日付) を抜き出す。

    Shift-JIS版とUnicode版の両方が載っていても、読み込み側が文字コードを
    自動判別するのでどちらを拾っても問題ない。日付が新しい方を採用する。
    """
    links: dict[str, tuple[str, str]] = {}
    for m in ZIP_LINK_RE.finditer(html):
        href, code, date = m.group(1), m.group(2), m.group(3)
        url = str(httpx.URL(base_url).join(href))
        cur = links.get(code)
        if cur is None or date > cur[1]:
            links[code] = (url, date)
    return links


def _out_path(code: str) -> Path:
    return DATA_DIR / f"nta_{code}.csv"


async def _download_to(client: httpx.AsyncClient, url: str, dst: Path, progress=None, label: str = "") -> None:
    async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}, timeout=600.0) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0) or 0)
        got = 0
        with open(dst, "wb") as f:
            async for chunk in resp.aiter_bytes(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if progress and got % (10 << 20) < (1 << 20):
                    mb = got / 1048576
                    pct = f" ({got * 100 // total}%)" if total else ""
                    await progress({"phase": "nta", "detail": f"{label} をダウンロード中... {mb:.0f}MB{pct}"})


_update_lock = asyncio.Lock()


def _summarize_errors(errors: list) -> str:
    if not errors:
        return ""
    head = errors[0]
    msg = f"{head.get('prefecture', '')}: {head.get('error', '')}".strip(": ")
    return msg if len(errors) == 1 else f"{msg} ほか{len(errors) - 1}件"


def _record_check(error: str = "") -> None:
    """最後にいつ確認して、成功したか失敗したかを残す（画面表示・再試行間隔用）。"""
    state = load_state()
    meta = dict(state.get("_meta") or {})
    now = datetime.now().isoformat(timespec="seconds")
    meta["last_checked_at"] = now
    meta["last_error"] = error
    if error:
        meta["consecutive_failures"] = int(meta.get("consecutive_failures", 0)) + 1
    else:
        meta["consecutive_failures"] = 0
        meta["last_success_at"] = now
    state["_meta"] = meta
    try:
        save_state(state)
    except Exception:
        logger.warning("更新状況の記録に失敗しました", exc_info=True)


def is_updating() -> bool:
    """更新処理が実行中か（画面の二重起動防止に使う）。"""
    return _update_lock.locked()


async def check_and_update(
    prefectures: Optional[list[str]] = None,
    *,
    force: bool = False,
    progress=None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """公開ページを確認し、新しい全件データがあればダウンロード→変換して差し替える。

    自動更新（毎日）と画面の「今すぐ更新」が同時に走ると同じファイルを取り合うため、
    同時実行はロックで1つに制限する。

    Returns: {"updated": [...], "skipped": [...], "errors": [...], "state": {...}}
    """
    async with _update_lock:
        try:
            result = await _check_and_update_locked(
                prefectures, force=force, progress=progress, http_client=http_client
            )
        except Exception as e:
            # 失敗を握りつぶすと「自動更新のはずが何ヶ月も古いまま」に誰も気づけない。
            # 画面から見えるように必ず記録してから投げ直す。
            _record_check(str(e))
            raise
        _record_check(_summarize_errors(result["errors"]))
        return result


async def _check_and_update_locked(
    prefectures: Optional[list[str]] = None,
    *,
    force: bool = False,
    progress=None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    prefs = prefectures or configured_prefectures()
    state = load_state()
    updated, skipped, errors = [], [], []

    own_client = http_client is None
    client = http_client or httpx.AsyncClient(follow_redirects=True)
    try:
        if progress:
            await progress({"phase": "nta", "detail": "国税庁の公開ページを確認中..."})
        try:
            resp = await client.get(ZENKEN_PAGE, headers={"User-Agent": USER_AGENT}, timeout=60.0)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"国税庁サイトに接続できませんでした: {e}") from e
        links = parse_zenken_links(resp.text)
        if not links:
            raise RuntimeError(
                "国税庁ページから全件データのリンクを見つけられませんでした（サイト構成が変わった可能性）。"
                "手動でダウンロードしたCSVを data/ に置けば従来どおり検索できます。"
            )

        for pref in prefs:
            code = PREFECTURE_CODES.get(pref)
            if not code or code not in links:
                errors.append({"prefecture": pref, "error": "ダウンロードリンクが見つかりません"})
                continue
            url, date = links[code]
            cur = state.get(pref, {})
            out = _out_path(code)
            if not force and cur.get("date") == date and out.exists():
                skipped.append({"prefecture": pref, "date": date})
                continue
            try:
                with tempfile.TemporaryDirectory(prefix="nta_dl_") as tmp:
                    zip_path = Path(tmp) / f"{code}.zip"
                    await _download_to(client, url, zip_path, progress, pref)
                    if progress:
                        await progress({"phase": "nta", "detail": f"{pref} を変換中..."})
                    # 変換はブロッキング処理なので別スレッドで（巨大CSVでもイベントループを塞がない）
                    rows = await asyncio.to_thread(
                        import_nta, zip_path, out, prefectures=[pref]
                    )
                state[pref] = {
                    "code": code,
                    "date": date,
                    "rows": rows,
                    "file": str(out),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                save_state(state)
                updated.append({"prefecture": pref, "date": date, "rows": rows})
                logger.info("国税庁データ更新: %s %s版 %s件", pref, date, f"{rows:,}")
            except Exception as e:
                logger.exception("国税庁データの更新に失敗: %s", pref)
                errors.append({"prefecture": pref, "error": str(e)})
    finally:
        if own_client:
            await client.aclose()

    return {"updated": updated, "skipped": skipped, "errors": errors, "state": state}


def status() -> dict:
    """管理画面用: 自動更新の設定と、県ごとの取得状況を返す。"""
    prefs = configured_prefectures()
    state = load_state()
    items = []
    for pref in prefs:
        cur = state.get(pref) or {}
        f = Path(cur["file"]) if cur.get("file") else None
        items.append({
            "prefecture": pref,
            "date": cur.get("date"),
            "rows": cur.get("rows"),
            "updated_at": cur.get("updated_at"),
            "file_exists": bool(f and f.exists()),
        })
    meta = state.get("_meta") or {}
    return {
        "auto_update": auto_update_enabled(),
        "prefectures": prefs,
        "items": items,
        "last_checked_at": meta.get("last_checked_at"),
        "last_success_at": meta.get("last_success_at"),
        "last_error": meta.get("last_error") or "",
        "consecutive_failures": int(meta.get("consecutive_failures", 0) or 0),
        "updating": is_updating(),
    }
