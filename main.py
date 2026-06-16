# FastAPI 앱 진입점. 정적 파일 서빙과 /ws WebSocket 메시지 디스패치를 담당한다.
import json
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import settings as settings_store
from scrapers.manager import BrowserManager

BASE_DIR = Path(__file__).parent
CONFIG = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
AGENTS = CONFIG["agents"]

# 웹 UI에서 편집한 설정. config 기본값에 settings.json을 덮어쓴 뒤 role_prompt를 AGENTS에 반영한다.
SETTINGS_PATH = BASE_DIR / "settings.json"
SETTINGS = settings_store.load(SETTINGS_PATH, AGENTS, CONFIG["memory"]["global_note"])
settings_store.apply_to_agents(SETTINGS, AGENTS)

_srv = CONFIG["server"]
manager = BrowserManager(
    agents=AGENTS,
    profiles_dir=BASE_DIR / "profiles",
    mode=_srv.get("browser_mode", "cdp"),
    cdp_url=_srv.get("cdp_url", "http://localhost:9222"),
    headless=_srv.get("headless", False),
    channel=_srv.get("browser_channel", "chrome"),
)

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.on_event("startup")
async def _startup():
    await manager.start()


@app.on_event("shutdown")
async def _shutdown():
    await manager.stop()


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


async def handle_status(ws: WebSocket, msg: dict):
    # 매니저에 각 에이전트 로그인 상태를 질의한다. (스크래퍼 있는 에이전트만 실제 확인)
    agents = {}
    for aid in AGENTS:
        agents[aid] = await manager.status(aid)
    await ws.send_json({"type": "status", "agents": agents})


async def handle_send(ws: WebSocket, msg: dict):
    # Phase 2: 실제 스크래퍼로 메시지 전송. 컨텍스트/메모리 패키징은 Phase 5 범위.
    targets = msg.get("target", [])
    text = msg.get("text", "")
    for aid in targets:
        if aid not in AGENTS:
            await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
            continue
        turn_id = str(uuid.uuid4())
        try:
            reply = await manager.send(aid, text)
            await ws.send_json({"type": "chunk", "agent": aid, "turn_id": turn_id, "text": reply})
            await ws.send_json({"type": "done", "agent": aid, "turn_id": turn_id})
        except Exception as e:
            await ws.send_json({"type": "error", "agent": aid, "message": str(e)})


async def handle_login(ws: WebSocket, msg: dict):
    # 헤드풀 브라우저로 로그인 페이지를 연다. 사용자가 창에서 로그인 후 login_complete를 보내야 저장된다.
    aid = msg.get("agent")
    if aid not in AGENTS:
        await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
        return
    try:
        await manager.login(aid)
        await ws.send_json({"type": "login_required", "agent": aid, "url": AGENTS[aid]["url"]})
    except Exception as e:
        await ws.send_json({"type": "error", "agent": aid, "message": str(e)})


async def handle_login_complete(ws: WebSocket, msg: dict):
    # 사용자가 로그인을 마쳤음을 알리면 현재 세션을 storageState로 저장한다.
    aid = msg.get("agent")
    if aid not in AGENTS:
        await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
        return
    try:
        await manager.save_session(aid)
        await ws.send_json({"type": "status", "agents": {aid: await manager.status(aid)}})
    except Exception as e:
        await ws.send_json({"type": "error", "agent": aid, "message": str(e)})


def _settings_payload() -> dict:
    # 편집 가능한 값(role_prompt/enabled/global_note)에 표시용 메타(이름/색)를 합쳐 UI로 보낸다.
    return {
        "type": "settings",
        "global_note": SETTINGS["global_note"],
        "agents": [
            {
                "id": aid,
                "display_name": AGENTS[aid].get("display_name", aid),
                "color": AGENTS[aid].get("color", "#888888"),
                "role_prompt": SETTINGS["agents"][aid]["role_prompt"],
                "enabled": SETTINGS["agents"][aid]["enabled"],
            }
            for aid in AGENTS
        ],
    }


async def handle_get_settings(ws: WebSocket, msg: dict):
    await ws.send_json(_settings_payload())


async def handle_save_settings(ws: WebSocket, msg: dict):
    # UI에서 보낸 설정을 SETTINGS에 반영하고 settings.json에 영구 저장한다.
    note = msg.get("global_note")
    if isinstance(note, str):
        SETTINGS["global_note"] = note
    for aid, a in (msg.get("agents") or {}).items():
        if aid in SETTINGS["agents"] and isinstance(a, dict):
            if isinstance(a.get("role_prompt"), str):
                SETTINGS["agents"][aid]["role_prompt"] = a["role_prompt"]
            if isinstance(a.get("enabled"), bool):
                SETTINGS["agents"][aid]["enabled"] = a["enabled"]
    settings_store.apply_to_agents(SETTINGS, AGENTS)
    settings_store.save(SETTINGS_PATH, SETTINGS)
    await ws.send_json(_settings_payload())


HANDLERS = {
    "status": handle_status,
    "send": handle_send,
    "login": handle_login,
    "login_complete": handle_login_complete,
    "get_settings": handle_get_settings,
    "save_settings": handle_save_settings,
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
