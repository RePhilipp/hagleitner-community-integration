"""Config flow for Hagleitner Community."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN
from .device import is_valid_customer_id


class HagleitnerCommunityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an Azure Service Bus queue."""

    VERSION = 1
    _discovery_info: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Ask for the queue connection details."""
        self.context.setdefault(
            "title_placeholders", {"name": "Hagleitner Community"}
        )
        errors = {}
        if user_input is not None:
            queue_name = user_input["queue_name"].strip()
            normalized_queue_name = queue_name.casefold()
            matching_entries = [
                entry
                for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.data.get("entry_type") != "device"
                and isinstance(entry.data.get("queue_name"), str)
                and entry.data["queue_name"].strip().casefold()
                == normalized_queue_name
            ]
            if matching_entries:
                error = (
                    "queue_already_configured"
                    if any(entry.disabled_by is None for entry in matching_entries)
                    else "queue_already_configured_disabled"
                )
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Hagleitner Community ({queue_name})",
                    data={
                        "entry_type": "hub",
                        **user_input,
                        "queue_name": queue_name,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("connection_string"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required("queue_name"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> FlowResult:
        """Ask the user whether to adopt a newly detected device."""
        await self.async_set_unique_id(discovery_info["device_id"])
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info["device_name"]
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create a device entry only after user confirmation."""
        if self._discovery_info is None:
            return self.async_abort(reason="missing_discovery_info")

        if user_input is not None:
            device_data = {
                key: value
                for key, value in self._discovery_info.items()
                if key
                not in {
                    "suggested_area_id",
                    "customer_name",
                    "location_name",
                    "mount_point",
                    "customer_id",
                }
            }
            customer_id = self._discovery_info.get("customer_id")
            if is_valid_customer_id(customer_id):
                device_data["customer_id"] = customer_id
            if area_id := user_input.get("area_id"):
                device_data["area_id"] = area_id
            return self.async_create_entry(
                title=self._discovery_info["device_name"],
                data={
                    "entry_type": "device",
                    "hub_entry_ids": [self._discovery_info["hub_entry_id"]],
                    **device_data,
                },
            )

        suggested_area_id = self._discovery_info.get("suggested_area_id")
        if suggested_area_id is not None:
            from homeassistant.helpers import area_registry as ar

            if ar.async_get(self.hass).async_get_area(suggested_area_id) is None:
                suggested_area_id = None

        schema_fields = {}
        if suggested_area_id is not None:
            schema_fields[
                vol.Optional("area_id", default=suggested_area_id)
            ] = selector.AreaSelector()
        else:
            schema_fields[vol.Optional("area_id")] = selector.AreaSelector()

        placeholders = {
            "name": self._discovery_info["device_name"],
            "customer_name": self._discovery_info.get("customer_name", ""),
            "location_name": self._discovery_info.get("location_name", ""),
            "mount_point": self._discovery_info.get("mount_point", ""),
        }
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(schema_fields),
            description_placeholders=placeholders,
        )
