"""Cluster verification, Prometheus polling, baseline reset, and scenario lookup."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import yaml

from benchmark.models import Scenario

ROOT = Path(__file__).resolve().parent


class ResetError(RuntimeError):
    """Reset could not restore or verify the baseline environment."""


class PrometheusQueryError(RuntimeError):
    """Prometheus could not execute a PromQL query."""


class SymptomTimeoutError(TimeoutError):
    """The scenario symptom did not reach its configured condition in time."""


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
    """Restore the clean application baseline when explicitly enabled."""
    if not real:
        return
    reset_script = ROOT.parent / "scripts" / "reset-dev-env.sh"
    if reset_script.is_file():
        subprocess.run(["bash", str(reset_script)], check=True, text=True, capture_output=True)
    wait_for_baseline(scenario, query_fn=query_fn)


def inject_fault(scenario: Scenario, *, real: bool = False) -> None:
    """Local harness injection stub; avoids mutating a cluster in dummy runs."""
