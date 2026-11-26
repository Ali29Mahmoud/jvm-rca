"""JVM GC log parser (unified and legacy formats)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_UNIFIED_GC_RE = re.compile(
    r'(?:\[([^\]]+)\].*?)?GC\((\d+)\)\s+'
    r'(Pause\s+[^()\n]+(?:\s+\([^)]+\))*|Concurrent\s+[^()\n]+(?:\s+\([^)]+\))*)'
    r'(?:\s+(\d+(?:\.\d+)?[KMG])->(\d+(?:\.\d+)?[KMG])\((\d+(?:\.\d+)?[KMG])\))?'
    r'\s+([\d.]+)ms\b'
)
_LEGACY_GC_RE = re.compile(
    r'\[(Full GC|GC)\s+\(([^)]+)\).*?'
    r'(?:(\d+[KMG])->(\d+[KMG])\((\d+[KMG])\))?.*?([\d.]+)\s+secs\]'
)


def _size_to_mb(token: str) -> float:
    """Convert GC size tokens like '1024K', '64M', '1G' to megabytes."""
    unit = token[-1].upper()
    val = float(token[:-1])
    if unit == "K":
        return val / 1024.0
    if unit == "M":
        return val
    if unit == "G":
        return val * 1024.0
    return val / (1024.0 * 1024.0)


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linearly interpolated percentile (0-100) on a pre-sorted non-empty list."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac



def parse_gc_logs(raw: str) -> dict[str, Any]:
    """Parse Unified JVM GC logs (`-Xlog:gc*`) or legacy GC logs into pause percentiles & counts."""
    events: list[dict[str, Any]] = []
    causes: Counter[str] = Counter()
    young_gc = 0
    mixed_gc = 0
    full_gc = 0
    concurrent_cycles = 0
    to_space_exhausted = 0
    oom_errors = 0

    for line in raw.splitlines():
        if "OutOfMemoryError" in line:
            oom_errors += 1
        if "To-space exhausted" in line or "Evacuation Failure" in line:
            to_space_exhausted += 1

        # Skip gc,start lines so we only count completed GC events
        if "[gc,start" in line:
            continue

        um = _UNIFIED_GC_RE.search(line)
        if um:
            ts, gc_id, desc, before_tok, after_tok, cap_tok, dur_str = um.groups()
            dur_ms = float(dur_str)
            desc_clean = desc.strip()
            is_pause = desc_clean.startswith("Pause")
            if "Pause Full" in desc_clean:
                full_gc += 1
                kind = "Full"
            elif "Mixed" in desc_clean:
                mixed_gc += 1
                kind = "Mixed"
            elif "Pause Young" in desc_clean:
                young_gc += 1
                kind = "Young"
            elif desc_clean.startswith("Concurrent"):
                concurrent_cycles += 1
                kind = "Concurrent"
            else:
                kind = "Pause" if is_pause else "Other"

            # Extract cause from last parenthesized group if any
            parens = re.findall(r'\(([^)]+)\)', desc_clean)
            cause = parens[-1] if parens else desc_clean
            if cause in ("Normal", "Mixed", "Concurrent Start") and len(parens) >= 2:
                cause = parens[-2]
            if is_pause:
                causes[cause] += 1

            ev: dict[str, Any] = {
                "gc_id": int(gc_id),
                "kind": kind,
                "is_pause": is_pause,
                "cause": cause,
                "duration_ms": round(dur_ms, 3),
            }
            if ts:
                ev["timestamp"] = ts
            if before_tok and after_tok and cap_tok:
                ev["heap_before_mb"] = round(_size_to_mb(before_tok), 2)
                ev["heap_after_mb"] = round(_size_to_mb(after_tok), 2)
                ev["heap_capacity_mb"] = round(_size_to_mb(cap_tok), 2)
            events.append(ev)
            continue

        lm = _LEGACY_GC_RE.search(line)
        if lm:
            kind_raw, cause, before_tok, after_tok, cap_tok, secs_str = lm.groups()
            dur_ms = float(secs_str) * 1000.0
            is_full = kind_raw == "Full GC"
            if is_full:
                full_gc += 1
            else:
                young_gc += 1
            causes[cause] += 1
            ev = {
                "gc_id": len(events),
                "kind": "Full" if is_full else "Young",
                "is_pause": True,
                "cause": cause,
                "duration_ms": round(dur_ms, 3),
            }
            if before_tok and after_tok and cap_tok:
                ev["heap_before_mb"] = round(_size_to_mb(before_tok), 2)
                ev["heap_after_mb"] = round(_size_to_mb(after_tok), 2)
                ev["heap_capacity_mb"] = round(_size_to_mb(cap_tok), 2)
            events.append(ev)

    pause_durations = sorted(ev["duration_ms"] for ev in events if ev["is_pause"])
    if pause_durations:
        pause_stats = {
            "count": len(pause_durations),
            "min": round(pause_durations[0], 3),
            "p50": round(_percentile(pause_durations, 50), 3),
            "p95": round(_percentile(pause_durations, 95), 3),
            "p99": round(_percentile(pause_durations, 99), 3),
            "max": round(pause_durations[-1], 3),
            "avg": round(sum(pause_durations) / len(pause_durations), 3),
            "total": round(sum(pause_durations), 3),
        }
    else:
        pause_stats = {"count": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "avg": 0.0, "total": 0.0}

    heap_events = [ev for ev in events if "heap_after_mb" in ev]
    heap_summary: dict[str, Any] = {}
    if heap_events:
        latest = heap_events[-1]
        max_after = max(ev["heap_after_mb"] for ev in heap_events)
        peak_pct = max(
            (ev["heap_after_mb"] / ev["heap_capacity_mb"] * 100.0)
            for ev in heap_events
            if ev["heap_capacity_mb"] > 0
        ) if any(ev["heap_capacity_mb"] > 0 for ev in heap_events) else 0.0
        heap_summary = {
            "latest_before": latest["heap_before_mb"],
            "latest_after": latest["heap_after_mb"],
            "latest_capacity": latest["heap_capacity_mb"],
            "max_after": round(max_after, 2),
            "peak_occupancy_pct": round(peak_pct, 1),
        }

    pause_events = [ev for ev in events if ev["is_pause"]]
    return {
        "gc_logging_enabled": len(events) > 0,
        "total_gc_events": len(events),
        "pause_events": len(pause_events),
        "young_gc_count": young_gc,
        "mixed_gc_count": mixed_gc,
        "full_gc_count": full_gc,
        "concurrent_cycles": concurrent_cycles,
        "to_space_exhausted_count": to_space_exhausted,
        "oom_errors": oom_errors,
        "pause_ms": pause_stats,
        "causes": dict(causes.most_common(10)),
        "heap_mb": heap_summary,
        "recent_events": pause_events[-5:],
    }


