"""Unofficial Hagleitner Community integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .const import DOMAIN
from .resource_data import device_identity, log_resource_values
from .service_bus import run_receiver

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start the receiver for a configured queue."""
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)

    async def handle_message(message: dict[str, Any]) -> None:
        device_id, device_type_id = device_identity(message)
        if registry.async_get_device({(DOMAIN, device_id)}) is None:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, device_id)},
                manufacturer="Hagleitner",
                model=device_type_id or None,
                name=f"Hagleitner {device_id[:8]}",
            )
            _LOGGER.info("Registered Hagleitner device %s", device_id)

        log_resource_values(message, _LOGGER)

    receiver_task = hass.async_create_task(
        run_receiver(
            entry.data["connection_string"],
            entry.data["queue_name"],
            handle_message,
        ),
        name=f"{DOMAIN} Service Bus receiver",
    )
    hass.data[DOMAIN][entry.entry_id] = receiver_task
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop the queue receiver when the config entry is unloaded."""
    receiver_task: asyncio.Task[None] | None = hass.data[DOMAIN].pop(
        entry.entry_id, None
    )
    if receiver_task is not None:
        receiver_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass
    return True
