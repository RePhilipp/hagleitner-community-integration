"""User removal support for adopted devices on push-only feeds."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.hagleitner_community as integration
from custom_components.hagleitner_community.const import DOMAIN
from homeassistant.helpers import device_registry as dr


async def test_user_can_remove_owned_adopted_device(hass):
    """The owner permits manual cleanup because the queue has no full inventory."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "device-1")},
    )

    assert await integration.async_remove_config_entry_device(hass, entry, device)
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert not dr.async_get(hass).async_get_devices(
        identifiers={(DOMAIN, "device-1")}
    )


async def test_user_removal_rejects_unowned_device(hass):
    """The removal callback never approves another config entry's device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )
    entry.add_to_hass(hass)
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub"},
    )
    other_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={(DOMAIN, "device-1")},
    )

    assert not await integration.async_remove_config_entry_device(hass, entry, device)
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry


async def test_user_removal_rejects_hub_entry_device(hass):
    """Hub entries cannot authorize removal of unrelated device registry items."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "device-1")},
    )

    assert not await integration.async_remove_config_entry_device(hass, entry, device)
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry


async def test_user_removal_rejects_mismatched_device_identifier(hass):
    """An adopted entry cannot authorize deletion of a different device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "device-2")},
    )

    assert not await integration.async_remove_config_entry_device(hass, entry, device)
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
