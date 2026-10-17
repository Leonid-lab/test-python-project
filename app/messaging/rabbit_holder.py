import aio_pika


class RabbitConnectionHolder:
    connection: aio_pika.abc.AbstractConnection | None = None


rabbit_connection_holder = RabbitConnectionHolder()
