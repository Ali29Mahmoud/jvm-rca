# Task: verify the tasks marked "Done" (read-only audit)

Goal: check whether each "Done" item in my project checklist is really done, then write a short report with comments on how to improve each one. **Do not fix anything. Only check and report.**

## Output I want

Create **one file: `docs/verification-report.md`**. It must contain:

1. **Summary table**, one row per item: `ID | Verdict | Evidence (max 2 lines) | Enhancement comment (max 2 lines)`.
   Verdicts: **PASS** (evidence matches the check), **PARTIAL**, **FAIL**, **UNVERIFIED** (say why).
2. **Per-item discussion**: for every ID, 2 to 3 sentences: what you checked, what you found, whether "Done" is justified, and what to improve. Write these for every item, including PASS items.
3. **Top 5 fixes** I should do before moving on, most important first.
4. **Checklist corrections**: items whose "Done" mark or check wording should change.

## Token budget rules (important)

- Be brief. No long explanations, no repeated context, no web searches.
- **Batch commands:** one shell call per section where possible.
- **Always filter output:** use `grep -c`, `head -n`, `tail -n`, `wc -l`, `jq` projections. Never dump full logs, full YAML or full files.
- Read docs with `grep` and heading lists (`grep -n '^#' file`), not by opening them whole.
- If one check already proves another item, write "covered by <ID>" and skip it.
- One k6 run only, short. Stop after at most about 50 tool calls.
- Keep the report under about 250 lines.

## Safety rules

- **Read-only.** Allowed writes: creating `docs/verification-report.md`, creating test data through the gateway (one customer and one order), and one short k6 run.
- **Never run:** `kubectl delete|apply|scale|rollout|set|patch|edit|exec ... (write commands)`, `helm install|upgrade|uninstall`, `terraform apply|destroy`, `git commit|push|checkout|reset`, `docker system prune`, or anything that pulls images (disk is almost full).
- **Never print secret values.** When listing environment variables, print names only. Use the Grafana password from the secret inside a command without echoing it.
- Confirm `kubectl config current-context` is `kind-jvm-rca` first. Stop if not. The user has other Kind clusters.
- The user's shell is **fish**. Use fish syntax in interactive commands or write a small bash script file for yourself.
- If a check would need something destructive, mark it UNVERIFIED and say how I can do it safely.

## Setup (once)

```fish
set -x NS eventuate-tram-examples-customers-and-orders
kubectl config current-context
df -h / | tail -1
```
Start background port-forwards on high local ports (stop them at the end):
- Gateway: `svc/api-gateway-service` `18085:8080` (namespace `$NS`)
- Prometheus: `svc/monitoring-kube-prometheus-prometheus` `19090:9090` (namespace `monitoring`)
- Tempo: `svc/tempo` `13200:3200` (namespace `$NS`)
- Grafana: `svc/monitoring-grafana` `13000:80` (namespace `monitoring`)

Use the Prometheus HTTP API (`curl -s localhost:19090/api/v1/query --data-urlencode query=...`) and the Tempo API (`/api/search`, `/api/traces/<id>`) instead of the UIs. Discover Kafka CLI paths and Postgres credentials yourself; do not assume them.

## Health snapshot (run once, report in 5 lines at the top of the report)

1. Pods: name, ready, restart count (`kubectl get pods -n $NS`), and anything not Running.
2. Disk: `df -h /` free space.
3. Consumer groups: any with lag above 0 (a poison message previously stalled customer-service).
4. Orders: count by state, and any `PENDING` older than 1 minute.
5. `git status -sb | head -20`, and the number of unpushed commits.

## Items to verify

### Day 1

| ID | Claim (marked Done) | Quick check |
|---|---|---|
| D1.1 | Fork with README credit and license kept | `git remote -v`; grep README (`README.adoc` or `.md`) for "upstream" and "Apache"; `LICENSE.md` exists and is unchanged vs upstream (if an `upstream` remote exists) |
| D1.2 | Prerequisites installed | `docker --version`, `java -version`, `./gradlew --version` (first lines only) |
| D1.3 | App ran locally with the Postgres variant | Do NOT rerun (slow, disk). Mark "covered by D2.6" if it passes |
| D1.4 | Customer, order, order history flow works | Covered by D2.6 (use the README or `run_flow.sh` for exact requests, including the history call) |
| D1.5 | `docs/recon.md` lists services, ports, topics with partitions, groups, tables | Headings and line count; cross-check 2 facts against the cluster |
| D1.6 | Config findings recorded (pool size, JVM options, Actuator, Micrometer, gateway type) | `grep -c` each keyword in recon.md; confirm "gateway is reactive" against `api-gateway-service/*/build.gradle` |
| D1.7 | `docs/prior-art.md` exists | Exists; mentions AIOpsLab, ITBench, OpenSRE, HolmesGPT; about 5 bullets |
| D1.8 | `docs/scope.md` written and pushed | `git ls-files docs/scope.md` (it was earlier in the repo root); unpushed commits |

