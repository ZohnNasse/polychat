# PolyChat 워크플로 — 남은 작업 순차 해결

현행화 2026-07-27. 상태 추적은 `checklist.md`, 결정 이력은 `context-notes.md`, 설계는 `PolyChat-DESIGN.md`.

## 큰 그림

로컬 MVP 마감 → **실사용 판정(게이트)** → 통과 시 Electron 배포. 판정 전까지 리디자인·기능 확장은 동결(DESIGN 규칙). Electron은 종착지지만 판정 통과 전 착수 금지.

## 원칙

- 한 번에 한 단계. 각 단계의 "검증"을 통과해야 다음으로 넘어간다.
- config·스크래퍼·서버 코드를 바꾸면 **서버 재시작 필수**(자동 반영 안 됨).
- 커밋은 단계 끝마다. 에이전트가 명령을 건네고 사용자가 실행한다(샌드박스는 git 실행 불가).

---

## Phase 0 — 이번 세션 마무리(안정화)

### 0-1. 미커밋 변경 커밋
- 대상. `CLAUDE.md`(지침 현행화), `config.yaml`(포트 9223 격리), `scrapers/manager.py`(탭 자가복구), `context-notes.md`.
- 검증. `git status` 클린, origin/main 동기화.

### 0-2. 브라우저 격리 검증(포트 9223)
- 서버 재시작 후 polychat이 9223 전용 프로필(`profiles/cdp`)로 자기 창을 띄우는지 확인.
- 검증. 에이전트 AI의 9222 Chrome과 별개 프로세스로 뜬다. 일상 프로필로 안 열린다. 최초 1회 AI 로그인 필요할 수 있음.

### 0-3. 탭 닫힘 자가복구 검증
- 임의 에이전트 탭을 닫았다가 다시 전송.
- 검증. 새 탭이 자동 생성되고 같은 대화(`conversation_url`)로 이어진다. "응답 대기" 멈춤 없음.

---

## Phase 1 — 로컬 MVP 마감(판정 전 필수)

### 1-1. Gemini 완료감지 버그
- 증상. Gemini 탭엔 응답이 다 나오는데 polychat은 "응답 대기중"에서 멈춘다. 원인은 config에 gemini `streaming` 셀렉터가 없어 텍스트 안정화 폴백에 의존하기 때문.
- 작업. JS 콘솔로 완료 시점 DOM 신호를 탐색 → `config.yaml` gemini `selectors.streaming` 추가.
- 검증. Gemini 단독 3회 전송 모두 완료 감지.

### 1-2. 릴레이 모드 E2E
- 검증. 팬아웃/릴레이 토글 → 슬롯별 델타 전달(자기 응답 제외) → done 복귀 → 합성 버튼까지 실사용 통과.

### 1-3. 프론트 디자인 마감
- 범위. 남은 디자인 다듬기. 동결 규칙상 "리디자인"이 아니라 마감 수준으로 한정.
- 검증. 주요 플로우 시각 확인.

---

## Phase 2 — 실사용 판정(게이트)

- 실제 고민 3~5개를 돌려 divergence가 진짜인지 판정. MVP가 검증하려던 단 하나의 가정.
- 검증. 판정 결과를 `context-notes.md`·`checklist.md`에 기록. 통과/실패 명시.
- 이 게이트를 통과해야 아래 동결이 해제된다.

---

## Phase 3 — Electron 배포(판정 통과 후에만)

- 목표. 터미널+외부 Chrome+Playwright 3종을 자립형 데스크톱 앱으로 합친다. 메인 프로세스가 `webContents.executeJavaScript`로 오케스트레이션(웹 샌드박스 밖이라 가능).
- 선결. 봇 감지 검증(UA 위장·스텔스), Python→JS 오케스트레이션 이관 범위 확정.
- 주의. 큰 재작성이다. 판정 통과 전 착수 금지.
- 가벼운 다리(선택). 지금 UX만 개선하려면 PyInstaller/py2app/`.command` 래핑으로 "앱처럼 실행"만 먼저 해결 가능. 현재 Python+CDP·진짜 Chrome 붙는 정당성 유지.
