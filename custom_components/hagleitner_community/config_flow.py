"""Config flow for Hagleitner Community."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.helpers import selector
from probatio import Optional, Required, Schema

from .const import DOMAIN
from .device import is_valid_customer_id
from .service_bus import (
    QueueValidationError,
    async_validate_queue,
)


class HagleitnerCommunityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an Azure Service Bus queue."""

    VERSION = 1
    _discovery_info: dict[str, Any] | None = None
    _reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
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
                try:
                    await async_validate_queue(
                        user_input["connection_string"], queue_name
                    )
                except QueueValidationError as error:
                    errors["base"] = error.reason.value
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
            data_schema=Schema(
                {
                    Required("connection_string"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    Required("queue_name"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start credential replacement for an existing hub entry."""
        del entry_data
        entry_id = self.context.get("entry_id")
        if entry_id is None:
            return self.async_abort(reason="reauth_entry_not_found")
        self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_entry_not_found")
        self.context["title_placeholders"] = {"name": self._reauth_entry.title}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Validate and save replacement queue credentials."""
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_entry_not_found")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await async_validate_queue(
                    user_input["connection_string"],
                    self._reauth_entry.data["queue_name"],
                )
            except QueueValidationError as error:
                errors["base"] = error.reason.value
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates={"connection_string": user_input["connection_string"]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=Schema(
                {
                    Required("connection_string"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change the queue used by an existing hub entry."""
        entry = self._get_reconfigure_entry()
        if entry.data.get("entry_type") == "device":
            return self.async_abort(reason="reconfigure_not_supported")

        errors: dict[str, str] = {}
        if user_input is not None:
            queue_name = user_input["queue_name"].strip()
            matching_entries = [
                configured_entry
                for configured_entry in self.hass.config_entries.async_entries(DOMAIN)
                if (
                    configured_entry.entry_id != entry.entry_id
                    and configured_entry.data.get("entry_type") != "device"
                    and isinstance(configured_entry.data.get("queue_name"), str)
                    and configured_entry.data["queue_name"].strip().casefold()
                    == queue_name.casefold()
                )
            ]
            if matching_entries:
                errors["base"] = (
                    "queue_already_configured"
                    if any(
                        configured_entry.disabled_by is None
                        for configured_entry in matching_entries
                    )
                    else "queue_already_configured_disabled"
                )
            else:
                try:
                    await async_validate_queue(
                        entry.data["connection_string"], queue_name
                    )
                except QueueValidationError as error:
                    errors["base"] = error.reason.value
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        title=f"Hagleitner Community ({queue_name})",
                        data_updates={"queue_name": queue_name},
                    )

        schema = Schema({Required("queue_name"): str})
        schema = self.add_suggested_values_to_schema(
            schema,
            {"queue_name": entry.data.get("queue_name", "")},
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
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
    ) -> config_entries.ConfigFlowResult:
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
                Optional("area_id", default=suggested_area_id)
            ] = selector.AreaSelector()
        else:
            schema_fields[Optional("area_id")] = selector.AreaSelector()

        placeholders = {
            "name": self._discovery_info["device_name"],
            "customer_name": self._discovery_info.get("customer_name", ""),
            "location_name": self._discovery_info.get("location_name", ""),
            "mount_point": self._discovery_info.get("mount_point", ""),
        }
        return self.async_show_form(
            step_id="confirm",
            data_schema=Schema(schema_fields),
            description_placeholders=placeholders,
        )
