"""Azure Service Bus consumer shared by HA and the local debug entry point."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from azure.servicebus.aio import ServiceBusClient

from .resource_data import device_identity

_LOGGER = logging.getLogger(__name__)
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
_INITIAL_RETRY_DELAY = 1
_MAX_RETRY_DELAY = 60


async def run_receiver(
    connection_string: str,
    queue_name: str,
    message_handler: MessageHandler,
) -> None:
    """Receive and settle messages, rebuilding the receiver after runtime failures."""
    retry_delay = _INITIAL_RETRY_DELAY
    while True:
        try:
            async with ServiceBusClient.from_connection_string(
                connection_string
            ) as client:
                receiver = await asyncio.to_thread(
                    client.get_queue_receiver,
                    queue_name=queue_name,
                    max_wait_time=5,
                )
                async with receiver:
                    _LOGGER.info("Listening on Azure Service Bus queue %s", queue_name)
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
                                    "Message handler failed for queue %s (%s); "
                                    "abandoning message for redelivery",
                                    queue_name,
                                    type(error).__name__,
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
            _LOGGER.error(
                "Service Bus receiver for queue %s failed (%s); "
                "recreating it in %s seconds",
                queue_name,
                type(error).__name__,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, _MAX_RETRY_DELAY)


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
