"""管理画面・管理APIの合言葉（アクセストークン）認証

管理画面にはAPIキーの設定・架電の実行・顧客リストの書き出しが全部ある。
一方でTwilioのwebhookを受けるにはサーバーを外から見える場所に置く必要があり
（ngrok等）、そのとき管理画面まで一緒に世界中へ公開されてしまう。

そこで「Twilioが叩く経路だけ開けて、それ以外は合言葉が要る」ようにする。

- 合言葉は環境変数 ADMIN_TOKEN。未設定なら初回起動時に自動生成して
  data/.admin_token に保存する（再起動しても変わらないので開いたタブが切れない）
- ブラウザは起動時に表示されるURL（?t=合言葉）を1回開けば、あとはcookieで通る
- curl等からは X-Admin-Token ヘッダでも通る
- 認証不要なのは /twilio/*（Twilioからのwebhook）と /audio/*（Twilioが音声を取得）
  と /health（死活監視）だけ
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

COOKIE_NAME = "telepy_admin"
HEADER_NAME = "X-Admin-Token"
QUERY_NAME = "t"

# Twilioは合言葉を知らないので、webhookと音声配信だけは開けておく。
# （Twilio側の署名検証は call_handler 側の責務）
OPEN_PREFIXES = ("/twilio/", "/audio/")
OPEN_PATHS = ("/health",)

_TOKEN_FILE = Path(__file__).parent / "data" / ".admin_token"
_cached_token: str | None = None


def _read_token_file() -> str:
    try:
        return _TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write_token_file(token: str) -> None:
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        _TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 本人だけが読める
    except OSError:
        pass  # Windows等で失敗しても致命的ではない


def get_token() -> str:
    """この起動で使う合言葉を返す（無ければ作って保存する）。"""
    global _cached_token
    env = (os.environ.get("ADMIN_TOKEN") or "").strip()
    if env:
        _cached_token = env
        return env
    if _cached_token:
        return _cached_token
    saved = _read_token_file()
    if saved:
        _cached_token = saved
        return saved
    token = secrets.token_urlsafe(24)
    _write_token_file(token)
    _cached_token = token
    logger.info("管理画面の合言葉を新規作成しました: %s", _TOKEN_FILE)
    return token


def reset_cache() -> None:
    """テスト用: 環境変数を変えた後にキャッシュを捨てる。"""
    global _cached_token
    _cached_token = None


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)


def token_matches(candidate: str) -> bool:
    if not candidate:
        return False
    return hmac.compare_digest(candidate, get_token())


def bootstrap_url(host: str, port: int) -> str:
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{shown}:{port}/?{QUERY_NAME}={get_token()}"


LOCKED_HTML = """<!doctype html>
<html lang="ja"><meta charset="utf-8">
<title>telepy — 合言葉が必要です</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#e7e9ee;
      font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif}
 .card{max-width:34rem;padding:2rem;line-height:1.9}
 h1{font-size:1.25rem;margin:0 0 1rem}
 code{background:#1b1f27;padding:.15em .45em;border-radius:.3em;font-size:.9em}
 p{margin:.6rem 0;color:#aab1c0}
</style>
<div class="card">
<h1>🔒 この画面には合言葉が必要です</h1>
<p>telepy の管理画面には、APIキーの設定や架電の実行が含まれます。外部に公開された状態で
誰でも操作できないよう、合言葉つきのURLからのみ開けるようにしています。</p>
<p>サーバーを起動したターミナルに表示されている
<code>http://127.0.0.1:8000/?t=…</code> のURLを開いてください。</p>
<p>合言葉は <code>data/.admin_token</code> にも保存されています。
自分で決めたい場合は環境変数 <code>ADMIN_TOKEN</code> を設定してから起動してください。</p>
</div>
</html>
"""
