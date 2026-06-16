# PolyChat 체크리스트

설계는 `PolyChat-DESIGN.md` 참고. Phase별로 진행하며 완료 항목에 체크한다.

## Phase 1 — FastAPI 서버 + WebSocket 골격 (현재)

- [x] `requirements.txt` — fastapi, uvicorn[standard], pyyaml
- [x] `config.yaml` — agents / memory / context_format 기본값
- [x] `main.py` — 설정 로드, 정적 파일 서빙, `/ws` WebSocket
- [x] WebSocket 메시지 디스패치 — `status`, `send`(스텁) 처리
- [x] `static/index.html` — 연결·송수신 확인용 최소 UI
- [x] 검증 — uvicorn 기동, `/` 200, `/ws` status 왕복

## Phase 2 — Claude 스크래퍼 + 세션 관리

- [ ] `scrapers/base.py` — AIScraper 추상 클래스
- [ ] `scrapers/claude.py` — claude.ai 제어
- [ ] storageState 로그인 세션 저장/복원
- [ ] 응답 완료 감지(텍스트 길이 3회 안정화)

## Phase 3 — 프론트엔드 기본 UI

## Phase 4 — Gemini 스크래퍼

## Phase 5 — 역할 설정 + 컨텍스트 제어 + 메모리(MemoryProvider)

## Phase 6 — Grok / Perplexity

## Phase 7 — 모바일 반응형
