"""Parsers for Kafka CLI outputs (consumer groups, topic offsets, partition skew)."""

from __future__ import annotations

import re
from typing import Any


def _safe_int(val: str) -> int | None:
    val = val.strip()
    if val in ("-", "", "unknown", "none", "None"):
        return None
    try:
        return int(val)
    except ValueError:
        return None


def parse_kafka_group_describe(raw: str) -> dict[str, Any]:
    """Parse `kafka-consumer-groups.sh --describe` output into lag per partition, state, and members."""
    partitions: list[dict[str, Any]] = []
    members: set[str] = set()
    state: str | None = None
    group_name: str | None = None
    total_lag = 0

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Handle `--state` output if present, e.g. "GROUP  COORDINATOR ... STATE  #MEMBERS"
        # or "Consumer group 'foo' has no active members."
        if "has no active members" in stripped.lower():
            state = state or "Empty"
            continue
        if stripped.startswith("GROUP") and "TOPIC" in stripped:
            continue
        if stripped.startswith("COORDINATOR") or stripped.startswith("GROUP") and "STATE" in stripped:
            continue

        parts = re.split(r"\s+", stripped)
        # Standard --describe row:
        # GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID
        if len(parts) >= 6 and _safe_int(parts[2]) is not None:
            group_name = group_name or parts[0]
            topic = parts[1]
            partition = int(parts[2])
            current_offset = _safe_int(parts[3])
            log_end_offset = _safe_int(parts[4])
            lag = _safe_int(parts[5])
            consumer_id = parts[6] if len(parts) > 6 and parts[6] != "-" else None
            host = parts[7] if len(parts) > 7 and parts[7] != "-" else None
            client_id = parts[8] if len(parts) > 8 and parts[8] != "-" else None

            if consumer_id:
                members.add(consumer_id)
            if lag is not None:
                total_lag += lag

            partitions.append(
                {
                    "topic": topic,
                    "partition": partition,
                    "current_offset": current_offset,
                    "log_end_offset": log_end_offset,
                    "lag": lag,
                    "consumer_id": consumer_id,
                    "host": host,
                    "client_id": client_id,
                }
            )
            continue

        # Check for state line from `--state` (e.g., "order-group  kafka:9092  range  Stable  2")
        for candidate_state in (
            "Stable",
            "PreparingRebalance",
            "CompletingRebalance",
            "Empty",
            "Dead",
        ):
            if candidate_state in parts:
                state = candidate_state
                break

    if state is None:
        state = "Stable" if members else "Empty"

    rebalance_evidence = state in ("PreparingRebalance", "CompletingRebalance")

    return {
        "group": group_name,
        "state": state,
        "member_count": len(members),
        "rebalance_evidence": rebalance_evidence,
        "total_lag": total_lag,
        "partition_count": len(partitions),
        "partitions": partitions,
    }


def parse_kafka_topic_offsets(raw: str) -> dict[str, Any]:
    """Parse `kafka-get-offsets.sh` or `GetOffsetShell` output (`topic:partition:offset`)."""
    partitions: list[dict[str, Any]] = []
    total_messages = 0
    topic_name: str | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        parts = stripped.split(":")
        if len(parts) != 3:
            continue
        topic, part_str, off_str = parts
        part = _safe_int(part_str)
        offset = _safe_int(off_str)
        if part is None or offset is None:
            continue
        topic_name = topic_name or topic
        total_messages += offset
        partitions.append({"topic": topic, "partition": part, "offset": offset})

    partitions.sort(key=lambda p: p["partition"])
    return {
        "topic": topic_name,
        "partition_count": len(partitions),
        "total_offset": total_messages,
        "partitions": partitions,
    }


def compute_partition_skew(partitions: list[dict[str, Any]], value_key: str = "offset") -> dict[str, Any]:
    """Compute partition skew metrics (min, max, avg, skew_ratio, skewed) from partition records."""
    values = [int(p[value_key]) for p in partitions if p.get(value_key) is not None]
    if not values:
        return {
            "partition_count": 0,
            "min": 0,
            "max": 0,
            "avg": 0.0,
            "skew_ratio": 0.0,
            "skewed": False,
            "hot_partitions": [],
        }

    min_val = min(values)
    max_val = max(values)
    avg_val = sum(values) / len(values)
    skew_ratio = round(max_val / avg_val, 2) if avg_val > 0 else 0.0
    # Consider skewed if max is > 2x average and there's meaningful volume
    skewed = skew_ratio >= 2.0 and max_val > 0
    hot_partitions = [
        p["partition"]
        for p in partitions
        if p.get(value_key) is not None and avg_val > 0 and p[value_key] >= avg_val * 2.0
    ]

    return {
        "partition_count": len(values),
        "min": min_val,
        "max": max_val,
        "avg": round(avg_val, 2),
        "skew_ratio": skew_ratio,
        "skewed": skewed,
        "hot_partitions": hot_partitions,
    }
