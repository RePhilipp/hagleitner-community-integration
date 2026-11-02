"""Binary sensors for adopted Hagleitner devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HagleitnerHub
from .resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)

_REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
_FILL_STATUS_EQUIVALENT_ID = "9c336908-7a04-4adc-8bd7-08dc3d205c10"


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

        entities = []
        for mode in _binary_modes(snapshot):
            unique_id = f"{device_id}_{snapshot.key}_{mode}"
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
                )
            )
        if entities:
            async_add_entities(entities)

    for snapshot in hub.resources_for_device(device_id):
        add_resource(snapshot)
    entry.async_on_unload(hub.async_add_resource_listener(device_id, add_resource))


def _binary_modes(snapshot: ResourceValueSnapshot) -> tuple[str, ...]:
    """Return the binary-sensor meanings for one supported resource."""
    definition = snapshot.definition
    if definition is None:
        return ()
    if definition.kind == "battery":
        if snapshot.mapped_value == "mains_adapter":
            return ("battery_charging",)
        return ("battery",)
    if definition.kind == "problem":
        return ("problem",)
    if snapshot.equivalent_id == _REFILL_STATE_EQUIVALENT_ID:
        return ("refill_problem",)
    if snapshot.equivalent_id == _FILL_STATUS_EQUIVALENT_ID:
        return ("fill_problem",)
    if definition.kind == "connection":
        return ("connectivity", "connection_problem")
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
            "battery_charging": "Battery charging",
            "problem": definition.name,
            "connectivity": "Connectivity",
            "refill_problem": "Refill problem",
            "fill_problem": "Fill status problem",
            "connection_problem": "Connection problem",
        }[mode]
        self._attr_unique_id = f"{device_id}_{resource_key}_{mode}"
        self._attr_device_class = {
            "battery": BinarySensorDeviceClass.BATTERY,
            "battery_charging": BinarySensorDeviceClass.BATTERY_CHARGING,
            "problem": BinarySensorDeviceClass.PROBLEM,
            "connectivity": BinarySensorDeviceClass.CONNECTIVITY,
            "refill_problem": BinarySensorDeviceClass.PROBLEM,
            "fill_problem": BinarySensorDeviceClass.PROBLEM,
            "connection_problem": BinarySensorDeviceClass.PROBLEM,
        }[mode]

    @property
    def is_on(self) -> bool | None:
        """Return the current low-battery, problem, or connectivity state."""
        snapshot = self._hub.value_for_resource(self._device_id, self._resource_key)
        if snapshot is None:
            return None

        if self._mode == "battery":
            if snapshot.mapped_value in ("low", "empty"):
                return True
            if snapshot.mapped_value in ("ok", "mains_adapter"):
                return False
            return None
        if self._mode == "battery_charging":
            if snapshot.mapped_value == "mains_adapter":
                return True
            if snapshot.mapped_value in ("ok", "low", "empty"):
                return False
            return None
        if self._mode == "problem":
            if snapshot.mapped_value == "error":
                return True
            if snapshot.mapped_value == "no_error":
                return False
            return None
        if self._mode == "refill_problem":
            if snapshot.mapped_value == "empty":
                return True
            if snapshot.mapped_value in ("full", "low"):
                return False
            return None
        if self._mode == "fill_problem":
            if snapshot.mapped_value == "full":
                return True
            if snapshot.mapped_value in ("empty", "nearly_full"):
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
        if self._mode == "connection_problem":
            if snapshot.mapped_value == "offline":
                return True
            if snapshot.mapped_value in (
                "temporarily_offline",
                "online",
                "not_connected",
                "not_available",
                "available",
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
