# perplexity.ai 웹 UI 스크래퍼. 동작은 base.AIScraper 공통 구현을 쓰고 식별 정보만 정의한다.
from .base import AIScraper


class PerplexityScraper(AIScraper):
    service_id = "perplexity"
    display_name = "Perplexity"
    url = "https://perplexity.ai"
