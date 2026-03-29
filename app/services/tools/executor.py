from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.tools.registry import ToolRegistry

logger = get_logger(__name__)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, name: str, **kwargs: Any) -> dict[str, Any]:
        tool = self._registry.get(name)
        logger.info("tool_execute_start", tool_name=name, payload=kwargs)
        result = await tool.execute(**kwargs)
        logger.info("tool_execute_complete", tool_name=name)
        return result
