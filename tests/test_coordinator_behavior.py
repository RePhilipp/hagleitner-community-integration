"""Tests for shared hub discovery, receiver state, and persisted data."""

from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.helpers import area_registry as ar, floor_registry as fr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community import coordinator
from custom_components.hagleitner_community.coordinator import (
    HagleitnerHub,
    async_restore_persisted_state,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    resource_value_snapshots,
    serialize_resource_snapshot,
)


def _supported_resource_snapshot():
    """Build a persistable firmware reading using the wire-format parser."""
    return resource_value_snapshots(
        {
            "deviceInfo": {"deviceId": "device-1"},
            "readings": [
                {
                    "loggedAt": "2026-11-10T12:00:00Z",
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 3,
                                "resourceInstanceNo": 0,
                            },
                            "stringValue": "1.2.3",
                        }
                    ],
                }
            ],
        }
    )[0]


async def test_restore_filters_invalid_persisted_resources_and_metadata(
    hass, monkeypatch
):
    """Only well-formed supported state is restored from the storage payload."""
    snapshot = _supported_resource_snapshot()
    serialized = serialize_resource_snapshot(snapshot)
    assert serialized is not None
    stored = {
        "devices": {
            "device-1": {
                "resources": {
                    snapshot.key: serialized,
                    "not-the-snapshot-key": serialized,
                    "unsupported": {"resource_type_id": 98765},
                    42: serialized,
                },
                "metadata": {
                    "customer_name": "Example customer",
                    "customer_id": True,
                    "location": "Building / Room",
                    "mount_point": 17,
                    "innermost_location": "Room",
                },
            },
            "empty-device": {
                "resources": [],
                "metadata": {"customer_id": False, "location": 123},
            },
            42: {"resources": {snapshot.key: serialized}},
        }
    }

    class FakeStore:
        def __init__(self, *_args, **_kwargs):
            self.load_count = 0

        async def async_load(self):
            self.load_count += 1
            return stored

    stores = []

    def make_store(*args, **kwargs):
        store = FakeStore(*args, **kwargs)
        stores.append(store)
        return store

    monkeypatch.setattr(coordinator, "Store", make_store)

    await async_restore_persisted_state(hass)
    await async_restore_persisted_state(hass)

    shared = hass.data[DOMAIN]["_shared_device_state"]
    assert set(shared["latest_values"]) == {"device-1"}
    restored_snapshot = shared["latest_values"]["device-1"][snapshot.key]
    assert restored_snapshot.raw_value == "1.2.3"
    assert restored_snapshot.logged_at == "2026-11-10T12:00:00Z"
    assert restored_snapshot.raw_resource == {}
    assert shared["device_metadata"]["device-1"].customer_name == "Example customer"
    assert shared["device_metadata"]["device-1"].customer_id is None
    assert shared["device_metadata"]["device-1"].location == "Building / Room"
    assert shared["device_metadata"]["device-1"].mount_point is None
    assert "empty-device" not in shared["device_metadata"]
    assert len(stores) == 1
    assert stores[0].load_count == 1


async def test_receiver_status_notifies_only_devices_reported_by_hub(hass):
    """Status transitions refresh a hub's adopted devices exactly once."""
    entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(hass, entry, logging.getLogger(__name__))
    hub.adopted_device_ids.update({"device-1", "device-2"})
    hub.device_sources["device-1"] = {entry.entry_id}
    hub.device_sources["device-2"] = {"another-hub"}
    notified = []
    hub.async_add_state_listener("device-1", lambda: notified.append("device-1"))
    hub.async_add_state_listener("device-2", lambda: notified.append("device-2"))

    hub.async_set_receiver_available(True)
    hub.async_set_receiver_available(True)
    hub.async_set_receiver_available(False)

    assert notified == ["device-1", "device-1"]
    assert hub.receiver_available is False


async def test_discovery_throttles_repeats_and_suggests_exact_hsm_room(
    hass, monkeypatch
):
    """Repeated messages respect the retry interval and retain useful area hints."""
    floor = fr.async_get(hass).async_create("EG", level=1)
    room = ar.async_get(hass).async_create("WC", floor_id=floor.floor_id)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(hass, entry, logging.getLogger(__name__))
    flow_init = AsyncMock(return_value={})
    monkeypatch.setattr(hass.config_entries.flow, "async_init", flow_init)
    times = iter((100.0, 150.0, 221.0))
    monkeypatch.setattr(
        coordinator,
        "time",
        SimpleNamespace(monotonic=lambda: next(times)),
    )
    message = {
        "deviceInfo": {
            "deviceId": "device-1",
            "deviceTypeId": "TYPE-1",
        },
        "customerInfo": {"customerId": 123, "name1": "Example"},
        "locationInfo": {
            "locations": [
                {"name": "Building 2"},
                {"name": "EG"},
                {"name": "WC"},
            ],
            "mountPoint": "Wall",
        },
    }

    await hub.async_handle_message(message)
    await hub.async_handle_message(message)
    await hub.async_handle_message(message)

    assert flow_init.await_count == 2
    discovery_data = flow_init.await_args_list[0].kwargs["data"]
    assert discovery_data == {
        "hub_entry_id": entry.entry_id,
        "device_id": "device-1",
        "device_type_id": "type-1",
        "device_name": "Hagleitner device-1 Wall",
        "customer_name": "Example",
        "location_name": "Building 2 / EG / WC",
        "mount_point": "Wall",
        "customer_id": 123,
        "suggested_area_id": room.id,
    }


