"""Strict base model and data schemas for Agent-G."""

from __future__ import annotations

from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolCall(StrictModel):
    model_config = ConfigDict(extra="allow")
    tool: Literal[
        "promql",
        "logql",
        "trace_search",
        "kubectl",
        "thread_dump",
        "heap_histogram",
        "gc_log",
        "hikari_summary",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _extract_arguments(cls, data: Any) -> Any:
        if isinstance(data, dict):
            known = {"tool", "arguments"}
            extras = {k: v for k, v in data.items() if k not in known}
            if extras:
                args = data.get("arguments") or {}
                if isinstance(args, dict):
                    merged = dict(args)
                    for k, v in extras.items():
                        if k not in merged and v is not None:
                            merged[k] = v
                    data["arguments"] = merged
        return data


class AgentDecision(StrictModel):
    model_config = ConfigDict(extra="allow")
    phase: Literal["hypothesize", "gather", "verify", "conclude"]
    hypothesis: str | None = None
    calls: list[ToolCall] = Field(default_factory=list, max_length=10)
    diagnosis: dict[str, Any] | None = None
    planned_actions: list[Any] | None = None


class DiagnosisLike(Protocol):
    @classmethod
    def model_validate(cls, obj: Any) -> Any: ...
