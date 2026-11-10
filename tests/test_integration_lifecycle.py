"""Tests for adopted-device config-entry lifecycle helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.helpers import area_registry as ar, device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hagleitner_community import (
    _async_setup_device,
    async_setup_entry,
)
from custom_components.hagleitner_community import (
    async_remove_entry,
    async_unload_entry,
)
from custom_components.hagleitner_community import (
    _device_model,
    _async_rebind_orphaned_devices,
    _async_set_device_hub_queue,
    _async_setup_linked_devices,
    async_remove_config_entry_device,
)
from custom_components.hagleitner_community.const import DOMAIN


def test_device_model_never_uses_uuid_or_blank_metadata():
    """Device type identifiers are not presented as readable models."""
    assert _device_model({"device_type_name": "  ", "device_name": "  "}) is None
    assert _device_model(
        {
            "device_type_name": "d15a2a06-7a04-4a7b-8f29-815d75c1da2f",
            "device_name": "Readable dispenser",
        }
    ) == "Readable dispenser"


def test_orphaned_devices_rebind_only_to_a_known_matching_hub(hass):
    """Queue affinity and ambiguity determine safe hub reattachment."""
    current_hub = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    current_hub.add_to_hass(hass)
    other_hub = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-b"},
    )
    other_hub.add_to_hass(hass)

    def add_orphan(device_id, **extra_data):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "entry_type": "device",
                "device_id": device_id,
                "hub_entry_id": "removed-hub",
                **extra_data,
            },
        )
        entry.add_to_hass(hass)
        return entry

    queue_a_device = add_orphan("device-a", hub_queue_name="  QUEUE-A ")
    queue_b_device = add_orphan("device-b", hub_queue_name="Queue-B")
    ambiguous_device = add_orphan("device-ambiguous")
    unknown_queue_device = add_orphan("device-unknown", hub_queue_name="queue-c")
    associated_current_device = add_orphan(
        "device-associated-current",
        hub_entry_ids=[current_hub.entry_id],
        hub_queue_name="queue-b",
    )
    associated_other_device = add_orphan(
        "device-associated-other",
        hub_entry_ids=[other_hub.entry_id],
        hub_queue_name="queue-a",
    )
    active_link_device = add_orphan(
        "device-active", hub_entry_id=current_hub.entry_id
    )
    active_other_link_device = add_orphan(
        "device-active-other", hub_entry_id=other_hub.entry_id
    )

    _async_rebind_orphaned_devices(hass, current_hub)

    assert queue_a_device.data["hub_entry_id"] == current_hub.entry_id
    assert queue_a_device.data["hub_queue_name"] == "queue-a"
    assert queue_b_device.data["hub_entry_id"] == other_hub.entry_id
    assert queue_b_device.data["hub_queue_name"] == "queue-b"
    assert ambiguous_device.data["hub_entry_id"] == "removed-hub"
    assert "hub_queue_name" not in ambiguous_device.data
    assert unknown_queue_device.data["hub_entry_id"] == "removed-hub"
    assert associated_current_device.data["hub_entry_id"] == current_hub.entry_id
    assert associated_other_device.data["hub_entry_id"] == other_hub.entry_id
    assert active_link_device.data["hub_entry_id"] == current_hub.entry_id
    assert active_other_link_device.data["hub_entry_id"] == other_hub.entry_id


def test_unlinked_device_binds_to_the_only_available_hub(hass):
    """A sole active queue is a safe fallback when legacy data lacks affinity."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-only"},
    )
    hub_entry.add_to_hass(hass)
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "legacy-device",
            "hub_entry_id": "removed-hub",
        },
    )
    device_entry.add_to_hass(hass)

    _async_rebind_orphaned_devices(hass, hub_entry)

    assert device_entry.data["hub_entry_id"] == hub_entry.entry_id
    assert device_entry.data["hub_queue_name"] == "queue-only"


