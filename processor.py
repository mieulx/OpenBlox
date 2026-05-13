from typing import List
from website_manager import WebsiteManager
from extractor import ContentExtractor, ContentChunk


class DevProcessor:
    def __init__(self, wm: WebsiteManager, extractor: ContentExtractor):
        self.wm = wm
        self.extractor = extractor
        self._cache: List[ContentChunk] = []
        self._cache_urls: set = set()

    def fetch_for_query(self, query: str) -> List[ContentChunk]:
        websites = self.wm.get_enabled_websites()
        current = {w.url for w in websites}
        if self._cache_urls != current or not self._cache:
            self._cache = []
            for w in websites:
                self._cache.extend(self.extractor.extract(w.url, w.extractor_type))
            self._cache_urls = current
        return self.extractor.search_relevant(
            query, self._cache, self.wm.search_config["max_chunks"])

    def format_raw(self, chunks: List[ContentChunk]) -> str:
        lines = []
        for c in chunks[:5]:
            lines.append(f"--- {c.heading_path or c.source_url} ---")
            lines.append(c.text[:600])
            lines.append("")
        return "\n".join(lines)

    def build_context(self, chunks: List[ContentChunk]) -> str:
        return "\n\n".join(
            f"[{c.heading_path or c.source_url}]\n{c.text}" for c in chunks)
