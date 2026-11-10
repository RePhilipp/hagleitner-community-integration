"""Tests for the Hagleitner Community config flow."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_REAUTH,
    SOURCE_USER,
    ConfigEntryDisabler,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community import config_flow
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.service_bus import (
    QueueValidationError,
    QueueValidationFailure,
)


async def test_user_flow_creates_hub_entry(
    hass, enable_custom_integrations, monkeypatch
):
    """The user flow stores the normalized queue connection details."""
    monkeypatch.setattr(config_flow, "async_validate_queue", _validate_ok)
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
    monkeypatch,
):
    """A duplicate queue is rejected, and the same flow can then succeed."""
    monkeypatch.setattr(config_flow, "async_validate_queue", _validate_ok)
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


@pytest.mark.parametrize(
    "reason",
    [
        QueueValidationFailure.INVALID_CONNECTION_STRING,
        QueueValidationFailure.INVALID_QUEUE,
        QueueValidationFailure.INVALID_AUTH,
        QueueValidationFailure.QUEUE_NOT_FOUND,
        QueueValidationFailure.CANNOT_CONNECT,
        QueueValidationFailure.UNKNOWN,
    ],
)
async def test_user_flow_does_not_create_entry_when_probe_fails(
    hass, enable_custom_integrations, monkeypatch, reason
):
    """Probe failures render a generic error and do not create a config entry."""

    async def fail_probe(*_args):
        raise QueueValidationError(reason)

    monkeypatch.setattr(config_flow, "async_validate_queue", fail_probe)
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={
            "connection_string": "Endpoint=sb://example/;SharedAccessKey=secret",
            "queue_name": "queue-a",
        },
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": reason.value}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_reauth_replaces_credentials_after_successful_probe(
    hass, enable_custom_integrations, monkeypatch
):
    """Reauth validates a replacement secret and preserves the queue name."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "hub",
            "connection_string": "old-secret",
            "queue_name": "queue-a",
        },
    )
    entry.add_to_hass(hass)
    validated = []

    async def validate(connection_string, queue_name):
        validated.append((connection_string, queue_name))

    monkeypatch.setattr(config_flow, "async_validate_queue", validate)
    monkeypatch.setattr(
        hass.config_entries,
        "async_reload",
        lambda _entry_id: asyncio.sleep(0, result=True),
    )

    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
    )
    assert form["type"] == "form"
    assert form["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={"connection_string": "new-secret"},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert validated == [("new-secret", "queue-a")]
    assert entry.data["connection_string"] == "new-secret"
    assert entry.data["queue_name"] == "queue-a"


async def test_reauth_keeps_existing_credentials_when_probe_fails(
    hass, enable_custom_integrations, monkeypatch
):
    """A failed reauth attempt leaves stored credentials untouched."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "hub",
            "connection_string": "old-secret",
            "queue_name": "queue-a",
        },
    )
    entry.add_to_hass(hass)

    async def fail_probe(*_args):
        raise QueueValidationError(QueueValidationFailure.INVALID_AUTH)

    monkeypatch.setattr(config_flow, "async_validate_queue", fail_probe)
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={"connection_string": "rejected-secret"},
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["connection_string"] == "old-secret"


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


async def _validate_ok(*_args):
    """Stand in for a successful external Service Bus probe."""
