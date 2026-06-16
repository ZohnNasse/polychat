# PolyChat 컨텍스트 노트

작업 중 내린 결정과 그 이유를 누적 기록한다. 다음 세션이 재추론 없이 이어가기 위함이다.

## 환경

- 작업 위치는 `~/workspace/polychat`. 처음엔 Google Drive 동기화 폴더였으나, git lock 충돌과 sandbox 마운트 권한 문제로 로컬로 이전했다.
- git 커밋·push는 사용자의 맥 터미널에서 수행한다. 에이전트 sandbox는 호스트 폴더 마운트 계층 제약으로 `.git/*.lock` 삭제가 막혀 git 쓰기 작업이 불안정하다. 코드 읽기/쓰기/편집은 정상.
- 원격: `https://github.com/ZohnNasse/polychat` (public).

## 설계 결정

- 메모리는 v1에서 장기 기억을 넣지 않는다. 대화 내 연속성은 SQLite 이력 + `context_format`으로 충분. 멀티 AI 일관성을 위해 기억은 PolyChat이 중앙에서 주입하며, v1은 `config.yaml`의 전역 노트(GlobalNoteMemory). 전략은 `MemoryProvider` 인터페이스 뒤에 두어 교체 가능하게 설계했다. (DESIGN 문서 "메모리" 섹션 참고)
- 컨텍스트 조립 순서는 `memory.preamble → role_prompt → context_format(history) → user message`.

## Phase 1 진행 메모

- 스크래퍼(Playwright)는 Phase 2 범위. Phase 1의 WebSocket은 `status`/`send`를 받지만 실제 AI 호출 없이 스텁 응답만 돌려준다. 골격 검증이 목적.
