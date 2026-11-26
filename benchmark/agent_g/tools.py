"""Read-only generic observability tools with bounded output."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from pydantic import Field, field_validator

from benchmark.agent_g.models import StrictModel


class ToolResult(StrictModel):
    """Compact, citeable evidence returned by every Agent-G tool."""

    evidence_id: str
    tool: str
    summary: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    original_chars: int = 0


class PromQLArgs(StrictModel):
    query: str = Field(min_length=1, max_length=4096)
    time: str | None = None


class LogQLArgs(StrictModel):
    query: str = Field(min_length=1, max_length=4096)
    start_ns: int | None = Field(default=None, ge=0)
    end_ns: int | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class TraceSearchArgs(StrictModel):
    service: str = Field(min_length=1, max_length=256)
    operation: str | None = Field(default=None, max_length=512)
    tags: dict[str, str] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=100)


class KubectlArgs(StrictModel):
    verb: Literal["get", "describe", "logs", "top", "events"]
    resource: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9./-]+$")
    name: str | None = Field(default=None, max_length=253, pattern=r"^[a-z0-9./-]+$")
    namespace: str | None = Field(default=None, max_length=253, pattern=r"^[a-z0-9-]+$")
    selector: str | None = Field(default=None, max_length=512)
    tail: int = Field(default=100, ge=1, le=500)

    @field_validator("resource", "name", "namespace")
    @classmethod
    def reject_option_like_values(cls, value: str | None) -> str | None:
        if value is not None and value.startswith("-"):
            raise ValueError("kubectl resource, name, and namespace cannot start with '-'")
        return value


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[StrictModel]
    function: Callable[[Any], ToolResult]

    @property
    def json_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


def _compact(value: Any, *, cap: int, top_k: int) -> tuple[str, list[dict[str, Any]], bool, int]:
    """Produce bounded text plus at most ``top_k`` structured records."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    original_chars = len(raw)
    if isinstance(value, list):
        items = [item if isinstance(item, dict) else {"value": item} for item in value[:top_k]]
    elif isinstance(value, dict):
        items = [{"key": key, "value": item} for key, item in list(value.items())[:top_k]]
    else:
        items = [{"value": value}]
    shown = raw[:cap]
    return shown, items, original_chars > cap or len(items) >= top_k and isinstance(value, list) and len(value) > top_k, original_chars


class AgentGTools:
    """Read-only generic observability tools with bounded output."""

    def __init__(
        self,
        *,
        prometheus_url: str | None = None,
        loki_url: str | None = None,
        jaeger_url: str | None = None,
        http_get: Callable[[str], Any] | None = None,
        command_runner: Callable[[list[str]], str] | None = None,
        output_cap_chars: int = 4_000,
        top_k: int = 10,
    ):
        self.prometheus_url = (prometheus_url or os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")).rstrip("/")
        self.loki_url = (loki_url or os.getenv("LOKI_URL", "http://127.0.0.1:3100")).rstrip("/")
        self.jaeger_url = (jaeger_url or os.getenv("JAEGER_URL", "http://127.0.0.1:16686")).rstrip("/")
        self.http_get = http_get or self._http_get
        self.command_runner = command_runner or self._run_command
        self.output_cap_chars = output_cap_chars
        self.top_k = top_k
        self._evidence_number = 0

    @staticmethod
    def _http_get(url: str) -> Any:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read())

    @staticmethod
    def _run_command(command: list[str]) -> str:
        return subprocess.run(command, check=True, text=True, capture_output=True, timeout=20).stdout

    def _result(self, tool: str, value: Any) -> ToolResult:
        self._evidence_number += 1
        summary, items, truncated, original_chars = _compact(value, cap=self.output_cap_chars, top_k=self.top_k)
        return ToolResult(
            evidence_id=f"E{self._evidence_number}", tool=tool, summary=summary,
            items=items, truncated=truncated, original_chars=original_chars,
        )

    def promql(self, args: PromQLArgs | dict[str, Any]) -> ToolResult:
        args = PromQLArgs.model_validate(args)
        params = {"query": args.query}
        if args.time:
            params["time"] = args.time
        return self._result("promql", self.http_get(f"{self.prometheus_url}/api/v1/query?{urllib.parse.urlencode(params)}"))

    def logql(self, args: LogQLArgs | dict[str, Any]) -> ToolResult:
        args = LogQLArgs.model_validate(args)
        params: dict[str, Any] = {"query": args.query, "limit": args.limit, "direction": "BACKWARD"}
        if args.start_ns is not None:
            params["start"] = args.start_ns
        if args.end_ns is not None:
            params["end"] = args.end_ns
        return self._result("logql", self.http_get(f"{self.loki_url}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"))

    def trace_search(self, args: TraceSearchArgs | dict[str, Any]) -> ToolResult:
        args = TraceSearchArgs.model_validate(args)
        params: dict[str, Any] = {"service": args.service, "limit": args.limit}
        if args.operation:
            params["operation"] = args.operation
        if args.tags:
            params["tags"] = json.dumps(args.tags, separators=(",", ":"))
        return self._result("trace_search", self.http_get(f"{self.jaeger_url}/api/traces?{urllib.parse.urlencode(params)}"))

    def kubectl(self, args: KubectlArgs | dict[str, Any]) -> ToolResult:
        args = KubectlArgs.model_validate(args)
        command = ["kubectl", args.verb, args.resource]
        if args.name:
            command.append(args.name)
        if args.namespace:
            command.extend(["--namespace", args.namespace])
        if args.selector:
            command.extend(["--selector", args.selector])
        if args.verb == "logs":
            command.extend(["--tail", str(args.tail)])
        command.extend(["--output", "json"] if args.verb == "get" else [])
        return self._result("kubectl", {"command": command, "output": self.command_runner(command)})

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec("promql", "Run a read-only instant PromQL query.", PromQLArgs, self.promql),
            ToolSpec("logql", "Search Loki logs with a bounded result count.", LogQLArgs, self.logql),
            ToolSpec("trace_search", "Search Jaeger traces by service, operation, and tags.", TraceSearchArgs, self.trace_search),
            ToolSpec("kubectl", "Run allowlisted read-only kubectl inspection commands.", KubectlArgs, self.kubectl),
        ]

    def to_langchain_tools(self) -> list[Any]:
        """Convert this toolset (including AgentJTools subclasses) into LangChain StructuredTools."""
        from langchain_core.tools import StructuredTool

        lc_tools: list[Any] = []
        for spec in self.specs():
            def _make_fn(s: ToolSpec):
                def _run(**kwargs: Any) -> str:
                    result = s.function(kwargs)
                    return json.dumps(result.model_dump(), default=str)
                return _run

            lc_tools.append(
                StructuredTool.from_function(
                    func=_make_fn(spec),
                    name=spec.name,
                    description=spec.description,
                    args_schema=spec.args_model,
                )
            )
        return lc_tools
