import json
from pathlib import Path

import duckdb
import pytest
from benchmark.harness import (
    ControlAgent,
    Diagnosis,
    Scenario,
    SymptomTimeoutError,
    find_scenario,
    run,
    wait_for_symptom,
)
from benchmark.scoring import score_diagnosis, should_manually_spot_check


def test_every_scenario_yaml_loads():
    for path in (Path(__file__).resolve().parents[1] / "benchmark" / "scenarios").rglob("*.yaml"):
        if path.name.startswith("_"):
            continue
        Scenario.from_yaml(path)


def test_malformed_scenario_yaml_is_rejected(tmp_path):
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("id: broken\nname: Broken\nunknown_field: true\n")
    with pytest.raises(ValueError):
        Scenario.from_yaml(malformed)


def test_s01_dummy_run_persists_json_and_duckdb(tmp_path):
    result = run("S01", "dummy", tmp_path)

    assert result.status == "completed"
    assert result.score is not None
    result_path = tmp_path / result.scenario_id / f"{result.run_id}.json"
    stored = json.loads(result_path.read_text())
    assert stored["agent_name"] == "dummy"
    assert stored["score"]["verdict"] in {"correct", "partial", "incorrect"}

    with duckdb.connect(str(tmp_path / "runs.duckdb"), read_only=True) as connection:
        row = connection.execute("SELECT scenario_id, agent_name, status, score FROM runs").fetchone()
    assert row[:3] == (result.scenario_id, "dummy", "completed")
    assert json.loads(row[3])["verdict"] == stored["score"]["verdict"]


def test_control_agent_returns_valid_s01_diagnosis_with_one_toolless_call(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_LLM_API_KEY", "test-key")
    scenario = Scenario.from_yaml(find_scenario("S01"))
    reply = Diagnosis(
        category="jvm_resource_exhaustion",
        culprit="order-service",
        evidence=["The order-service memory limit is below the JVM working set."],
        remediation="Restore the order-service memory limit to at least 1024Mi.",
        confidence=0.8,
    )
    calls = []

    def request(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return {"choices": [{"message": {"content": reply.model_dump_json()}}]}

    agent = ControlAgent(request_fn=request)
    result = run("S01", "control", tmp_path, control_agent=agent)

    assert result.status == "completed"
    assert result.diagnosis == reply
    assert result.score is not None
    assert len(calls) == 1
    url, headers, payload, timeout = calls[0]
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer test-key"
    assert timeout == 60
    assert "tools" not in payload
    assert "S01-order-service-memory-limit-lowered" in payload["messages"][1]["content"]


def test_control_agent_uses_gemini_openai_compatible_defaults(monkeypatch):
    monkeypatch.delenv("BENCH_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("BENCH_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("BENCH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    observed = []

    def request(url, headers, payload, timeout):
        observed.append((url, headers, payload))
        return {"choices": [{"message": {"content": '{"category":"x","culprit":"y","evidence":[],"remediation":"z"}'}}]}

    scenario = Scenario.from_yaml(find_scenario("S01"))
    ControlAgent(request_fn=request).run(scenario)

    assert len(observed) == 1
    url, headers, payload = observed[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert headers["Authorization"] == "Bearer fake-gemini-key"
    assert payload["model"] == "gemini-3.8-flash"
    assert "tools" not in payload


def test_symptom_check_polls_until_threshold_matches():
    scenario = Scenario.from_yaml(find_scenario("S01"))
    scenario.symptom_check["wait"] = {
        "initial_delay_seconds": 0,
        "interval_seconds": 0.001,
        "timeout_seconds": 0.1,
    }
    observed = iter([0.0, 0.0, 1.0])

    value = wait_for_symptom(scenario, query_fn=lambda _query: next(observed))

    assert value == 1.0


def test_symptom_check_timeout_reports_query_value_and_threshold():
    scenario = Scenario.from_yaml(find_scenario("S01"))
    scenario.symptom_check["wait"] = {
        "initial_delay_seconds": 0,
        "interval_seconds": 0.001,
        "timeout_seconds": 0.01,
    }

    with pytest.raises(SymptomTimeoutError) as exc_info:
        wait_for_symptom(scenario, query_fn=lambda _query: 0.0)

    message = str(exc_info.value)
    assert "timed out" in message
    assert scenario.symptom_check["promql"] in message
    assert "last_value=0" in message
    assert "value >= 1" in message


def _all_strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _all_strings(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _all_strings(nested)]
    return []


@pytest.fixture
def s01_ground_truth():
    return Scenario.from_yaml(find_scenario("S01")).ground_truth


@pytest.fixture
def diagnosis_cases(s01_ground_truth):
    return {
        "right": Diagnosis(
            category=s01_ground_truth["category"],
            culprit=s01_ground_truth["culprit"]["service"],
            evidence=_all_strings(s01_ground_truth["expected_evidence"]),
            remediation=" ".join(_all_strings(s01_ground_truth["remediation"])),
        ),
        "wrong": Diagnosis(
            category="database_corruption",
            culprit="postgres",
            evidence=["The database has a query problem."],
            remediation="Restart PostgreSQL and rebuild its indexes.",
        ),
        "partial": Diagnosis(
            category=s01_ground_truth["category"],
            culprit="api-gateway-service",
            evidence=["container_memory_working_set_bytes reached container_spec_memory_limit_bytes"],
            remediation="Increase order-service container memory limit to 1024Mi.",
        ),
    }


@pytest.mark.parametrize(
    ("case", "expected_verdict"),
    [("right", "correct"), ("wrong", "incorrect"), ("partial", "partial")],
)
def test_diagnosis_scoring_fixtures(s01_ground_truth, diagnosis_cases, case, expected_verdict):
    score = score_diagnosis(diagnosis_cases[case], s01_ground_truth, f"fixture-{case}")

    assert score.verdict == expected_verdict
    assert 0 <= score.total <= 1
    assert score.category in (0, 1)
    assert score.culprit in (0, 1)
    assert 0 <= score.evidence_keyword <= 1
    assert 0 <= score.remediation <= 1


def test_optional_evidence_judge_receives_committed_prompt(s01_ground_truth, diagnosis_cases):
    observed = {}

    def judge(prompt, diagnosis, expected):
        observed.update(prompt=prompt, diagnosis=diagnosis, expected=expected)
        return 0.8

    prompt = (Path(__file__).resolve().parents[1] / "benchmark/prompts/evidence-judge.txt").read_text()
    score = score_diagnosis(
        diagnosis_cases["right"],
        s01_ground_truth,
        "judge-fixture",
        evidence_judge=judge,
        judge_prompt=prompt,
    )

    assert score.evidence_judge == 0.8
    assert score.evidence == pytest.approx(0.94)
    assert observed["prompt"] == prompt
    assert observed["diagnosis"]["category"] == s01_ground_truth["category"]
    assert observed["expected"]


def test_manual_spot_check_sample_is_about_twenty_percent():
    selected = sum(should_manually_spot_check(f"run-{index}") for index in range(100))
    assert 15 <= selected <= 25
