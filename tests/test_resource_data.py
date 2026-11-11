"""Tests for parsing, ordering, and safely persisting resource values."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.hagleitner_community.resource_data import (
    ResourceDefinition,
    ResourceValueSnapshot,
    battery_percentage,
    device_identity,
    parse_device_metadata,
    resource_value_key,
    resource_value_snapshots,
    restore_resource_snapshot,
    serialize_resource_snapshot,
    should_accept_reading,
    source_timestamp,
)


def _snapshot(
    *,
    definition: ResourceDefinition | None = None,
    logged_at: object = "2026-01-02T00:00:00Z",
    raw_value: object = "1.2.3",
    resource_type_id: object = 3,
    instance_number: object = 0,
    key: str = "resource-key",
) -> ResourceValueSnapshot:
    """Build a snapshot for the resource parsing and persistence helpers."""
    return ResourceValueSnapshot(
        key=key,
        logged_at=logged_at,
        resource_type_id=resource_type_id,
        instance_number=instance_number,
        equivalent_id=None,
        raw_value=raw_value,
        mapped_value=raw_value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


def test_metadata_parser_ignores_malformed_optional_sections():
    """Optional customer and location fields cannot corrupt metadata parsing."""
    malformed = parse_device_metadata(
        {
            "customerInfo": ["not", "an", "object"],
            "locationInfo": "not an object",
        }
    )
    assert malformed.customer_name is None
    assert malformed.customer_id is None
    assert malformed.location is None
    assert malformed.mount_point is None

    partial = parse_device_metadata(
        {
            "customerInfo": {"name1": "   ", "name2": 123, "customerId": True},
            "locationInfo": {
                "locations": [None, {"name": "  "}, {"name": "Room 4"}],
                "mountPoint": " Wall ",
            },
        }
    )
    assert partial.customer_name is None
    assert partial.customer_id is None
    assert partial.location == "Room 4"
    assert partial.innermost_location == "Room 4"
    assert partial.mount_point == "Wall"

    assert (
        parse_device_metadata({"locationInfo": {"locations": "invalid"}}).location
        is None
    )


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"deviceInfo": None},
        {"deviceInfo": {"deviceId": "  "}},
    ],
)
def test_device_identity_rejects_missing_or_empty_identifiers(message):
    """Messages without a real device ID are rejected before processing."""
    with pytest.raises(ValueError):
        device_identity(message)


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(),
        _snapshot(
            definition=ResourceDefinition(name="Test", kind="counter"),
            resource_type_id=True,
        ),
        _snapshot(
            definition=ResourceDefinition(name="Test", kind="counter"),
            instance_number=False,
        ),
        _snapshot(
            definition=ResourceDefinition(name="Test", kind="counter"),
            raw_value=[],
        ),
    ],
)
def test_snapshot_serializer_rejects_unsupported_or_nonprimitive_values(snapshot):
    """Persisted resource state contains only supported identifiers and scalars."""
    assert serialize_resource_snapshot(snapshot) is None


def test_snapshot_restore_validates_shape_and_normalizes_persisted_metadata():
    """Restoration ignores invalid data and normalizes supported stored snapshots."""
    assert restore_resource_snapshot([]) is None
    assert (
        restore_resource_snapshot({"resource_type_id": True, "instance_number": 0})
        is None
    )
    assert restore_resource_snapshot(
        {"resource_type_id": 3, "instance_number": 0, "raw_value": []}
    ) is None
    assert restore_resource_snapshot(
        {"resource_type_id": 99999, "instance_number": 0, "raw_value": 1}
    ) is None

    restored = restore_resource_snapshot(
        {
            "resource_type_id": 3,
            "instance_number": 0,
            "equivalent_id": 17,
            "raw_value": " 1.2.3 ",
            "logged_at": "   ",
            "device_type_names": ["  Gateway  ", 3, ""],
        }
    )
    assert restored is not None
    assert restored.logged_at == "unknown"
    assert restored.equivalent_id is None
    assert restored.device_type_names == frozenset({"gateway"})
    assert restored.definition is not None
    assert restored.definition.name == "Firmware version"


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (0, "hard_offline"),
        (1, "soft_offline"),
        (2, "online"),
    ],
)
def test_data_link_expectation_resource_maps_classification_values(
    raw_value, expected
):
    """Type 45060 instance 0 maps its three known enum values for display."""
    snapshots = resource_value_snapshots(
        {
            "deviceInfo": {"deviceId": "device-1"},
            "readings": [
                {
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 45060,
                                "resourceInstanceNo": 0,
                                "resourceInstanceEquivalentId": (
                                    "b81580d4-55b7-49f3-95b6-a1b9effe5118"
                                ),
                            },
                            "integerValue": raw_value,
                        }
                    ]
                }
            ],
        }
    )

    assert len(snapshots) == 1
    assert snapshots[0].definition is not None
    assert snapshots[0].definition.name == "Data-link expectation"
    assert snapshots[0].mapped_value == expected


def test_battery_and_timestamp_helpers_handle_unusable_values():
    """Invalid battery readings and timestamps are treated conservatively."""
    battery_definition = ResourceDefinition(
        name="Battery",
        kind="battery",
        battery_percent_values={0: 100},
    )
    assert battery_percentage(_snapshot(definition=None)) is None
    assert battery_percentage(
        _snapshot(definition=ResourceDefinition(name="Counter", kind="counter"))
    ) is None
    assert (
        battery_percentage(
            _snapshot(definition=battery_definition, raw_value=True)
        )
        is None
    )
    assert battery_percentage(
        _snapshot(definition=battery_definition, raw_value=8)
    ) is None

    current = _snapshot(logged_at="not-a-timestamp")
    incoming = _snapshot(logged_at="2026-01-01T00:00:00Z")
    assert should_accept_reading(incoming, current)
    assert not should_accept_reading(
        _snapshot(logged_at="invalid"),
        _snapshot(logged_at="2026-01-01T00:00:00Z"),
    )
    assert not should_accept_reading(
        _snapshot(logged_at="2026-01-01T00:00:00Z"),
        _snapshot(logged_at="2026-01-02T00:00:00Z"),
    )
    assert should_accept_reading(
        _snapshot(logged_at="2026-01-02T00:00:00Z"),
        _snapshot(logged_at="2026-01-02T00:00:00+00:00"),
    )

    assert source_timestamp(datetime(2026, 1, 2, tzinfo=timezone.utc)) == (
        "2026-01-02T00:00:00+00:00"
    )
    assert source_timestamp(" unknown ") is None
    assert source_timestamp(" 2026-01-02T00:00:00Z ") == "2026-01-02T00:00:00Z"
    assert resource_value_key(_snapshot(key="stable-key")) == "stable-key"


def test_snapshot_serialization_preserves_safe_source_timestamp():
    """Serializable snapshots retain the source reading time for diagnostics."""
    definition = ResourceDefinition(name="Firmware version", kind="diagnostic")
    serialized = serialize_resource_snapshot(
        _snapshot(definition=definition, logged_at=" 2026-01-02T00:00:00Z ")
    )

    assert serialized is not None
    assert serialized["logged_at"] == "2026-01-02T00:00:00Z"
    assert restore_resource_snapshot(serialized) is not None
