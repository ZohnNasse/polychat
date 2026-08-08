# Playwright 브라우저 생명주기와 에이전트별 세션을 관리한다. cdp / persistent 두 모드를 지원한다.
import asyncio
import subprocess
import time
from collections import defaultdict
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

# cdp 자동 실행 시 찾아볼 Chrome 실행 파일 후보(설정에 chrome_path가 없을 때).
_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]

from . import SCRAPERS

# persistent 모드에서 자동화 탐지(Cloudflare 등)를 줄이기 위한 설정.
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
_STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


class BrowserManager:
    def __init__(self, agents: dict, profiles_dir, mode: str = "cdp",
                 cdp_url: str = "http://localhost:9222",
                 headless: bool = False, channel: str = "chrome",
                 auto_launch: bool = True, chrome_path: str = "",
                 global_note: str = ""):
        self.agents = agents              # config.yaml의 agents 딕셔너리 (셀렉터 포함)
        self.global_note = global_note    # 모든 새 대화의 priming 앞에 붙는 전역메모(설정에서 편집)
        self.profiles_dir = Path(profiles_dir)
        self.mode = mode                  # "cdp"=실행 중인 Chrome에 접속, "persistent"=영구 프로필 직접 기동
        self.cdp_url = cdp_url
        self.headless = headless
        self.channel = channel or None
        self.auto_launch = auto_launch    # cdp: 엔드포인트가 없으면 전용 프로필로 Chrome을 직접 띄운다
        self.chrome_path = chrome_path or None
        self._pw = None
        self._browser = None              # cdp: 접속한 사용자 Chrome
        self._context = None              # cdp: 탭들을 담는 공유 컨텍스트
        self._chrome_proc = None          # cdp: 우리가 직접 띄운 Chrome 프로세스(있으면)
        self._scrapers = {}               # agent_id -> AIScraper
        # 에이전트별 전송 락. 한 모델이 멈춰도 다른 모델은 막히지 않게 모델마다 따로 둔다.
        self._send_locks = defaultdict(asyncio.Lock)
        self._init_lock = asyncio.Lock()  # 스크래퍼·컨텍스트 최초 생성만 직렬화(공유 상태 레이스 방지)

    async def start(self):
        # cdp 접속은 Chrome이 아직 안 떠 있을 수 있으므로 첫 사용 시점까지 지연한다.
        self._pw = await async_playwright().start()

    async def stop(self):
        # 우리가 연 탭만 닫는다. cdp 모드에서 사용자의 Chrome 자체는 절대 닫지 않는다.
        for scraper in self._scrapers.values():
            try:
                await scraper.page.close()
            except Exception:
                pass
        if self.mode != "cdp":
            for scraper in self._scrapers.values():
                try:
                    await scraper._context.close()
                except Exception:
                    pass
        if self._pw:
            await self._pw.stop()

    def _cdp_alive(self) -> bool:
        # CDP 디버그 엔드포인트가 응답하는지 확인한다.
        try:
            with urllib.request.urlopen(self.cdp_url.rstrip("/") + "/json/version", timeout=1):
                return True
        except Exception:
            return False

    def _chrome_binary(self):
        if self.chrome_path:
            return self.chrome_path
        for c in _CHROME_CANDIDATES:
            if Path(c).exists():
                return c
        return None

    def _launch_chrome(self):
        # 전용 프로필(profiles/cdp)로 디버그 포트를 켜서 깔끔한 단일 창을 띄운다.
        # 평소 쓰는 Chrome과 프로필이 분리되어 동시 사용·세션 복원 문제가 없다. AI 로그인은 최초 1회만.
        binary = self._chrome_binary()
        if not binary:
            raise RuntimeError("Chrome 실행 파일을 못 찾음. config server.chrome_path를 지정해줘.")
        profile = self.profiles_dir / "cdp"
        profile.mkdir(parents=True, exist_ok=True)
        port = urlparse(self.cdp_url).port or 9222
        self._chrome_proc = subprocess.Popen(
            [binary, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check", "--restore-last-session"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(40):  # 엔드포인트가 뜰 때까지 최대 10초 대기
            if self._cdp_alive():
                return
            time.sleep(0.25)
        raise RuntimeError(
            "Chrome을 띄웠지만 CDP 엔드포인트가 안 열림. 9222를 다른 앱이 쓰고 있는지 확인해줘."
        )

    async def _ensure_cdp_context(self):
        if self._context is not None:
            return self._context
        if self.auto_launch and not self._cdp_alive():
            self._launch_chrome()
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            raise RuntimeError(
                f"Chrome에 접속 실패({self.cdp_url}). "
                f"전용 프로필 Chrome 자동 실행도 실패했어. 원인: {e}"
            )
        self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        await self._context.add_init_script(_STEALTH_JS)
        # restore-last-session이 지난 탭을 되살려 매 실행마다 탭이 누적된다. 쿠키는 이미 복원됐으니
        # 탭 하나만 남기고 정리한 뒤, 각 에이전트가 자기 탭을 새로 연다.
        pages = self._context.pages
        for p in pages[1:]:
            try:
                await p.close()
            except Exception:
                pass
        return self._context

    async def _ensure_scraper(self, agent_id: str):
        # 캐시된 스크래퍼의 탭이 살아있으면 재사용. 사용자가 탭을 닫았으면 버리고 새로 만든다.
        cached = self._scrapers.get(agent_id)
        if cached and not cached.page.is_closed():
            return cached
        saved_conv = cached.conversation_url if cached else None  # 탭이 닫혀도 대화는 이어간다
        saved_setup = cached.setup_prompt if cached else None     # 복구로 대화가 새로 열리면 priming 재주입용
        self._scrapers.pop(agent_id, None)
        if agent_id not in SCRAPERS:
            raise ValueError(f"no scraper for agent: {agent_id}")
        agent_cfg = self.agents.get(agent_id, {})
        selectors = agent_cfg.get("selectors", {})
        setup_prompt = agent_cfg.get("role_prompt", "")  # 첫 대화에 1회 주입할 모델별 설정
        cfg_url = agent_cfg.get("url")                    # config의 url(예: ChatGPT 임시채팅)을 스크래퍼 기본 URL보다 우선

        if self.mode == "cdp":
            context = await self._ensure_cdp_context()
            page = await context.new_page()       # 공유 Chrome 안의 새 탭
            scraper = SCRAPERS[agent_id](page, selectors, setup_prompt)
            scraper._context = context
        else:
            profile = self.profiles_dir / agent_id
            profile.mkdir(parents=True, exist_ok=True)
            context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile), headless=self.headless,
                channel=self.channel, args=_STEALTH_ARGS,
            )
            await context.add_init_script(_STEALTH_JS)
            page = context.pages[0] if context.pages else await context.new_page()
            scraper = SCRAPERS[agent_id](page, selectors, setup_prompt)
            scraper._context = context

        if cfg_url:
            scraper.url = cfg_url
        if saved_conv:
            scraper.conversation_url = saved_conv  # 재생성 시 원래 대화로 복귀
        if saved_setup:
            scraper.setup_prompt = saved_setup     # 대화가 새로 열리면 이 priming을 재주입
        self._scrapers[agent_id] = scraper
        return scraper

    async def status(self, agent_id: str) -> str:
        try:
            scraper = await self._ensure_scraper(agent_id)
            return "ready" if await scraper.is_logged_in() else "offline"
        except Exception as e:
            print(f"[status:{agent_id}] offline 원인: {e}")
            return "offline"

    async def login(self, agent_id: str):
        """해당 에이전트 탭을 서비스 URL로 이동시킨다. cdp 모드에서는 사용자가 그 Chrome에 이미 로그인돼 있어야 한다."""
        scraper = await self._ensure_scraper(agent_id)
        await scraper.page.goto(scraper.url, wait_until="domcontentloaded")

    async def save_session(self, agent_id: str):
        """cdp 모드는 사용자 프로필이 세션을 보존하므로 별도 저장이 없다. 컨텍스트 존재만 보장한다."""
        await self._ensure_scraper(agent_id)

    async def reset(self):
        # 모든 스크래퍼의 대화 컨텍스트를 초기화한다. 다음 전송은 새 대화로 시작(교차 실행 오염 방지).
        for s in self._scrapers.values():
            s.conversation_url = None

    async def send(self, agent_id: str, text: str, on_update=None, setup_prompt=None) -> str:
        async with self._init_lock:                       # 생성 단계만 직렬화
            scraper = await self._ensure_scraper(agent_id)
            # priming(설정 프롬프트)은 새 대화가 열릴 때만 1회 주입된다(복구로 새로 열려도 재주입).
            # setup_prompt(릴레이 첫 턴의 페르소나·프리앰블)가 오면 전역메모와 묶어 갱신하고,
            # 없으면 priming이 아직 비어 있을 때에 한해 전역메모만이라도 넣는다.
            if setup_prompt and setup_prompt.strip():
                parts = [p for p in (self.global_note, setup_prompt) if p and p.strip()]
                scraper.setup_prompt = "\n\n".join(parts)
            elif not scraper.setup_prompt.strip() and self.global_note.strip():
                scraper.setup_prompt = self.global_note
        async with self._send_locks[agent_id]:            # 전송은 모델별 독립 → 한 모델 정지가 전체를 막지 않음
            return await scraper.send_message(text, on_update=on_update)
