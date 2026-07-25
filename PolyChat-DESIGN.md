# PolyChat 기술 설계 문서

현행화 2026-07-06. 작업 이력·결정 근거는 `context-notes.md`, 진행 상태는 `checklist.md` 참고.

## 개요

PolyChat은 하나의 고민을 서로 다른 베이스 모델(Claude / ChatGPT / Gemini)에게 각기 다른 역할로 던지고, 그 답을 종합해 **검증할 가설**을 뽑아내는 1인 개발자용 아이디어 검증 작업장이다. House M.D.식 감별진단에서 출발했다. 사용자는 환자, 모델 팀이 진단한다. API 키 없이 각 서비스의 웹 UI를 Playwright로 제어하며, CDP attach로 사용자의 로그인된 Chrome에 붙어 봇 차단을 회피한다.

핵심은 멀티프롬프트가 아니라 **멀티모델**이다. 같은 모델에 프롬프트만 바꾸면 sycophancy로 동조 수렴해 역할이 붕괴한다. 역할은 반드시 다른 베이스 모델에 박는다.

## 핵심 설계 원칙

1. **멀티모델 역할 고정**. 동조·반대·엉뚱을 서로 다른 모델에 박아 divergence를 만든다.
2. **출력은 결론이 아니라 가설**. 모델은 모르는 업계도 자신 있게 지어낸다. 합의를 현실로 믿지 않는다.
3. **사용자 = 환자**. 증상의 진실성(날것의 맥락)과 최종 동의는 사람이 쥔다.
4. **API 불필요**. 각 서비스 웹 UI를 Playwright로 제어.
5. **확장 가능**. 모델은 `base.AIScraper` + config 셀렉터로 플러그인처럼 추가.

---

## 아키텍처

```
[사용자 브라우저]
        ↕ WebSocket (/ws)
[FastAPI 서버 (localhost:7777)]
        ↕ Playwright (connect_over_cdp)
[사용자의 Chrome — CDP :9222]
   ├── claude.ai        (탭 A)
   ├── chatgpt.com      (탭 B)
   └── gemini.google.com(탭 C)
```

Chrome 하나에 에이전트별 탭을 여는 구조라 가볍다. 서버는 탭을 열어 제어만 하고, 사용자의 다른 창은 건드리지 않는다.

### 구성 요소

| 구성 요소 | 기술 | 역할 |
|-----------|------|------|
| 웹 서버 | FastAPI (Python) | 정적 서빙 + `/ws` WebSocket |
| 브라우저 자동화 | Playwright (async) | CDP attach, 탭별 제어 |
| 프론트엔드 | 단일 `static/index.html` | 채팅 UI (바닐라 JS/CSS) |
| 세션 | 사용자 Chrome / `profiles/cdp` | 로그인 상태는 브라우저가 유지 |
| 설정 | `config.yaml`(기본값) + `settings.json`(편집값) | 역할·전송·메모리 노트 |
| 진단 기록 | `diagnoses.md` | 합성 결과 append |

SQLite·별도 DB는 쓰지 않는다. 대화 연속성은 모델별 대화(conversation_url) 재사용으로 처리한다.

---

## 브라우저 모드

`BrowserManager`는 `server.browser_mode`로 두 모드를 지원한다.

- **cdp (기본)**. 사용자가 `--remote-debugging-port=9222`로 띄운(이미 로그인된) Chrome에 `connect_over_cdp`로 접속. 새 로그인이 없어 Cloudflare(Claude)·Google "안전하지 않은 브라우저" 차단을 원천 회피. `stop()` 시 우리가 연 탭만 닫는다.
- **persistent**. 영구 프로필을 직접 기동.

`cdp_auto_launch`가 켜져 있고 9222가 비어 있으면 서버가 **전용 프로필(`profiles/cdp`)**로 Chrome을 직접 띄운다. 실제 프로필은 세션 복원으로 창이 여럿 열리고 평소 Chrome과 포트 충돌이 나서, 전용 프로필로 확정했다(2026-06-16). 대신 AI 3개에 최초 1회 로그인이 필요하며 `profiles/cdp`에 영구 저장된다.

---

## 디렉토리 구조

```
polychat/
├── main.py                  # FastAPI 앱 + /ws 디스패치
├── config.yaml              # 모델·역할·프롬프트·셀렉터 기본값
├── settings.py              # config 기본값 + settings.json 병합 로직
├── settings.json            # 편집값(.gitignore, 사용자 로컬)
├── requirements.txt
├── diagnoses.md             # 합성 결과 로그
├── profiles/cdp/            # CDP 전용 Chrome 프로필(로그인 상태)
├── scrapers/
│   ├── __init__.py          # SCRAPERS 레지스트리(claude/chatgpt/gemini만 등록)
│   ├── base.py              # AIScraper 공통 구현
│   ├── manager.py           # BrowserManager, 탭·대화 생명주기
│   ├── claude.py            # thin override
│   ├── chatgpt.py
│   ├── gemini.py
│   └── grok.py, perplexity.py  # 죽은 파일. 레지스트리 미등록, 삭제 안 함
├── static/
│   └── index.html           # 프론트엔드(단일 파일)
├── PolyChat-DESIGN.md       # 이 문서
├── checklist.md
├── context-notes.md         # 작업 이력·결정
└── POLYCHAT-SESSION-BRIEF.md# overseer 브리핑
```

