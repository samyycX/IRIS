from app.services.crawl.canonicalizer import URLCanonicalizer
from app.services.crawl.discovery import LinkDiscoveryService


def test_discovery_filters_external_domains_and_deduplicates():
    service = LinkDiscoveryService(URLCanonicalizer(), {"wiki.example.com"})
    html = """
    <html><body>
      <a href="/character/role-alpha?utm_source=home">Role Alpha</a>
      <a href="https://wiki.example.com/character/role-alpha#story">Role Alpha Duplicate</a>
      <a href="https://other.example.com/page">Other</a>
    </body></html>
    """

    result = service.discover(html, "https://wiki.example.com/index")

    assert result == ["https://wiki.example.com/character/role-alpha"]
