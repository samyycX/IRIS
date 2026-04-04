import pytest

from app.models import CrawlPageResult
from app.services.crawl.canonicalizer import URLCanonicalizer
from app.services.tools.builtins import FetchUrlTool


class FakeFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def fetch(self, url: str, referer: str | None = None) -> tuple[str, int, str, str]:
        self.calls.append((url, referer))
        return (
            "https://wiki.example.com/character/role-alpha",
            200,
            "<html><head><title>角色甲</title></head><body>正文</body></html>",
            "browser",
        )


class FakeExtractor:
    def __init__(self) -> None:
        self.last_kwargs: dict | None = None

    def extract(self, **kwargs) -> CrawlPageResult:
        self.last_kwargs = kwargs
        return CrawlPageResult(
            url=kwargs["url"],
            canonical_url=kwargs["canonical_url"],
            title="角色甲",
            status_code=kwargs["status_code"],
            fetch_mode=kwargs["fetch_mode"],
            html=kwargs["html"],
            text="正文",
            links=kwargs["links"],
            content_hash="hash",
        )


class FakeDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def discover(self, html: str, base_url: str) -> list[str]:
        self.calls.append((html, base_url))
        return [f"{base_url}/story"]


@pytest.mark.asyncio
async def test_fetch_url_tool_passes_referer_and_fetch_mode():
    fetcher = FakeFetcher()
    extractor = FakeExtractor()
    discovery = FakeDiscovery()
    tool = FetchUrlTool(fetcher, extractor, discovery, URLCanonicalizer())

    result = await tool.execute(
        url="https://wiki.example.com/character/role-alpha",
        referer="https://wiki.example.com/index",
    )

    assert fetcher.calls == [
        ("https://wiki.example.com/character/role-alpha", "https://wiki.example.com/index")
    ]
    assert extractor.last_kwargs is not None
    assert extractor.last_kwargs["fetch_mode"] == "browser"
    assert extractor.last_kwargs["canonical_url"] == "https://wiki.example.com/character/role-alpha"
    assert result["fetch_mode"] == "browser"
    assert result["links"] == ["https://wiki.example.com/character/role-alpha/story"]
    assert discovery.calls == [
        (
            "<html><head><title>角色甲</title></head><body>正文</body></html>",
            "https://wiki.example.com/character/role-alpha",
        )
    ]
