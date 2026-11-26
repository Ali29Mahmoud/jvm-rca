"""Tests for Agent‑J tool wrappers and parsers.
These tests mock external interactions (Kubernetes exec, HTTP calls, file reads)
so they can run offline.
"""

import json
from unittest import mock

import pytest

from benchmark.agent_j import AgentJTools
from benchmark.agent_j.parsers import (
    parse_thread_dump,
    parse_actuator_threaddump,
    parse_heap_histogram,
    parse_gc_logs,
    parse_hikari_metrics,
)

# Sample payloads ------------------------------------------------------------
_ACTUATOR_TD = {
    "threads": [
        {
            "threadId": 1,
            "threadName": "main",
            "threadState": "RUNNABLE",
            "stackTrace": [],
            "lockedMonitors": [],
            "lockedSynchronizers": [],
        }
    ]
}
_ACTUATOR_TD_JSON = json.dumps(_ACTUATOR_TD)

_JCMD_TD = "\"1\" #\njava.lang.Thread.State: BLOCKED\n\tat com.example.Test.method(Test.java:10)\n\t- waiting to lock <0x12345> (a com.example.Lock)"

_HEAP_HISTO = """num #instances #bytes class name
1:      10   204800 com.example.Foo
2:       5   102400 com.example.Bar
Total 15 307200"""

_GC_LOG = "[0.123s][info][gc] Pause Young (Allocation Failure) 64M->32M(256M) 5.678ms"

_HIKARI_PROM = {
    "status": "success",
    "data": {
        "result": [
            {"metric": {"__name__": "hikaricp_connections_active", "application": "order-service"}, "value": [0, "5"]},
            {"metric": {"__name__": "hikaricp_connections_idle", "application": "order-service"}, "value": [0, "2"]},
            {"metric": {"__name__": "hikaricp_connections", "application": "order-service"}, "value": [0, "7"]},
            {"metric": {"__name__": "hikaricp_connections_max", "application": "order-service"}, "value": [0, "10"]},
        ]
    }
}

# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------

def test_parse_actuator_thread_dump():
    summary = parse_actuator_threaddump(_ACTUATOR_TD_JSON)
    assert summary["total_threads"] == 1
    assert summary["states"]["RUNNABLE"] == 1
    assert summary["deadlock_count"] == 0


def test_parse_jcmd_thread_dump():
    summary = parse_thread_dump(_JCMD_TD)
    # The sample contains a BLOCKED thread, ensure it appears in summary
    assert summary["total_threads"] == 1
    assert summary["states"]["BLOCKED"] == 1


def test_parse_heap_histogram():
    result = parse_heap_histogram(_HEAP_HISTO)
    assert result["total_instances"] == 15
    assert len(result["top_classes"]) == 2
    assert result["top_classes"][0]["class_name"] == "com.example.Foo"


def test_parse_gc_logs():
    result = parse_gc_logs(_GC_LOG)
    assert result["gc_logging_enabled"] is True
    assert result["total_gc_events"] == 1
    assert result["pause_events"] == 1
    assert result["pause_ms"]["count"] == 1


def test_parse_hikari_metrics():
    summary = parse_hikari_metrics(_HIKARI_PROM)
    assert summary["pool_count"] == 1
    pool = summary["pools"][0]
    assert pool["service"] == "order-service"
    assert pool["active"] == 5
    assert pool["idle"] == 2
    assert pool["total"] == 7
    assert pool["max"] == 10
    assert pool["utilization_pct"] == 50.0

# ---------------------------------------------------------------------------
# Tool wrapper integration tests (AgentJTools)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_adapter():
    # Create an AgentJTools instance with mocked command_runner and http_get
    tools = AgentJTools()
    tools.command_runner = mock.Mock(return_value="")
    tools.http_get = mock.Mock(return_value=json.dumps(_HIKARI_PROM))
    return tools

def test_thread_dump_tool(mock_adapter):
    args = {"target": "order-service", "namespace": "default", "source": "actuator"}
    mock_adapter._exec_actuator = mock.Mock(return_value=_ACTUATOR_TD_JSON)
    result = mock_adapter.thread_dump(args)
    summary = json.loads(result.summary)
    assert summary["total_threads"] == 1

def test_heap_histogram_tool(mock_adapter):
    args = {"target": "order-service", "namespace": "default", "top_n": 2, "live_only": False}
    mock_adapter._exec_jcmd = mock.Mock(return_value=_HEAP_HISTO)
    result = mock_adapter.heap_histogram(args)
    data = json.loads(result.summary)
    assert data["shown_count"] == 2

def test_gc_log_tool(mock_adapter):
    args = {"target": "order-service", "namespace": "default", "tail": 10, "previous": False}
    mock_adapter.command_runner = mock.Mock(return_value=_GC_LOG)
    result = mock_adapter.gc_log(args)
    data = json.loads(result.summary)
    assert data["total_gc_events"] == 1

def test_hikari_summary_tool_prometheus(mock_adapter):
    args = {"service": "order-service", "namespace": "default", "source": "prometheus"}
    result = mock_adapter.hikari_summary(args)
    data = json.loads(result.summary)
    assert data["pool_count"] == 1
    assert data["any_saturated"] is False

def test_hikari_summary_tool_actuator_fallback(mock_adapter):
    # Simulate empty Prometheus result -> fallback to actuator
    mock_adapter.http_get = mock.Mock(return_value=json.dumps({"status": "success", "data": {"result": []}}))
    mock_adapter._exec_actuator = mock.Mock(return_value="metrics text")
    # Provide minimal actuator text that parses to empty pools (stub)
    with mock.patch('benchmark.agent_j.parsers.parse_hikari_metrics', return_value={"pool_count": 0, "any_saturated": False, "pools": []}):
        args = {"service": "order-service", "namespace": "default", "source": "auto"}
        result = mock_adapter.hikari_summary(args)
        data = json.loads(result.summary)
        assert data["pool_count"] == 0
