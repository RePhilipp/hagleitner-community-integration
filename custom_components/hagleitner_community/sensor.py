"""Sensors for adopted Hagleitner devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HagleitnerConfigEntry, HagleitnerHub
from .device import device_info
from .resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    battery_percentage,
    enum_options,
    source_timestamp,
)

PARALLEL_UPDATES = 0
_OBSOLETE_BATTERY_STATUS_NAME = "Energy supply status"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one adopted device."""
    device_id = entry.data["device_id"]
    _remove_obsolete_battery_status_sensors(hass, entry, device_id)

    hub = getattr(entry, "runtime_data", None)
    if hub is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="waiting_for_queue_connection",
        )

    customer_id = entry.data.get("customer_id")
    added_ids: set[str] = set()

    def add_resource(snapshot: ResourceValueSnapshot) -> None:
        definition = snapshot.definition
        if definition is None:
            return

        entities = []
        for mode in _sensor_modes(definition, snapshot):
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
                    customer_id,
                )
            )
        if entities:
            async_add_entities(entities)

    for snapshot in hub.resources_for_device(device_id):
        add_resource(snapshot)
    entry.async_on_unload(hub.async_add_resource_listener(device_id, add_resource))
    async_add_entities(
        [
            HagleitnerMetadataSensor(
                hub,
                device_id,
                "customer_name",
                customer_id,
            ),
            HagleitnerMetadataSensor(hub, device_id, "customer_id", customer_id),
            HagleitnerMetadataSensor(hub, device_id, "location", customer_id),
            HagleitnerMetadataSensor(hub, device_id, "mount_point", customer_id),
        ]
    )


@callback
def _remove_obsolete_battery_status_sensors(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
    device_id: str,
) -> None:
    """Remove the old enum sensor now that battery percent is the primary value."""
    registry = er.async_get(hass)
    device_prefix = f"{device_id}_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.platform == DOMAIN
            and entity.domain == "sensor"
            and entity.unique_id.startswith(device_prefix)
            and entity.unique_id.endswith("_enum")
            and entity.original_name == _OBSOLETE_BATTERY_STATUS_NAME
        ):
            registry.async_remove(entity.entity_id)


def _sensor_modes(
    definition: ResourceDefinition,
    snapshot: ResourceValueSnapshot,
) -> tuple[str, ...]:
    """Return HA sensor entities for a resource kind."""
    if definition.kind == "counter":
        return ("counter",)
    if definition.kind == "measurement":
        return ("measurement",)
    if definition.kind == "diagnostic":
        return ("diagnostic",)
    if definition.kind == "enum":
        return ("enum",)
    if definition.kind == "opening":
        return ("enum",)
    if definition.kind == "battery":
        if snapshot.mapped_value == "mains_adapter":
            return ()
        return ("battery_level",)
    if definition.kind == "connection":
        return ("enum",)
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
        customer_id: int | None,
    ) -> None:
        """Initialize a sensor for one resource instance."""
        self._hub = hub
        self._device_id = device_id
        self._resource_key = resource_key
        self._definition = definition
        self._mode = mode
        self._attr_device_info = device_info(device_id, customer_id)
        self._attr_entity_registry_enabled_default = (
            definition.entity_registry_enabled_default
        )
        if definition.entity_category is not None:
            self._attr_entity_category = definition.entity_category
        if mode == "battery_level":
            self._attr_translation_key = "battery_level"
        elif definition.entity_translation_key is not None:
            self._attr_translation_key = definition.entity_translation_key
        self._attr_unique_id = f"{device_id}_{resource_key}_{mode}"
        if mode == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        if mode == "enum":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = enum_options(definition, device_type_names)
        elif mode in ("counter", "measurement"):
            if definition.device_class == "volume":
                self._attr_device_class = SensorDeviceClass.VOLUME
            elif definition.device_class == "signal_strength":
                self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
            if definition.unit == "milliliters":
                self._attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS
            elif definition.unit == "liters":
                self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
            elif definition.unit == "percentage":
                self._attr_native_unit_of_measurement = PERCENTAGE
            elif definition.unit == "milliseconds":
                self._attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
            elif definition.unit == "dBm":
                self._attr_native_unit_of_measurement = (
                    SIGNAL_STRENGTH_DECIBELS_MILLIWATT
                )
            self._attr_state_class = (
                SensorStateClass.TOTAL_INCREASING
                if mode == "counter"
                else SensorStateClass.MEASUREMENT
            )
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
        if self._mode in ("counter", "measurement", "diagnostic"):
            return snapshot.raw_value
        if self._mode == "enum":
            options = self._attr_options
            if options is not None and snapshot.mapped_value in options:
                return snapshot.mapped_value
            return None
        return None

    @property
    def available(self) -> bool:
        """Hide device readings only for an explicitly offline device."""
        return self._hub.receiver_available and (
            self._definition.kind == "connection"
            or not self._hub.device_is_offline(self._device_id)
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose the timestamp supplied with the resource reading."""
        snapshot = self._hub.value_for_resource(self._device_id, self._resource_key)
        if snapshot is None:
            return None
        timestamp = source_timestamp(snapshot.logged_at)
        return {"last_reading_at": timestamp} if timestamp is not None else None

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


class HagleitnerMetadataSensor(SensorEntity):
    """Expose customer or location metadata received with device messages."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hub: HagleitnerHub,
        device_id: str,
        metadata_key: str,
        customer_id: int | None,
    ) -> None:
        """Initialize a diagnostic sensor for one metadata field."""
        self._hub = hub
        self._device_id = device_id
        self._metadata_key = metadata_key
        self._attr_device_info = device_info(device_id, customer_id)
        self._attr_translation_key = f"metadata_{metadata_key}"
        self._attr_unique_id = f"{device_id}_{metadata_key}"
        self._attr_entity_registry_enabled_default = metadata_key != "customer_id"

    @property
    def native_value(self) -> Any:
        """Return the latest customer or location metadata."""
        metadata = self._hub.metadata_for_device(self._device_id)
        return getattr(metadata, self._metadata_key)

    @property
    def available(self) -> bool:
        """Hide metadata only while the queue or device is offline."""
        return self._hub.receiver_available and not self._hub.device_is_offline(
            self._device_id
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to metadata and state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._hub.async_add_state_listener(
                self._device_id,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the latest metadata to Home Assistant."""
        self.async_write_ha_state()
