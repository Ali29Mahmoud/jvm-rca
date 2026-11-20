#!/usr/bin/env bash
set -euo pipefail

mkdir -p docs

# Dynamically resolve the postgres pod name
NAMESPACE="eventuate-tram-examples-customers-and-orders"
POSTGRES_POD=$(kubectl get pod -n "$NAMESPACE" -l role=postgres -o jsonpath='{.items[0].metadata.name}')

# Get initial max order ID
START_MAX_ID=$(kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- \
  psql -U eventuate -d eventuate -t -A -c "SELECT COALESCE(MAX(id), 0) FROM eventuate.orders;")
echo "Initial max order ID: ${START_MAX_ID}"

# Port-forward API Gateway
kubectl port-forward svc/api-gateway-service -n "$NAMESPACE" 8085:8080 > /tmp/baseline-pf.log 2>&1 &
PF_PID=$!
trap 'kill -9 "$PF_PID" 2>/dev/null || true' EXIT

echo "Waiting for gateway..."
for i in $(seq 1 30); do
  curl -sf http://localhost:8085/actuator/health > /dev/null 2>&1 && break
  sleep 0.5
done
echo "Gateway connected."

# Run k6 with dashboard HTML export
echo "Starting 10-minute k6 baseline test at 20 RPS..."
GATEWAY_URL="http://localhost:8085" K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_EXPORT=docs/baseline-report.html \
  k6 run k6/baseline-test.js 2>&1 | tee docs/baseline-k6.log

echo "Baseline load test finished. Waiting 10s for in-flight sagas to complete..."
sleep 10

END_MAX_ID=$(kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- \
  psql -U eventuate -d eventuate -t -A -c "SELECT COALESCE(MAX(id), 0) FROM eventuate.orders;")
echo "Ending max order ID: ${END_MAX_ID}"

# Query order states for orders created during this test
STATE_STATS=$(kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- \
  psql -U eventuate -d eventuate -c "SELECT state, count(*) FROM eventuate.orders WHERE id > ${START_MAX_ID} GROUP BY state;")
echo "Order states:"
echo "$STATE_STATS"

echo "$STATE_STATS" > docs/order-states.txt
echo "START_MAX_ID=${START_MAX_ID}" >> docs/order-states.txt
echo "END_MAX_ID=${END_MAX_ID}" >> docs/order-states.txt
