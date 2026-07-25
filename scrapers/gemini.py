# gemini.google.com 웹 UI 스크래퍼. Enter 전송이 불안정해 전송 버튼 클릭 방식으로 오버라이드한다.
from .base import AIScraper


class GeminiScraper(AIScraper):
    service_id = "gemini"
    display_name = "Gemini"
    url = "https://gemini.google.com/app"

    async def _submit(self, text: str):
        """텍스트를 입력한 후 전송 버튼을 클릭한다. Enter 키만 누르면 Gemini UI가 듣지 않는 경우가 있다."""
        box = self.page.locator(self.selectors["input"]).last
        await box.click()
        await self.page.keyboard.insert_text(text)
        try:
            # 버튼 활성화까지 자동 대기 후 클릭. 입력만 되고 전송이 안 되던 문제의 실제 수정.
            await self.page.locator(self.selectors["send_button"]).last.click(timeout=5000)
        except Exception:
            await self.page.keyboard.press("Enter")  # 버튼 못 찾으면 Enter 폴백
