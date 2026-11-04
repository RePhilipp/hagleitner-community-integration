"""Helpers for Hagleitner device metadata."""

from __future__ import annotations

from urllib.parse import urlencode

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_HSM_DEVICE_LOCATIONS_URL = "https://hsm.hygieneportal.com/devices/locations"


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
