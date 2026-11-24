"""Adapters for agents evaluated in the benchmark harness."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from benchmark.agent_g import AgentG, AgentGRun, AgentGTools, OpenAICompatiblePolicy
from benchmark.models import Diagnosis, Scenario


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
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        model = (
            os.environ.get("BENCH_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or ("openrouter/free" if openrouter_key else "gemini-3.8-flash" if gemini_key else "gpt-4o-mini")
        )
        base_url = (
            os.environ.get("BENCH_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or (
                "https://openrouter.ai/api/v1"
                if openrouter_key
                else "https://generativelanguage.googleapis.com/v1beta/openai"
                if gemini_key
                else "https://api.openai.com/v1"
            )
        ).rstrip("/")
        api_key = (
            os.environ.get("BENCH_LLM_API_KEY")
            or openrouter_key
            or gemini_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        if not api_key:
            raise ControlAgentError(
                "Set BENCH_LLM_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY "
                "to run the control agent"
            )
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
            if isinstance(content, dict):
                content = json.dumps(content)
            if not isinstance(content, str):
                raise TypeError("assistant message content must be a string")
            diagnosis = Diagnosis.model_validate_json(content)
        except Exception as exc:
            raise ControlAgentError(f"Control agent failed to produce a valid diagnosis: {exc}") from exc
        return diagnosis, content


class AgentGAdapter:
    """Harness adapter that preserves Agent-G's full, auditable loop trace."""

    def __init__(self, tools: AgentGTools | None = None, policy=None):
        tools = tools or AgentGTools()
        self.tools = tools
        self.policy = policy or OpenAICompatiblePolicy(tools.specs())
        self.last_run: AgentGRun | None = None

    def run(self, scenario: Scenario) -> tuple[Diagnosis, str]:
        incident = {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "alert": scenario.agent_input.get("prompt", ""),
            "target": scenario.target,
            "symptom": scenario.symptom_check,
        }
        max_steps = int(scenario.budgets.get("max_steps", 25))
        self.last_run = AgentG(self.tools, self.policy, Diagnosis, max_steps=max_steps).run(incident)
        return self.last_run.diagnosis, json.dumps({"trace": self.last_run.trace}, indent=2)


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
