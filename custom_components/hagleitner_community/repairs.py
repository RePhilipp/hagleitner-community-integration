"""Repairs issues for active Hagleitner maintenance conditions."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .resource_data import ResourceValueSnapshot

_REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
_FILL_STATUS_EQUIVALENT_ID = "9c336908-7a04-4adc-8bd7-08dc3d205c10"

_ISSUE_SEVERITIES = {
    "battery_low": ir.IssueSeverity.WARNING,
    "battery_empty": ir.IssueSeverity.ERROR,
    "refill_low": ir.IssueSeverity.WARNING,
    "refill_empty": ir.IssueSeverity.ERROR,
    "fill_nearly_full": ir.IssueSeverity.WARNING,
    "fill_full": ir.IssueSeverity.ERROR,
    "error_active": ir.IssueSeverity.ERROR,
    "connection_offline": ir.IssueSeverity.ERROR,
}


@callback
def async_update_maintenance_issue(
    hass: HomeAssistant,
    device_id: str,
    device_entry_id: str,
    device_name: str,
    snapshot: ResourceValueSnapshot,
) -> None:
    """Create the active issue for a resource and clear its resolved issues."""
    definition = snapshot.definition
    if definition is None:
        return
    issue_states = _issue_states(snapshot)
    if not issue_states:
        return

    registry = ir.async_get(hass)
    for issue_key, is_active in issue_states.items():
        issue_id = _issue_id(device_id, snapshot, issue_key)
        current_issue = registry.async_get_issue(DOMAIN, issue_id)
        if not is_active:
            if current_issue is not None:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
            continue
        if current_issue is not None:
            continue

        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            config_entry_id=device_entry_id,
            is_fixable=False,
            is_persistent=True,
            severity=_ISSUE_SEVERITIES[issue_key],
            translation_key=issue_key,
            translation_placeholders={
                "device_name": device_name,
                "resource_name": definition.name,
                "resource_type_id": str(snapshot.resource_type_id),
            },
        )


@callback
def async_clear_maintenance_issues(
    hass: HomeAssistant,
    device_entry_id: str,
) -> None:
    """Remove this device's issues when its config entry is removed."""
    registry = ir.async_get(hass)
    for (domain, issue_id), issue in tuple(registry.issues.items()):
        if domain == DOMAIN and issue.config_entry_id == device_entry_id:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def _issue_states(snapshot: ResourceValueSnapshot) -> dict[str, bool]:
    """Return possible issue keys and whether each is active."""
    definition = snapshot.definition
    if definition is None:
        return {}

    if definition.kind == "battery":
        return {
            "battery_low": snapshot.mapped_value == "low",
            "battery_empty": snapshot.mapped_value == "empty",
        }

    if snapshot.equivalent_id == _REFILL_STATE_EQUIVALENT_ID:
        return {
            "refill_low": snapshot.mapped_value == "low",
            "refill_empty": snapshot.mapped_value == "empty",
        }

    if snapshot.equivalent_id == _FILL_STATUS_EQUIVALENT_ID:
        return {
            "fill_nearly_full": snapshot.mapped_value == "nearly_full",
            "fill_full": snapshot.mapped_value == "full",
        }

    if definition.kind == "problem":
        return {"error_active": snapshot.mapped_value == "error"}

    if definition.kind == "connection":
        return {"connection_offline": snapshot.mapped_value == "offline"}

    return {}


def _issue_id(
    device_id: str,
    snapshot: ResourceValueSnapshot,
    issue_key: str,
) -> str:
    """Build a stable issue ID for one device resource condition."""
    return (
        f"{device_id}_{snapshot.resource_type_id}_"
        f"{snapshot.instance_number}_{issue_key}"
    )
