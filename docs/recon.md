# Recon

## Poison message in customer-service

### What was sent

An `OrderCreatedEvent` whose payload has **no `customerId`** — an order created with a
null customer id (a shell variable was empty when the order was posted). It landed in
Kafka at `io.eventuate.examples.tram.ordersandcustomers.orders.domain.Order`
partition **1**, offset **0** (order 1, `2026-11-13T10:33:49Z`):

```json
{"payload":"{\"orderDetails\":{\"orderTotal\":{\"amount\":100}}}",
 "headers":{"event-type":"...OrderCreatedEvent","event-aggregate-id":"1","DATE":"Fri, 13 Nov 2026 10:33:49 GMT"}}
```

Two more of the same kind were produced later by the same client when it could not get a
customer id: order 6 (p0/3, 10:53:52Z, POST /customers got 500 while customer-service was
scaled to 0) and order 9 (11:00:31Z, POST /customers hit the gateway's 1 s circuit-breaker
timeout). Both are poison for the same handler.

### Error text

```
Caused by: java.lang.NullPointerException: Cannot invoke "java.lang.Long.longValue()"
  because the return value of "...orders.domain.OrderDetails.customerId()" is null
    at ...customers.eventhandlers.OrderEventConsumer.handleOrderCreatedEvent(OrderEventConsumer.java:24)
ERROR i.e.m.k.consumer.SwimlaneDispatcher - Exception handling message - terminating
```

### Which service and group

- Service: **customer-service** (the only service with the NPE; order-service and
  order-history-service logged none).
- Consumer group: **`OrderEventConsumer`**, subscribed to topic
  `io.eventuate.examples.tram.ordersandcustomers.orders.domain.Order` (2 partitions).
- Kafka CLI: `/usr/local/kafka_2.13-3.2.3/bin/kafka-consumer-groups.sh`,
  bootstrap `kafka:29092`, run via `kubectl exec -n <ns> deploy/kafka`.

The failure mode: the handler throws, `SwimlaneDispatcher` terminates the consumer thread,
and because the failing record is never committed the group restarts at the same offset.
`kafka-consumer-groups --describe --group OrderEventConsumer` therefore reported
**"Consumer group 'OrderEventConsumer' does not exist"** — no offsets were ever committed.
On every restart the consumer logged `Found no committed offset for partition ...` and
`Resetting offset ... to position FetchPosition{offset=0}`, i.e. it re-reads the poison
record first and dies again. Restarting the deployment does not help.

### How it was detected

1. `kubectl logs -n $NS deploy/customer-service --since=15m | grep -c NullPointerException` → 4
   (order-service and order-history-service → 0).
2. The lag of every *other* group was 0, yet orders stayed `PENDING`, so the stall was
   behind the customer-service consumer, not somewhere else.
3. Reading the topic with `kafka-console-consumer.sh --partition 1 --offset 0` showed the
   null-customer record as the first message of that partition.

### Exact recovery commands

```bash
NS=eventuate-tram-examples-customers-and-orders
T=io.eventuate.examples.tram.ordersandcustomers.orders.domain.Order
K=/usr/local/kafka_2.13-3.2.3/bin/kafka-consumer-groups.sh

# 1. stop the consumer, offsets can only be reset with no active members
kubectl scale deploy/customer-service -n $NS --replicas=0
kubectl get pods -n $NS -l svc=customer-service          # no pods

# 2. dry run, read the output: only the intended group/topic/partitions
kubectl exec -n $NS deploy/kafka -- sh -c "$K --bootstrap-server kafka:29092 \
  --reset-offsets --group OrderEventConsumer --topic $T --to-latest --dry-run"

# 3. execute
kubectl exec -n $NS deploy/kafka -- sh -c "$K --bootstrap-server kafka:29092 \
  --reset-offsets --group OrderEventConsumer --topic $T --to-latest --execute"

# 4. bring it back
kubectl scale deploy/customer-service -n $NS --replicas=1
kubectl rollout status deploy/customer-service -n $NS --timeout=180s
```

An exact skip of the poison record was attempted first and **worked for that one record**:
`--topic $T:0 --to-offset 2` / `--topic $T:1 --to-offset 1 --execute` (dry run checked
first). Orders 3, 4 and 5 were then approved at 10:55:52. It was not sufficient because a
new null-customer record arrived while the service was down (see above), so the group was
reset `--to-latest` instead. This skips unprocessed records, including valid orders 7 and 8,
which stay `PENDING`; new traffic is processed normally.

Reusable form: `scripts/reset-consumer-group.sh customer-service OrderEventConsumer [--execute]`
(dry run by default; scales down, waits for no active members, resets `--all-topics
--to-latest`, and always scales back to 1).

### Numbers before and after

| Item | Before | After |
|---|---|---|
| `OrderEventConsumer` group | did not exist / no committed offsets | p0 offset 9 = log-end 9, p1 8 = 8, **lag 0**, 1 member |
| Order topic log-end | p0 2, p1 3 | p0 9, p1 8 |
| customer-service NPE (15 min) | 4 | 0 |
| `customerServiceEvents` lag | 0 | 0 (Customer p0/p1 8/8) |
| `customerHistoryServiceEvents` lag | 0 | 0 (Customer 8/8, Order 9/8) |
| Pod restarts | gateway 1, cdc 2, customer 0, kafka 3, mongo 1, order-history 1, order 5, otel 1, postgres 1, tempo 1, zookeeper 1 | unchanged, customer-service 0 |
| Test order via gateway | stayed `PENDING` > 10 s | order 11 `APPROVED` in 1 s |

### Outbox

`eventuate.message` (Postgres `eventuate` db, `psql -U eventuate -d eventuate` inside the
postgres pod) held 11 rows, all `published = 0` (5 Order, 6 Customer events); not modified.

Scenario S09 (poison message): confirmed that one order created with a null customerId stalls the consumer permanently, and the stall survives restarts.
