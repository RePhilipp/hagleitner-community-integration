"""Tests for removing consumable problem entities."""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.hagleitner_community.binary_sensor import (
    _binary_modes,
    async_setup_entry,
)
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.resource_data import (
    ResourceValueSnapshot,
    SUPPORTED_RESOURCES_BY_EQUIVALENT_ID,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

_REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
_FILL_STATUS_EQUIVALENT_ID = "9c336908-7a04-4adc-8bd7-08dc3d205c10"


def _snapshot(equivalent_id: str) -> ResourceValueSnapshot:
    """Build a supported consumable resource snapshot."""
    definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID[equivalent_id]
    return ResourceValueSnapshot(
        key="12290:0",
        logged_at=None,
        resource_type_id=12290,
        instance_number=0,
        equivalent_id=equivalent_id,
        raw_value=0,
        mapped_value="empty",
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


@pytest.mark.parametrize(
    "equivalent_id",
    [_REFILL_STATE_EQUIVALENT_ID, _FILL_STATUS_EQUIVALENT_ID],
)
def test_consumable_states_do_not_create_problem_entities(equivalent_id):
    """Refill/fill states do not produce problem binary sensors."""
    assert _binary_modes(_snapshot(equivalent_id)) == ()


async def test_setup_removes_existing_consumable_problem_entities(hass):
    """Old refill/fill problem entities are deleted while real issues remain."""
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
        f"{device_id}_12290:0_connection_problem",
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

    await async_setup_entry(hass, device_entry, lambda _entities: None)

    remaining = er.async_entries_for_config_entry(registry, device_entry.entry_id)
    assert [entity.unique_id for entity in remaining] == [
        f"{device_id}_12290:0_connection_problem"
    ]
