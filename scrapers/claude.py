# claude.ai 웹 UI 스크래퍼. 전송·완료감지·대화재사용은 base.AIScraper 공통 구현을 그대로 쓰고 식별 정보만 정의한다.
from .base import AIScraper


class ClaudeScraper(AIScraper):
    service_id = "claude"
    display_name = "Claude"
    url = "https://claude.ai/new"
