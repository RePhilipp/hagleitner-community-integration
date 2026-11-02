"""Sensors for adopted Hagleitner devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HagleitnerHub
from .resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    battery_percentage,
    device_type_icon,
    enum_options,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one adopted device."""
    hub: HagleitnerHub | None = hass.data[DOMAIN].get(entry.data["hub_entry_id"])
    if hub is None:
        raise ConfigEntryNotReady("Waiting for the Hagleitner queue connection")

    device_id = entry.data["device_id"]
    added_ids: set[str] = set()

    def add_resource(snapshot: ResourceValueSnapshot) -> None:
        definition = snapshot.definition
        if definition is None:
            return

        entities = []
        for mode, name in _sensor_modes(definition, snapshot):
            unique_id = f"{device_id}_{snapshot.key}_{mode}"
            if unique_id in added_ids:
                continue
            added_ids.add(unique_id)
            entities.append(
                HagleitnerSensor(
                    hub,
                    device_id,
                    snapshot.key,
                    definition,
                    snapshot.device_type_names,
                    mode,
                    name,
                )
            )
        if entities:
            async_add_entities(entities)

    for snapshot in hub.resources_for_device(device_id):
        add_resource(snapshot)
    entry.async_on_unload(hub.async_add_resource_listener(device_id, add_resource))


def _sensor_modes(
    definition: ResourceDefinition,
    snapshot: ResourceValueSnapshot,
) -> tuple[tuple[str, str], ...]:
    """Return HA sensor entities for a resource kind."""
    if definition.kind == "counter":
        return (("counter", definition.name),)
    if definition.kind == "enum":
        return (("enum", definition.name),)
    if definition.kind == "battery":
        modes = [("enum", definition.name)]
        if snapshot.mapped_value != "mains_adapter":
            modes.append(("battery_level", "Battery level"))
        return tuple(modes)
    if definition.kind == "connection":
        return (("enum", definition.name),)
    return ()


class HagleitnerSensor(SensorEntity):
    """A resource-backed sensor that receives updates from the queue hub."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hub: HagleitnerHub,
        device_id: str,
        resource_key: str,
        definition: ResourceDefinition,
        device_type_names: frozenset[str],
        mode: str,
        name: str,
    ) -> None:
        """Initialize a sensor for one resource instance."""
        self._hub = hub
        self._device_id = device_id
        self._resource_key = resource_key
        self._definition = definition
        self._mode = mode
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._attr_name = name
        self._attr_unique_id = f"{device_id}_{resource_key}_{mode}"
        if mode in ("counter", "enum"):
            self._attr_icon = device_type_icon(device_type_names)

        if mode == "enum":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = enum_options(definition, device_type_names)
        elif mode == "counter":
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif mode == "battery_level":
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        """Return the latest normalized value."""
        snapshot = self._hub.value_for_resource(self._device_id, self._resource_key)
        if snapshot is None:
            return None
        if self._mode == "battery_level":
            return battery_percentage(snapshot)
        if self._mode == "counter":
            return snapshot.raw_value
        if self._mode == "enum":
            if snapshot.mapped_value in self._attr_options:
                return snapshot.mapped_value
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