`memory/` 모듈·`db/`는 **미구현**. Grok/Perplexity는 레지스트리에서 빠졌으나 `scrapers/grok.py`·`perplexity.py` 파일이 잔존한다(죽은 코드, 정리는 판정 후).

---

## 스크래퍼 설계

전송·완료감지·대화재사용·로그인확인 로직은 `base.AIScraper` 공통 구현에 있다. 모델별 스크래퍼는 `service_id / display_name / url`만 정의하고, 동작이 다르면 해당 메서드(예: Gemini `_submit`)만 오버라이드한다. 셀렉터(input/response/streaming/send_button)는 `config.yaml`에서 주입한다.

```python
class AIScraper:
    service_id: str
    display_name: str
    url: str
    # 공통: setup / is_logged_in / send / _ensure_conversation
    #       _collect_response(on_update) / _submit
```

### 모델별 전략

| 모델 | URL | 입력 셀렉터 | 응답 셀렉터 | 완료 감지 |
|------|-----|------------|------------|-----------|
| Claude | claude.ai/new | `div[contenteditable="true"]` | `.font-claude-response` | `[data-is-streaming="true"]` 소멸 |
| ChatGPT | chatgpt.com/?temporary-chat=true | `#prompt-textarea` | `div[data-message-author-role="assistant"]` | 텍스트 3회 안정화 폴백 |
| Gemini | gemini.google.com/app | `rich-textarea` | `.response-content` | 텍스트 3회 안정화 폴백 |

ChatGPT/Gemini는 Enter 전송이 불안정해 `send_button` 셀렉터를 폴백으로 둔다.

### 응답 수집

`_collect_response(on_update)`가 0.4초 간격으로 누적 텍스트를 폴링한다. 스트리밍 셀렉터가 있으면 그것이 사라질 때 완료, 없으면 텍스트가 3회 연속 동일할 때 완료. 옛 응답 오독을 막으려 전송 직전 응답 개수를 baseline으로 잡고 그보다 늘어난 새 응답만 읽는다.

### 대화 재사용

매 턴 새 대화를 만들지 않는다. 모델당 대화를 1회만 만들고 그 `conversation_url`을 재사용한다. 첫 진입 시 `role_prompt`(있으면)를 setup으로 1회 주입한 뒤 생성된 URL을 캡처한다. `reset` 시 `conversation_url`까지 비워 다음 실행이 새 대화로 시작한다.

---

## 흐름 — 팬아웃 감별진단 + MOA 투표

```
1. 고민 1개 입력
2. 팬아웃 — 3열(역할 고정: 동조/반대/엉뚱, 모델은 컬럼에서 선택)
   → 프론트가 send 3회, 모델별 역할 프롬프트 + 고민을 전송, 순차 스트리밍
3. 합성 — 세 답을 Claude가 종합 → "검증할 가설 N개 + 레드팀 반박 한 단락"
4. 투표 — 3모델이 합의안에 병렬 이의제기(놓친 점/다른 각도/약한 논리)
5. 최종 결론 — 투표를 반영한 최종 합성
6. 재검토 — 사용자 피드백으로 다시 검토
```

역할↔모델 매핑은 고정하지 않고 UI 컬럼 드롭다운에서 매번 고른다(기본 동조=Claude / 반대=ChatGPT / 엉뚱=Gemini). 합성·최종은 Claude 고정. 전송 텍스트 = `role_prompt + "\n\n" + content`를 `handle_send`가 조립한다.

---

## 역할·프롬프트 (config.yaml)

`roles`에 동조/반대/엉뚱 프리셋이 있고 UI에서 편집 가능하다. 각 프롬프트 끝에 공통 제약을 박아 모델 폭주를 막는다. "질문하지 말고 바로 답(정보 부족 시 가정 한 줄 후 진행)·과거 대화/기억 무시·간결·가설 3개 이내." `synthesis_prompt`는 가설 + 레드팀 반박, `vote_prompt`는 이의제기, `consolidate_prompt`는 릴레이 콘솔용(현 미사용).

---

## 메모리 (설계만, 미구현)

장기 기억은 MVP 범위 밖이다. `config.yaml`에 `memory.provider: global_note`와 전역 노트가 있으나 **실제 컨텍스트 주입은 아직 안 한다**(Phase 5). 설계 의도는 기억을 각 서비스에 위임하지 않고 PolyChat이 중앙에서 동일하게 주입하는 것이며, 교체 가능한 `MemoryProvider` 인터페이스 뒤에 두기로 했다. 구현 시 조립 순서는 `memory.preamble → role_prompt → context_format(history) → user message`. `memory/` 모듈은 아직 없다.

