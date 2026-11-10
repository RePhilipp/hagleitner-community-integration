"""Regression tests for recent Home Assistant and Service Bus log fixes."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community import (
    _async_setup_device,
    async_setup_entry,
    service_bus,
)
from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.resource_data import device_display_name


@pytest.mark.parametrize(
    ("friendly_type_name", "expected_model"),
    [
        ("Foam dispenser", "Foam dispenser"),
        (None, "Hagleitner Foam dispenser"),
        (
            "d15a2a06-7a04-4a7b-8f29-815d75c1da2f",
            "Hagleitner Foam dispenser",
        ),
    ],
)
async def test_device_setup_uses_supported_registry_lookup_and_readable_model(
    hass,
    monkeypatch,
    friendly_type_name,
    expected_model,
):
    """Setup uses the current registry API and never exposes a type UUID as model."""
    identifiers = {(DOMAIN, "device-1")}
    type_id = "d15a2a06-7a04-4a7b-8f29-815d75c1da2f"

    class DeviceRegistry:
        """Minimal registry that deliberately has no deprecated lookup method."""

        def __init__(self):
            self.lookup_identifiers = None
            self.create_options = None

        def async_get_devices(self, *, identifiers):
            self.lookup_identifiers = identifiers
            return [object()]

        def async_get_or_create(self, **kwargs):
            self.create_options = kwargs
            return SimpleNamespace(id="registered-device")

    registry = DeviceRegistry()
    monkeypatch.setattr(dr, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        hass.config_entries,
        "async_forward_entry_setups",
        lambda *_args: asyncio.sleep(0),
    )

    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub"},
    )
    hub_entry.add_to_hass(hass)
    entry = SimpleNamespace(
        data={
            "device_id": "device-1",
            "device_name": "Foam dispenser MountPoint",
            "device_type_id": type_id,
            "hub_entry_id": hub_entry.entry_id,
            "device_type_name": friendly_type_name,
        },
        entry_id="device-entry-1",
        title="Dispenser",
        runtime_data=None,
    )

    class Hub:
        """Provide the hub methods needed during adopted-device setup."""

        @staticmethod
        def adopt_device(*_args):
            pass

        @staticmethod
        def _async_record_device_source(*_args):
            pass

        @staticmethod
        def firmware_version_for_device(_device_id):
            return "1.2.3"

    hub = Hub()
    hub_entry.runtime_data = hub
    hass.data[DOMAIN] = {}

    assert await _async_setup_device(hass, entry)
    assert entry.runtime_data is hub
    assert registry.lookup_identifiers == identifiers
    assert registry.create_options["model"] == expected_model
    assert registry.create_options["sw_version"] == "1.2.3"
    assert registry.create_options["manufacturer"] == "Hagleitner"
    assert registry.create_options["identifiers"] == identifiers


@pytest.mark.parametrize(
    ("mount_point", "expected_name"),
    [
        (" MountPoint ", "Foam dispenser MountPoint"),
        ("", "Foam dispenser"),
        ("   ", "Foam dispenser"),
        (None, "Foam dispenser"),
        (42, "Foam dispenser"),
    ],
)
def test_device_display_name_includes_nonempty_mount_point(
    mount_point, expected_name
):
    """Device names append a non-empty, trimmed mount point when available."""
    message = {
        "deviceInfo": {
            "deviceId": "device-1",
            "deviceTypeNameTranslations": [
                {"languageTag": "en", "value": "Foam dispenser"}
            ],
        },
        "locationInfo": {"mountPoint": mount_point},
    }

    assert device_display_name(message) == expected_name


async def test_hub_receiver_uses_config_entry_background_task(hass, monkeypatch):
    """The persistent receiver is excluded from startup task waits."""
    created_tasks = []
    receiver_started = asyncio.Event()

    class Entry:
        entry_id = "hub-1"
        data = {"connection_string": "connection", "queue_name": "queue"}

        def async_create_background_task(self, hass, target, name):
            created_tasks.append(name)
            return hass.async_create_background_task(target, name)

    class Hub:
        receiver_task = None

        async def async_handle_message(self, _message):
            pass

        def async_set_receiver_available(self, _available):
            pass

    hub = Hub()

    async def run_receiver(*_args):
        receiver_started.set()
        await asyncio.Event().wait()

    async def setup_linked_devices(*_args):
        pass

    monkeypatch.setattr(
        "custom_components.hagleitner_community._async_rebind_orphaned_devices",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_validate_queue",
        lambda *_args: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.HagleitnerHub",
        lambda *_args: hub,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community._async_setup_linked_devices",
        setup_linked_devices,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.run_receiver",
        run_receiver,
    )

    hass.data[DOMAIN] = {}
    entry = Entry()
    assert await async_setup_entry(hass, entry)
    assert entry.runtime_data is hub
    await asyncio.wait_for(receiver_started.wait(), timeout=1)
    await hass.async_block_till_done()

    assert created_tasks == [f"{DOMAIN} Service Bus receiver"]
    assert hub.receiver_task is not None and not hub.receiver_task.done()

    hub.receiver_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await hub.receiver_task


async def test_receiver_preloads_tls_context_off_loop_and_keeps_async_io(
    monkeypatch,
):
    """TLS setup and SDK receiver creation are off-loop; network I/O stays async."""
    event_loop_thread = threading.get_ident()
    context_thread = None
    receiver_thread = None
    expected_context = object()
    client_options = {}
    receiver = None
    receiver_closed = False
    client_closed = False

    def create_ssl_context():
        nonlocal context_thread
        context_thread = threading.get_ident()
        return expected_context

    class FakeReceiver:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            nonlocal receiver_closed
            receiver_closed = True

        async def receive_messages(self, **_kwargs):
            raise asyncio.CancelledError

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            nonlocal client_closed
            client_closed = True

        def get_queue_receiver(self, **_kwargs):
            nonlocal receiver_thread
            receiver_thread = threading.get_ident()
            return receiver

    def from_connection_string(_connection_string, **kwargs):
        client_options.update(kwargs)
        return FakeClient()

    receiver = FakeReceiver()
    monkeypatch.setattr(service_bus, "_create_ssl_context", create_ssl_context)
    monkeypatch.setattr(
        service_bus.ServiceBusClient,
        "from_connection_string",
        staticmethod(from_connection_string),
    )

    with pytest.raises(asyncio.CancelledError):
        await service_bus.run_receiver("connection", "queue", lambda _message: None)

    assert context_thread is not None and context_thread != event_loop_thread
    assert receiver_thread is not None and receiver_thread != event_loop_thread
    assert client_options["ssl_context"] is expected_context
    assert receiver_closed is True
    assert client_closed is True
