"""Parsers for CDC service logs, outbox backlog, and Postgres replication slot lag."""

from __future__ import annotations

import re
from typing import Any

from benchmark.agent_j.parsers.postgres import parse_psql_json

_ERROR_LINE_RE = re.compile(r"\b(ERROR|Exception|FATAL|WARN)\b")


def parse_outbox_backlog(raw: str) -> dict[str, Any]:
    """Parse unpublished outbox row count and oldest timestamp from psql JSON."""
    rows = parse_psql_json(raw)
    if not rows:
        return {"unpublished_count": 0, "oldest_creation_time": None}
    row = rows[0]
    return {
        "unpublished_count": int(row.get("unpublished_count") or 0),
        "oldest_creation_time": row.get("oldest_creation_time"),
    }


def parse_replication_slots(raw: str) -> dict[str, Any]:
    """Parse pg_replication_slots lag metrics from psql JSON."""
    rows = parse_psql_json(raw)
    total_lag_bytes = 0
    inactive_slots = []
    for row in rows:
        lag = int(row.get("wal_lag_bytes") or 0)
        total_lag_bytes += lag
        if not row.get("active", False):
            inactive_slots.append(row.get("slot_name"))
    return {
        "slot_count": len(rows),
        "total_wal_lag_bytes": total_lag_bytes,
        "inactive_slots": inactive_slots,
        "slots": rows,
    }


def parse_cdc_logs(raw: str) -> dict[str, Any]:
    """Summarize CDC service logs for errors, exceptions, and recent activity."""
    lines = [line for line in raw.splitlines() if line.strip()]
    error_lines = [line for line in lines if _ERROR_LINE_RE.search(line)]
    return {
        "total_lines": len(lines),
        "error_count": len(error_lines),
        "recent_errors": error_lines[-10:],
        "tail_lines": lines[-10:],
    }
