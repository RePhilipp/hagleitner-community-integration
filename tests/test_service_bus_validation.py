"""Focused tests for the non-destructive Service Bus connectivity probe."""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest
from azure.servicebus.exceptions import (
    MessagingEntityNotFoundError,
    OperationTimeoutError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    ServiceBusError,
    ServiceBusServerBusyError,
)

from custom_components.hagleitner_community import service_bus
from custom_components.hagleitner_community.service_bus import (
    QueueValidationError,
    QueueValidationFailure,
)


class FakeReceiver:
    """An async-context receiver that records only the peek call."""

    def __init__(self, peek_error: Exception | None = None):
        self.peek_error = peek_error
        self.peek_options = None
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def peek_messages(self, **kwargs):
        self.peek_options = kwargs
        if self.peek_error is not None:
            raise self.peek_error
        return [object()]


class FakeClient:
    """An async-context client that supplies the fake receiver."""

    def __init__(self, receiver):
        self.receiver = receiver
        self.receiver_options = None
        self.receiver_thread_id = None
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    def get_queue_receiver(self, **kwargs):
        self.receiver_options = kwargs
        self.receiver_thread_id = threading.get_ident()
        return self.receiver


async def test_validation_peeks_one_message_and_closes_resources(monkeypatch):
    """A successful probe opens and closes one non-destructive peek receiver."""
    receiver = FakeReceiver()
    client = FakeClient(receiver)
    client_options = {}

    def from_connection_string(connection_string, **kwargs):
        client_options.update(connection_string=connection_string, **kwargs)
        return client

    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(from_connection_string),
    )

    await service_bus.async_validate_queue("connection-secret", "queue-a")

    assert client_options["connection_string"] == "connection-secret"
    assert client.receiver_options == {"queue_name": "queue-a"}
    assert client.receiver_thread_id != threading.get_ident()
    assert receiver.peek_options == {"max_message_count": 1, "timeout": 15}
    assert receiver.closed is True
    assert client.closed is True


@pytest.mark.parametrize(
    ("sdk_error", "expected_reason"),
    [
        (ServiceBusAuthenticationError(message="secret token"), "invalid_auth"),
        (ServiceBusAuthorizationError(message="sensitive endpoint"), "invalid_auth"),
        (MessagingEntityNotFoundError(message="private queue name"), "queue_not_found"),
        (ServiceBusConnectionError(message="host detail"), "cannot_connect"),
        (ServiceBusCommunicationError(message="network detail"), "cannot_connect"),
        (ServiceBusServerBusyError(message="service detail"), "cannot_connect"),
        (OperationTimeoutError(message="timeout detail"), "cannot_connect"),
        (ServiceBusError(message="private service error"), "unknown"),
        (RuntimeError("secret raw SDK message"), "unknown"),
    ],
)
async def test_validation_maps_failures_without_exposing_sdk_message(
    monkeypatch, caplog, sdk_error, expected_reason
):
    """SDK errors become safe categories and still clean up both resources."""
    receiver = FakeReceiver(sdk_error)
    client = FakeClient(receiver)
    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: client),
    )

    with pytest.raises(QueueValidationError) as raised:
        await service_bus.async_validate_queue("connection-secret", "queue-a")

    assert raised.value.reason.value == expected_reason
    assert "secret raw SDK message" not in str(raised.value)
    assert "secret raw SDK message" not in caplog.text
    assert receiver.closed is True
    assert client.closed is True


async def test_validation_classifies_malformed_connection_string(monkeypatch):
    """SDK parser details are not passed back to the flow."""

    def malformed_connection(*_args, **_kwargs):
        raise ValueError("connection-secret parse details")

    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(malformed_connection),
    )

    with pytest.raises(QueueValidationError) as raised:
        await service_bus.async_validate_queue("bad-secret", "queue-a")

    assert raised.value.reason is QueueValidationFailure.INVALID_CONNECTION_STRING
    assert "connection-secret" not in str(raised.value)


async def test_validation_classifies_invalid_queue_argument(monkeypatch):
    """SDK receiver-construction errors are reported as queue input errors."""
    client = FakeClient(FakeReceiver())

    def invalid_receiver(**_kwargs):
        raise ValueError("private queue details")

    client.get_queue_receiver = invalid_receiver
    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: client),
    )

    with pytest.raises(QueueValidationError) as raised:
        await service_bus.async_validate_queue("connection", "bad-queue")

    assert raised.value.reason is QueueValidationFailure.INVALID_QUEUE
    assert "private queue details" not in str(raised.value)
    assert client.closed is True


