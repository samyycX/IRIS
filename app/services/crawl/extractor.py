from __future__ import annotations

import hashlib
from copy import deepcopy

import trafilatura
from bs4 import BeautifulSoup

from app.models import CrawlPageResult


class ContentExtractor:
    def extract(
        self,
        *,
        url: str,
        canonical_url: str,
        status_code: int,
        fetch_mode: str = "http",
        html: str,
        links: list[str],
    ) -> CrawlPageResult:
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_title(soup)
        text = self._extract_text(soup)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return CrawlPageResult(
            url=url,
            canonical_url=canonical_url,
            title=title,
            status_code=status_code,
            fetch_mode=fetch_mode,
            html=html,
            text=text,
            links=links,
            content_hash=content_hash,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        title_node = soup.select_one("#firstHeading .mw-page-title-main") or soup.select_one("#firstHeading")
        if title_node:
            title = title_node.get_text(" ", strip=True)
            if title:
                return title
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return None

    def _extract_text(self, soup: BeautifulSoup) -> str:
        best_scoped_text = ""
        for root in self._iter_content_candidates(soup, fallback=False):
            text = self._extract_text_from_root(root)
            if len(text) >= EARLY_RETURN_TEXT_LENGTH:
                return text
            if len(text) > len(best_scoped_text):
                best_scoped_text = text
        if best_scoped_text:
            return best_scoped_text

        for root in self._iter_content_candidates(soup, fallback=True):
            text = self._extract_text_from_root(root)
            if text:
                return text
        return ""

    def _iter_content_candidates(self, soup: BeautifulSoup, *, fallback: bool) -> list:
        selectors = ["#mw-content-text", ".mw-parser-output", "article", "main"]
        if fallback:
            selectors = ["body"]

        candidates: list = []
        seen: set[int] = set()
        for selector in selectors:
            node = soup.select_one(selector)
            if node is None:
                continue
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)
            candidates.append(node)

        if fallback:
            soup_id = id(soup)
            if soup_id not in seen:
                candidates.append(soup)
        return candidates

    def _extract_text_from_root(self, root) -> str:
        content_root = deepcopy(root)
        self._remove_noise(content_root)
        content_html = str(content_root)
        text = trafilatura.extract(content_html, include_links=False, include_formatting=False) or ""
        if not text:
            text = content_root.get_text("\n", strip=True)
        return self._normalize_text(text)

    def _remove_noise(self, root) -> None:
        for selector in [
            "script",
            "style",
            "noscript",
            "iframe",
            "svg",
            "nav",
            "footer",
            "form",
            "fandom-ad",
            ".global-top-navigation",
            ".global-explore-navigation",
            ".page-side-tools__wrapper",
            ".page-footer",
            ".global-footer",
            ".right-rail-wrapper",
            ".WikiaRail",
            ".top-ads-container",
            ".bottom-ads-container",
            ".notifications-placeholder",
            ".banner-notifications-placeholder",
            ".wds-dropdown",
            ".mw-editsection",
            ".reference",
            ".reflist",
        ]:
            for node in root.select(selector):
                node.decompose()

    def _normalize_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        filtered: list[str] = []
        previous = None
        for line in lines:
            if not line:
                continue
            if line == previous:
                continue
            filtered.append(line)
            previous = line
        return "\n".join(filtered)


EARLY_RETURN_TEXT_LENGTH = 200
