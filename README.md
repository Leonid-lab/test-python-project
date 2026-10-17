# Async Payment Processor

Микросервис асинхронной обработки платежей: FastAPI + PostgreSQL (transactional outbox) + RabbitMQ (FastStream) + webhook.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

API: `http://localhost:8000`

RabbitMQ Management (только внутри compose-сети по умолчанию): пользователь/пароль `payments` / `payments`, очереди `payments.new`, `payments.dlq`.

## Примеры

```bash
export API_KEY=change-me-demo-key

curl -s -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: demo-001" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1250.50",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": "42"},
    "webhook_url": "https://webhook.site/your-uuid"
  }'

curl -s http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: $API_KEY"
```

Повтор с тем же `Idempotency-Key` и телом вернёт тот же `payment_id`. Другое тело — `409`.

## Webhook

Тело JSON: `event_id`, `payment_id`, `status`, `amount`, `currency`, `processed_at`. Заголовок `X-Event-ID` совпадает с `event_id`. Доставка **at-least-once**; получатель должен дедуплицировать по `event_id`.

`webhook_url` при создании платежа должен быть HTTPS и хост из `WEBHOOK_ALLOWED_HOSTS` (точное совпадение).

## Гарантии и ограничения

- Создание платежа и запись outbox — одна транзакция; API не публикует в RabbitMQ напрямую.
- Публикация из outbox и обработка сообщений — **at-least-once**; consumer идемпотентен для терминальных статусов.
- Эмулятор шлюза: 2–5 с задержки, ~90% `succeeded` / ~10% `failed` (детерминировано от `payment_id`).
- Технические сбои webhook: 3 суммарные попытки (задержки ~2 с и ~4 с через TTL-очереди), затем `payments.dlq` и `webhook_status=exhausted`.
- Бизнес-`failed` не уходит в DLQ.

## Разработка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main_api:app --reload
faststream run app.main_consumer:app
```

Тесты (в Docker, Postgres + RabbitMQ из compose):

```bash
docker-compose stop consumer   # иначе consumer забирает сообщения из очередей
docker-compose run --rm api pytest -q
# параллельно (юниты свободно, Rabbit/webhook под файловым локом):
docker-compose run --rm api pytest -q -n auto --dist loadfile
```

Матрица T01–T30: `tests/README.md`.

Линтер: `ruff check .` и `ruff format --check .`

## Миграции

Только сервис `api` выполняет `alembic upgrade head` при старте. `consumer` ждёт готовности БД.
