import json
from pathlib import Path

import duckdb
import pytest
from benchmark.harness import Scenario, SymptomTimeoutError, find_scenario, run, wait_for_symptom


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
    result_path = tmp_path / result.scenario_id / f"{result.run_id}.json"
    assert json.loads(result_path.read_text())["agent_name"] == "dummy"

    with duckdb.connect(str(tmp_path / "runs.duckdb"), read_only=True) as connection:
        row = connection.execute("SELECT scenario_id, agent_name, status FROM runs").fetchone()
    assert row == (result.scenario_id, "dummy", "completed")


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
