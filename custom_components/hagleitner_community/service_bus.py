"""Azure Service Bus consumer shared by HA and the local debug entry point."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from azure.servicebus.aio import ServiceBusClient

from .resource_data import device_identity

_LOGGER = logging.getLogger(__name__)
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


async def run_receiver(
    connection_string: str,
    queue_name: str,
    message_handler: MessageHandler,
) -> None:
    """Receive messages, call the handler, and settle each handled message."""
    async with ServiceBusClient.from_connection_string(connection_string) as client:
        async with client.get_queue_receiver(
            queue_name=queue_name,
            max_wait_time=5,
        ) as receiver:
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
                        _LOGGER.error("Dead-lettering invalid resource data: %s", error)
                        await receiver.dead_letter_message(
                            service_bus_message,
                            reason="Invalid resource data message",
                            error_description=str(error)[:1024],
                        )
                        continue

                    await message_handler(payload)
                    await receiver.complete_message(service_bus_message)


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
