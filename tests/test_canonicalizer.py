from app.services.crawl.canonicalizer import URLCanonicalizer


def test_canonicalize_removes_tracking_params_and_fragment():
    canonicalizer = URLCanonicalizer()

    result = canonicalizer.canonicalize(
        "https://wiki.example.com/path/?utm_source=test&id=1#section"
    )

    assert result == "https://wiki.example.com/path?id=1"


def test_canonicalize_decodes_embedded_redirect_url():
    canonicalizer = URLCanonicalizer()

    result = canonicalizer.canonicalize(
        "https://wiki.example.com/redirect?target=https%3A%2F%2Fwiki.example.com%2Fcharacter%2F%E8%A7%92%E8%89%B2%E7%94%B2%3Futm_source%3Dhome"
    )

    assert result == "https://wiki.example.com/character/角色甲"
