"""Config flow for Hagleitner Community."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class HagleitnerCommunityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an Azure Service Bus queue."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Ask for the queue connection details."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Hagleitner Community ({user_input['queue_name']})",
                data=user_input,
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
