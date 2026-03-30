from __future__ import annotations

import re

_CHINESE_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_PINYIN_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


def expand_aliases_with_pinyin(values: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            continue
        _append_unique(expanded, seen, cleaned)
        pinyin_alias = to_pinyin_alias(cleaned)
        if pinyin_alias:
            _append_unique(expanded, seen, pinyin_alias)
    return expanded


def to_pinyin_alias(value: str) -> str | None:
    cleaned = " ".join(value.split()).strip()
    if not cleaned or not _CHINESE_CHAR_PATTERN.search(cleaned):
        return None
    from pypinyin import lazy_pinyin

    transliterated = "".join(lazy_pinyin(cleaned, errors="ignore")).casefold()
    normalized = _PINYIN_SANITIZE_PATTERN.sub("", transliterated)
    if not normalized or normalized == cleaned.casefold():
        return None
    return normalized


def _append_unique(values: list[str], seen: set[str], value: str) -> None:
    key = value.casefold()
    if key in seen:
        return
    seen.add(key)
    values.append(value)
