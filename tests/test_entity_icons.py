"""Tests for icons shown by Hagleitner resource entities."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    SUPPORTED_RESOURCES_BY_EQUIVALENT_ID,
)
from custom_components.hagleitner_community.sensor import HagleitnerSensor

_BATTERY_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "77d144fd-d7a3-42f7-03aa-08dac1664f9a"
]
_REFILL_STATE_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
]
_CONNECTION_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "7c178f1d-271f-4554-03ac-08dac1664f9a"
]
_ERROR_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "9a77375d-964c-451f-03ab-08dac1664f9a"
]
_OPENING_DEFINITION = ResourceDefinition(
    name="Cover state",
    kind="opening",
    enum_values={0: "opened", 1: "closed"},
)


class _EntityHub:
    """Provide one resource snapshot to an entity."""

    def __init__(self, snapshot: ResourceValueSnapshot) -> None:
        self._snapshot = snapshot

    def value_for_resource(self, device_id: str, resource_key: str):
        return self._snapshot


def _snapshot(
    definition: ResourceDefinition,
    *,
    mapped_value: str = "low",
    raw_value: int = 1,
) -> ResourceValueSnapshot:
    """Build a resource reading for an icon presentation test."""
    return ResourceValueSnapshot(
        key="resource",
        logged_at=None,
        resource_type_id=1,
        instance_number=0,
        equivalent_id=None,
        raw_value=raw_value,
        mapped_value=mapped_value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset({"foam dispenser"}),
    )


def _sensor(
    definition: ResourceDefinition,
    *,
    mode: str,
    mapped_value: str = "low",
) -> HagleitnerSensor:
    snapshot = _snapshot(definition, mapped_value=mapped_value)
    return HagleitnerSensor(
        _EntityHub(snapshot),
        "device",
        snapshot.key,
        definition,
        snapshot.device_type_names,
        mode,
        definition.name,
        None,
    )


def test_sensor_icons_match_the_resource_meaning():
    """Avoid product-type icons for counts and status enums."""
    for equivalent_id, expected_icon in (
        ("84b96502-7738-43fb-f3dd-08dace26c91e", "mdi:counter"),
        ("491d2cd9-92a0-4107-f3de-08dace26c91e", "mdi:counter"),
    ):
        entity = _sensor(
            SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[equivalent_id],
            mode="counter",
        )
        assert entity._attr_icon == expected_icon

    assert _sensor(_BATTERY_DEFINITION, mode="enum")._attr_icon == "mdi:battery-alert"
    assert _sensor(_CONNECTION_DEFINITION, mode="enum")._attr_icon == "mdi:lan-connect"
    assert (
        _sensor(_REFILL_STATE_DEFINITION, mode="enum")._attr_icon
        == "mdi:package-variant-closed"
    )
    assert _sensor(_OPENING_DEFINITION, mode="enum")._attr_icon == "mdi:package-variant"


def test_battery_level_uses_home_assistant_battery_icon_pattern():
    """Let HA render the battery-level icon from its battery device class."""
    entity = _sensor(_BATTERY_DEFINITION, mode="battery_level")

    assert entity._attr_device_class == SensorDeviceClass.BATTERY
    assert getattr(entity, "_attr_icon", None) is None


def test_binary_statuses_use_home_assistant_device_class_icons():
    """Use HA's standard state-aware icons for connection and problem statuses."""
    for definition, mode, expected_class in (
        (
            _CONNECTION_DEFINITION,
            "connection_problem",
            BinarySensorDeviceClass.PROBLEM,
        ),
        (
            _CONNECTION_DEFINITION,
            "connectivity",
            BinarySensorDeviceClass.CONNECTIVITY,
        ),
        (_ERROR_DEFINITION, "problem", BinarySensorDeviceClass.PROBLEM),
        (
            _REFILL_STATE_DEFINITION,
            "refill_problem",
            BinarySensorDeviceClass.PROBLEM,
        ),
    ):
        entity = HagleitnerBinarySensor(
            _EntityHub(_snapshot(definition)),
            "device",
            "resource",
            definition,
            mode,
            None,
        )
        assert entity._attr_device_class == expected_class

    battery = HagleitnerBinarySensor(
        _EntityHub(_snapshot(_BATTERY_DEFINITION)),
        "device",
        "battery",
        _BATTERY_DEFINITION,
        "battery",
        None,
    )
    assert battery._attr_icon == "mdi:battery-alert"

    opening = HagleitnerBinarySensor(
        _EntityHub(_snapshot(_OPENING_DEFINITION, mapped_value="closed", raw_value=1)),
        "device",
        "cover",
        _OPENING_DEFINITION,
        "opening",
        None,
    )
    assert opening._attr_icon == "mdi:package-variant"
