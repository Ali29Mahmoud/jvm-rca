import json

import pytest
from pydantic import ValidationError

from benchmark.agent_g import AgentDecision, AgentG, AgentGTools, KubectlArgs, OpenAICompatiblePolicy, ToolCall
from benchmark.harness import AgentGAdapter, Diagnosis, run


def test_generic_tools_publish_strict_schemas_and_compact_results():
    seen = []

    def http_get(url):
        seen.append(url)
        return {"status": "success", "data": [{"line": "x" * 100}, {"line": "y" * 100}]}

    def command(command):
        seen.append(command)
        return "pod-a\npod-b\npod-c\n" + "z" * 100

    tools = AgentGTools(http_get=http_get, command_runner=command, output_cap_chars=60, top_k=1)
    schemas = {spec.name: spec.json_schema for spec in tools.specs()}
    assert set(schemas) == {"promql", "logql", "trace_search", "kubectl"}
    assert schemas["promql"]["additionalProperties"] is False

    results = [
        tools.promql({"query": "up"}),
        tools.logql({"query": '{app="orders"}', "limit": 2}),
        tools.trace_search({"service": "order-service"}),
        tools.kubectl({"verb": "get", "resource": "pods", "namespace": "demo"}),
    ]
    assert all(len(result.summary) <= 60 for result in results)
    assert all(len(result.items) <= 1 for result in results)
    assert all(result.truncated for result in results)
    assert "/api/v1/query?query=up" in seen[0]
    assert "/loki/api/v1/query_range?" in seen[1]
    assert "/api/traces?service=order-service" in seen[2]
    assert seen[3] == ["kubectl", "get", "pods", "--namespace", "demo", "--output", "json"]


def test_kubectl_tool_rejects_write_verbs_before_execution():
    with pytest.raises(ValidationError):
        KubectlArgs.model_validate({"verb": "delete", "resource": "pod", "name": "x"})
    with pytest.raises(ValidationError):
        KubectlArgs.model_validate({"verb": "get", "resource": "--all-namespaces"})


def test_gemini_policy_disables_hidden_thinking_for_json_decisions(monkeypatch):
    monkeypatch.delenv("BENCH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BENCH_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("BENCH_LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    payloads = []

    def request(_url, _headers, payload, _timeout):
        payloads.append(payload)
        return {"choices": [{"message": {"content": '{"phase":"hypothesize"}'}}]}

    decision = OpenAICompatiblePolicy([], request_fn=request).decide({"step": 1})

    assert decision.phase == "hypothesize"
    assert payloads[0]["reasoning_effort"] == "none"


def test_policy_reports_empty_model_content_clearly(monkeypatch):
    monkeypatch.setenv("BENCH_LLM_API_KEY", "test-key")
    monkeypatch.setenv("BENCH_LLM_BASE_URL", "https://example.test/v1")

    policy = OpenAICompatiblePolicy(
        [], request_fn=lambda *_args: {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
    )

    with pytest.raises(RuntimeError, match="returned no decision content.*finish_reason='length'"):
        policy.decide({"step": 1})


class ScriptedPolicy:
    def __init__(self):
        self.decisions = iter([
            AgentDecision(phase="hypothesize", hypothesis="The target may be resource constrained."),
            AgentDecision(phase="gather", calls=[ToolCall(tool="promql", arguments={"query": "up"})]),
            AgentDecision(phase="verify", calls=[ToolCall(tool="kubectl", arguments={"verb": "get", "resource": "pods"})]),
            AgentDecision(phase="conclude", diagnosis={"category": "x", "culprit": "y", "evidence": [], "remediation": "z"}),
            AgentDecision(phase="conclude", diagnosis={
                "category": "x", "culprit": "y", "evidence": ["E1 confirms the symptom; E2 confirms the pod state."],
                "remediation": "z", "confidence": 0.6,
            }),
        ])

    def decide(self, _state):
        return next(self.decisions)


def test_agent_loop_has_explicit_phases_retries_invalid_output_and_cites_evidence():
    tools = AgentGTools(
        http_get=lambda _url: {"status": "success", "data": {"result": []}},
        command_runner=lambda _command: json.dumps({"items": []}),
    )
    run = AgentG(tools, ScriptedPolicy(), Diagnosis, max_steps=5).run({"alert": "service failing"})

    assert run.steps_used == 5
    assert run.invalid_diagnoses == 1
    assert run.diagnosis.evidence[0].startswith("E1")
    assert [entry["phase"] for entry in run.trace] == ["observe", "hypothesize", "gather", "verify", "conclude", "conclude"]


def test_agent_loop_stops_at_step_budget():
    class NeverConclude:
        def decide(self, _state):
            return AgentDecision(phase="gather", calls=[])

    agent = AgentG(AgentGTools(http_get=lambda _url: {}, command_runner=lambda _command: ""), NeverConclude(), Diagnosis, max_steps=2)
    with pytest.raises(RuntimeError, match=r"exhausted step budget \(2\)"):
        agent.run({"alert": "service failing"})


def test_agent_g_harness_run_persists_trace_and_budget(tmp_path):
    class Policy:
        def __init__(self):
            self.calls = 0

        def decide(self, _state):
            self.calls += 1
            if self.calls == 1:
                return AgentDecision(phase="hypothesize", hypothesis="The pod might be out of memory.")
            if self.calls == 2:
                return AgentDecision(phase="gather", calls=[ToolCall(tool="promql", arguments={"query": "up"})])
            if self.calls == 3:
                return AgentDecision(phase="verify", calls=[])
            return AgentDecision(phase="conclude", diagnosis={
                "category": "jvm_resource_exhaustion", "culprit": "order-service",
                "evidence": ["E1 observed a restart signal."], "remediation": "Increase memory limit.",
            })

    adapter = AgentGAdapter(
        tools=AgentGTools(http_get=lambda _url: {"status": "success", "data": {"result": []}}, command_runner=lambda _command: ""),
        policy=Policy(),
    )
    result = run("S01", "agent-g", tmp_path, agent_g=adapter)

    assert result.status == "completed"
    assert result.budgets_used == {"steps": 4, "max_steps": 25, "invalid_diagnoses": 0}
    assert '"trace"' in result.raw_agent_output
