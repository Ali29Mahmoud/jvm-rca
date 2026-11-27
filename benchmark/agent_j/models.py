"""Pydantic argument schemas for Agent-J JVM diagnostic tools."""

from __future__ import annotations

from typing import Literal
from pydantic import Field, field_validator

from benchmark.agent_g.models import StrictModel

DEFAULT_NAMESPACE = "eventuate-tram-examples-customers-and-orders"
_K8S_NAME_RE = r"^[a-z0-9./-]+$"
_K8S_NS_RE = r"^[a-z0-9-]+$"


def _reject_option_like(value: str | None, field_desc: str) -> str | None:
    if value is not None and value.startswith("-"):
        raise ValueError(f"{field_desc} cannot start with '-'")
    return value


class ThreadDumpArgs(StrictModel):
    target: str = Field(min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    source: Literal["auto", "jcmd", "actuator"] = "auto"

    @field_validator("target", "namespace")
    @classmethod
    def reject_option_like_values(cls, value: str) -> str:
        return _reject_option_like(value, "target and namespace")  # type: ignore[return-value]


class HeapHistogramArgs(StrictModel):
    target: str = Field(min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    top_n: int = Field(default=15, ge=1, le=25)
    live_only: bool = False

    @field_validator("target", "namespace")
    @classmethod
    def reject_option_like_values(cls, value: str) -> str:
        return _reject_option_like(value, "target and namespace")  # type: ignore[return-value]


class GCLogArgs(StrictModel):
    target: str = Field(min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    tail: int = Field(default=2000, ge=1, le=10000)
    previous: bool = False

    @field_validator("target", "namespace")
    @classmethod
    def reject_option_like_values(cls, value: str) -> str:
        return _reject_option_like(value, "target and namespace")  # type: ignore[return-value]


class HikariSummaryArgs(StrictModel):
    service: str | None = Field(default=None, min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    source: Literal["auto", "prometheus", "actuator"] = "auto"

    @field_validator("service", "namespace")
    @classmethod
    def reject_option_like_values(cls, value: str | None) -> str | None:
        return _reject_option_like(value, "service and namespace")


class KafkaGroupDescribeArgs(StrictModel):
    group: str = Field(min_length=1, max_length=253)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    kafka_pod: str = Field(default="kafka", min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    bootstrap_server: str = Field(default="localhost:9092", min_length=1, max_length=253)

    @field_validator("group", "namespace", "kafka_pod", "bootstrap_server")
    @classmethod
    def reject_option_like_values(cls, value: str) -> str:
        return _reject_option_like(value, "kafka argument")  # type: ignore[return-value]


class KafkaTopicOffsetsArgs(StrictModel):
    topic: str = Field(min_length=1, max_length=253)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    kafka_pod: str = Field(default="kafka", min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    bootstrap_server: str = Field(default="localhost:9092", min_length=1, max_length=253)

    @field_validator("topic", "namespace", "kafka_pod", "bootstrap_server")
    @classmethod
    def reject_option_like_values(cls, value: str) -> str:
        return _reject_option_like(value, "kafka argument")  # type: ignore[return-value]


class KafkaPartitionSkewArgs(StrictModel):
    topic: str | None = Field(default=None, min_length=1, max_length=253)
    group: str | None = Field(default=None, min_length=1, max_length=253)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    kafka_pod: str = Field(default="kafka", min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    bootstrap_server: str = Field(default="localhost:9092", min_length=1, max_length=253)


class PgBaseArgs(StrictModel):
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    postgres_pod: str = Field(default="postgres", min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    database: str = Field(default="eventuate", min_length=1, max_length=128)
    ro_user: str = Field(default="readonly", min_length=1, max_length=128)


class PgStatActivityArgs(PgBaseArgs):
    pass


class PgBlockingTreeArgs(PgBaseArgs):
    pass


class PgStatStatementsArgs(PgBaseArgs):
    limit: int = Field(default=10, ge=1, le=50)


class PgExplainArgs(PgBaseArgs):
    sql: str = Field(min_length=1, max_length=4000)


class OutboxBacklogArgs(PgBaseArgs):
    table: str = Field(default="eventuate.message", min_length=1, max_length=128)


class ReplicationSlotLagArgs(PgBaseArgs):
    pass


class CdcLogsArgs(StrictModel):
    target: str = Field(default="cdc-service", min_length=1, max_length=253, pattern=_K8S_NAME_RE)
    namespace: str = Field(default=DEFAULT_NAMESPACE, min_length=1, max_length=253, pattern=_K8S_NS_RE)
    tail: int = Field(default=500, ge=1, le=10000)
    previous: bool = False


class RunbookSearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)
