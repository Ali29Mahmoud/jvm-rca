"""HikariCP metrics parser for Prometheus and Actuator formats."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_PROM_LINE_RE = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|[Nn][Aa][Nn]|[+-]?[Ii]nf)\s*$'
)
_PROM_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


def _parse_prometheus_text(raw: str) -> list[dict[str, Any]]:
    """Convert Prometheus exposition text into Prometheus vector-like dicts."""
    samples: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _PROM_LINE_RE.match(line)
        if not m:
            continue
        name, labels_raw, val_str = m.groups()
        if not name.startswith("hikaricp_"):
            continue
        labels: dict[str, str] = {"__name__": name}
        if labels_raw:
            for k, v in _PROM_LABEL_RE.findall(labels_raw):
                labels[k] = v
        samples.append({"metric": labels, "value": [0, val_str]})
    return samples


def parse_hikari_metrics(data: dict[str, Any] | list[dict[str, Any]] | str, *, source: str = "prometheus") -> dict[str, Any]:
    """Summarize HikariCP connection pool metrics from Prometheus JSON or Actuator `/actuator/prometheus` text."""
    if isinstance(data, str):
        samples = _parse_prometheus_text(data)
        detected_source = "actuator"
    elif isinstance(data, dict):
        samples = data.get("data", {}).get("result", [])
        detected_source = source
    else:
        samples = data
        detected_source = source

    pools: dict[tuple[str, str], dict[str, Any]] = {}
    for sample in samples:
        metric = sample.get("metric", {})
        name = metric.get("__name__", "")
        if not name.startswith("hikaricp_"):
            continue
        raw_val = sample.get("value", [None, None])[1]
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            continue
        if val != val:  # NaN
            continue

        service = metric.get("application") or metric.get("service") or metric.get("pod") or "unknown"
        pool_name = metric.get("pool") or "default"
        key = (service, pool_name)
        if key not in pools:
            pools[key] = {
                "service": service,
                "pool": pool_name,
                "active": None,
                "idle": None,
                "pending": None,
                "total": None,
                "max": None,
                "min": None,
                "timeout_total": None,
                "_acquire_count": None,
                "_acquire_sum": None,
                "acquire_max_ms": None,
                "_usage_count": None,
                "_usage_sum": None,
                "usage_max_ms": None,
                "creation_max_ms": None,
            }
        entry = pools[key]
        if name == "hikaricp_connections_active":
            entry["active"] = val
        elif name == "hikaricp_connections_idle":
            entry["idle"] = val
        elif name == "hikaricp_connections_pending":
            entry["pending"] = val
        elif name == "hikaricp_connections":
            entry["total"] = val
        elif name == "hikaricp_connections_max":
            entry["max"] = val
        elif name == "hikaricp_connections_min":
            entry["min"] = val
        elif name == "hikaricp_connections_timeout_total":
            entry["timeout_total"] = val
        elif name == "hikaricp_connections_acquire_seconds_count":
            entry["_acquire_count"] = val
        elif name == "hikaricp_connections_acquire_seconds_sum":
            entry["_acquire_sum"] = val
        elif name == "hikaricp_connections_acquire_seconds_max":
            entry["acquire_max_ms"] = round(val * 1000.0, 3)
        elif name == "hikaricp_connections_usage_seconds_count":
            entry["_usage_count"] = val
        elif name == "hikaricp_connections_usage_seconds_sum":
            entry["_usage_sum"] = val
        elif name == "hikaricp_connections_usage_seconds_max":
            entry["usage_max_ms"] = round(val * 1000.0, 3)
        elif name == "hikaricp_connections_creation_seconds_max":
            entry["creation_max_ms"] = round(val * 1000.0, 3)

    summarized: list[dict[str, Any]] = []
    for entry in pools.values():
        acq_c = entry.pop("_acquire_count")
        acq_s = entry.pop("_acquire_sum")
        usg_c = entry.pop("_usage_count")
        usg_s = entry.pop("_usage_sum")

        entry["acquire_avg_ms"] = round((acq_s / acq_c) * 1000.0, 3) if acq_c and acq_s is not None else None
        entry["usage_avg_ms"] = round((usg_s / usg_c) * 1000.0, 3) if usg_c and usg_s is not None else None

        active = entry["active"]
        max_conn = entry["max"]
        pending = entry["pending"]
        entry["utilization_pct"] = round((active / max_conn) * 100.0, 1) if active is not None and max_conn and max_conn > 0 else None
        entry["saturated"] = bool(
            (pending is not None and pending > 0)
            or (max_conn is not None and max_conn > 0 and active is not None and active >= max_conn)
        )
        summarized.append(entry)

    summarized.sort(key=lambda p: (not p["saturated"], -(p["pending"] or 0.0), p["service"], p["pool"]))
    return {
        "source": detected_source,
        "pool_count": len(summarized),
        "any_saturated": any(p["saturated"] for p in summarized),
        "pools": summarized,
    }
