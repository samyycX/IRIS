from datetime import datetime, timedelta, timezone
import json

import pytest

from app.repos.url_history import UrlHistoryRepository


class DummyGraphRepo:
    async def source_fetched_since(self, canonical_url: str, cutoff: datetime) -> bool:
        return False


@pytest.mark.asyncio
async def test_url_history_persists_visited_urls_to_file(tmp_path):
    history_file = tmp_path / "visited_urls.json"
    now = datetime(2026, 3, 29, tzinfo=timezone.utc)
    repo = UrlHistoryRepository(
        DummyGraphRepo(),
        history_file=str(history_file),
        now_provider=lambda: now,
    )

    assert await repo.has_seen("https://wiki.example.com/character/role-alpha") is False

    await repo.remember("https://wiki.example.com/character/role-alpha")
    await repo.remember("https://wiki.example.com/character/role-alpha")

    assert await repo.has_seen("https://wiki.example.com/character/role-alpha") is True
    assert json.loads(history_file.read_text(encoding="utf-8")) == {
        "version": 1,
        "entries": {
            "https://wiki.example.com/character/role-alpha": {
                "visited_at": now.isoformat()
            }
        },
    }


@pytest.mark.asyncio
async def test_url_history_reloads_existing_file(tmp_path):
    history_file = tmp_path / "visited_urls.json"
    now = datetime(2026, 3, 29, tzinfo=timezone.utc)
    history_file.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "https://wiki.example.com/weapon/ages-of-harvest": {
                        "visited_at": (now - timedelta(days=2)).isoformat()
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    repo = UrlHistoryRepository(
        DummyGraphRepo(),
        history_file=str(history_file),
        now_provider=lambda: now,
    )

    assert await repo.has_seen("https://wiki.example.com/weapon/ages-of-harvest") is True


@pytest.mark.asyncio
async def test_url_history_ignores_expired_entries(tmp_path):
    history_file = tmp_path / "visited_urls.json"
    now = datetime(2026, 3, 29, tzinfo=timezone.utc)
    history_file.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "https://wiki.example.com/echo/expired": {
                        "visited_at": (now - timedelta(days=11)).isoformat()
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    repo = UrlHistoryRepository(
        DummyGraphRepo(),
        history_file=str(history_file),
        ttl_days=10,
        now_provider=lambda: now,
    )

    assert await repo.has_seen("https://wiki.example.com/echo/expired") is False


@pytest.mark.asyncio
async def test_url_history_still_reads_legacy_text_format(tmp_path):
    history_file = tmp_path / "visited_urls.txt"
    now = datetime(2026, 3, 29, tzinfo=timezone.utc)
    history_file.write_text(
        f"{(now - timedelta(days=1)).isoformat()}\thttps://wiki.example.com/legacy/page\n",
        encoding="utf-8",
    )

    repo = UrlHistoryRepository(
        DummyGraphRepo(),
        history_file=str(history_file),
        now_provider=lambda: now,
    )

    assert await repo.has_seen("https://wiki.example.com/legacy/page") is True
