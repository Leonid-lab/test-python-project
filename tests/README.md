# Test matrix (T01–T30)

Run all tests inside Docker (PostgreSQL + RabbitMQ):

```bash
docker-compose stop consumer
docker-compose run --rm api pytest -q
```

Unit only:

```bash
docker-compose run --rm api pytest -q -m unit
```

Integration:

```bash
docker-compose run --rm api pytest -q -m integration
```

| ID | Scenario | Status | Test location |
|----|----------|--------|---------------|
| T01 | POST valid payment | PASS | `tests/unit/test_api.py::test_t01_post_valid` |
| T02 | GET payment | PASS | `tests/unit/test_api_extra.py::test_t02_get_payment` |
| T03 | API key auth POST/GET | PASS | `test_api.py::test_t03_unauthorized`, `test_api_extra.py` |
| T04 | Idempotency-Key required | PASS | `test_api.py::test_t04_no_idempotency` |
| T05 | Idempotent repeat | PASS | `test_api.py::test_t05_idempotent_repeat` |
| T06 | Idempotency conflict 409 | PASS | `test_api.py::test_t06_idempotent_conflict` |
| T07 | Concurrent idempotency | PASS | `test_api.py::test_t07_concurrent_idempotency` |
| T08 | Invalid amounts | PASS | `test_api.py::test_t08_invalid_amount` |
| T09 | Bad currency/URL | PASS | `test_api_extra.py::test_t09_invalid_currency_and_url` |
| T10 | 404 / invalid UUID | PASS | `test_api.py`, `test_api_extra.py` |
| T11 | No orphan payment on rollback | PASS | `tests/integration/test_outbox.py` |
| T12 | POST without Rabbit dependency | PASS | `test_outbox_rmq.py::test_t12_*` |
| T13 | Outbox publish when broker up | PASS | `test_outbox_rmq.py::test_t13_*` |
| T14 | Duplicate event idempotent | PASS | `test_outbox_rmq.py::test_t14_*` |
| T15 | Duplicate AMQP after done | PASS | `test_consumer_flow.py::test_t15_*` |
| T16 | Gateway failed | PASS | `test_consumer_flow.py::test_t16_*` |
| T17 | Gateway succeeded | PASS | `test_consumer_flow.py::test_t17_*` |
| T18 | Webhook 2xx once | PASS | `test_consumer_flow.py::test_t18_*` |
| T19 | 3 webhook attempts | PASS | `test_consumer_flow.py::test_t19_*` |
| T20 | Exhausted + DLQ | PASS | `test_consumer_flow.py::test_t20_*` |
| T21 | Redirect not followed | PASS | `test_consumer_flow.py::test_t21_*` |
| T22 | Redelivery safe | PASS | `test_consumer_flow.py::test_t22_*` |
| T23 | Duplicate webhook same event_id | PASS | `test_consumer_flow.py::test_t23_*` |
| T24 | Invalid AMQP payload | PASS | `test_consumer_flow.py::test_t24_*` |
| T25 | Retry publish failure nack | PASS | `test_consumer_flow.py::test_t25_*` |
| T26 | SSRF strict | PASS | `test_ssrf.py`, `test_ssrf_strict.py` |
| T27 | Clean compose up | NOT RUN | Manual: `docker-compose up --build` (CI/host) |
| T28 | Restart recovery | NOT RUN | Manual smoke after restarts |
| T29 | RabbitMQ topology | PASS | `test_topology.py::test_t29_*` |
| T30 | Outbox EXPLAIN | PASS | `test_outbox_rmq.py::test_t30_*` |

T27–T28 are documented manual checks; automated suite covers business and infra logic on real Postgres/RabbitMQ in compose.
