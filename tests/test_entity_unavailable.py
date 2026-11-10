"""Tests for availability based on the exact device connection status."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
)
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.coordinator import HagleitnerHub
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerMetadataSensor,
    HagleitnerSensor,
)


def _connection_snapshot(status: str) -> ResourceValueSnapshot:
    """Build a device connection-status reading."""
    return ResourceValueSnapshot(
        key="connection-status",
        logged_at="2026-01-01T00:00:00Z",
        resource_type_id=12290,
        instance_number=0,
        equivalent_id="connection-status",
        raw_value=status,
        mapped_value=status,
        raw_resource={},
        definition=ResourceDefinition(
            name="Connection status",
            kind="connection",
            enum_values={
                0: "offline",
                1: "temporarily_offline",
                2: "online",
                3: "not_connected",
            },
        ),
        device_type_names=frozenset(),
    )


def test_device_is_offline_only_for_exact_offline_status(hass):
    """Temporary offline and other connection states are not exact offline."""
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(
        hass,
        SimpleNamespace(entry_id="hub-1"),
        logging.getLogger(__name__),
    )

    for status in ("offline", "temporarily_offline", "online", "not_connected"):
        hub.latest_values["device-1"] = {
            "connection-status": _connection_snapshot(status)
        }
        assert hub.device_is_offline("device-1") is (status == "offline")


def test_only_non_connection_entities_are_unavailable_for_exact_offline(hass):
    """Keep the status sensor available while hiding the device's other values."""
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(
        hass,
        SimpleNamespace(entry_id="hub-1"),
        logging.getLogger(__name__),
    )
    hub.receiver_available = True
    hub.latest_values["device-1"] = {
        "connection-status": _connection_snapshot("offline")
    }
    counter_definition = ResourceDefinition(name="Dispense count", kind="counter")
    connection_definition = _connection_snapshot("offline").definition
    assert connection_definition is not None
    problem_definition = ResourceDefinition(
        name="Device error",
        kind="problem",
        enum_values={0: "ok", 1: "error"},
        problem_entity_on_values=("error",),
        problem_entity_name="Device error",
    )

    value_sensor = HagleitnerSensor(
        hub,
        "device-1",
        "counter",
        counter_definition,
        frozenset(),
        "counter",
        "Dispense count",
        None,
    )
    connection_sensor = HagleitnerSensor(
        hub,
        "device-1",
        "connection-status",
        connection_definition,
        frozenset(),
        "enum",
        "Connection status",
        None,
    )
    metadata_sensor = HagleitnerMetadataSensor(
        hub,
        "device-1",
        "customer_name",
        None,
    )
    problem_sensor = HagleitnerBinarySensor(
        hub,
        "device-1",
        "problem",
        problem_definition,
        "resource_problem",
        None,
    )

    assert not value_sensor.available
    assert connection_sensor.available
    assert not metadata_sensor.available
    assert not problem_sensor.available

    hub.latest_values["device-1"]["connection-status"] = _connection_snapshot(
        "temporarily_offline"
    )
    assert value_sensor.available
    assert connection_sensor.available
    assert metadata_sensor.available
    assert problem_sensor.available
