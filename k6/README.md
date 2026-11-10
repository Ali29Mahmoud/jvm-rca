# k6 Load Testing

This directory contains k6 load testing scripts for the Customers and Orders application through the API Gateway.

## Script: `load-test.js`

- **Setup phase:**
  - Creates 50 customers (configurable via `CUSTOMER_COUNT`) with a high credit limit ($1,000,000 by default, configurable via `CREDIT_LIMIT`).
  - Collects their generated `customerId`s.
- **Main test loop (VU iterations):**
  - Selects a customer at random from the pool created in the setup phase.
  - Sends a `POST /orders` request through the API Gateway.
  - Verifies HTTP 200/201 response and validates the returned `orderId`.

## How to Run

1. Ensure the API Gateway port-forward is active (if running from host):
   ```bash
   kubectl port-forward svc/api-gateway-service -n eventuate-tram-examples-customers-and-orders 8085:8080
   ```

2. Run with default scenario (ramping up to 20 VUs):
   ```bash
   k6 run k6/load-test.js
   ```

3. Customize parameters with environment variables:
   ```bash
   k6 run \
     -e GATEWAY_URL=http://localhost:8085 \
     -e CUSTOMER_COUNT=50 \
     -e CREDIT_LIMIT=5000000 \
     k6/load-test.js
   ```

4. Run a quick smoke run:
   ```bash
   k6 run --vus 5 --duration 30s k6/load-test.js
   ```
