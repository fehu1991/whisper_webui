from __future__ import annotations

import asyncio
import json
import re
import secrets
import struct
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from whisper_app.jobs import JobBusyError
from whisper_app.jobs.cancellation import JobCancelledError
from whisper_app.live.models import MODEL_SIZES, readiness

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


class SessionStore:
    def __init__(self, root: Path):
        self.root = root

    def folder(self, session_id):
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise HTTPException(400, "無效的工作編號。")
        return self.root / session_id

    def write(self, session_id, name, data):
        folder = self.folder(session_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def read(self, session_id):
        folder = self.folder(session_id)
        try:
            data = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise HTTPException(404, "找不到這份本機文字稿。")
        edited = folder / "edited.json"
        data["edited"] = json.loads(edited.read_text(encoding="utf-8")) if edited.exists() else None
        return data

    def listing(self):
        records = []
        if self.root.exists():
            for path in sorted(self.root.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    records.append({key: data.get(key) for key in ("id", "created", "status", "model")})
                except (OSError, ValueError):
                    continue
        return records


class Worker:
    def __init__(self, base, model, language):
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "whisper_app.live.worker", model, language],
            cwd=str(base), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

    def write(self, data):
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()

    def read(self):
        line = self.process.stdout.readline(MAX_DOCUMENT_BYTES)
        if not line:
            raise RuntimeError("辨識程序已離線，請重新開始收音。")
        return json.loads(line)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


def create_live_app(base: Path, manager, release_models=lambda: None, worker_factory=Worker):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    token = secrets.token_urlsafe(32)
    store = SessionStore(base / ".whisper" / "live")
    web = Path(__file__).parent / "web"
    app.state.live_store = store
    app.state.live_token = token

    def check_origin(connection):
        origin = connection.headers.get("origin")
        if origin and origin != f"http://{connection.headers.get('host')}":
            raise HTTPException(403, "不允許其他網站存取本機工作台。")

    def authorize(request):
        check_origin(request)
        if not secrets.compare_digest(request.headers.get("x-workspace-token", ""), token):
            raise HTTPException(403, "請從本機工作台開啟。")

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.url.path.startswith("/live"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                "connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
                "object-src 'none'; base-uri 'none'; form-action 'none'"
            )
        return response

    @app.get("/live/")
    async def index():
        return HTMLResponse((web / "index.html").read_text(encoding="utf-8").replace("__WORKSPACE_TOKEN__", token))

    @app.get("/live/editor")
    async def editor():
        return FileResponse(base / "文字稿編輯工具.html", media_type="text/html")

    @app.get("/live/assets/{name}")
    async def asset(name: str):
        if name not in {"live.css", "live.js", "capture-worklet.js"}:
            raise HTTPException(404)
        return FileResponse(web / name)

    @app.get("/live/api/status")
    async def status(request: Request):
        authorize(request)
        result = await asyncio.to_thread(readiness, base)
        result["busy"] = manager.active is not None
        return result

    @app.get("/live/api/sessions")
    async def sessions(request: Request):
        authorize(request)
        return store.listing()

    @app.get("/live/api/sessions/{session_id}")
    async def load_session(session_id: str, request: Request):
        authorize(request)
        return store.read(session_id)

    @app.put("/live/api/sessions/{session_id}")
    async def save_session(session_id: str, request: Request):
        authorize(request)
        if not (store.folder(session_id) / "session.json").is_file():
            raise HTTPException(404, "工作不存在。")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_DOCUMENT_BYTES:
                raise HTTPException(413, "文字稿過大，請先匯出。")
        try:
            snapshot = json.loads(body)
            if not isinstance(snapshot, dict) or not isinstance(snapshot["text"], str):
                raise ValueError()
            if not isinstance(snapshot["seen"], list) or any(not re.fullmatch(r"live-\d+", item) for item in snapshot["seen"]):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "文字稿格式錯誤。")
        store.write(session_id, "edited.json", {"text": snapshot["text"], "seen": snapshot["seen"]})
        return {"saved": True}

    @app.websocket("/live/ws")
    async def microphone(ws: WebSocket):
        try:
            check_origin(ws)
        except HTTPException:
            await ws.close(code=1008)
            return
        await ws.accept()
        worker = None
        audio_file = None
        state = None
        tasks = []
        lease = None
        lease_entered = False
        failure = None
        try:
            options = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if not isinstance(options, dict) or not secrets.compare_digest(str(options.get("token", "")), token):
                await ws.close(code=1008)
                return
            model, language = options.get("model", "small"), options.get("language", "zh")
            if model not in MODEL_SIZES or language not in {"zh", "en", "ja", "auto"}:
                raise ValueError("模型或語言設定錯誤。")
            lease = manager.run("live", "即時收音")
            cancellation = lease.__enter__()
            lease_entered = True
            state = {"id": secrets.token_hex(16), "created": datetime.now().isoformat(timespec="seconds"),
                     "model": model, "language": language, "status": "loading", "rows": [],
                     "record_audio": options.get("record_audio") is True}
            store.write(state["id"], "session.json", state)
            await ws.send_json({"type": "session", "id": state["id"]})
            await asyncio.to_thread(release_models)
            worker = await asyncio.to_thread(worker_factory, base, model, language)
            loading = asyncio.create_task(asyncio.to_thread(worker.read))
            disconnected = asyncio.create_task(ws.receive())
            tasks = [loading, disconnected]
            loaded, _ = await asyncio.wait(tasks, timeout=180, return_when=asyncio.FIRST_COMPLETED)
            if disconnected in loaded:
                raise WebSocketDisconnect()
            if loading not in loaded:
                raise TimeoutError("Model startup timed out")
            first = loading.result()
            disconnected.cancel()
            await asyncio.gather(disconnected, return_exceptions=True)
            tasks = []
            if first.get("type") != "ready":
                raise RuntimeError(first.get("message", "模型載入失敗。"))
            state["status"] = "recording"
            store.write(state["id"], "session.json", state)
            if state["record_audio"]:
                audio_file = wave.open(str(store.folder(state["id"]) / "recording.wav"), "wb")
                audio_file.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            await ws.send_json(first)

            async def receive():
                total_bytes = 0
                while True:
                    cancellation.raise_if_cancelled()
                    message = await asyncio.wait_for(ws.receive(), timeout=20)
                    if message["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect()
                    if message.get("bytes") is not None:
                        data = message["bytes"]
                        if not data or len(data) > 64000 or len(data) % 2:
                            raise ValueError("音訊格式錯誤。")
                        total_bytes += len(data)
                        if total_bytes > 16000 * 2 * 60 * 60 * 6:
                            raise ValueError("已達單場 6 小時上限，請另開一場。")
                        if audio_file:
                            audio_file.writeframes(data)
                        await asyncio.wait_for(asyncio.to_thread(worker.write, data), timeout=10)
                    elif message.get("text") == "stop":
                        await asyncio.to_thread(worker.write, b"")
                        return
                    else:
                        raise ValueError("未知的收音指令。")

            async def send():
                while True:
                    event = await asyncio.wait_for(asyncio.to_thread(worker.read), timeout=120)
                    if event.get("type") == "transcript" and event.get("rows"):
                        state["rows"].extend(event["rows"])
                        store.write(state["id"], "session.json", state)
                    if event.get("type") == "error":
                        raise RuntimeError(event.get("message", "辨識失敗。"))
                    if event.get("type") == "done":
                        state["status"] = "completed"
                        return
                    await ws.send_json(event)

            tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if tasks[0] in done:
                await asyncio.wait_for(tasks[1], timeout=100)
            else:
                raise RuntimeError("辨識程序提前結束，請先匯出文字稿。")
            # Release the child before unlocking the shared inference resource.
            await asyncio.to_thread(worker.close)
            worker = None
            await ws.send_json({"type": "done"})
        except WebSocketDisconnect as exc:
            failure = exc
        except (Exception, asyncio.CancelledError) as exc:
            failure = exc
            if isinstance(exc, JobBusyError):
                message = "目前已有轉錄工作。請等工作完成，或先停止另一場收音。"
            elif type(exc) in (RuntimeError, ValueError):
                message = str(exc)
            else:
                message = "收音連線或本機儲存失敗。已確認的段落仍可從本機紀錄取回；請先匯出目前內容。"
            try:
                await ws.send_json({"type": "error", "message": message})
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            for task in tasks:
                task.cancel()
            if worker:
                await asyncio.to_thread(worker.close)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if lease_entered:
                try:
                    lease.__exit__(type(failure) if failure else None, failure, None)
                except JobCancelledError:
                    if state:
                        state["status"] = "interrupted"
            if audio_file:
                audio_file.close()
            if state:
                if state["status"] != "completed":
                    state["status"] = "interrupted"
                store.write(state["id"], "session.json", state)
            try:
                await ws.close()
            except RuntimeError:
                pass

    return app
