# Kafka Consumer Lag

## Symptoms
- Consumer group lag grows continuously across one or more partitions.
- Downstream state transitions stall or remain pending.
- `kafka_group_describe` shows high `total_lag`, `Empty` or `PreparingRebalance` state, or `member_count == 0`.

## Diagnosis
1. Run `kafka_group_describe` on the affected consumer group to check state, member count, and per-partition lag.
2. Check if consumers are alive (`kubectl get pods`) or stuck in a rebalance loop.
3. Inspect consumer pod logs and thread dumps for slow processing or blocked threads.

## Remediation
- Scale up consumer replicas or restart stalled consumer pods.
- Fix downstream bottlenecks (DB locks, network latency) slowing down message processing.
