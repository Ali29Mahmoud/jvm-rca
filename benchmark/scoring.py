"""Deterministic diagnosis scoring with an optional evidence quality judge."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: float = Field(ge=0, le=1)
    culprit: float = Field(ge=0, le=1)
    evidence_keyword: float = Field(ge=0, le=1)
    evidence_judge: float | None = Field(default=None, ge=0, le=1)
    evidence: float = Field(ge=0, le=1)
    remediation: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)
    verdict: Literal["correct", "partial", "incorrect"]
    manual_spot_check: bool


EvidenceJudge = Callable[[str, dict[str, Any], list[str]], float]

_STOP_WORDS = {
    "with", "from", "that", "this", "then", "than", "into", "when", "where",
    "which", "while", "should", "would", "could", "there", "their", "after",
    "before", "under", "over", "close", "matching", "spike", "increasing",
    "showing", "show", "expected", "evidence", "metric", "metrics", "logs",
    "traces", "events", "service", "container", "namespace", "query", "prometheus",
    "order", "error", "errors", "request", "requests", "state", "status",
}


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 3 and token not in _STOP_WORDS
    }


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for nested in value.values() for text in _flatten_strings(nested)]
    if isinstance(value, (list, tuple)):
        return [text for nested in value for text in _flatten_strings(nested)]
    return []


def _score_keyword_recall(expected_text: list[str], observed_text: str) -> float:
    expected_tokens = set().union(*(_tokens(text) for text in expected_text)) if expected_text else set()
    if not expected_tokens:
        return 1.0
    observed_tokens = _tokens(observed_text)
    return len(expected_tokens & observed_tokens) / len(expected_tokens)


def should_manually_spot_check(run_id: str) -> bool:
    """Select a stable, evenly distributed ~20% of run IDs for human review."""
    bucket = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16) % 5
    return bucket == 0


def score_diagnosis(
    diagnosis: Any,
    ground_truth: dict[str, Any],
    run_id: str,
    *,
    evidence_judge: EvidenceJudge | None = None,
    judge_prompt: str = "",
) -> ScoreResult:
    """Compare a diagnosis with scenario ground truth and return field scores."""
    diagnosis_data = diagnosis.model_dump() if hasattr(diagnosis, "model_dump") else dict(diagnosis)
    expected_category = str(ground_truth.get("category", "")).strip().casefold()
    actual_category = str(diagnosis_data.get("category", "")).strip().casefold()
    category_score = float(bool(expected_category) and actual_category == expected_category)

    raw_culprit = ground_truth.get("culprit", {})
    expected_culprits = set()
    if isinstance(raw_culprit, dict):
        expected_culprits.update(str(value).strip().casefold() for value in raw_culprit.values() if value)
    elif raw_culprit:
        expected_culprits.add(str(raw_culprit).strip().casefold())
    actual_culprit = str(diagnosis_data.get("culprit", "")).strip().casefold()
    culprit_score = float(bool(actual_culprit) and actual_culprit in expected_culprits)

    evidence = diagnosis_data.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]
    observed_evidence = " ".join(str(item) for item in evidence)
    expected_evidence = _flatten_strings(ground_truth.get("expected_evidence", {}))
    keyword_score = _score_keyword_recall(expected_evidence, observed_evidence)
    judge_score = None
    evidence_score = keyword_score
    if evidence_judge is not None:
        judge_score = float(evidence_judge(judge_prompt, diagnosis_data, expected_evidence))
        if not 0 <= judge_score <= 1:
            raise ValueError(f"Evidence judge must return a score from 0 to 1, got {judge_score}")
        evidence_score = 0.7 * keyword_score + 0.3 * judge_score

    remediation = ground_truth.get("remediation", {})
    expected_remediation = _flatten_strings(remediation)
    remediation_score = _score_keyword_recall(
        expected_remediation,
        str(diagnosis_data.get("remediation", "")),
    )
    total = (category_score + culprit_score + evidence_score + remediation_score) / 4
    if total >= 0.85 and category_score == 1 and culprit_score == 1:
        verdict: Literal["correct", "partial", "incorrect"] = "correct"
    elif total < 0.25:
        verdict = "incorrect"
    else:
        verdict = "partial"

    return ScoreResult(
        category=category_score,
        culprit=culprit_score,
        evidence_keyword=keyword_score,
        evidence_judge=judge_score,
        evidence=evidence_score,
        remediation=remediation_score,
        total=total,
        verdict=verdict,
        manual_spot_check=should_manually_spot_check(run_id),
    )


def append_spot_check(log_path: Any, run_id: str, scenario_id: str, verdict: str, score: float) -> None:
    """Add a pending review row when the stable one-in-five sample selects a run."""
    if not should_manually_spot_check(run_id):
        return
    path = log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Manual verdict spot checks\n\n"
            "One in five run IDs are selected deterministically. Review the diagnosis and evidence, "
            "then fill in the human verdict and notes.\n\n"
            "| Run ID | Scenario | Automated verdict | Score | Human verdict | Notes |\n"
            "|---|---|---|---:|---|---|\n"
        )
    with path.open("a") as log:
        log.write(f"| {run_id} | {scenario_id} | {verdict} | {score:.3f} | pending | |\n")
