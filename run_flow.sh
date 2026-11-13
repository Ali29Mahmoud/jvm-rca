#!/usr/bin/env bash
# run_flow.sh — end-to-end curl smoke test through the API Gateway port-forward.
# Exits non-zero if any step fails or the order is not APPROVED within the wait window.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

NS="eventuate-tram-examples-customers-and-orders"
GW_PORT=8085
GW="http://127.0.0.1:${GW_PORT}"
START_TS=$(date +%s)

# ── Port-forward (cleanup on exit) ──────────────────────────────────────────
kubectl port-forward svc/api-gateway-service -n "$NS" "${GW_PORT}:8080" \
  > /tmp/gw-pf.log 2>&1 &
PF_PID=$!
trap 'kill -9 "$PF_PID" 2>/dev/null || true' EXIT

echo "→ Waiting for gateway on :${GW_PORT}..."
for i in $(seq 1 40); do
  curl -sf "${GW}/actuator/health" > /dev/null 2>&1 && break
  sleep 0.5
  if [[ "$i" == "40" ]]; then
    echo "✗ Gateway not reachable after 20 s. Aborting." >&2
    exit 1
  fi
done
echo "✓ Gateway up"
echo ""

# ── 1. Health ────────────────────────────────────────────────────────────────
echo "▶ 1. Gateway health"
curl -s "${GW}/actuator/health" | jq .
echo ""

# ── 2. Create Customer ───────────────────────────────────────────────────────
echo "▶ 2. Create customer"
CUSTOMER_RESP=$(curl -sf -X POST "${GW}/customers" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test User","creditLimit":{"amount":500}}')
echo "$CUSTOMER_RESP" | jq .
CUSTOMER_ID=$(echo "$CUSTOMER_RESP" | jq -r '.customerId')
echo "   → customerId=${CUSTOMER_ID}"
echo ""

# ── 3. List Customers ────────────────────────────────────────────────────────
echo "▶ 3. Get all customers"
curl -sf "${GW}/customers" | jq .
echo ""

# ── 4. Create Order (Saga) ───────────────────────────────────────────────────
echo "▶ 4. Create order (triggers saga)"
ORDER_RESP=$(curl -sf -X POST "${GW}/orders" \
  -H "Content-Type: application/json" \
  -d "{\"customerId\":${CUSTOMER_ID},\"orderTotal\":{\"amount\":150}}")
echo "$ORDER_RESP" | jq .
ORDER_ID=$(echo "$ORDER_RESP" | jq -r '.orderId')
echo "   → orderId=${ORDER_ID}"
echo ""

# ── 5. Poll for APPROVED ─────────────────────────────────────────────────────
echo "▶ 5. Polling order state (expect APPROVED within 10 s)..."
for i in $(seq 1 20); do
  STATE=$(curl -sf "${GW}/orders/${ORDER_ID}" | jq -r '.orderState // .state')
  echo "   attempt $i — state=${STATE}"
  if [[ "$STATE" == "APPROVED" ]]; then break; fi
  sleep 0.5
  if [[ "$i" == "20" ]]; then
    echo "✗ Order not APPROVED after 10 s" >&2
    exit 1
  fi
done
echo ""

# ── 6. Order History (CQRS / MongoDB) ───────────────────────────────────────
echo "▶ 6. Order history (CQRS / MongoDB)"
sleep 1   # brief extra wait for event propagation
curl -sf "${GW}/customers/${CUSTOMER_ID}/orderhistory" | jq .
echo ""

END_TS=$(date +%s)
echo "✓ All checks passed in $(( END_TS - START_TS )) seconds."