async def test_device_removal_requires_matching_entry_and_identifier(
    hass, monkeypatch
):
    """Explicit device deletion removes only the config entry it owns."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )
    remove_entry = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_remove", remove_entry)

    matching_device = SimpleNamespace(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "device-1")},
    )
    assert await async_remove_config_entry_device(hass, entry, matching_device)
    remove_entry.assert_awaited_once_with(entry.entry_id)

    remove_entry.reset_mock()
    unrelated_device = SimpleNamespace(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "another-device")},
    )
    assert not await async_remove_config_entry_device(hass, entry, unrelated_device)
    remove_entry.assert_not_awaited()


async def test_device_setup_retries_unloaded_hub_before_registering(hass, monkeypatch):
    """An unloaded queue is set up once before its device can be registered."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    hub_entry.add_to_hass(hass)

    class Hub:
        def adopt_device(self, *_args):
            pass

        def _async_record_device_source(self, *_args):
            pass

        @staticmethod
        def firmware_version_for_device(_device_id):
            return None

    hub = Hub()

    async def load_hub(_entry_id):
        hub_entry.runtime_data = hub
        return True

    setup_hub = AsyncMock(side_effect=load_hub)
    monkeypatch.setattr(hass.config_entries, "async_setup", setup_hub)

    class DeviceRegistry:
        def async_get_devices(self, *, identifiers):
            return []

        def async_get_or_create(self, **_kwargs):
            return SimpleNamespace(id="registered-device")

    monkeypatch.setattr(dr, "async_get", lambda _hass: DeviceRegistry())
    monkeypatch.setattr(
        hass.config_entries,
        "async_forward_entry_setups",
        lambda *_args: asyncio.sleep(0),
    )
    device_entry = SimpleNamespace(
        data={
            "device_id": "device-1",
            "device_name": "Dispenser",
            "hub_entry_id": hub_entry.entry_id,
        },
        entry_id="device-entry",
        title="Dispenser",
        runtime_data=None,
    )

    assert await _async_setup_device(hass, device_entry)
    setup_hub.assert_awaited_once_with(hub_entry.entry_id)
    assert device_entry.runtime_data is hub


@pytest.mark.parametrize("area_exists", [True, False])
async def test_new_device_uses_area_suggestion_only_while_area_exists(
    hass, monkeypatch, area_exists
):
    """Adoption assigns a valid suggested area but ignores stale area IDs."""
    hub_entry = MockConfigEntry(domain=DOMAIN, data={"entry_type": "hub"})
    hub_entry.add_to_hass(hass)

    class Hub:
        @staticmethod
        def adopt_device(*_args):
            pass

        @staticmethod
        def _async_record_device_source(*_args):
            pass

        @staticmethod
        def firmware_version_for_device(_device_id):
            return None

    hub_entry.runtime_data = Hub()

    class DeviceRegistry:
        def __init__(self):
            self.updated_area = None

        def async_get_devices(self, *, identifiers):
            return []

        def async_get_or_create(self, **_kwargs):
            return SimpleNamespace(id="registered-device")

        def async_update_device(self, _device_id, **kwargs):
            self.updated_area = kwargs["area_id"]

    device_registry = DeviceRegistry()
    monkeypatch.setattr(dr, "async_get", lambda _hass: device_registry)
    monkeypatch.setattr(
        ar,
        "async_get",
        lambda _hass: SimpleNamespace(
            async_get_area=lambda _area_id: object() if area_exists else None
        ),
    )
    monkeypatch.setattr(
        hass.config_entries,
        "async_forward_entry_setups",
        lambda *_args: asyncio.sleep(0),
    )
    entry = SimpleNamespace(
        data={
            "device_id": "device-1",
            "device_name": "Dispenser",
            "hub_entry_id": hub_entry.entry_id,
            "area_id": "suggested-area",
        },
        entry_id="device-entry",
        title="Dispenser",
        runtime_data=None,
    )

    assert await _async_setup_device(hass, entry)
    assert device_registry.updated_area == ("suggested-area" if area_exists else None)


