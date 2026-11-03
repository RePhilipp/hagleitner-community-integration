"""Helpers for Hagleitner device metadata."""

from __future__ import annotations

from urllib.parse import urlencode

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_HSM_CUSTOMER_DEVICES_URL = "https://hsm.hygieneportal.com/devices/devices-list"


def is_valid_customer_id(customer_id: object) -> bool:
    """Return whether a value is a usable HSM customer identifier."""
    return (
        isinstance(customer_id, int)
        and not isinstance(customer_id, bool)
        and customer_id > 0
    )


def device_info(device_id: str, customer_id: int | None) -> DeviceInfo:
    """Return device metadata with an HSM link when its customer ID is valid."""
    identifiers = {(DOMAIN, device_id)}
    if not is_valid_customer_id(customer_id):
        return DeviceInfo(identifiers=identifiers)

    customer_query = urlencode({"customerId": customer_id})
    return DeviceInfo(
        identifiers=identifiers,
        configuration_url=f"{_HSM_CUSTOMER_DEVICES_URL}?{customer_query}",
    )
