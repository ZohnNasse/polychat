# chatgpt.com 웹 UI 스크래퍼. 동작은 base.AIScraper 공통 구현을 쓰고 식별 정보만 정의한다.
from .base import AIScraper


class ChatGPTScraper(AIScraper):
    service_id = "chatgpt"
    display_name = "ChatGPT"
    url = "https://chatgpt.com"
