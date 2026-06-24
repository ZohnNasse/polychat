# FastAPI 앱 진입점. 정적 파일 서빙과 /ws WebSocket 메시지 디스패치를 담당한다.
import asyncio
import json
import uuid
from datetime import datetime
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
ROLES = CONFIG.get("roles", {})                            # 역할 프리셋(동조/반대/엉뚱)
CONSOLIDATE_PROMPT = CONFIG.get("consolidate_prompt", "")  # 단계 전환 정리 프롬프트 템플릿(릴레이용)
SYNTHESIS_PROMPT = CONFIG.get("synthesis_prompt", "")      # 팬아웃 후 합성 프롬프트 템플릿

# 웹 UI에서 편집한 설정. config 기본값에 settings.json을 덮어쓴 뒤 role_prompt를 AGENTS에 반영한다.
SETTINGS_PATH = BASE_DIR / "settings.json"
DIAGNOSES_PATH = BASE_DIR / "diagnoses.md"  # 끝난 진단을 누적 기록하는 파일
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
    auto_launch=_srv.get("cdp_auto_launch", True),
    chrome_path=_srv.get("chrome_path", ""),
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
    # 회의 콘솔: 한 번에 한 모델에게만 전송한다. 역할 프롬프트를 본문 앞에 붙여 단계별로 주입한다.
    aid = msg.get("agent")
    if aid not in AGENTS:
        await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
        return
    role_prompt = (msg.get("role_prompt") or "").strip()
    content = msg.get("content") or msg.get("text") or ""
    text = f"{role_prompt}\n\n{content}" if role_prompt else content
    turn_id = msg.get("turn_id") or str(uuid.uuid4())
    print(f"[handle_send] agent={aid} role={'Y' if role_prompt else 'N'} turn={turn_id}")

    async def on_update(t):
        # 생성 중 누적 텍스트를 단계 카드에 실시간 갱신하도록 흘려보낸다.
        await ws.send_json({"type": "chunk", "agent": aid, "turn_id": turn_id, "text": t})

    try:
        reply = await manager.send(aid, text, on_update=on_update)
        await ws.send_json({"type": "done", "agent": aid, "turn_id": turn_id, "text": reply})
    except Exception as e:
        print(f"[handle_send:{aid}] ERROR {e!r}")
        await ws.send_json({"type": "error", "agent": aid, "turn_id": turn_id, "message": str(e)})


async def handle_consolidate(ws: WebSocket, msg: dict):
    # 단계 전환: 직전 모델에게 (자기 대화 컨텍스트 + 사용자 의견)을 화자 분리·정리시키고 정리본을 돌려준다.
    aid = msg.get("agent")
    if aid not in AGENTS:
        await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
        return
    my_opinion = msg.get("my_opinion") or ""
    prompt = CONSOLIDATE_PROMPT.format(my_opinion=my_opinion)
    print(f"[handle_consolidate] agent={aid}")

    async def on_update(t):
        await ws.send_json({"type": "consolidate_chunk", "agent": aid, "text": t})

    try:
        text = await manager.send(aid, prompt, on_update=on_update)
        await ws.send_json({"type": "consolidate_done", "agent": aid, "text": text})
    except Exception as e:
        print(f"[handle_consolidate:{aid}] ERROR {e!r}")
        await ws.send_json({"type": "error", "agent": aid, "message": str(e)})


def _save_diagnosis(symptom: str, responses: list, synthesis: str):
    # 끝난 진단(증상+3열 응답+합성)을 diagnoses.md에 한 건씩 append 한다.
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [f"\n\n---\n\n## {ts}\n\n**증상**\n\n{symptom}\n"]
    for r in responses:
        name = AGENTS.get(r.get("model"), {}).get("display_name", r.get("model", "?"))
        parts.append(f"\n### {r.get('role', '')} · {name}\n\n{r.get('text', '')}\n")
    parts.append(f"\n### 합성 (가설 + 레드팀)\n\n{synthesis}\n")
    with DIAGNOSES_PATH.open("a", encoding="utf-8") as f:
        f.write("".join(parts))


