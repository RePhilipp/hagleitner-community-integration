"""In-memory state and discovery for one Azure Service Bus queue."""

from __future__ import annotations

import logging
import time
from asyncio import Task
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import callback

from .const import DOMAIN
from .repairs import async_update_maintenance_issue
from .resource_data import (
    ResourceValueSnapshot,
    device_display_name,
    device_identity,
    log_resource_values,
    resource_value_snapshots,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_DISCOVERY_RETRY_SECONDS = 120


class HagleitnerHub:
    """Keep the latest queue values and notify adopted device entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        logger: logging.Logger,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.logger = logger
        self.adopted_device_ids: set[str] = set()
        self.device_entry_ids: dict[str, str] = {}
        self.device_names: dict[str, str] = {}
        self.latest_values: dict[str, dict[str, ResourceValueSnapshot]] = {}
        self._pending_discoveries: dict[str, float] = {}
        self._state_listeners: dict[str, set[Callable[[], None]]] = {}
        self._resource_listeners: dict[
            str, set[Callable[[ResourceValueSnapshot], None]]
        ] = {}
        self.receiver_task: Task[None] | None = None

    async def async_handle_message(self, message: dict[str, Any]) -> None:
        """Cache a message, prompt for unadopted devices, and update entities."""
        device_id, device_type_id = device_identity(message)
        device_name = device_display_name(message)
        self.device_names[device_id] = device_name
        log_resource_values(message, self.logger)

        device_values = self.latest_values.setdefault(device_id, {})
        resource_updates: dict[str, ResourceValueSnapshot] = {}
        for snapshot in resource_value_snapshots(message):
            device_values[snapshot.key] = snapshot
            if snapshot.definition is not None:
                resource_updates[snapshot.key] = snapshot

        if device_id not in self.adopted_device_ids:
            await self._async_start_discovery(
                message,
                device_id,
                device_type_id,
            )
            return

        for snapshot in resource_updates.values():
            self._async_update_maintenance_issue(device_id, snapshot)
            for listener in tuple(self._resource_listeners.get(device_id, ())):
                listener(snapshot)

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
        await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={
                "hub_entry_id": self.entry.entry_id,
                "device_id": device_id,
                "device_type_id": device_type_id,
                "device_name": device_display_name(message),
            },
        )
