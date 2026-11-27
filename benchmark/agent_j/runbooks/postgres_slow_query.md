# Postgres Slow Query

## Symptoms
- Elevated database CPU or I/O and high query latency.
- `pg_stat_statements` shows queries with high `mean_exec_time` or `total_exec_time`.

## Diagnosis
1. Run `pg_stat_statements` to find the top slow queries.
2. Run `pg_explain` on the slow `SELECT` query to check for sequential scans or poor join plans.

## Remediation
- Add appropriate indexes or rewrite the query to avoid full table scans.
- Run `ANALYZE` if table statistics are stale.
