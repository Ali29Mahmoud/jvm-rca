# Chaos Mesh Native CRD Scenarios

This directory contains **native Chaos Mesh Custom Resource Definitions (CRDs)** corresponding to the benchmark scenarios. These files can be applied directly to your Kubernetes cluster without any external scripts or wrappers.

## Scenarios Overview

| Scenario File | Chaos Kind | Target Service | Failure Mechanism |
| :--- | :--- | :--- | :--- |
| [`s01-order-service-memory-stress.yaml`](s01-order-service-memory-stress.yaml) | `StressChaos` | `order-service` | Injects 850Mi memory allocation stress inside the container, exceeding cgroup limits and causing kernel `OOMKilled` (Exit Code 137). |
| [`s02-customer-service-jvm-oom.yaml`](s02-customer-service-jvm-oom.yaml) | `JVMChaos` | `customer-service` | Uses JVM agent / Byteman bytecode injection to throw `java.lang.OutOfMemoryError` on `CustomerService.createCustomer()`. |
| [`s04-order-service-cpu-stress.yaml`](s04-order-service-cpu-stress.yaml) | `StressChaos` | `order-service` | Injects 100% CPU burn across 2 worker threads, triggering Linux CFS quota throttling and request latency. |

---

## Native Usage

### 1. Apply Fault Injection
```bash
# Apply a single scenario
kubectl apply -f benchmark/scenarios/ScenariosCRD/s01-order-service-memory-stress.yaml

# Or apply all
kubectl apply -f benchmark/scenarios/ScenariosCRD/
```

### 2. Inspect Chaos Mesh Status
```bash
# Check status of the Chaos object
kubectl describe stresschaos order-service-memory-stress -n eventuate-tram-examples-customers-and-orders

# Inspect Chaos Mesh controller logs
kubectl logs -n chaos-mesh -l app.kubernetes.io/component=controller-manager --tail=50
```

### 3. Cleanup / Teardown
```bash
kubectl delete -f benchmark/scenarios/ScenariosCRD/s01-order-service-memory-stress.yaml
```
