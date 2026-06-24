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

    async def _response_count(self) -> int:
        return await self.page.locator(self.selectors["response"]).count()

    async def _submit(self, text: str):
        # 입력창에 텍스트를 넣고 전송한다. insert_text는 줄바꿈을 Enter(전송)로 오해하지 않는다.
        box = self.page.locator(self.selectors["input"]).last
        await box.click()
        await self.page.keyboard.insert_text(text)
        await self.page.keyboard.press("Enter")

    async def _collect_response(self, on_update=None, baseline: int = 0) -> str:
        # 응답을 폴링하며 누적 텍스트를 on_update로 점진 전송한다(실시간 스트리밍).
        # baseline = 전송 직전 응답 블록 수. 그보다 늘어난(=새로 생성된) 응답만 읽어 직전 대화의 옛 텍스트 오염을 막는다.
        # 완료 판정: streaming 셀렉터가 있으면 그것이 사라질 때, 없으면 텍스트가 3회 연속 동일할 때.
        page = self.page
        sel = self.selectors.get("streaming")
        print(f"[{self.service_id}] collect 시작 sel={'Y' if sel else 'N'} baseline={baseline} url={page.url}")
        streamed = False
        if sel:
            try:
                await page.wait_for_selector(sel, timeout=10000)  # 응답 시작(스트리밍 등장) 대기
                streamed = True  # 새 응답 시작 확인. 이후 마지막 블록이 곧 새 응답이다.
            except Exception:
                pass
        loc = page.locator(self.selectors["response"])
        last = ""
        same = 0
        elapsed = 0.0
        interval = 0.4
        timeout = 120.0
        while elapsed < timeout:
            n = await loc.count()
            # 보통은 응답 블록 수가 baseline보다 늘면 새 응답. 단 Claude 등은 옛 블록을 DOM에서 덜어내
            # 개수가 안 늘 수 있어, 스트리밍이 떴으면 개수와 무관하게 마지막 블록을 읽는다.
            read_ok = n > baseline or (streamed and n > 0)
            cur = (await loc.nth(n - 1).inner_text()) if read_ok else ""
            cur = cur or ""
            if cur != last:
                last = cur
                same = 0
                if on_update and cur:
                    await on_update(cur)
            elif cur:
                same += 1
            if sel:
                if cur and await page.locator(sel).count() == 0:  # 스트리밍 종료=완료
                    break
            elif same >= 3 and cur:  # streaming 셀렉터 없는 서비스: 새 응답이 멈추면 완료
                break
            await asyncio.sleep(interval)
            elapsed += interval
        print(f"[{self.service_id}] collect 끝 len={len(last)} elapsed={elapsed:.1f}")
        return last

    def _is_fresh(self) -> bool:
        # 아직 대화가 생성되지 않은(새 대화) 상태인지. 현재 URL이 새 대화 URL과 같으면 fresh.
        return self.page.url.rstrip("/") == self.url.rstrip("/")

    async def _ensure_conversation(self):
        # 대화를 1회만 생성하고 이후 턴은 그 대화(conversation_url)를 재사용한다.
        page = self.page
        print(f"[{self.service_id}] ensure_conv 시작 url={page.url} conv_url={self.conversation_url}")
        if self.conversation_url:
            if self.conversation_url not in page.url:
                await page.goto(self.conversation_url, wait_until="domcontentloaded")
                await page.wait_for_selector(self.selectors["input"], timeout=8000)
            return

        # 첫 진입. 새 대화를 연다.
        await page.goto(self.url, wait_until="domcontentloaded")
        await page.wait_for_selector(self.selectors["input"], timeout=8000)
        print(f"[{self.service_id}] 입력창 확인 url={page.url}")

        # 설정 프롬프트가 있으면 1회 주입한다. 이 전송이 대화를 생성하므로 URL을 캡처한다.
        if self.setup_prompt.strip():
            baseline = await self._response_count()
            await self._submit(self.setup_prompt)
            await self._collect_response(baseline=baseline)
            if not self._is_fresh():
                self.conversation_url = page.url

    async def send_message(self, text: str, on_update=None) -> str:
        await self._ensure_conversation()
        baseline = await self._response_count()  # 전송 직전 응답 수. 새 응답만 읽기 위한 기준선.
        await self._submit(text)
        reply = await self._collect_response(on_update, baseline=baseline)

        # 설정 프롬프트가 없어 아직 대화 URL을 못 잡았다면, 첫 메시지 전송 후 여기서 캡처한다.
        if not self.conversation_url and not self._is_fresh():
            self.conversation_url = self.page.url

        print(f"[{self.service_id}] conv_url={self.conversation_url} fresh={self._is_fresh()}")
        return reply
