# Postgres Row Lock Contention

## Symptoms
- Transactions hang waiting on row-level or table-level locks.
- `pg_stat_activity` shows `wait_event_type = Lock`.

## Diagnosis
1. Run `pg_blocking_tree` to identify blocking PIDs and blocked queries.
2. Run `pg_stat_activity` to inspect long-running `idle in transaction` sessions.

## Remediation
- Terminate or fix long-running transactions holding locks.
- Shorten transaction scope and ensure consistent lock ordering.
