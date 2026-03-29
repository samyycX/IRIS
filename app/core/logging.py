import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog


def _rename_event_key(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event = event_dict.pop("event", None)
    if event is not None:
        event_dict["message"] = event
    event_dict["level"] = method_name
    return event_dict


def configure_logging(log_level: str) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=False)
    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        _rename_event_key,
        timestamper,
    ]

    logging.basicConfig(
        level=log_level.upper(),
        format="%(message)s",
        stream=sys.stdout,
    )

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
