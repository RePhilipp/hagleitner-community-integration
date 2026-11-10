"""Focused checks for Gold device and entity lifecycle rules."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
    async_setup_entry as async_setup_binary_entry,
)
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    SUPPORTED_RESOURCES_BY_EQUIVALENT_ID,
    SUPPORTED_RESOURCES_BY_TYPE_INSTANCE,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerMetadataSensor,
    HagleitnerSensor,
    async_setup_entry as async_setup_sensor_entry,
)


class _Entry:
    """Provide the config-entry fields used by platform setup."""

    data = {"entry_type": "device", "device_id": "device-1"}
    entry_id = "entry-1"

    def async_on_unload(self, _callback) -> None:
        """Accept a platform cleanup callback."""


class _Registry:
    """Hold existing entity-registry entries for setup tests."""

    def __init__(self, entries=()) -> None:
        self.entries = list(entries)

    def async_update_entity(self, entity_id: str, *, disabled_by) -> None:
        for entry in self.entries:
            if entry.entity_id == entity_id:
                entry.disabled_by = disabled_by


class _ResourceHub:
    """Keep resource listeners and deliver later resource snapshots to them."""

    def __init__(self, resources: tuple[ResourceValueSnapshot, ...] = ()) -> None:
        self._resources = resources
        self._listeners = []

    def resources_for_device(self, _device_id: str):
        return self._resources

    def async_add_resource_listener(self, _device_id: str, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def publish(self, snapshot: ResourceValueSnapshot) -> None:
        for listener in tuple(self._listeners):
            listener(snapshot)


def _snapshot(
    key: str,
    definition: ResourceDefinition,
    mapped_value: str,
) -> ResourceValueSnapshot:
    """Build a resource value delivered by the queue hub."""
    return ResourceValueSnapshot(
        key=key,
        logged_at="2026-11-10T12:00:00Z",
        resource_type_id=1,
        instance_number=0,
        equivalent_id=None,
        raw_value=mapped_value,
        mapped_value=mapped_value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


def test_device_health_entities_are_diagnostic_but_usage_is_primary():
    """Classify device metadata as diagnostic without hiding usage values."""
    diagnostic_definitions = (
        SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
            "77d144fd-d7a3-42f7-03aa-08dac1664f9a"
        ],
        SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
            "9a77375d-964c-451f-03ab-08dac1664f9a"
        ],
        SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
            "7c178f1d-271f-4554-03ac-08dac1664f9a"
        ],
        SUPPORTED_RESOURCES_BY_TYPE_INSTANCE[(45058, 0)],
        SUPPORTED_RESOURCES_BY_TYPE_INSTANCE[(3, 0)],
        SUPPORTED_RESOURCES_BY_TYPE_INSTANCE[(12289, 0)],
    )
    assert all(
        definition.entity_category is EntityCategory.DIAGNOSTIC
        for definition in diagnostic_definitions
    )
    assert all(
        not definition.entity_registry_enabled_default
        for definition in (diagnostic_definitions[3], diagnostic_definitions[4])
    )
    assert (
        SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
            "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
        ].entity_category
        is None
    )

    error_definition = diagnostic_definitions[1]
    error_entity = HagleitnerBinarySensor(
        _ResourceHub(),
        "device-1",
        "error-resource",
        error_definition,
        "resource_problem",
        None,
    )
    assert error_entity.entity_category is EntityCategory.DIAGNOSTIC

    customer_id_sensor = HagleitnerMetadataSensor(
        _ResourceHub(), "device-1", "customer_id", None
    )
    assert not customer_id_sensor.entity_registry_enabled_default


@pytest.mark.asyncio
async def test_resource_entities_are_added_when_reported_after_platform_setup(
    monkeypatch,
):
    """Both entity platforms add supported resources without a reload."""
    entry = _Entry()
    hub = _ResourceHub()
    entry.runtime_data = hub
    registry = _Registry()
    monkeypatch.setattr(er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        lambda _registry, _entry_id: registry.entries,
    )
    hass = SimpleNamespace()
    sensors = []
    binary_sensors = []

    await async_setup_sensor_entry(hass, entry, sensors.extend)
    await async_setup_binary_entry(hass, entry, binary_sensors.extend)

    hub.publish(
        _snapshot(
            "new-counter",
            ResourceDefinition(
                name="Dispense count",
                kind="counter",
                entity_translation_key="dispense_count",
            ),
            "1",
        )
    )
    hub.publish(
        _snapshot(
            "new-error",
            ResourceDefinition(
                name="Device error",
                kind="enum",
                problem_entity_translation_key="device_error",
                enum_values={0: "ok", 1: "error"},
                problem_entity_on_values=("error",),
            ),
            "error",
        )
    )

    assert any(
        isinstance(entity, HagleitnerSensor)
        and entity._resource_key == "new-counter"
        for entity in sensors
    )
    assert any(
        isinstance(entity, HagleitnerBinarySensor)
        and entity._resource_key == "new-error"
        for entity in binary_sensors
    )


@pytest.mark.asyncio
async def test_default_disabled_entity_does_not_override_existing_user_choice(
    monkeypatch,
):
    """A previously enabled cover entity stays enabled after setup."""
    entry = _Entry()
    cover = _snapshot(
        "12289:0",
        ResourceDefinition(
            name="Cover state",
            kind="opening",
            entity_registry_enabled_default=False,
            enum_values={0: "opened", 1: "closed"},
        ),
        "opened",
    )
    hub = _ResourceHub((cover,))
    entry.runtime_data = hub
    registry_entry = SimpleNamespace(
        entity_id="sensor.device_1_cover_state",
        unique_id="device-1_12289:0_enum",
        domain="sensor",
        platform=DOMAIN,
        original_name="Cover state",
        disabled_by=None,
    )
    registry = _Registry((registry_entry,))
    monkeypatch.setattr(er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        lambda _registry, _entry_id: registry.entries,
    )
    hass = SimpleNamespace()
    assert registry_entry.disabled_by is None

    sensors = []
    await async_setup_sensor_entry(hass, entry, sensors.extend)

    assert registry_entry.disabled_by is None
    cover_entity = next(
        entity
        for entity in sensors
        if isinstance(entity, HagleitnerSensor)
        and entity._resource_key == "12289:0"
    )
    assert cover_entity.entity_registry_enabled_default is False
