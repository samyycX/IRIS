from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class LocalDataStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def read_json(self, *parts: str) -> dict[str, Any] | list[Any] | None:
        path = self.resolve(*parts)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, *parts: str, payload: dict[str, Any] | list[Any]) -> Path:
        path = self.resolve(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            suffix=".tmp",
        ) as handle:
            handle.write(serialized)
            temp_path = Path(handle.name)
        temp_path.replace(path)
        return path

    def resolve(self, *parts: str) -> Path:
        return self._root.joinpath(*parts)
