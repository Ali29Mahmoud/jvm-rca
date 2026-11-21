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

from benchmark.scoring import EvidenceJudge, ScoreResult, append_spot_check, score_diagnosis


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
        # Map the established scenario YAML structure into the runner model.
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
    score: ScoreResult | None = None
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


class ControlAgentError(RuntimeError):
    """The one-call control agent could not return a valid diagnosis."""


class ControlAgent:
    """Single-call, no-tools agent using an OpenAI-compatible chat endpoint."""

    def __init__(self, request_fn=None):
        self.request_fn = request_fn or _post_chat_completion

    @staticmethod
    def build_prompt(scenario: Scenario) -> str:
        target = scenario.target
        incident_prompt = scenario.agent_input.get("prompt", "")
        symptom = scenario.symptom_check
        return f"""You are a control agent in an incident diagnosis benchmark.
Diagnose the incident from the supplied scenario context. You have no tools and
must not claim that you queried metrics, logs, traces, Kubernetes, or databases.
Use only the context below. Return one JSON object matching the supplied schema.

Scenario: {scenario.id} — {scenario.name}
Target service: {target.get('service', 'unspecified')}
Target component: {target.get('component', 'unspecified')}
Incident description:
{scenario.description}

Alert context:
{incident_prompt}

Symptom description:
{symptom.get('description', '')}
PromQL definition (query only; no observed value is provided):
{symptom.get('promql', '')}

Diagnosis JSON schema:
{json.dumps(Diagnosis.model_json_schema(), separators=(',', ':'))}

Respond with JSON fields category (string), culprit (string), evidence (array
of strings), remediation (string), and optional confidence (number from 0 to 1).
Do not include markdown fences or fields outside the schema."""

    def run(self, scenario: Scenario) -> tuple[Diagnosis, str]:
        prompt = self.build_prompt(scenario)
        gemini_key = os.environ.get("GEMINI_API_KEY")
        model = (
            os.environ.get("BENCH_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or ("gemini-3.8-flash" if gemini_key else "gpt-4o-mini")
        )
        base_url = (
            os.environ.get("BENCH_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or (
                "https://generativelanguage.googleapis.com/v1beta/openai"
                if gemini_key
                else "https://api.openai.com/v1"
            )
        ).rstrip("/")
        api_key = (
            os.environ.get("BENCH_LLM_API_KEY")
            or gemini_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        if not api_key:
            raise ControlAgentError("Set BENCH_LLM_API_KEY or OPENAI_API_KEY to run the control agent")
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return only a diagnosis JSON object. No tools are available."},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            response = self.request_fn(
                f"{base_url}/chat/completions",
                {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                payload,
                60,
            )
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("assistant message content must be a string")
            diagnosis = Diagnosis.model_validate_json(content)
        except Exception as exc:
            raise ControlAgentError(f"Control agent failed to produce a valid diagnosis: {exc}") from exc
        return diagnosis, content


def _post_chat_completion(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ControlAgentError(f"LLM request failed: {exc}") from exc


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


class PrometheusQueryError(RuntimeError):
    """Prometheus could not execute a PromQL query."""


class SymptomTimeoutError(TimeoutError):
    """The scenario symptom did not reach its configured condition in time."""


def query_prometheus(promql: str, prometheus_url: str | None = None) -> float | None:
    """Run an instant PromQL query; return the maximum sample or None for an empty vector."""
    base_url = (prometheus_url or os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")).rstrip("/")
    url = f"{base_url}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise PrometheusQueryError(f"Prometheus query failed ({promql!r}): {exc}") from exc
    if payload.get("status") != "success":
        raise PrometheusQueryError(f"Prometheus rejected query {promql!r}: {payload.get('error', payload)}")
    values = []
    for item in payload.get("data", {}).get("result", []):
        try:
            values.append(float(item["value"][1]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    if not values:
        if not payload.get("data", {}).get("result"):
            return None
        raise PrometheusQueryError(f"Prometheus returned no numeric samples: {promql!r}")
    return max(values)


def _matches(value: float, operator: str, threshold: float) -> bool:
    comparison = {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
        "!=": value != threshold,
    }.get(operator)
    if comparison is None:
        raise ValueError(f"Unsupported comparison operator {operator!r}; use one of >, >=, <, <=, ==, !=")
    return comparison


def wait_for_symptom(
    scenario: Scenario,
    query_fn=query_prometheus,
    sleep_fn=time.sleep,
) -> float:
    """Poll Prometheus until the scenario's symptom condition passes or times out."""
    symptom = scenario.symptom_check
    promql = str(symptom.get("promql", "")).strip()
    operator = str(symptom.get("operator", ">="))
    threshold = float(symptom.get("threshold", 0))
    wait = symptom.get("wait", {})
    initial_delay = max(0.0, float(wait.get("initial_delay_seconds", 0)))
    interval = float(wait.get("interval_seconds", 5))
    timeout = float(wait.get("timeout_seconds", 120))
    if not promql:
        raise ValueError(f"Scenario {scenario.id} symptom_check has an empty PromQL query")
    if interval <= 0 or timeout <= 0:
        raise ValueError(f"Scenario {scenario.id} symptom_check interval and timeout must be positive")
    # Validate the operator before spending time polling.
    _matches(0.0, operator, threshold)

    start = time.monotonic()
    deadline = start + timeout
    if initial_delay:
        sleep_fn(min(initial_delay, timeout))
    last_value: float | None = None
    last_error = "no sample received"
    while time.monotonic() < deadline:
        try:
            last_value = query_fn(promql)
            if last_value is None:
                last_error = "Prometheus returned an empty result"
            elif _matches(last_value, operator, threshold):
                return last_value
            else:
                last_error = f"last value {last_value:g}"
        except PrometheusQueryError as exc:
            last_error = str(exc)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            sleep_fn(min(interval, remaining))

    elapsed = time.monotonic() - start
    shown_value = "none" if last_value is None else f"{last_value:g}"
    raise SymptomTimeoutError(
        f"Symptom check timed out after {elapsed:.1f}s for scenario {scenario.id}: "
        f"query={promql!r}, last_value={shown_value}, condition value {operator} {threshold:g}; {last_error}"
    )


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
            if value is not None and _matches(value, operator, threshold):
                return
        except PrometheusQueryError as exc:
            last_error = str(exc)
        else:
            if value is None:
                last_error = "Prometheus returned an empty result"
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
                score JSON,
                budgets_used JSON,
                raw_agent_output VARCHAR,
                errors JSON
            )
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info('runs')").fetchall()}
        if "score" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN score JSON")
        connection.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, scenario_id, agent_name, started_at, finished_at, status,
                diagnosis, score, budgets_used, raw_agent_output, errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            result.run_id, result.scenario_id, result.agent_name,
            result.started_at.replace(tzinfo=None), result.finished_at.replace(tzinfo=None),
            result.status,
            result.diagnosis.model_dump_json() if result.diagnosis else None,
            result.score.model_dump_json() if result.score else None,
            json.dumps(result.budgets_used), result.raw_agent_output, json.dumps(result.errors),
        ])
    return path


def run(
    scenario_id: str,
    agent_name: str,
    results_dir: Path = DEFAULT_RESULTS,
    *,
    real_reset: bool = False,
    check_symptom: bool = False,
    evidence_judge: EvidenceJudge | None = None,
    control_agent: ControlAgent | None = None,
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
        if check_symptom:
            wait_for_symptom(scenario)
        if agent_name == "dummy":
            agent = DummyAgent()
        elif agent_name == "control":
            agent = control_agent or ControlAgent()
        else:
            raise ValueError(f"Unknown agent {agent_name!r}; available agents: dummy, control")
        diagnosis, raw = agent.run(scenario)
        result.diagnosis = diagnosis
        result.raw_agent_output = raw
        prompt_path = ROOT / "prompts" / "evidence-judge.txt"
        judge_prompt = prompt_path.read_text() if prompt_path.exists() else ""
        result.score = score_diagnosis(
            diagnosis,
            scenario.ground_truth,
            run_id,
            evidence_judge=evidence_judge,
            judge_prompt=judge_prompt,
        )
        append_spot_check(
            results_dir / "manual-spot-checks.md",
            run_id,
            scenario.id,
            result.score.verdict,
            result.score.total,
        )
        result.status = "completed"
    except Exception as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}")
        if isinstance(exc, SymptomTimeoutError):
            result.status = "timeout"
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
    run_parser.add_argument("--check-symptom", action="store_true", help="poll Prometheus for the scenario symptom (requires live infrastructure)")
    args = parser.parse_args(argv)
    # Keep the default dummy workflow safe for local plumbing checks.
    result = run(
        args.scenario,
        args.agent,
        args.results_dir,
        real_reset=args.real_reset,
        check_symptom=args.check_symptom,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
