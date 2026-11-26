"""JVM heap class histogram parser."""

from __future__ import annotations

import re
from typing import Any

_HISTOGRAM_ROW_RE = re.compile(r'^\s*(\d+):\s+(\d+)\s+(\d+)\s+(\S+)(?:\s+\(([^)]+)\))?\s*$')
_HISTOGRAM_TOTAL_RE = re.compile(r'^\s*Total\s+(\d+)\s+(\d+)\s*$')

_PRIMITIVE_ARRAY_CODES = {
    "B": "byte",
    "C": "char",
    "D": "double",
    "F": "float",
    "I": "int",
    "J": "long",
    "S": "short",
    "Z": "boolean",
}


def _decode_jvm_class(name: str) -> str:
    """Decode JVM internal array signatures like '[B' or '[Ljava.lang.String;'."""
    dims = 0
    rest = name
    while rest.startswith("["):
        dims += 1
        rest = rest[1:]
    if dims == 0:
        return name
    if len(rest) == 1 and rest in _PRIMITIVE_ARRAY_CODES:
        base = _PRIMITIVE_ARRAY_CODES[rest]
    elif rest.startswith("L") and rest.endswith(";"):
        base = rest[1:-1]
    else:
        base = rest
    return base + ("[]" * dims)



def parse_heap_histogram(raw: str, *, top_n: int = 15) -> dict[str, Any]:
    """Parse `jcmd <pid> GC.class_histogram` output and return the top N classes by bytes."""
    rows: list[dict[str, Any]] = []
    total_instances: int | None = None
    total_bytes: int | None = None

    for line in raw.splitlines():
        total_match = _HISTOGRAM_TOTAL_RE.match(line)
        if total_match:
            total_instances = int(total_match.group(1))
            total_bytes = int(total_match.group(2))
            continue
        row_match = _HISTOGRAM_ROW_RE.match(line)
        if row_match:
            rank, instances, nbytes, cls_name, module = row_match.groups()
            rows.append(
                {
                    "rank": int(rank),
                    "class_name": cls_name,
                    "readable_name": _decode_jvm_class(cls_name),
                    "module": module or "",
                    "instances": int(instances),
                    "bytes": int(nbytes),
                }
            )

    if total_instances is None:
        total_instances = sum(r["instances"] for r in rows)
    if total_bytes is None:
        total_bytes = sum(r["bytes"] for r in rows)

    rows.sort(key=lambda r: r["bytes"], reverse=True)
    top_rows = []
    for idx, row in enumerate(rows[:top_n], start=1):
        pct = round((row["bytes"] / total_bytes * 100.0), 2) if total_bytes > 0 else 0.0
        top_rows.append(
            {
                "rank": idx,
                "class_name": row["class_name"],
                "readable_name": row["readable_name"],
                "module": row["module"],
                "instances": row["instances"],
                "bytes": row["bytes"],
                "mb": round(row["bytes"] / (1024.0 * 1024.0), 2),
                "pct_bytes": pct,
            }
        )

    return {
        "total_instances": total_instances,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024.0 * 1024.0), 2),
        "shown_count": len(top_rows),
        "top_classes": top_rows,
    }


