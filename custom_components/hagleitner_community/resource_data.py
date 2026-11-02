"""Device identification and initial supported-resource logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

FRAGRANCE_DISPENSER_DEVICE_TYPE_ID = "d15a2a06-5fea-43ba-1cff-08d87b4a7749"
REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"


@dataclass(frozen=True)
class ResourceDefinition:
    """Metadata for a resource that will eventually become an HA entity."""

    name: str
    platform: str
    enum_values: dict[int, Any] = field(default_factory=dict)
    device_type_enum_values: dict[str, dict[int, Any]] = field(default_factory=dict)


SUPPORTED_RESOURCES_BY_EQUIVALENT_ID: dict[str, ResourceDefinition] = {
    "84b96502-7738-43fb-f3dd-08dace26c91e": ResourceDefinition(
        name="Dispense count",
        platform="sensor",
    ),
    "491d2cd9-92a0-4107-f3de-08dace26c91e": ResourceDefinition(
        name="Refill count",
        platform="sensor",
    ),
    "77d144fd-d7a3-42f7-03aa-08dac1664f9a": ResourceDefinition(
        name="Energy supply status",
        platform="sensor",
        enum_values={
            0: "ok",
            1: "low",
            2: "empty",
            3: "mains_adapter",
        },
    ),
    REFILL_STATE_EQUIVALENT_ID: ResourceDefinition(
        name="Refill state",
        platform="sensor",
        enum_values={
            0: "full",
            1: "low",
            2: "empty",
        },
    ),
    "9a77375d-964c-451f-03ab-08dac1664f9a": ResourceDefinition(
        name="Error status",
        platform="sensor",
        enum_values={
            0: "no_error",
            1: "error",
        },
    ),
    "7c178f1d-271f-4554-03ac-08dac1664f9a": ResourceDefinition(
        name="Connection status",
        platform="sensor",
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
        platform="sensor",
        enum_values={
            0: "empty",
            1: "nearly_full",
            2: "full",
        },
    ),
    "f8cdaa9a-4633-4fd4-1d0d-08de5e8412d5": ResourceDefinition(
        name="Passage counter",
        platform="sensor",
    ),
}

SUPPORTED_RESOURCES_BY_DEVICE_RESOURCE: dict[
    tuple[str, int, int], ResourceDefinition
] = {
    (FRAGRANCE_DISPENSER_DEVICE_TYPE_ID, 12290, 0): ResourceDefinition(
        name="Refill state",
        platform="sensor",
        enum_values={
            0: "full",
            1: "low",
            2: "empty",
        },
    )
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
    """Log each resource value, flagging identifiers in the supported catalog."""
    device_id, device_type_id = device_identity(message)
    device_info = _field(message, "deviceInfo", "DeviceInfo", default={}) or {}
    device_type_names = _device_type_names(device_info)

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
            equivalent_id = _field(
                identifier,
                "resourceInstanceEquivalentId",
                "ResourceInstanceEquivalentId",
            )

            definition = None
            if isinstance(equivalent_id, str):
                definition = SUPPORTED_RESOURCES_BY_EQUIVALENT_ID.get(
                    equivalent_id.lower()
                )

            if isinstance(resource_type_id, int) and isinstance(instance_number, int):
                definition = definition or SUPPORTED_RESOURCES_BY_DEVICE_RESOURCE.get(
                    (device_type_id, resource_type_id, instance_number)
                )
            raw_value = _raw_value(resource_value)
            mapped_value = _mapped_value(
                raw_value,
                definition,
                device_type_names,
            )

            logger.info(
                "Resource value device_id=%s logged_at=%s resource_type_id=%s "
                "instance=%s equivalent_id=%s device_type_id=%s "
                "supported=%s name=%s mapped_value=%s value=%s",
                device_id,
                logged_at,
                resource_type_id,
                instance_number,
                equivalent_id,
                device_type_id,
                definition is not None,
                definition.name if definition else None,
                mapped_value,
                json.dumps(resource_value, ensure_ascii=False, sort_keys=True),
            )


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
