"""Small, local-friendly benchmark harness for incident scenarios."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS = ROOT / "results"


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
        # Map the established scenario YAML structure into the runner model.
        data = {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "description": raw.get("description", ""),
            "inject": raw.get("inject", {}),
            "symptom_check": raw.get("symptom_check", {}),
            "ground_truth": raw.get("ground_truth", {}),
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
    budgets_used: dict[str, int] = Field(default_factory=dict)
    raw_agent_output: str | None = None
    errors: list[str] = Field(default_factory=list)


class DummyAgent:
    def run(self, scenario: Scenario) -> tuple[Diagnosis, str]:
        truth = scenario.ground_truth
        culprit = truth.get("culprit", {})
        culprit_name = culprit.get("service", "unknown") if isinstance(culprit, dict) else str(culprit)
        diagnosis = Diagnosis(
            category=str(truth.get("category", "unknown")),
            culprit=culprit_name,
            evidence=["Dummy agent uses scenario ground truth."],
            remediation=str(truth.get("remediation", {}).get("summary", "Investigate and restore the service baseline.")),
            confidence=1.0,
        )
        return diagnosis, diagnosis.model_dump_json()


def find_scenario(scenario_id: str) -> Path:
    paths = [p for p in (ROOT / "scenarios").rglob("*.yaml") if not p.name.startswith("_")]
    for path in paths:
        data = yaml.safe_load(path.read_text())
        scenario_code = path.stem.split("-", 1)[0]
        if (
            str(data.get("id", "")).lower() == scenario_id.lower()
            or path.stem.lower() == scenario_id.lower()
            or scenario_code.lower() == scenario_id.lower()
        ):
            return path
    raise FileNotFoundError(f"Unknown scenario {scenario_id!r}; searched {ROOT / 'scenarios'}")


class ResetError(RuntimeError):
    """Reset could not restore or verify the baseline environment."""


def query_prometheus(promql: str, prometheus_url: str | None = None) -> float:
    """Run an instant PromQL query and return the maximum numeric sample."""
    base_url = (prometheus_url or os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")).rstrip("/")
    url = f"{base_url}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ResetError(f"Prometheus baseline query failed ({promql!r}): {exc}") from exc
    if payload.get("status") != "success":
        raise ResetError(f"Prometheus rejected baseline query {promql!r}: {payload.get('error', payload)}")
    values = []
    for item in payload.get("data", {}).get("result", []):
        try:
            values.append(float(item["value"][1]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    if not values:
        raise ResetError(f"Prometheus baseline query returned no numeric samples: {promql!r}")
    return max(values)


def _matches(value: float, operator: str, threshold: float) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
        "!=": value != threshold,
    }.get(operator, False)


def wait_for_baseline(scenario: Scenario, query_fn=query_prometheus) -> None:
    verification = scenario.cleanup.get("baseline_verification")
    if not verification:
        raise ResetError(f"Scenario {scenario.id} has no cleanup.baseline_verification check")
    promql = verification.get("promql", "").strip()
    operator = verification.get("operator", "==")
    threshold = float(verification.get("threshold", 0))
    timeout = float(verification.get("timeout_seconds", 120))
    interval = float(verification.get("interval_seconds", 2))
    if not promql:
        raise ResetError(f"Scenario {scenario.id} baseline verification has an empty PromQL query")
    start = time.monotonic()
    last_error = "no sample received"
    while time.monotonic() - start < timeout:
        try:
            value = query_fn(promql)
            last_error = f"last value {value:g}"
            if _matches(value, operator, threshold):
                return
        except ResetError as exc:
            last_error = str(exc)
        time.sleep(min(interval, max(0, timeout - (time.monotonic() - start))))
    elapsed = time.monotonic() - start
    raise ResetError(
        f"Baseline health check timed out after {elapsed:.1f}s: query={promql!r}, "
        f"condition value {operator} {threshold:g}; {last_error}"
    )


def reset(scenario: Scenario, *, real: bool = False, query_fn=query_prometheus) -> None:
    """Restore the clean application baseline when explicitly enabled.

    The repository's reset script truncates application state (the established
    empty baseline), resets Kafka by restarting its broker, and resets
    pg_stat_statements. Set ``real=True`` to mutate the configured cluster.
    """
    if not real:
        return
    script = Path(__file__).resolve().parents[1] / "scripts" / "reset-environment.sh"
    try:
        subprocess.run(["bash", str(script)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ResetError(f"Environment reset failed: {exc}") from exc
    wait_for_baseline(scenario, query_fn=query_fn)


def inject_fault(_scenario: Scenario) -> None:
    """Local harness injection stub; avoids mutating a cluster in dummy runs."""


def wait_for_symptom(_scenario: Scenario) -> None:
    """Local harness symptom stub; dummy runs don't require live Prometheus."""


def store_result(result: RunResult, results_dir: Path) -> Path:
    path = results_dir / result.scenario_id / f"{result.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n")
    db_path = results_dir / "runs.duckdb"
    with duckdb.connect(str(db_path)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR,
                agent_name VARCHAR,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                status VARCHAR,
                diagnosis JSON,
                budgets_used JSON,
                raw_agent_output VARCHAR,
                errors JSON
            )
        """)
        connection.execute("""
            INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            result.run_id, result.scenario_id, result.agent_name,
            result.started_at.replace(tzinfo=None), result.finished_at.replace(tzinfo=None),
            result.status,
            result.diagnosis.model_dump_json() if result.diagnosis else None,
            json.dumps(result.budgets_used), result.raw_agent_output, json.dumps(result.errors),
        ])
    return path


def run(
    scenario_id: str,
    agent_name: str,
    results_dir: Path = DEFAULT_RESULTS,
    *,
    real_reset: bool = False,
) -> RunResult:
    scenario = Scenario.from_yaml(find_scenario(scenario_id))
    started = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    result = RunResult(
        run_id=run_id, scenario_id=scenario.id, agent_name=agent_name,
        started_at=started, finished_at=started, status="error",
    )
    try:
        reset(scenario, real=real_reset)
        inject_fault(scenario)
        wait_for_symptom(scenario)
        if agent_name != "dummy":
            raise ValueError(f"Unknown agent {agent_name!r}; available agents: dummy")
        diagnosis, raw = DummyAgent().run(scenario)
        result.diagnosis = diagnosis
        result.raw_agent_output = raw
        result.status = "completed"
    except Exception as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        result.finished_at = datetime.now(timezone.utc)
        store_result(result, results_dir)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench", description="Run incident-agent benchmark scenarios")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run a scenario with an agent")
    run_parser.add_argument("--scenario", required=True)
    run_parser.add_argument("--agent", required=True)
    run_parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    run_parser.add_argument("--real-reset", action="store_true", help="reset the Kubernetes benchmark environment and verify baseline health")
    args = parser.parse_args(argv)
    # Keep the default dummy workflow safe for local plumbing checks.
    result = run(args.scenario, args.agent, args.results_dir, real_reset=args.real_reset)
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
