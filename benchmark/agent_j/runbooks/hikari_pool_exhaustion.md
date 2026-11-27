# HikariCP Connection Pool Exhaustion

## Symptoms
- Application logs `SQLTransientConnectionException: Connection is not available, request timed out`.
- `hikari_summary` shows `pending > 0`, `active == max`, or rising `acquire_p99`.

## Diagnosis
1. Run `hikari_summary` for the affected service.
2. Run `thread_dump` to check threads blocked in `HikariPool.getConnection`.
3. Run `pg_stat_activity` to see if database queries are slow or idle-in-transaction.

## Remediation
- Increase HikariCP `maximum-pool-size` if database capacity allows.
- Fix slow queries or unclosed transactions holding connections.
