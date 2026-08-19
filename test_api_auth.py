"""管理APIの合言葉認証テスト（ネットワーク不使用）

ngrok等でサーバーを外に出したとき、Twilioのwebhookだけが通り、
管理画面・管理APIは合言葉なしでは触れないことを確かめる。
実行: python test_api_auth.py
"""

import os
import tempfile
from pathlib import Path

# 実データや本物のconfigを触らないよう、テスト用ディレクトリに隔離する
_tmp = Path(tempfile.mkdtemp(prefix="telepy_auth_"))
os.environ["LOCAL_DATA_DIR"] = str(_tmp)
os.environ["ADMIN_TOKEN"] = "test-secret-token"
os.environ["NTA_AUTO_UPDATE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import admin_auth  # noqa: E402
import main  # noqa: E402

admin_auth.reset_cache()
TOKEN = "test-secret-token"

# 管理画面から叩ける代表的なエンドポイント（1つでも素通しなら事故になる）
GUARDED = [
    ("GET", "/api/settings"),
    ("GET", "/api/status"),
    ("GET", "/api/list/local-status"),
    ("GET", "/api/list/nta-status"),
    ("GET", "/api/logs"),
    ("GET", "/api/scripts"),
    ("GET", "/sessions"),
    ("GET", "/"),
    ("POST", "/api/list/nta-update"),
    ("PUT", "/api/settings"),
]


def _client() -> TestClient:
    # 見たいのは「合言葉で通るか塞がるか」だけ。ハンドラ側の失敗
    # （twilio SDK未導入等）は例外ではなく500として受け取り、401と区別する。
    return TestClient(main.app, raise_server_exceptions=False)


def test_unauthenticated_is_blocked():
    with _client() as c:
        for method, path in GUARDED:
            res = c.request(method, path, json={} if method in ("PUT", "POST") else None)
            assert res.status_code == 401, f"{method} {path} が合言葉なしで通った ({res.status_code})"
            if path.startswith("/api/"):
                assert "合言葉" in res.json().get("detail", ""), res.text
    print(f"✓ 合言葉なしでは管理系 {len(GUARDED)} 経路すべてが401")


def test_wrong_token_is_blocked():
    with _client() as c:
        res = c.get("/api/settings", headers={"X-Admin-Token": "test-secret-tokem"})
        assert res.status_code == 401, res.status_code
        res = c.get("/api/settings", cookies={"telepy_admin": ""})
        assert res.status_code == 401, res.status_code
    print("✓ 合言葉が1文字違うだけでも通さない")


def test_header_and_query_and_cookie_work():
    with _client() as c:
        res = c.get("/api/list/local-status", headers={"X-Admin-Token": TOKEN})
        assert res.status_code == 200, res.text

    with _client() as c:
        # 合言葉つきURLで1回開くとcookieが入り、以降は合言葉なしで通る
        res = c.get("/", params={"t": TOKEN})
        assert res.status_code == 200, res.status_code
        assert res.cookies.get("telepy_admin") == TOKEN, dict(res.cookies)
        res2 = c.get("/api/list/local-status")
        assert res2.status_code == 200, res2.text
    print("✓ ヘッダ・?t=・cookie のいずれでも通る（1回開けば以降はcookie）")


def test_twilio_and_health_stay_open():
    """Twilioは合言葉を知らないので、webhookと音声・死活監視だけは開いている"""
    with _client() as c:
        res = c.get("/health")
        assert res.status_code == 200, res.status_code
        # webhookは合言葉で弾かれない（中身が動くかはここでは見ない）
        res = c.post("/twilio/voice", data={"CallSid": "CAtest"})
        assert res.status_code != 401, "Twilioのwebhookが合言葉で塞がれている"
        assert not admin_auth.is_open_path("/api/settings")
        assert admin_auth.is_open_path("/twilio/respond")
        res = c.get("/audio/does-not-exist.mp3")
        assert res.status_code != 401, "Twilioが取りに来る音声が塞がれている"
    print("✓ Twilio webhook・音声配信・/health は開いたまま（合言葉不要）")


def test_generated_token_persists():
    """ADMIN_TOKEN未設定なら自動生成し、再起動しても同じ合言葉を使う"""
    saved_env = os.environ.pop("ADMIN_TOKEN")
    orig_file = admin_auth._TOKEN_FILE
    admin_auth._TOKEN_FILE = _tmp / ".admin_token"
    admin_auth.reset_cache()
    try:
        first = admin_auth.get_token()
        assert len(first) >= 20, first
        assert admin_auth._TOKEN_FILE.exists()
        admin_auth.reset_cache()  # 再起動を模擬
        assert admin_auth.get_token() == first, "再起動で合言葉が変わると開いたタブが切れる"
        assert TOKEN in admin_auth.bootstrap_url("0.0.0.0", 8000) or first in \
            admin_auth.bootstrap_url("0.0.0.0", 8000)
        assert "127.0.0.1" in admin_auth.bootstrap_url("0.0.0.0", 8000)
    finally:
        admin_auth._TOKEN_FILE = orig_file
        os.environ["ADMIN_TOKEN"] = saved_env
        admin_auth.reset_cache()
    print("✓ 合言葉の自動生成と永続化（再起動しても同じ）")


if __name__ == "__main__":
    tests = [
        test_unauthenticated_is_blocked,
        test_wrong_token_is_blocked,
        test_header_and_query_and_cookie_work,
        test_twilio_and_health_stay_open,
        test_generated_token_persists,
    ]
    for t in tests:
        t()
    print(f"\n全 {len(tests)} テスト成功 ✅")
