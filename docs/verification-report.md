# Done-task verification report

Health snapshot (2026-11-14 recheck): all 11 application pods are Running and Ready; infrastructure restart counts are Kafka 6 and MongoDB/Postgres/Tempo/ZooKeeper 2. Disk free space is 7.2G (97% used). No Kafka numeric lag above zero was found. PostgreSQL has 828 APPROVED orders and no PENDING orders. Git has one modified manifest and the audit/report files are untracked; there are zero unpushed commits.

| ID | Verdict | Evidence (max 2 lines) | Enhancement comment (max 2 lines) |
|---|---|---|---|
| D1.1 | PARTIAL | README credits upstream and Apache; LICENSE.md exists. No upstream remote permits an unchanged comparison. | Add an upstream remote pinned to the fork point. |
| D1.2 | PASS | Docker 29.7, Java 17, and Gradle 8.14.5 run. | Pin supported versions in docs. |
| D1.3 | PASS | Covered by D2.6: deployed Postgres flow works. | Retain a local-run transcript. |
| D1.4 | PASS | Covered by D2.6: customer, approved order, and history work. | Automate the smoke flow in CI. |
| D1.5 | FAIL | recon.md lacks the required service/port/topic/table inventory. | Add concise topology and partition facts. |
| D1.6 | PARTIAL | Gateway is WebFlux/reactive; recon.md lacks pool/JVM/Actuator/Micrometer findings. | Record all requested configuration evidence. |
| D1.7 | FAIL | docs/prior-art.md is absent. | Add the four named projects and comparison bullets. |
| D1.8 | FAIL | docs/scope.md is absent/untracked; no unpushed commits exist. | Add and commit scope.md. |
| D2.1 | PASS | kind, kubectl, helm, and Skaffold v2.25.0 are installed. | Pin supported tool versions in setup docs. |
| D2.2 | PASS | Healthy Kind cluster is named jvm-rca. | Correct checklist text from rca to jvm-rca. |
| D2.3 | FAIL | recon.md has no Skaffold/manifests decision. | Record the deployment ownership decision. |
| D2.4 | PARTIAL | Infrastructure is Running, but each component has historical restarts. | Investigate or baseline restart counts. |
| D2.5 | PASS | All app deployments are 1/1 and have requests/limits. | Keep readiness in automated checks. |
| D2.6 | PASS | Customer 55/order 829 reached APPROVED; history also reports APPROVED; NPE count 0. | Keep response-key assertions in run_flow.sh. |
| D2.7 | FAIL | recon.md contains no CPU/RAM measurements. | Add sampling window and resource figures. |
| D2.8 | PARTIAL | Dry runs expand correctly, but up can pull/apply and down destroys the cluster. | Separate safe checks from destructive lifecycle targets. |
| D3.1 | PASS | One k6 run: 1,822 checks succeeded, 0 failed; HTTP failures 0%. | Save timestamped run output. |
| D3.2 | PASS | baseline.md has p95, error, approval, and 20 RPS; current error rate is also 0%. | Add exact script/configuration identifier. |
| D3.3 | PASS | Database has 828 APPROVED and no PENDING orders after the run. | Query this automatically after load testing. |
| D4.1 | PASS | Five targets and five JVM application labels are up; manifests configure metrics and OTel. | Replace :latest images with immutable digests. |
| D4.2 | PARTIAL | kube-prometheus-stack 93.1.1 and all monitoring pods are Ready. | Save Helm values in git. |
| D4.3 | PASS | All five application ServiceMonitor targets are up. | Alert on target loss. |
| D4.4 | PASS | JVM dashboard exists, repo JSON exists, and no DS placeholder remains. | Provision it declaratively. |
| D4.6 | FAIL | docs/queries.md is absent; eight queries cannot be run. | Add versioned PromQL and expected results. |
| D5.1 | PASS | Four Java app services have otel-agent init containers and JAVA_TOOL_OPTIONS. | Append JVM flags to the existing agent option. |
| D5.2 | PASS | Collector/Tempo Ready; Tempo ready was 200; recent export errors 0. | Add this to automated health checks. |
| D5.3 | FAIL | Tempo search did not return a POST /orders trace for the new flow. | Verify spans through gateway, outbox, CDC, and customer-service. |
| D6.1 | FAIL | terraform_kind exists and state is ignored, but Terraform is unavailable for validate/fmt. | Install Terraform; validate and document Loki/coverage. |

