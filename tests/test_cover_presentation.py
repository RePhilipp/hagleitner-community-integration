"""Tests for the Hagleitner cover-state entity presentation."""

from __future__ import annotations

from homeassistant.const import EntityCategory

from custom_components.hagleitner_community.binary_sensor import _binary_modes
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerSensor,
    _sensor_modes,
)

_COVER_DEFINITION = ResourceDefinition(
    name="Cover state",
    kind="opening",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    enum_values={0: "opened", 1: "closed"},
)


class _CoverHub:
    """Provide one cover-state reading to the entity."""

    def __init__(self, snapshot: ResourceValueSnapshot) -> None:
        self._snapshot = snapshot

    def value_for_resource(self, device_id: str, resource_key: str):
        return self._snapshot


def _cover_snapshot(mapped_value: str) -> ResourceValueSnapshot:
    """Build a cover-state resource reading."""
    return ResourceValueSnapshot(
        key="cover-resource",
        logged_at=None,
        resource_type_id=12289,
        instance_number=0,
        equivalent_id=None,
        raw_value=0 if mapped_value == "opened" else 1,
        mapped_value=mapped_value,
        raw_resource={},
        definition=_COVER_DEFINITION,
        device_type_names=frozenset(),
    )


def test_cover_state_shows_opened_and_closed_without_a_boolean_duplicate():
    """Expose the enum state only; it is not a security or binary sensor."""
    opened_snapshot = _cover_snapshot("opened")
    assert _sensor_modes(_COVER_DEFINITION, opened_snapshot) == (
        ("enum", "Cover state"),
    )
    assert _binary_modes(opened_snapshot) == ()

    opened_entity = HagleitnerSensor(
        _CoverHub(opened_snapshot),
        "device",
        opened_snapshot.key,
        _COVER_DEFINITION,
        frozenset(),
        "enum",
        "Cover state",
        None,
    )
    assert opened_entity.native_value == "opened"
    assert opened_entity.unique_id == "device_cover-resource_enum"
    assert opened_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert opened_entity.entity_registry_enabled_default is False

    closed_snapshot = _cover_snapshot("closed")
    closed_entity = HagleitnerSensor(
        _CoverHub(closed_snapshot),
        "device",
        closed_snapshot.key,
        _COVER_DEFINITION,
        frozenset(),
        "enum",
        "Cover state",
        None,
    )
    assert closed_entity.native_value == "closed"
