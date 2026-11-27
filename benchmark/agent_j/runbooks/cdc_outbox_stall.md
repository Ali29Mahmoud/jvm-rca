# CDC Outbox Stall

## Symptoms
- Outbox table accumulates unpublished rows.
- Postgres replication slot WAL lag grows or slot becomes inactive.
- Kafka outbox topic offsets stop advancing.

## Diagnosis
1. Run `outbox_backlog` to check `unpublished_count`.
2. Run `replication_slot_lag` to check slot `active` status and `wal_lag_bytes`.
3. Run `cdc_logs` to check for CDC service errors or pod unavailability.

## Remediation
- Restore or scale up the CDC service deployment.
- Verify database and Kafka connectivity from the CDC pod.