## Per-item discussion

### D1.1
README attribution, licensing, and a fork-change list are present. Without an upstream remote, license equivalence cannot be checked; keep an upstream reference.

### D1.2
All three prerequisite version commands succeeded. Done is justified; document supported versions.

### D1.3
This is covered by the repaired D2.6 deployment flow. Done is justified; preserve local-run evidence.

### D1.4
The recheck created a customer and order, then observed APPROVED in both order and history APIs. Done is justified; run this automatically.

### D1.5
recon.md documents poison-message recovery rather than the requested inventory. Done is not justified; add service, port, topic, group, and table facts.

### D1.6
The gateway build confirms reactive WebFlux, but recon.md omits the other four findings. Done is only partly justified; add file-backed evidence.

### D1.7
The prior-art document is absent. Done is not justified; add the requested comparison.

### D1.8
scope.md remains absent and untracked. Done is not justified; add and commit it.

### D2.1
kind, kubectl, helm, and Skaffold v2.25.0 all returned versions successfully. Done is justified; document supported tool versions.

### D2.2
The jvm-rca cluster and its node are healthy. Done is justified; fix the stale name in the checklist.

### D2.3
No Skaffold decision exists in recon.md. Done is not justified; record the rationale for plain manifests.

### D2.4
All infrastructure pods run, but historical restarts remain. Done is partly justified; explain or remove the instability.

### D2.5
Every app deployment is Ready and each has requests and limits. Done is justified; preserve this as a deployment gate.

### D2.6
Customer 55 and order 829 were created through the gateway and reached APPROVED in history. Done is justified; keep response-key validation.

### D2.7
No resource-use figures are recorded in recon.md. Done is not justified; add measured CPU/RAM data.

### D2.8
Dry-run expansion works, but the targets are lifecycle operations rather than safe idempotency proofs. Done is partly justified; split these concerns.

### D3.1
The single 25-second k6 run had 1,822 successful checks and zero HTTP failures. Done is justified; save machine-readable results.

### D3.2
baseline.md includes all requested metrics and its zero error rate agrees with this run. Done is justified; identify the producing k6 configuration.

### D3.3
The database has no PENDING orders and all 828 are APPROVED. Done is justified; automate the post-run assertion.

### D4.1
All Java service targets are up and expose JVM metrics; manifests contain metrics and agent setup. Done is justified; pin image digests.

### D4.2
The Helm stack and all monitoring pods are healthy, but saved values were not found. Done is partly justified; commit values.yaml.

### D4.3
All five ServiceMonitor targets report up. Done is justified; add an alert for regression.

### D4.4
The JVM dashboard is in Grafana and repository JSON, without a leftover datasource variable. Done is justified; provision it declaratively.

### D4.6
queries.md is absent. Done is not justified; add and execute eight PromQL queries.

### D5.1
All four Java application deployments have the init agent and JAVA_TOOL_OPTIONS. Done is justified; append scenario heap flags to the agent setting.

### D5.2
Tempo and collector are ready, and recent collector export errors are zero. Done is justified; add a recurring check.

### D5.3
The application flow succeeded, but Tempo did not return a matching POST /orders trace. Done is not justified; demonstrate the asynchronous span chain.

### D6.1
The module and ignore rules exist, but Terraform cannot run locally. Done is not justified; install Terraform and run required checks.

## Top 5 fixes before moving on

1. Prove and repair the complete POST /orders trace across outbox, CDC, and customer-service.
2. Add docs/queries.md and execute its eight PromQL queries.
3. Add recon inventory/config/resource evidence and record the Skaffold decision.
4. Add and commit docs/scope.md and docs/prior-art.md.
5. Install Terraform; commit Helm values and pin deployment images.

## Checklist corrections

- Change D2.2 from `rca` to `jvm-rca`.
- Remove Done marks from all FAIL items and make PARTIAL items explicitly incomplete.
- Reword D2.8 to distinguish dry-run inspection from destructive execution.
- Reword D4.1/D5.1 to require committed and live evidence for every Java service.
- Reword D3.2 to identify the exact script, configuration, and run date.
