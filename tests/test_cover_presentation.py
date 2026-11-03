"""Tests for the Hagleitner cover-state entity presentation."""

from __future__ import annotations

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
    _binary_modes,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)

_COVER_DEFINITION = ResourceDefinition(
    name="Cover state",
    kind="opening",
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


def test_cover_state_keeps_automation_state_without_security_class():
    """The lid remains usable as a binary sensor, but not a security opening."""
    snapshot = _cover_snapshot("opened")
    entity = HagleitnerBinarySensor(
        _CoverHub(snapshot),
        "device",
        snapshot.key,
        _COVER_DEFINITION,
        "opening",
        None,
    )

    assert _binary_modes(snapshot) == ("opening",)
    assert entity.is_on is True
    assert getattr(entity, "_attr_device_class", None) is None
    assert entity.name == "Cover state"
    assert entity.unique_id == "device_cover-resource_opening"

    closed_entity = HagleitnerBinarySensor(
        _CoverHub(_cover_snapshot("closed")),
        "device",
        snapshot.key,
        _COVER_DEFINITION,
        "opening",
        None,
    )
    assert closed_entity.is_on is False
