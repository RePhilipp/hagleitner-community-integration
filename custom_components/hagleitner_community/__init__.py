"""Unofficial Hagleitner Community integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import (
    HagleitnerConfigEntry,
    HagleitnerHub,
    async_restore_persisted_state,
)
from .device import MANUFACTURER, device_model_id
from .repairs import (
    async_clear_maintenance_issues,
    async_clear_obsolete_consumable_issues,
    async_clear_queue_not_found_issue,
    async_create_queue_not_found_issue,
)
from .service_bus import (
    QueueValidationError,
    QueueValidationFailure,
    async_validate_queue,
    run_receiver,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
_DEVICE_SETUP_TASKS = "_device_setup_tasks"


def _device_model(device_data: Mapping[str, Any]) -> str | None:
    """Return the translated device type name, never the display name or UUID."""
    value = device_data.get("device_type_name")
    if not isinstance(value, str) or not value.strip():
        return None
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
) -> bool:
    """Set up a queue hub or an adopted device."""
    if entry.data.get("entry_type") != "device":
        try:
            await async_validate_queue(
                entry.data.get("connection_string"), entry.data.get("queue_name")
            )
        except QueueValidationError as error:
            if error.reason in {
                QueueValidationFailure.INVALID_AUTH,
                QueueValidationFailure.INVALID_CONNECTION_STRING,
            }:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="service_bus_credentials_invalid",
                ) from error
            if error.reason in {
                QueueValidationFailure.CANNOT_CONNECT,
            }:
                raise ConfigEntryNotReady(
                    translation_domain=DOMAIN,
                    translation_key="service_bus_queue_unavailable",
                ) from error
            if error.reason is QueueValidationFailure.QUEUE_NOT_FOUND:
                async_create_queue_not_found_issue(hass, entry.entry_id)
                raise ConfigEntryError(
                    translation_domain=DOMAIN,
                    translation_key="service_bus_queue_not_found",
                ) from error
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="service_bus_queue_validation_failed",
            ) from error
        else:
            async_clear_queue_not_found_issue(hass, entry.entry_id)

    await async_restore_persisted_state(hass)
    if entry.data.get("entry_type") == "device":
        return await _async_setup_device(hass, entry)

    _async_rebind_orphaned_devices(hass, entry)
    hub = HagleitnerHub(hass, entry, _LOGGER)
    entry.runtime_data = hub
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
            hub.async_set_receiver_available,
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
    hub_entry: HagleitnerConfigEntry,
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
    device_entry: HagleitnerConfigEntry,
    hub_entry: HagleitnerConfigEntry,
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
    hub_entry = hass.config_entries.async_get_entry(hub_entry_id)
    if hub_entry is None:
        return

    for device_entry in hass.config_entries.async_entries(DOMAIN):
        if (
            device_entry.data.get("entry_type") != "device"
            or device_entry.data.get("hub_entry_id") != hub_entry_id
            or device_entry.disabled_by is not None
            or device_entry.state != ConfigEntryState.NOT_LOADED
            or getattr(hub_entry, "runtime_data", None) is not hub
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
    entry: HagleitnerConfigEntry,
) -> bool:
    """Register an adopted device and load its entity platforms."""
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import area_registry as ar

    hub_entry_id = entry.data["hub_entry_id"]
    hub_entry = hass.config_entries.async_get_entry(hub_entry_id)
    hub: HagleitnerHub | None = (
        getattr(hub_entry, "runtime_data", None) if hub_entry is not None else None
    )
    if hub is None:
        if hub_entry is not None and hub_entry.state == ConfigEntryState.NOT_LOADED:
            await hass.config_entries.async_setup(hub_entry_id)
            hub = getattr(hub_entry, "runtime_data", None)
    if hub is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="waiting_for_queue_connection",
        )

    entry.runtime_data = hub
    device_id = entry.data["device_id"]
    hub.adopt_device(device_id, entry.entry_id, entry.title)
    hub._async_record_device_source(device_id)
    identifiers = {(DOMAIN, device_id)}
    device_registry = dr.async_get(hass)
    existing_devices = device_registry.async_get_devices(identifiers=identifiers)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers=identifiers,
        manufacturer=MANUFACTURER,
        model=_device_model(entry.data),
        model_id=device_model_id(entry.data.get("device_type_id")),
        sw_version=hub.firmware_version_for_device(device_id),
        name=entry.data["device_name"],
    )
    hub.async_update_device_links()
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


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
) -> bool:
    """Unload an adopted device or its queue connection."""
    if entry.data.get("entry_type") == "device":
        hub = getattr(entry, "runtime_data", None)
        if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            return False
        if hub is not None:
            hub.unadopt_device(entry.data["device_id"])
        entry.runtime_data = None
        return True

    hub = getattr(entry, "runtime_data", None)
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
            device_entry.runtime_data = getattr(alternate_entry, "runtime_data", None)
            retained_entries.add(device_entry.entry_id)

    unloaded_entries: list[HagleitnerConfigEntry] = []
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

    if hub is not None and hub.receiver_task is not None:
        hub.receiver_task.cancel()
        try:
            await hub.receiver_task
        except asyncio.CancelledError:
            pass
    entry.runtime_data = None
    return True


async def async_remove_entry(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
) -> None:
    """Clean up repair issues when a config entry is removed."""
    async_clear_queue_not_found_issue(hass, entry.entry_id)
    if entry.data.get("entry_type") == "device":
        async_clear_maintenance_issues(hass, entry.data["device_id"])


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Remove a user's adopted device and its per-device config entry together."""
    device_id = entry.data.get("device_id")
    if not (
        entry.data.get("entry_type") == "device"
        and isinstance(device_id, str)
        and device_entry.config_entry_id == entry.entry_id
        and (DOMAIN, device_id) in device_entry.identifiers
    ):
        return False

    # This integration gives each adopted device its own config entry. Remove that
    # entry on the user's explicit device deletion so it cannot leave an orphaned
    # adoption that silently suppresses rediscovery on the push-only feed.
    await hass.config_entries.async_remove(entry.entry_id)
    return True
