"""Tests for derived binary sensor states and resource listener setup."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
    async_setup_entry,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)


def _snapshot(
    definition: ResourceDefinition | None,
    mapped_value: object,
    *,
    logged_at: object = "2026-03-04T05:06:07Z",
    key: str = "resource-key",
) -> ResourceValueSnapshot:
    """Build a resource reading for binary sensor tests."""
    return ResourceValueSnapshot(
        key=key,
        logged_at=logged_at,
        resource_type_id=1,
        instance_number=0,
        equivalent_id=None,
        raw_value=mapped_value,
        mapped_value=mapped_value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


class _Hub:
    """Provide current resource readings and availability for an entity."""

    receiver_available = True

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.offline = False
        self.resource_callback = None

    def value_for_resource(self, _device_id, _resource_key):
        return self.snapshot

    def device_is_offline(self, _device_id):
        return self.offline

    def resources_for_device(self, _device_id):
        return [self.snapshot]

    def async_add_resource_listener(self, _device_id, callback):
        self.resource_callback = callback
        return lambda: None


def test_problem_sensor_maps_known_states_and_hides_unknown_values():
    """A problem sensor is on only for declared problem states."""
    definition = ResourceDefinition(
        name="Error status",
        kind="problem",
        enum_values={0: "no_error", 1: "error"},
        problem_entity_on_values=("error",),
    )
    hub = _Hub(_snapshot(definition, "error"))
    entity = HagleitnerBinarySensor(
        hub, "device-1", "resource-key", definition, "resource_problem", None
    )

    assert entity.is_on is True
    assert entity.unique_id == "device-1_resource-key_resource_problem"
    assert entity.extra_state_attributes == {
        "last_reading_at": "2026-03-04T05:06:07Z"
    }
    hub.snapshot = _snapshot(definition, "no_error")
    assert entity.is_on is False
    hub.snapshot = _snapshot(definition, "unrecognized")
    assert entity.is_on is None
    hub.snapshot = None
    assert entity.is_on is None
    assert entity.extra_state_attributes is None


def test_binary_sensor_availability_requires_receiver_and_online_device():
    """Derived device conditions are unavailable during queue/device outages."""
    definition = ResourceDefinition(
        name="Error status",
        kind="problem",
        enum_values={0: "no_error"},
        problem_entity_on_values=("error",),
    )
    hub = _Hub(_snapshot(definition, "no_error"))
    entity = HagleitnerBinarySensor(
        hub, "device-1", "resource-key", definition, "resource_problem", None
    )

    assert entity.available is True
    hub.offline = True
    assert entity.available is False
    hub.offline = False
    hub.receiver_available = False
    assert entity.available is False


async def test_binary_setup_skips_unknown_and_deduplicates_live_resource_updates():
    """Initial and listener-delivered snapshots create only one entity per key."""
    definition = ResourceDefinition(
        name="Error status",
        kind="problem",
        enum_values={0: "no_error", 1: "error"},
        problem_entity_on_values=("error",),
    )
    snapshot = _snapshot(definition, "error")
    hub = _Hub(snapshot)
    entry = SimpleNamespace(
        data={"device_id": "device-1"},
        runtime_data=hub,
        async_on_unload=lambda _unsubscribe: None,
    )
    entities = []

    await async_setup_entry(None, entry, entities.extend)
    assert len(entities) == 1
    assert hub.resource_callback is not None
    hub.resource_callback(snapshot)
    hub.resource_callback(_snapshot(None, "not-supported", key="other-key"))
    assert len(entities) == 1
    assert isinstance(entities[0], HagleitnerBinarySensor)


async def test_binary_setup_waits_until_device_hub_is_available():
    """Platform setup reports a retryable error when runtime data is absent."""
    entry = SimpleNamespace(data={"device_id": "device-1"}, runtime_data=None)

    with pytest.raises(ConfigEntryNotReady) as raised:
        await async_setup_entry(None, entry, lambda _entities: None)

    assert raised.value.translation_key == "waiting_for_queue_connection"


def test_mains_adapter_indicator_distinguishes_known_and_unknown_power_states():
    """The plug indicator is off only for recognized battery power states."""
    definition = ResourceDefinition(
        name="Energy supply",
        kind="battery",
        enum_values={0: "ok", 1: "low", 3: "mains_adapter"},
    )
    hub = _Hub(_snapshot(definition, "mains_adapter"))
    entity = HagleitnerBinarySensor(
        hub, "device-1", "resource-key", definition, "mains_adapter", None
    )

    assert entity.is_on is True
    hub.snapshot = _snapshot(definition, "low")
    assert entity.is_on is False
    hub.snapshot = _snapshot(definition, "unknown")
    assert entity.is_on is None

    unsupported_mode = HagleitnerBinarySensor(
        hub, "device-1", "resource-key", definition, "unsupported", None
    )
    assert unsupported_mode.is_on is None
