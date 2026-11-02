"""Run the queue listener locally without starting Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import os

from .resource_data import log_resource_values
from .service_bus import run_receiver

_LOGGER = logging.getLogger("hagleitner_community")


async def _run() -> None:
    connection_string = os.environ.get("HAGLEITNER_SERVICE_BUS_CONNECTION_STRING")
    queue_name = os.environ.get("HAGLEITNER_QUEUE_NAME")
    if not connection_string or not queue_name:
        raise SystemExit(
            "Set HAGLEITNER_SERVICE_BUS_CONNECTION_STRING and "
            "HAGLEITNER_QUEUE_NAME in your environment."
        )

    async def log_message(message: dict[str, object]) -> None:
        _LOGGER.info("Received resource-data message")
        log_resource_values(message, _LOGGER)

    await run_receiver(connection_string, queue_name, log_message)


def main() -> None:
    """Start the standalone listener."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        _LOGGER.info("Receiver stopped")


if __name__ == "__main__":
    main()
