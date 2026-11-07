# Project scope

## Purpose

Measure how well AI SRE agents diagnose failures in a Java microservice system
(Spring Boot, Kafka, PostgreSQL), and test whether an agent with JVM, Kafka and
Postgres specific tools does better than agents with generic tools.

## Research questions

1. Does domain-specific tooling (JVM, Kafka, Postgres) improve root-cause
   accuracy compared with generic tooling, using the same LLM?
2. Which failure categories are hardest for all agents?
3. What are the cost, time and safety trade-offs?

## System under test

A fork of eventuate-tram-examples-customers-and-orders (Eventuate, Inc.,
Apache License 2.0). It is deployed on a local Kind cluster and instrumented
with metrics, traces and logs. Its code is changed as little as possible; any
change is listed in the README and kept in `patches/`.

## What will be built

- A set of about 15 fault scenarios, injected from outside the application
  code, each with written ground truth (root cause, culprit, expert evidence,
  correct fix) and an automated symptom check.
- A harness that resets the system, injects a fault, runs an agent under fixed
  budgets, scores the result and stores it.
- An agent with generic tools (Agent-G) and the same agent plus JVM, Kafka,
  Postgres and CDC tools (Agent-J), with human-approved remediation.
- A comparison against OpenSRE, HolmesGPT and a single-prompt control.
- A results dashboard, a write-up and a short demo video.

## In scope

- One Kind cluster, one target system.
- Agents compared: Control, Agent-G, Agent-J, OpenSRE, HolmesGPT.
- At least 3 repeats per scenario and agent on a held-out test set.
- Metrics: category accuracy, culprit accuracy, evidence quality, remediation
  success, safety violations, time, steps, cost, and variance.

## Out of scope

- Changing the target system's business logic.
- Fully automatic remediation without human approval.
- Multi-cluster or cloud deployment.
- Stretch goals unless time is left: mobile approval app, graph-based
  localizer, fine-tuned model, React and TypeScript dashboard.

## Success criteria

- At least 14 reproducible scenarios with automated symptom checks.
- At least 4 agent variants compared, each with 3 repeats on the test set.
- Results reported with confidence intervals and a failure taxonomy.
- One-command reproduction on a clean clone.
- Public repository with README, dashboard screenshots, write-up and demo.

## Fairness rules

- Same LLM (or a documented difference) and same telemetry for all agents.
- Same step, time and token budgets.
- Tune only on the dev set; freeze the test set before the final runs.
- Publish all runs, including failures and negative results.
- Pin and publish all versions.

## Time plan

24 working days of 6 hours (144 hours), with a rest or catch-up day each week.
- Week 1: deploy, instrument and observe the system, understand it.
- Week 2: scenarios and harness.
- Week 3: scoring, agents and competitor integration.
- Week 4: experiments, analysis, dashboard, CI, documentation, write-up.

## Assumptions to verify (Days 1 to 3)

- The stack fits on my machine.
- Each scenario can be injected without code changes (see the recon notes).
- OpenSRE and HolmesGPT can run against this system.
- Eventuate Tram's behavior on malformed messages (needed for the poison
  message scenario).

## Related work

AIOpsLab (Microsoft) and ITBench (IBM) are existing benchmarks for AI agents
on incident diagnosis. See `docs/prior-art.md`. This project focuses on JVM,
Kafka and Postgres failure modes.

## License note

The target system is Apache 2.0. This fork keeps its license and copyright
notices, marks changed files, and credits the upstream project in the README.