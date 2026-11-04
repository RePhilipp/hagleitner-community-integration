"""Tests for HSM links on Hagleitner devices."""

from __future__ import annotations

import logging

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.helpers import device_registry as dr
import pytest

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.coordinator import HagleitnerHub
from custom_components.hagleitner_community.device import device_info
from custom_components.hagleitner_community.sensor import async_setup_entry
from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_device_info_links_to_hsm_device_locations():
    """Valid customer and device IDs produce the HSM device location URL."""
    info = device_info("device & 123", 456)

    assert info["identifiers"] == {(DOMAIN, "device & 123")}
    assert info.get("configuration_url") == (
        "https://hsm.hygieneportal.com/devices/locations"
        "?customerId=456&device=device+%26+123"
    )


def test_device_info_omits_link_when_device_id_is_invalid():
    """Do not create a customer-only URL if the device ID is unusable."""
    info = device_info("   ", 456)

    assert info.get("configuration_url") is None


@pytest.mark.parametrize("customer_id", [None, 0, -1, True, "456"])
def test_device_info_omits_link_for_invalid_customer_id(customer_id):
    """Invalid customer identifiers never result in a malformed HSM URL."""
    info = device_info("device-123", customer_id)

    assert info.get("configuration_url") is None


async def test_device_discovery_persists_valid_customer_id(
    hass,
    enable_custom_integrations,
):
    """The confirmed discovery entry retains its HSM customer ID."""
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={
            "hub_entry_id": "hub-entry",
            "device_id": "device-123",
            "device_type_id": "type-123",
            "device_name": "Dispenser",
            "customer_id": 456,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={},
    )

    assert result["type"] == "create_entry"
    device_entry = result["result"]
    assert device_entry.data["customer_id"] == 456

    class EmptyHub:
        """Represent a restarted hub before it receives a new message."""

        @staticmethod
        def resources_for_device(device_id):
            return ()

        @staticmethod
        def async_add_resource_listener(device_id, listener):
            return lambda: None

    hass.data.setdefault(DOMAIN, {})["hub-entry"] = EmptyHub()
    entities = []
    await async_setup_entry(hass, device_entry, entities.extend)

    assert entities
    expected_url = (
        "https://hsm.hygieneportal.com/devices/locations"
        "?customerId=456&device=device-123"
    )
    assert all(
        entity._attr_device_info.get("configuration_url") == expected_url
        for entity in entities
    )


@pytest.mark.parametrize("customer_id", [None, 0, -1, True, "456"])
async def test_device_discovery_does_not_persist_invalid_customer_id(
    hass,
    enable_custom_integrations,
    customer_id,
):
    """Invalid customer IDs are excluded instead of saved on device entries."""
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={
            "hub_entry_id": "hub-entry",
            "device_id": f"device-{customer_id}",
            "device_type_id": "type-123",
            "device_name": "Dispenser",
            "customer_id": customer_id,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={},
    )

    assert result["type"] == "create_entry"
    assert "customer_id" not in result["result"].data


async def test_existing_device_backfills_customer_id_and_registry_url(hass):
    """A later queue message upgrades an existing device's saved HSM link."""
    device_id = "123e4567-e89b-12d3-a456-426614174000"
    hass.data.setdefault(DOMAIN, {})
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub"},
    )
    hub_entry.add_to_hass(hass)
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "hub_entry_id": hub_entry.entry_id,
            "hub_entry_ids": [hub_entry.entry_id],
            "device_id": device_id,
        },
    )
    device_entry.add_to_hass(hass)

    registry = dr.async_get(hass)
    registered_device = registry.async_get_or_create(
        config_entry_id=device_entry.entry_id,
        identifiers={(DOMAIN, device_id)},
    )
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub.adopt_device(device_id, device_entry.entry_id, "Legacy device")

    await hub.async_handle_message(
        {
            "deviceInfo": {
                "deviceId": device_id,
                "deviceTypeId": "dispenser",
            },
            "customerInfo": {"customerId": 456},
        }
    )

    assert device_entry.data["customer_id"] == 456
    refreshed_device = next(
        iter(registry.async_get_devices(identifiers={(DOMAIN, device_id)})),
        None,
    )
    assert refreshed_device is not None
    assert refreshed_device.configuration_url == (
        "https://hsm.hygieneportal.com/devices/locations"
        f"?customerId=456&device={device_id}"
    )
    assert registered_device.configuration_url is None


async def test_existing_customer_id_is_not_overwritten_by_missing_metadata(hass):
    """Messages without a customer ID preserve stored IDs and device links."""
    device_id = "123e4567-e89b-12d3-a456-426614174001"
    hass.data.setdefault(DOMAIN, {})
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub"},
    )
    hub_entry.add_to_hass(hass)
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "hub_entry_id": hub_entry.entry_id,
            "hub_entry_ids": [hub_entry.entry_id],
            "device_id": device_id,
            "customer_id": 123,
        },
    )
    device_entry.add_to_hass(hass)

    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=device_entry.entry_id,
        identifiers={(DOMAIN, device_id)},
    )
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub.adopt_device(device_id, device_entry.entry_id, "Saved device")

    await hub.async_handle_message(
        {
            "deviceInfo": {
                "deviceId": device_id,
                "deviceTypeId": "dispenser",
            },
        }
    )

    assert device_entry.data["customer_id"] == 123
    registered_device = next(
        iter(registry.async_get_devices(identifiers={(DOMAIN, device_id)})),
        None,
    )
    assert registered_device is not None
    assert registered_device.configuration_url == (
        "https://hsm.hygieneportal.com/devices/locations"
        f"?customerId=123&device={device_id}"
    )
