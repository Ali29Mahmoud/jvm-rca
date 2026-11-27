"""Parsers and read-only SQL validators for Postgres diagnostic tools."""

from __future__ import annotations

import json
import re
from typing import Any

_FORBIDDEN_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|MERGE|CALL|DO)\b",
    re.IGNORECASE,
)


def validate_readonly_sql(sql: str) -> str:
    """Ensure a SQL statement is strictly read-only (SELECT/WITH/EXPLAIN SELECT)."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("SQL query cannot be empty")
    if ";" in stripped:
        raise ValueError("Multiple SQL statements are not allowed")
    if _FORBIDDEN_SQL_RE.search(stripped):
        raise ValueError("Write or DDL/DML statements are not permitted in read-only mode")
    upper = stripped.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise ValueError("Only SELECT or WITH ... SELECT queries are permitted")
    return stripped


def parse_psql_json(raw: str) -> list[dict[str, Any]]:
    """Parse JSON array output from `psql -X -t -A -c 'SELECT coalesce(json_agg(t), ...)'`."""
    text = raw.strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def parse_pg_stat_activity(raw: str) -> dict[str, Any]:
    """Summarize pg_stat_activity rows by state, wait_event_type, and active queries."""
    rows = parse_psql_json(raw)
    by_state: dict[str, int] = {}
    waiting_count = 0
    longest_active_sec = 0.0
    active_queries: list[dict[str, Any]] = []

    for row in rows:
        state = str(row.get("state") or "unknown")
        by_state[state] = by_state.get(state, 0) + 1
        if row.get("wait_event_type"):
            waiting_count += 1
        dur = float(row.get("duration_seconds") or 0.0)
        if state == "active":
            longest_active_sec = max(longest_active_sec, dur)
            active_queries.append(
                {
                    "pid": row.get("pid"),
                    "usename": row.get("usename"),
                    "state": state,
                    "wait_event_type": row.get("wait_event_type"),
                    "wait_event": row.get("wait_event"),
                    "duration_seconds": round(dur, 3),
                    "query": str(row.get("query") or "")[:200],
                }
            )

    active_queries.sort(key=lambda q: q["duration_seconds"], reverse=True)
    return {
        "total_connections": len(rows),
        "by_state": by_state,
        "waiting_count": waiting_count,
        "longest_active_seconds": round(longest_active_sec, 3),
        "active_queries": active_queries[:10],
    }


def parse_pg_blocking_tree(raw: str) -> dict[str, Any]:
    """Summarize blocked vs blocking PIDs from pg_blocking_pids() query output."""
    rows = parse_psql_json(raw)
    return {
        "blocked_count": len(rows),
        "locks": rows[:20],
    }


def parse_pg_stat_statements(raw: str) -> dict[str, Any]:
    """Summarize top queries from pg_stat_statements."""
    rows = parse_psql_json(raw)
    return {
        "query_count": len(rows),
        "top_queries": rows[:15],
    }


def parse_pg_explain(raw: str) -> dict[str, Any]:
    """Parse `EXPLAIN (FORMAT JSON)` output into plan summary."""
    text = raw.strip()
    if not text:
        return {"plan": None, "node_type": None, "total_cost": None}
    data = json.loads(text)
    if isinstance(data, list) and data:
        plan = data[0].get("Plan", {})
        return {
            "node_type": plan.get("Node Type"),
            "relation_name": plan.get("Relation Name"),
            "startup_cost": plan.get("Startup Cost"),
            "total_cost": plan.get("Total Cost"),
            "plan_rows": plan.get("Plan Rows"),
            "plan": plan,
        }
    return {"plan": data, "node_type": None, "total_cost": None}
