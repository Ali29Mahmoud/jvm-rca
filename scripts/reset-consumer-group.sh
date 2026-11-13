#!/bin/sh
# reset-consumer-group.sh — unstick an Eventuate Tram Kafka consumer by skipping
# its backlog (`--to-latest`). Used as the reset step of the benchmark harness.
#
# usage: scripts/reset-consumer-group.sh <deployment> <consumer-group> [--execute]
#
#   <deployment>      deployment to scale down/up (e.g. customer-service)
#   <consumer-group>  Kafka consumer group to reset (e.g. OrderEventConsumer)
#   --execute         actually apply the reset; without it this is a dry run
#
# Offsets can only be reset while the group has no active members, so the
# deployment is scaled to 0 first and is always scaled back to 1 on exit.
set -eu

CONTEXT=kind-jvm-rca
NS=eventuate-tram-examples-customers-and-orders
KAFKA_BIN=/usr/local/kafka_2.13-3.2.3/bin
KAFKA_DEPLOY=kafka
BROKER=kafka:29092

if [ $# -lt 2 ]; then
  echo "usage: $0 <deployment> <consumer-group> [--execute]" >&2
  exit 2
fi

DEPLOY=$1
GROUP=$2
MODE=--dry-run
if [ "${3:-}" = "--execute" ]; then
  MODE=--execute
fi

if [ "$(kubectl config current-context)" != "$CONTEXT" ]; then
  echo "refusing to run: kubectl context is not $CONTEXT" >&2
  exit 1
fi

# Run a Kafka CLI command inside the broker pod.
kafka() {
  kubectl exec -n "$NS" "deploy/$KAFKA_DEPLOY" -- sh -c "$KAFKA_BIN/kafka-consumer-groups.sh --bootstrap-server $BROKER $*"
}

# Always bring the consumer back, even if the reset fails.
restore() {
  echo ">> scaling $DEPLOY back to 1"
  kubectl scale deploy/"$DEPLOY" -n "$NS" --replicas=1 >/dev/null
  kubectl rollout status deploy/"$DEPLOY" -n "$NS" --timeout=180s || true
}
trap restore EXIT
trap 'exit 130' INT TERM

echo ">> scaling $DEPLOY to 0"
kubectl scale deploy/"$DEPLOY" -n "$NS" --replicas=0 >/dev/null

# Wait for the pods to go away (up to 60s). status.replicas is absent when 0.
i=0
while [ "$i" -lt 60 ]; do
  replicas=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.replicas}')
  case "$replicas" in ""|0) break ;; esac
  i=$((i + 1)); sleep 1
done
[ "$i" -lt 60 ] || { echo "warning: $DEPLOY still has replicas after 60s" >&2; }

# Wait until the group reports no active members (a missing group is also fine).
i=0
while [ "$i" -lt 60 ]; do
  out=$(kafka --describe --group "$GROUP" 2>&1 || true)
  case "$out" in
    *"does not exist"*|*"has no active members"*) break ;;
  esac
  i=$((i + 1)); sleep 1
done
[ "$i" -lt 60 ] || { echo "error: group $GROUP still has active members" >&2; exit 1; }

echo ">> resetting $GROUP to latest ($MODE)"
kafka --reset-offsets --group "$GROUP" --all-topics --to-latest "$MODE"

# Show the resulting offsets so the caller can see the reset took effect.
if [ "$MODE" = "--execute" ]; then
  kafka --describe --group "$GROUP"
fi
