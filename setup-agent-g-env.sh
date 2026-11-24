# Setup environment for Agent-G benchmark
# Usage: source setup-agent-g-env.sh

# 1. Fetch Gemini API key from Kubernetes cluster secret
export GEMINI_API_KEY="$(kubectl -n eventuate-tram-examples-customers-and-orders get secret holmes-gemini-secret -o jsonpath='{.data.api-key}' 2>/dev/null | base64 --decode)"

# 2. Clear any lingering OpenRouter overrides
unset BENCH_LLM_API_KEY BENCH_LLM_BASE_URL OPENROUTER_API_KEY

# 3. Benchmark LLM configuration (disables hidden thinking so JSON outputs properly)
export BENCH_LLM_MODEL='gemini-3.1-flash-lite'
export BENCH_LLM_REASONING_EFFORT='none'
export BENCH_LLM_MAX_TOKENS='2000'

# 4. Hide massive raw output from printed terminal JSON by default
export BENCH_HIDE_RAW='true'

# 5. Local telemetry endpoints
export PROMETHEUS_URL=http://127.0.0.1:9090
export LOKI_URL=http://127.0.0.1:3100
export JAEGER_URL=http://127.0.0.1:3200

echo "Agent-G environment configured successfully!"
echo "Model: $BENCH_LLM_MODEL | Reasoning effort: $BENCH_LLM_REASONING_EFFORT | Hide raw: $BENCH_HIDE_RAW"
