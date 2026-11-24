"""LLM interaction policy, prompt templates, and response parsing for Agent-G."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from benchmark.agent_g.models import AgentDecision
from benchmark.agent_g.tools import ToolSpec


class AgentGPolicy(Protocol):
    def decide(self, state: dict[str, Any]) -> AgentDecision: ...


class OpenAICompatiblePolicy:
    """Policy adapter for an OpenAI-compatible endpoint.

    Each call returns one strictly validated loop decision. The model never gets
    shell access: its only possible actions are the schemas advertised below.
    """

    def __init__(
        self,
        tool_specs: list[ToolSpec],
        request_fn: Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]] | None = None,
    ):
        self.tool_specs = tool_specs
        self.request_fn = request_fn or self._post
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key and not os.getenv("BENCH_LLM_API_KEY") and not os.getenv("OPENAI_API_KEY"):
            # Automatically fetch from cluster secret if available
            try:
                out = subprocess.run(
                    ["kubectl", "-n", "eventuate-tram-examples-customers-and-orders", "get", "secret", "holmes-gemini-secret", "-o", "jsonpath={.data.api-key}"],
                    capture_output=True, text=True, timeout=5,
                )
                if out.returncode == 0 and out.stdout.strip():
                    import base64
                    gemini_key = base64.b64decode(out.stdout.strip()).decode()
            except Exception:
                pass
        self.api_key = os.getenv("BENCH_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or gemini_key
        self.base_url = (os.getenv("BENCH_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or (
            "https://generativelanguage.googleapis.com/v1beta/openai" if gemini_key else "https://api.openai.com/v1"
        )).rstrip("/")
        self.model = os.getenv("BENCH_LLM_MODEL") or os.getenv("OPENAI_MODEL") or (
            "gemini-3.1-flash-lite" if gemini_key else "gpt-4o-mini"
        )
        # Gemini's OpenAI-compatible endpoint can spend its complete output
        # budget on hidden thinking and return a message with null content.
        # Agent-G needs the visible, machine-readable decision each turn.
        self.reasoning_effort = os.getenv("BENCH_LLM_REASONING_EFFORT")
        if self.reasoning_effort is None and ("generativelanguage.googleapis.com" in self.base_url or "gemini" in self.model):
            self.reasoning_effort = "none"

        # Fallback configuration (e.g. OpenRouter if Gemini fails)
        self.fallback_api_key = os.getenv("BENCH_LLM_FALLBACK_API_KEY")
        self.fallback_base_url = os.getenv("BENCH_LLM_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.fallback_model = os.getenv("BENCH_LLM_FALLBACK_MODEL", "google/gemini-2.5-flash")
        if not self.fallback_api_key and "generativelanguage.googleapis.com" in self.base_url:
            try:
                out = subprocess.run(
                    ["kubectl", "-n", "eventuate-tram-examples-customers-and-orders", "get", "secret", "openrouter-key", "-o", "jsonpath={.data.OPENROUTER_API_KEY}"],
                    capture_output=True, text=True, timeout=5,
                )
                if out.returncode == 0 and out.stdout.strip():
                    import base64
                    self.fallback_api_key = base64.b64decode(out.stdout.strip()).decode()
            except Exception:
                pass

        if not self.api_key and not self.fallback_api_key:
            raise RuntimeError("Set BENCH_LLM_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY to run Agent-G")

    @staticmethod
    def _post(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        for attempt in range(5):
            request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read())
            except (urllib.error.HTTPError, TimeoutError, OSError) as exc:
                is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
                is_retryable_http = isinstance(exc, urllib.error.HTTPError) and exc.code in (429, 500, 502, 503, 504)
                if (is_timeout or is_retryable_http) and attempt < 4:
                    retry_after = getattr(exc, "headers", {}).get("Retry-After") if hasattr(exc, "headers") else None
                    sleep_time = float(retry_after) if retry_after and retry_after.isdigit() else (5 * (attempt + 1))
                    time.sleep(sleep_time)
                    continue
                raise

    def decide(self, state: dict[str, Any]) -> AgentDecision:
        tool_contract = [
            {"name": spec.name, "description": spec.description, "arguments_schema": spec.json_schema}
            for spec in self.tool_specs
        ]
        required_phase = state.get("required_phase", "hypothesize")
        available_eids = [item.get("evidence_id") for item in state.get("evidence", []) if "evidence_id" in item]

        prompt = (
            f"You are Agent-G, a bounded read-only incident investigator.\n"
            f"CURRENT REQUIRED PHASE: '{required_phase}'. You MUST return JSON with \"phase\": \"{required_phase}\".\n\n"
            f"Return ONLY a flat JSON object (no wrapper key) with these fields:\n"
            f'  "phase": "{required_phase}"\n'
            f'  "hypothesis": "<string hypothesis or null>"\n'
            f'  "calls": list of {{"tool":"...","arguments":{{...}}}} (max 4, empty for hypothesize/conclude)\n'
            f'  "diagnosis": null (OR a Diagnosis object ONLY when phase is "conclude")\n'
            f'  "planned_actions": null\n\n'
        )
        if required_phase == "conclude":
            prompt += (
                f"For the 'conclude' phase, 'diagnosis' MUST be a JSON object with these exact fields:\n"
                f'  "category": string (e.g. "jvm_resource_exhaustion")\n'
                f'  "culprit": string (service name, e.g. "order-service")\n'
                f'  "evidence": list of strings, where EVERY string MUST cite at least one collected evidence ID from {available_eids} (e.g. ["E1 confirms restarts", "E2 confirms OOMKilled"])\n'
                f'  "remediation": string describing how to fix the issue\n'
                f'  "confidence": number between 0 and 1\n'
                f"Do not include calls during conclude.\n\n"
            )
        else:
            prompt += (
                f"Set 'diagnosis': null for this phase.\n"
                f"At gather/verify, use only advertised tools and valid arguments.\n\n"
            )
        prompt += (
            "Tools:\n"
            + json.dumps(tool_contract, separators=(",", ":"))
            + "\n\nState:\n"
            + json.dumps(state, separators=(",", ":"), default=str)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": int(os.getenv("BENCH_LLM_MAX_TOKENS", "1200")),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return only JSON matching AgentDecision."},
                {"role": "user", "content": prompt},
            ],
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        timeout = int(os.getenv("BENCH_LLM_TIMEOUT", "90"))
        try:
            response = self.request_fn(
                f"{self.base_url}/chat/completions",
                {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                payload,
                timeout,
            )
        except Exception as exc:
            if self.fallback_api_key and self.fallback_base_url and self.base_url != self.fallback_base_url:
                fallback_payload = dict(payload)
                fallback_payload["model"] = self.fallback_model
                fallback_payload.pop("reasoning_effort", None)
                response = self.request_fn(
                    f"{self.fallback_base_url}/chat/completions",
                    {"Authorization": f"Bearer {self.fallback_api_key}", "Content-Type": "application/json"},
                    fallback_payload,
                    timeout,
                )
            else:
                raise
        try:
            choice = response["choices"][0]
            message = choice["message"]
            content = message.get("content")
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise RuntimeError("LLM response did not contain choices[0].message.content") from exc
        if isinstance(content, list):
            content = "".join(
                part["text"] for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if not isinstance(content, (str, dict)) or not content:
            finish_reason = choice.get("finish_reason", "unknown") if isinstance(choice, dict) else "unknown"
            refusal = message.get("refusal") if isinstance(message, dict) else None
            detail = f"finish_reason={finish_reason!r}"
            if refusal:
                detail += f", refusal={refusal!r}"
            raise RuntimeError(
                "LLM returned no decision content (" + detail + "). "
                "For Gemini, use BENCH_LLM_REASONING_EFFORT=none or allow a larger output budget."
            )
        # Parse content to dict, unwrapping common LLM wrapping patterns.
        if isinstance(content, str):
            parsed = json.loads(content)
        else:
            parsed = content
        # Some models wrap the decision in {"AgentDecision": {…}} — unwrap it.
        if isinstance(parsed, dict) and len(parsed) == 1 and "AgentDecision" in parsed:
            parsed = parsed["AgentDecision"]
        return AgentDecision.model_validate(parsed)