async def test_linked_device_setup_filters_by_hub_and_disabled_state(hass, monkeypatch):
    """A loaded hub only starts its enabled, not-yet-loaded device entries."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    hub_entry.add_to_hass(hass)
    hub = object()
    hub_entry.runtime_data = hub
    linked_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "linked-device",
            "hub_entry_id": hub_entry.entry_id,
        },
    )
    linked_entry.add_to_hass(hass)
    unrelated_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "other-device",
            "hub_entry_id": "another-hub",
        },
    )
    unrelated_entry.add_to_hass(hass)
    disabled_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "disabled-device",
            "hub_entry_id": hub_entry.entry_id,
        },
        disabled_by=ConfigEntryDisabler.USER,
    )
    disabled_entry.add_to_hass(hass)
    setup = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_setup", setup)

    await _async_setup_linked_devices(hass, hub_entry.entry_id, hub)

    setup.assert_awaited_once_with(linked_entry.entry_id)


async def test_linked_device_setup_tolerates_removed_hub(hass):
    """A background setup task exits harmlessly if its hub entry disappeared."""
    await _async_setup_linked_devices(hass, "removed-hub", object())


async def test_hub_setup_restores_links_and_starts_the_receiver(hass, monkeypatch):
    """Hub startup reattaches configured devices and launches one receiver task."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "hub",
            "connection_string": "private-connection",
            "queue_name": "queue-a",
        },
    )
    hub_entry.add_to_hass(hass)
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "device-1",
            "device_name": "Dispenser",
            "hub_entry_id": hub_entry.entry_id,
        },
    )
    device_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}

    async def no_op(*_args, **_kwargs):
        return None

    async def blocked_receiver(*_args, **_kwargs):
        await asyncio.Event().wait()

    receiver_tasks = []

    def create_background_task(_hass, coroutine, *, name):
        task = asyncio.create_task(coroutine, name=name)
        receiver_tasks.append(task)
        return task

    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_validate_queue", no_op
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_restore_persisted_state",
        no_op,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.run_receiver", blocked_receiver
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community._async_setup_linked_devices",
        no_op,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.HagleitnerHub._async_schedule_state_save",
        lambda _hub: None,
    )
    monkeypatch.setattr(
        hub_entry, "async_create_background_task", create_background_task
    )

    assert await async_setup_entry(hass, hub_entry)
    setup_task = hass.data[DOMAIN]["_device_setup_tasks"][hub_entry.entry_id]
    await setup_task

    hub = hub_entry.runtime_data
    assert device_entry.data["hub_queue_name"] == "queue-a"
    assert device_entry.data["hub_entry_ids"] == [hub_entry.entry_id]
    assert "device-1" in hub.adopted_device_ids
    assert hub.device_sources["device-1"] == {hub_entry.entry_id}
    assert len(receiver_tasks) == 1

    receiver_tasks[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await receiver_tasks[0]


def test_device_entry_remembers_hub_queue_for_recovery(hass):
    """The latest queue name is persisted without rewriting unchanged values."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
    )
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "hub_queue_name": "old-queue"},
    )
    hub_entry.add_to_hass(hass)
    device_entry.add_to_hass(hass)

    _async_set_device_hub_queue(hass, device_entry, hub_entry)
    assert device_entry.data["hub_queue_name"] == "queue-a"
    _async_set_device_hub_queue(hass, device_entry, hub_entry)
    assert device_entry.data["hub_queue_name"] == "queue-a"


async def test_device_unload_removes_its_runtime_adoption(hass, monkeypatch):
    """Successful platform unload releases device adoption and runtime state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )
    unadopt_device = Mock()
    hub = SimpleNamespace(unadopt_device=unadopt_device)
    entry.runtime_data = hub
    unload_platforms = AsyncMock(return_value=True)
    monkeypatch.setattr(
        hass.config_entries, "async_unload_platforms", unload_platforms
    )

    assert await async_unload_entry(hass, entry)
    unload_platforms.assert_awaited_once()
    unadopt_device.assert_called_once_with("device-1")
    assert entry.runtime_data is None


async def test_device_unload_failure_preserves_adoption(hass, monkeypatch):
    """A platform unload failure leaves runtime data attached for retry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )
    unadopt_device = Mock()
    hub = SimpleNamespace(unadopt_device=unadopt_device)
    entry.runtime_data = hub
    monkeypatch.setattr(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=False),
    )

    assert not await async_unload_entry(hass, entry)
    assert entry.runtime_data is hub
    unadopt_device.assert_not_called()


async def test_hub_unload_keeps_device_config_and_cancels_receiver(hass):
    """Unloading a hub retains its device entry for future queue recovery."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "queue-a"},
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
    receiver = asyncio.create_task(asyncio.Event().wait())
    sources = {"device-1": {hub_entry.entry_id}}
    hub_entry.runtime_data = SimpleNamespace(
        device_sources=sources,
        receiver_task=receiver,
    )
    hass.data[DOMAIN] = {"_device_setup_tasks": {}}

    assert await async_unload_entry(hass, hub_entry)
    assert device_entry.data["hub_queue_name"] == "queue-a"
    assert hub_entry.runtime_data is None
    assert sources["device-1"] == set()
    with pytest.raises(asyncio.CancelledError):
        await receiver


async def test_remove_entry_clears_queue_issue_and_device_issues(hass, monkeypatch):
    """Config-entry removal cleans queue repairs and adopted-device repairs."""
    clear_queue = Mock()
    clear_device = Mock()
    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_clear_queue_not_found_issue",
        clear_queue,
    )
    monkeypatch.setattr(
        "custom_components.hagleitner_community.async_clear_maintenance_issues",
        clear_device,
    )
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub"},
    )
    device_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "device", "device_id": "device-1"},
    )

    await async_remove_entry(hass, hub_entry)
    await async_remove_entry(hass, device_entry)

    assert [call.args for call in clear_queue.call_args_list] == [
        (hass, hub_entry.entry_id),
        (hass, device_entry.entry_id),
    ]
    clear_device.assert_called_once_with(hass, "device-1")
