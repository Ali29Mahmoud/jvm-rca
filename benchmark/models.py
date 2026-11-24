"""Data models for benchmark scenarios, diagnoses, and run results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Diagnosis(StrictModel):
    category: str
    culprit: str
    evidence: list[str] = Field(default_factory=list)
    remediation: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class Scenario(StrictModel):
    id: str
    name: str
    description: str
    inject: dict[str, Any]
    symptom_check: dict[str, Any]
    ground_truth: dict[str, Any]
    target: dict[str, Any] = Field(default_factory=dict)
    agent_input: dict[str, Any] = Field(default_factory=dict)
    cleanup: dict[str, Any] = Field(default_factory=dict)
    budgets: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "Scenario":
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"Scenario YAML {path} must contain a mapping")
        allowed = {"id", "name", "description", "inject", "symptom_check", "ground_truth", "budgets"}
        allowed.update({"version", "category", "tier", "target", "tags", "agent_input", "cleanup", "verification"})
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Scenario YAML {path} has unknown fields: {', '.join(sorted(unknown))}")
        data = {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "description": raw.get("description", ""),
            "inject": raw.get("inject", {}),
            "symptom_check": raw.get("symptom_check", {}),
            "ground_truth": raw.get("ground_truth", {}),
            "target": raw.get("target", {}),
            "agent_input": raw.get("agent_input", {}),
            "cleanup": raw.get("cleanup", {}),
            "budgets": raw.get("agent_input", {}).get("budgets", {}),
        }
        return cls.model_validate(data)


class RunResult(StrictModel):
    run_id: str
    scenario_id: str
    agent_name: str
    started_at: datetime
    finished_at: datetime
    status: Literal["completed", "timeout", "budget_exceeded", "error"]
    diagnosis: Diagnosis | None = None
    score: Any | None = None
    budgets_used: dict[str, int] = Field(default_factory=dict)
    raw_agent_output: str | None = None
    errors: list[str] = Field(default_factory=list)
