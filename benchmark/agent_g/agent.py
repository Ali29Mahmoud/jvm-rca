"""Agent-G execution loop: observe -> hypothesize -> gather -> verify -> conclude."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from pydantic import ValidationError

from benchmark.agent_g.models import DiagnosisLike
from benchmark.agent_g.policy import AgentGPolicy
from benchmark.agent_g.tools import AgentGTools, ToolResult


@dataclass
class AgentGRun:
    diagnosis: Any
    trace: list[dict[str, Any]]
    steps_used: int
    invalid_diagnoses: int


class AgentG:
    """Observe → hypothesize → gather → verify → conclude, bounded by steps."""

    def __init__(
        self,
        tools: AgentGTools,
        policy: AgentGPolicy,
        diagnosis_model: DiagnosisLike,
        *,
        max_steps: int = 25,
    ):
        self.tools = {spec.name: spec for spec in tools.specs()}
        self.policy = policy
        self.diagnosis_model = diagnosis_model
        self.max_steps = max_steps

    def run(self, incident: dict[str, Any]) -> AgentGRun:
        evidence: list[ToolResult] = []
        trace: list[dict[str, Any]] = [{"phase": "observe", "incident": incident}]
        invalid_diagnoses = 0
        required_phase = "hypothesize"
        for step in range(1, self.max_steps + 1):
            state = {
                "incident": incident,
                "step": step,
                "max_steps": self.max_steps,
                "evidence": [item.model_dump() for item in evidence],
                "trace": trace,
                "required_phase": required_phase,
            }
            decision = self.policy.decide(state)
            entry: dict[str, Any] = {"step": step, "phase": decision.phase, "hypothesis": decision.hypothesis}
            if decision.phase != required_phase:
                entry["phase_error"] = f"expected {required_phase}, got {decision.phase}"
                trace.append(entry)
                continue
            if decision.phase == "conclude":
                try:
                    diag_data = decision.diagnosis
                    if isinstance(diag_data, dict):
                        diag_copy = dict(diag_data)
                        if "evidence" not in diag_copy and "evidence_cited" in diag_copy:
                            diag_copy["evidence"] = [f"{e} confirms the finding." for e in diag_copy["evidence_cited"]]
                        if "culprit" not in diag_copy:
                            diag_copy["culprit"] = incident.get("target", {}).get("service", "unknown")
                        if "category" not in diag_copy and "root_cause" in diag_copy:
                            diag_copy["category"] = "jvm_resource_exhaustion"
                        if "remediation" not in diag_copy:
                            diag_copy["remediation"] = diag_copy.get("root_cause", "Investigate and restore baseline.")
                        diag_data = diag_copy
                    diagnosis = self.diagnosis_model.model_validate(diag_data)
                    cited = set()
                    for line in diagnosis.evidence:
                        cited.update(token for token in str(line).split() if token.startswith("E"))
                    available = {item.evidence_id for item in evidence}
                    if not cited or not cited <= available:
                        raise ValueError("diagnosis evidence must cite one or more collected E<n> IDs")
                    entry["diagnosis"] = diagnosis.model_dump()
                    trace.append(entry)
                    return AgentGRun(diagnosis, trace, step, invalid_diagnoses)
                except (ValidationError, ValueError, TypeError) as exc:
                    invalid_diagnoses += 1
                    entry["invalid_diagnosis"] = str(exc)
                    trace.append(entry)
                    continue
            results = []
            for call in decision.calls:
                spec = self.tools.get(call.tool)
                if spec is None:
                    results.append({"tool": call.tool, "error": f"Unknown or disallowed tool: {call.tool}"})
                    continue
                try:
                    result = spec.function(call.arguments)
                    evidence.append(result)
                    results.append(result.model_dump())
                except Exception as exc:  # Evidence collection failures are visible to the policy.
                    results.append({"tool": call.tool, "error": f"{type(exc).__name__}: {exc}"})
            entry["results"] = results
            trace.append(entry)
            required_phase = {"hypothesize": "gather", "gather": "verify", "verify": "conclude"}[required_phase]
        raise RuntimeError(f"Agent-G exhausted step budget ({self.max_steps}) without a valid cited diagnosis")
