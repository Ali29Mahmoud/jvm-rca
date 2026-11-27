# OOM and Container Memory Limit

## Symptoms
- Pod restarts with `OOMKilled` (exit code 137) or JVM throws `OutOfMemoryError`.
- Heap usage approaches `-Xmx` or container RSS approaches cgroup memory limit.

## Diagnosis
1. Check pod status and events for `OOMKilled`.
2. Run `heap_histogram` to identify top memory-consuming classes.
3. Run `gc_log` to check for frequent full GCs prior to termination.

## Remediation
- Increase container memory limit and align `-Xmx` / `-XX:MaxRAMPercentage`.
- Investigate memory leaks in top histogram classes.
