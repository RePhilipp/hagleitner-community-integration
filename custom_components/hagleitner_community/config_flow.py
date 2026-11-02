"""Config flow for Hagleitner Community."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN


class HagleitnerCommunityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an Azure Service Bus queue."""

    VERSION = 1
    _discovery_info: dict[str, str] | None = None

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Ask for the queue connection details."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Hagleitner Community ({user_input['queue_name']})",
                data={"entry_type": "hub", **user_input},
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
        )

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, str]
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
                if key != "suggested_area_id"
            }
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

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "name": self._discovery_info["device_name"]
            },
        )
