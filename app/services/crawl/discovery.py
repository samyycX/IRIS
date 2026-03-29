from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.crawl.canonicalizer import URLCanonicalizer


class LinkDiscoveryService:
    def __init__(self, canonicalizer: URLCanonicalizer, allowed_domains: set[str]) -> None:
        self._canonicalizer = canonicalizer
        self._allowed_domains = allowed_domains

    def discover(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        discovered: list[str] = []
        seen: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            canonical = self._canonicalizer.canonicalize(href, base_url=base_url)
            if not canonical.startswith(("http://", "https://")):
                continue
            host = canonical.split("/")[2].lower()
            if self._allowed_domains and host not in self._allowed_domains:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            discovered.append(canonical)
        return discovered
