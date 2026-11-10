"""Tests for the Hagleitner Community config flow."""

from __future__ import annotations

from homeassistant.config_entries import (
    ConfigEntryDisabler,
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
)
import pytest

from custom_components.hagleitner_community.const import DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_user_flow_creates_hub_entry(hass, enable_custom_integrations):
    """The user flow stores the normalized queue connection details."""
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert form["type"] == "form"
    assert form["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={
            "connection_string": "Endpoint=sb://example/;SharedAccessKey=secret",
            "queue_name": "  Queue-A  ",
        },
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Hagleitner Community (Queue-A)"
    assert result["data"] == {
        "entry_type": "hub",
        "connection_string": "Endpoint=sb://example/;SharedAccessKey=secret",
        "queue_name": "Queue-A",
    }
    assert result["result"].unique_id is None


@pytest.mark.parametrize(
    ("disabled_by", "expected_error"),
    [
        (None, "queue_already_configured"),
        (ConfigEntryDisabler.USER, "queue_already_configured_disabled"),
    ],
)
async def test_duplicate_queue_error_recovers(
    hass,
    enable_custom_integrations,
    disabled_by,
    expected_error,
):
    """A duplicate queue is rejected, and the same flow can then succeed."""
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
        disabled_by=disabled_by,
    )
    existing_entry.add_to_hass(hass)

    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    duplicate_result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={
            "connection_string": "Endpoint=sb://example/;SharedAccessKey=secret",
            "queue_name": " Queue-A ",
        },
    )

    assert duplicate_result["type"] == "form"
    assert duplicate_result["errors"] == {"base": expected_error}

    recovered_result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={
            "connection_string": "Endpoint=sb://example/;SharedAccessKey=secret",
            "queue_name": "queue-b",
        },
    )

    assert recovered_result["type"] == "create_entry"
    assert recovered_result["data"]["queue_name"] == "queue-b"
    assert recovered_result["result"].unique_id is None


async def test_device_discovery_aborts_for_existing_unique_id(
    hass,
    enable_custom_integrations,
):
    """Discovery does not offer a device that already has an entry."""
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="device-123",
        data={"entry_type": "device", "device_id": "device-123"},
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={
            "hub_entry_id": "hub-entry",
            "device_id": "device-123",
            "device_name": "Dispenser",
        },
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_device_discovery_ignores_missing_suggested_area(
    hass,
    enable_custom_integrations,
):
    """A stale area suggestion does not prevent adopting a discovered device."""
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={
            "hub_entry_id": "hub-entry",
            "device_id": "device-with-stale-area",
            "device_name": "Dispenser",
            "suggested_area_id": "area-that-no-longer-exists",
        },
    )

    assert form["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={},
    )

    assert result["type"] == "create_entry"
    assert result["result"].unique_id == "device-with-stale-area"
    assert "area_id" not in result["data"]


async def test_confirm_without_discovery_data_aborts(
    hass,
    enable_custom_integrations,
):
    """The confirm step safely aborts if its discovery data was lost."""
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={
            "hub_entry_id": "hub-entry",
            "device_id": "device-123",
            "device_name": "Dispenser",
        },
    )
    flow = hass.config_entries.flow._progress[form["flow_id"]]
    flow._discovery_info = None

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "missing_discovery_info"
