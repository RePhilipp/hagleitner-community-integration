"""Tests for removing consumable problem entities."""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
    _binary_modes,
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
    async_setup_entry as async_setup_sensor_entry,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

_REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
_FILL_STATUS_EQUIVALENT_ID = "9c336908-7a04-4adc-8bd7-08dc3d205c10"


def _snapshot(equivalent_id: str) -> ResourceValueSnapshot:
    """Build a supported consumable resource snapshot."""
    definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[equivalent_id]
    return _resource_snapshot(definition, equivalent_id, "empty")


def _resource_snapshot(
    definition: ResourceDefinition,
    equivalent_id: str | None,
    mapped_value: str,
) -> ResourceValueSnapshot:
    """Build a resource snapshot for entity-mode tests."""
    return ResourceValueSnapshot(
        key="12293:0" if equivalent_id == _FILL_STATUS_EQUIVALENT_ID else "12290:0",
        logged_at=None,
        resource_type_id=12293 if equivalent_id == _FILL_STATUS_EQUIVALENT_ID else 12290,
        instance_number=0,
        equivalent_id=equivalent_id,
        raw_value=0,
        mapped_value=mapped_value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


@pytest.mark.parametrize(
    "equivalent_id",
    [_REFILL_STATE_EQUIVALENT_ID, _FILL_STATUS_EQUIVALENT_ID],
)
def test_consumable_states_do_not_create_problem_entities(equivalent_id):
    """Consumable enums each derive one problem binary sensor for Maintenance."""
    modes = _binary_modes(_snapshot(equivalent_id))
    assert modes == ("refill_empty",)


def test_fill_status_resource_is_a_mapped_enum_sensor():
    """Expose fill level as an enum sensor with catalog-correct values."""
    definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[_FILL_STATUS_EQUIVALENT_ID]
    assert definition.kind == "enum"
    assert definition.enum_values == {
        0: "full",
        1: "nearly_full",
        2: "empty",
    }


@pytest.mark.parametrize(
    ("equivalent_id", "mapped_value", "expected"),
    [
        (_REFILL_STATE_EQUIVALENT_ID, "full", False),
        (_REFILL_STATE_EQUIVALENT_ID, "low", True),
        (_REFILL_STATE_EQUIVALENT_ID, "empty", True),
        (_FILL_STATUS_EQUIVALENT_ID, "full", False),
        (_FILL_STATUS_EQUIVALENT_ID, "nearly_full", True),
        (_FILL_STATUS_EQUIVALENT_ID, "empty", True),
    ],
)
def test_refill_problem_state_matches_catalog_warning_values(
    equivalent_id, mapped_value, expected
):
    """Set the Maintenance problem state from each enum's warning values."""
    snapshot = _resource_snapshot(
        SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[equivalent_id],
        equivalent_id,
        mapped_value,
    )

    class SnapshotHub:
        """Return the provided snapshot to the entity."""

        @staticmethod
        def value_for_resource(_device_id, _resource_key):
            return snapshot

    entity = HagleitnerBinarySensor(
        SnapshotHub(),
        "device-1",
        snapshot.key,
        snapshot.definition,
        "refill_empty",
        None,
    )

    assert entity.device_class == "problem"
    assert entity.is_on is expected
    assert entity.entity_registry_visible_default is True


def test_only_unique_conditions_create_binary_entities():
    """Status values already represented by sensors or Repairs stay single."""
    battery_definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
        "77d144fd-d7a3-42f7-03aa-08dac1664f9a"
    ]
    connection_definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
        "7c178f1d-271f-4554-03ac-08dac1664f9a"
    ]
    error_definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[
        "9a77375d-964c-451f-03ab-08dac1664f9a"
    ]
    cover_definition = SUPPORTED_RESOURCES_BY_TYPE_INSTANCE[(12289, 0)]
    maintenance_definition = SUPPORTED_RESOURCES_BY_TYPE_INSTANCE[(12307, 0)]

    for snapshot in (
        _resource_snapshot(battery_definition, None, "low"),
        _resource_snapshot(connection_definition, None, "offline"),
        _resource_snapshot(error_definition, None, "error"),
        _resource_snapshot(cover_definition, None, "opened"),
        _resource_snapshot(maintenance_definition, None, "change_required"),
        _resource_snapshot(
            ResourceDefinition(name="Refill inserted", kind="presence"),
            None,
            "inserted",
        ),
    ):
        assert _binary_modes(snapshot) == ()

    assert (12294, 0) not in SUPPORTED_RESOURCES_BY_TYPE_INSTANCE


async def test_setup_removes_existing_consumable_problem_entities(hass):
    """Old duplicate binary entities are removed while distinct states remain."""
    hub_entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hub_entry.add_to_hass(hass)
    device_id = "device-1"
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "hub_entry_id": hub_entry.entry_id,
            "device_id": device_id,
        },
    )
    device_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    unique_ids = (
        f"{device_id}_12290:0_refill_problem",
        f"{device_id}_12290:0_fill_problem",
        f"{device_id}_12290:0_battery",
        f"{device_id}_12290:0_connectivity",
        f"{device_id}_12290:0_connection_problem",
        f"{device_id}_12289:0_opening",
        f"{device_id}_12307:0_problem",
        f"{device_id}_12307:0_maintenance_required",
        f"{device_id}_12294:0_refill_inserted",
        f"{device_id}_battery-resource_mains_adapter",
    )
    for unique_id in unique_ids:
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            unique_id,
            config_entry=device_entry,
        )

    class EmptyHub:
        """Provide no resources while supporting platform setup."""

        @staticmethod
        def resources_for_device(_device_id):
            return ()

        @staticmethod
        def async_add_resource_listener(_device_id, _listener):
            return lambda: None

    hass.data[DOMAIN] = {hub_entry.entry_id: EmptyHub()}

    await async_setup_binary_entry(hass, device_entry, lambda _entities: None)

    remaining = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(registry, device_entry.entry_id)
        if entity.domain == "binary_sensor"
    }
    assert remaining == {f"{device_id}_battery-resource_mains_adapter"}


async def test_setup_removes_obsolete_battery_status_sensor(hass):
    """Remove the duplicate battery enum but keep other enum resources."""
    hub_entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hub_entry.add_to_hass(hass)
    device_id = "device-1"
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "hub_entry_id": hub_entry.entry_id,
            "device_id": device_id,
        },
    )
    device_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    for unique_id, original_name in (
        (f"{device_id}_1:0_enum", "Energy supply status"),
        (f"{device_id}_12290:0_enum", "Refill state"),
    ):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            unique_id,
            config_entry=device_entry,
            original_name=original_name,
        )

    class EmptyHub:
        """Provide no resources while supporting platform setup."""

        @staticmethod
        def resources_for_device(_device_id):
            return ()

        @staticmethod
        def async_add_resource_listener(_device_id, _listener):
            return lambda: None

    hass.data[DOMAIN] = {hub_entry.entry_id: EmptyHub()}

    await async_setup_sensor_entry(hass, device_entry, lambda _entities: None)

    remaining = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(registry, device_entry.entry_id)
        if entity.domain == "sensor"
    }
    assert remaining == {f"{device_id}_12290:0_enum"}
