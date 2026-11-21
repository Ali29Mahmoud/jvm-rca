# AI SRE agent spikes

Date: 2026-11-21  
Cluster: `kind-jvm-rca`  
Target namespace: `eventuate-tram-examples-customers-and-orders`

## Environment and incident

- Prometheus: `http://monitoring-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090`
- Loki: `http://loki.monitoring.svc.cluster.local:3100`
- Both services were reachable and healthy from inside the cluster.
- The workload had earlier startup probe warnings during a prior pod replacement. By the test, `customer-service-698dcfbb56-wnbcf` had been running for about 30 minutes with zero container restarts.
- At approximately `2026-11-21 10:41 UTC`, the test deliberately deleted that one pod with `kubectl delete pod ... --grace-period=0 --wait=false`. The Deployment created `customer-service-698dcfbb56-pp98j`; it is now `1/1 Running` with zero restarts. Its startup produced brief readiness probe connection-refused/timeout events before recovering.
- Prometheus returned `success` for `up` (24 series from Holmes' pod) and reported zero restarts for the replacement. Loki returned customer-service logs for the test window; the sampled entries were normal actuator/health requests ending in `200 OK`.

## OpenSRE

- **Setup steps:** OpenSRE's documented local stack is `cd OpenSRE && make dev`. For this spike, the Compose services were run with isolated `opensre-spike-*` database/session volumes and a temporary override (`docker-compose.yml` plus `--profile litellm`). The LiteLLM config mapped the Claude Agent SDK's Anthropic Messages requests to Gemini:

  ```yaml
  model_list:
    - model_name: "*"
      litellm_params:
        model: gemini/gemini-3.1-flash-lite
        api_key: os.environ/GEMINI_API_KEY
  ```

  The agent used `ANTHROPIC_BASE_URL=http://litellm:4000`, `PROMETHEUS_URL=http://host.docker.internal:19090`, and `LOKI_URL=http://host.docker.internal:13100`. A namespace-scoped read-only Kubernetes service account was mounted into the agent. Host-only port forwards exposed the in-cluster Prometheus and Loki services on those ports to the Compose network. The OpenSRE agent and its dependencies started, and the agent container independently queried Kubernetes, Prometheus, and Loki successfully.
- **LLM provider needed:** OpenSRE uses the Claude Agent SDK and works natively with an Anthropic API key. Gemini requires a compatible proxy such as LiteLLM or the repository's credential proxy. The checked-in local LiteLLM generator only creates NVIDIA/OpenRouter configurations; direct Gemini requires additional configuration. The supplied Gemini key could list models and worked with Holmes, but OpenSRE's larger prompt triggered Gemini's free-tier cached-content limit (`429`, cached-content storage limit `0`, request `39,581` tokens). Gemini also returned a temporary high-demand `503` during the run.
- **Result:** No OpenSRE RCA report was produced. Its Gemini request failed before investigation tools ran. Direct checks from the configured OpenSRE container did succeed: its read-only Kubernetes credentials listed the target namespace, its Prometheus script returned `success` for `up` and zero restarts for the replacement, and its Loki script returned five customer-service entries with normal actuator `200 OK` responses. These were connectivity checks, not an OpenSRE-generated analysis.
- **Go/no-go:** **NO-GO with the supplied Gemini setup.** The telemetry wiring works, but the agent could not complete an investigation because the free-tier cache quota is zero and the model was intermittently unavailable. Revisit with Anthropic credentials or a Gemini account/proxy configuration that supports the SDK's prompt-caching request size.

## HolmesGPT

- **Setup steps:** Installed the official standalone Helm chart `robusta/holmes` version `0.46.0` into the target namespace. Created Kubernetes Secret `holmes-gemini` with `GEMINI_API_KEY`; set `MODEL`, `TOOL_SCHEMA_NO_PARAM_OBJECT_IF_NO_PARAMS=true`, and a Gemini model list entry. Enabled `kubernetes/core`, `kubernetes/logs`, `prometheus/metrics` pointing to the Prometheus service above, and `grafana/loki` pointing directly to Loki. Set `namespaceScopedRBAC: true` and `k8sRBAC: false`, giving Holmes read-only access in the target namespace. The chart repository is `https://robusta-charts.storage.googleapis.com`.

  The install commands were:

  ```bash
  kubectl -n eventuate-tram-examples-customers-and-orders create secret generic holmes-gemini \
    --from-literal=GEMINI_API_KEY="$GEMINI_API_KEY"
  helm repo add robusta https://robusta-charts.storage.googleapis.com
  helm upgrade --install holmes robusta/holmes --version 0.46.0 \
    --namespace eventuate-tram-examples-customers-and-orders -f values.yaml
  ```

  The essential Helm values were:

  ```yaml
  namespaceScopedRBAC: true
  k8sRBAC: false
  extraEnvVarsSecrets:
    - holmes-gemini
  additionalEnvVars:
    - name: TOOL_SCHEMA_NO_PARAM_OBJECT_IF_NO_PARAMS
      value: "true"
    - name: MODEL
      value: gemini-3.1-flash-lite
  modelList:
    gemini-3.1-flash-lite:
      api_key: envRef:GEMINI_API_KEY
      model: gemini/gemini-3.1-flash-lite
  toolsets:
    kubernetes/core:
      enabled: true
    kubernetes/logs:
      enabled: true
    prometheus/metrics:
      enabled: true
      subtype: prometheus
      config:
        prometheus_url: http://monitoring-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090
    grafana/loki:
      enabled: true
      config:
        api_url: http://loki.monitoring.svc.cluster.local:3100
  ```
- **LLM provider needed:** Holmes supports Gemini through LiteLLM. The spike used `gemini-3.1-flash-lite`; `gemini-2.5-flash` was unavailable to this account, `gemini-3.8-flash` returned a high-demand `503`, and `gemini-3.7-flash` timed out. The 3.1 Flash Lite model completed the investigation calls.
- **Result:** Holmes' Kubernetes, Prometheus, and Loki toolsets initialized successfully. It returned a report that correctly noted the replacement was healthy with zero container restarts. However, its first pass failed to retrieve events and guessed a Loki tool name. On follow-up, it found the startup probe warnings and actuator logs but conflated older startup events with the deliberate deletion: it said the original pod had been killed by the controller, although the test explicitly deleted it after it had been running for about 30 minutes. The replacement did show brief probe failures during startup and then recovered. No underlying cause for the injected deletion exists; the available logs/metrics did not establish a cause for the separate earlier probe warnings.
- **Go/no-go:** **NO-GO for unsupervised RCA in this spike.** The tools can query all three sources, but the report mixed historical probe events with the test action and made an incorrect causal claim. A supervised, narrower rerun is reasonable after improving the time-window/tool guidance.

## Credential handling

The Gemini key was stored in the target namespace as Secret `holmes-gemini` for the installed Holmes deployment. The temporary OpenSRE Compose stack and its Gemini environment were removed after the failed run. The key is not present in this file. Since it was shared in chat, rotate it before using it beyond this spike.
