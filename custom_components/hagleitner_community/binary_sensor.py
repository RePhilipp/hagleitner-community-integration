"""Binary sensors for adopted Hagleitner devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HagleitnerHub
from .resource_data import ResourceDefinition, ResourceValueSnapshot


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for one adopted device."""
    hub: HagleitnerHub | None = hass.data[DOMAIN].get(entry.data["hub_entry_id"])
    if hub is None:
        raise ConfigEntryNotReady("Waiting for the Hagleitner queue connection")

    device_id = entry.data["device_id"]
    added_ids: set[str] = set()

    def add_resource(snapshot: ResourceValueSnapshot) -> None:
        definition = snapshot.definition
        if definition is None:
            return

        mode = _binary_mode(definition)
        if mode is None:
            return

        unique_id = f"{device_id}_{snapshot.key}_{mode}"
        if unique_id in added_ids:
            return
        added_ids.add(unique_id)
        async_add_entities(
            [
                HagleitnerBinarySensor(
                    hub,
                    device_id,
                    snapshot.key,
                    definition,
                    mode,
                )
            ]
        )

    for snapshot in hub.resources_for_device(device_id):
        add_resource(snapshot)
    entry.async_on_unload(hub.async_add_resource_listener(device_id, add_resource))


def _binary_mode(definition: ResourceDefinition) -> str | None:
    """Return the HA binary-sensor meaning for a resource kind."""
    if definition.kind == "battery":
        return "battery"
    if definition.kind == "problem":
        return "problem"
    if definition.kind == "connection":
        return "connectivity"
    return None


class HagleitnerBinarySensor(BinarySensorEntity):
    """A binary status derived from a Hagleitner resource value."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hub: HagleitnerHub,
        device_id: str,
        resource_key: str,
        definition: ResourceDefinition,
        mode: str,
    ) -> None:
        """Initialize a binary sensor for one resource instance."""
        self._hub = hub
        self._device_id = device_id
        self._resource_key = resource_key
        self._definition = definition
        self._mode = mode
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._attr_name = {
            "battery": "Battery",
            "problem": definition.name,
            "connectivity": "Connectivity",
        }[mode]
        self._attr_unique_id = f"{device_id}_{resource_key}_{mode}"
        self._attr_device_class = {
            "battery": BinarySensorDeviceClass.BATTERY,
            "problem": BinarySensorDeviceClass.PROBLEM,
            "connectivity": BinarySensorDeviceClass.CONNECTIVITY,
        }[mode]

    @property
    def is_on(self) -> bool | None:
        """Return the current low-battery, problem, or connectivity state."""
        snapshot = self._hub.value_for_resource(self._device_id, self._resource_key)
        if snapshot is None:
            return None

        if self._mode == "battery":
            if snapshot.raw_value in (1, 2):
                return True
            if snapshot.raw_value in (0, 3):
                return False
            return None
        if self._mode == "problem":
            if snapshot.mapped_value == "error":
                return True
            if snapshot.mapped_value == "no_error":
                return False
            return None
        if self._mode == "connectivity":
            if snapshot.mapped_value in ("online", "available"):
                return True
            if snapshot.mapped_value in (
                "offline",
                "temporarily_offline",
                "not_available",
            ):
                return False
            return None
        return None

    async def async_added_to_hass(self) -> None:
        """Subscribe to resource updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._hub.async_add_state_listener(
                self._device_id,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the latest queue value to Home Assistant."""
        self.async_write_ha_state()
