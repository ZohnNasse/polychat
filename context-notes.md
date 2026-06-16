# PolyChat 컨텍스트 노트

작업 중 내린 결정과 그 이유를 누적 기록한다. 다음 세션이 재추론 없이 이어가기 위함이다.

## 환경

- 작업 위치는 `~/workspace/polychat`. 처음엔 Google Drive 동기화 폴더였으나, git lock 충돌과 sandbox 마운트 권한 문제로 로컬로 이전했다.
- git 커밋·push는 사용자의 맥 터미널에서 수행한다. 에이전트 sandbox는 호스트 폴더 마운트 계층 제약으로 `.git/*.lock` 삭제가 막혀 git 쓰기 작업이 불안정하다. 코드 읽기/쓰기/편집은 정상.
- 원격: `https://github.com/ZohnNasse/polychat` (public).

## 설계 결정

- 메모리는 v1에서 장기 기억을 넣지 않는다. 대화 내 연속성은 SQLite 이력 + `context_format`으로 충분. 멀티 AI 일관성을 위해 기억은 PolyChat이 중앙에서 주입하며, v1은 `config.yaml`의 전역 노트(GlobalNoteMemory). 전략은 `MemoryProvider` 인터페이스 뒤에 두어 교체 가능하게 설계했다. (DESIGN 문서 "메모리" 섹션 참고)
- 컨텍스트 조립 순서는 `memory.preamble → role_prompt → context_format(history) → user message`.

## Phase 2 진행 메모

- 셀렉터는 코드 상수가 아니라 `config.yaml`의 `agents.*.selectors`(input/response)로 외부화했다. claude.ai 등 UI가 바뀌면 설정 두 줄만 고치면 되고 코드는 안 건드린다. 매니저가 스크래퍼 생성 시 주입한다.
- 로그인은 헤드풀 브라우저에서 사용자가 직접 수행 → UI의 "로그인 완료" 버튼이 `login_complete`를 보내면 storageState를 `sessions/{agent}.json`에 저장한다.
- 입력은 `keyboard.insert_text`로 넣는다(줄바꿈을 Enter=전송으로 오해하지 않게). 그 뒤 Enter로 전송.
- 컨텍스트/메모리 패키징은 아직 미적용(Phase 5). Phase 2 send는 raw text를 그대로 보낸다.
- 대화 재사용 결정: 매 턴 `/new`로 새 대화를 만들면 감당 불가 → 대화를 1회만 생성하고 그 URL(conversation_url)을 재사용한다. 첫 진입 시 `role_prompt`를 setup_prompt로 1회 주입(향후 모델별 설정 자리)하고, 그 전송으로 생긴 `/chat/<id>` URL을 캡처해 이후 모든 턴이 같은 대화에 들어간다. setup_prompt가 비어 있으면 첫 사용자 메시지 후 URL을 캡처한다. (base.AIScraper에 setup_prompt/conversation_url 보관, manager가 role_prompt 주입)
- 응답 완료 감지 결정: 텍스트 안정화(_wait_until_stable)는 inner_text가 미세 변동하면 120초 타임아웃까지 대기해 "답 끝나도 한참 멈춤" 문제가 있었다. → 스트리밍 표시 셀렉터(claude: `div[data-is-streaming="true"]`)가 사라지는 시점을 완료로 보는 `_wait_done`으로 교체. 라이브 검증 완료(답 끝나자마자 다음 전송됨). streaming 셀렉터가 config에 없으면 텍스트 안정화로 자동 폴백. 다른 모델 스크래퍼도 각자 streaming 셀렉터를 config에 넣으면 동일하게 동작.
- 인터페이스화 결정: 전송·완료감지·대화재사용·로그인확인 로직을 ClaudeScraper에서 base.AIScraper 공통 구현으로 올렸다. 모델별 스크래퍼는 `service_id/display_name/url` 3개만 정의하고 동작이 다르면 해당 메서드만 오버라이드한다. 셀렉터(input/response/streaming)는 config로 주입. 새 대화 판별은 claude 전용 "/new" 문자열 대신 `_is_fresh()`(현재 URL == self.url)로 일반화해 모델별 URL 스킴 차이를 흡수한다.
- 설정 UI 결정: 모델별 role_prompt·전송 on/off·전역 메모리 노트를 웹 UI "설정" 패널에서 편집한다. config.yaml은 기본값, 편집값은 별도 `settings.json`에 영구 저장(.gitignore 처리, 사용자별 로컬). 서버 startup에서 settings 로드 후 `apply_to_agents`로 role_prompt를 AGENTS에 반영 → 매니저가 setup_prompt로 사용. WS: get_settings/save_settings. 한계: 이미 생성된 스크래퍼는 setup_prompt를 생성 시점에 캐시하므로 role_prompt 변경은 새 대화부터 적용(추후 "대화 초기화" 필요). global_note는 저장만 되고 실제 주입은 Phase 5.
- 한계: Playwright 헤드풀 + 실제 claude.ai 로그인/셀렉터 동작은 사용자 맥에서만 검증 가능. sandbox는 import/문법까지만 확인함.

### 카드 UI + 실시간 스트리밍 결정

- UI는 "한 번의 전송 = 한 턴" 구조. 턴마다 내 메시지 + 대상 모델별 응답 카드(가로 배치, flex-wrap)를 묶어 보여준다. 본문은 일반 텍스트(white-space: pre-wrap), 마크다운 렌더 안 함.
- 스트리밍 방식: 완료 후 한 번에 보내던 `_wait_done`/`_wait_until_stable`을 단일 `_collect_response(on_update)`로 통합. 0.4초 간격 폴링하며 누적 텍스트가 바뀔 때마다 on_update로 흘려보낸다. 완료 판정은 streaming 셀렉터가 있으면 그것이 사라질 때, 없으면 텍스트가 3회 연속 동일할 때.
- WS 프로토콜: 생성 중 `chunk`(누적 텍스트, 델타 아님)를 여러 번 → 끝나면 `done`(최종 텍스트 포함). 프론트는 turn_id로 카드를 찾아 textContent를 통째로 교체(누적이라 유실에 강함). 에러도 turn_id로 해당 카드를 빨갛게 표시.
- main.py handle_send가 모델·turn_id를 바인딩한 on_update 클로저를 만들어 manager.send에 넘긴다. 직렬 루프라 모델별로 순차 스트리밍된다(동시 아님 — 사용자 요청).

### 로그인/브라우저 모드 결정 (중요)

- 자동으로 띄운 브라우저에 직접 로그인하는 방식은 Cloudflare(Claude)와 Google "안전하지 않은 브라우저" 차단에 양쪽 다 막혔다.
- 해결: **CDP attach 모드를 기본 채택.** 사용자가 평소 쓰는(이미 로그인된) Chrome을 `--remote-debugging-port=9222`로 띄우고, 서버가 `connect_over_cdp`로 접속만 한다. 새 로그인이 없으니 봇 차단을 원천 회피. Chrome 1개 + 에이전트별 탭이라 가벼움.
- `BrowserManager`는 `browser_mode`로 `cdp`(기본)와 `persistent`(영구 프로필 직접 기동)를 모두 지원한다. config `server.browser_mode`로 전환.
- stop() 시 cdp 모드는 우리가 연 탭만 닫고 사용자 Chrome은 건드리지 않는다.

## Phase 1 진행 메모

- 스크래퍼(Playwright)는 Phase 2 범위. Phase 1의 WebSocket은 `status`/`send`를 받지만 실제 AI 호출 없이 스텁 응답만 돌려준다. 골격 검증이 목적.
