"""Azure Service Bus consumer shared by HA and the local debug entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

import certifi
from azure.servicebus.aio import ServiceBusClient
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

from .resource_data import device_identity

_LOGGER = logging.getLogger(__name__)
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
ReceiverStatusHandler = Callable[[bool], None]
_INITIAL_RETRY_DELAY = 1
_MAX_RETRY_DELAY = 60
_QUEUE_VALIDATION_TIMEOUT = 15


class QueueValidationFailure(str, Enum):
    """Safe, user-facing categories for failures validating a queue."""

    INVALID_CONNECTION_STRING = "invalid_connection_string"
    INVALID_QUEUE = "invalid_queue"
    INVALID_AUTH = "invalid_auth"
    QUEUE_NOT_FOUND = "queue_not_found"
    CANNOT_CONNECT = "cannot_connect"
    UNKNOWN = "unknown"


class QueueValidationError(Exception):
    """A validation failure that never contains SDK or credential details."""

    def __init__(self, reason: QueueValidationFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


async def async_validate_queue(
    connection_string: str,
    queue_name: str,
    *,
    timeout: float = _QUEUE_VALIDATION_TIMEOUT,
) -> None:
    """Validate access to a queue without receiving or changing its messages."""
    if not isinstance(connection_string, str) or not connection_string.strip():
        raise QueueValidationError(QueueValidationFailure.INVALID_CONNECTION_STRING)
    if not isinstance(queue_name, str) or not queue_name.strip():
        raise QueueValidationError(QueueValidationFailure.INVALID_QUEUE)

    try:
        await asyncio.wait_for(
            _async_peek_queue(connection_string, queue_name.strip(), timeout),
            timeout=timeout,
        )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        raise QueueValidationError(QueueValidationFailure.CANNOT_CONNECT) from None
    except (ServiceBusAuthenticationError, ServiceBusAuthorizationError):
        raise QueueValidationError(QueueValidationFailure.INVALID_AUTH) from None
    except MessagingEntityNotFoundError:
        raise QueueValidationError(QueueValidationFailure.QUEUE_NOT_FOUND) from None
    except (
        OperationTimeoutError,
        ServiceBusCommunicationError,
        ServiceBusConnectionError,
        ServiceBusServerBusyError,
    ):
        raise QueueValidationError(QueueValidationFailure.CANNOT_CONNECT) from None
    except ServiceBusError:
        raise QueueValidationError(QueueValidationFailure.UNKNOWN) from None
    except QueueValidationError:
        raise
    except Exception as error:
        # SDK messages may include endpoint or credential details. Keep them out of
        # both flow errors and logs, while leaving unexpected bugs visible by type.
        _LOGGER.warning(
            "Service Bus queue validation failed (%s)", type(error).__name__
        )
        raise QueueValidationError(QueueValidationFailure.UNKNOWN) from None


async def _async_peek_queue(
    connection_string: str,
    queue_name: str,
    timeout: float,
) -> None:
    """Open and close a one-shot peek client within the caller's time budget."""
    ssl_context = await asyncio.to_thread(_create_ssl_context)
    try:
        client = ServiceBusClient.from_connection_string(
            connection_string,
            ssl_context=ssl_context,
        )
    except (TypeError, ValueError):
        raise QueueValidationError(
            QueueValidationFailure.INVALID_CONNECTION_STRING
        ) from None

    async with client:
        try:
            receiver = await asyncio.to_thread(
                client.get_queue_receiver,
                queue_name=queue_name,
            )
        except (TypeError, ValueError):
            raise QueueValidationError(QueueValidationFailure.INVALID_QUEUE) from None
        async with receiver:
            # Do not retain or inspect the returned messages. Peek is non-destructive
            # and does not lock or consume them.
            await receiver.peek_messages(max_message_count=1, timeout=timeout)


async def run_receiver(
    connection_string: str,
    queue_name: str,
    message_handler: MessageHandler,
    status_handler: ReceiverStatusHandler | None = None,
) -> None:
    """Receive and settle messages, rebuilding the receiver after runtime failures."""
    retry_delay = _INITIAL_RETRY_DELAY
    ssl_context: ssl.SSLContext | None = None
    while True:
        try:
            _LOGGER.info("Starting Azure Service Bus receiver for queue %s", queue_name)
            if ssl_context is None:
                ssl_context = await asyncio.to_thread(_create_ssl_context)
            async with ServiceBusClient.from_connection_string(
                connection_string,
                ssl_context=ssl_context,
            ) as client:
                receiver = await asyncio.to_thread(
                    client.get_queue_receiver,
                    queue_name=queue_name,
                    max_wait_time=5,
                )
                async with receiver:
                    # DEBUG ONLY: remove before merging; pause to observe unavailable.
                    await asyncio.sleep(10)
                    if status_handler is not None:
                        status_handler(True)
                    _LOGGER.info(
                        "Started Azure Service Bus receiver; listening on queue %s",
                        queue_name,
                    )
                    while True:
                        messages = await receiver.receive_messages(
                            max_message_count=10,
                            max_wait_time=5,
                        )
                        for service_bus_message in messages:
                            try:
                                payload = _decode_message(service_bus_message.body)
                                device_identity(payload)
                            except (UnicodeDecodeError, ValueError) as error:
                                _LOGGER.error(
                                    "Dead-lettering invalid resource data: %s",
                                    error,
                                )
                                await receiver.dead_letter_message(
                                    service_bus_message,
                                    reason="Invalid resource data message",
                                    error_description=str(error)[:1024],
                                )
                                continue

                            try:
                                await message_handler(payload)
                            except asyncio.CancelledError:
                                raise
                            except Exception as error:
                                _LOGGER.error(
                                    "Message handler failed for queue %s (%s): %s; "
                                    "abandoning message for redelivery",
                                    queue_name,
                                    type(error).__name__,
                                    error,
                                )
                                await receiver.abandon_message(service_bus_message)
                                continue

                            await receiver.complete_message(service_bus_message)

                        # The receive and settlement cycle is healthy; start any
                        # subsequent recovery at the initial delay.
                        retry_delay = _INITIAL_RETRY_DELAY
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if status_handler is not None:
                status_handler(False)
            # DEBUG ONLY: remove before merging; pause to observe unavailable.
            await asyncio.sleep(10)
            _LOGGER.error(
                "Service Bus receiver for queue %s failed (%s); "
                "recreating it in %s seconds",
                queue_name,
                type(error).__name__,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, _MAX_RETRY_DELAY)


def _create_ssl_context() -> ssl.SSLContext:
    """Load Azure's default CA bundle outside the event loop."""
    return ssl.create_default_context(cafile=certifi.where())


def _decode_message(body: Any) -> dict[str, Any]:
    """Decode a Service Bus body into a JSON object."""
    if isinstance(body, bytes):
        encoded_body = body
    elif isinstance(body, str):
        encoded_body = body.encode("utf-8")
    else:
        encoded_body = b"".join(body)

    payload = json.loads(encoded_body)
    if not isinstance(payload, dict):
        raise ValueError("Message root must be a JSON object")
    return payload
