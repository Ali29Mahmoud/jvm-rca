"""JVM-aware diagnostic tools extending AgentGTools with compact structured summaries."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from benchmark.agent_g.tools import AgentGTools, ToolResult, ToolSpec
from benchmark.agent_j.models import (
    CdcLogsArgs,
    DEFAULT_NAMESPACE,
    GCLogArgs,
    HeapHistogramArgs,
    HikariSummaryArgs,
    KafkaGroupDescribeArgs,
    KafkaPartitionSkewArgs,
    KafkaTopicOffsetsArgs,
    OutboxBacklogArgs,
    PgBlockingTreeArgs,
    PgExplainArgs,
    PgStatActivityArgs,
    PgStatStatementsArgs,
    ReplicationSlotLagArgs,
    RunbookSearchArgs,
    ThreadDumpArgs,
)
from benchmark.agent_j.parsers import (
    compute_partition_skew,
    parse_cdc_logs,
    parse_gc_logs,
    parse_heap_histogram,
    parse_hikari_metrics,
    parse_kafka_group_describe,
    parse_kafka_topic_offsets,
    parse_outbox_backlog,
    parse_pg_blocking_tree,
    parse_pg_explain,
    parse_pg_stat_activity,
    parse_pg_stat_statements,
    parse_replication_slots,
    parse_thread_dump,
    validate_readonly_sql,
)
from benchmark.agent_j.runbook_retriever import BM25RunbookRetriever


class AgentJTools(AgentGTools):
    """Generic observability tools plus JVM-specific structured analyzers."""

    def _resolve_exec_target(self, target: str, namespace: str) -> str:
        """Resolve a service name like 'order-service' to a Running pod or deployment target."""
        if "/" in target:
            return target
        try:
            raw_pods = self.command_runner(
                ["kubectl", "get", "pods", "--namespace", namespace, "--output", "json"]
            )
            items = json.loads(raw_pods).get("items", [])
        except Exception:
            return target

        # Exact pod name match
        for item in items:
            if item.get("metadata", {}).get("name") == target:
                return target

        # Match by label svc/app or name prefix, preferring Running+Ready pods
        candidates = []
        for item in items:
            meta = item.get("metadata", {})
            labels = meta.get("labels", {})
            pod_name = meta.get("name", "")
            if (
                labels.get("svc") == target
                or labels.get("app") == target
                or pod_name.startswith(f"{target}-")
            ):
                phase = item.get("status", {}).get("phase", "")
                ready = all(
                    cs.get("ready", False)
                    for cs in item.get("status", {}).get("containerStatuses", [])
                )
                candidates.append((phase == "Running" and ready, phase == "Running", pod_name))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]
        return target

    def _exec_jcmd(self, pod_or_target: str, namespace: str, jcmd_args: list[str]) -> str:
        return self.command_runner(
            [
                "kubectl",
                "exec",
                "--namespace",
                namespace,
                pod_or_target,
                "--",
                "env",
                "-u",
                "JAVA_TOOL_OPTIONS",
                "jcmd",
                "1",
                *jcmd_args,
            ]
        )

    def _exec_actuator(self, pod_or_target: str, namespace: str, path: str) -> str:
        return self.command_runner(
            [
                "kubectl",
                "exec",
                "--namespace",
                namespace,
                pod_or_target,
                "--",
                "curl",
                "-sf",
                f"http://localhost:8080{path}",
            ]
        )

    def thread_dump(self, args: ThreadDumpArgs | dict[str, Any]) -> ToolResult:
        args = ThreadDumpArgs.model_validate(args)
        pod_target = self._resolve_exec_target(args.target, args.namespace)
        if args.source == "actuator":
            raw = self._exec_actuator(pod_target, args.namespace, "/actuator/threaddump")
        elif args.source == "jcmd":
            raw = self._exec_jcmd(pod_target, args.namespace, ["Thread.print"])
        else:
            try:
                raw = self._exec_jcmd(pod_target, args.namespace, ["Thread.print"])
            except Exception:
                raw = self._exec_actuator(pod_target, args.namespace, "/actuator/threaddump")
        summary = parse_thread_dump(raw)
        summary["target"] = pod_target
        return self._result("thread_dump", summary)

    def heap_histogram(self, args: HeapHistogramArgs | dict[str, Any]) -> ToolResult:
        args = HeapHistogramArgs.model_validate(args)
        pod_target = self._resolve_exec_target(args.target, args.namespace)
        cmd_args = ["GC.class_histogram"] if args.live_only else ["GC.class_histogram", "-all"]
        raw = self._exec_jcmd(pod_target, args.namespace, cmd_args)
        summary = parse_heap_histogram(raw, top_n=args.top_n)
        summary["target"] = pod_target
        return self._result("heap_histogram", summary)

    def gc_log(self, args: GCLogArgs | dict[str, Any]) -> ToolResult:
        args = GCLogArgs.model_validate(args)
        pod_target = self._resolve_exec_target(args.target, args.namespace)
        command = [
            "kubectl",
            "logs",
            "--namespace",
            args.namespace,
            pod_target,
            "--tail",
            str(args.tail),
        ]
        if args.previous:
            command.append("--previous")
        raw = self.command_runner(command)
        summary = parse_gc_logs(raw)
        summary["target"] = pod_target
        return self._result("gc_log", summary)

    def hikari_summary(self, args: HikariSummaryArgs | dict[str, Any]) -> ToolResult:
        args = HikariSummaryArgs.model_validate(args)
        if args.source != "actuator":
            filters = [f'namespace="{args.namespace}"', '__name__=~"hikaricp_.*"']
            if args.service:
                filters.append(f'application="{args.service}"')
            promql = "{" + ", ".join(filters) + "}"
            payload = self.http_get(
                f"{self.prometheus_url}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
            )
            summary = parse_hikari_metrics(payload, source="prometheus")
            if summary["pool_count"] > 0 or args.source == "prometheus":
                return self._result("hikari_summary", summary)

        if not args.service:
            raise ValueError("hikari_summary with actuator fallback requires 'service' when Prometheus has no HikariCP samples")
        pod_target = self._resolve_exec_target(args.service, args.namespace)
        raw = self._exec_actuator(pod_target, args.namespace, "/actuator/prometheus")
        summary = parse_hikari_metrics(raw, source="actuator")
        return self._result("hikari_summary", summary)

    # --- Kafka tools ---

    def _exec_kafka_cli(self, kafka_pod: str, namespace: str, cmd: list[str]) -> str:
        pod_target = self._resolve_exec_target(kafka_pod, namespace)
        return self.command_runner(
            ["kubectl", "exec", "--namespace", namespace, pod_target, "--", *cmd]
        )

    def kafka_group_describe(self, args: KafkaGroupDescribeArgs | dict[str, Any]) -> ToolResult:
        args = KafkaGroupDescribeArgs.model_validate(args)
        raw_desc = self._exec_kafka_cli(
            args.kafka_pod,
            args.namespace,
            [
                "kafka-consumer-groups.sh",
                "--bootstrap-server",
                args.bootstrap_server,
                "--group",
                args.group,
                "--describe",
            ],
        )
        summary = parse_kafka_group_describe(raw_desc)
        summary["group"] = summary["group"] or args.group
        return self._result("kafka_group_describe", summary)

    def kafka_topic_offsets(self, args: KafkaTopicOffsetsArgs | dict[str, Any]) -> ToolResult:
        args = KafkaTopicOffsetsArgs.model_validate(args)
        raw = self._exec_kafka_cli(
            args.kafka_pod,
            args.namespace,
            [
                "kafka-run-class.sh",
                "kafka.tools.GetOffsetShell",
                "--broker-list",
                args.bootstrap_server,
                "--topic",
                args.topic,
            ],
        )
        summary = parse_kafka_topic_offsets(raw)
        summary["topic"] = summary["topic"] or args.topic
        return self._result("kafka_topic_offsets", summary)

    def kafka_partition_skew(self, args: KafkaPartitionSkewArgs | dict[str, Any]) -> ToolResult:
        args = KafkaPartitionSkewArgs.model_validate(args)
        if args.group:
            desc = json.loads(
                self.kafka_group_describe(
                    {
                        "group": args.group,
                        "namespace": args.namespace,
                        "kafka_pod": args.kafka_pod,
                        "bootstrap_server": args.bootstrap_server,
                    }
                ).summary
            )
            skew = compute_partition_skew(desc.get("partitions", []), value_key="lag")
            skew["source"] = "consumer_group_lag"
            skew["group"] = args.group
            return self._result("kafka_partition_skew", skew)
        if args.topic:
            offsets = json.loads(
                self.kafka_topic_offsets(
                    {
                        "topic": args.topic,
                        "namespace": args.namespace,
                        "kafka_pod": args.kafka_pod,
                        "bootstrap_server": args.bootstrap_server,
                    }
                ).summary
            )
            skew = compute_partition_skew(offsets.get("partitions", []), value_key="offset")
            skew["source"] = "topic_offsets"
            skew["topic"] = args.topic
            return self._result("kafka_partition_skew", skew)
        raise ValueError("kafka_partition_skew requires either 'topic' or 'group'")

    # --- Postgres read-only tools ---

    def _exec_psql_ro(self, postgres_pod: str, namespace: str, database: str, ro_user: str, sql: str) -> str:
        pod_target = self._resolve_exec_target(postgres_pod, namespace)
        ro_sql = f"BEGIN READ ONLY; {sql}; COMMIT;"
        return self.command_runner(
            [
                "kubectl",
                "exec",
                "--namespace",
                namespace,
                pod_target,
                "--",
                "psql",
                "-U",
                ro_user,
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-X",
                "-t",
                "-A",
                "-c",
                ro_sql,
            ]
        )

    def pg_stat_activity(self, args: PgStatActivityArgs | dict[str, Any]) -> ToolResult:
        args = PgStatActivityArgs.model_validate(args)
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT pid, usename, state, wait_event_type, wait_event, "
            "EXTRACT(EPOCH FROM (now() - query_start))::float AS duration_seconds, query "
            "FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
            "ORDER BY duration_seconds DESC NULLS LAST LIMIT 50"
            ") t"
        )
        raw = self._exec_psql_ro(args.postgres_pod, args.namespace, args.database, args.ro_user, sql)
        return self._result("pg_stat_activity", parse_pg_stat_activity(raw))

    def pg_blocking_tree(self, args: PgBlockingTreeArgs | dict[str, Any]) -> ToolResult:
        args = PgBlockingTreeArgs.model_validate(args)
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT a.pid AS blocked_pid, a.usename AS blocked_user, a.query AS blocked_query, "
            "pg_blocking_pids(a.pid) AS blocking_pids, "
            "EXTRACT(EPOCH FROM (now() - a.query_start))::float AS blocked_seconds "
            "FROM pg_stat_activity a WHERE cardinality(pg_blocking_pids(a.pid)) > 0"
            ") t"
        )
        raw = self._exec_psql_ro(args.postgres_pod, args.namespace, args.database, args.ro_user, sql)
        return self._result("pg_blocking_tree", parse_pg_blocking_tree(raw))

    def pg_stat_statements(self, args: PgStatStatementsArgs | dict[str, Any]) -> ToolResult:
        args = PgStatStatementsArgs.model_validate(args)
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT calls, round(total_exec_time::numeric, 2) AS total_exec_time_ms, "
            "round(mean_exec_time::numeric, 2) AS mean_exec_time_ms, rows, left(query, 200) AS query "
            f"FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT {args.limit}"
            ") t"
        )
        raw = self._exec_psql_ro(args.postgres_pod, args.namespace, args.database, args.ro_user, sql)
        return self._result("pg_stat_statements", parse_pg_stat_statements(raw))

    def pg_explain(self, args: PgExplainArgs | dict[str, Any]) -> ToolResult:
        args = PgExplainArgs.model_validate(args)
        safe_sql = validate_readonly_sql(args.sql)
        raw = self._exec_psql_ro(
            args.postgres_pod,
            args.namespace,
            args.database,
            args.ro_user,
            f"EXPLAIN (FORMAT JSON) {safe_sql}",
        )
        return self._result("pg_explain", parse_pg_explain(raw))

    # --- CDC & Outbox tools ---

    def outbox_backlog(self, args: OutboxBacklogArgs | dict[str, Any]) -> ToolResult:
        args = OutboxBacklogArgs.model_validate(args)
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT count(*) AS unpublished_count, min(creation_time) AS oldest_creation_time "
            f"FROM {args.table} WHERE published = 0"
            ") t"
        )
        raw = self._exec_psql_ro(args.postgres_pod, args.namespace, args.database, args.ro_user, sql)
        return self._result("outbox_backlog", parse_outbox_backlog(raw))

    def replication_slot_lag(self, args: ReplicationSlotLagArgs | dict[str, Any]) -> ToolResult:
        args = ReplicationSlotLagArgs.model_validate(args)
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT slot_name, plugin, slot_type, active, "
            "pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint AS wal_lag_bytes "
            "FROM pg_replication_slots"
            ") t"
        )
        raw = self._exec_psql_ro(args.postgres_pod, args.namespace, args.database, args.ro_user, sql)
        return self._result("replication_slot_lag", parse_replication_slots(raw))

    def cdc_logs(self, args: CdcLogsArgs | dict[str, Any]) -> ToolResult:
        args = CdcLogsArgs.model_validate(args)
        pod_target = self._resolve_exec_target(args.target, args.namespace)
        command = [
            "kubectl",
            "logs",
            "--namespace",
            args.namespace,
            pod_target,
            "--tail",
            str(args.tail),
        ]
        if args.previous:
            command.append("--previous")
        raw = self.command_runner(command)
        summary = parse_cdc_logs(raw)
        summary["target"] = pod_target
        return self._result("cdc_logs", summary)

    # --- Runbook BM25 retriever ---

    def runbook_search(self, args: RunbookSearchArgs | dict[str, Any]) -> ToolResult:
        args = RunbookSearchArgs.model_validate(args)
        retriever = BM25RunbookRetriever()
        matches = retriever.search(args.query, top_k=args.top_k)
        return self._result("runbook_search", {"query": args.query, "matches": matches})

    def specs(self) -> list[ToolSpec]:
        return [
            *super().specs(),
            ToolSpec(
                "thread_dump",
                "Capture and summarize a JVM thread dump by state, lock owners, wait hotspots, and deadlocks.",
                ThreadDumpArgs,
                self.thread_dump,
            ),
            ToolSpec(
                "heap_histogram",
                "Capture a JVM heap class histogram and return the top classes by memory usage.",
                HeapHistogramArgs,
                self.heap_histogram,
            ),
            ToolSpec(
                "gc_log",
                "Parse JVM GC logs from pod stdout and compute pause percentiles (p50/p95/p99), full GC count, and heap occupancy.",
                GCLogArgs,
                self.gc_log,
            ),
            ToolSpec(
                "hikari_summary",
                "Summarize HikariCP connection pool active, idle, pending, max, timeouts, and acquire/usage latency.",
                HikariSummaryArgs,
                self.hikari_summary,
            ),
            ToolSpec(
                "kafka_group_describe",
                "Describe a Kafka consumer group: lag per partition, group state, member count, and rebalance evidence.",
                KafkaGroupDescribeArgs,
                self.kafka_group_describe,
            ),
            ToolSpec(
                "kafka_topic_offsets",
                "Fetch Kafka topic end offsets per partition.",
                KafkaTopicOffsetsArgs,
                self.kafka_topic_offsets,
            ),
            ToolSpec(
                "kafka_partition_skew",
                "Compute Kafka partition skew (min, max, avg, skew_ratio, hot_partitions) for a topic or consumer group.",
                KafkaPartitionSkewArgs,
                self.kafka_partition_skew,
            ),
            ToolSpec(
                "pg_stat_activity",
                "Inspect Postgres pg_stat_activity (read-only) by connection state, wait events, and longest active queries.",
                PgStatActivityArgs,
                self.pg_stat_activity,
            ),
            ToolSpec(
                "pg_blocking_tree",
                "Inspect Postgres lock contention and blocking PIDs using pg_blocking_pids() (read-only).",
                PgBlockingTreeArgs,
                self.pg_blocking_tree,
            ),
            ToolSpec(
                "pg_stat_statements",
                "Return top Postgres queries by total execution time from pg_stat_statements (read-only).",
                PgStatStatementsArgs,
                self.pg_stat_statements,
            ),
            ToolSpec(
                "pg_explain",
                "Run read-only EXPLAIN (FORMAT JSON) on a SELECT/WITH query.",
                PgExplainArgs,
                self.pg_explain,
            ),
            ToolSpec(
                "outbox_backlog",
                "Count unpublished rows in the Eventuate outbox table (read-only).",
                OutboxBacklogArgs,
                self.outbox_backlog,
            ),
            ToolSpec(
                "replication_slot_lag",
                "Inspect Postgres replication slot active status and WAL lag bytes (read-only).",
                ReplicationSlotLagArgs,
                self.replication_slot_lag,
            ),
            ToolSpec(
                "cdc_logs",
                "Fetch and summarize CDC service pod logs for errors and recent activity.",
                CdcLogsArgs,
                self.cdc_logs,
            ),
            ToolSpec(
                "runbook_search",
                "Search failure-class runbooks using BM25 and return top matching remediation guides.",
                RunbookSearchArgs,
                self.runbook_search,
            ),
        ]