async def test_adopted_device_ignores_stale_and_duplicate_readings(hass, monkeypatch):
    """Only a newer, changed supported reading reaches subscribed entities."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    hub_entry.add_to_hass(hass)
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "device-1",
            "hub_entry_id": hub_entry.entry_id,
        },
    )
    device_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    monkeypatch.setattr(hub, "_async_schedule_state_save", lambda: None)
    hub.adopt_device("device-1", device_entry.entry_id, "Dispenser")
    state_updates = []
    resource_updates = []
    hub.async_add_state_listener("device-1", lambda: state_updates.append(True))
    hub.async_add_resource_listener(
        "device-1", lambda snapshot: resource_updates.append(snapshot.raw_value)
    )

    def message(logged_at, count):
        return {
            "deviceInfo": {"deviceId": "device-1", "deviceTypeId": "dispenser"},
            "readings": [
                {
                    "loggedAt": logged_at,
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 20486,
                                "resourceInstanceNo": 0,
                            },
                            "integerValue": count,
                        }
                    ],
                }
            ],
        }

    await hub.async_handle_message(message("2026-11-10T12:00:00Z", 8))
    await hub.async_handle_message(message("2026-11-10T11:00:00Z", 7))
    await hub.async_handle_message(message("2026-11-10T12:00:00Z", 8))

    snapshot = hub.resources_for_device("device-1")[0]
    assert snapshot.raw_value == 8
    assert snapshot.logged_at == "2026-11-10T12:00:00Z"
    assert resource_updates == [8]
    assert state_updates == [True]


async def test_hub_reports_only_safe_firmware_and_cleans_up_unadopted_device(hass):
    """Firmware strings are allowlisted and unadoption removes device listeners."""
    entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(hass, entry, logging.getLogger(__name__))
    hub.adopt_device("device-1", "device-entry", "Dispenser")
    state_listener = lambda: None
    resource_listener = lambda _snapshot: None
    hub.async_add_state_listener("device-1", state_listener)
    hub.async_add_resource_listener("device-1", resource_listener)

    firmware = _supported_resource_snapshot()
    hub.latest_values["device-1"] = {firmware.key: firmware}
    assert hub.firmware_version_for_device("device-1") == "1.2.3"

    unrelated = replace(
        firmware,
        definition=ResourceDefinition(name="Unrelated", kind="counter"),
    )
    hub.latest_values["device-1"] = {unrelated.key: unrelated}
    assert hub.firmware_version_for_device("device-1") is None

    hub.unadopt_device("device-1")
    assert "device-1" not in hub.adopted_device_ids
    assert "device-1" not in hub.device_entry_ids
    assert "device-1" not in hub.device_names
    assert "device-1" not in hub._state_listeners
    assert "device-1" not in hub._resource_listeners

    firmware = replace(firmware, raw_value="not a safe version;")
    hub.latest_values["device-1"] = {firmware.key: firmware}
    assert hub.firmware_version_for_device("device-1") is None


def test_missing_hsm_location_never_suggests_an_area(hass):
    """Area suggestion helpers require a meaningful supplied location."""
    assert coordinator._suggest_area_from_hsm_location(
        hass, "device-1", None
    ) == (False, None)
    assert coordinator._suggest_existing_area_id(hass, None) is None
    assert coordinator._suggest_existing_area_id(hass, "  ") is None


async def test_hub_adopts_preconfigured_device_when_its_first_message_arrives(
    hass, monkeypatch
):
    """An existing device entry is linked rather than rediscovered on first data."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    hub_entry.add_to_hass(hass)
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "device-1",
            "hub_entry_id": hub_entry.entry_id,
        },
    )
    device_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    monkeypatch.setattr(hub, "_async_schedule_state_save", lambda: None)

    await hub.async_handle_message(
        {"deviceInfo": {"deviceId": "device-1", "deviceTypeId": "dispenser"}}
    )

    assert "device-1" in hub.adopted_device_ids
    assert hub.device_entry_ids["device-1"] == device_entry.entry_id
    assert device_entry.data["hub_entry_ids"] == [hub_entry.entry_id]


def test_empty_persisted_metadata_is_not_restored():
    """Empty stored metadata does not create a meaningless device record."""
    assert coordinator._restore_device_metadata({}) is None
    assert coordinator._restore_device_metadata(None) is None
