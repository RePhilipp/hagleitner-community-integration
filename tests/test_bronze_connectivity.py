"""Hub setup validation and retry-order regressions."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import issue_registry as ir

from custom_components.hagleitner_community import (
    _async_setup_device,
    async_remove_entry,
    async_setup_entry,
)
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.repairs import (
    async_create_queue_not_found_issue,
)
from custom_components.hagleitner_community.service_bus import (
    QueueValidationError,
    QueueValidationFailure,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.mark.parametrize(
    ("reason", "expected_error", "translation_key"),
    [
        (
            QueueValidationFailure.INVALID_AUTH,
            ConfigEntryAuthFailed,
            "service_bus_credentials_invalid",
        ),
        (
            QueueValidationFailure.INVALID_CONNECTION_STRING,
            ConfigEntryAuthFailed,
            "service_bus_credentials_invalid",
        ),
        (
            QueueValidationFailure.QUEUE_NOT_FOUND,
            ConfigEntryError,
            "service_bus_queue_not_found",
        ),
        (
            QueueValidationFailure.CANNOT_CONNECT,
            ConfigEntryNotReady,
            "service_bus_queue_unavailable",
        ),
        (
            QueueValidationFailure.INVALID_QUEUE,
            ConfigEntryError,
            "service_bus_queue_validation_failed",
        ),
        (
            QueueValidationFailure.UNKNOWN,
            ConfigEntryError,
            "service_bus_queue_validation_failed",
        ),
    ],
)
async def test_failed_probe_precedes_hub_and_device_mutation(
    hass, monkeypatch, reason, expected_error, translation_key
):
    """No setup, registration, or background task begins until validation passes."""
    events = []

    async def fail_probe(*_args):
        events.append("probe")
        raise QueueValidationError(reason)

    async def restore(*_args):
        events.append("restore")

    def unexpected_mutation(*_args):
        events.append("mutation")

    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_validate_queue", fail_probe
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_restore_persisted_state",
        restore,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community._async_rebind_orphaned_devices",
        unexpected_mutation,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.HagleitnerHub",
        unexpected_mutation,
    )
    hass.data[DOMAIN] = {}
    entry = SimpleNamespace(
        entry_id="hub-entry",
        data={
            "entry_type": "hub",
            "connection_string": "private-connection-string",
            "queue_name": "queue-a",
        },
    )

    with pytest.raises(expected_error) as raised:
        await async_setup_entry(hass, entry)

    assert events == ["probe"]
    assert hass.data[DOMAIN] == {}
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == translation_key
    assert "private-connection-string" not in str(raised.value)
    assert "raw SDK" not in str(raised.value)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, "queue_not_found_hub-entry"
    )
    if reason is QueueValidationFailure.QUEUE_NOT_FOUND:
        assert issue is not None
        if "config_entry_id" in signature(ir.async_create_issue).parameters:
            assert issue.config_entry_id == "hub-entry"
    else:
        assert issue is None


async def test_successful_probe_happens_before_hub_setup(hass, monkeypatch):
    """A successful validation completes before restoration and receiver startup."""
    events = []

    async def successful_probe(*_args):
        events.append("probe")

    async def restore(*_args):
        events.append("restore")
        hass.data[DOMAIN] = {}

    class Hub:
        def __init__(self):
            self.receiver_task = None
            self.device_sources = {}

        async def async_handle_message(self, _message):
            pass

        def async_set_receiver_available(self, _available):
            pass

    hub = Hub()

    def make_hub(*_args):
        events.append("hub")
        return hub

    async def run_receiver(*_args):
        events.append("receiver")

    async def setup_linked_devices(*_args):
        events.append("device_setup")

    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_validate_queue",
        successful_probe,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_restore_persisted_state",
        restore,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community._async_rebind_orphaned_devices",
        lambda *_args: events.append("rebind"),
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.HagleitnerHub", make_hub
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.run_receiver", run_receiver
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community._async_setup_linked_devices",
        setup_linked_devices,
    )

    class Entry:
        def __init__(self):
            self.entry_id = "hub-entry"
            self.data = {
                "entry_type": "hub",
                "connection_string": "secret",
                "queue_name": "queue-a",
            }

        def async_create_background_task(self, _hass, coroutine, *, name):
            events.append("receiver_task_created")
            return hass.async_create_background_task(coroutine, name)

    async_create_queue_not_found_issue(hass, "hub-entry")

    assert await async_setup_entry(hass, Entry())
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, "queue_not_found_hub-entry")
        is None
    )
    await hass.async_block_till_done()

    assert events[:5] == ["probe", "restore", "rebind", "hub", "receiver_task_created"]
    assert events[5:] == ["receiver", "device_setup"]


async def test_removing_hub_clears_its_queue_repair(hass):
    """A queue repair is cleaned up when its owning hub entry is deleted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    entry.add_to_hass(hass)
    async_create_queue_not_found_issue(hass, entry.entry_id)

    await async_remove_entry(hass, entry)

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"queue_not_found_{entry.entry_id}"
        )
        is None
    )


async def test_device_setup_does_not_reenter_hub_setup_in_progress(
    hass, monkeypatch
):
    """A child setup waits instead of re-entering an in-progress hub setup."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub"},
        state=ConfigEntryState.SETUP_IN_PROGRESS,
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
    setup_hub = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_setup", setup_hub)
    hass.data[DOMAIN] = {}

    with pytest.raises(ConfigEntryNotReady):
        await _async_setup_device(hass, device_entry)

    setup_hub.assert_not_awaited()
