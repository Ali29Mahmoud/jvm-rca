# Postgres Max Connections Saturation

## Symptoms
- Services fail to open new DB connections with `FATAL: sorry, too many clients already`.
- `pg_stat_activity` shows total connections near `max_connections`.

## Diagnosis
1. Run `pg_stat_activity` to inspect connection count by state and application.
2. Check HikariCP pool sizes across all services sharing the database.

## Remediation
- Increase Postgres `max_connections` or introduce a connection pooler (PgBouncer).
- Reduce per-pod `maximum-pool-size` to fit within database limits.
