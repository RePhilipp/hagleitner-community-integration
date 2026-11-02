"""Device identification and initial supported-resource logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

FRAGRANCE_DISPENSER_DEVICE_TYPE_ID = "d15a2a06-5fea-43ba-1cff-08d87b4a7749"


@dataclass(frozen=True)
class ResourceDefinition:
    """Metadata for a resource that will eventually become an HA entity."""

    name: str
    platform: str
    enum_values: dict[str, Any] = field(default_factory=dict)


# The enum labels for values 0, 1, and 2 have not been confirmed yet.
SUPPORTED_RESOURCES: dict[tuple[str, int, int], ResourceDefinition] = {
    (FRAGRANCE_DISPENSER_DEVICE_TYPE_ID, 12290, 0): ResourceDefinition(
        name="Refill state",
        platform="sensor",
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

            definition = None
            if isinstance(resource_type_id, int) and isinstance(instance_number, int):
                definition = SUPPORTED_RESOURCES.get(
                    (device_type_id, resource_type_id, instance_number)
                )

            logger.info(
                "Resource value device_id=%s logged_at=%s resource_type_id=%s "
                "instance=%s supported=%s name=%s value=%s",
                device_id,
                logged_at,
                resource_type_id,
                instance_number,
                definition is not None,
                definition.name if definition else None,
                json.dumps(resource_value, ensure_ascii=False, sort_keys=True),
            )


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
