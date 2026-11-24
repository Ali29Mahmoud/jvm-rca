"""Small, local-friendly benchmark harness for incident scenarios.

Refactored modular orchestrator delegating to specialized benchmark submodules.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import duckdb

from benchmark.adapters import (
    AgentGAdapter,
    ControlAgent,
    ControlAgentError,
    DummyAgent,
    _post_chat_completion,
)
from benchmark.cluster import (
    PrometheusQueryError,
    ResetError,
    SymptomTimeoutError,
    find_scenario,
    inject_fault,
    query_prometheus,
    reset,
    wait_for_baseline,
    wait_for_symptom,
    _matches,
)
from benchmark.models import (
    Diagnosis,
    RunResult,
    Scenario,
    StrictModel,
)
from benchmark.scoring import append_spot_check, score_diagnosis
from benchmark.storage import store_result

ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS = ROOT / "results"


def run(
    scenario_id: str,
    agent_name: str,
    results_dir: Path = DEFAULT_RESULTS,
    *,
    real_reset: bool = False,
    check_symptom: bool = False,
    control_agent: ControlAgent | None = None,
    agent_g: AgentGAdapter | None = None,
    evidence_judge=None,
) -> RunResult:
    scenario = Scenario.from_yaml(find_scenario(scenario_id))
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    result = RunResult(
        run_id=run_id,
        scenario_id=scenario.id,
        agent_name=agent_name,
        started_at=started_at,
        finished_at=started_at,
        status="error",
    )
    results_dir = Path(results_dir)
    try:
        reset(scenario, real=real_reset)
        inject_fault(scenario, real=False)
        if check_symptom:
            wait_for_symptom(scenario)
        if agent_name == "dummy":
            agent = DummyAgent()
        elif agent_name == "control":
            agent = control_agent or ControlAgent()
        elif agent_name == "agent-g":
            agent = agent_g or AgentGAdapter()
        else:
            raise ValueError(f"Unknown agent {agent_name!r}; available agents: dummy, control, agent-g")
        diagnosis, raw = agent.run(scenario)
        result.diagnosis = diagnosis
        result.raw_agent_output = raw
        if isinstance(agent, AgentGAdapter) and agent.last_run:
            result.budgets_used = {
                "steps": agent.last_run.steps_used,
                "max_steps": int(scenario.budgets.get("max_steps", 25)),
                "invalid_diagnoses": agent.last_run.invalid_diagnoses,
            }
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
    run_parser.add_argument(
        "--hide-raw",
        action="store_true",
        default=os.getenv("BENCH_HIDE_RAW", "").lower() in ("1", "true", "yes"),
        help="hide raw_agent_output from the printed JSON output",
    )
    args = parser.parse_args(argv)
    result = run(
        args.scenario,
        args.agent,
        args.results_dir,
        real_reset=args.real_reset,
        check_symptom=args.check_symptom,
    )
    exclude = {"raw_agent_output"} if args.hide_raw else None
    print(result.model_dump_json(indent=2, exclude=exclude))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
