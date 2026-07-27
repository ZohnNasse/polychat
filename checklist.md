# PolyChat 체크리스트

설계는 `PolyChat-DESIGN.md`, 작업 이력·결정은 `context-notes.md` 참고. 현행화 2026-07-06.

## 현재 상태 한 줄

팬아웃 감별진단 MVP + MOA 투표 루프까지 구현·E2E 통과(2026-06-29). 남은 건 코드가 아니라 **사용자 실사용 판정** 하나.

## 골격 (Phase 1~2) — 완료

- [x] FastAPI 서버 + `/ws` WebSocket 디스패치
- [x] `scrapers/base.py` — AIScraper 공통 구현(전송·완료감지·대화재사용·로그인)
- [x] `scrapers/manager.py` — 브라우저 생명주기, 에이전트별 탭
- [x] 모델별 스크래퍼 — claude / chatgpt / gemini (thin override)
- [x] 셀렉터 외부화 — `config.yaml agents.*.selectors`(input/response/streaming/send_button)
- [x] 응답 완료 감지 — 스트리밍 셀렉터 소멸 감지(`_collect_response`), 없으면 텍스트 3회 안정화 폴백

## 브라우저 모드 — 완료

- [x] CDP attach 모드 기본 채택 — 사용자의 로그인된 Chrome(:9222)에 접속, 봇 차단 회피
- [x] `cdp_auto_launch` — 9222 비면 전용 프로필(`profiles/cdp`)로 직접 기동
- [x] `persistent` 모드도 지원(`server.browser_mode`로 전환)

## 팬아웃 감별진단 MVP — 완료

- [x] config `roles`(동조/반대/엉뚱) 진단 프레이밍 + 공통 제약(질문금지·과거무시·간결)
- [x] 3열 컬럼 UI — 역할 고정, 모델은 컬럼 드롭다운에서 선택(중복 모델 차단)
- [x] 팬아웃 — 프론트가 `send` 3회(모델별 역할 주입), 순차 스트리밍
- [x] 합성 — `synthesis_prompt` + `handle_synthesize`(Claude 고정), 결과 `diagnoses.md` 기록
- [x] 교차 실행 오염 차단 — `reset` 핸들러 + 임시채팅/새대화 URL(ChatGPT `?temporary-chat=true`, Gemini `/app`, Claude `/new`)

## MOA 투표 루프 — 완료 (2026-06-29)

- [x] `handle_vote` — 3모델 병렬 이의제기(asyncio.gather), `vote_prompt`
- [x] `handle_finalize` — 투표 반영 최종 결론
- [x] `handle_refine` — 사용자 피드백 재검토
- [x] 흐름 E2E — 질문 → 3모델 → 합성 → 투표 → 최종 → 재검토 통과

## 릴레이 모드 — 완료 (2026-07-25, 프론트만)

- [x] 헤더 팬아웃/릴레이 토글, 릴레이 대상 선택 바(`#relayBar`)
- [x] 전역 transcript + `relaySeen` 델타 — 슬롯별 마지막 본 이후 항목만 전달(자기 응답 자동 제외), 첫 턴만 페르소나 주입
- [x] 기존 `send`/`chunk`/`done` 프로토콜 재사용(백엔드·config 무변경), done/error 릴레이 분기
- [x] 릴레이 합성 버튼 — 슬롯별 최신 응답 모아 기존 합성→투표 흐름 연결
- [ ] **(사용자) 릴레이 E2E** — 서버 재기동 후 실사용 검증

## UI — 완료 (2026-06-28~29)

- [x] Apple 라이트 테마 전환
- [x] 수직 채팅 플로우(아바타 + 말풍선), 하단 고정 콤포저(iMessage 스타일)
- [x] 역할 배지(찬/부/엉), 합성 "✦ 종합" 시각 구분

## 전역메모+페르소나 priming (B안) — 완료 (2026-07-27)

- [x] manager.py — global_note 파라미터, send priming 구성(전역메모+페르소나+프리앰블), 복구 시 setup_prompt 보존
- [x] main.py — 매니저에 global_note 전달, handle_send가 setup_prompt 전달, save_settings에서 manager.global_note 갱신
- [x] index.html relaySend — 첫 턴에만 페르소나+릴레이 프리앰블을 setup_prompt로 전송
- [ ] **(사용자) 서버 재기동 후 E2E** — 릴레이 첫 턴 priming 주입 + 탭 닫힘 복구 시 재주입 확인. 팬아웃 첫 대화 global_note priming 턴 확인(원치 않으면 알려줘)

## 회의 테이블 UI (팬아웃·릴레이 공용) — 완료 (2026-07-28, 프론트만)

- [x] `static/index.html` — 세로 스크롤 대신 3좌석 회의 테이블. 좌석마다 고정 아바타(브랜드색+엠블럼)·역할/모델 명패·말풍선(내부 스크롤)·좌우 방향키
- [x] 화자별 발언 이력 페이징 — `histories[slot]`에 자기 발언만 쌓고 `‹ n/N ›`로 앞뒤 이동(다른 화자 발언 안 섞임)
- [x] 팬아웃·릴레이 렌더 경로를 테이블로 통합 — `mtNewUtterance`/`mtUpdate`로 chunk·done 반영, 기존 send/relay/synth/vote 로직·백엔드·config 무변경
- [x] 사용자 발언도 `나` 좌석에 페이징 표시
- [x] 구문검증 — 스크립트 추출 `node --check` 통과
- [ ] **(사용자) 시각 확인** — 브라우저 새로고침(서버 재기동 불필요, 프론트만)으로 좌석·아바타·페이징·스트리밍 확인

## 남은 것

- [ ] **(사용자) 실사용 판정** — 실제 고민 3~5개를 돌려 divergence가 진짜인지 판정. MVP가 검증하려던 단 하나의 가정. 이 판정이 결론이며, 판정 전까지 UI 리디자인·기능 확장 동결.

## 알려진 한계 (판정에 영향)

- 매니저가 모델당 대화 1개 재사용 → 같은 세션에서 2회 돌리면 2번째가 1번째 맥락을 봄(초기화 = "초기화" 버튼/reload).
- ChatGPT/Gemini 계정의 메모리·개인화가 켜져 있으면 누수 가능(코드 밖, 계정 설정에서 꺼야 완전).
- Gemini 간헐적 빈 응답(스트리밍 감지) — 재검증 대상.

## 동결 (판정 통과 후에만)

메모리 주입(GlobalNoteMemory, Phase 5) · 의장 다단계 루프 · 상시 레드팀 · DB(SQLite) · 멀티턴 · Grok/Perplexity · 모바일 반응형. 릴레이 콘솔용 `consolidate` 핸들러/프롬프트는 코드에 휴면 상태로 남아 있음(현 UI 미사용).
