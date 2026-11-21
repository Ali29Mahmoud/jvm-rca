#!/usr/bin/env bash
# reset-environment.sh — Comprehensive reset procedure for jvm-rca:
# 1. Scale down consumer/producer applications (prevent race conditions during flush)
# 2. Database restore: TRUNCATE relational application tables (customer, orders, reservations, messages)
#    while preserving schema & flyway_schema_history
# 3. MongoDB cleanup: delete documents in customerView CQRS collection
# 4. Reset Kafka topics / offsets
# 5. Reset pg_stat_statements statistics
# 6. Scale applications back up and wait for readiness
set -euo pipefail

NS="eventuate-tram-examples-customers-and-orders"
KAFKA_BIN="/usr/local/kafka_2.13-3.2.3/bin"
BROKER="kafka:29092"

echo "=== [1/6] Scaling down producer and consumer services ==="
kubectl scale deploy/customer-service deploy/order-service deploy/order-history-service deploy/cdc-service \
  -n "$NS" --replicas=0

echo "Waiting for pods to scale down..."
kubectl wait --for=delete pod -l svc=customer-service -n "$NS" --timeout=60s || true
kubectl wait --for=delete pod -l svc=order-service -n "$NS" --timeout=60s || true
kubectl wait --for=delete pod -l svc=order-history-service -n "$NS" --timeout=60s || true
kubectl wait --for=delete pod -l svc=cdc-service -n "$NS" --timeout=60s || true

echo "=== [2/6] Resetting PostgreSQL database & pg_stat_statements ==="
PG_POD=$(kubectl get pod -n "$NS" -l role=postgres -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n "$NS" "$PG_POD" -- psql -U eventuate -d eventuate -v ON_ERROR_STOP=1 -c "
TRUNCATE TABLE 
  eventuate.orders,
  eventuate.customer_credit_reservations,
  eventuate.customer,
  eventuate.message,
  eventuate.received_messages
CASCADE;
"
echo "✓ Postgres tables truncated (schema & flyway history preserved)"

# Ensure extension is created and reset statement metrics
kubectl exec -n "$NS" "$PG_POD" -- psql -U eventuate -d eventuate -v ON_ERROR_STOP=1 -c "
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SELECT pg_stat_statements_reset();
"
echo "✓ pg_stat_statements reset"

echo "=== [3/6] Cleaning MongoDB CQRS views ==="
MONGO_POD=$(kubectl get pod -n "$NS" -l role=mongodb -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NS" "$MONGO_POD" -- mongosh customers_and_orders --quiet --eval "
db.customerView.deleteMany({});
"
echo "✓ MongoDB customerView collection cleaned"

echo "=== [4/6] Clearing fault flags and Chaos Mesh experiments ==="
# Chaos experiments are benchmark fault flags. Delete only resources in the
# application namespace; ignore missing CRDs/resources so reset is repeatable.
for resource in podchaos networkchaos stresschaos iochaos timechaos kernelchaos dnschaos httpchaos; do
  kubectl delete "$resource" --all -n "$NS" --ignore-not-found=true 2>/dev/null || true
done
kubectl delete schedule --all -n "$NS" --ignore-not-found=true 2>/dev/null || true
echo "✓ Namespaced Chaos Mesh experiments cleared"

echo "=== [5/7] Resetting Kafka topics and consumer offsets ==="
# Kafka in this cluster uses ephemeral broker storage. Restarting the broker
# clears topic data; restarting consumers below establishes fresh group state.
kubectl rollout restart deploy/kafka -n "$NS"
kubectl rollout status deploy/kafka -n "$NS" --timeout=90s
echo "✓ Kafka broker restarted; ephemeral topic data reset"

echo "=== [6/7] Scaling microservices back up ==="
kubectl scale deploy/cdc-service deploy/customer-service deploy/order-service deploy/order-history-service \
  -n "$NS" --replicas=1

echo "Waiting for microservices to roll out and become Ready..."
kubectl rollout status deploy/cdc-service -n "$NS" --timeout=90s
kubectl rollout status deploy/customer-service -n "$NS" --timeout=90s
kubectl rollout status deploy/order-service -n "$NS" --timeout=90s
kubectl rollout status deploy/order-history-service -n "$NS" --timeout=90s

echo "=== [7/7] Baseline pod health ==="
kubectl wait --for=condition=ready pod -l svc=customer-service -n "$NS" --timeout=120s
kubectl wait --for=condition=ready pod -l svc=order-service -n "$NS" --timeout=120s
kubectl wait --for=condition=ready pod -l svc=order-history-service -n "$NS" --timeout=120s
kubectl wait --for=condition=ready pod -l svc=cdc-service -n "$NS" --timeout=120s
echo "✓ Application pods are Ready"

echo "=== Reset Completed Successfully ==="
kubectl get pods -n "$NS"
