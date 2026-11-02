"""Device identification and initial supported-resource logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"


@dataclass(frozen=True)
class ResourceDefinition:
    """Entity mapping for one supported resource equivalent ID."""

    name: str
    kind: str
    enum_values: dict[int, Any] = field(default_factory=dict)
    device_type_enum_values: dict[str, dict[int, Any]] = field(default_factory=dict)
    battery_percent_values: dict[int, int | None] = field(default_factory=dict)


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


SUPPORTED_RESOURCES_BY_EQUIVALENT_ID: dict[str, ResourceDefinition] = {
    "84b96502-7738-43fb-f3dd-08dace26c91e": ResourceDefinition(
        name="Dispense count",
        kind="counter",
    ),
    "491d2cd9-92a0-4107-f3de-08dace26c91e": ResourceDefinition(
        name="Refill count",
        kind="counter",
    ),
    "77d144fd-d7a3-42f7-03aa-08dac1664f9a": ResourceDefinition(
        name="Energy supply status",
        kind="battery",
        enum_values={
            0: "ok",
            1: "low",
            2: "empty",
            3: "mains_adapter",
        },
        battery_percent_values={
            0: 100,
            1: 20,
            2: 0,
            3: None,
        },
    ),
    REFILL_STATE_EQUIVALENT_ID: ResourceDefinition(
        name="Refill state",
        kind="enum",
        enum_values={
            0: "full",
            1: "low",
            2: "empty",
        },
    ),
    "9a77375d-964c-451f-03ab-08dac1664f9a": ResourceDefinition(
        name="Error status",
        kind="problem",
        enum_values={
            0: "no_error",
            1: "error",
        },
    ),
    "7c178f1d-271f-4554-03ac-08dac1664f9a": ResourceDefinition(
        name="Connection status",
        kind="connection",
        enum_values={
            0: "offline",
            1: "temporarily_offline",
            2: "online",
            3: "not_connected",
        },
        device_type_enum_values={
            "gateway longrange": {
                0: "not_available",
                2: "available",
            }
        },
    ),
    "9c336908-7a04-4adc-8bd7-08dc3d205c10": ResourceDefinition(
        name="Fill status",
        kind="enum",
        enum_values={
            0: "empty",
            1: "nearly_full",
            2: "full",
        },
    ),
    "f8cdaa9a-4633-4fd4-1d0d-08de5e8412d5": ResourceDefinition(
        name="Passage counter",
        kind="counter",
    ),
}

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

            raw_value = _raw_value(resource_value)
            snapshots.append(
                ResourceValueSnapshot(
                    key=_resource_key(
                        equivalent_id,
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


def device_display_name(message: dict[str, Any]) -> str:
    """Return a translated type name for discovery, falling back to the ID."""
    device_id, _ = device_identity(message)
    device_info = _field(message, "deviceInfo", "DeviceInfo", default={}) or {}
    translations = (
        _field(
            device_info,
            "deviceTypeNameTranslations",
            "DeviceTypeNameTranslations",
            default=[],
        )
        or []
    )
    for translation in translations:
        if str(_field(translation, "languageTag", "LanguageTag", default="")).casefold() == "en":
            value = _field(translation, "value", "Value")
            if isinstance(value, str) and value:
                return f"Hagleitner {value}"
    return f"Hagleitner {device_id[:8]}"


def enum_options(
    definition: ResourceDefinition,
    device_type_names: frozenset[str],
) -> list[str]:
    """Return allowed HA enum states for the device type."""
    for device_type_name, values in definition.device_type_enum_values.items():
        if device_type_name.casefold() in device_type_names:
            return list(dict.fromkeys(values.values()))
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


def resource_value_key(snapshot: ResourceValueSnapshot) -> str:
    """Build a stable per-device key for an equivalent resource instance."""
    return snapshot.key


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
    device_type_names: set[str],
) -> Any:
    """Map known integer enums to normalized states; leave other values intact."""
    if definition is None or not isinstance(raw_value, int) or isinstance(raw_value, bool):
        return raw_value

    for device_type_name, values in definition.device_type_enum_values.items():
        if device_type_name.casefold() in device_type_names:
            return values.get(raw_value, raw_value)
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