async def test_validation_timeout_closes_resources(monkeypatch):
    """The total probe deadline cancels an outstanding peek and closes resources."""
    peek_started = asyncio.Event()
    receiver = FakeReceiver()

    async def never_returns(**kwargs):
        receiver.peek_options = kwargs
        peek_started.set()
        await asyncio.Event().wait()

    receiver.peek_messages = never_returns
    client = FakeClient(receiver)
    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: client),
    )

    with pytest.raises(QueueValidationError) as raised:
        await service_bus.async_validate_queue("connection", "queue", timeout=0.01)

    assert raised.value.reason is QueueValidationFailure.CANNOT_CONNECT
    assert peek_started.is_set()
    assert receiver.closed is True
    assert client.closed is True


async def test_validation_propagates_cancellation_after_cleanup(monkeypatch):
    """Caller cancellation is not converted into a connection failure."""
    peek_started = asyncio.Event()
    receiver = FakeReceiver()

    async def never_returns(**_kwargs):
        peek_started.set()
        await asyncio.Event().wait()

    receiver.peek_messages = never_returns
    client = FakeClient(receiver)
    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: client),
    )
    task = asyncio.create_task(service_bus.async_validate_queue("connection", "queue"))
    await peek_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert receiver.closed is True
    assert client.closed is True


async def test_validation_rejects_empty_connection_and_queue_without_client(
    monkeypatch,
):
    """Locally malformed fields are rejected before creating SDK resources."""
    calls = []
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: calls.append(True)),
    )

    for connection_string, queue_name, expected in (
        ("  ", "queue", QueueValidationFailure.INVALID_CONNECTION_STRING),
        ("connection", " ", QueueValidationFailure.INVALID_QUEUE),
    ):
        with pytest.raises(QueueValidationError) as raised:
            await service_bus.async_validate_queue(connection_string, queue_name)
        assert raised.value.reason is expected

    assert calls == []


async def test_receiver_logs_one_outage_and_one_recovery(monkeypatch, caplog):
    """The persistent consumer still retries transient failures in the background."""
    attempts = 0
    receiver_started = asyncio.Event()
    receiver_closed = False
    client_closed = False

    class BlockingReceiver:
        async def __aenter__(self):
            receiver_started.set()
            return self

        async def __aexit__(self, *_args):
            nonlocal receiver_closed
            receiver_closed = True

        async def receive_messages(self, **_kwargs):
            await asyncio.Event().wait()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            nonlocal client_closed
            client_closed = True

        @staticmethod
        def get_queue_receiver(**_kwargs):
            return BlockingReceiver()

    def from_connection_string(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ServiceBusConnectionError(message="private transient detail")
        return Client()

    async def skip_retry_delay(_delay):
        return None

    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(service_bus.asyncio, "sleep", skip_retry_delay)
    caplog.set_level(logging.DEBUG, logger=service_bus.__name__)
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(from_connection_string),
    )
    statuses = []
    task = asyncio.create_task(
        service_bus.run_receiver(
            "connection", "queue", lambda _message: None, statuses.append
        )
    )
    await receiver_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts == 3
    assert receiver_closed is True
    assert client_closed is True
    messages = [record.getMessage() for record in caplog.records]
    assert sum("is unavailable" in message for message in messages) == 1
    assert (
        sum("Starting Azure Service Bus receiver" in message for message in messages)
        == 1
    )
    assert (
        sum("Retrying Azure Service Bus receiver" in message for message in messages)
        == 2
    )
    assert (
        sum("Started Azure Service Bus receiver" in message for message in messages)
        == 1
    )
    assert all(
        record.levelno == logging.INFO
        for record in caplog.records
        if "is unavailable" in record.getMessage()
        or "Started Azure Service Bus receiver" in record.getMessage()
    )
    assert "private transient detail" not in caplog.text
    assert statuses == [False, False, True]


def test_decode_message_accepts_supported_sdk_body_shapes():
    """SDK strings and iterable body chunks decode like a single byte body."""
    expected = {"deviceInfo": {"deviceId": "device-1"}}

    assert service_bus._decode_message(
        '{"deviceInfo":{"deviceId":"device-1"}}'
    ) == expected
    assert service_bus._decode_message(
        [b'{"deviceInfo":', b'{"deviceId":"device-1"}}']
    ) == expected


