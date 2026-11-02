"""Unofficial Hagleitner Community integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import HagleitnerHub
from .service_bus import run_receiver

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a queue hub or an adopted device."""
    if entry.data.get("entry_type") == "device":
        return await _async_setup_device(hass, entry)

    hub = HagleitnerHub(hass, entry, _LOGGER)
    hass.data[DOMAIN][entry.entry_id] = hub
    for configured_entry in hass.config_entries.async_entries(DOMAIN):
        if (
            configured_entry.data.get("entry_type") == "device"
            and configured_entry.data.get("hub_entry_id") == entry.entry_id
        ):
            hub.adopt_device(configured_entry.data["device_id"])

    hub.receiver_task = hass.async_create_task(
        run_receiver(
            entry.data["connection_string"],
            entry.data["queue_name"],
            hub.async_handle_message,
        ),
        name=f"{DOMAIN} Service Bus receiver",
    )
    return True


async def _async_setup_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Register an adopted device and load its entity platforms."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.exceptions import ConfigEntryNotReady

    hub_entry_id = entry.data["hub_entry_id"]
    hub: HagleitnerHub | None = hass.data[DOMAIN].get(hub_entry_id)
    if hub is None:
        if hass.config_entries.async_get_entry(hub_entry_id) is not None:
            await hass.config_entries.async_setup(hub_entry_id)
            hub = hass.data[DOMAIN].get(hub_entry_id)
    if hub is None:
        raise ConfigEntryNotReady("Waiting for the Hagleitner queue connection")

    device_id = entry.data["device_id"]
    hub.adopt_device(device_id)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        manufacturer="Hagleitner",
        model=entry.data.get("device_type_id") or None,
        name=entry.data["device_name"],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an adopted device or its queue connection."""
    if entry.data.get("entry_type") == "device":
        hub: HagleitnerHub | None = hass.data[DOMAIN].get(
            entry.data["hub_entry_id"]
        )
        if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            return False
        if hub is not None:
            hub.unadopt_device(entry.data["device_id"])
        return True

    hub = hass.data[DOMAIN].pop(entry.entry_id, None)
    if hub is not None and hub.receiver_task is not None:
        hub.receiver_task.cancel()
        try:
            await hub.receiver_task
        except asyncio.CancelledError:
            pass
    return True
