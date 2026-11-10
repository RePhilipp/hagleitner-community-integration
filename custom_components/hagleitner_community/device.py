"""Helpers for Hagleitner device metadata."""

from __future__ import annotations

from urllib.parse import urlencode
from uuid import UUID

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

MANUFACTURER = "HAGLEITNER Hygiene International GmbH"
_HSM_DEVICE_LOCATIONS_URL = "https://hsm.hygieneportal.com/devices/locations"


def device_model_id(device_type_id: object) -> str | None:
    """Return a normalized model ID only for a valid device-type GUID."""
    if not isinstance(device_type_id, str) or not device_type_id.strip():
        return None
    value = device_type_id.strip()
    try:
        return str(UUID(value))
    except ValueError:
        return None


def is_valid_customer_id(customer_id: object) -> bool:
    """Return whether a value is a usable HSM customer identifier."""
    return (
        isinstance(customer_id, int)
        and not isinstance(customer_id, bool)
        and customer_id > 0
    )


def device_info(device_id: str, customer_id: int | None) -> DeviceInfo:
    """Return device metadata with an HSM location link when IDs are valid."""
    identifiers = {(DOMAIN, device_id)}
    if (
        not is_valid_customer_id(customer_id)
        or not isinstance(device_id, str)
        or not device_id.strip()
    ):
        return DeviceInfo(identifiers=identifiers)

    query = urlencode({"customerId": customer_id, "device": device_id})
    return DeviceInfo(
        identifiers=identifiers,
        configuration_url=f"{_HSM_DEVICE_LOCATIONS_URL}?{query}",
    )
