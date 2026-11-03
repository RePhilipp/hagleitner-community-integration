"""Tests for Home Assistant area suggestions during device adoption."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.coordinator import (
    _suggest_area_from_hsm_location,
    _suggest_existing_area_id,
)
from custom_components.hagleitner_community.resource_data import DeviceMetadata


def _add_device(
    hass,
    device_id: str,
    area_id: str | None = None,
):
    """Create an integration device in Home Assistant's device registry."""
    config_entry = MockConfigEntry(domain=DOMAIN)
    config_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, device_id)},
    )
    if area_id is not None:
        device_registry.async_update_device(device.id, area_id=area_id)
    return device


async def test_hsm_location_reuses_area_from_adopted_device(hass):
    """An exact HSM path match reuses the sibling device's HA area."""
    area = ar.async_get(hass).async_create("Production")
    _add_device(hass, "existing-device", area.id)
    hass.data[DOMAIN] = {
        "_shared_device_state": {
            "device_metadata": {
                "existing-device": DeviceMetadata(location="HQ / Production")
            }
        }
    }

    assert _suggest_area_from_hsm_location(
        hass,
        "new-device",
        "hq /   production",
    ) == (True, area.id)


async def test_hsm_location_does_not_guess_between_conflicting_areas(hass):
    """Conflicting HA areas for the same HSM path suppress guessing."""
    area_one = ar.async_get(hass).async_create("Production")
    area_two = ar.async_get(hass).async_create("Warehouse")
    _add_device(hass, "existing-one", area_one.id)
    _add_device(hass, "existing-two", area_two.id)
    hass.data[DOMAIN] = {
        "_shared_device_state": {
            "device_metadata": {
                "existing-one": DeviceMetadata(location="HQ / Production"),
                "existing-two": DeviceMetadata(location="HQ / Production"),
            }
        }
    }

    assert _suggest_area_from_hsm_location(
        hass,
        "new-device",
        "HQ / Production",
    ) == (True, None)


async def test_hsm_location_falls_back_to_persisted_location_sensor(hass):
    """The stored HA location sensor is used when runtime metadata is absent."""
    area = ar.async_get(hass).async_create("Production")
    device = _add_device(hass, "existing-device", area.id)
    entity = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        "existing-device_location",
        device_id=device.id,
    )
    hass.states.async_set(entity.entity_id, "HQ / Production")

    assert _suggest_area_from_hsm_location(
        hass,
        "new-device",
        "HQ / Production",
    ) == (True, area.id)


async def test_area_suggestion_uses_unique_exact_area_name(hass):
    """A unique HA area name match is preferred."""
    area = ar.async_get(hass).async_create("Production")

    assert _suggest_existing_area_id(hass, " production ") == area.id


async def test_adoption_form_defaults_and_saves_suggested_area(
    hass,
    enable_custom_integrations,
):
    """The discovery form shows HSM metadata and saves the selected area."""
    area = ar.async_get(hass).async_create("Production")
    discovery_data = {
        "device_id": "new-device",
        "device_type_id": "device-type",
        "device_name": "Dispenser",
        "hub_entry_id": "hub-entry",
        "hsm_location_path": "HQ / Production",
        "hsm_mount_point": "Wall",
        "suggested_area_id": area.id,
    }

    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data=discovery_data,
    )

    assert form["type"] == "form"
    assert form["step_id"] == "confirm"
    assert form["description_placeholders"]["location_path"] == "HQ / Production"
    assert form["description_placeholders"]["mount_point"] == "Wall"
    area_field = next(
        key for key in form["data_schema"].schema if key.schema == "area_id"
    )
    assert area_field.default() == area.id

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={"area_id": area.id},
    )

    assert result["type"] == "create_entry"
    device_entry = result["result"]
    assert device_entry.data["area_id"] == area.id
    assert "suggested_area_id" not in device_entry.data
    assert "hsm_location_path" not in device_entry.data
    assert "hsm_mount_point" not in device_entry.data
