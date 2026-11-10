"""Tests for icons shown by Hagleitner resource entities."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.sensor import SensorDeviceClass

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
_FILL_STATUS_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "9c336908-7a04-4adc-8bd7-08dc3d205c10"
]
_CONNECTION_DEFINITION = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
    "7c178f1d-271f-4554-03ac-08dac1664f9a"
]
_OPENING_DEFINITION = ResourceDefinition(
    name="Cover state",
    kind="opening",
    entity_translation_key="cover_state",
    enum_values={0: "opened", 1: "closed"},
)
_ICONS_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "hagleitner_community"
    / "icons.json"
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
        None,
    )


def test_sensor_icons_are_defined_by_entity_translation_key():
    """Keep custom icons in icons.json instead of entity state attributes."""
    icons = json.loads(_ICONS_PATH.read_text())["entity"]["sensor"]
    for equivalent_id, expected_key, expected_icon in (
        (
            "84b96502-7738-43fb-f3dd-08dace26c91e",
            "dispense_count",
            "mdi:numeric",
        ),
        (
            "491d2cd9-92a0-4107-f3de-08dace26c91e",
            "refill_count",
            "mdi:numeric",
        ),
    ):
        entity = _sensor(
            SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[equivalent_id],
            mode="counter",
        )
        assert entity._attr_translation_key == expected_key
        assert icons[expected_key]["default"] == expected_icon

    for definition, expected_key, expected_icon in (
        (_CONNECTION_DEFINITION, "connection_status", "mdi:lan"),
        (_REFILL_STATE_DEFINITION, "refill_state", "mdi:beaker-outline"),
        (_FILL_STATUS_DEFINITION, "fill_status", "mdi:beaker"),
        (_OPENING_DEFINITION, "cover_state", "mdi:package-variant"),
    ):
        entity = _sensor(definition, mode="enum")
        assert entity._attr_translation_key == expected_key
        assert icons[expected_key]["default"] == expected_icon
        assert getattr(entity, "_attr_icon", None) is None


def test_battery_level_uses_home_assistant_battery_icon_pattern():
    """Let HA render the battery-level icon from its battery device class."""
    entity = _sensor(_BATTERY_DEFINITION, mode="battery_level")

    assert entity._attr_device_class == SensorDeviceClass.BATTERY
    assert entity._attr_translation_key == "battery_level"
    assert getattr(entity, "_attr_icon", None) is None
