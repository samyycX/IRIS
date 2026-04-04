from __future__ import annotations

from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_", "spm", "fbclid", "gclid")
REDIRECT_QUERY_KEYS = ("url", "target", "dest", "destination", "redirect", "redirect_url", "redir", "to", "link")


class URLCanonicalizer:
    def canonicalize(self, url: str, base_url: str | None = None) -> str:
        decoded = self._decode_url(url)
        absolute = urljoin(base_url, decoded) if base_url else decoded
        absolute = self._unwrap_redirect_url(absolute)
        parts = urlsplit(absolute)
        scheme = parts.scheme.lower() or "https"
        netloc = parts.netloc.lower()
        path = self._normalize_path(parts.path or "/")
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        filtered_query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
        ]
        query = urlencode(filtered_query, doseq=True)
        return urlunsplit((scheme, netloc, path, query, ""))

    def _normalize_path(self, path: str) -> str:
        decoded_path = self._decode_url(path or "/")
        return quote(decoded_path, safe="/%:@!$&'()*+,;=-._~") or "/"

    def _decode_url(self, url: str) -> str:
        decoded = url.strip()
        for _ in range(3):
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        return decoded

    def _unwrap_redirect_url(self, url: str) -> str:
        parts = urlsplit(url)
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() not in REDIRECT_QUERY_KEYS:
                continue
            candidate = self._decode_url(value)
            if candidate.startswith(("http://", "https://")):
                return candidate
        return url
