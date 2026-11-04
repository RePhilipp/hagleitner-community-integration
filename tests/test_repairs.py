"""Tests for Home Assistant repair issues."""

from __future__ import annotations

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.repairs import (
    async_clear_maintenance_issues,
    async_clear_obsolete_consumable_issues,
    async_update_maintenance_issue,
)
from custom_components.hagleitner_community.resource_data import (
    REFILL_STATE_EQUIVALENT_ID,
    ResourceDefinition,
    ResourceValueSnapshot,
)
from homeassistant.helpers import issue_registry as ir

_FILL_STATUS_EQUIVALENT_ID = "9c336908-7a04-4adc-8bd7-08dc3d205c10"
_REPLACEMENT_RESOURCE_TYPE_ID = 12307


def _snapshot(
    definition: ResourceDefinition,
    value: str,
    *,
    equivalent_id: str | None = None,
    resource_type_id: int = 1,
    instance_number: int = 0,
) -> ResourceValueSnapshot:
    """Build a resource reading for repair tests."""
    return ResourceValueSnapshot(
        key=f"{resource_type_id}:{instance_number}",
        logged_at=None,
        resource_type_id=resource_type_id,
        instance_number=instance_number,
        equivalent_id=equivalent_id,
        raw_value=value,
        mapped_value=value,
        raw_resource={},
        definition=definition,
        device_type_names=frozenset(),
    )


async def test_consumable_states_do_not_create_repairs(hass):
    """Battery and refill/fill levels remain device entities, not Repairs."""
    snapshots = (
        _snapshot(ResourceDefinition(name="Battery", kind="battery"), "empty"),
        _snapshot(
            ResourceDefinition(name="Refill state", kind="enum"),
            "empty",
            equivalent_id=REFILL_STATE_EQUIVALENT_ID,
        ),
        _snapshot(
            ResourceDefinition(name="Fill status", kind="enum"),
            "full",
            equivalent_id=_FILL_STATUS_EQUIVALENT_ID,
        ),
    )

    for snapshot in snapshots:
        async_update_maintenance_issue(
            hass,
            "device-one",
            "Dispenser",
            snapshot,
        )

    assert ir.async_get(hass).issues == {}


async def test_device_error_is_created_and_cleared_after_recovery(hass):
    """Actual device faults continue to create and clear Repairs issues."""
    device_id = "device-one"
    definition = ResourceDefinition(name="Error status", kind="problem")
    issue_id = f"{device_id}_1_0_error_active"

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _snapshot(definition, "error"),
    )

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _snapshot(definition, "no_error"),
    )

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_component_replacement_still_creates_maintenance_repair(hass):
    """A device-reported component replacement threshold remains actionable."""
    device_id = "device-one"
    snapshot = _snapshot(
        ResourceDefinition(name="Replacement status", kind="maintenance"),
        "change_required",
        resource_type_id=_REPLACEMENT_RESOURCE_TYPE_ID,
    )
    issue_id = f"{device_id}_{_REPLACEMENT_RESOURCE_TYPE_ID}_0_flowmeter_replacement"

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        snapshot,
    )

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING


async def test_obsolete_consumable_repairs_are_removed(hass):
    """Old persistent consumable issues are cleaned up on integration setup."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        "device-one_12290_0_refill_empty",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="refill_empty",
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        "device-one_1_0_error_active",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="error_active",
    )

    async_clear_obsolete_consumable_issues(hass)
    registry = ir.async_get(hass)

    assert registry.async_get_issue(DOMAIN, "device-one_12290_0_refill_empty") is None
    assert registry.async_get_issue(DOMAIN, "device-one_1_0_error_active") is not None


async def test_removing_device_clears_only_its_repair_issues(hass):
    """Removing one adopted device leaves other devices' issues untouched."""
    definition = ResourceDefinition(name="Error status", kind="problem")
    for device_id in ("device-one", "device-two"):
        async_update_maintenance_issue(
            hass,
            device_id,
            device_id,
            _snapshot(definition, "error"),
        )

    async_clear_maintenance_issues(hass, "device-one")
    registry = ir.async_get(hass)

    assert registry.async_get_issue(DOMAIN, "device-one_1_0_error_active") is None
    assert registry.async_get_issue(DOMAIN, "device-two_1_0_error_active") is not None
