# FastAPI 앱 진입점. 정적 파일 서빙과 /ws WebSocket 메시지 디스패치를 담당한다.
import json
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
CONFIG = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
AGENTS = CONFIG["agents"]

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


async def handle_status(ws: WebSocket, msg: dict):
    # Phase 1: 스크래퍼 미구현이므로 전부 offline으로 보고한다.
    await ws.send_json({
        "type": "status",
        "agents": {aid: "offline" for aid in AGENTS},
    })


async def handle_send(ws: WebSocket, msg: dict):
    # Phase 1 스텁: 실제 AI 호출 없이 수신 확인만 돌려준다. Phase 2에서 스크래퍼로 대체.
    targets = msg.get("target", [])
    text = msg.get("text", "")
    for aid in targets:
        if aid not in AGENTS:
            await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
            continue
        turn_id = str(uuid.uuid4())
        stub = f"[{AGENTS[aid]['display_name']} 스텁 응답] 받은 메시지: {text}"
        await ws.send_json({"type": "chunk", "agent": aid, "turn_id": turn_id, "text": stub})
        await ws.send_json({"type": "done", "agent": aid, "turn_id": turn_id})


HANDLERS = {
    "status": handle_status,
    "send": handle_send,
}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "invalid json"})
                continue
            handler = HANDLERS.get(msg.get("type"))
            if handler is None:
                await ws.send_json({"type": "error", "message": f"unknown type: {msg.get('type')}"})
                continue
            await handler(ws, msg)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=CONFIG["server"]["host"], port=CONFIG["server"]["port"])
