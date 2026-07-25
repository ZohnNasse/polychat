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

### 회의 콘솔 재설계 (2026-06-16, 중요)

- 비전 전환: "같은 질문 동시 브로드캐스트"를 폐기하고 **사용자가 사회 보는 수동 릴레이 회의 콘솔**로 전면 재작성. 단일 라우팅(한 번에 한 모델), 단계별 동적 역할, 사용자 큐레이션 점진 컨텍스트, 인간 종료.
- 단계 전환 = **2스텝 핸드오프**. (1) "전달" 누르면 직전 모델에게 `consolidate_prompt`(자기 대화 컨텍스트 + 사용자 의견 → 화자 분리·정리)를 보내 정리본을 받는다. (2) 정리본을 사용자가 편집·확정하면 `역할 프롬프트 + 정리본`을 다음 모델로 전송. 정리 노동은 직전 모델이, 최종 통제는 사용자가(편집 게이트). (이전 메모리의 "정리는 사용자가 직접"에서 변경됨.)
- 역할은 config 고정값이 아니라 **턴별 주입**. config `roles`(긍정/부정/개소리/레드팀) 프리셋을 드롭다운으로 제공하되 프롬프트 textarea에서 자유 편집 가능. 전송 텍스트 = `role_prompt + "\n\n" + content`를 main.py handle_send가 조립.
- WS 프로토콜 변경: `send`가 다중 `target` 배열 → 단일 `agent` + `role_prompt` + `content` + `turn_id`. `consolidate`(`agent`,`my_opinion`) 신설 → `consolidate_chunk`/`consolidate_done`로 정리본 스트리밍. settings 페이로드에 `roles` 추가.
- 프론트 전면 교체: 카드 그리드 → **세로 타임라인**. 의제 composer(1회) → 단계마다 모델·역할 뱃지 + 응답 + 연결부(내 의견 → 정리 → 다음 모델/역할 선택). 정리 스트림은 직렬 가정 하에 단일 `pendingConsolidate` 박스로 라우팅. `crypto.randomUUID()`로 turn_id 생성(localhost=보안 컨텍스트라 가용).
- 한계: 라이브 3단계 end-to-end는 사용자 맥에서 검증 필요(#29). 2턴째 응답 갱신/`.response-content` 중복 의심(Gemini len=533 2회)도 이때 같이 확인.

### 팬아웃 감별진단 MVP 전환 (2026-06-20, 현재 방향)

- overseer 브리핑(POLYCHAT-SESSION-BRIEF) 반영해 **릴레이 콘솔 → 팬아웃 MVP**로 재초점. House M.D. 감별진단: 사용자=환자, 모델 팀이 진단. 검증할 단 하나의 가정 = "역할 박은 멀티모델이 진짜 divergence를 내는가". 안 나오면 접는 것도 결론.
- MVP 범위: 증상 1개 → 세 역할(동조/반대/엉뚱) 모델에 **동시 전송** → 3열 응답 → Claude가 1회 **합성**(검증할 가설 N개 + 레드팀 반박 한 단락). 멀티턴·DB·의장 루프·상시 레드팀 전부 제외.
- 절대 제약 3: (1) 역할은 **서로 다른 베이스 모델**에 박는다(같은 모델 프롬프트만 바꾸면 sycophancy로 동조 수렴). (2) 출력은 결론이 아니라 '검증할 가설'(모델은 모르는 업계도 자신있게 지어냄). (3) 사용자=환자 — 증상의 진실성·최종 동의는 사람이 쥔다.
- 역할↔모델 매핑은 **고정 안 하고 UI 컬럼 드롭다운에서 매번 선택**(사용자 결정). 기본 동조=Claude/반대=ChatGPT/엉뚱=Gemini. 합성은 Claude 고정(SYNTH_AGENT).
- 구현: 백엔드 거의 그대로 재사용. 팬아웃은 프론트가 `send`를 3회(모델별 역할 주입). 신설은 `synthesis_prompt`(config) + `handle_synthesize`(main.py, `synthesize` 타입 → `synthesis_chunk/done`)뿐. config roles를 동조/반대/엉뚱 진단 프레이밍으로 갱신, redteam 역할은 합성에 흡수돼 제거.
- 프론트 전면 교체: 세로 타임라인 → **증상 입력 1개 + 3열 컬럼(역할 고정·모델 선택) + 합성 패널**. 세 컬럼 done 시 합성 버튼 활성.
- 휴면: 릴레이용 `consolidate` 핸들러·`consolidate_prompt`는 남겼지만 현 UI 미사용. 키운 버전(의장 루프) 갈 때 부활 가능.
- 한계: 매니저가 모델당 대화 1개 재사용 → 증상 2회 돌리면 2번째가 1번째 컨텍스트를 봄(MVP는 단발, 초기화는 페이지 reload). Claude가 동조 컬럼이면 합성 호출이 같은 대화에 들어가 자기 동조 답을 봄(합성 프롬프트에 3답 전문을 넣으므로 MVP 허용). 라이브 3열+합성 end-to-end는 사용자 맥에서 검증 필요(#29).

### 1차 라이브 실행 피드백 수정 (2026-06-20)

라이브 첫 실행에서 3문제. (1) ChatGPT·Gemini가 과거 대화/기억을 끌어와 오염, (2) Claude가 진단 대신 사용자에게 되물어 답이 안 옴, (3) 출력이 너무 김. 첫 실행이라 conversation_url 재사용 탓은 아니고 모델 측 기억·탭의 이전 대화 재오픈 + 프롬프트 제약 부재가 원인.
- 역할 프롬프트(동조/반대/엉뚱) 끝에 공통 제약 추가: "질문하지 말고 바로 답(정보 부족 시 가정 한 줄 후 진행)·과거 대화/기억 무시·가설 3개 이내·각 1~2문장·전체 5문장 이내". 합성 프롬프트에도 질문금지·간결 추가.
- URL을 새 대화로 고정: ChatGPT `?temporary-chat=true`(기억·과거 미참조, 단 새로고침 시 일반채팅으로 열리는 알려진 버그 있음), Gemini `/app`(이전 대화 자동 재오픈 방지), Claude `/new` 유지.
- 교차 실행 오염 차단: manager.reset() + WS `reset` 핸들러 신설. 프론트 "초기화"는 `reset` 전송 → `reset_done` 수신 시 reload(서버 conversation_url까지 비움). #21 완료.
- 남은 한계: ChatGPT/Gemini 계정의 메모리/개인화가 켜져 있으면 여전히 누수 가능 → 가장 깨끗한 해법은 사용자가 계정 설정에서 끄는 것(코드 밖). ChatGPT 임시채팅 param이 안 먹는 경우도 보고됨 → 라이브 재검증 필요.

### 로그인/브라우저 모드 결정 (중요)

- 자동으로 띄운 브라우저에 직접 로그인하는 방식은 Cloudflare(Claude)와 Google "안전하지 않은 브라우저" 차단에 양쪽 다 막혔다.
- 해결: **CDP attach 모드를 기본 채택.** 사용자가 평소 쓰는(이미 로그인된) Chrome을 `--remote-debugging-port=9222`로 띄우고, 서버가 `connect_over_cdp`로 접속만 한다. 새 로그인이 없으니 봇 차단을 원천 회피. Chrome 1개 + 에이전트별 탭이라 가벼움.
- `BrowserManager`는 `browser_mode`로 `cdp`(기본)와 `persistent`(영구 프로필 직접 기동)를 모두 지원한다. config `server.browser_mode`로 전환.
- stop() 시 cdp 모드는 우리가 연 탭만 닫고 사용자 Chrome은 건드리지 않는다.
- 자동 실행(cdp_auto_launch): 9222가 비어 있으면 서버가 Chrome을 직접 띄운다. 프로필은 **전용 프로필(profiles/cdp)** 사용으로 확정(2026-06-16). 실제 프로필을 쓰니 세션 복원으로 창 5개가 열리고, 평소 Chrome이 같은 프로필로 떠 있으면 디버그 포트가 안 열리는 문제가 있었다. 전용 프로필은 깔끔한 단일 창 + 평소 Chrome과 동시 사용 가능 + 세션 복원 없음. 대신 AI 3개에 최초 1회 로그인 필요(profiles/cdp에 영구 저장). chrome_user_data_dir 설정·_user_data_dir() 메서드·user_data_dir 인자는 이 결정으로 제거.

## Phase 1 진행 메모

- 스크래퍼(Playwright)는 Phase 2 범위. Phase 1의 WebSocket은 `status`/`send`를 받지만 실제 AI 호출 없이 스텁 응답만 돌려준다. 골격 검증이 목적.

## 스크래핑 기초 동작 수정 (2026-06-20)
- 옛 대화 텍스트("번뜩이는 신입개발자") 캡처 원인 = base._collect_response가 새 응답 대기 없이 nth(n-1)을 즉시 읽음. → 전송 직전 응답 개수를 baseline으로 잡고, count가 baseline을 넘는(새 응답) 경우에만 읽도록 변경. 모델 무관.
- ChatGPT 임시채팅 URL이 무시된 원인 = base._ensure_conversation이 클래스 self.url("https://chatgpt.com")로 이동. config의 url이 죽은 값. → manager._ensure_scraper에서 cfg_url을 scraper.url에 반영.
- 같은 모델 중복 선택 시 단일 탭/대화로 직렬화되어 컬럼이 섞임(브리프상 역할은 서로 다른 모델이어야 함). → index.html startDiagnosis에서 중복 모델 alert 후 차단.
- ChatGPT streaming 셀렉터는 미검증이라 추가 안 함(틀린 셀렉터는 첫 청크에서 조기 종료 위험). same>=3 폴백이 baseline 수정으로 정상 동작.

## 라이브 로그 기반 2차 수정 (2026-06-20)
- 증상: collect이 모델당 2번 돎(GPT len 427→775 식), Claude는 2번 다 len=0/120초 타임아웃.
- 원인1(이중 collect + 잡설 오염): settings.json에 팬아웃 전환 전 옛 role_prompt("냉철한 pm","번뜩이는 신입 개발자" 등)가 잔존 → apply_to_agents가 AGENTS[*].role_prompt에 복사 → _ensure_conversation이 setup_prompt로 증상 전에 첫 메시지로 전송. settings.json role_prompt 전부 "" 처리로 해결(팬아웃은 역할 프롬프트를 컬럼에서 증상과 함께 보냄).
- 원인2(Claude 무응답): 응답 셀렉터 'div.font-claude-message'가 현재 claude.ai에서 0개(죽음). 콘솔 querySelectorAll로 확인: '.font-claude-response'=살아있음. config claude response를 '.font-claude-response', streaming을 '[data-is-streaming="true"]'(태그 비의존)로 교체. 스트리밍 셀렉터 자체는 정상이었고 응답 셀렉터만 문제였음.

## UI 리뉴얼 (2026-06-28)

- 컨셉 변경: "감별진단 콘솔" → "1인 개발자를 위한 아이디어 검증 작업장". House MD 의학적 프레임워크를 vibes 코딩 작업장으로 전환. 세 가지 각도(찬성/부정/엉뚱)에서 의견을 수집하고 종합하는 MOA(Multiple Opinion Aggregation) 스타일.
- 디자인: 다크 테마 + 그라데이션 + 글로우 제거. Apple 스타일 라이트 테마로 전환 — `#f5f5f7` 배경, 흰 카드, SF Pro 계열 폰트, pill 버튼, 부드러운 그림자 (`0 2px 12px rgba(0,0,0,0.08)`).
- 역할 배지: 각 역할에 점(도트) + 텍스트 배지로 변경. 찬성=초록(rgba(52,199,89,0.12)), 부정=빨강(rgba(255,59,48,0.1)), 엉뚱=주황(rgba(255,149,0,0.12)).
- 콤포저: "증상 입력" → "무엇을 고민 중인가요?"로 라벨 변경. 입력 영역에 Enter 팁 표시. "진단 시작" → "시작" 버튼 텍스트 단순화.
- 합성 패널: "Claude 합성 (가설 + 레드팀)" → "합성하기"로 간소화. 상단에 "✦ 종합" 라벨 추가, 중앙 정렬.
- 헤더: "감별진단 콘솔" → "세 가지 시선으로 더 나은 코드를". 불필요한 status 버튼 제거. 설정 버튼에서 ⚙ 이모티콘 제거.
- 재반박 섹션: "재반박" → "재검토"로 라벨 변경.
- 전체적으로 모서리 반경 12px/16px, pill 버튼(980px radius), `cubic-bezier(0.25, 0.1, 0.25, 1)` 트랜지션으로 Apple UI 느낌 통일.

## UI v2 — 채팅 메시지 스타일 (2026-06-29)

- 3열 카드 레이아웃 → **수직 채팅 플로우**로 변경. 그래픽적 UX: 각 AI 응답이 아바타(원형, 역할별 색상) + 말풍선 버블로 나타남.
- 사용자 메시지는 우측 파란 버블, AI 응답은 좌측 흰 버블 + 컬러 아바타.
- 역할 배지: 찬성(초록, "찬"), 부정(빨강, "부"), 엉뚱(주황, "엉") — 아바타 안에 한글 자음 표시.
- 콤포저: 화면 하단에 fixed로 고정 (iMessage 스타일). 전송 버튼은 원형 아이콘 버튼.
- 역할 설정: 접을 수 있는 패널로 분리 (설정과 분리).
- 빈 화면: 큰 아이콘 + "무엇을 고민 중인가요?" 빈 상태 메시지.
- 합성: "✦ 종합" 라벨 + 그라데이션 아바타로 시각적 구분.
- 헤더: backdrop-filter 블러로 sticky (Apple 스타일 네비게이션 바).
- `bubbleIn` 애니메이션: `cubic-bezier(0.34, 1.56, 0.64, 1)` (스프링 느낌)으로 메시지 등장.
- Enter 전송: `keydown` 이벤트 리스너로 직접 바인딩 (이전에는 `enterToSend` 헬퍼 사용).
- columns 구조 변경: DOM 요소 대신 데이터 객체로 유지, config 패널에서 설정 저장/로드.

## MOA 투표 루프 + Grok/Perplexity 제거 (2026-06-29)

- Grok/Perplexity 제거: settings.json, config.yaml, scrapers/__init__.py에서 삭제. 모델은 Claude, ChatGPT, Gemini 3개.
- MOA 투표 루프 흐름: 질문 → 3모델 → 합성 → **투표**(3모델이 합의안에 이의제기) → **최종 결론**(투표 반영) → 재검토(사용자 피드백)
- 백엔드: `handle_vote` (3개 모델 병렬 투표, asyncio.gather), `handle_finalize` (투표 결과 반영 최종 합성) 핸들러 신설. `vote_prompt` config.yaml에 추가.
- WS 프로토콜: `vote` (agents 배열 + synthesis + vote_turn_id) → `vote_chunk`/`vote_done` (각 모델) → `vote_round_complete` → `finalize` → `finalize_chunk`/`finalize_done`
- 프론트: 합성 후 "투표하기" 버튼 → 각 모델별 투표 버블 → "최종 결론" 버튼 → 최종 결과 → 재검토
- Gemini 전송 문제: Enter 키가 불안정해 `_submit` 오버라이드. ChatGPT/Gemini에 `send_button` 셀렉터 추가.
- End-to-end 테스트: 팬아웃(3개 모델) → 합성(625자) → 투표(Claude/ChatGPT/Gemini 3개) → 최종 결론(488자) 성공. Gemini가 간헐적으로 빈 응답 발생(스트리밍 감지 문제).

## 문서 정합화 (2026-07-06, overseer)

- 이 노트가 어느 시점부터 `architecture.md`(untracked)에 append돼 왔다. `context-notes.md`는 06-20에서 멈춘 옛 복사본이었다(diff상 84줄까지 동일, 이후 06-28/06-29 3섹션만 architecture.md에 존재). 노트를 빼먹은 게 아니라 파일명이 어긋난 것.
- 조치. architecture.md 전체를 context-notes.md로 통합하고 architecture.md는 제거. 앞으로 작업 노트는 이 파일 한 곳에만 쌓는다.
- 코드 현실(06-29 기준). 모델 3개(Claude/ChatGPT/Gemini), 팬아웃 → 합성 → MOA 투표(vote/finalize) → 재검토까지 구현되고 E2E 성공. 반면 PolyChat-DESIGN.md와 checklist.md는 브로드캐스트/릴레이 시절 기준이라 여전히 드리프트. 다음 조치로 이 둘을 현행화한다.
- 완료(같은 날). checklist.md·PolyChat-DESIGN.md 전면 현행화. WS 핸들러 12개와 outbound type은 main.py를 grep으로 실측해 반영. 검증 중 추가 발견 2건 문서에 기록. (1) `scrapers/grok.py`·`perplexity.py`가 레지스트리(SCRAPERS)에서 빠졌는데 파일은 잔존 — 죽은 코드, 삭제는 판정 후. (2) 최상위 `settings.py`(설정 병합 모듈) 누락돼 있어 구조도에 추가.

## 2026-07-25 릴레이 모드 추가 (팬아웃과 병행)
- 요구. 3-LLM 대화 유지하되 사용자가 매 턴 특정 LLM을 골라 순차 릴레이. 각 LLM은 페르소나 유지, 자기 응답은 다시 안 받고 나·타 LLM 응답만 델타로 받는다. 각 LLM 웹 대화(conversation_url) 재사용으로 기억 일관성 유지.
- 결정. 팬아웃/릴레이 두 모드 병행(헤더 토글). 합성·투표는 릴레이에서도 버튼으로 선택적.
- 구현 범위. index.html 프론트만. 백엔드(main.py handle_send)·config 무변경 — 델타를 프론트에서 만들어 기존 send 프로토콜 재사용. 그래서 계획상 config 델타포맷(#13)·relay 핸들러(#14)는 불필요로 삭제.
- 메커니즘. 전역 transcript[]({speaker:'user'|slotIdx,label,text}) + relaySeen[slotIdx]=마지막 본 인덱스. relayDelta(slot)=seen 이후 항목만 라벨(`[나]`,`[찬성·Claude]`)로 이어붙임 → 자기 응답은 인덱스로 자동 제외. 첫 턴만 role_prompt(페르소나) 주입, 이후 "".
- WS 재사용. 릴레이 턴 객체에 relay:true 플래그. chunk는 공통, done/error에서 relay 분기(relayDone: transcript push + seen 갱신 + 버튼 재활성). 팬아웃 columns.every(done) 로직과 분리.
- 릴레이 합성. 각 슬롯 최신 응답 모아 기존 synthesize로 전송 → synthesis_done이 기존 vote 흐름을 그대로 연결(voteBtn이 columns 사용하므로 릴레이서도 동작).
- 검증. node --check로 스크립트 구문 통과. E2E(#17)는 서버 재기동 후 실사용 확인 필요.
