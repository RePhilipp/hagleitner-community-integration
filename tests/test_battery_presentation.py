"""Tests for battery entity presentation."""

from __future__ import annotations

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, PERCENTAGE

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
    _binary_modes,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceValueSnapshot,
    SUPPORTED_RESOURCES_BY_EQUIVALENT_ID,
    battery_percentage,
    resource_value_snapshots,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerSensor,
    _sensor_modes,
)

_BATTERY_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "77d144fd-d7a3-42f7-03aa-08dac1664f9a"
]


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


@pytest.mark.parametrize("raw_value", (1, 2))
def test_catalog_low_energy_values_are_reported_as_twenty_percent(raw_value):
    """Both production-catalog low values map to the low battery percentage."""
    snapshot = resource_value_snapshots(
        {
            "deviceInfo": {"deviceId": "device-1"},
            "readings": [
                {
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 12288,
                                "resourceInstanceNo": 0,
                                "resourceInstanceEquivalentId": (
                                    "77d144fd-d7a3-42f7-03aa-08dac1664f9a"
                                ),
                            },
                            "integerValue": raw_value,
                        }
                    ]
                }
            ],
        }
    )[0]

    assert snapshot.mapped_value == "low"
    assert battery_percentage(snapshot) == 20
    assert _sensor_modes(_BATTERY_DEFINITION, snapshot) == (
        ("battery_level", None),
    )
    assert _binary_modes(snapshot) == ()

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
    assert level_entity._attr_entity_category is EntityCategory.DIAGNOSTIC


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
    """A mains adapter gets its own binary state, not an enum duplicate."""
    snapshot = _battery_snapshot("mains_adapter", 3)

    assert _sensor_modes(_BATTERY_DEFINITION, snapshot) == ()
    assert _binary_modes(snapshot) == ("mains_adapter",)
    entity = HagleitnerBinarySensor(
        _BatteryHub(snapshot),
        "device",
        snapshot.key,
        _BATTERY_DEFINITION,
        "mains_adapter",
        None,
    )
    assert entity.is_on is True
    assert entity._attr_device_class == BinarySensorDeviceClass.PLUG
