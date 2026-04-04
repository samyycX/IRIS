"""Logging helpers for the IRIS MCP server."""

from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    """Configure standard library logging once for CLI entrypoints."""

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )