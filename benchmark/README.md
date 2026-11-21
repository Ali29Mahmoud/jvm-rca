# Benchmark agents

## Control agent

The `control` agent makes exactly one OpenAI-compatible chat completion call and
has no tools. It receives the scenario description, alert context, target service,
and symptom query definition, but no ground truth or observed telemetry. Its JSON
response is validated against the strict `Diagnosis` model.

Configure an API key using `BENCH_LLM_API_KEY`, `GEMINI_API_KEY`, or
`OPENAI_API_KEY`. When `GEMINI_API_KEY` is set, the adapter defaults to Gemini's
OpenAI-compatible endpoint and `gemini-3.8-flash`. Otherwise it defaults to the
OpenAI endpoint and `gpt-4o-mini`. Override the endpoint with
`BENCH_LLM_BASE_URL` or `OPENAI_BASE_URL`, and override the model with
`BENCH_LLM_MODEL` or `OPENAI_MODEL`.

From the repository root:

```bash
python3 -m benchmark.harness run --scenario S01 --agent control
```

The call is not made by tests. Tests inject a fixed response and verify the
single-request, no-tools contract.
