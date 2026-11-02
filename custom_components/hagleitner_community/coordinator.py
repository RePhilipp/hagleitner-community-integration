"""In-memory state and discovery for one Azure Service Bus queue."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from asyncio import Task

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import callback

from .const import DOMAIN
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
            for listener in tuple(self._resource_listeners.get(device_id, ())):
                listener(snapshot)

        for listener in tuple(self._state_listeners.get(device_id, ())):
            listener()

    def adopt_device(self, device_id: str) -> None:
        """Enable the device after the user confirms the discovery flow."""
        self.adopted_device_ids.add(device_id)
        self._pending_discoveries.pop(device_id, None)

    def unadopt_device(self, device_id: str) -> None:
        """Stop publishing values after a device config entry is removed."""
        self.adopted_device_ids.discard(device_id)
        self._state_listeners.pop(device_id, None)
        self._resource_listeners.pop(device_id, None)

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
