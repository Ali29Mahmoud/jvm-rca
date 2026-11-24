"""Agent-G: a bounded, evidence-first generic incident investigator.

Refactored modular package exposing tools, models, policy, and agent loop.
"""

from benchmark.agent_g.models import (
    StrictModel,
    ToolCall,
    AgentDecision,
    DiagnosisLike,
)
from benchmark.agent_g.tools import (
    ToolResult,
    PromQLArgs,
    LogQLArgs,
    TraceSearchArgs,
    KubectlArgs,
    ToolSpec,
    AgentGTools,
    _compact,
)
from benchmark.agent_g.policy import (
    AgentGPolicy,
    OpenAICompatiblePolicy,
)
from benchmark.agent_g.agent import (
    AgentGRun,
    AgentG,
)

__all__ = [
    "StrictModel",
    "ToolCall",
    "AgentDecision",
    "DiagnosisLike",
    "ToolResult",
    "PromQLArgs",
    "LogQLArgs",
    "TraceSearchArgs",
    "KubectlArgs",
    "ToolSpec",
    "AgentGTools",
    "_compact",
    "AgentGPolicy",
    "OpenAICompatiblePolicy",
    "AgentGRun",
    "AgentG",
]
