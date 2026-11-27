# GC Pause Storm

## Symptoms
- Periodic latency spikes and timeouts across all endpoints.
- `gc_log` shows elevated p99 pause times or frequent Full GC events.

## Diagnosis
1. Run `gc_log` to inspect pause percentiles and Full GC frequency.
2. Run `heap_histogram` to check for excessive object allocation or retention.

## Remediation
- Tune heap sizing (`-Xms`/`-Xmx`) or switch/tune GC collector (G1GC/ZGC).
- Reduce allocation rate in hot code paths.
