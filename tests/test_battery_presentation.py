"""Tests for battery entity presentation."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, PERCENTAGE

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
    _binary_modes,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerSensor,
    _sensor_modes,
)

_BATTERY_DEFINITION = ResourceDefinition(
    name="Energy supply status",
    kind="battery",
    enum_values={0: "ok", 1: "low", 2: "empty", 3: "mains_adapter"},
    battery_percent_values={0: 100, 1: 20, 2: 0, 3: None},
)


def _battery_snapshot(mapped_value: str, raw_value: int) -> ResourceValueSnapshot:
    """Build a battery resource reading."""
    return ResourceValueSnapshot(
        key="battery-resource",
        logged_at=None,
        resource_type_id=1,
        instance_number=0,
        equivalent_id="battery",
        raw_value=raw_value,
        mapped_value=mapped_value,
        raw_resource={},
        definition=_BATTERY_DEFINITION,
        device_type_names=frozenset(),
    )


class _BatteryHub:
    """Provide one battery reading to the entity."""

    def __init__(self, snapshot: ResourceValueSnapshot) -> None:
        self._snapshot = snapshot

    def value_for_resource(self, device_id: str, resource_key: str):
        return self._snapshot


def test_battery_percentage_is_primary_and_status_is_diagnostic():
    """Keep the useful percentage primary and status entities diagnostic."""
    snapshot = _battery_snapshot("low", 1)

    assert _sensor_modes(_BATTERY_DEFINITION, snapshot) == (
        ("enum", _BATTERY_DEFINITION.name),
        ("battery_level", None),
    )
    assert _binary_modes(snapshot) == ("battery",)

    level_entity = HagleitnerSensor(
        _BatteryHub(snapshot),
        "device",
        snapshot.key,
        _BATTERY_DEFINITION,
        frozenset(),
        "battery_level",
        None,
        None,
    )
    assert level_entity.native_value == 20
    assert level_entity._attr_device_class == SensorDeviceClass.BATTERY
    assert level_entity._attr_native_unit_of_measurement == PERCENTAGE
    assert level_entity._attr_state_class == SensorStateClass.MEASUREMENT
    assert getattr(level_entity, "_attr_entity_category", None) is None

    enum_entity = HagleitnerSensor(
        _BatteryHub(snapshot),
        "device",
        snapshot.key,
        _BATTERY_DEFINITION,
        frozenset(),
        "enum",
        _BATTERY_DEFINITION.name,
        None,
    )
    assert enum_entity.native_value == "low"
    assert enum_entity._attr_entity_category == EntityCategory.DIAGNOSTIC

    binary_entity = HagleitnerBinarySensor(
        _BatteryHub(snapshot),
        "device",
        snapshot.key,
        _BATTERY_DEFINITION,
        "battery",
        None,
    )
    assert binary_entity.is_on is True
    assert binary_entity.unique_id == "device_battery-resource_battery"
    assert getattr(binary_entity, "_attr_device_class", None) is None
    assert binary_entity._attr_entity_category == EntityCategory.DIAGNOSTIC
    assert binary_entity._attr_icon == "mdi:battery-alert"


def test_normal_battery_is_reported_as_one_hundred_percent():
    """The normal battery state remains available through the canonical sensor."""
    snapshot = _battery_snapshot("ok", 0)
    entity = HagleitnerSensor(
        _BatteryHub(snapshot),
        "device",
        snapshot.key,
        _BATTERY_DEFINITION,
        frozenset(),
        "battery_level",
        None,
        None,
    )

    assert entity.native_value == 100


def test_mains_adapter_indicator_is_preserved():
    """A distinct mains-adapter indication remains available."""
    snapshot = _battery_snapshot("mains_adapter", 3)

    assert _sensor_modes(_BATTERY_DEFINITION, snapshot) == (
        ("enum", _BATTERY_DEFINITION.name),
    )
    assert _binary_modes(snapshot) == ("mains_adapter",)
