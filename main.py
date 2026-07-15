"""telepy - テレアポ代行AIシステム メインサーバー"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import load_config, save_config, get_masked_config, sync_env, is_configured

# 重い外部SDK依存モジュールは遅延インポート（管理画面だけなら不要）
def _import_call_modules():
    from ai_engine import AIEngine
    from call_handler import CallSession, CallState
    from voice import TextToSpeech, cleanup_audio_files
    from notifier import notify_appointment, notify_error
    from database import save_call_log
    return AIEngine, CallSession, CallState, TextToSpeech, cleanup_audio_files, notify_appointment, notify_error, save_call_log

load_dotenv()

# 起動時にconfig.jsonがあれば環境変数に反映
sync_env(load_config())

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# パス定数
BASE_DIR = Path(__file__).parent
SCRIPTS_DIR = BASE_DIR / "scripts"
FRONTEND_DIR = BASE_DIR / "frontend"

# アクティブな通話セッションを管理
active_sessions: dict = {}

DEFAULT_SCRIPT = SCRIPTS_DIR / "example_client.yaml"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("telepy サーバー起動")
    yield
    try:
        _, _, _, _, cleanup_audio_files, _, _, _ = _import_call_modules()
        cleanup_audio_files()
    except ImportError:
        pass
    logger.info("telepy サーバー停止")


app = FastAPI(
    title="telepy - テレアポ代行AIシステム",
    version="1.0.0",
    lifespan=lifespan,
)

# 静的ファイル配信
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# =====================================================
# フロントエンド
# =====================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """管理画面を返す"""
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")


# =====================================================
# 管理API: 設定
# =====================================================

@app.get("/api/settings")
async def api_get_settings():
    """マスク済み設定を取得"""
    return get_masked_config()


@app.put("/api/settings")
async def api_put_settings(request: Request):
    """設定を保存（空文字のシークレットは既存値を維持）"""
    new = await request.json()
    current = load_config()
    secret_keys = {
        "twilio_auth_token", "deepgram_api_key", "elevenlabs_api_key",
        "anthropic_api_key", "supabase_key", "slack_webhook_url",
        "gbizinfo_api_token", "search_api_key",
    }
    for key in current:
        val = new.get(key, "")
        # マスク値や空文字のシークレットは既存値を維持
        if key in secret_keys and (not val or "*" in val):
            new[key] = current[key]
    save_config(new)
    return {"status": "ok"}


@app.get("/api/status")
async def api_status():
    """システムステータスを返す"""
    services = {
        "Twilio": is_configured("twilio_account_sid") and is_configured("twilio_auth_token"),
        "Deepgram": is_configured("deepgram_api_key"),
        "ElevenLabs": is_configured("elevenlabs_api_key"),
        "Anthropic": is_configured("anthropic_api_key"),
        "Firebase": is_configured("firebase_credentials_path"),
        "Slack": is_configured("slack_webhook_url"),
        "gBizINFO": is_configured("gbizinfo_api_token"),
    }
    today_calls = 0
    today_appointed = 0
    try:
        from database import get_call_logs
        from datetime import date
        logs = await get_call_logs(limit=200)
        today = date.today().isoformat()
        today_logs = [l for l in logs if l.get("called_at", "").startswith(today)]
        today_calls = len(today_logs)
        today_appointed = sum(1 for l in today_logs if l.get("status") == "appointed")
    except Exception:
        pass
    return {
        "services": services,
        "today_calls": today_calls,
        "today_appointed": today_appointed,
    }


# =====================================================
# 管理API: セッション
# =====================================================

@app.get("/api/sessions")
async def api_list_sessions():
    return {
        sid: session.get_summary()
        for sid, session in active_sessions.items()
    }


# =====================================================
# 管理API: スクリプト
# =====================================================

@app.get("/api/scripts")
async def api_list_scripts():
    """スクリプト一覧"""
    scripts = []
    for f in sorted(SCRIPTS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            scripts.append({
                "filename": f.name,
                "client_name": data.get("client_name", ""),
                "product": data.get("product", ""),
                "target": data.get("target", ""),
            })
        except Exception:
            scripts.append({"filename": f.name, "client_name": f.stem, "product": "", "target": ""})
    return scripts


@app.get("/api/scripts/{filename}")
async def api_get_script(filename: str):
    """スクリプト内容を取得"""
    path = SCRIPTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="スクリプトが見つかりません")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


@app.post("/api/scripts/{filename}")
async def api_create_script(filename: str, request: Request):
    """スクリプトを新規作成"""
    if not filename.endswith(".yaml"):
        filename += ".yaml"
    path = SCRIPTS_DIR / filename
    if path.exists():
        raise HTTPException(status_code=409, detail="同名のスクリプトが既に存在します")
    data = await request.json()
    path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return {"status": "ok", "filename": filename}


@app.put("/api/scripts/{filename}")
async def api_update_script(filename: str, request: Request):
    """スクリプトを更新"""
    path = SCRIPTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="スクリプトが見つかりません")
    data = await request.json()
    path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return {"status": "ok"}


@app.delete("/api/scripts/{filename}")
async def api_delete_script(filename: str):
    """スクリプトを削除"""
    path = SCRIPTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="スクリプトが見つかりません")
    path.unlink()
    return {"status": "ok"}


# =====================================================
# 管理API: 通話履歴
# =====================================================

@app.get("/api/logs")
async def api_get_logs(status: Optional[str] = None, limit: int = 50):
    """通話ログを取得"""
    try:
        from database import get_call_logs
        return await get_call_logs(status=status, limit=limit)
    except Exception:
        return []


# =====================================================
# 管理API: 架電
# =====================================================

class CallRequest(BaseModel):
    phone_number: str
    script_path: Optional[str] = None


@app.post("/api/call/initiate")
async def api_initiate_call(req: CallRequest):
    """管理画面から架電を開始"""
    script = str(SCRIPTS_DIR / req.script_path) if req.script_path else str(DEFAULT_SCRIPT)
    if not Path(script).exists():
        raise HTTPException(status_code=404, detail="スクリプトファイルが見つかりません")
    try:
        from twilio.rest import Client as TwilioClient  # noqa
        twilio_client = TwilioClient(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        )
        base_url = os.environ.get("BASE_URL", "https://your-domain.ngrok.io")
        call = twilio_client.calls.create(
            to=req.phone_number,
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            url=f"{base_url}/twilio/voice?script_path={script}",
            record=True,
            recording_status_callback=f"{base_url}/twilio/recording-status",
            status_callback=f"{base_url}/twilio/call-status",
        )
        logger.info("架電開始: %s (CallSid: %s)", req.phone_number, call.sid)
        return {"call_sid": call.sid, "phone_number": req.phone_number, "status": "initiated"}
    except Exception as e:
        logger.exception("架電開始エラー: %s", req.phone_number)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/call/batch-json")
async def api_batch_call(file: UploadFile = File(...)):
    """CSV一括架電（管理画面用）"""
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    results = []
    for row in reader:
        phone = row.get("phone_number", "").strip()
        if not phone:
            continue
        try:
            req = CallRequest(phone_number=phone)
            result = await api_initiate_call(req)
            results.append(result)
        except Exception as e:
            results.append({"phone_number": phone, "status": "error", "error": str(e)})
    return {"total": len(results), "results": results}


# =====================================================
# 管理API: リスト作成（企業リストビルダー）
# =====================================================

# 進行中・完了したリスト作成ジョブを管理（インメモリ）
list_jobs: dict = {}


class ParseRequest(BaseModel):
    text: str


class BuildRequest(BaseModel):
    criteria: dict
    mode: str = "auto"  # auto | local | api | demo
    enrich: bool = True
    detail_budget: int = 1500
    include_unknown_employee: bool = True
    strict_capital: bool = True
    demo: bool = False


@app.post("/api/list/parse")
async def api_list_parse(req: ParseRequest):
    """依頼文を検索条件に構造化する"""
    from list_builder import InquiryParser
    parser = InquiryParser()
    criteria = await parser.parse(req.text)
    return criteria.to_dict()


async def _run_build_job(job_id: str, req: BuildRequest):
    from list_builder import (
        SearchCriteria, GBizClient, LocalDataSource, ListBuilder, to_csv, to_call_csv,
    )
    job = list_jobs[job_id]
    try:
        criteria = SearchCriteria.from_dict(req.criteria)

        async def on_progress(p: dict):
            job["progress"] = p

        job["status"] = "running"

        if req.mode == "web":
            # Web自動探索: 公開HPを検索して会社情報を抽出する
            from web_finder import WebFinder
            job["mode"] = "web"
            companies, stats = await WebFinder().find(
                criteria,
                fetch_profile=req.enrich,
                include_unknown_employee=req.include_unknown_employee,
                strict_capital=req.strict_capital,
                progress=on_progress,
            )
        elif req.mode == "local_web":
            # 自前の母集団（国税庁 法人番号データ等のローカルCSV）で社名・地域を絞り、
            # 無料のWebエンリッチでHP・電話番号を補完する（従量課金ゼロが基本）
            from web_finder import WebFinder
            job["mode"] = "local_web"
            builder = ListBuilder(GBizClient(), LocalDataSource())
            companies, stats = await builder.build(
                criteria,
                mode="local",
                include_unknown_employee=req.include_unknown_employee,
                strict_capital=req.strict_capital,
                progress=on_progress,
            )
            if req.enrich and companies:
                companies, enrich_stats = await WebFinder().enrich_companies(
                    companies, progress=on_progress,
                )
                stats.enriched = enrich_stats.enriched
        else:
            builder = ListBuilder(GBizClient(), LocalDataSource())
            job["mode"] = builder.resolve_mode("demo" if req.demo else req.mode)
            companies, stats = await builder.build(
                criteria,
                mode=req.mode,
                enrich=req.enrich,
                detail_budget=req.detail_budget,
                include_unknown_employee=req.include_unknown_employee,
                strict_capital=req.strict_capital,
                demo=req.demo,
                progress=on_progress,
            )
        job["status"] = "done"
        job["companies"] = [c.to_dict() for c in companies]
        job["stats"] = stats.__dict__
        job["csv"] = to_csv(companies)
        job["call_csv"] = to_call_csv(companies)
        job["count"] = len(companies)
    except Exception as e:
        logger.exception("リスト作成ジョブ失敗: %s", job_id)
        job["status"] = "error"
        job["error"] = str(e)


@app.post("/api/list/build")
async def api_list_build(req: BuildRequest):
    """リスト作成ジョブを非同期で開始する"""
    import uuid
    job_id = uuid.uuid4().hex[:12]
    list_jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "progress": {},
        "companies": [],
        "stats": {},
        "count": 0,
    }
    # 古いジョブを整理（最新20件だけ保持）
    if len(list_jobs) > 20:
        for old in list(list_jobs)[:-20]:
            list_jobs.pop(old, None)
    asyncio.create_task(_run_build_job(job_id, req))
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/list/jobs/{job_id}")
async def api_list_job(job_id: str, preview: int = 50):
    """ジョブの進捗・結果を取得する（companiesは先頭preview件のみ）"""
    job = list_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {
        "id": job["id"],
        "status": job["status"],
        "mode": job.get("mode"),
        "progress": job.get("progress", {}),
        "stats": job.get("stats", {}),
        "count": job.get("count", 0),
        "error": job.get("error"),
        "companies": job.get("companies", [])[:preview],
    }


@app.get("/api/list/local-status")
async def api_list_local_status():
    """ローカルCSV（PC内検索用データ）の設置状況を返す"""
    from list_builder import LocalDataSource
    src = LocalDataSource()
    files = src.available_files()
    return {
        "configured": len(files) > 0,
        "data_dir": str(src.data_dir),
        "files": [{"name": p.name, "size": p.stat().st_size} for p in files],
    }


@app.post("/api/list/test-connection")
async def api_list_test_connection():
    """gBizINFO APIトークンで実際に1件検索し、接続できるか確認する（設定確認用）"""
    from list_builder import GBizClient
    return await GBizClient().test_connection()


@app.get("/api/list/jobs/{job_id}/export")
async def api_list_export(job_id: str, fmt: str = "detail"):
    """完成したリストをCSVでダウンロードする（fmt=detail|call）"""
    from fastapi.responses import Response
    job = list_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="ジョブが完了していません")
    if fmt == "call":
        content = job.get("call_csv", "")
        filename = f"call_list_{job_id}.csv"
    else:
        content = job.get("csv", "")
        filename = f"company_list_{job_id}.csv"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =====================================================
# Twilio Webhookエンドポイント（既存）
# =====================================================

@app.post("/twilio/voice")
async def twilio_voice(request: Request, script_path: Optional[str] = None):
    """Twilioが通話接続時に呼び出すWebhook"""
    from twilio.twiml.voice_response import VoiceResponse, Gather  # noqa
    AIEngine, CallSession, CallState, TextToSpeech, _, notify_appointment, notify_error, _ = _import_call_modules()

    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    phone_number = form.get("To", "unknown")
    script = script_path or str(DEFAULT_SCRIPT)

    try:
        ai_engine = AIEngine(script)
        session = CallSession(ai_engine, call_sid, phone_number)
        active_sessions[call_sid] = session
        greeting = await session.start()

        tts = TextToSpeech()
        audio_path = await tts.synthesize(greeting, f"{call_sid}_greeting.mp3")
        base_url = os.environ.get("BASE_URL", "https://your-domain.ngrok.io")

        response = VoiceResponse()
        response.record(recording_status_callback=f"{base_url}/twilio/recording-status")
        gather = Gather(
            input="speech",
            action=f"{base_url}/twilio/respond?call_sid={call_sid}",
            language="ja-JP", speech_timeout="auto", timeout=10,
        )
        gather.play(f"{base_url}/audio/{audio_path.name}")
        response.append(gather)
        response.say("お声が聞こえませんでした。またお電話させていただきます。失礼いたします。", language="ja-JP")
        response.hangup()
        return str(response)
    except Exception as e:
        logger.exception("通話開始エラー: %s", call_sid)
        await notify_error(str(e), f"CallSid: {call_sid}")
        response = VoiceResponse()
        response.say("申し訳ございません。技術的な問題が発生しました。", language="ja-JP")
        response.hangup()
        return str(response)


@app.post("/twilio/respond")
async def twilio_respond(request: Request, call_sid: str):
    """相手の発言を受け取り、AIの応答を返すWebhook"""
    from twilio.twiml.voice_response import VoiceResponse, Gather  # noqa
    _, _, CallState, TextToSpeech, _, _, notify_error, _ = _import_call_modules()

    form = await request.form()
    speech_result = form.get("SpeechResult", "")
    session = active_sessions.get(call_sid)
    if not session:
        response = VoiceResponse()
        response.say("セッションが見つかりませんでした。失礼いたします。", language="ja-JP")
        response.hangup()
        return str(response)

    try:
        result = await session.process_speech(speech_result)
        base_url = os.environ.get("BASE_URL", "https://your-domain.ngrok.io")
        tts = TextToSpeech()
        audio_path = await tts.synthesize(
            result["response"], f"{call_sid}_{len(session.conversation_history)}.mp3"
        )
        response = VoiceResponse()

        if result["is_finished"]:
            if result["state"] == CallState.HANDOFF:
                response.play(f"{base_url}/audio/{audio_path.name}")
                await _handle_handoff(session)
                forward_number = os.environ.get("FORWARD_PHONE_NUMBER")
                if forward_number:
                    response.dial(forward_number)
                else:
                    response.hangup()
            else:
                response.play(f"{base_url}/audio/{audio_path.name}")
                response.hangup()
            await _save_session(session)
            active_sessions.pop(call_sid, None)
        else:
            gather = Gather(
                input="speech",
                action=f"{base_url}/twilio/respond?call_sid={call_sid}",
                language="ja-JP", speech_timeout="auto", timeout=10,
            )
            gather.play(f"{base_url}/audio/{audio_path.name}")
            response.append(gather)
            response.say("お声が聞こえませんでした。またお電話させていただきます。失礼いたします。", language="ja-JP")
            response.hangup()
        return str(response)
    except Exception as e:
        logger.exception("応答処理エラー: %s", call_sid)
        await notify_error(str(e), f"CallSid: {call_sid}")
        response = VoiceResponse()
        response.say("申し訳ございません、少々お待ちください。", language="ja-JP")
        response.hangup()
        return str(response)


@app.post("/twilio/call-status")
async def twilio_call_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    logger.info("通話ステータス変更: %s -> %s", call_sid, call_status)
    if call_status in ("no-answer", "busy", "failed", "canceled"):
        session = active_sessions.pop(call_sid, None)
        if session:
            try:
                _, _, _, _, _, _, _, save_call_log = _import_call_modules()
                await save_call_log(
                    phone_number=session.phone_number, client_id="default",
                    status="absent", conversation_log=session.conversation_history,
                )
            except ImportError:
                logger.warning("database module not available")
    return JSONResponse({"status": "ok"})


@app.post("/twilio/recording-status")
async def twilio_recording_status(request: Request):
    form = await request.form()
    logger.info("録音完了: %s -> %s", form.get("CallSid", ""), form.get("RecordingUrl", ""))
    return JSONResponse({"status": "ok"})


# --- 音声ファイル配信 ---

@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    import tempfile
    AUDIO_DIR = Path(tempfile.gettempdir()) / "telepy_audio"
    filepath = AUDIO_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが見つかりません")
    return FileResponse(filepath, media_type="audio/mpeg")


# --- 既存互換エンドポイント ---

@app.get("/sessions")
async def list_sessions():
    return await api_list_sessions()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "telepy"}


# --- ヘルパー ---

async def _handle_handoff(session):
    try:
        _, _, _, _, _, notify_appointment, _, _ = _import_call_modules()
        await notify_appointment(
            company_name=session.contact_name or "不明",
            contact_name=session.contact_name or "不明",
            appointment_datetime=session.appointment_datetime or "未確定",
            phone_number=session.phone_number, notes=session.notes,
        )
    except Exception:
        logger.exception("ハンドオフ通知エラー")


async def _save_session(session):
    try:
        _, _, _, _, _, _, _, save_call_log = _import_call_modules()
        await save_call_log(
            phone_number=session.phone_number, client_id="default",
            status=session.get_status(), conversation_log=session.conversation_history,
            contact_name=session.contact_name, appointment_datetime=session.appointment_datetime,
        )
    except Exception:
        logger.exception("セッション保存エラー")


if __name__ == "__main__":
    import uvicorn
    # reload=True は watchfiles 追加インストールが必要なので既定オフ。
    # 開発中にホットリロードしたい場合だけ RELOAD=1 python main.py で有効化。
    reload = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)
