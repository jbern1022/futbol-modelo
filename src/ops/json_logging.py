"""
Structured JSON logging for the cron scripts and the API (Todoist:
"Structured JSON logging shipped to Loki/Grafana"). One JSON object per
line on stdout -- k8s captures container stdout automatically, and
Promtail (see k8s/promtail.yaml) parses these lines directly, promoting
`level`/`logger`/`job` to real Loki labels instead of leaving them
buried in an opaque message string. A plain-text formatter can't be
queried that way: "show me every ERROR from auto_slate in the last
hour" needs level and job to be structured fields, not substrings.

    from ops.json_logging import configure_json_logging
    log = configure_json_logging("auto_slate")
    log.info("fixture skipped", extra={"reason": "already slated", "league": "MLS"})

Extra keyword fields passed via `extra=` are merged into the JSON line
verbatim -- the same mechanism the stdlib logging module already uses,
just serialized as JSON instead of interpolated into a text template.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Attributes every LogRecord already carries (from stdlib logging's own
# __init__) -- anything else on the record came from a caller's `extra=`
# and belongs in the JSON output. Diffing against this set, rather than
# hardcoding the field list, means it doesn't go stale if a caller starts
# passing new extra fields tomorrow.
_STANDARD_ATTRS = frozenset(logging.LogRecord(
    "", 0, "", 0, "", (), None).__dict__.keys())


class JsonFormatter(logging.Formatter):
    def __init__(self, job: str):
        super().__init__()
        self.job = job

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "job": self.job,
            "message": record.getMessage(),
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}
        payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logging(job: str, level: int = logging.INFO) -> logging.Logger:
    """Configures the ROOT logger (so every module's `logging.getLogger(__name__)`
    inherits it, matching how `logging.basicConfig` is used elsewhere in this
    codebase) and returns a logger named after `job` for the caller's own use."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(job))
    root.addHandler(handler)
    return logging.getLogger(job)
