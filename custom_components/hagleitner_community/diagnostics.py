"""Diagnostics for the Hagleitner Community integration."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return a privacy-safe summary for one queue or adopted device."""
    domain_data = hass.data.get(DOMAIN, {})
    shared = domain_data.get("_shared_device_state", {})
    adopted_ids = shared.get("adopted_device_ids", set())
    device_sources = shared.get("device_sources", {})
    latest_values = shared.get("latest_values", {})

    if entry.data.get("entry_type") == "device":
        device_id = entry.data.get("device_id")
        device_ids = [device_id] if isinstance(device_id, str) else []
    else:
        device_ids = [
            device_id
            for device_id, source_ids in device_sources.items()
            if device_id in adopted_ids and entry.entry_id in source_ids
        ]
        for device_entry in hass.config_entries.async_entries(DOMAIN):
            if device_entry.data.get("entry_type") != "device":
                continue
            hub_ids = device_entry.data.get("hub_entry_ids", ())
            if not isinstance(hub_ids, (list, tuple, set)):
                hub_ids = ()
            if device_entry.data.get("hub_entry_id") == entry.entry_id:
                hub_ids = (*hub_ids, entry.entry_id)
            if (
                entry.entry_id in hub_ids
                and (device_id := device_entry.data.get("device_id"))
                and device_id in adopted_ids
            ):
                device_ids.append(device_id)

    device_ids = sorted(set(device_ids))
    devices = [
        {
            "device": f"Device {index}",
            "resources": _safe_resources(latest_values.get(device_id, {}).values()),
        }
        for index, device_id in enumerate(device_ids, start=1)
    ]
    diagnostics: dict[str, Any] = {
        "device_count": len(device_ids),
        "devices": devices,
    }
    return diagnostics


def _safe_resources(snapshots: Any) -> list[dict[str, Any]]:
    """Select only known resource names and values suitable for diagnostics."""
    resources = []
    for snapshot in snapshots:
        definition = snapshot.definition
        if definition is None:
            continue
        value = _safe_resource_value(snapshot, definition)
        if value is not None:
            resources.append({"name": definition.name, "value": value})
    return resources


def _safe_resource_value(snapshot: Any, definition: Any) -> Any:
    """Allow only primitive values appropriate for a known resource kind."""
    if definition.kind in ("counter", "measurement"):
        value = snapshot.raw_value
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        return None

    if definition.kind == "diagnostic" and definition.name == "Firmware version":
        value = snapshot.raw_value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._+-]{1,64}", value):
            return value
        return None

    if definition.kind == "presence":
        value = snapshot.mapped_value
        return (
            value
            if isinstance(value, str) and value in definition.enum_values.values()
            else None
        )

    allowed_values = set(definition.enum_values.values())
    value = snapshot.mapped_value
    return value if isinstance(value, str) and value in allowed_values else None
