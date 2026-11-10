"""Tests for retaining Hagleitner entity values across Home Assistant restarts."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.hagleitner_community as integration
from homeassistant.config_entries import ConfigEntryState
from custom_components.hagleitner_community import async_setup
from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
)
from custom_components.hagleitner_community.binary_sensor import (
    async_setup_entry as async_setup_binary_entry,
)
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.coordinator import (
    HagleitnerHub,
    async_restore_persisted_state,
)
from custom_components.hagleitner_community.sensor import (
    HagleitnerMetadataSensor,
    HagleitnerSensor,
    async_setup_entry,
)

_CONNECTION_STATUS_EQUIVALENT_ID = "7c178f1d-271f-4554-03ac-08dac1664f9a"
_BATTERY_STATUS_EQUIVALENT_ID = "77d144fd-d7a3-42f7-03aa-08dac1664f9a"


async def test_config_entry_setup_initializes_persisted_state(hass, monkeypatch):
    """Load the state store through config-entry setup."""
    restore = AsyncMock(wraps=async_restore_persisted_state)
    monkeypatch.setattr(integration, "async_restore_persisted_state", restore)

    async def idle_receiver(*_args):
        await asyncio.sleep(0)

    monkeypatch.setattr(integration, "run_receiver", idle_receiver)
    monkeypatch.setattr(
        integration,
        "async_validate_queue",
        lambda *_args: asyncio.sleep(0),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "hub",
            "connection_string": "Endpoint=sb://example/",
            "queue_name": "queue",
        },
    )
    entry.add_to_hass(hass)

    assert await integration.async_setup_entry(hass, entry)
    assert isinstance(entry.runtime_data, HagleitnerHub)
    assert entry.entry_id not in hass.data[DOMAIN]
    restore.assert_awaited_once_with(hass)
    assert hass.data[DOMAIN]["_state_restored"] is True
    assert "_state_store" in hass.data[DOMAIN]["_shared_device_state"]


async def test_hub_runtime_data_is_cleared_and_recreated_on_reload(
    hass, monkeypatch
):
    """The queue entry owns a fresh hub object for each loaded lifetime."""

    async def idle_receiver(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(integration, "run_receiver", idle_receiver)
    monkeypatch.setattr(
        integration,
        "async_validate_queue",
        lambda *_args: asyncio.sleep(0),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "hub",
            "connection_string": "Endpoint=sb://example/",
            "queue_name": "queue",
        },
    )
    entry.add_to_hass(hass)

    assert await integration.async_setup_entry(hass, entry)
    first_hub = entry.runtime_data
    assert isinstance(first_hub, HagleitnerHub)
    await hass.async_block_till_done()

    assert await integration.async_unload_entry(hass, entry)
    assert entry.runtime_data is None

    assert await integration.async_setup_entry(hass, entry)
    second_hub = entry.runtime_data
    assert isinstance(second_hub, HagleitnerHub)
    assert second_hub is not first_hub

    assert await integration.async_unload_entry(hass, entry)


async def test_device_unload_clears_its_hub_reference(hass, monkeypatch):
    """An unloaded adopted entry no longer retains the loaded hub reference."""
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "device-1",
            "hub_entry_id": "hub-1",
        },
    )
    device_entry.add_to_hass(hass)

    class Hub:
        """Track adopted-device cleanup without constructing a queue receiver."""

        def __init__(self):
            self.unadopted_device = None

        def unadopt_device(self, device_id):
            self.unadopted_device = device_id

    hub = Hub()
    device_entry.runtime_data = hub
    unload_platforms = AsyncMock(return_value=True)
    monkeypatch.setattr(
        hass.config_entries,
        "async_unload_platforms",
        unload_platforms,
    )

    assert await integration.async_unload_entry(hass, device_entry)
    unload_platforms.assert_awaited_once_with(device_entry, integration.PLATFORMS)
    assert hub.unadopted_device == "device-1"
    assert device_entry.runtime_data is None


async def test_retained_device_switches_to_alternate_hub_runtime_data(
    hass,
    monkeypatch,
):
    """A still-loaded adopted device follows its alternate loaded hub."""
    hub = SimpleNamespace(device_sources={}, receiver_task=None)
    alternate_hub = object()
    hub_entry = SimpleNamespace(
        entry_id="hub-1",
        runtime_data=hub,
        data={"entry_type": "hub", "queue_name": "queue-1"},
    )
    alternate_entry = SimpleNamespace(
        entry_id="hub-2",
        runtime_data=alternate_hub,
        data={"entry_type": "hub", "queue_name": "queue-2"},
        state=ConfigEntryState.LOADED,
    )
    device_entry = SimpleNamespace(
        entry_id="device-1",
        runtime_data=hub,
        data={
            "entry_type": "device",
            "device_id": "device-1",
            "hub_entry_id": hub_entry.entry_id,
            "hub_entry_ids": [hub_entry.entry_id, alternate_entry.entry_id],
        },
        state=ConfigEntryState.LOADED,
    )
    entries = [hub_entry, alternate_entry, device_entry]
    entries_by_id = {entry.entry_id: entry for entry in entries}

    def update_entry(entry, *, data):
        entry.data = data

    hass.data[DOMAIN] = {}

    with monkeypatch.context() as config_entries_patch:
        config_entries_patch.setattr(
            hass.config_entries,
            "async_entries",
            lambda _domain=None: entries,
        )
        config_entries_patch.setattr(
            hass.config_entries,
            "async_get_entry",
            lambda entry_id: entries_by_id.get(entry_id),
        )
        config_entries_patch.setattr(
            hass.config_entries,
            "async_update_entry",
            update_entry,
        )
        assert await integration.async_unload_entry(hass, hub_entry)

    assert device_entry.data["hub_entry_id"] == alternate_entry.entry_id
    assert device_entry.runtime_data is alternate_hub
    assert hub_entry.runtime_data is None


async def test_last_known_resource_and_metadata_values_survive_restart(hass):
    """Recreate resource sensors from the last received values after restart."""
    await async_setup(hass, {})

    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue"},
    )
    hub_entry.add_to_hass(hass)
    device_id = "device-1"
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": device_id,
            "hub_entry_id": hub_entry.entry_id,
            "device_name": "Gateway",
        },
    )
    device_entry.add_to_hass(hass)

    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub_entry.runtime_data = hub
    device_entry.runtime_data = hub
    hub.adopt_device(device_id, device_entry.entry_id, "Gateway")
    await hub.async_handle_message(
        {
            "deviceInfo": {
                "deviceId": device_id,
                "deviceTypeId": "gateway-type",
                "deviceTypeNameTranslations": [
                    {"languageTag": "en", "value": "Gateway Longrange"}
                ],
            },
            "componentInfo": {"networkId": "gateway-component-network"},
            "gateway": {"networkId": "upstream-gateway-network"},
            "customerInfo": {"customerId": 123, "name1": "Example customer"},
            "locationInfo": {
                "locations": [
                    {"id": 1, "name": "Building 2"},
                    {"id": 2, "name": "EG"},
                    {"id": 3, "name": "Room4"},
                ],
                "mountPoint": "Wall",
            },
            "readings": [
                {
                    "loggedAt": "2026-11-03T17:00:00Z",
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 12290,
                                "resourceInstanceNo": 0,
                                "resourceInstanceEquivalentId": (
                                    _CONNECTION_STATUS_EQUIVALENT_ID
                                ),
                            },
                            "integerValue": 2,
                        },
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 12290,
                                "resourceInstanceNo": 1,
                                "resourceInstanceEquivalentId": (
                                    _BATTERY_STATUS_EQUIVALENT_ID
                                ),
                            },
                            "integerValue": 3,
                        },
                    ],
                }
            ],
        }
    )

    shared = hass.data[DOMAIN]["_shared_device_state"]
    store = shared["_state_store"]
    await store.async_save(hub._serialize_persisted_state())

    hass.data[DOMAIN] = {}
    await async_restore_persisted_state(hass)
    restored_hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    assert restored_hub.component_network_ids[device_id] == "gateway-component-network"
    assert restored_hub.gateway_network_ids[device_id] == "upstream-gateway-network"
    restored_hub.async_set_receiver_available(True)
    hub_entry.runtime_data = restored_hub
    device_entry.runtime_data = restored_hub
    restored_hub.adopt_device(device_id, device_entry.entry_id, "Gateway")

    entities = []
    await async_setup_entry(hass, device_entry, entities.extend)
    binary_entities = []
    await async_setup_binary_entry(hass, device_entry, binary_entities.extend)

    connection_sensor = next(
        entity
        for entity in entities
        if isinstance(entity, HagleitnerSensor) and entity._mode == "enum"
    )
    location_sensor = next(
        entity
        for entity in entities
        if isinstance(entity, HagleitnerMetadataSensor)
        and entity._metadata_key == "location"
    )
    mains_adapter_sensor = next(
        entity
        for entity in binary_entities
        if isinstance(entity, HagleitnerBinarySensor)
    )

    assert connection_sensor.native_value == "online"
    assert connection_sensor.available is True
    assert connection_sensor.extra_state_attributes == {
        "last_reading_at": "2026-11-03T17:00:00Z"
    }
    assert location_sensor.native_value == "Building 2 / EG / Room4"
    assert mains_adapter_sensor.is_on is True
    assert mains_adapter_sensor.available is True
