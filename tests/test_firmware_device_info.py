"""Tests for publishing reported firmware in Home Assistant device info."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.coordinator import HagleitnerHub


async def test_reported_firmware_updates_device_registry(hass, monkeypatch):
    """A firmware resource updates sw_version for an adopted device."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    hub_entry.add_to_hass(hass)
    device_id = "device-1"
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": device_id,
            "hub_entry_id": hub_entry.entry_id,
            "hub_entry_ids": [hub_entry.entry_id],
        },
    )
    device_entry.add_to_hass(hass)

    class DeviceRegistry:
        """Record firmware updates to an existing device."""

        def __init__(self):
            self.device = SimpleNamespace(id="registry-device", sw_version=None)
            self.update = None

        def async_get_devices(self, *, identifiers):
            assert identifiers == {(DOMAIN, device_id)}
            return [self.device]

        def async_update_device(self, device_id, **kwargs):
            self.update = (device_id, kwargs)
            self.device.sw_version = kwargs.get("sw_version")

    registry = DeviceRegistry()
    monkeypatch.setattr(dr, "async_get", lambda _hass: registry)
    hass.data[DOMAIN] = {}
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub.adopt_device(device_id, device_entry.entry_id, "Dispenser")

    await hub.async_handle_message(
        {
            "deviceInfo": {
                "deviceId": device_id,
                "deviceTypeId": "dispenser",
            },
            "readings": [
                {
                    "loggedAt": "2026-11-10T12:00:00Z",
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 3,
                                "resourceInstanceNo": 0,
                            },
                            "stringValue": "1.2.3+build_4",
                        }
                    ],
                }
            ],
        }
    )

    assert registry.update == (
        "registry-device",
        {"sw_version": "1.2.3+build_4"},
    )
