"""Pure, zero-I/O parsers for JVM diagnostics."""

from benchmark.agent_j.parsers.cdc import (
    parse_cdc_logs,
    parse_outbox_backlog,
    parse_replication_slots,
)
from benchmark.agent_j.parsers.gc import parse_gc_logs
from benchmark.agent_j.parsers.heap import parse_heap_histogram
from benchmark.agent_j.parsers.hikari import parse_hikari_metrics
from benchmark.agent_j.parsers.kafka import (
    compute_partition_skew,
    parse_kafka_group_describe,
    parse_kafka_topic_offsets,
)
from benchmark.agent_j.parsers.postgres import (
    parse_pg_blocking_tree,
    parse_pg_explain,
    parse_pg_stat_activity,
    parse_pg_stat_statements,
    validate_readonly_sql,
)
from benchmark.agent_j.parsers.thread_dump import (
    parse_actuator_threaddump,
    parse_jcmd_thread_dump,
    parse_thread_dump,
)

__all__ = [
    "compute_partition_skew",
    "parse_actuator_threaddump",
    "parse_cdc_logs",
    "parse_gc_logs",
    "parse_heap_histogram",
    "parse_hikari_metrics",
    "parse_jcmd_thread_dump",
    "parse_kafka_group_describe",
    "parse_kafka_topic_offsets",
    "parse_outbox_backlog",
    "parse_pg_blocking_tree",
    "parse_pg_explain",
    "parse_pg_stat_activity",
    "parse_pg_stat_statements",
    "parse_replication_slots",
    "parse_thread_dump",
    "validate_readonly_sql",
]
