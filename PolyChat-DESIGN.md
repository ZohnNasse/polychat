# PolyChat 기술 설계 문서

## 개요

PolyChat은 Claude, Gemini, Grok, Perplexity 등 여러 AI 서비스와 동시에 대화할 수 있는 웹 기반 채팅 플랫폼이다. API 키 없이 각 서비스의 웹 인터페이스를 브라우저 자동화로 제어하며, 사용자가 메시지 흐름을 직접 제어한다.

---

## 핵심 설계 원칙

1. **사용자 제어 흐름**: 각 AI의 응답 후 다음 수신자를 사용자가 직접 선택한다.
2. **API 불필요**: 각 서비스의 웹 UI를 Playwright로 제어한다.
3. **웹 기반**: 로컬 서버에 접속하는 방식이므로 같은 네트워크의 모바일에서도 사용 가능하다.
4. **확장 가능**: AI 서비스를 플러그인 방식으로 추가할 수 있다.

---

## 아키텍처

```
[사용자 브라우저 / 모바일]
        ↕ WebSocket
[FastAPI 서버 (localhost:7777)]
        ↕ Playwright
[각 AI 서비스 브라우저 세션]
   ├── claude.ai (Chromium context A)
   ├── gemini.google.com (Chromium context B)
   ├── grok.com (Chromium context C)
   └── perplexity.ai (Chromium context D)
```

### 구성 요소

| 구성 요소 | 기술 | 역할 |
|-----------|------|------|
| 웹 서버 | FastAPI (Python) | REST API + WebSocket 처리 |
| 브라우저 자동화 | Playwright (async) | 각 AI 세션 제어 |
| 프론트엔드 | 단일 HTML 파일 | 채팅 UI (반응형) |
| 세션 저장 | Playwright storageState | 로그인 상태 유지 |
| 대화 저장 | SQLite | 대화 이력 |

---

## 디렉토리 구조

```
polychat/
├── main.py                  # FastAPI 앱 진입점
├── config.yaml              # AI 서비스 설정
├── requirements.txt
├── sessions/                # Playwright 세션 파일 (로그인 상태)
│   ├── claude.json
│   ├── gemini.json
│   ├── grok.json
│   └── perplexity.json
├── db/
│   └── conversations.db     # SQLite 대화 이력
├── scrapers/                # 서비스별 스크래퍼
│   ├── base.py              # 추상 베이스 클래스
│   ├── claude.py
│   ├── gemini.py
│   ├── grok.py
│   └── perplexity.py
├── memory/                  # 교체 가능한 메모리 전략
│   ├── __init__.py          # provider 팩토리
│   ├── base.py              # MemoryProvider 추상 인터페이스
│   └── global_note.py       # v1: 전역 노트 주입
└── static/
    └── index.html           # 프론트엔드 (단일 파일)
```

---

## AI 서비스 스크래퍼 설계

### 베이스 클래스

```python
class AIScraper:
    service_id: str          # "claude", "gemini" 등
    display_name: str        # "Claude", "Gemini" 등
    url: str                 # 서비스 접속 URL
    session_file: str        # storageState 저장 경로

    async def setup(browser)      # 브라우저 컨텍스트 초기화
    async def is_logged_in()      # 로그인 여부 확인
    async def login_manual()      # 수동 로그인 안내 후 대기
    async def send_message(text, context) -> str  # 메시지 전송 + 응답 수집
    async def clear_conversation()               # 새 대화 시작
```

### 서비스별 스크래핑 전략

| 서비스 | URL | 입력 셀렉터 | 응답 감지 방법 |
|--------|-----|------------|----------------|
| Claude | claude.ai/new | `div[contenteditable]` | 스트리밍 완료 감지 (타이핑 인디케이터 사라짐) |
| Gemini | gemini.google.com | `rich-textarea` | `.response-content` 안정화 대기 |
| Grok | grok.com | `textarea` | `.message-bubble` 마지막 항목 안정화 |
| Perplexity | perplexity.ai | `textarea` | `.prose` 블록 완료 감지 |

