"""Repairs issues for active Hagleitner maintenance conditions."""

from __future__ import annotations

from enum import Enum
from inspect import signature
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .resource_data import ResourceValueSnapshot

_REPLACEMENT_RESOURCE_TYPE_ID = 12307
_OBSOLETE_CONSUMABLE_ISSUE_KEYS = (
    "battery_low",
    "battery_empty",
    "refill_low",
    "refill_empty",
    "fill_nearly_full",
    "fill_full",
)
_QUEUE_NOT_FOUND_ISSUE_PREFIX = "queue_not_found_"


class _IssueState(Enum):
    """Whether a maintenance issue is active, resolved, or not interpretable."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


_ISSUE_SEVERITIES = {
    "flowmeter_replacement": ir.IssueSeverity.WARNING,
    "pump_replacement": ir.IssueSeverity.WARNING,
}


@callback
def async_update_maintenance_issue(
    hass: HomeAssistant,
    device_id: str,
    device_name: str,
    snapshot: ResourceValueSnapshot,
    device_snapshots: tuple[ResourceValueSnapshot, ...] = (),
    config_entry_id: str | None = None,
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
            is_fixable=False,
            is_persistent=True,
            severity=_ISSUE_SEVERITIES[issue_key],
            translation_key=issue_key,
            translation_placeholders={
                "device_name": device_name,
                "resource_name": definition.name,
                "resource_type_id": str(snapshot.resource_type_id),
            },
            **_config_entry_issue_kwargs(config_entry_id),
        )


@callback
def async_clear_maintenance_issues(
    hass: HomeAssistant,
    device_id: str,
) -> None:
    """Remove this device's issues when its config entry is removed."""
    registry = ir.async_get(hass)
    device_issue_prefix = f"{device_id}_"
    for domain, issue_id in tuple(registry.issues):
        if domain == DOMAIN and issue_id.startswith(device_issue_prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_clear_obsolete_issues(hass: HomeAssistant) -> None:
    """Remove old issues for conditions now exposed as device entities."""
    registry = ir.async_get(hass)
    obsolete_suffixes = tuple(
        f"_{issue_key}"
        for issue_key in (
            *_OBSOLETE_CONSUMABLE_ISSUE_KEYS,
            "error_active",
            "connection_offline",
        )
    )
    for domain, issue_id in tuple(registry.issues):
        if domain == DOMAIN and issue_id.endswith(obsolete_suffixes):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_create_queue_not_found_issue(
    hass: HomeAssistant,
    config_entry_id: str,
) -> None:
    """Explain how to fix a hub entry that points at a missing queue."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{_QUEUE_NOT_FOUND_ISSUE_PREFIX}{config_entry_id}",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="queue_not_found",
        **_config_entry_issue_kwargs(config_entry_id),
    )


@callback
def async_clear_queue_not_found_issue(
    hass: HomeAssistant,
    config_entry_id: str,
) -> None:
    """Clear the missing-queue issue after setup validates successfully."""
    ir.async_delete_issue(
        hass,
        DOMAIN,
        f"{_QUEUE_NOT_FOUND_ISSUE_PREFIX}{config_entry_id}",
    )


def _config_entry_issue_kwargs(
    config_entry_id: str | None,
) -> dict[str, Any]:
    """Link an issue to its config entry on Home Assistant versions that support it."""
    if (
        config_entry_id is not None
        and "config_entry_id" in signature(ir.async_create_issue).parameters
    ):
        return {"config_entry_id": config_entry_id}
    return {}


def _issue_states(
    snapshot: ResourceValueSnapshot,
    device_snapshots: tuple[ResourceValueSnapshot, ...] = (),
) -> dict[str, _IssueState]:
    """Return each issue's active, recognized-healthy, or unknown state."""
    definition = snapshot.definition
    if definition is None:
        return {}

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
