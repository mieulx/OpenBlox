import json
import re
import requests
from typing import List, Optional
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup, Tag
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

TIMEOUT = 15


class ContentChunk:
    def __init__(self, text: str, source_url: str, heading_path: str = "",
                 content_type: str = "text"):
        self.text = text
        self.source_url = source_url
        self.heading_path = heading_path
        self.content_type = content_type

    def __repr__(self):
        return f"ContentChunk(url={self.source_url}, heading={self.heading_path[:40]}, len={len(self.text)})"


class ContentExtractor:
    def __init__(self, chunk_size: int = 1500):
        self.chunk_size = chunk_size
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException:
            return None

    def extract(self, url: str, extractor_type: str = "generic_html") -> List[ContentChunk]:
        if not BS4_AVAILABLE:
            return [ContentChunk(
                text="BeautifulSoup4 not installed. Run: pip install beautifulsoup4",
                source_url=url, content_type="error")]

        html = self.fetch(url)
        if html is None:
            return [ContentChunk(
                text=f"Failed to fetch content from {url}",
                source_url=url, content_type="error")]

        soup = BeautifulSoup(html, "lxml")
        extractors = {
            "devforum": self._extract_devforum,
            "api_docs": self._extract_api_docs,
            "wiki": self._extract_wiki,
            "nextjs": self._extract_nextjs,
        }
        chunks = extractors.get(extractor_type, self._extract_generic)(soup, url)
        chunks = self._chunk_content(chunks)
        return chunks if chunks else [
            ContentChunk(text="No relevant content found.", source_url=url, content_type="empty")]

    def _clean_text(self, text: str) -> str:
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:5000]

    def _extract_generic(self, soup, url):
        chunks = []
        for tag in soup.find_all(['article', 'main', 'div', 'section']):
            if tag.name == 'div' and not tag.get('class'):
                continue
            text = self._clean_text(tag.get_text(separator=' ', strip=True))
            if len(text) > 100:
                heading = ""
                for h in reversed(list(tag.parents)):
                    f = h.find(['h1', 'h2', 'h3'])
                    if f:
                        heading = self._clean_text(f.get_text(separator=' ', strip=True))
                        break
                chunks.append(ContentChunk(text=text, source_url=url, heading_path=heading))
        if not chunks:
            body = soup.find('body')
            if body:
                text = self._clean_text(body.get_text(separator=' ', strip=True))
                if text:
                    chunks.append(ContentChunk(text=text, source_url=url))
        return chunks

    def _extract_devforum(self, soup, url):
        chunks = []
        topic = soup.find('div', class_=re.compile(r'post|topic-body|cooked', re.I))
        if topic:
            text = self._clean_text(topic.get_text(separator=' ', strip=True))
            if text:
                chunks.append(ContentChunk(text=text, source_url=url, heading_path="Topic"))
        if not chunks:
            posts = soup.find_all('article', class_=re.compile(r'post', re.I))
            for i, p in enumerate(posts[:10]):
                text = self._clean_text(p.get_text(separator=' ', strip=True))
                if len(text) > 50:
                    chunks.append(ContentChunk(text=text, source_url=url, heading_path=f"Post {i+1}"))
        return chunks or self._extract_generic(soup, url)

    def _extract_api_docs(self, soup, url):
        chunks = []
        area = (soup.find('article') or soup.find('main')
                or soup.find('div', class_=re.compile(r'content|documentation|docs', re.I))
                or soup)
        headings = area.find_all(['h1', 'h2', 'h3', 'h4'])
        if headings:
            for h in headings:
                parts = []
                n = h.find_next_sibling()
                while n and n.name not in ['h1', 'h2', 'h3', 'h4']:
                    if n.name in ['p', 'li', 'pre', 'code', 'div']:
                        parts.append(self._clean_text(n.get_text(separator=' ', strip=True)))
                    n = n.find_next_sibling()
                combined = ' '.join(parts)
                if len(combined) > 30:
                    chunks.append(ContentChunk(
                        text=combined, source_url=url,
                        heading_path=self._clean_text(h.get_text(separator=' ', strip=True))))
        else:
            text = self._clean_text(area.get_text(separator=' ', strip=True))
            if text:
                chunks.append(ContentChunk(text=text, source_url=url))
        return chunks

    def _extract_wiki(self, soup, url):
        chunks = []
        area = (soup.find('div', class_=re.compile(r'mw-parser-output|wiki-content', re.I))
                or soup.find('div', id='content') or soup)
        headings = area.find_all(['h1', 'h2', 'h3'])
        if headings:
            for h in headings:
                parts = [self._clean_text(h.get_text(separator=' ', strip=True))]
                n = h.find_next_sibling()
                while n and n.name not in ['h1', 'h2', 'h3']:
                    if n.name in ['p', 'li', 'pre']:
                        parts.append(self._clean_text(n.get_text(separator=' ', strip=True)))
                    n = n.find_next_sibling()
                combined = ' '.join(parts)
                if len(combined) > 50:
                    chunks.append(ContentChunk(
                        text=combined, source_url=url,
                        heading_path=self._clean_text(h.get_text(separator=' ', strip=True))))
        else:
            text = self._clean_text(area.get_text(separator=' ', strip=True))
            if text:
                chunks.append(ContentChunk(text=text, source_url=url))
        return chunks

    def _extract_nextjs(self, soup, url):
        chunks = []
        script = soup.find('script', id='__NEXT_DATA__')
        if script and script.string:
            try:
                pp = json.loads(script.string).get('props', {}).get('pageProps', {})
                data = pp.get('data', {}) if isinstance(pp.get('data'), dict) else {}

                ar = data.get('apiReference') if isinstance(data, dict) else None
                if isinstance(ar, dict):
                    desc = ar.get('description', '')
                    if isinstance(desc, str) and len(desc) > 20:
                        chunks.append(ContentChunk(text=self._clean_text(desc), source_url=url,
                                                   heading_path="Description"))
                    for section in ('properties', 'methods', 'events', 'callbacks', 'functions', 'enums'):
                        for item in ar.get(section, []) if isinstance(ar.get(section), list) else []:
                            if isinstance(item, dict):
                                nm = item.get('name', '')
                                d = item.get('description', '')
                                if isinstance(d, str) and len(d) > 30:
                                    chunks.append(ContentChunk(
                                        text=self._clean_text(d), source_url=url,
                                        heading_path=f"{section}/{nm}"))

                if isinstance(data, dict):
                    parents = data.get('classReferenceParents')
                    if isinstance(parents, list):
                        for p in parents:
                            if isinstance(p, dict):
                                d = p.get('description', '')
                                if isinstance(d, str) and len(d) > 30:
                                    chunks.append(ContentChunk(
                                        text=self._clean_text(d), source_url=url,
                                        heading_path=f"parent/{p.get('name', '')}"))
                    desc = data.get('description', '')
                    if isinstance(desc, str) and len(desc) > 30:
                        chunks.append(ContentChunk(text=self._clean_text(desc), source_url=url,
                                                   heading_path="Summary"))

                for item in pp.get('translationResources', []) if isinstance(pp.get('translationResources'), list) else []:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            if isinstance(v, str) and len(v) > 100 and not self._is_js(v):
                                chunks.append(ContentChunk(text=self._clean_text(v), source_url=url,
                                                           heading_path=f"resource/{k}"))
            except (json.JSONDecodeError, TypeError):
                pass

        if not chunks:
            body = soup.find('body')
            if body:
                text = self._clean_text(body.get_text(separator=' ', strip=True))
                if text:
                    chunks.append(ContentChunk(text=text, source_url=url))
        return chunks

    def _is_js(self, t: str) -> bool:
        s = t.strip()
        if s.startswith('var ') or s.startswith('let ') or s.startswith('const '):
            return True
        if s.startswith('function') or s.startswith('()=>'):
            return True
        if '=>{' in s[:100]:
            return True
        return False

    def _chunk_content(self, chunks: List[ContentChunk]) -> List[ContentChunk]:
        result = []
        for c in chunks:
            if len(c.text) <= self.chunk_size:
                result.append(c)
            else:
                parts = re.split(r'(?<=[.!?])\s+', c.text)
                buf = ""
                for s in parts:
                    if len(buf) + len(s) < self.chunk_size:
                        buf += s + " "
                    else:
                        if buf.strip():
                            result.append(ContentChunk(text=buf.strip(), source_url=c.source_url,
                                                       heading_path=c.heading_path))
                        buf = s + " "
                if buf.strip():
                    result.append(ContentChunk(text=buf.strip(), source_url=c.source_url,
                                               heading_path=c.heading_path))
        return result

    def search_relevant(self, query: str, chunks: List[ContentChunk],
                        max_chunks: int = 8) -> List[ContentChunk]:
        terms = set(re.findall(r'\w+', query.lower()))
        scored = []
        for c in chunks:
            overlap = len(terms & set(re.findall(r'\w+', c.text.lower())))
            if overlap > 0:
                scored.append((overlap / max(len(terms), 1), c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:max_chunks]] if scored else chunks[:max_chunks]
