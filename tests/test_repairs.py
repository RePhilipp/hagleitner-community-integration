"""Tests for Home Assistant repair issues."""

from __future__ import annotations

from inspect import signature

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.repairs import (
    async_clear_maintenance_issues,
    async_clear_obsolete_issues,
    async_clear_queue_not_found_issue,
    async_create_queue_not_found_issue,
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
    definition: ResourceDefinition | None,
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
            "empty",
            equivalent_id=_FILL_STATUS_EQUIVALENT_ID,
            resource_type_id=12293,
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


async def test_device_error_is_not_duplicated_as_a_repair(hass):
    """Device errors are represented by their problem binary sensor, not Repairs."""
    device_id = "device-one"
    definition = ResourceDefinition(name="Error status", kind="problem")

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _snapshot(definition, "error"),
    )

    assert ir.async_get(hass).issues == {}


async def test_connection_offline_is_reported_by_sensor_not_repairs(hass):
    """The connection-state sensor replaces the former offline Repair issue."""
    async_update_maintenance_issue(
        hass,
        "device-one",
        "Dispenser",
        _snapshot(
            ResourceDefinition(name="Connection status", kind="connection"),
            "offline",
        ),
    )

    assert ir.async_get(hass).issues == {}


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


async def test_pump_replacement_requires_both_healthy_triggers_to_clear(hass):
    """Unknown pump telemetry preserves an issue until both triggers recover."""
    device_id = "device-one"
    definition = ResourceDefinition(name="Pump replacement", kind="maintenance")
    time_trigger = _snapshot(
        definition,
        "change_required",
        resource_type_id=_REPLACEMENT_RESOURCE_TYPE_ID,
        instance_number=1,
    )
    volume_trigger = _snapshot(
        definition,
        "no_change_required",
        resource_type_id=_REPLACEMENT_RESOURCE_TYPE_ID,
        instance_number=2,
    )
    issue_id = f"{device_id}_{_REPLACEMENT_RESOURCE_TYPE_ID}_pump_pump_replacement"

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        time_trigger,
        (time_trigger, volume_trigger),
    )
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    # One healthy trigger cannot establish that the other has also recovered.
    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        volume_trigger,
        (volume_trigger,),
    )
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    healthy_time_trigger = _snapshot(
        definition,
        "no_change_required",
        resource_type_id=_REPLACEMENT_RESOURCE_TYPE_ID,
        instance_number=1,
    )
    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        volume_trigger,
        (healthy_time_trigger, volume_trigger),
    )
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_unrecognized_maintenance_values_and_resources_are_ignored(hass):
    """Only supported maintenance resources and normalized states create issues."""
    async_update_maintenance_issue(
        hass,
        "device-one",
        "Dispenser",
        _snapshot(ResourceDefinition(name="Unknown", kind="maintenance"), "unknown"),
    )
    async_update_maintenance_issue(
        hass,
        "device-one",
        "Dispenser",
        _snapshot(
            ResourceDefinition(name="Other maintenance", kind="maintenance"),
            "change_required",
            resource_type_id=99999,
        ),
    )

    assert ir.async_get(hass).issues == {}


async def test_unknown_and_missing_problem_state_do_not_create_repairs(hass):
    """Unknown status values stay non-actionable and duplicate reports are stable."""
    device_id = "device-one"
    definition = ResourceDefinition(name="Error status", kind="problem")
    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _snapshot(definition, "unrecognized-state"),
    )
    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _snapshot(None, "error"),
    )
    assert ir.async_get(hass).issues == {}

    snapshot = _snapshot(definition, "error")
    async_update_maintenance_issue(hass, device_id, "Dispenser", snapshot)
    async_update_maintenance_issue(hass, device_id, "Dispenser", snapshot)
    assert ir.async_get(hass).issues == {}


async def test_maintenance_issue_links_to_config_entry_when_supported(hass):
    """Created maintenance issues point back to their adopted-device entry."""
    device_id = "device-one"
    issue_id = f"{device_id}_{_REPLACEMENT_RESOURCE_TYPE_ID}_0_flowmeter_replacement"
    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _snapshot(
            ResourceDefinition(name="Flowmeter replacement", kind="maintenance"),
            "change_required",
            resource_type_id=_REPLACEMENT_RESOURCE_TYPE_ID,
        ),
        config_entry_id="device-entry",
    )

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    if "config_entry_id" in signature(ir.async_create_issue).parameters:
        assert issue.config_entry_id == "device-entry"


async def test_obsolete_entity_issues_are_removed(hass):
    """Old issues are removed when their conditions become device entities."""
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
    ir.async_create_issue(
        hass,
        DOMAIN,
        "device-one_1_0_connection_offline",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="connection_offline",
    )

    async_clear_obsolete_issues(hass)
    registry = ir.async_get(hass)

    assert registry.async_get_issue(DOMAIN, "device-one_12290_0_refill_empty") is None
    assert registry.async_get_issue(DOMAIN, "device-one_1_0_error_active") is None
    assert registry.async_get_issue(DOMAIN, "device-one_1_0_connection_offline") is None


async def test_removing_device_clears_only_its_repair_issues(hass):
    """Removing one adopted device leaves other devices' issues untouched."""
    definition = ResourceDefinition(name="Flowmeter replacement", kind="maintenance")
    for device_id in ("device-one", "device-two"):
        async_update_maintenance_issue(
            hass,
            device_id,
            device_id,
            _snapshot(
                definition,
                "change_required",
                resource_type_id=_REPLACEMENT_RESOURCE_TYPE_ID,
            ),
        )

    async_clear_maintenance_issues(hass, "device-one")
    registry = ir.async_get(hass)

    assert (
        registry.async_get_issue(
            DOMAIN,
            "device-one_12307_0_flowmeter_replacement",
        )
        is None
    )
    assert (
        registry.async_get_issue(
            DOMAIN,
            "device-two_12307_0_flowmeter_replacement",
        )
        is not None
    )


async def test_missing_queue_issue_is_entry_scoped_and_cleared_on_recovery(hass):
    """The actionable queue repair belongs to its hub and clears after recovery."""
    config_entry_id = "hub-entry"
    issue_id = f"queue_not_found_{config_entry_id}"

    async_create_queue_not_found_issue(hass, config_entry_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    if "config_entry_id" in signature(ir.async_create_issue).parameters:
        assert issue.config_entry_id == config_entry_id
    assert issue.translation_key == "queue_not_found"
    assert issue.severity is ir.IssueSeverity.ERROR

    async_clear_queue_not_found_issue(hass, config_entry_id)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
