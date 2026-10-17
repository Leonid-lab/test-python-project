# Архитектурные решения

1. **Outbox publisher в процессе `consumer`** — сохраняем 4 сервиса в Compose и один бизнес-handler; API не зависит от доступности RabbitMQ после commit.

2. **Публикация outbox/retry через aio-pika с `mandatory=True` и return callback** — publisher confirm без маршрутизации не считается успехом; FastStream используется для единственного subscriber с manual ACK.

3. **Идемпотентность POST через UNIQUE(`idempotency_key`) + `request_hash`** — гонки закрываются `IntegrityError` и повторным чтением, без предварительного SELECT.

4. **Webhook SSRF: allowlist hostname при создании + pin IP в aiohttp resolver при доставке** — снижает DNS rebinding; не отключаем TLS verify и не используем `trust_env`.

5. **Retry webhook через TTL-очереди `payments.retry.1/2`** — явный `attempt` в payload (1..3); ACK исходного сообщения только после подтверждённой публикации в retry-очередь.