### 응답 완료 감지 전략

스트리밍 응답은 텍스트가 계속 바뀌므로 완료 시점을 감지해야 한다.

```
1. 응답 요소 등장 감지
2. 0.5초 간격으로 텍스트 길이 샘플링
3. 연속 3회 동일하면 완료로 판정
4. 최대 대기 시간: 120초
```

---

## 메시지 흐름 제어

### 대화 상태 모델

```
ConversationTurn {
    id: uuid
    role: "user" | "claude" | "gemini" | "grok" | "perplexity"
    content: string
    timestamp: datetime
    forwarded_to: [role]    # 이 메시지가 전달된 AI 목록
    forwarded_from: role    # 이 응답이 어느 응답을 보고 생성됐는지
}
```

### 사용자 흐름 예시

```
1. 유저가 메시지 입력
   → 전달 대상 선택 (Claude / Gemini / 둘 다)

2. Claude가 응답
   → 유저에게 옵션 제시:
     [Gemini에 전달] [편집 후 전달] [내가 직접 답장] [새 질문]

3. 유저가 [Gemini에 전달] 선택
   → 컨텍스트 구성:
     "User: {원본 메시지}\nClaude: {Claude 응답}"
   → Gemini에 전송

4. Gemini가 응답
   → 동일한 옵션 제시
```

### 컨텍스트 전달 방식

각 AI에게 전달할 때 이전 대화를 어떻게 패키징할지 설정 가능.

```yaml
# config.yaml
context_format: |
  다음은 지금까지의 대화야:
  
  {history}
  
  위 대화를 참고해서 답변해줘.
```

---

## 역할(Role) 설정

각 AI에게 페르소나를 부여할 수 있다.

```yaml
# config.yaml
agents:
  claude:
    display_name: "Claude"
    color: "#D97706"
    role_prompt: |
      너는 논리적이고 분석적인 관점으로 답변해.
      다른 AI의 의견에 동의하지 않으면 반드시 반박해.

  gemini:
    display_name: "Gemini"
    color: "#3B82F6"
    role_prompt: |
      너는 창의적이고 감성적인 관점으로 답변해.
      항상 실제 사례나 비유를 들어 설명해.

  grok:
    display_name: "Grok"
    color: "#10B981"
    role_prompt: ""   # 빈값이면 기본 동작
```

역할 프롬프트는 메시지 전송 시 컨텍스트 앞에 자동으로 붙는다.

---

## 메모리(Memory)

### 설계 결정

장기 기억은 v1 범위에서 제외한다. 대화 내 연속성은 SQLite 이력 + `context_format` 패키징으로 이미 해결되므로 별도 시스템이 필요 없다. 다만 멀티 AI 환경에서 각 서비스의 계정 단위 메모리가 제각각 끼어드는 문제를 막기 위해, 기억은 **각 서비스에 위임하지 않고 PolyChat이 중앙에서 모든 AI 컨텍스트에 동일하게 주입**한다.

v1 구현은 가장 단순한 형태인 **전역 노트(GlobalNote)** 방식이다. 사용자 단위 선호·페르소나를 `config.yaml`에 한 덩어리로 두고, 매 컨텍스트 맨 앞에 그대로 붙인다. RAG·요약 없이 "일관된 사용자 기억" 효과를 얻는다.

### 교체 가능한 인터페이스

메모리 전략은 추후 교체될 수 있으므로 단일 추상 인터페이스 뒤에 둔다. 새 전략(요약형, 벡터 검색형 등)은 이 인터페이스만 구현하면 되고, 교체는 `config.yaml`의 `provider` 한 줄로 끝난다.

