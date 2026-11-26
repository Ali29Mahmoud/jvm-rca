"""JVM-aware diagnostic tools extending AgentGTools with compact structured summaries."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from benchmark.agent_g.tools import AgentGTools, ToolResult, ToolSpec
from benchmark.agent_j.models import (
    DEFAULT_NAMESPACE,
    GCLogArgs,
    HeapHistogramArgs,
    HikariSummaryArgs,
    ThreadDumpArgs,
)
from benchmark.agent_j.parsers import (
    parse_gc_logs,
    parse_heap_histogram,
    parse_hikari_metrics,
    parse_thread_dump,
)


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
        ]