async def handle_synthesize(ws: WebSocket, msg: dict):
    # 팬아웃 종합: 세 모델 응답을 화자 분리 텍스트로 묶어 합성 모델(기본 Claude)에게 가설+레드팀을 뽑게 한다.
    aid = msg.get("agent")
    if aid not in AGENTS:
        await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
        return
    responses = msg.get("responses") or []
    blocks = []
    for r in responses:
        name = AGENTS.get(r.get("model"), {}).get("display_name", r.get("model", "?"))
        blocks.append(f"[{r.get('role', '')} · {name}]\n{r.get('text', '')}")
    prompt = SYNTHESIS_PROMPT.format(responses="\n\n".join(blocks))
    print(f"[handle_synthesize] agent={aid} n={len(blocks)}")

    async def on_update(t):
        await ws.send_json({"type": "synthesis_chunk", "agent": aid, "text": t})

    try:
        text = await manager.send(aid, prompt, on_update=on_update)
        _save_diagnosis(msg.get("symptom", ""), responses, text)
        await ws.send_json({"type": "synthesis_done", "agent": aid, "text": text})
    except Exception as e:
        print(f"[handle_synthesize:{aid}] ERROR {e!r}")
        await ws.send_json({"type": "error", "agent": aid, "message": str(e)})


async def handle_refine(ws: WebSocket, msg: dict):
    # 재반박 루프: 사용자가 합성 결과에 반박·조율 의견을 보내면, 같은 합성 대화를 이어 재반박을 받는다.
    aid = msg.get("agent")
    if aid not in AGENTS:
        await ws.send_json({"type": "error", "agent": aid, "message": "unknown agent"})
        return
    content = (msg.get("content") or "").strip()
    if not content:
        await ws.send_json({"type": "error", "agent": aid, "message": "빈 의견"})
        return
    print(f"[handle_refine] agent={aid}")

    async def on_update(t):
        await ws.send_json({"type": "refine_chunk", "agent": aid, "text": t})

    try:
        text = await manager.send(aid, content, on_update=on_update)
        with DIAGNOSES_PATH.open("a", encoding="utf-8") as f:
            f.write(f"\n### 재반박 · 사용자\n\n{content}\n\n### 재반박 · 합성\n\n{text}\n")
        await ws.send_json({"type": "refine_done", "agent": aid, "text": text})
    except Exception as e:
        print(f"[handle_refine:{aid}] ERROR {e!r}")
        await ws.send_json({"type": "error", "agent": aid, "message": str(e)})


async def handle_reset(ws: WebSocket, msg: dict):
    # 모든 모델 대화를 초기화한다. 다음 진단은 새 대화에서 시작한다.
    await manager.reset()
    await ws.send_json({"type": "reset_done"})


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
        "roles": [{"id": rid, "label": r.get("label", rid), "prompt": r.get("prompt", "")}
                  for rid, r in ROLES.items()],
        "columns": SETTINGS.get("columns", {}),
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
    cols = msg.get("columns")
    if isinstance(cols, dict):
        SETTINGS["columns"] = cols
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
    "consolidate": handle_consolidate,
    "synthesize": handle_synthesize,
    "refine": handle_refine,
    "reset": handle_reset,
    "login": handle_login,
    "login_complete": handle_login_complete,
    "get_settings": handle_get_settings,
    "save_settings": handle_save_settings,
}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    tasks = set()  # 진행 중인 핸들러 태스크. 연결 종료 시 정리한다.
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
            # 핸들러를 백그라운드로 돌린다. 한 모델 전송이 멈춰도 메시지 루프가 막히지 않아
            # reset·status 같은 제어 메시지를 즉시 처리할 수 있다.
            task = asyncio.create_task(handler(ws, msg))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=CONFIG["server"]["host"], port=CONFIG["server"]["port"])