```python
# memory/base.py - 메모리 전략 추상 인터페이스
class MemoryProvider(ABC):
    @abstractmethod
    async def preamble(self, agent_id: str) -> str:
        """각 AI 컨텍스트 맨 앞에 주입할 기억 텍스트를 반환한다."""

    async def observe(self, turn: ConversationTurn) -> None:
        """새 턴을 기억에 반영한다. 기본은 no-op이며 학습형 메모리만 override한다."""
        return None
```

```python
# memory/global_note.py - config.yaml의 전역 사용자 노트를 그대로 주입하는 v1 메모리
class GlobalNoteMemory(MemoryProvider):
    def __init__(self, note: str):
        self._note = note

    async def preamble(self, agent_id: str) -> str:
        return self._note
```

### 설정

```yaml
# config.yaml
memory:
  provider: global_note      # 교체 지점. 다른 전략 추가 시 이 값만 변경
  global_note: |
    사용자는 한국어로 간결한 답변을 선호한다.
    불필요한 설명을 줄이고 핵심만 전달한다.
```

```python
# memory/__init__.py - provider 이름으로 구현체를 선택하는 팩토리
def build_memory(cfg: dict) -> MemoryProvider:
    provider = cfg["memory"]["provider"]
    if provider == "global_note":
        return GlobalNoteMemory(cfg["memory"]["global_note"])
    raise ValueError(f"unknown memory provider: {provider}")
```

### 주입 위치

메시지 전송 시 최종 컨텍스트 조립 순서는 다음과 같다.

```
[memory.preamble] + [role_prompt] + [context_format(history)] + [user message]
```

---

## WebSocket API

### 클라이언트 → 서버

```json
// 메시지 전송
{ "type": "send", "target": ["claude", "gemini"], "text": "..." }

// 응답 전달
{ "type": "forward", "target": "gemini", "source_turn_id": "uuid" }

// 설정 저장
{ "type": "update_config", "agent": "claude", "role_prompt": "..." }

// 로그인 요청
{ "type": "login", "agent": "claude" }

// 세션 상태 확인
{ "type": "status" }
```

### 서버 → 클라이언트

```json
// 응답 청크 (스트리밍 시뮬레이션)
{ "type": "chunk", "agent": "claude", "turn_id": "uuid", "text": "..." }

// 응답 완료
{ "type": "done", "agent": "claude", "turn_id": "uuid" }

// 에러
{ "type": "error", "agent": "claude", "message": "..." }

// 로그인 필요
{ "type": "login_required", "agent": "claude", "url": "..." }

// 세션 상태
{ "type": "status", "agents": { "claude": "ready", "gemini": "offline" } }
```

---

## 프론트엔드 UI 설계

### 레이아웃

```
┌─────────────────────────────────────────────────────┐
│  PolyChat              [설정] [세션관리] [이력]       │  ← 헤더
├──────────────┬──────────────────────────────────────┤
│              │                                      │
│  대화 이력   │  👤 유저                              │
│              │  안녕하세요. 의식이란 무엇인가요?      │
│  [오늘]      │                                      │
│  ▸ 의식이란  │  🟠 Claude                           │
│  ▸ 양자역학  │  의식은 정보 처리의 주관적 경험...    │
│              │  [Gemini에 전달 →] [편집 후 전달] [↩] │
│              │                                      │
│              │  🔵 Gemini                           │
│              │  흥미롭네요. 저는 통합 정보 이론...   │
│              │  [Claude에 전달 →] [편집 후 전달] [↩] │
│              │                                      │
│              │──────────────────────────────────────│
│              │  [Claude ✓] [Gemini ✓] [Grok] [PPX]  │
│              │  ┌──────────────────────────────┐   │
│              │  │ 메시지 입력...               │   │
│              │  └──────────────────────────────┘   │
│              │                          [전송]      │
└──────────────┴──────────────────────────────────────┘
```

### 모바일 레이아웃

모바일에서는 사이드바가 숨겨지고 하단 탭으로 전환된다.

