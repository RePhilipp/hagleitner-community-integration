"""Shared device state and discovery across Azure Service Bus queue hubs."""

from __future__ import annotations

import logging
import time
from asyncio import Task
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
)

from .const import DOMAIN
from .repairs import async_update_maintenance_issue
from .resource_data import (
    DeviceMetadata,
    ResourceValueSnapshot,
    device_display_name,
    device_identity,
    log_resource_values,
    merge_device_metadata,
    parse_device_metadata,
    resource_value_snapshots,
    should_accept_reading,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_DISCOVERY_RETRY_SECONDS = 120


class HagleitnerHub:
    """Receive one queue's messages into shared device state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        logger: logging.Logger,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.logger = logger
        shared = hass.data[DOMAIN].setdefault("_shared_device_state", {})
        self.adopted_device_ids: set[str] = shared.setdefault(
            "adopted_device_ids", set()
        )
        self.device_entry_ids: dict[str, str] = shared.setdefault(
            "device_entry_ids", {}
        )
        self.device_names: dict[str, str] = shared.setdefault("device_names", {})
        self.device_metadata: dict[str, DeviceMetadata] = shared.setdefault(
            "device_metadata", {}
        )
        self.latest_values: dict[
            str, dict[str, ResourceValueSnapshot]
        ] = shared.setdefault("latest_values", {})
        self.device_sources: dict[str, set[str]] = shared.setdefault(
            "device_sources", {}
        )
        self._pending_discoveries: dict[str, float] = shared.setdefault(
            "pending_discoveries", {}
        )
        self._state_listeners: dict[str, set[Callable[[], None]]] = shared.setdefault(
            "state_listeners", {}
        )
        self._resource_listeners: dict[
            str, set[Callable[[ResourceValueSnapshot], None]]
        ] = shared.setdefault("resource_listeners", {})
        self.receiver_task: Task[None] | None = None

    async def async_handle_message(self, message: dict[str, Any]) -> None:
        """Cache a message, prompt for unadopted devices, and update entities."""
        device_id, device_type_id = device_identity(message)
        device_name = device_display_name(message)
        self.device_sources.setdefault(device_id, set()).add(self.entry.entry_id)
        self.device_names[device_id] = device_name
        log_resource_values(message, self.logger)

        current_metadata = self.device_metadata.get(device_id, DeviceMetadata())
        updated_metadata = merge_device_metadata(
            current_metadata,
            parse_device_metadata(message),
        )
        metadata_changed = updated_metadata != current_metadata
        if metadata_changed:
            self.device_metadata[device_id] = updated_metadata

        device_values = self.latest_values.setdefault(device_id, {})
        resource_updates: dict[str, ResourceValueSnapshot] = {}
        for snapshot in resource_value_snapshots(message):
            current = device_values.get(snapshot.key)
            if current is not None and not should_accept_reading(snapshot, current):
                continue
            if (
                current is not None
                and snapshot.logged_at == current.logged_at
                and snapshot.raw_value == current.raw_value
                and snapshot.mapped_value == current.mapped_value
            ):
                continue
            device_values[snapshot.key] = snapshot
            if snapshot.definition is not None:
                resource_updates[snapshot.key] = snapshot

        if device_id not in self.adopted_device_ids:
            configured_device = next(
                (
                    entry
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                    if (
                        entry.data.get("entry_type") == "device"
                        and entry.data.get("device_id") == device_id
                    )
                ),
                None,
            )
            if configured_device is None:
                await self._async_start_discovery(
                    message,
                    device_id,
                    device_type_id,
                )
                return
            self.adopt_device(
                device_id,
                configured_device.entry_id,
                configured_device.title,
            )

        self._async_record_device_source(device_id)
        for snapshot in resource_updates.values():
            self._async_update_maintenance_issue(device_id, snapshot)
            for listener in tuple(self._resource_listeners.get(device_id, ())):
                listener(snapshot)

        if not resource_updates and not metadata_changed:
            return

        for listener in tuple(self._state_listeners.get(device_id, ())):
            listener()

    def adopt_device(
        self,
        device_id: str,
        device_entry_id: str,
        device_name: str,
    ) -> None:
        """Enable the device after the user confirms the discovery flow."""
        self.adopted_device_ids.add(device_id)
        self.device_entry_ids[device_id] = device_entry_id
        self.device_names[device_id] = device_name
        self._pending_discoveries.pop(device_id, None)
        for snapshot in self.resources_for_device(device_id):
            self._async_update_maintenance_issue(device_id, snapshot)

    def unadopt_device(self, device_id: str) -> None:
        """Stop publishing values after a device config entry is removed."""
        self.adopted_device_ids.discard(device_id)
        self.device_entry_ids.pop(device_id, None)
        self.device_names.pop(device_id, None)
        self._state_listeners.pop(device_id, None)
        self._resource_listeners.pop(device_id, None)

    def _async_update_maintenance_issue(
        self,
        device_id: str,
        snapshot: ResourceValueSnapshot,
    ) -> None:
        """Synchronize one resource's active Home Assistant repair issues."""
        device_entry_id = self.device_entry_ids.get(device_id)
        if device_entry_id is None:
            return
        async_update_maintenance_issue(
            self.hass,
            device_id,
            device_entry_id,
            self.device_names.get(device_id, f"Hagleitner {device_id[:8]}"),
            snapshot,
            tuple(self.resources_for_device(device_id)),
        )

    def _async_record_device_source(self, device_id: str) -> None:
        """Persist additional queues that have reported an adopted device."""
        device_entry_id = self.device_entry_ids.get(device_id)
        if device_entry_id is None:
            return
        device_entry = self.hass.config_entries.async_get_entry(device_entry_id)
        if device_entry is None:
            return
        source_ids = list(device_entry.data.get("hub_entry_ids", ()))
        original_source_ids = list(source_ids)
        primary_hub_id = device_entry.data.get("hub_entry_id")
        if primary_hub_id is not None and primary_hub_id not in source_ids:
            source_ids.append(primary_hub_id)
        for source_id in self.device_sources.get(device_id, ()):
            if source_id not in source_ids:
                source_ids.append(source_id)
        if source_ids == original_source_ids:
            return
        self.hass.config_entries.async_update_entry(
            device_entry,
            data={
                **device_entry.data,
                "hub_entry_ids": source_ids,
            },
        )

    def resources_for_device(
        self, device_id: str
    ) -> tuple[ResourceValueSnapshot, ...]:
        """Return the current resource values for one adopted device."""
        return tuple(self.latest_values.get(device_id, {}).values())

    def value_for_resource(
        self, device_id: str, resource_key: str
    ) -> ResourceValueSnapshot | None:
        """Return the last received state for an entity's resource."""
        return self.latest_values.get(device_id, {}).get(resource_key)

    def metadata_for_device(self, device_id: str) -> DeviceMetadata:
        """Return the last received customer and location details."""
        return self.device_metadata.get(device_id, DeviceMetadata())

    @callback
    def async_add_state_listener(
        self, device_id: str, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe an entity to state updates for its device."""
        listeners = self._state_listeners.setdefault(device_id, set())
        listeners.add(listener)
        return lambda: listeners.discard(listener)

    @callback
    def async_add_resource_listener(
        self,
        device_id: str,
        listener: Callable[[ResourceValueSnapshot], None],
    ) -> Callable[[], None]:
        """Subscribe a platform to supported resource updates."""
        listeners = self._resource_listeners.setdefault(device_id, set())
        listeners.add(listener)
        return lambda: listeners.discard(listener)

    async def _async_start_discovery(
        self,
        message: dict[str, Any],
        device_id: str,
        device_type_id: str,
    ) -> None:
        """Open an adoption flow, throttling repeated messages for one device."""
        now = time.monotonic()
        last_started = self._pending_discoveries.get(device_id)
        if last_started is not None and now - last_started < _DISCOVERY_RETRY_SECONDS:
            return

        self._pending_discoveries[device_id] = now
        discovery_data = {
            "hub_entry_id": self.entry.entry_id,
            "device_id": device_id,
            "device_type_id": device_type_id,
            "device_name": device_display_name(message),
        }
        metadata = self.metadata_for_device(device_id)
        discovery_data["hsm_location_path"] = metadata.location or "—"
        discovery_data["hsm_mount_point"] = metadata.mount_point or "—"
        has_location_area, suggested_area_id = _suggest_area_from_hsm_location(
            self.hass,
            device_id,
            metadata.location,
        )
        if not has_location_area:
            suggested_area_id = _suggest_existing_area_id(
                self.hass,
                metadata.innermost_location,
            )
        if suggested_area_id is not None:
            discovery_data["suggested_area_id"] = suggested_area_id

        await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data=discovery_data,
        )


def _suggest_area_from_hsm_location(
    hass: HomeAssistant,
    device_id: str,
    location_path: str | None,
) -> tuple[bool, str | None]:
    """Reuse an adopted sibling device's area for the exact HSM location."""
    if not location_path:
        return False, None

    shared = hass.data.get(DOMAIN, {}).get("_shared_device_state", {})
    metadata_by_device = shared.get("device_metadata", {})
    if not isinstance(metadata_by_device, dict):
        return False, None

    normalized_path = _normalize_area_name(location_path)
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    matching_area_ids: set[str] = set()
    for device in device_registry.devices.values():
        candidate_id = next(
            (
                identifier
                for domain, identifier in device.identifiers
                if domain == DOMAIN
            ),
            None,
        )
        if candidate_id is None or candidate_id == device_id:
            continue
        metadata = metadata_by_device.get(candidate_id)
        candidate_path = (
            metadata.location if isinstance(metadata, DeviceMetadata) else None
        )
        if (
            not isinstance(candidate_path, str)
            or _normalize_area_name(candidate_path) != normalized_path
        ):
            continue
        if (
            device.area_id is not None
            and area_registry.async_get_area(device.area_id) is not None
        ):
            matching_area_ids.add(device.area_id)

    if len(matching_area_ids) == 1:
        return True, next(iter(matching_area_ids))
    if matching_area_ids:
        return True, None
    return False, None


def _suggest_existing_area_id(
    hass: HomeAssistant,
    location_name: str | None,
) -> str | None:
    """Suggest a confident match to an existing Home Assistant area."""
    if not location_name:
        return None

    normalized_location = _normalize_area_name(location_name)
    if not normalized_location:
        return None

    areas = list(ar.async_get(hass).async_list_areas())
    exact_matches = {
        area.id
        for area in areas
        if any(
            _normalize_area_name(name) == normalized_location
            for name in (area.name, *area.aliases)
        )
    }
    if len(exact_matches) == 1:
        return next(iter(exact_matches))
    if exact_matches:
        return None

    area_scores: list[tuple[float, str]] = []
    for area in areas:
        score = max(
            (
                SequenceMatcher(
                    None,
                    normalized_location,
                    _normalize_area_name(name),
                ).ratio()
                for name in (area.name, *area.aliases)
                if _normalize_area_name(name)
            ),
            default=0.0,
        )
        area_scores.append((score, area.id))

    area_scores.sort(reverse=True)
    if not area_scores or area_scores[0][0] < 0.85:
        return None
    if len(area_scores) > 1 and area_scores[0][0] - area_scores[1][0] < 0.1:
        return None
    return area_scores[0][1]


def _normalize_area_name(name: str) -> str:
    """Normalize whitespace and case before comparing location names."""
    return " ".join(name.casefold().split())
