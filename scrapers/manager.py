# Playwright 브라우저 생명주기와 에이전트별 세션을 관리한다. cdp / persistent 두 모드를 지원한다.
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from . import SCRAPERS

# persistent 모드에서 자동화 탐지(Cloudflare 등)를 줄이기 위한 설정.
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
_STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


class BrowserManager:
    def __init__(self, agents: dict, profiles_dir, mode: str = "cdp",
                 cdp_url: str = "http://localhost:9222",
                 headless: bool = False, channel: str = "chrome"):
        self.agents = agents              # config.yaml의 agents 딕셔너리 (셀렉터 포함)
        self.profiles_dir = Path(profiles_dir)
        self.mode = mode                  # "cdp"=실행 중인 Chrome에 접속, "persistent"=영구 프로필 직접 기동
        self.cdp_url = cdp_url
        self.headless = headless
        self.channel = channel or None
        self._pw = None
        self._browser = None              # cdp: 접속한 사용자 Chrome
        self._context = None              # cdp: 탭들을 담는 공유 컨텍스트
        self._scrapers = {}               # agent_id -> AIScraper
        self._lock = asyncio.Lock()       # Playwright 동시 조작 직렬화 (단일 사용자 기준)

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

    async def _ensure_cdp_context(self):
        if self._context is not None:
            return self._context
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            raise RuntimeError(
                f"Chrome에 접속 실패({self.cdp_url}). "
                f"--remote-debugging-port로 Chrome을 먼저 실행했는지 확인. 원인: {e}"
            )
        self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        await self._context.add_init_script(_STEALTH_JS)
        return self._context

    async def _ensure_scraper(self, agent_id: str):
        if agent_id in self._scrapers:
            return self._scrapers[agent_id]
        if agent_id not in SCRAPERS:
            raise ValueError(f"no scraper for agent: {agent_id}")
        agent_cfg = self.agents.get(agent_id, {})
        selectors = agent_cfg.get("selectors", {})
        setup_prompt = agent_cfg.get("role_prompt", "")  # 첫 대화에 1회 주입할 모델별 설정

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

    async def send(self, agent_id: str, text: str, on_update=None) -> str:
        async with self._lock:
            scraper = await self._ensure_scraper(agent_id)
            return await scraper.send_message(text, on_update=on_update)
