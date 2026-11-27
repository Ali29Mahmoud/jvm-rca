# CPU Throttling

## Symptoms
- High p95/p99 request latency while CPU utilization appears capped.
- Container CFS throttling (`container_cpu_cfs_throttled_periods_total`) is elevated.

## Diagnosis
1. Check CPU usage vs CPU limits in pod spec and Prometheus.
2. Run `thread_dump` to see runnable threads competing for CPU.

## Remediation
- Increase container CPU limits or remove overly restrictive CPU quotas.
- Reduce thread pool sizes if excessive context switching occurs.
