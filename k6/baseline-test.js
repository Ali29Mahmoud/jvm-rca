import http from 'k6/http';
import { check } from 'k6';

const GATEWAY_URL = __ENV.GATEWAY_URL || 'http://localhost:8085';
const CUSTOMER_COUNT = Number(__ENV.CUSTOMER_COUNT) || 50;
const CREDIT_LIMIT = Number(__ENV.CREDIT_LIMIT) || 100000000; // $100M large credit limit

export const options = {
  scenarios: {
    constant_rate_orders: {
      executor: 'constant-arrival-rate',
      rate: 20,                // 20 orders per second
      timeUnit: '1s',
      duration: '10m',         // 10 minutes
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
};

export function setup() {
  console.log(`Setting up ${CUSTOMER_COUNT} customers with credit limit $${CREDIT_LIMIT} at ${GATEWAY_URL}...`);
  const customerIds = [];
  const headers = { 'Content-Type': 'application/json' };

  for (let i = 1; i <= CUSTOMER_COUNT; i++) {
    const payload = JSON.stringify({
      name: `Baseline Customer ${i}`,
      creditLimit: { amount: CREDIT_LIMIT },
    });

    const res = http.post(`${GATEWAY_URL}/customers`, payload, {
      headers,
      tags: { name: 'SetupCreateCustomer' },
    });

    const ok = check(res, {
      'setup customer created': (r) => r.status === 200 || r.status === 201,
    });

    if (ok) {
      try {
        const body = res.json();
        const cid = body.customerId || body.id;
        if (cid !== undefined && cid !== null) {
          customerIds.push(cid);
        }
      } catch (err) {
        console.error(`Failed to parse customer response: ${res.body}`);
      }
    }
  }

  console.log(`Setup finished. Created ${customerIds.length} customers.`);
  if (customerIds.length === 0) {
    throw new Error('Setup failed: No customers were created.');
  }

  return { customerIds };
}

export default function (data) {
  const customerIds = data.customerIds;
  const randomIndex = Math.floor(Math.random() * customerIds.length);
  const customerId = customerIds[randomIndex];
  const orderAmount = Math.floor(Math.random() * 100) + 10;

  const payload = JSON.stringify({
    customerId: customerId,
    orderTotal: { amount: orderAmount },
  });

  const headers = { 'Content-Type': 'application/json' };

  const res = http.post(`${GATEWAY_URL}/orders`, payload, {
    headers,
    tags: { name: 'CreateOrder' },
  });

  check(res, {
    'order created (200/201)': (r) => r.status === 200 || r.status === 201,
    'orderId returned': (r) => {
      try {
        const b = r.json();
        return b && (b.orderId !== undefined || b.id !== undefined);
      } catch {
        return false;
      }
    },
  });
}