---

## WebSocket API (실제)

### 클라이언트 → 서버 (핸들러)

`status`, `send`, `synthesize`, `vote`, `finalize`, `refine`, `reset`, `get_settings`, `save_settings`, `login`, `login_complete`, `consolidate`(휴면).

```json
{ "type": "send", "agent": "claude", "role_prompt": "...", "content": "...", "turn_id": "uuid" }
{ "type": "synthesize", "responses": [ ... ] }
{ "type": "vote", "agents": ["claude","chatgpt","gemini"], "synthesis": "...", "vote_turn_id": "uuid" }
{ "type": "finalize", ... }
{ "type": "refine", ... }
{ "type": "reset" }
{ "type": "save_settings", ... }  { "type": "get_settings" }
```

### 서버 → 클라이언트 (type)

- 전송. `chunk`(누적 텍스트, 델타 아님) → `done`
- 합성. `synthesis_chunk` → `synthesis_done`
- 투표. `vote_chunk` → `vote_done`(모델별), `vote_error`, 라운드 끝 `vote_round_complete`
- 최종. `finalize_chunk` → `finalize_done`
- 재검토. `refine_chunk` → `refine_done`
- 기타. `settings`, `reset_done`, `status`, `login_required`, `error`
- 휴면. `consolidate_chunk` / `consolidate_done`(릴레이 콘솔용, 현 UI 미사용)

`chunk` 계열은 누적 텍스트라 유실에 강하다. 프론트는 `turn_id`로 카드/버블을 찾아 통째로 교체한다.

---

## 프론트엔드 UI

단일 `static/index.html`, 바닐라 JS. UI v2(2026-06-29)는 **수직 채팅 플로우**다. 각 AI 응답이 아바타(원형, 역할별 색상 + 한글 자음 "찬/부/엉") + 말풍선으로 나타나고, 사용자 메시지는 우측 파란 버블, AI는 좌측 흰 버블. 콤포저는 하단 고정(iMessage 스타일), 전송은 원형 아이콘 버튼. 합성은 "✦ 종합" 라벨 + 그라데이션 아바타로 구분. 헤더는 backdrop-filter 블러 sticky. 테마는 Apple 라이트(`#f5f5f7` 배경, 흰 카드, pill 버튼, 부드러운 그림자). 진행은 팬아웃 3열 done → 합성 버튼 → 투표 버튼 → 최종 결론 → 재검토 순으로 열린다.

`turn_id`는 `crypto.randomUUID()`(localhost 보안 컨텍스트). 역할·모델 설정은 접이식 패널에서 저장/로드한다.

---

## 초기 설정 흐름 (최초 1회)

```
1. Chrome을 --remote-debugging-port=9222로 띄우고 AI 3개에 로그인
   (또는 cdp_auto_launch로 서버가 profiles/cdp Chrome을 띄운 뒤 1회 로그인)
2. python main.py
3. 브라우저에서 localhost:7777 접속 → 고민 입력 → 시작
```

---

## 기술 스택 요약

| 항목 | 선택 | 이유 |
|------|------|------|
| 서버 | FastAPI + uvicorn | 비동기 WebSocket |
| 브라우저 자동화 | Playwright (async, CDP attach) | 로그인 세션 재사용, 봇 차단 회피 |
| 프론트엔드 | 바닐라 JS + CSS | 의존성 없음, 단일 파일 |
| 설정 | YAML + JSON | 기본값/편집값 분리 |

---

## 알려진 제약사항

1. **라이브 의존**. Playwright + 실제 웹 UI 동작은 사용자 맥에서만 검증 가능. 셀렉터는 UI 변경 시 `config.yaml` 두 줄만 고친다.
2. **대화 재사용 오염**. 같은 세션에서 고민을 2회 돌리면 2번째가 1번째 맥락을 봄. 초기화 = "초기화" 버튼/reload.
3. **계정 메모리 누수**. ChatGPT/Gemini 개인화·메모리가 켜져 있으면 누수 가능(코드 밖, 계정 설정에서 꺼야 완전).
4. **Gemini 간헐 빈 응답**. 스트리밍 감지 문제, 재검증 대상.
5. **속도**. 모델 응답 시간만큼 대기(30~90초/턴), 팬아웃은 순차.
6. **단일 사용자**. 1명 기준 설계.

---

## 동결 (MVP 가정 판정 통과 후에만)

메모리 실주입 · 의장 다단계 루프 · 상시 레드팀 · SQLite · 멀티턴 · Grok/Perplexity · 모바일 반응형. 릴레이 콘솔용 `consolidate` 핸들러/프롬프트는 코드에 휴면 상태로 남아 있다.
