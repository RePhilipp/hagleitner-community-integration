"""Binary sensors for adopted Hagleitner devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HagleitnerConfigEntry, HagleitnerHub
from .device import device_info
from .resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    source_timestamp,
)

PARALLEL_UPDATES = 0
_PROBLEM_MODE = "resource_problem"


def _unique_id_suffix(mode: str, definition: ResourceDefinition) -> str:
    """Return the configured unique-ID suffix for an entity mode."""
    if mode == _PROBLEM_MODE:
        return definition.problem_entity_translation_key or mode
    return mode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HagleitnerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for one adopted device."""
    device_id = entry.data["device_id"]

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
        for mode in _binary_modes(snapshot):
            mode_suffix = _unique_id_suffix(mode, definition)
            unique_id = f"{device_id}_{snapshot.key}_{mode_suffix}"
            if unique_id in added_ids:
                continue
            added_ids.add(unique_id)
            entities.append(
                HagleitnerBinarySensor(
                    hub,
                    device_id,
                    snapshot.key,
                    definition,
                    mode,
                    customer_id,
                )
            )
        if entities:
            async_add_entities(entities)

    for snapshot in hub.resources_for_device(device_id):
        add_resource(snapshot)
    entry.async_on_unload(hub.async_add_resource_listener(device_id, add_resource))


def _binary_modes(snapshot: ResourceValueSnapshot) -> tuple[str, ...]:
    """Return binary sensors derived from supported resource values."""
    definition = snapshot.definition
    if definition is None:
        return ()
    if definition.kind == "battery":
        if snapshot.mapped_value == "mains_adapter":
            return ("mains_adapter",)
    if definition.problem_entity_on_values:
        return (_PROBLEM_MODE,)
    return ()


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
        customer_id: int | None,
    ) -> None:
        """Initialize a binary sensor for one resource instance."""
        self._hub = hub
        self._device_id = device_id
        self._resource_key = resource_key
        self._definition = definition
        self._mode = mode
        self._attr_device_info = device_info(device_id, customer_id)
        if definition.entity_category is not None:
            self._attr_entity_category = definition.entity_category
        if mode == "mains_adapter":
            self._attr_translation_key = mode
        elif mode == _PROBLEM_MODE:
            if definition.problem_entity_translation_key:
                self._attr_translation_key = definition.problem_entity_translation_key
        mode_suffix = _unique_id_suffix(mode, definition)
        self._attr_unique_id = f"{device_id}_{resource_key}_{mode_suffix}"
        if mode == "mains_adapter":
            self._attr_device_class = BinarySensorDeviceClass.PLUG
        elif mode == _PROBLEM_MODE:
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        """Return the state represented by this binary sensor."""
        snapshot = self._hub.value_for_resource(self._device_id, self._resource_key)
        if snapshot is None:
            return None

        if self._mode == "mains_adapter":
            if snapshot.mapped_value == "mains_adapter":
                return True
            if snapshot.mapped_value in ("ok", "low"):
                return False
            return None
        if self._mode == _PROBLEM_MODE:
            if snapshot.mapped_value in self._definition.problem_entity_on_values:
                return True
            if snapshot.mapped_value in self._definition.enum_values.values():
                return False
            return None
        return None

    @property
    def available(self) -> bool:
        """Hide device values only while the queue or device is offline."""
        return self._hub.receiver_available and not self._hub.device_is_offline(
            self._device_id
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
