# 웹 UI에서 편집하는 모델별/전역 설정을 settings.json에 영구 저장하고 config.yaml 기본값과 병합한다.
import json
from pathlib import Path


def _defaults(agents: dict, global_note: str) -> dict:
    # config.yaml 값을 기본으로 설정 구조를 만든다. enabled 기본값은 claude만 켜 둔다.
    return {
        "global_note": global_note,
        "agents": {
            aid: {"role_prompt": cfg.get("role_prompt", ""), "enabled": aid == "claude"}
            for aid, cfg in agents.items()
        },
    }


def load(path, agents: dict, global_note: str) -> dict:
    # settings.json이 있으면 그 값으로 기본값을 덮어쓴다(없는 키는 기본값 유지).
    data = _defaults(agents, global_note)
    p = Path(path)
    if p.exists():
        saved = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(saved.get("global_note"), str):
            data["global_note"] = saved["global_note"]
        for aid, a in saved.get("agents", {}).items():
            if aid in data["agents"] and isinstance(a, dict):
                data["agents"][aid].update(
                    {k: a[k] for k in ("role_prompt", "enabled") if k in a}
                )
    return data


def save(path, data: dict):
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def apply_to_agents(data: dict, agents: dict):
    # 편집된 role_prompt를 config agents 딕셔너리에 반영해 매니저가 최신 값을 setup_prompt로 쓰게 한다.
    for aid, a in data["agents"].items():
        if aid in agents:
            agents[aid]["role_prompt"] = a.get("role_prompt", "")