### Day 2

| ID | Claim | Quick check |
|---|---|---|
| D2.1 | kind, kubectl, helm, skaffold installed | Version commands |
| D2.2 | Cluster created | `kind get clusters`; `kubectl get nodes`. Note: the checklist says `rca` but the real name is `jvm-rca`. Suggest fixing the text |
| D2.3 | Skaffold-or-own-manifests decision recorded | grep recon.md for "skaffold" |
| D2.4 | Infrastructure pods running | kafka, zookeeper, postgres, mongodb Running; restart counts |
| D2.5 | App pods Ready, resource requests and limits set | `kubectl get deploy -n $NS -o json \| jq` projection of name, ready, requests and limits only; any CrashLoop |
| D2.6 | **Functional flow works** | Create 1 customer and 1 order via the gateway (check ids are numeric first), wait 10 s, expect `APPROVED`, then query order history. Check `customer-service` logs for `NullPointerException` count |
| D2.7 | Resource use recorded | grep recon.md for CPU or RAM numbers |
| D2.8 | Makefile `up` and `down` work | `make -n up` and `make -n down` only (dry run, do not execute). Comment on idempotency |

### Day 3

| ID | Claim | Quick check |
|---|---|---|
| D3.1 | k6 script works, 0 failed checks | `ls k6/`; run once for about 25 s with `timeout -s INT 25 k6 run k6/load-test.js` and grep `http_req_failed`, `checks`, `http_req_duration` (if `--duration` conflicts with the script's scenario, use the timeout form) |
| D3.2 | `docs/baseline.md` has p95, error rate, approval rate, chosen rate | File exists with numbers; compare the error rate with the run in D3.1 (an earlier run I saw showed 99.5% failures) |
| D3.3 | All orders APPROVED after the run | Count orders by state after D3.1; no stale `PENDING` |

### Day 4

| ID | Claim | Quick check |
|---|---|---|
| D4.1 | Prometheus endpoint exposed by every Java service | Prometheus: `up{namespace="$NS"}` per job and `count by (application)(jvm_memory_used_bytes)`; I have only confirmed order-service and customer-service. Also: are `MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE` and `MANAGEMENT_METRICS_TAGS_APPLICATION` present **in the manifests in git** (`grep -rn` in `k8s-deployment/`) and not only live in the cluster (`jq` env **names** only)? Which image does each deployment run (patched build or `:latest`)? Is there a patch file in `patches/` and a "What this fork changes" list in the README? |
| D4.2 | kube-prometheus-stack installed | `helm list -n monitoring`; pods Ready; are the install values saved in the repo? |
| D4.3 | ServiceMonitors and targets healthy | `/api/v1/targets` for `$NS`: job and health only; report any not `up` |
| D4.4 | JVM dashboard imported and shows data | Grafana API search for the dashboard; its JSON has no leftover `${DS_PROMETHEUS}`; is it saved in the repo (for example `monitoring/dashboards/*.json` or a labeled ConfigMap), since Grafana here may not persist it? |
| D4.6 | `docs/queries.md` has 8 queries that work | Run each listed query against Prometheus; report only which ones return no data |

### Day 5

| ID | Claim | Quick check |
|---|---|---|
| D5.1 | OTel Java agent attached to the Java services | Init containers and env **names** per deployment; `grep -ci` count of agent errors in recent logs per service. **Also report how `JAVA_TOOL_OPTIONS` is set**, because scenario S02 plans to set `-Xmx` through the same variable and must append, not overwrite |
| D5.2 | Collector and Tempo running | Pods Ready; Tempo `/ready`; count of export errors in collector logs (counts only) |
| D5.3 | A trace shows the request across services | Use the order from D2.6. Find the newest `POST /orders` trace in Tempo and report: services list, span count, any database spans. The current evidence is a GET trace with 2 services. State whether the trace continues through the outbox, CDC and customer-service |

### Day 6

| ID | Claim | Quick check |
|---|---|---|
| D6.1 | Terraform module deploys the observability stack and the app | Locate the module; `terraform validate` and `terraform fmt -check` only (no plan, apply or destroy); which `helm_release` and manifests it covers; is Loki missing (Day 5 is blocked)? Are state files git-ignored? |

## Extra checks worth a line each

- **Git hygiene:** large or generated files tracked (`k6-report.html`, build output)? `.gitignore` covers them? Quick secret scan: `git grep -nI -E '(password|secret|token|api[_-]?key)\s*[:=]' | head -10`.
- **Reproducibility:** things done by hand in the cluster that are not in git (live `kubectl set env`, manual Helm installs). List them.
- **Docs consistency:** does `docs/recon.md` match what you saw (Serial GC, small heap, reactive gateway, poison-message finding)? Note gaps.

## Final step

Stop the background port-forwards. Reply with only: the report path, the verdict counts (PASS / PARTIAL / FAIL / UNVERIFIED), and the top 3 problems. Do not paste the report.
