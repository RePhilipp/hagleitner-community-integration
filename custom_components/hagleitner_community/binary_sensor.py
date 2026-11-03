"""Binary sensors for adopted Hagleitner devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HagleitnerHub
from .device import device_info
from .resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    source_timestamp,
)

_LEGACY_UNIQUE_ID_SUFFIXES = {"mains_adapter": "battery_charging"}
_OBSOLETE_CONSUMABLE_PROBLEM_SUFFIXES = (
    "_refill_problem",
    "_fill_problem",
)


def _unique_id_suffix(mode: str) -> str:
    """Keep established registry IDs when a sensor's presentation changes."""
    return _LEGACY_UNIQUE_ID_SUFFIXES.get(mode, mode)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for one adopted device."""
    device_id = entry.data["device_id"]
    _remove_obsolete_consumable_problem_entities(hass, entry, device_id)

    hub: HagleitnerHub | None = hass.data[DOMAIN].get(entry.data["hub_entry_id"])
    if hub is None:
        raise ConfigEntryNotReady("Waiting for the Hagleitner queue connection")

    customer_id = entry.data.get("customer_id")
    added_ids: set[str] = set()

    def add_resource(snapshot: ResourceValueSnapshot) -> None:
        definition = snapshot.definition
        if definition is None:
            return

        entities = []
        for mode in _binary_modes(snapshot):
            unique_id = f"{device_id}_{snapshot.key}_{_unique_id_suffix(mode)}"
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


@callback
def _remove_obsolete_consumable_problem_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: str,
) -> None:
    """Remove old refill/fill problem binary sensors from the entity registry."""
    registry = er.async_get(hass)
    device_prefix = f"{device_id}_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.platform == DOMAIN
            and entity.domain == "binary_sensor"
            and entity.unique_id.startswith(device_prefix)
            and entity.unique_id.endswith(_OBSOLETE_CONSUMABLE_PROBLEM_SUFFIXES)
        ):
            registry.async_remove(entity.entity_id)


def _binary_modes(snapshot: ResourceValueSnapshot) -> tuple[str, ...]:
    """Return the binary-sensor meanings for one supported resource."""
    definition = snapshot.definition
    if definition is None:
        return ()
    if definition.kind == "opening":
        return ("opening",)
    if definition.kind == "presence":
        return ("refill_inserted",)
    if definition.kind == "maintenance":
        return ("maintenance_required",)
    if definition.kind == "battery":
        if snapshot.mapped_value == "mains_adapter":
            return ("mains_adapter",)
        return ("battery",)
    if definition.kind == "problem":
        return ("problem",)
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
        customer_id: int | None,
    ) -> None:
        """Initialize a binary sensor for one resource instance."""
        self._hub = hub
        self._device_id = device_id
        self._resource_key = resource_key
        self._definition = definition
        self._mode = mode
        self._attr_device_info = device_info(device_id, customer_id)
        if mode == "battery":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_icon = "mdi:battery-alert"
        elif mode == "opening":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if mode in {
            "battery",
            "mains_adapter",
            "connectivity",
            "connection_problem",
        }:
            self._attr_translation_key = mode
        else:
            self._attr_name = definition.name
        self._attr_unique_id = (
            f"{device_id}_{resource_key}_{_unique_id_suffix(mode)}"
        )
        if mode == "refill_inserted":
            self._attr_icon = "mdi:package-check"
        elif mode == "opening":
            self._attr_icon = "mdi:package-variant"
        elif mode not in {"battery", "opening"}:
            self._attr_device_class = {
                "mains_adapter": BinarySensorDeviceClass.PLUG,
                "problem": BinarySensorDeviceClass.PROBLEM,
                "connectivity": BinarySensorDeviceClass.CONNECTIVITY,
                "connection_problem": BinarySensorDeviceClass.PROBLEM,
                "maintenance_required": BinarySensorDeviceClass.PROBLEM,
            }[mode]

    @property
    def is_on(self) -> bool | None:
        """Return the current low-battery, problem, or connectivity state."""
        snapshot = self._hub.value_for_resource(self._device_id, self._resource_key)
        if snapshot is None:
            return None

        if self._mode == "refill_inserted":
            if snapshot.mapped_value == "inserted":
                return True
            if snapshot.mapped_value == "removed":
                return False
            return None
        if self._mode == "maintenance_required":
            if snapshot.mapped_value == "change_required":
                return True
            if snapshot.mapped_value == "no_change_required":
                return False
            return None
        if self._mode == "opening":
            if snapshot.mapped_value == "opened":
                return True
            if snapshot.mapped_value == "closed":
                return False
            return None
        if self._mode == "battery":
            if snapshot.mapped_value in ("low", "empty"):
                return True
            if snapshot.mapped_value in ("ok", "mains_adapter"):
                return False
            return None
        if self._mode == "mains_adapter":
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
