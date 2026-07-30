"""JSON log records, redacted, with the current trace attached.

One formatter for every process, so an API line and a worker line join on the
same fields. Records are JSON because they are read by machines first: a human
greps them perhaps once an incident, while an aggregator parses every one.

The redaction happens *here*, in the formatter, rather than at each call site.
Call-site discipline is the wrong mechanism for a guarantee this absolute — it
holds until the one debug line somebody adds at 2am, and that line is the one
that leaks. Putting it in the formatter means a developer cannot log tenant
content by accident, only by deliberately renaming a field to defeat the
classifier.

Exception text is deliberately reduced to the exception *type*. A driver error
carries its bound parameters — the raw query, sometimes evidence text — so a
traceback is one of the richest sources of tenant content in the system, and it
arrives on exactly the path where nobody is looking.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.observability.context import context_fields
from app.observability.redaction import redact_fields

# Attributes `logging` puts on every record. Anything outside this set was added
# by a caller through `extra=`, which is what the structured payload is.
_STANDARD_ATTRIBUTES = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Render a record as one redacted JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRIBUTES and not key.startswith("_")
        }
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            # The format *string*, not the interpolated message: arguments are
            # frequently the values a caller wanted to see, and those go through
            # redaction as fields instead of being spliced into free text where
            # nothing can classify them.
            "event": record.msg if isinstance(record.msg, str) else str(record.msg),
            **context_fields(),
            **redact_fields(extras),
        }
        if record.exc_info and record.exc_info[0] is not None:
            # Type only. The message and traceback of a database or provider
            # error routinely carry bound parameters, which is tenant content
            # arriving on the one path nobody inspects.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, stream: Any | None = None) -> None:
    """Install the JSON formatter as the only handler on the root logger.

    Replaces existing handlers rather than adding to them: a second plain-text
    handler would re-emit every record unredacted, which is the failure this
    module exists to prevent and would be invisible in a normal test run.
    """
    handler = logging.StreamHandler(stream) if stream is not None else logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)


__all__ = ["JsonFormatter", "configure_logging"]
