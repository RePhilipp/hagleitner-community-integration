"""Tests for linking Hagleitner devices through reported gateway network IDs."""

from __future__ import annotations

import logging

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.coordinator import HagleitnerHub


def _message(device_id: str, *, component_network_id=None, gateway_network_id=None):
    message = {
        "deviceInfo": {"deviceId": device_id, "deviceTypeId": "dispenser"},
    }
    if component_network_id is not None:
        message["componentInfo"] = {"networkId": component_network_id}
    if gateway_network_id is not None:
        message["gateway"] = {"networkId": gateway_network_id}
    return message


def _add_device(hass, registry, hub_entry, device_id: str):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": device_id,
            "hub_entry_id": hub_entry.entry_id,
            "hub_entry_ids": [hub_entry.entry_id],
        },
    )
    entry.add_to_hass(hass)
    registered_device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=device_id,
    )
    return entry, registered_device


async def test_gateway_network_id_links_to_matching_registered_device(hass):
    """The network ID resolves to another device's HA registry ID."""
    hass.data[DOMAIN] = {}
    hub_entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hub_entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    gateway_entry, gateway_device = _add_device(
        hass, registry, hub_entry, "gateway-device"
    )
    dispenser_entry, dispenser_device = _add_device(
        hass, registry, hub_entry, "dispenser-device"
    )
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub.adopt_device("gateway-device", gateway_entry.entry_id, "Gateway")
    hub.adopt_device("dispenser-device", dispenser_entry.entry_id, "Dispenser")

    await hub.async_handle_message(
        _message("gateway-device", component_network_id="GW-NETWORK")
    )
    await hub.async_handle_message(
        _message(
            "dispenser-device",
            component_network_id="dispenser-network",
            gateway_network_id="gw-network",
        )
    )

    updated_dispenser = registry.async_get(dispenser_device.id)
    assert updated_dispenser is not None
    assert updated_dispenser.via_device_id == gateway_device.id
    assert updated_dispenser.via_device_id != "gw-network"


async def test_gateway_link_waits_for_matching_device_and_updates_on_change(hass):
    """An unmatched gateway clears an old link, then links when adopted/registered."""
    hass.data[DOMAIN] = {}
    hub_entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hub_entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    original_gateway_entry, original_gateway = _add_device(
        hass, registry, hub_entry, "gateway-1"
    )
    dispenser_entry, dispenser = _add_device(hass, registry, hub_entry, "dispenser")
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub.adopt_device("gateway-1", original_gateway_entry.entry_id, "Gateway 1")
    hub.adopt_device("dispenser", dispenser_entry.entry_id, "Dispenser")

    await hub.async_handle_message(
        _message("gateway-1", component_network_id="network-one")
    )
    await hub.async_handle_message(
        _message("dispenser", gateway_network_id="network-one")
    )
    assert registry.async_get(dispenser.id).via_device_id == original_gateway.id

    await hub.async_handle_message(
        _message("dispenser", gateway_network_id="network-two")
    )
    assert registry.async_get(dispenser.id).via_device_id is None

    new_gateway_entry, new_gateway = _add_device(hass, registry, hub_entry, "gateway-2")
    hub.adopt_device("gateway-2", new_gateway_entry.entry_id, "Gateway 2")
    await hub.async_handle_message(
        _message("gateway-2", component_network_id="network-two")
    )
    assert registry.async_get(dispenser.id).via_device_id == new_gateway.id


async def test_explicitly_missing_gateway_clears_previous_link(hass):
    """A null Gateway record removes the previous integration-managed link."""
    hass.data[DOMAIN] = {}
    hub_entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hub_entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    gateway_entry, gateway = _add_device(hass, registry, hub_entry, "gateway")
    dispenser_entry, dispenser = _add_device(hass, registry, hub_entry, "dispenser")
    hub = HagleitnerHub(hass, hub_entry, logging.getLogger(__name__))
    hub.adopt_device("gateway", gateway_entry.entry_id, "Gateway")
    hub.adopt_device("dispenser", dispenser_entry.entry_id, "Dispenser")

    await hub.async_handle_message(
        _message("gateway", component_network_id="network")
    )
    await hub.async_handle_message(_message("dispenser", gateway_network_id="network"))
    assert registry.async_get(dispenser.id).via_device_id == gateway.id

    await hub.async_handle_message({"deviceInfo": {"deviceId": "dispenser"}})
    assert registry.async_get(dispenser.id).via_device_id == gateway.id

    # Explicit null must clear a link even if the integration's cached network ID
    # was lost or restored from an older state payload.
    hub.gateway_network_ids.pop("dispenser")
    await hub.async_handle_message(
        {"deviceInfo": {"deviceId": "dispenser"}, "gateway": None}
    )
    assert registry.async_get(dispenser.id).via_device_id is None
