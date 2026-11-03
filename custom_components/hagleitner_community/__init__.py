"""Unofficial Hagleitner Community integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import HagleitnerHub, async_restore_persisted_state
from .repairs import (
    async_clear_maintenance_issues,
    async_clear_obsolete_consumable_issues,
)
from .service_bus import run_receiver

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
_DEVICE_SETUP_TASKS = "_device_setup_tasks"


def _device_model(device_data: Mapping[str, Any]) -> str | None:
    """Return a readable model name without exposing a device type UUID."""
    for key in ("device_type_name", "device_name"):
        value = device_data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        try:
            UUID(value)
        except ValueError:
            return value
    return None


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    await async_restore_persisted_state(hass)
    async_clear_obsolete_consumable_issues(hass)
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
            hub.device_sources.setdefault(
                configured_entry.data["device_id"], set()
            ).add(entry.entry_id)
            hub.adopt_device(
                configured_entry.data["device_id"],
                configured_entry.entry_id,
                configured_entry.title,
            )
            hub._async_record_device_source(configured_entry.data["device_id"])

    hub.receiver_task = entry.async_create_background_task(
        hass,
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
        and configured_entry.disabled_by is None
    ]
    for configured_entry in entries:
        if configured_entry.data.get("entry_type") != "device":
            continue
        previous_hub_id = configured_entry.data.get("hub_entry_id")
        if previous_hub_id == hub_entry.entry_id:
            continue
        previous_hub = (
            hass.config_entries.async_get_entry(previous_hub_id)
            if previous_hub_id is not None
            else None
        )
        if previous_hub is not None and previous_hub.disabled_by is None:
            continue

        associated_hubs = [
            hass.config_entries.async_get_entry(hub_id)
            for hub_id in configured_entry.data.get("hub_entry_ids", ())
        ]
        available_hubs = [
            associated_hub
            for associated_hub in associated_hubs
            if associated_hub is not None
            and associated_hub.data.get("entry_type") != "device"
            and associated_hub.disabled_by is None
        ]
        if hub_entry.entry_id in {
            associated_hub.entry_id for associated_hub in available_hubs
        }:
            selected_hub = hub_entry
        elif available_hubs:
            selected_hub = available_hubs[0]
        else:
            known_queue = configured_entry.data.get("hub_queue_name")
            normalized_known_queue = (
                known_queue.strip().casefold()
                if isinstance(known_queue, str)
                else None
            )
            matching_hubs = [
                candidate
                for candidate in hubs
                if isinstance(candidate.data.get("queue_name"), str)
                and candidate.data["queue_name"].strip().casefold()
                == normalized_known_queue
            ]
            if normalized_known_queue is not None and matching_hubs:
                selected_hub = (
                    hub_entry
                    if any(
                        candidate.entry_id == hub_entry.entry_id
                        for candidate in matching_hubs
                    )
                    else matching_hubs[0]
                )
            elif known_queue is None and len(hubs) == 1:
                selected_hub = hubs[0]
            else:
                continue

        hass.config_entries.async_update_entry(
            configured_entry,
            data={
                **configured_entry.data,
                "hub_entry_id": selected_hub.entry_id,
                "hub_queue_name": selected_hub.data.get("queue_name"),
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
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import area_registry as ar, device_registry as dr

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
    hub._async_record_device_source(device_id)
    identifiers = {(DOMAIN, device_id)}
    device_registry = dr.async_get(hass)
    existing_devices = device_registry.async_get_devices(identifiers=identifiers)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers=identifiers,
        manufacturer="Hagleitner",
        model=_device_model(entry.data),
        name=entry.data["device_name"],
    )
    area_id = entry.data.get("area_id")
    if not existing_devices and isinstance(area_id, str):
        if ar.async_get(hass).async_get_area(area_id) is not None:
            device_registry.async_update_device(device.id, area_id=area_id)
        else:
            _LOGGER.info(
                "The suggested Home Assistant area %s no longer exists; "
                "leaving device %s unassigned",
                area_id,
                device_id,
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
    hub = hass.data[DOMAIN].get(entry.entry_id)
    retained_entries: set[str] = set()
    if hub is not None:
        for device_entry in device_entries:
            device_id = device_entry.data["device_id"]
            alternate_hub = next(
                (
                    candidate_id
                    for candidate_id in device_entry.data.get("hub_entry_ids", ())
                    if candidate_id != entry.entry_id
                    and (
                        candidate := hass.config_entries.async_get_entry(
                            candidate_id
                        )
                    )
                    is not None
                    and candidate.state == ConfigEntryState.LOADED
                ),
                None,
            )
            if alternate_hub is None:
                continue
            alternate_entry = hass.config_entries.async_get_entry(alternate_hub)
            assert alternate_entry is not None
            hass.config_entries.async_update_entry(
                device_entry,
                data={
                    **device_entry.data,
                    "hub_entry_id": alternate_entry.entry_id,
                    "hub_queue_name": alternate_entry.data.get("queue_name"),
                },
            )
            retained_entries.add(device_entry.entry_id)

    unloaded_entries: list[ConfigEntry] = []
    for device_entry in device_entries:
        if device_entry.entry_id in retained_entries:
            continue
        if device_entry.state != ConfigEntryState.LOADED:
            continue
        if not await hass.config_entries.async_unload(device_entry.entry_id):
            for unloaded_entry in unloaded_entries:
                await hass.config_entries.async_setup(unloaded_entry.entry_id)
            return False
        unloaded_entries.append(device_entry)

    for device_entry in device_entries:
        if device_entry.entry_id in retained_entries:
            continue
        _async_set_device_hub_queue(hass, device_entry, entry)

    if hub is not None:
        for sources in hub.device_sources.values():
            sources.discard(entry.entry_id)

    hass.data[DOMAIN].pop(entry.entry_id, None)
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
        async_clear_maintenance_issues(hass, entry.data["device_id"])
