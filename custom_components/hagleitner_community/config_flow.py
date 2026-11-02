"""Config flow for Hagleitner Community."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

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
                    vol.Required("connection_string"): str,
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
        self, user_input: dict[str, bool] | None = None
    ) -> FlowResult:
        """Create a device entry only after user confirmation."""
        if self._discovery_info is None:
            return self.async_abort(reason="missing_discovery_info")

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info["device_name"],
                data={
                    "entry_type": "device",
                    **self._discovery_info,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": self._discovery_info["device_name"]
            },
        )
