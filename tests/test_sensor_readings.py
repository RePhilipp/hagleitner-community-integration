"""Tests for resource and metadata sensor value semantics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.helpers import entity_registry as er

from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerMetadataSensor,
    HagleitnerSensor,
    _sensor_modes,
    async_setup_entry,
)


def _snapshot(
    definition: ResourceDefinition,
    *,
    raw_value: object = 7,
    mapped_value: object = 7,
    logged_at: object = "2026-03-04T05:06:07Z",
) -> ResourceValueSnapshot:
    """Build a resource reading for sensor tests."""
    return ResourceValueSnapshot(
        key="resource-key",
        logged_at=logged_at,
        resource_type_id=1,
        instance_number=0,
        equivalent_id=None,
        raw_value=raw_value,
        mapped_value=mapped_value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


class _Hub:
    """Expose mutable values and availability to standalone entity tests."""

    receiver_available = True

    def __init__(self, snapshot: ResourceValueSnapshot | None = None):
        self.snapshot = snapshot
        self.offline = False
        self.metadata = SimpleNamespace(location="Building / Room")

    def value_for_resource(self, _device_id, _resource_key):
        return self.snapshot

    def device_is_offline(self, _device_id):
        return self.offline

    def metadata_for_device(self, _device_id):
        return self.metadata

    def resources_for_device(self, _device_id):
        return [self.snapshot] if self.snapshot is not None else []

    def async_add_resource_listener(self, _device_id, callback):
        self.resource_callback = callback
        return lambda: None


@pytest.mark.parametrize(
    ("kind", "mapped_value", "expected_modes"),
    [
        ("measurement", 1.5, ("measurement",)),
        ("diagnostic", "1.2.3", ("diagnostic",)),
        ("connection", "online", ("enum",)),
        ("unknown", "value", ()),
        ("battery", "mains_adapter", ()),
    ],
)
def test_resource_kinds_select_only_their_supported_sensor_modes(
    kind, mapped_value, expected_modes
):
    """Resource kinds map to the appropriate entity and no duplicate battery enum."""
    definition = ResourceDefinition(
        name="Resource",
        kind=kind,
        enum_values={0: "online"},
    )
    assert _sensor_modes(
        definition,
        _snapshot(definition, mapped_value=mapped_value),
    ) == expected_modes


def test_enum_and_numeric_sensors_reject_missing_or_invalid_latest_values():
    """Sensor states use normalized enum values and preserve numeric readings."""
    hub = _Hub()
    enum_definition = ResourceDefinition(
        name="Connection",
        kind="enum",
        enum_values={0: "online", 1: "offline"},
    )
    enum_sensor = HagleitnerSensor(
        hub,
        "device-1",
        "resource-key",
        enum_definition,
        frozenset(),
        "enum",
        None,
    )
    assert enum_sensor.native_value is None
    hub.snapshot = _snapshot(enum_definition, raw_value=0, mapped_value="online")
    assert enum_sensor.native_value == "online"
    assert enum_sensor.extra_state_attributes == {
        "last_reading_at": "2026-03-04T05:06:07Z"
    }
    hub.snapshot = None
    assert enum_sensor.extra_state_attributes is None
    hub.snapshot = _snapshot(enum_definition, raw_value=9, mapped_value="unknown")
    assert enum_sensor.native_value is None
    hub.snapshot = _snapshot(enum_definition, logged_at="unknown")
    assert enum_sensor.extra_state_attributes is None

    counter_definition = ResourceDefinition(name="Count", kind="counter")
    counter_sensor = HagleitnerSensor(
        hub,
        "device-1",
        "resource-key",
        counter_definition,
        frozenset(),
        "counter",
        None,
    )
    hub.snapshot = _snapshot(counter_definition, raw_value=42, mapped_value=42)
    assert counter_sensor.native_value == 42

    unsupported_sensor = HagleitnerSensor(
        hub,
        "device-1",
        "resource-key",
        counter_definition,
        frozenset(),
        "unsupported",
        None,
    )
    assert unsupported_sensor.native_value is None


def test_data_link_expectation_enum_exposes_all_classification_values():
    """The catalog-less enum exposes numeric classes with display labels."""
    definition = ResourceDefinition(
        name="Data-link expectation",
        kind="enum",
        entity_translation_key="data_link_expectation",
        enum_values={
            0: "hard_offline",
            1: "soft_offline",
            2: "online",
        },
    )
    hub = _Hub(_snapshot(definition, raw_value=2, mapped_value="online"))
    sensor = HagleitnerSensor(
        hub,
        "device-1",
        "45060:0",
        definition,
        frozenset(),
        "enum",
        None,
    )

    assert sensor._attr_options == [
        "hard_offline",
        "soft_offline",
        "online",
    ]
    assert sensor.native_value == "online"


@pytest.mark.parametrize(
    ("kind", "device_class", "unit", "mode", "expected_unit"),
    [
        ("counter", "volume", "milliliters", "counter", UnitOfVolume.MILLILITERS),
        ("counter", "volume", "liters", "counter", UnitOfVolume.LITERS),
        ("measurement", None, "percentage", "measurement", PERCENTAGE),
    ],
)
def test_sensor_constructor_applies_configured_measurement_units(
    kind, device_class, unit, mode, expected_unit
):
    """Catalog volume and percentage resources use consistent HA metadata."""
    definition = ResourceDefinition(
        name="Measurement",
        kind=kind,
        device_class=device_class,
        unit=unit,
    )
    entity = HagleitnerSensor(
        _Hub(_snapshot(definition)),
        "device-1",
        "resource-key",
        definition,
        frozenset(),
        mode,
        None,
    )

    if device_class == "volume":
        assert entity._attr_device_class is SensorDeviceClass.VOLUME
    assert entity._attr_native_unit_of_measurement == expected_unit
    assert entity._attr_state_class is (
        SensorStateClass.TOTAL_INCREASING
        if mode == "counter"
        else SensorStateClass.MEASUREMENT
    )


@pytest.mark.parametrize(
    ("device_class", "unit", "expected_class", "expected_unit"),
    [
        (None, "milliseconds", None, UnitOfTime.MILLISECONDS),
        (
            "signal_strength",
            "dBm",
            SensorDeviceClass.SIGNAL_STRENGTH,
            SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ],
)
def test_sensor_constructor_applies_duration_and_rssi_metadata(
    device_class, unit, expected_class, expected_unit
):
    """Durations use milliseconds and signed radio RSSI uses dBm metadata."""
    definition = ResourceDefinition(
        name="Measurement",
        kind="measurement",
        device_class=device_class,
        unit=unit,
    )
    entity = HagleitnerSensor(
        _Hub(_snapshot(definition)),
        "device-1",
        "resource-key",
        definition,
        frozenset(),
        "measurement",
        None,
    )

    assert getattr(entity, "_attr_device_class", None) is expected_class
    assert entity._attr_native_unit_of_measurement == expected_unit
    assert entity._attr_state_class is SensorStateClass.MEASUREMENT


def test_diagnostic_interval_keeps_seconds_without_measurement_state_class():
    """Diagnostic-only intervals retain their unit but do not imply a metric."""
    definition = ResourceDefinition(
        name="Heartbeat interval",
        kind="diagnostic",
        entity_category=EntityCategory.DIAGNOSTIC,
        unit="seconds",
    )
    entity = HagleitnerSensor(
        _Hub(_snapshot(definition)),
        "device-1",
        "36866:0",
        definition,
        frozenset(),
        "diagnostic",
        None,
    )

    assert entity._attr_native_unit_of_measurement == UnitOfTime.SECONDS
    assert getattr(entity, "_attr_state_class", None) is None


def test_diagnostic_resource_is_always_a_diagnostic_entity():
    """Diagnostic resources remain categorized even without a catalog category."""
    definition = ResourceDefinition(name="Diagnostic", kind="diagnostic")
    entity = HagleitnerSensor(
        _Hub(_snapshot(definition)),
        "device-1",
        "resource-key",
        definition,
        frozenset(),
        "diagnostic",
        None,
    )

    assert entity._attr_entity_category is EntityCategory.DIAGNOSTIC


def test_metadata_sensor_reads_location_and_tracks_device_availability():
    """Metadata values follow the same offline and listener-backed lifecycle."""
    hub = _Hub()
    sensor = HagleitnerMetadataSensor(hub, "device-1", "location", None)

    assert sensor.native_value == "Building / Room"
    assert sensor.available is True
    hub.offline = True
    assert sensor.available is False
    hub.offline = False
    hub.receiver_available = False
    assert sensor.available is False


async def test_sensor_setup_skips_unknown_and_deduplicates_resources(
    hass, monkeypatch
):
    """Existing and later readings create one resource sensor plus metadata."""
    definition = ResourceDefinition(name="Count", kind="counter")
    snapshot = _snapshot(definition)
    hub = _Hub(snapshot)
    hub.resources_for_device = lambda _device_id: [
        _snapshot(None),
        snapshot,
        snapshot,
    ]
    entry = SimpleNamespace(
        entry_id="device-entry",
        data={"device_id": "device-1"},
        runtime_data=hub,
        async_on_unload=lambda _unsubscribe: None,
    )
    monkeypatch.setattr(er, "async_get", lambda _hass: object())
    monkeypatch.setattr(er, "async_entries_for_config_entry", lambda *_args: [])
    entities = []

    await async_setup_entry(hass, entry, entities.extend)

    resource_entities = [
        entity for entity in entities if isinstance(entity, HagleitnerSensor)
    ]
    metadata_entities = [
        entity for entity in entities if isinstance(entity, HagleitnerMetadataSensor)
    ]
    assert len(resource_entities) == 1
    assert len(metadata_entities) == 4
    assert hub.resource_callback is not None
    hub.resource_callback(snapshot)
    assert sum(
        isinstance(entity, HagleitnerSensor) for entity in entities
    ) == 1
