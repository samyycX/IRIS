from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    name: str
    description: str
    schema: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError
