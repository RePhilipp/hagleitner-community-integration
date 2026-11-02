"""Repairs issues for active Hagleitner maintenance conditions."""

from __future__ import annotations

from enum import Enum

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .resource_data import ResourceValueSnapshot

_REFILL_STATE_EQUIVALENT_ID = "4b963ce8-14f4-4f90-03a9-08dac1664f9a"
_FILL_STATUS_EQUIVALENT_ID = "9c336908-7a04-4adc-8bd7-08dc3d205c10"
_REPLACEMENT_RESOURCE_TYPE_ID = 12307


class _IssueState(Enum):
    """Whether a maintenance issue is active, resolved, or not interpretable."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


_ISSUE_SEVERITIES = {
    "battery_low": ir.IssueSeverity.WARNING,
    "battery_empty": ir.IssueSeverity.ERROR,
    "refill_low": ir.IssueSeverity.WARNING,
    "refill_empty": ir.IssueSeverity.ERROR,
    "fill_nearly_full": ir.IssueSeverity.WARNING,
    "fill_full": ir.IssueSeverity.ERROR,
    "error_active": ir.IssueSeverity.ERROR,
    "connection_offline": ir.IssueSeverity.ERROR,
    "flowmeter_replacement": ir.IssueSeverity.WARNING,
    "pump_replacement": ir.IssueSeverity.WARNING,
}


@callback
def async_update_maintenance_issue(
    hass: HomeAssistant,
    device_id: str,
    device_entry_id: str,
    device_name: str,
    snapshot: ResourceValueSnapshot,
    device_snapshots: tuple[ResourceValueSnapshot, ...] = (),
) -> None:
    """Create the active issue for a resource and clear its resolved issues."""
    definition = snapshot.definition
    if definition is None:
        return
    issue_states = _issue_states(snapshot, device_snapshots)
    if not issue_states:
        return

    registry = ir.async_get(hass)
    for issue_key, state in issue_states.items():
        if state is _IssueState.UNKNOWN:
            continue

        issue_id = _issue_id(device_id, snapshot, issue_key)
        current_issue = registry.async_get_issue(DOMAIN, issue_id)
        if state is _IssueState.INACTIVE:
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


def _issue_states(
    snapshot: ResourceValueSnapshot,
    device_snapshots: tuple[ResourceValueSnapshot, ...] = (),
) -> dict[str, _IssueState]:
    """Return each issue's active, recognized-healthy, or unknown state."""
    definition = snapshot.definition
    if definition is None:
        return {}

    if definition.kind == "battery":
        return {
            "battery_low": _issue_state(
                snapshot.mapped_value, "low", ("ok", "empty", "mains_adapter")
            ),
            "battery_empty": _issue_state(
                snapshot.mapped_value, "empty", ("ok", "low", "mains_adapter")
            ),
        }

    if snapshot.equivalent_id == _REFILL_STATE_EQUIVALENT_ID:
        return {
            "refill_low": _issue_state(
                snapshot.mapped_value, "low", ("full", "empty")
            ),
            "refill_empty": _issue_state(
                snapshot.mapped_value, "empty", ("full", "low")
            ),
        }

    if snapshot.equivalent_id == _FILL_STATUS_EQUIVALENT_ID:
        return {
            "fill_nearly_full": _issue_state(
                snapshot.mapped_value, "nearly_full", ("empty", "full")
            ),
            "fill_full": _issue_state(
                snapshot.mapped_value, "full", ("empty", "nearly_full")
            ),
        }

    if definition.kind == "problem":
        return {
            "error_active": _issue_state(snapshot.mapped_value, "error", ("no_error",))
        }

    if definition.kind == "connection":
        return {
            "connection_offline": _issue_state(
                snapshot.mapped_value,
                "offline",
                (
                    "temporarily_offline",
                    "online",
                    "not_connected",
                    "not_available",
                    "available",
                ),
            )
        }

    if definition.kind == "maintenance":
        if snapshot.resource_type_id != _REPLACEMENT_RESOURCE_TYPE_ID:
            return {}
        if snapshot.instance_number == 0:
            return {
                "flowmeter_replacement": _issue_state(
                    snapshot.mapped_value,
                    "change_required",
                    ("no_change_required",),
                )
            }
        if snapshot.instance_number in (1, 2):
            return {
                "pump_replacement": _pump_replacement_state(device_snapshots)
            }

    return {}


def _pump_replacement_state(
    device_snapshots: tuple[ResourceValueSnapshot, ...],
) -> _IssueState:
    """Combine the pump's time- and volume-based replacement triggers."""
    trigger_values = {
        snapshot.instance_number: snapshot.mapped_value
        for snapshot in device_snapshots
        if (
            snapshot.resource_type_id == _REPLACEMENT_RESOURCE_TYPE_ID
            and snapshot.instance_number in (1, 2)
        )
    }
    if "change_required" in trigger_values.values():
        return _IssueState.ACTIVE
    if all(
        trigger_values.get(instance_number) == "no_change_required"
        for instance_number in (1, 2)
    ):
        return _IssueState.INACTIVE
    return _IssueState.UNKNOWN


def _issue_state(
    value: object,
    active_value: str,
    healthy_values: tuple[str, ...],
) -> _IssueState:
    """Interpret only the condition and explicitly healthy normalized values."""
    if value == active_value:
        return _IssueState.ACTIVE
    if value in healthy_values:
        return _IssueState.INACTIVE
    return _IssueState.UNKNOWN


def _issue_id(
    device_id: str,
    snapshot: ResourceValueSnapshot,
    issue_key: str,
) -> str:
    """Build a stable issue ID for one device resource condition."""
    instance_number = (
        "pump" if issue_key == "pump_replacement" else snapshot.instance_number
    )
    return (
        f"{device_id}_{snapshot.resource_type_id}_"
        f"{instance_number}_{issue_key}"
    )
