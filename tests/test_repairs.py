"""Tests for Home Assistant repair issues."""

from __future__ import annotations

from custom_components.hagleitner_community.const import DOMAIN
from custom_components.hagleitner_community.repairs import (
    async_clear_maintenance_issues,
    async_update_maintenance_issue,
)
from custom_components.hagleitner_community.resource_data import (
    REFILL_STATE_EQUIVALENT_ID,
    ResourceDefinition,
    ResourceValueSnapshot,
)
from homeassistant.helpers import issue_registry as ir


def _refill_snapshot(value: str) -> ResourceValueSnapshot:
    """Build a supported refill-state reading."""
    return ResourceValueSnapshot(
        key="12290:0",
        logged_at=None,
        resource_type_id=12290,
        instance_number=0,
        equivalent_id=REFILL_STATE_EQUIVALENT_ID,
        raw_value=value,
        mapped_value=value,
        raw_resource={},
        definition=ResourceDefinition(name="Refill state", kind="enum"),
        device_type_names=frozenset(),
    )


async def test_refill_issue_uses_current_issue_registry_api_and_clears(hass):
    """Active refill issues are created and removed when readings recover."""
    device_id = "device-one"

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _refill_snapshot("low"),
    )
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"{device_id}_12290_0_refill_low")

    assert issue is not None
    assert issue.translation_placeholders == {
        "device_name": "Dispenser",
        "resource_name": "Refill state",
        "resource_type_id": "12290",
    }

    async_update_maintenance_issue(
        hass,
        device_id,
        "Dispenser",
        _refill_snapshot("full"),
    )

    assert registry.async_get_issue(DOMAIN, f"{device_id}_12290_0_refill_low") is None


async def test_removing_device_clears_only_its_repair_issues(hass):
    """Removing one adopted device leaves other devices' issues untouched."""
    for device_id in ("device-one", "device-two"):
        async_update_maintenance_issue(
            hass,
            device_id,
            device_id,
            _refill_snapshot("low"),
        )

    async_clear_maintenance_issues(hass, "device-one")
    registry = ir.async_get(hass)

    assert registry.async_get_issue(DOMAIN, "device-one_12290_0_refill_low") is None
    assert registry.async_get_issue(DOMAIN, "device-two_12290_0_refill_low") is not None
