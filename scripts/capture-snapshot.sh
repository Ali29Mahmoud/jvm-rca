#!/usr/bin/env bash
# capture-snapshot.sh — Captures a full snapshot of the cluster state:
# 1. Pods & resource utilization
# 2. Database state (Postgres tables count + MongoDB count)
# 3. pg_stat_statements metrics
# 4. Kafka topic offsets & lag
# 5. Prometheus JVM metrics (heap usage, gc duration, thread counts)
set -euo pipefail

SNAPSHOT_DIR="${1:-snapshots/healthy-baseline}"
mkdir -p "$SNAPSHOT_DIR"

NS="eventuate-tram-examples-customers-and-orders"
DATE_STR=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "=== Capturing snapshot to $SNAPSHOT_DIR ($DATE_STR) ==="

# 1. Kubernetes cluster & pod state
echo "Capturing pod state..."
kubectl get pods -n "$NS" -o wide > "$SNAPSHOT_DIR/pods.txt"
kubectl describe pods -n "$NS" > "$SNAPSHOT_DIR/pods-describe.txt"
kubectl top pods -n "$NS" 2>/dev/null > "$SNAPSHOT_DIR/pods-top.txt" || true

# 2. Postgres data state
echo "Capturing Postgres state..."
PG_POD=$(kubectl get pod -n "$NS" -l role=postgres -o jsonpath='{.items[0].metadata.name}')
cat << 'EOF' > /tmp/pg-stats-query.sql
SELECT 
  schemaname, 
  relname as table_name, 
  n_live_tup as row_count 
FROM pg_stat_user_tables 
WHERE schemaname = 'eventuate'
ORDER BY relname;
EOF
kubectl exec -i -n "$NS" "$PG_POD" -- psql -U eventuate -d eventuate < /tmp/pg-stats-query.sql > "$SNAPSHOT_DIR/postgres-table-counts.txt"

# 3. pg_stat_statements
echo "Capturing pg_stat_statements metrics..."
cat << 'EOF' > /tmp/pg-statements-query.sql
SELECT 
  calls, 
  round(total_exec_time::numeric, 2) AS total_ms, 
  round(mean_exec_time::numeric, 2) AS mean_ms, 
  rows, 
  substr(query, 1, 100) AS query 
FROM pg_stat_statements 
ORDER BY calls DESC 
LIMIT 30;
EOF
kubectl exec -i -n "$NS" "$PG_POD" -- psql -U eventuate -d eventuate < /tmp/pg-statements-query.sql > "$SNAPSHOT_DIR/pg_stat_statements.txt"

# 4. MongoDB state
echo "Capturing MongoDB state..."
MONGO_POD=$(kubectl get pod -n "$NS" -l role=mongodb -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NS" "$MONGO_POD" -- mongosh customers_and_orders --quiet --eval "
print('customerView count: ' + db.customerView.countDocuments());
printjson(db.customerView.find().limit(5).toArray());
" > "$SNAPSHOT_DIR/mongodb-state.txt"

# 5. Kafka state
echo "Capturing Kafka topic and consumer group offsets..."
KAFKA_POD=$(kubectl get pod -n "$NS" -l role=kafka -o jsonpath='{.items[0].metadata.name}')
KAFKA_BIN="/usr/local/kafka_2.13-3.2.3/bin"
BROKER="kafka:29092"

kubectl exec -n "$NS" "$KAFKA_POD" -- "$KAFKA_BIN/kafka-topics.sh" --bootstrap-server "$BROKER" --describe > "$SNAPSHOT_DIR/kafka-topics.txt"

for group in customerHistoryServiceEvents customerServiceEvents OrderEventConsumer; do
  echo "--- Group: $group ---" >> "$SNAPSHOT_DIR/kafka-consumer-groups.txt"
  kubectl exec -n "$NS" "$KAFKA_POD" -- "$KAFKA_BIN/kafka-consumer-groups.sh" --bootstrap-server "$BROKER" --describe --group "$group" >> "$SNAPSHOT_DIR/kafka-consumer-groups.txt" 2>&1 || true
done

# 6. Prometheus telemetry (port-forward if needed)
echo "Capturing Prometheus telemetry snapshot..."
PF_STARTED=false
if ! curl -sf http://localhost:9090/-/ready >/dev/null 2>&1; then
  kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n monitoring 9090:9090 >/tmp/prom-snap-pf.log 2>&1 &
  PF_PID=$!
  PF_STARTED=true
  sleep 2
fi

query_prom() {
  local query="$1"
  local outfile="$2"
  curl -s --data-urlencode "query=$query" "http://localhost:9090/api/v1/query" | python3 -m json.tool > "$outfile"
}

query_prom 'jvm_memory_used_bytes{area="heap"}' "$SNAPSHOT_DIR/prom-jvm-heap-used.json"
query_prom 'process_cpu_usage' "$SNAPSHOT_DIR/prom-cpu-usage.json"
query_prom 'jvm_threads_live_threads' "$SNAPSHOT_DIR/prom-jvm-threads.json"
query_prom 'jvm_gc_pause_seconds_count' "$SNAPSHOT_DIR/prom-jvm-gc-count.json"

if [ "$PF_STARTED" = true ]; then
  kill -9 "$PF_PID" 2>/dev/null || true
fi

# Metadata file
cat << EOF > "$SNAPSHOT_DIR/metadata.json"
{
  "timestamp": "$DATE_STR",
  "namespace": "$NS",
  "status": "healthy-baseline"
}
EOF

echo "✓ Snapshot captured successfully in $SNAPSHOT_DIR"
