"""Device identification and initial supported-resource logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from homeassistant.const import EntityCategory

REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"


@dataclass(frozen=True)
class ResourceDefinition:
    """Entity mapping for a supported resource identifier."""

    name: str
    kind: str
    entity_translation_key: str | None = None
    device_class: str | None = None
    unit: str | None = None
    enum_values: dict[int, Any] = field(default_factory=dict)
    battery_percent_values: dict[int, int | None] = field(default_factory=dict)
    problem_entity_on_values: tuple[str, ...] = ()
    problem_entity_translation_key: str | None = None
    problem_entity_unique_id_suffix: str | None = None
    entity_category: EntityCategory | None = None
    entity_registry_enabled_default: bool = True


@dataclass(frozen=True)
class ResourceValueSnapshot:
    """Latest values and identifiers for one wire-format resource value."""

    key: str
    logged_at: Any
    resource_type_id: Any
    instance_number: Any
    equivalent_id: str | None
    raw_value: Any
    mapped_value: Any
    raw_resource: dict[str, Any]
    definition: ResourceDefinition | None
    device_type_names: frozenset[str]


@dataclass(frozen=True)
class DeviceMetadata:
    """Customer and location details carried alongside resource messages."""

    customer_name: str | None = None
    customer_id: int | None = None
    location: str | None = None
    mount_point: str | None = None
    innermost_location: str | None = None


SUPPORTED_RESOURCES_BY_EQUIVALENT_ID: dict[str, ResourceDefinition] = {
    "84b96502-7738-43fb-f3dd-08dace26c91e": ResourceDefinition(
        name="Dispense count",
        kind="counter",
        entity_translation_key="dispense_count",
        entity_category=None,
        entity_registry_enabled_default=True,
    ),
    "491d2cd9-92a0-4107-f3de-08dace26c91e": ResourceDefinition(
        name="Refill count",
        kind="counter",
        entity_translation_key="refill_count",
        entity_category=None,
        entity_registry_enabled_default=True,
    ),
    "f8cdaa9a-4633-4fd4-1d0d-08de5e8412d5": ResourceDefinition(
        name="Passage count",
        kind="counter",
        entity_translation_key="passage_count",
        entity_category=None,
        entity_registry_enabled_default=True,
    ),
    "77d144fd-d7a3-42f7-03aa-08dac1664f9a": ResourceDefinition(
        name="Energy supply status",
        kind="battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        enum_values={
            0: "ok",
            1: "low",
            2: "low",
            3: "mains_adapter",
        },
        battery_percent_values={
            0: 100,
            1: 20,
            2: 20,
            3: None,
        },
    ),
    REFILL_STATE_EQUIVALENT_ID: ResourceDefinition(
        name="Refill state",
        kind="enum",
        entity_translation_key="refill_state",
        entity_category=None,
        entity_registry_enabled_default=True,
        enum_values={
            0: "full",
            1: "low",
            2: "empty",
        },
        problem_entity_on_values=("low", "empty"),
        problem_entity_translation_key="refill_warning",
        problem_entity_unique_id_suffix="refill_empty",
    ),
    "9a77375d-964c-451f-03ab-08dac1664f9a": ResourceDefinition(
        name="Error status",
        kind="problem",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        enum_values={
            0: "no_error",
            1: "error",
        },
        problem_entity_on_values=("error",),
        problem_entity_translation_key="device_error",
        problem_entity_unique_id_suffix="device_error",
    ),
    "7c178f1d-271f-4554-03ac-08dac1664f9a": ResourceDefinition(
        name="Connection status",
        kind="connection",
        entity_translation_key="connection_status",
        entity_category=None,
        entity_registry_enabled_default=True,
        enum_values={
            0: "offline",
            1: "temporarily_offline",
            2: "online",
            3: "not_connected",
        },
    ),
    "9c336908-7a04-4adc-8bd7-08dc3d205c10": ResourceDefinition(
        name="Fill status",
        kind="enum",
        entity_translation_key="fill_status",
        entity_category=None,
        entity_registry_enabled_default=True,
        enum_values={
            0: "empty",
            1: "nearly_full",
            2: "full",
        },
        problem_entity_on_values=("nearly_full", "full"),
        problem_entity_translation_key="fill_warning",
        problem_entity_unique_id_suffix="refill_empty",
    ),
}

SUPPORTED_RESOURCES_BY_TYPE_INSTANCE: dict[
    tuple[int, int], ResourceDefinition
] = {
    (3, 0): ResourceDefinition(
        name="Firmware version",
        kind="diagnostic",
        entity_translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    (28680, 0): ResourceDefinition(
        name="Total delivery volume",
        kind="counter",
        entity_translation_key="total_delivery_volume",
        entity_category=None,
        entity_registry_enabled_default=True,
        device_class="volume",
        unit="milliliters",
    ),
    (28682, 0): ResourceDefinition(
        name="Total dispensed water volume",
        kind="counter",
        entity_translation_key="total_dispensed_water_volume",
        entity_category=None,
        entity_registry_enabled_default=True,
        device_class="volume",
        unit="liters",
    ),
    (45058, 0): ResourceDefinition(
        name="Online ratio",
        kind="measurement",
        entity_translation_key="online_ratio",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        unit="percentage",
    ),
    (45060, 0): ResourceDefinition(
        name="Data-link expectation",
        kind="enum",
        entity_translation_key="data_link_expectation",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        enum_values={
            0: "hard_offline",
            1: "soft_offline",
            2: "online",
        },
    ),
    (12289, 0): ResourceDefinition(
        name="Cover state",
        kind="opening",
        entity_translation_key="cover_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        enum_values={
            0: "opened",
            1: "closed",
        },
    ),
    (20486, 0): ResourceDefinition(
        name="Number of openings",
        kind="counter",
        entity_translation_key="number_of_openings",
        entity_category=None,
        entity_registry_enabled_default=True,
    ),
    (20485, 0): ResourceDefinition(
        name="Passage count",
        kind="counter",
        entity_translation_key="passage_count",
        entity_category=None,
        entity_registry_enabled_default=True,
    ),
    (20485, 1): ResourceDefinition(
        name="People count",
        kind="counter",
        entity_translation_key="people_count",
        entity_category=None,
        entity_registry_enabled_default=True,
    ),
    (12307, 0): ResourceDefinition(
        name="Flowmeter change required (volume-based)",
        kind="maintenance",
        entity_category=None,
        entity_registry_enabled_default=True,
        enum_values={
            0: "no_change_required",
            1: "change_required",
        },
    ),
    (12307, 1): ResourceDefinition(
        name="Pump change required (time-based)",
        kind="maintenance",
        entity_category=None,
        entity_registry_enabled_default=True,
        enum_values={
            0: "no_change_required",
            1: "change_required",
        },
    ),
    (12307, 2): ResourceDefinition(
        name="Pump change required (volume-based)",
        kind="maintenance",
        entity_category=None,
        entity_registry_enabled_default=True,
        enum_values={
            0: "no_change_required",
            1: "change_required",
        },
    ),
}


def parse_device_metadata(message: dict[str, Any]) -> DeviceMetadata:
    """Extract customer and location details from a resource-data message."""
    customer_info = (
        _field(message, "customerInfo", "CustomerInfo", default={}) or {}
    )
    if not isinstance(customer_info, dict):
        customer_info = {}
    name_parts = []
    for field in ("name1", "name2", "name3", "name4"):
        value = _field(customer_info, field, field.title())
        if isinstance(value, str) and value.strip():
            name_parts.append(value.strip())

    customer_id = _field(customer_info, "customerId", "CustomerId")
    if not isinstance(customer_id, int) or isinstance(customer_id, bool):
        customer_id = None

    location_info = (
        _field(message, "locationInfo", "LocationInfo", default={}) or {}
    )
    if not isinstance(location_info, dict):
        location_info = {}
    locations = _field(location_info, "locations", "Locations", default=[]) or []
    if not isinstance(locations, list):
        locations = []
    location_names = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        name = _field(location, "name", "Name")
        if isinstance(name, str) and name.strip():
            location_names.append(name.strip())

    mount_point = _field(location_info, "mountPoint", "MountPoint")
    if not isinstance(mount_point, str) or not mount_point.strip():
        mount_point = None
    else:
        mount_point = mount_point.strip()

    return DeviceMetadata(
        customer_name=" ".join(name_parts) or None,
        customer_id=customer_id,
        location=" / ".join(location_names) or None,
        mount_point=mount_point,
        innermost_location=location_names[-1] if location_names else None,
    )


def merge_device_metadata(
    current: DeviceMetadata,
    incoming: DeviceMetadata,
) -> DeviceMetadata:
    """Retain previously received metadata when a message omits a field."""
    return DeviceMetadata(
        customer_name=incoming.customer_name or current.customer_name,
        customer_id=(
            incoming.customer_id
            if incoming.customer_id is not None
            else current.customer_id
        ),
        location=incoming.location or current.location,
        mount_point=incoming.mount_point or current.mount_point,
        innermost_location=(
            incoming.innermost_location or current.innermost_location
        ),
    )


def device_identity(message: dict[str, Any]) -> tuple[str, str]:
    """Return the device ID and device type ID from a wire-format message."""
    device_info = _field(message, "deviceInfo", "DeviceInfo")
    if not isinstance(device_info, dict):
        raise ValueError("Resource-data message has no DeviceInfo object")

    device_id = _field(device_info, "deviceId", "DeviceId")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Resource-data message has no DeviceInfo.DeviceId")

    device_type_id = _field(device_info, "deviceTypeId", "DeviceTypeId", default="")
    return device_id, str(device_type_id).lower()


def device_type_name(message: dict[str, Any]) -> str | None:
    """Return the English translated device type name, when supplied."""
    device_info = _field(message, "deviceInfo", "DeviceInfo", default={}) or {}
    if not isinstance(device_info, dict):
        return None
    translations = _field(
        device_info,
        "deviceTypeNameTranslations",
        "DeviceTypeNameTranslations",
        default=[],
    )
    if not isinstance(translations, list):
        return None
    for translation in translations:
        if not isinstance(translation, dict):
            continue
        language_tag = _field(translation, "languageTag", "LanguageTag", default="")
        value = _field(translation, "value", "Value")
        if (
            isinstance(language_tag, str)
            and language_tag.casefold() == "en"
            and isinstance(value, str)
            and value.strip()
        ):
            value = value.strip()
            try:
                UUID(value)
            except ValueError:
                return value
    return None


def log_resource_values(message: dict[str, Any], logger: logging.Logger) -> None:
    """Log raw and normalized values for every resource in a message."""
    device_id, device_type_id = device_identity(message)
    for snapshot in resource_value_snapshots(message):
        logger.info(
            "Resource value device_id=%s logged_at=%s resource_type_id=%s "
            "instance=%s equivalent_id=%s device_type_id=%s "
            "supported=%s name=%s mapped_value=%s value=%s",
            device_id,
            snapshot.logged_at,
            snapshot.resource_type_id,
            snapshot.instance_number,
            snapshot.equivalent_id,
            device_type_id,
            snapshot.definition is not None,
            snapshot.definition.name if snapshot.definition else None,
            snapshot.mapped_value,
            json.dumps(snapshot.raw_resource, ensure_ascii=False, sort_keys=True),
        )


def resource_value_snapshots(
    message: dict[str, Any],
) -> list[ResourceValueSnapshot]:
    """Extract resource values and their best available mapping metadata."""
    device_identity(message)
    device_info = _field(message, "deviceInfo", "DeviceInfo", default={}) or {}
    device_type_names = frozenset(_device_type_names(device_info))
    snapshots = []

    for reading in _field(message, "readings", "Readings", default=[]) or []:
        logged_at = _field(reading, "loggedAt", "LoggedAt", default="unknown")
        values = _field(reading, "resourceValues", "ResourceValues", default=[]) or []
        for resource_value in values:
            identifier = (
                _field(
                    resource_value,
                    "resourceIdentifier",
                    "ResourceIdentifier",
                    default={},
                )
                or {}
            )
            resource_type_id = _field(
                identifier, "resourceTypeId", "ResourceTypeId"
            )
            instance_number = _field(
                identifier, "resourceInstanceNo", "ResourceInstanceNo"
            )
            equivalent_id_value = _field(
                identifier,
                "resourceInstanceEquivalentId",
                "ResourceInstanceEquivalentId",
            )
            equivalent_id = (
                equivalent_id_value.lower()
                if isinstance(equivalent_id_value, str)
                else None
            )
            definition = (
                SUPPORTED_RESOURCES_BY_EQUIVALENT_ID.get(equivalent_id)
                if equivalent_id
                else None
            )
            key_equivalent_id = equivalent_id
            if definition is None:
                definition = SUPPORTED_RESOURCES_BY_TYPE_INSTANCE.get(
                    (resource_type_id, instance_number)
                )
                if definition is not None:
                    key_equivalent_id = None

            raw_value = _raw_value(resource_value)
            snapshots.append(
                ResourceValueSnapshot(
                    key=_resource_key(
                        key_equivalent_id,
                        resource_type_id,
                        instance_number,
                    ),
                    logged_at=logged_at,
                    resource_type_id=resource_type_id,
                    instance_number=instance_number,
                    equivalent_id=equivalent_id,
                    raw_value=raw_value,
                    mapped_value=_mapped_value(
                        raw_value,
                        definition,
                        device_type_names,
                    ),
                    raw_resource=resource_value,
                    definition=definition,
                    device_type_names=device_type_names,
                )
            )
    return snapshots


def serialize_resource_snapshot(
    snapshot: ResourceValueSnapshot,
) -> dict[str, Any] | None:
    """Return the minimal JSON-safe state needed to restore a resource."""
    if (
        snapshot.definition is None
        or not isinstance(snapshot.resource_type_id, int)
        or isinstance(snapshot.resource_type_id, bool)
        or not isinstance(snapshot.instance_number, int)
        or isinstance(snapshot.instance_number, bool)
        or not (
            snapshot.raw_value is None
            or isinstance(snapshot.raw_value, (str, int, bool))
        )
    ):
        return None

    return {
        "resource_type_id": snapshot.resource_type_id,
        "instance_number": snapshot.instance_number,
        "equivalent_id": snapshot.equivalent_id,
        "raw_value": snapshot.raw_value,
        "logged_at": source_timestamp(snapshot.logged_at),
        "device_type_names": sorted(snapshot.device_type_names),
    }


def restore_resource_snapshot(data: Any) -> ResourceValueSnapshot | None:
    """Rebuild a supported resource snapshot from stored primitive values."""
    if not isinstance(data, dict):
        return None

    resource_type_id = data.get("resource_type_id")
    instance_number = data.get("instance_number")
    if (
        not isinstance(resource_type_id, int)
        or isinstance(resource_type_id, bool)
        or not isinstance(instance_number, int)
        or isinstance(instance_number, bool)
    ):
        return None

    raw_value = data.get("raw_value")
    if raw_value is not None and not isinstance(raw_value, (str, int, bool)):
        return None

    equivalent_id = data.get("equivalent_id")
    if not isinstance(equivalent_id, str):
        equivalent_id = None
    else:
        equivalent_id = equivalent_id.lower()

    stored_names = data.get("device_type_names", [])
    if not isinstance(stored_names, (list, tuple, set)):
        stored_names = []
    device_type_names = frozenset(
        name.strip().casefold()
        for name in stored_names
        if isinstance(name, str) and name.strip()
    )
    definition = (
        SUPPORTED_RESOURCES_BY_EQUIVALENT_ID.get(equivalent_id)
        if equivalent_id is not None
        else None
    )
    key_equivalent_id = equivalent_id
    if definition is None:
        definition = SUPPORTED_RESOURCES_BY_TYPE_INSTANCE.get(
            (resource_type_id, instance_number)
        )
        key_equivalent_id = None
    if definition is None:
        return None

    logged_at = data.get("logged_at")
    if not isinstance(logged_at, str) or not logged_at.strip():
        logged_at = "unknown"

    return ResourceValueSnapshot(
        key=_resource_key(
            key_equivalent_id,
            resource_type_id,
            instance_number,
        ),
        logged_at=logged_at,
        resource_type_id=resource_type_id,
        instance_number=instance_number,
        equivalent_id=equivalent_id,
        raw_value=raw_value,
        mapped_value=_mapped_value(raw_value, definition, device_type_names),
        raw_resource={},
        definition=definition,
        device_type_names=device_type_names,
    )


def device_display_name(message: dict[str, Any]) -> str:
    """Return the translated device type with its known mount point."""
    device_id, _ = device_identity(message)
    display_name = device_type_name(message) or f"Hagleitner {device_id[:8]}"
    mount_point = parse_device_metadata(message).mount_point
    if mount_point:
        return f"{display_name} {mount_point}"
    return display_name


def enum_options(
    definition: ResourceDefinition,
    device_type_names: frozenset[str],
) -> list[str]:
    """Return allowed HA enum states for the device type."""
    return list(dict.fromkeys(definition.enum_values.values()))


def battery_percentage(
    snapshot: ResourceValueSnapshot,
) -> int | None:
    """Convert energy-supply enums to a battery percentage where applicable."""
    if snapshot.definition is None or snapshot.definition.kind != "battery":
        return None
    if not isinstance(snapshot.raw_value, int) or isinstance(snapshot.raw_value, bool):
        return None
    return snapshot.definition.battery_percent_values.get(snapshot.raw_value)


def source_timestamp(logged_at: Any) -> str | None:
    """Return the reading's source timestamp for entity attributes."""
    if isinstance(logged_at, datetime):
        return logged_at.isoformat()
    if isinstance(logged_at, str) and logged_at.strip().casefold() != "unknown":
        return logged_at.strip()
    return None


