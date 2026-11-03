"""Shared device state and discovery across Azure Service Bus queue hubs."""

from __future__ import annotations

import logging
import time
from asyncio import Task
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .device import device_info, is_valid_customer_id
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
    restore_resource_snapshot,
    serialize_resource_snapshot,
    should_accept_reading,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_DISCOVERY_RETRY_SECONDS = 120
_STATE_STORE_VERSION = 1
_STATE_STORE_KEY = f"{DOMAIN}_device_state"


async def async_restore_persisted_state(hass: HomeAssistant) -> None:
    """Load the last known adopted-device values before platforms are set up."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_state_restored"):
        return

    store: Store[dict[str, Any]] = Store(
        hass,
        _STATE_STORE_VERSION,
        _STATE_STORE_KEY,
        private=True,
    )
    stored = await store.async_load()
    shared = domain_data.setdefault("_shared_device_state", {})
    latest_values = shared.setdefault("latest_values", {})
    device_metadata = shared.setdefault("device_metadata", {})

    if isinstance(stored, dict):
        stored_devices = stored.get("devices", {})
        if isinstance(stored_devices, dict):
            for device_id, device_data in stored_devices.items():
                if not isinstance(device_id, str) or not isinstance(device_data, dict):
                    continue
                stored_resources = device_data.get("resources", {})
                if isinstance(stored_resources, dict):
                    restored_resources = {}
                    for resource_key, resource_data in stored_resources.items():
                        if not isinstance(resource_key, str):
                            continue
                        snapshot = restore_resource_snapshot(resource_data)
                        if snapshot is not None and snapshot.key == resource_key:
                            restored_resources[resource_key] = snapshot
                    if restored_resources:
                        latest_values[device_id] = restored_resources

                metadata = _restore_device_metadata(device_data.get("metadata"))
                if metadata is not None:
                    device_metadata[device_id] = metadata

    shared["_state_store"] = store
    domain_data["_state_restored"] = True


def _restore_device_metadata(data: Any) -> DeviceMetadata | None:
    """Restore only the typed metadata fields used by integration entities."""
    if not isinstance(data, dict):
        return None

    customer_id = data.get("customer_id")
    if not isinstance(customer_id, int) or isinstance(customer_id, bool):
        customer_id = None
    metadata = DeviceMetadata(
        customer_name=(
            data["customer_name"]
            if isinstance(data.get("customer_name"), str)
            else None
        ),
        customer_id=customer_id,
        location=data["location"] if isinstance(data.get("location"), str) else None,
        mount_point=(
            data["mount_point"]
            if isinstance(data.get("mount_point"), str)
            else None
        ),
        innermost_location=(
            data["innermost_location"]
            if isinstance(data.get("innermost_location"), str)
            else None
        ),
    )
    return (
        metadata
        if any(
            (
                metadata.customer_name,
                metadata.customer_id,
                metadata.location,
                metadata.mount_point,
                metadata.innermost_location,
            )
        )
        else None
    )


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
        self._shared_state = shared
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
        self._async_record_customer_id(device_id)
        self._async_record_device_location(device_id)
        for snapshot in resource_updates.values():
            self._async_update_maintenance_issue(device_id, snapshot)
            for listener in tuple(self._resource_listeners.get(device_id, ())):
                listener(snapshot)

        if not resource_updates and not metadata_changed:
            return

        self._async_schedule_state_save()
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
        self._async_record_device_location(device_id)
        self._async_schedule_state_save()
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

    def _async_record_customer_id(self, device_id: str) -> None:
        """Persist a known customer ID and update an existing device link."""
        device_entry_id = self.device_entry_ids.get(device_id)
        if device_entry_id is None:
            return
        device_entry = self.hass.config_entries.async_get_entry(device_entry_id)
        if device_entry is None:
            return

        customer_id = device_entry.data.get("customer_id")
        if not is_valid_customer_id(customer_id):
            customer_id = self.metadata_for_device(device_id).customer_id
            if not is_valid_customer_id(customer_id):
                return
            self.hass.config_entries.async_update_entry(
                device_entry,
                data={
                    **device_entry.data,
                    "customer_id": customer_id,
                },
            )

        configuration_url = device_info(device_id, customer_id).get(
            "configuration_url"
        )
        if configuration_url is None:
            return
        device_registry = dr.async_get(self.hass)
        registered_device = next(
            iter(
                device_registry.async_get_devices(
                    identifiers={(DOMAIN, device_id)}
                )
            ),
            None,
        )
        if (
            registered_device is not None
            and registered_device.configuration_url != configuration_url
        ):
            device_registry.async_update_device(
                registered_device.id,
                configuration_url=configuration_url,
            )

    def _async_record_device_location(self, device_id: str) -> None:
        """Persist the latest HSM location for suggestions after a restart."""
        device_entry_id = self.device_entry_ids.get(device_id)
        if device_entry_id is None:
            return
        device_entry = self.hass.config_entries.async_get_entry(device_entry_id)
        if device_entry is None:
            return

        location = self.metadata_for_device(device_id).location
        if not location or device_entry.data.get("_hsm_location_path") == location:
            return
        self.hass.config_entries.async_update_entry(
            device_entry,
            data={
                **device_entry.data,
                "_hsm_location_path": location,
            },
        )

    def _async_schedule_state_save(self) -> None:
        """Debounce persistence of the latest adopted-device values."""
        store: Store[dict[str, Any]] | None = self._shared_state.get("_state_store")
        if store is not None:
            store.async_delay_save(self._serialize_persisted_state, delay=1)

    def _serialize_persisted_state(self) -> dict[str, Any]:
        """Serialize only supported values and metadata for adopted devices."""
        devices: dict[str, Any] = {}
        for device_id in self.adopted_device_ids:
            resources = {}
            for key, snapshot in self.latest_values.get(device_id, {}).items():
                serialized = serialize_resource_snapshot(snapshot)
                if serialized is not None:
                    resources[key] = serialized

            metadata = self.device_metadata.get(device_id)
            serialized_metadata = (
                {
                    "customer_name": metadata.customer_name,
                    "customer_id": metadata.customer_id,
                    "location": metadata.location,
                    "mount_point": metadata.mount_point,
                    "innermost_location": metadata.innermost_location,
                }
                if metadata is not None
                else {}
            )
            if resources or any(
                value is not None for value in serialized_metadata.values()
            ):
                devices[device_id] = {
                    "resources": resources,
                    "metadata": serialized_metadata,
                }
        return {"devices": devices}

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
        discovery_data: dict[str, Any] = {
            "hub_entry_id": self.entry.entry_id,
            "device_id": device_id,
            "device_type_id": device_type_id,
            "device_name": device_display_name(message),
        }
        metadata = self.metadata_for_device(device_id)
        if is_valid_customer_id(metadata.customer_id):
            discovery_data["customer_id"] = metadata.customer_id
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
                _innermost_location_name(
                    metadata.location,
                    metadata.innermost_location,
                ),
                _parent_location_name(metadata.location),
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
        metadata_by_device = {}

    normalized_path = _normalize_location_path(location_path)
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    persisted_locations = {
        entry.data["device_id"]: entry.data["_hsm_location_path"]
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("entry_type") == "device"
        and isinstance(entry.data.get("device_id"), str)
        and isinstance(entry.data.get("_hsm_location_path"), str)
    }
    matching_area_ids: set[str] = set()
    for device in device_registry.devices:
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
        if candidate_path is None:
            candidate_path = persisted_locations.get(candidate_id)
        if candidate_path is None:
            location_entity = next(
                (
                    entity
                    for entity in er.async_entries_for_device(
                        entity_registry,
                        device.id,
                    )
                    if entity.platform == DOMAIN
                    and entity.domain == "sensor"
                    and entity.unique_id == f"{candidate_id}_location"
                ),
                None,
            )
            location_state = (
                hass.states.get(location_entity.entity_id)
                if location_entity is not None
                else None
            )
            if (
                location_state is not None
                and location_state.state not in ("unknown", "unavailable")
            ):
                candidate_path = location_state.state
        if (
            not isinstance(candidate_path, str)
            or _normalize_location_path(candidate_path) != normalized_path
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
    floor_name: str | None = None,
) -> str | None:
    """Suggest an exact floor-and-room match, then an exact room match."""
    if not location_name:
        return None

    normalized_location = _normalize_area_name(location_name)
    if not normalized_location:
        return None

    areas = list(ar.async_get(hass).async_list_areas())
    if floor_name and (normalized_floor := _normalize_area_name(floor_name)):
        matching_floors = [
            floor
            for floor in fr.async_get(hass).async_list_floors()
            if _normalize_area_name(floor.name) == normalized_floor
        ]
        if len(matching_floors) == 1:
            floor_matches = {
                area.id
                for area in areas
                if area.floor_id == matching_floors[0].floor_id
                and _normalize_area_name(area.name) == normalized_location
            }
            if len(floor_matches) == 1:
                return next(iter(floor_matches))

    exact_matches = {
        area.id
        for area in areas
        if _normalize_area_name(area.name) == normalized_location
    }
    if len(exact_matches) == 1:
        return next(iter(exact_matches))
    return None


def _innermost_location_name(
    location_path: str | None,
    innermost_location: str | None,
) -> str | None:
    """Return the leaf location, including when HSM supplies a delimited path."""
    if isinstance(innermost_location, str) and innermost_location.strip():
        return innermost_location.strip()

    segments = _location_path_segments(location_path)
    return segments[-1] if segments else None


def _parent_location_name(location_path: str | None) -> str | None:
    """Return the HSM path segment immediately above the room."""
    segments = _location_path_segments(location_path)
    return segments[-2] if len(segments) > 1 else None


def _location_path_segments(location_path: str | None) -> list[str]:
    """Split an HSM location path into non-empty, trimmed segments."""
    if not isinstance(location_path, str):
        return []
    return [
        segment.strip()
        for segment in location_path.replace(">", "/").split("/")
        if segment.strip()
    ]


def _normalize_area_name(name: str) -> str:
    """Trim and case-fold a room name for exact area-name matching."""
    return name.strip().casefold()


def _normalize_location_path(path: str) -> str:
    """Normalize whitespace and case before comparing HSM location paths."""
    return " ".join(path.casefold().split())
