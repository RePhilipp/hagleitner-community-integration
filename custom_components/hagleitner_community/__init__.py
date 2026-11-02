"""Unofficial Hagleitner Community integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import HagleitnerHub
from .repairs import async_clear_maintenance_issues
from .service_bus import run_receiver

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
_DEVICE_SETUP_TASKS = "_device_setup_tasks"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a queue hub or an adopted device."""
    if entry.data.get("entry_type") == "device":
        return await _async_setup_device(hass, entry)

    _async_rebind_orphaned_devices(hass, entry)
    hub = HagleitnerHub(hass, entry, _LOGGER)
    hass.data[DOMAIN][entry.entry_id] = hub
    for configured_entry in hass.config_entries.async_entries(DOMAIN):
        if (
            configured_entry.data.get("entry_type") == "device"
            and configured_entry.data.get("hub_entry_id") == entry.entry_id
        ):
            _async_set_device_hub_queue(hass, configured_entry, entry)
            hub.adopt_device(
                configured_entry.data["device_id"],
                configured_entry.entry_id,
                configured_entry.title,
            )

    hub.receiver_task = hass.async_create_task(
        run_receiver(
            entry.data["connection_string"],
            entry.data["queue_name"],
            hub.async_handle_message,
        ),
        name=f"{DOMAIN} Service Bus receiver",
    )
    setup_task = hass.async_create_task(
        _async_setup_linked_devices(hass, entry.entry_id, hub),
        name=f"{DOMAIN} adopted device setup",
    )
    setup_tasks = hass.data[DOMAIN].setdefault(_DEVICE_SETUP_TASKS, {})
    setup_tasks[entry.entry_id] = setup_task
    setup_task.add_done_callback(
        lambda task: _async_remove_device_setup_task(
            setup_tasks, entry.entry_id, task
        )
    )
    return True


def _async_rebind_orphaned_devices(
    hass: HomeAssistant,
    hub_entry: ConfigEntry,
) -> None:
    """Reattach device entries whose previous hub entry was removed."""
    entries = hass.config_entries.async_entries(DOMAIN)
    hubs = [
        configured_entry
        for configured_entry in entries
        if configured_entry.data.get("entry_type") != "device"
    ]
    queue_name = hub_entry.data.get("queue_name")
    for configured_entry in entries:
        if configured_entry.data.get("entry_type") != "device":
            continue
        previous_hub_id = configured_entry.data.get("hub_entry_id")
        if previous_hub_id == hub_entry.entry_id:
            continue
        if (
            previous_hub_id is not None
            and hass.config_entries.async_get_entry(previous_hub_id) is not None
        ):
            continue

        known_queue = configured_entry.data.get("hub_queue_name")
        if known_queue is not None:
            if known_queue != queue_name:
                continue
        elif len(hubs) != 1:
            continue

        hass.config_entries.async_update_entry(
            configured_entry,
            data={
                **configured_entry.data,
                "hub_entry_id": hub_entry.entry_id,
                "hub_queue_name": queue_name,
            },
        )


def _async_set_device_hub_queue(
    hass: HomeAssistant,
    device_entry: ConfigEntry,
    hub_entry: ConfigEntry,
) -> None:
    """Remember the hub queue so device entries can survive hub removal."""
    queue_name = hub_entry.data.get("queue_name")
    if device_entry.data.get("hub_queue_name") == queue_name:
        return
    hass.config_entries.async_update_entry(
        device_entry,
        data={**device_entry.data, "hub_queue_name": queue_name},
    )


async def _async_setup_linked_devices(
    hass: HomeAssistant,
    hub_entry_id: str,
    hub: HagleitnerHub,
) -> None:
    """Set up adopted entries after the hub has been loaded or reloaded."""
    for device_entry in hass.config_entries.async_entries(DOMAIN):
        if (
            device_entry.data.get("entry_type") != "device"
            or device_entry.data.get("hub_entry_id") != hub_entry_id
            or device_entry.disabled_by is not None
            or device_entry.state != ConfigEntryState.NOT_LOADED
            or hass.data[DOMAIN].get(hub_entry_id) is not hub
        ):
            continue
        await hass.config_entries.async_setup(device_entry.entry_id)


def _async_remove_device_setup_task(
    setup_tasks: dict[str, asyncio.Task[None]],
    hub_entry_id: str,
    task: asyncio.Task[None],
) -> None:
    """Forget a completed adopted-device setup task."""
    if setup_tasks.get(hub_entry_id) is task:
        setup_tasks.pop(hub_entry_id)


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
    hub.adopt_device(device_id, entry.entry_id, entry.title)
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

    setup_tasks = hass.data[DOMAIN].get(_DEVICE_SETUP_TASKS, {})
    setup_task = setup_tasks.get(entry.entry_id)
    if setup_task is not None and not setup_task.done():
        await setup_task

    device_entries = [
        configured_entry
        for configured_entry in hass.config_entries.async_entries(DOMAIN)
        if (
            configured_entry.data.get("entry_type") == "device"
            and configured_entry.data.get("hub_entry_id") == entry.entry_id
        )
    ]
    unloaded_entries: list[ConfigEntry] = []
    for device_entry in device_entries:
        if device_entry.state != ConfigEntryState.LOADED:
            continue
        if not await hass.config_entries.async_unload(device_entry.entry_id):
            for unloaded_entry in unloaded_entries:
                await hass.config_entries.async_setup(unloaded_entry.entry_id)
            return False
        unloaded_entries.append(device_entry)

    for device_entry in device_entries:
        _async_set_device_hub_queue(hass, device_entry, entry)

    hub = hass.data[DOMAIN].pop(entry.entry_id, None)
    if hub is not None and hub.receiver_task is not None:
        hub.receiver_task.cancel()
        try:
            await hub.receiver_task
        except asyncio.CancelledError:
            pass
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove repair issues when an adopted device entry is deleted."""
    if entry.data.get("entry_type") == "device":
        async_clear_maintenance_issues(hass, entry.entry_id)
