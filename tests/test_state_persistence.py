"""Tests for retaining Hagleitner entity values across Home Assistant restarts."""

from __future__ import annotations

import logging

from custom_components.hagleitner_community import async_setup
from custom_components.hagleitner_community.binary_sensor import (
    HagleitnerBinarySensor,
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
from pytest_homeassistant_custom_component.common import MockConfigEntry

_CONNECTION_STATUS_EQUIVALENT_ID = "7c178f1d-271f-4554-03ac-08dac1664f9a"
_BATTERY_STATUS_EQUIVALENT_ID = "77d144fd-d7a3-42f7-03aa-08dac1664f9a"


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
    hass.data[DOMAIN][hub_entry.entry_id] = hub
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
    hass.data[DOMAIN][hub_entry.entry_id] = restored_hub
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

    assert connection_sensor.native_value == "available"
    assert connection_sensor.available is True
    assert connection_sensor.extra_state_attributes == {
        "last_reading_at": "2026-11-03T17:00:00Z"
    }
    assert location_sensor.native_value == "Building 2 / EG / Room4"
    assert mains_adapter_sensor.is_on is True
    assert mains_adapter_sensor.available is True
