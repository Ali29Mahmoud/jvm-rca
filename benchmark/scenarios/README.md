# Benchmark Scenarios

This directory contains the fault scenario specifications for the **JVM-RCA Benchmark**.

## Directory Structure

```
benchmark/scenarios/
├── _template.yaml          # Master scenario specification template & field documentation
├── README.md               # Overview and specification schema guide (this file)
└── <category>/             # Scenarios organized by domain category
    ├── jvm/                # JVM memory leaks, GC pauses, thread exhaustion, CPU spikes
    ├── kafka/              # Broker partitions, consumer lag, poison messages, rebalances
    ├── postgres/           # Connection pool starvation, table lock, slow queries, WAL lag
    ├── cdc/                # Debezium capture failure, outbox table backlog
    └── network/            # Packet loss, latency injection, DNS resolution failures
```

---

## Scenario Specification Schema Guide

Every scenario file must conform to the template specification defined in [_template.yaml](file:///home/ali-mahmoud/Desktop/jvm-rca/jvm-rca/benchmark/scenarios/_template.yaml).

### Required Top-Level Sections

1. **`id` & Metadata**:
   - `id`: Stable unique scenario identifier (e.g., `SCENARIO-001-jvm-heap-oom`).
   - `name`: Brief descriptive human-readable title.
   - `category`: Root failure domain (`jvm`, `kafka`, `postgres`, `cdc`, `network`, `pod`, `dependency`).
   - `tier`: Complexity tier (`1` direct/local crash, `2` cascading downstream failure, `3` subtle/silent degradation).
   - `target`: Service name (`order-service`, `customer-service`, `postgres`, `kafka`, etc.), namespace, and component.
   - `description`: Detailed explanation of the scenario.

2. **`inject`**:
   - `type`: `chaos-mesh`, `k8s-patch`, or `exec`.
   - `timeout`: Maximum duration to apply the fault (e.g. `180s`).
   - `chaos_mesh`: Inline Chaos Mesh CRD (e.g., `PodChaos`, `NetworkChaos`, `StressChaos`, `JVMChaos`, `IOChaos`) or path.
   - `commands`: Optional auxiliary commands executed during injection.

3. **`symptom_check`**:
   - `promql`: PromQL expression querying Prometheus to detect fault manifestation.
   - `operator`: Comparison operator (`==`, `!=`, `>`, `>=`, `<`, `<=`, `absent`, `present`).
   - `threshold`: Numeric or string threshold that signals fault presence.
   - `wait`:
     - `initial_delay_seconds`: Time before starting symptom verification.
     - `interval_seconds`: Query polling interval.
     - `timeout_seconds`: Max time to wait for the symptom before failing the test run.
     - `stabilization_duration`: Minimum duration metric must remain in breach condition.

4. **`agent_input`**:
   - `prompt`: The realistic alert message/dispatch text presented to the AI SRE agent.
   - `budgets`: Limits on tool execution steps (`max_steps`), elapsed wall-clock time (`time_limit_seconds`), and token budget.

5. **`ground_truth`**:
   - `culprit`: Precise service, component, container, and namespace.
   - `category`: Benchmark taxonomy category.
   - `root_cause`: Expert explanation of the failure mechanism.
   - `affected_services`: All degraded or broken services.
   - `expected_evidence`: Key signals expected in metrics, logs, traces, and Kubernetes events.
   - `expected_tools`: Tools an optimal agent should use (e.g., `query_prometheus`, `get_pod_logs`, `describe_pod`).
   - `remediation`: Description of the correct recovery action and verification condition.

6. **`cleanup`**:
   - `chaos_mesh.resources`: List of Chaos Mesh CRDs to clean up.
   - `k8s.delete`: Any created temporary Kubernetes resources to delete.
   - `commands`: Shell cleanup and reset commands.
   - `baseline_verification`: PromQL check verifying the system returned to baseline health.
