# 스크래퍼 패키지. service_id로 스크래퍼 클래스를 찾는 레지스트리를 제공한다.
from .base import AIScraper
from .claude import ClaudeScraper
from .chatgpt import ChatGPTScraper
from .gemini import GeminiScraper
from .grok import GrokScraper
from .perplexity import PerplexityScraper

SCRAPERS = {
    s.service_id: s
    for s in (ClaudeScraper, ChatGPTScraper, GeminiScraper, GrokScraper, PerplexityScraper)
}
