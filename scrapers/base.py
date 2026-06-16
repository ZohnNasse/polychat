# 각 AI 서비스 스크래퍼의 공통 인터페이스. 전송·완료감지·대화재사용 로직을 셀렉터 기반으로 공통 구현한다.
import asyncio
from abc import ABC


class AIScraper(ABC):
    # 모델별 스크래퍼는 아래 3개 식별 정보만 정의하면 된다. 동작이 다른 서비스는 필요한 메서드만 오버라이드한다.
    service_id: str = ""
    display_name: str = ""
    url: str = ""  # 새 대화 시작 URL. 첫 전송 후 대화 전용 URL로 바뀌면 그 URL을 재사용한다.

    def __init__(self, page, selectors: dict, setup_prompt: str = ""):
        self.page = page
        self.selectors = selectors  # {"input","response","streaming"?} — config.yaml에서 주입
        self.setup_prompt = setup_prompt  # 첫 진입 시 1회 주입할 설정 프롬프트(없으면 빈 문자열)
        self.conversation_url = None      # 첫 대화 생성 후 받은 URL. 이후 모든 턴이 이 대화를 재사용한다.

    async def is_logged_in(self) -> bool:
        # 입력창이 보이면 로그인된 것으로 본다. 미로그인 시 로그인 페이지로 리다이렉트되어 입력창이 없다.
        try:
            if self.url not in self.page.url:
                await self.page.goto(self.url, wait_until="domcontentloaded")
            await self.page.wait_for_selector(self.selectors["input"], timeout=8000)
            return True
        except Exception as e:
            print(f"[{self.service_id}.is_logged_in] 입력창 못 찾음. url={self.page.url} | {e}")
            return False

    async def _last_response_text(self) -> str:
        loc = self.page.locator(self.selectors["response"])
        n = await loc.count()
        return await loc.nth(n - 1).inner_text() if n else ""

    async def _submit(self, text: str):
        # 입력창에 텍스트를 넣고 전송한다. insert_text는 줄바꿈을 Enter(전송)로 오해하지 않는다.
        box = self.page.locator(self.selectors["input"]).last
        await box.click()
        await self.page.keyboard.insert_text(text)
        await self.page.keyboard.press("Enter")

    async def _wait_done(self) -> str:
        # 응답 완료 감지. streaming 셀렉터가 사라지는 순간을 완료로 본다(텍스트 안정화보다 정확·신속).
        page = self.page
        sel = self.selectors.get("streaming")
        if not sel:
            return await self._wait_until_stable(self._last_response_text)
        try:
            await page.wait_for_selector(sel, timeout=10000)                    # 응답 시작(스트리밍 등장) 대기
        except Exception:
            pass
        try:
            await page.wait_for_selector(sel, state="detached", timeout=120000)  # 스트리밍 종료=완료 대기
        except Exception:
            pass
        return await self._last_response_text()

    def _is_fresh(self) -> bool:
        # 아직 대화가 생성되지 않은(새 대화) 상태인지. 현재 URL이 새 대화 URL과 같으면 fresh.
        return self.page.url.rstrip("/") == self.url.rstrip("/")

    async def _ensure_conversation(self):
        # 대화를 1회만 생성하고 이후 턴은 그 대화(conversation_url)를 재사용한다.
        page = self.page
        if self.conversation_url:
            if self.conversation_url not in page.url:
                await page.goto(self.conversation_url, wait_until="domcontentloaded")
                await page.wait_for_selector(self.selectors["input"], timeout=8000)
            return

        # 첫 진입. 새 대화를 연다.
        await page.goto(self.url, wait_until="domcontentloaded")
        await page.wait_for_selector(self.selectors["input"], timeout=8000)

        # 설정 프롬프트가 있으면 1회 주입한다. 이 전송이 대화를 생성하므로 URL을 캡처한다.
        if self.setup_prompt.strip():
            await self._submit(self.setup_prompt)
            await self._wait_done()
            if not self._is_fresh():
                self.conversation_url = page.url

    async def send_message(self, text: str) -> str:
        await self._ensure_conversation()
        await self._submit(text)
        reply = await self._wait_done()

        # 설정 프롬프트가 없어 아직 대화 URL을 못 잡았다면, 첫 메시지 전송 후 여기서 캡처한다.
        if not self.conversation_url and not self._is_fresh():
            self.conversation_url = self.page.url

        return reply

    async def _wait_until_stable(self, get_text, interval=0.5, stable_rounds=3, timeout=120.0) -> str:
        """get_text()로 응답을 주기적으로 샘플링해 연속 stable_rounds회 동일하면 완료로 판정한다.

        streaming 셀렉터가 없는 서비스용 폴백. 변화가 멈춘 시점을 완료로 본다.
        timeout 초과 시 마지막으로 본 텍스트를 반환한다.
        """
        elapsed = 0.0
        last = ""
        same = 0
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            cur = (await get_text()) or ""
            if cur and cur == last:
                same += 1
                if same >= stable_rounds:
                    return cur
            else:
                same = 0
                last = cur
        return last