```
┌───────────────────────┐
│ PolyChat    [≡] [⚙️]  │
├───────────────────────┤
│                       │
│  🟠 Claude            │
│  의식은 정보 처리의   │
│  주관적 경험...       │
│                       │
│  [→ Gemini] [편집] [↩]│
│                       │
│  🔵 Gemini            │
│  통합 정보 이론에서.. │
│                       │
├───────────────────────┤
│ [C✓][G✓][Gk][Ppx]    │
│ ┌─────────────────┐  │
│ │ 입력...         │  │
│ └─────────────────┘  │
│                [전송] │
└───────────────────────┘
```

### 설정 모달

```
┌─────────────────────────────┐
│  에이전트 설정               │
├─────────────────────────────┤
│  [Claude] [Gemini] [Grok] [+추가] │
├─────────────────────────────┤
│  표시 이름: Claude           │
│  색상: 🟠 #D97706           │
│                             │
│  역할 프롬프트:              │
│  ┌─────────────────────┐   │
│  │ 너는 논리적이고...   │   │
│  │                     │   │
│  └─────────────────────┘   │
│                             │
│  컨텍스트 포함 방식:         │
│  ○ 전체 대화 포함           │
│  ○ 마지막 N턴만 포함        │
│  ○ 요약 후 포함             │
│                             │
│  [세션 로그인] [세션 초기화] │
│                    [저장]   │
└─────────────────────────────┘
```

---

## 초기 설정 흐름 (최초 1회)

```
1. 서버 실행: python main.py
2. 브라우저에서 localhost:7777 접속
3. 설정 → 세션 관리 → [Claude 로그인]
   → 서버가 Playwright 브라우저 창을 열고 claude.ai로 이동
   → 사용자가 직접 로그인
   → 완료 버튼 클릭 → 세션 저장
4. 동일하게 Gemini, Grok 등 순서대로 설정
5. 이후 서버 재시작 시 자동 로그인 유지
```

---

## 기술 스택 요약

| 항목 | 선택 | 이유 |
|------|------|------|
| 서버 | FastAPI + uvicorn | 비동기 WebSocket 지원 |
| 브라우저 자동화 | Playwright (async) | 멀티 컨텍스트, 세션 저장 |
| 프론트엔드 | 바닐라 JS + CSS | 의존성 없음, 단일 파일 |
| DB | SQLite (aiosqlite) | 설치 불필요, 로컬 저장 |
| 설정 | YAML | 사람이 읽기 쉬움 |

---

## 구현 단계 (Phase)

| Phase | 내용 | 예상 복잡도 |
|-------|------|-------------|
| 1 | FastAPI 서버 + WebSocket 기본 구조 | 낮음 |
| 2 | Claude 스크래퍼 구현 + 세션 관리 | 중간 |
| 3 | 프론트엔드 기본 UI | 중간 |
| 4 | Gemini 스크래퍼 추가 | 낮음 |
| 5 | 역할 설정 + 컨텍스트 제어 | 낮음 |
| 6 | Grok / Perplexity 추가 | 낮음 |
| 7 | 모바일 반응형 최적화 | 낮음 |

---

## 알려진 제약사항

1. **Claude.ai Cloudflare**: 자동화 감지 시 캡챠 발생 가능. 최초 로그인은 사용자가 직접 해야 함.
2. **세션 만료**: 각 서비스의 세션은 일정 기간 후 만료됨. 재로그인 필요.
3. **UI 변경**: 각 서비스가 UI를 바꾸면 셀렉터가 깨짐. 유지보수 필요.
4. **속도**: 각 AI 응답 시간만큼 대기 (30~90초/턴).
5. **동시 접속**: 1명 사용 기준 설계. 멀티유저는 세션 충돌 가능.
6. **모바일 접속**: 서버와 같은 네트워크여야 함 (또는 ngrok 등 터널링).