def should_accept_reading(
    incoming: ResourceValueSnapshot,
    current: ResourceValueSnapshot,
) -> bool:
    """Reject older readings when both timestamps can be compared."""
    current_time = _parse_timestamp(current.logged_at)
    if current_time is None:
        return True

    incoming_time = _parse_timestamp(incoming.logged_at)
    return incoming_time is not None and incoming_time >= current_time


def resource_value_key(snapshot: ResourceValueSnapshot) -> str:
    """Build a stable per-device key for an equivalent resource instance."""
    return snapshot.key


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a source timestamp, treating timezone-naive values as UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resource_key(
    equivalent_id: str | None,
    resource_type_id: Any,
    instance_number: Any,
) -> str:
    """Classify by equivalent ID but keep distinct type/instance entities apart."""
    if equivalent_id is not None:
        return f"{equivalent_id}:{resource_type_id}:{instance_number}"
    return f"{resource_type_id}:{instance_number}"


def _device_type_names(device_info: dict[str, Any]) -> set[str]:
    """Collect translated device-type names for narrowly scoped enum overrides."""
    names: set[str] = set()
    for translations_field in (
        "deviceTypeNameTranslations",
        "DeviceTypeNameTranslations",
        "deviceTypeNameAliasTranslations",
        "DeviceTypeNameAliasTranslations",
    ):
        translations = device_info.get(translations_field) or []
        for translation in translations:
            value = _field(translation, "value", "Value")
            if isinstance(value, str):
                names.add(value.strip().casefold())
    return names


def _raw_value(resource_value: dict[str, Any]) -> Any:
    """Return the one populated typed value from a ResourceValue."""
    for field in ("stringValue", "integerValue", "booleanValue"):
        value = _field(resource_value, field, field[0].upper() + field[1:])
        if value is not None:
            return value
    return None


def _mapped_value(
    raw_value: Any,
    definition: ResourceDefinition | None,
    device_type_names: frozenset[str],
) -> Any:
    """Map known integer enums to normalized states; leave other values intact."""
    if definition is None or not isinstance(raw_value, int) or isinstance(raw_value, bool):
        return raw_value

    return definition.enum_values.get(raw_value, raw_value)


def _field(
    value: dict[str, Any],
    camel_case: str,
    pascal_case: str,
    default: Any = None,
) -> Any:
    """Read either the JSON camel-case property or CLR property spelling."""
    if camel_case in value:
        return value[camel_case]
    return value.get(pascal_case, default)