def test_create_ssl_context_uses_certifi_bundle(monkeypatch):
    """The receiver explicitly loads the bundled CA certificates."""
    calls = []
    sentinel = object()

    def create_default_context(*, cafile):
        calls.append(cafile)
        return sentinel

    monkeypatch.setattr(service_bus.certifi, "where", lambda: "/ca/cert.pem")
    monkeypatch.setattr(
        service_bus.ssl, "create_default_context", create_default_context
    )

    assert service_bus._create_ssl_context() is sentinel
    assert calls == ["/ca/cert.pem"]


async def test_receiver_settles_invalid_failed_and_successful_messages(monkeypatch):
    """Invalid payloads are dead-lettered while handler failures can be retried."""
    messages = [
        type("Message", (), {"body": b"not-json"})(),
        type("Message", (), {"body": b"[]"})(),
        type("Message", (), {"body": b'{"readings": []}'})(),
        type(
            "Message",
            (),
            {"body": b'{"deviceInfo": {"deviceId": "retry-me"}}'},
        )(),
        type(
            "Message",
            (),
            {"body": b'{"deviceInfo": {"deviceId": "complete-me"}}'},
        )(),
    ]
    settlements = []
    receiver_ready = asyncio.Event()
    receiver_closed = False
    client_closed = False
    receive_count = 0

    class Receiver:
        async def __aenter__(self):
            receiver_ready.set()
            return self

        async def __aexit__(self, *_args):
            nonlocal receiver_closed
            receiver_closed = True

        async def receive_messages(self, **_kwargs):
            nonlocal receive_count
            receive_count += 1
            if receive_count == 1:
                return messages
            await asyncio.Event().wait()

        async def dead_letter_message(self, message, **kwargs):
            settlements.append(("dead_letter", message, kwargs))

        async def abandon_message(self, message):
            settlements.append(("abandon", message))

        async def complete_message(self, message):
            settlements.append(("complete", message))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            nonlocal client_closed
            client_closed = True

        @staticmethod
        def get_queue_receiver(**_kwargs):
            return Receiver()

    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: Client()),
    )

    handled = []

    async def handle(payload):
        device_id = payload["deviceInfo"]["deviceId"]
        handled.append(device_id)
        if device_id == "retry-me":
            raise RuntimeError("temporary downstream failure")

    task = asyncio.create_task(
        service_bus.run_receiver("connection", "queue", handle)
    )
    await receiver_ready.wait()
    # Wait until the second receive blocks, proving that the first batch was
    # decoded and each message has been settled before cancellation.
    while receive_count < 2:
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert handled == ["retry-me", "complete-me"]
    assert [settlement[0] for settlement in settlements] == [
        "dead_letter",
        "dead_letter",
        "dead_letter",
        "abandon",
        "complete",
    ]
    for _, _, options in settlements[:3]:
        assert options["reason"] == "Invalid resource data message"
        assert len(options["error_description"]) <= 1024
    assert settlements[3][1] is messages[3]
    assert settlements[4][1] is messages[4]
    assert receiver_closed is True
    assert client_closed is True


async def test_receiver_propagates_handler_cancellation_without_settlement(monkeypatch):
    """Shutdown cancellation during processing must not abandon or complete."""
    message = type(
        "Message",
        (),
        {"body": b'{"deviceInfo": {"deviceId": "device-1"}}'},
    )()
    handler_started = asyncio.Event()
    settlements = []
    receiver_closed = False
    client_closed = False

    class Receiver:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            nonlocal receiver_closed
            receiver_closed = True

        async def receive_messages(self, **_kwargs):
            return [message]

        async def abandon_message(self, current_message):
            settlements.append(("abandon", current_message))

        async def complete_message(self, current_message):
            settlements.append(("complete", current_message))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            nonlocal client_closed
            client_closed = True

        @staticmethod
        def get_queue_receiver(**_kwargs):
            return Receiver()

    monkeypatch.setattr(service_bus, "_create_ssl_context", lambda: object())
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(lambda *_args, **_kwargs: Client()),
    )

    async def blocked_handler(_payload):
        handler_started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        service_bus.run_receiver("connection", "queue", blocked_handler)
    )
    await handler_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert settlements == []
    assert receiver_closed is True
    assert client_closed is True
