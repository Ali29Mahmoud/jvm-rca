# Network Latency or Partition

## Symptoms
- Downstream RPC or database calls experience elevated latency or timeouts without local CPU/GC saturation.
- `thread_dump` shows threads waiting on socket reads (`socketRead0`).

## Diagnosis
1. Check service-to-service latency metrics and pod network policies.
2. Run `thread_dump` to confirm threads are blocked on network I/O.

## Remediation
- Remove faulty network policies, traffic-shaping rules, or DNS/CNI issues.
- Configure appropriate client timeouts and circuit breakers.
