# PolyChat 체크리스트

설계는 `PolyChat-DESIGN.md` 참고. Phase별로 진행하며 완료 항목에 체크한다.

## Phase 1 — FastAPI 서버 + WebSocket 골격

- [x] `requirements.txt` — fastapi, uvicorn[standard], pyyaml
- [x] `config.yaml` — agents / memory / context_format 기본값
- [x] `main.py` — 설정 로드, 정적 파일 서빙, `/ws` WebSocket
- [x] WebSocket 메시지 디스패치 — `status`, `send`(스텁) 처리
- [x] `static/index.html` — 연결·송수신 확인용 최소 UI
- [x] 검증 — uvicorn 기동, `/` 200, `/ws` status 왕복

## Phase 2 — Claude 스크래퍼 + 세션 관리

- [x] `scrapers/base.py` — AIScraper 추상 클래스 + 응답 안정화 헬퍼
- [x] `scrapers/manager.py` — Playwright 생명주기, 에이전트별 context/page
- [x] `scrapers/claude.py` — claude.ai 제어
- [x] 셀렉터 외부화 — config.yaml `agents.*.selectors`로 분리(코드 수정 없이 교체)
- [x] storageState 로그인 세션 저장/복원
- [x] 응답 완료 감지(스트리밍 셀렉터 + 텍스트 안정화)
- [x] `main.py` 연동 — status/send 실연결, login/login_complete 핸들러
- [ ] **(사용자) 라이브 검증** — 맥에서 로그인·응답 수집, 셀렉터 튜닝

## Phase 3 — 프론트엔드 기본 UI

- [x] 3열 레이아웃 — 역할 고정(동조/반대/엉뚱) + 모델 선택 드롭다운
- [x] 증상 입력 1개 + 진단 시작 버튼
- [x] 실시간 스트리밍 표시 (chunk 수신 → 컬럼 갱신)
- [x] 합성 버튼 — 3열 응답을 Claude에게 합성 요청
- [x] 재반박 루프 — 합성 결과에 반박 의견 → 재반박 수신
- [x] 설정 패널 — 전역 메모리 노트 + 에이전트 enabled/disable
- [x] 컬럼별 모델·프롬프트 편집 + settings.json 영구 저장
- [x] 같은 모델 중복 방지 (역할 붕괴 방지)
- [ ] **(사용자) 라이브 검증** — 실제 브라우저에서 UI 흐름 테스트

## Phase 4 — Gemini / ChatGPT 스크래퍼

- [x] `scrapers/gemini.py` — gemini.google.com 스크래퍼
- [x] `scrapers/chatgpt.py` — chatgpt.com 스크래퍼 (임시 채팅 URL 사용)
- [x] config.yaml 셀렉터 정의
- [ ] **(사용자) 라이브 검증** — 셀렉터 튜닝

## Phase 5 — 역할 설정 + 컨텍스트 제어 + 메모리(MemoryProvider)

- [x] `roles` 정의 — 동조/반대/엉뚱 역할 프롬프트
- [x] `synthesis_prompt` — 팬아웃 후 합성 템플릿
- [x] `consolidate_prompt` — 단계 전환 정리 템플릿
- [x] `memory.global_note` — 전역 메모리 노트
- [x] `context_format` — 대화 히스토리 감싸기 템플릿
- [ ] **(향후) MemoryProvider 확장** — global_note 외 다른 전략 추가 (선택사항)

## Phase 6 — Grok / Perplexity

- [x] `scrapers/grok.py` — grok.com 스크래퍼
- [x] `scrapers/perplexity.py` — perplexity.ai 스크래퍼
- [x] config.yaml 셀렉터 정의
- [ ] **(사용자) 라이브 검증** — 셀렉터 튜닝

## Phase 7 — 모바일 반응형

- [x] 기본 그리드 레이아웃 (3열 CSS Grid)
- [ ] 모바일 뷰포트 테스트 + 미디어 쿼리 적용
- [ ] 터치 인터페이스 최적화
- [ ] 세로 화면에서의 컬럼 스택 처리

## Phase 8 — (향후) 대화 컨텍스트 관리

- [ ] Multi-turn 대화 — 이전 턴의 응답을 컨텍스트로 전달
- [ ] `context_format` 실제 적용 (현재는 setup_prompt만 1회 주입)
- [ ] 대화 히스토리 누적/절단 전략
- [ ] `memory.provider` 교체 가능한 인터페이스 구현

## Phase 9 — (향후) diagnoses.md 자동 관리

- [ ] diagnoses.md 생성/읽기 UI
- [ ] 진단 이력 브라우저 (검색/필터)
- [ ] 진단 통계 (빈도, 패턴)
