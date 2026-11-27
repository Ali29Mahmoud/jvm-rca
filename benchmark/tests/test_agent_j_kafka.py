"""Fixture and unit tests for Day 16 Agent-J tools (Kafka, Postgres, CDC, Runbooks)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

import pytest

from benchmark.agent_j import AgentJTools, BM25RunbookRetriever

_KAFKA_GROUP_DESCRIBE_FIXTURE = """
GROUP           TOPIC                          PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID                                           HOST            CLIENT-ID
order-group     io.eventuate.tram.outbox       0          120             150             30              consumer-order-1-abc                                  /10.0.0.5       consumer-order-1
order-group     io.eventuate.tram.outbox       1          200             205             5               consumer-order-2-def                                  /10.0.0.6       consumer-order-2
"""

_KAFKA_TOPIC_OFFSETS_FIXTURE = """
io.eventuate.tram.outbox:0:500
io.eventuate.tram.outbox:1:50
io.eventuate.tram.outbox:2:45
"""

_PG_STAT_ACTIVITY_FIXTURE = json.dumps(
    [
        {
            "pid": 101,
            "usename": "eventuate",
            "state": "active",
            "wait_event_type": "Lock",
            "wait_event": "tuple",
            "duration_seconds": 12.5,
            "query": "UPDATE customer SET credit_limit = 100 WHERE id = 1",
        },
        {
            "pid": 102,
            "usename": "eventuate",
            "state": "idle in transaction",
            "wait_event_type": None,
            "wait_event": None,
            "duration_seconds": 15.0,
            "query": "SELECT * FROM customer WHERE id = 1 FOR UPDATE",
        },
    ]
)

_PG_BLOCKING_TREE_FIXTURE = json.dumps(
    [
        {
            "blocked_pid": 101,
            "blocked_user": "eventuate",
            "blocked_query": "UPDATE customer SET credit_limit = 100 WHERE id = 1",
            "blocking_pids": [102],
            "blocked_seconds": 12.5,
        }
    ]
)

_PG_STAT_STATEMENTS_FIXTURE = json.dumps(
    [
        {
            "calls": 1500,
            "total_exec_time_ms": 45210.5,
            "mean_exec_time_ms": 30.14,
            "rows": 1500,
            "query": "SELECT * FROM orders WHERE customer_id = $1",
        }
    ]
)

_PG_EXPLAIN_FIXTURE = json.dumps(
    [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "orders",
                "Startup Cost": 0.0,
                "Total Cost": 1234.56,
                "Plan Rows": 10000,
            }
        }
    ]
)

_OUTBOX_BACKLOG_FIXTURE = json.dumps(
    [{"unpublished_count": 42, "oldest_creation_time": 1700000000000}]
)

_REPLICATION_SLOTS_FIXTURE = json.dumps(
    [
        {
            "slot_name": "eventuate_slot",
            "plugin": "pgoutput",
            "slot_type": "logical",
            "active": False,
            "wal_lag_bytes": 1048576,
        }
    ]
)

_CDC_LOGS_FIXTURE = """
2026-11-27 12:00:00 INFO  Starting Eventuate CDC service
2026-11-27 12:00:05 ERROR Failed to connect to replication slot eventuate_slot
2026-11-27 12:00:06 WARN  Retrying database connection
"""


@pytest.fixture
def tools():
    return AgentJTools(
        prometheus_url="http://localhost:9090",
        command_runner=mock.Mock(return_value=""),
        http_get=mock.Mock(return_value={}),
    )


def test_kafka_group_describe(tools):
    tools.command_runner = mock.Mock(return_value=_KAFKA_GROUP_DESCRIBE_FIXTURE)
    res = tools.kafka_group_describe({"group": "order-group"})
    data = json.loads(res.summary)
    assert data["group"] == "order-group"
    assert data["state"] == "Stable"
    assert data["member_count"] == 2
    assert data["total_lag"] == 35
    assert len(data["partitions"]) == 2


def test_kafka_topic_offsets_and_skew(tools):
    tools.command_runner = mock.Mock(return_value=_KAFKA_TOPIC_OFFSETS_FIXTURE)
    res = tools.kafka_topic_offsets({"topic": "io.eventuate.tram.outbox"})
    data = json.loads(res.summary)
    assert data["partition_count"] == 3
    assert data["total_offset"] == 595

    skew_res = tools.kafka_partition_skew({"topic": "io.eventuate.tram.outbox"})
    skew = json.loads(skew_res.summary)
    assert skew["skewed"] is True
    assert skew["hot_partitions"] == [0]


def test_postgres_readonly_tools(tools):
    tools.command_runner = mock.Mock(return_value=_PG_STAT_ACTIVITY_FIXTURE)
    act = json.loads(tools.pg_stat_activity({}).summary)
    assert act["total_connections"] == 2
    assert act["waiting_count"] == 1

    tools.command_runner = mock.Mock(return_value=_PG_BLOCKING_TREE_FIXTURE)
    blk = json.loads(tools.pg_blocking_tree({}).summary)
    assert blk["blocked_count"] == 1

    tools.command_runner = mock.Mock(return_value=_PG_STAT_STATEMENTS_FIXTURE)
    stmts = json.loads(tools.pg_stat_statements({"limit": 5}).summary)
    assert stmts["query_count"] == 1

    tools.command_runner = mock.Mock(return_value=_PG_EXPLAIN_FIXTURE)
    exp = json.loads(tools.pg_explain({"sql": "SELECT * FROM orders"}).summary)
    assert exp["node_type"] == "Seq Scan"


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM orders WHERE id = 1",
        "INSERT INTO orders VALUES (1)",
        "UPDATE orders SET state = 'CANCELLED'",
        "DROP TABLE orders",
        "SELECT 1; DELETE FROM orders",
    ],
)
def test_postgres_explain_rejects_writes(tools, bad_sql):
    with pytest.raises(ValueError):
        tools.pg_explain({"sql": bad_sql})


def test_cdc_and_outbox_tools(tools):
    tools.command_runner = mock.Mock(return_value=_OUTBOX_BACKLOG_FIXTURE)
    outbox = json.loads(tools.outbox_backlog({}).summary)
    assert outbox["unpublished_count"] == 42

    tools.command_runner = mock.Mock(return_value=_REPLICATION_SLOTS_FIXTURE)
    slots = json.loads(tools.replication_slot_lag({}).summary)
    assert slots["slot_count"] == 1
    assert slots["total_wal_lag_bytes"] == 1048576
    assert slots["inactive_slots"] == ["eventuate_slot"]

    tools.command_runner = mock.Mock(return_value=_CDC_LOGS_FIXTURE)
    logs = json.loads(tools.cdc_logs({}).summary)
    assert logs["error_count"] == 2


def test_runbooks_and_bm25_retriever(tools):
    retriever = BM25RunbookRetriever()
    assert 10 <= len(retriever.docs) <= 15

    # Ensure no runbook mentions a scenario ID like S01..S15
    for doc in retriever.docs:
        assert not re.search(r"\bS\d{2}\b", doc["content"]), f"Scenario ID found in {doc['id']}"

    res = json.loads(tools.runbook_search({"query": "consumer lag", "top_k": 3}).summary)
    assert res["matches"], "Expected at least one runbook match"
    assert res["matches"][0]["id"] == "kafka_consumer_lag"
