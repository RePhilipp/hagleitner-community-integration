"""Tests for privacy-safe integration diagnostics."""

from __future__ import annotations

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _snapshot(
    definition: ResourceDefinition | None,
    *,
    raw_value: object = None,
    mapped_value: object = None,
) -> ResourceValueSnapshot:
    """Build a resource reading for diagnostics tests."""
    return ResourceValueSnapshot(
        key="resource:1",
        logged_at="2026-01-01T00:00:00Z",
        resource_type_id=1,
        instance_number=1,
        equivalent_id=None,
        raw_value=raw_value,
        mapped_value=mapped_value,
        raw_resource={"sensitive_payload": "must-not-appear"},
        definition=definition,
        device_type_names=frozenset(),
    )


async def test_hub_diagnostics_include_safe_resources_not_config_secrets(hass):
    """Hub diagnostics report useful values without exposing config or IDs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "hub",
            "queue_name": "customer-private-queue",
            "connection_string": "Endpoint=sb://private;SharedAccessKey=secret",
        },
    )
    entry.add_to_hass(hass)
    device_id = "sensitive-device-id"
    reading = _snapshot(
        ResourceDefinition(name="Dispense count", kind="counter"),
        raw_value=42,
    )
    hass.data[DOMAIN] = {
        "_shared_device_state": {
            "adopted_device_ids": {device_id},
            "device_sources": {device_id: {entry.entry_id}},
            "latest_values": {device_id: {reading.key: reading}},
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result == {
        "device_count": 1,
        "devices": [
            {
                "device": "Device 1",
                "resources": [{"name": "Dispense count", "value": 42}],
            }
        ],
    }
    serialized = repr(result)
    assert "customer-private-queue" not in serialized
    assert "SharedAccessKey" not in serialized
    assert device_id not in serialized
    assert "must-not-appear" not in serialized


async def test_device_diagnostics_include_only_allowlisted_resource_values(hass):
    """Device diagnostics expose approved readings, not raw payloads or IDs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "sensitive-device-id",
            "hub_queue_name": "customer-private-queue",
            "connection_string": "Endpoint=sb://private;SharedAccessKey=secret",
        },
    )
    entry.add_to_hass(hass)
    device_id = entry.data["device_id"]
    readings = {
        "counter": _snapshot(
            ResourceDefinition(name="Dispense count", kind="counter"),
            raw_value=7,
        ),
        "boolean-counter": _snapshot(
            ResourceDefinition(name="Boolean counter", kind="counter"),
            raw_value=True,
        ),
        "non-finite-counter": _snapshot(
            ResourceDefinition(name="Non-finite counter", kind="counter"),
            raw_value=float("inf"),
        ),
        "firmware": _snapshot(
            ResourceDefinition(name="Firmware version", kind="diagnostic"),
            raw_value="1.2.3+build_4",
        ),
        "unrecognized": _snapshot(None, raw_value="customer-sensitive"),
        "bad-firmware": _snapshot(
            ResourceDefinition(name="Firmware version", kind="diagnostic"),
            raw_value="version; customer-sensitive",
        ),
        "presence": _snapshot(
            ResourceDefinition(
                name="Presence", kind="presence", enum_values={0: "present"}
            ),
            mapped_value="present",
        ),
        "bad-presence": _snapshot(
            ResourceDefinition(
                name="Presence", kind="presence", enum_values={0: "present"}
            ),
            mapped_value="customer-sensitive",
        ),
        "enum": _snapshot(
            ResourceDefinition(name="Status", kind="enum", enum_values={0: "ok"}),
            mapped_value="ok",
        ),
        "bad-enum": _snapshot(
            ResourceDefinition(name="Status", kind="enum", enum_values={0: "ok"}),
            mapped_value="customer-sensitive",
        ),
    }
    hass.data[DOMAIN] = {
        "_shared_device_state": {
            "adopted_device_ids": {device_id},
            "latest_values": {device_id: readings},
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result == {
        "device_count": 1,
        "devices": [
            {
                "device": "Device 1",
                "resources": [
                    {"name": "Dispense count", "value": 7},
                    {"name": "Firmware version", "value": "1.2.3+build_4"},
                    {"name": "Presence", "value": "present"},
                    {"name": "Status", "value": "ok"},
                ],
            }
        ],
    }
    serialized = repr(result)
    assert "customer-private-queue" not in serialized
    assert "SharedAccessKey" not in serialized
    assert device_id not in serialized
    assert "customer-sensitive" not in serialized


async def test_hub_diagnostics_find_adopted_entries_linked_to_hub(hass):
    """Hub diagnostics include adopted entries linked through device config."""
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "hub", "queue_name": "private-queue"},
    )
    hub_entry.add_to_hass(hass)
    device_id = "sensitive-device-id"
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
    invalid_links_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": "device",
            "device_id": "other-device-id",
            "hub_entry_ids": "invalid",
        },
    )
    invalid_links_entry.add_to_hass(hass)
    reading = _snapshot(
        ResourceDefinition(name="Flow rate", kind="measurement"),
        raw_value=1.5,
    )
    hass.data[DOMAIN] = {
        "_shared_device_state": {
            "adopted_device_ids": {device_id},
            "latest_values": {device_id: {reading.key: reading}},
        }
    }

    result = await async_get_config_entry_diagnostics(hass, hub_entry)

    assert result == {
        "device_count": 1,
        "devices": [
            {
                "device": "Device 1",
                "resources": [{"name": "Flow rate", "value": 1.5}],
            }
        ],
    }
    assert device_id not in repr(result)
