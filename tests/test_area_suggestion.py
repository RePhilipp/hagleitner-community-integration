"""Focused tests for HSM location-to-area suggestions."""

from homeassistant.helpers import area_registry as ar

from custom_components.hagleitner_community.coordinator import (
    _innermost_location_name,
    _suggest_existing_area_id,
)


async def test_nested_hsm_path_suggests_leaf_area(hass):
    """Only the innermost part of a delimited HSM path names the area."""
    area = ar.async_get(hass).async_create("WC")
    location_name = _innermost_location_name("Home > OG 3 > WC", None)

    assert location_name == "WC"
    assert _suggest_existing_area_id(hass, location_name) == area.id


async def test_area_suggestion_matches_case_insensitively(hass):
    """Area name comparisons ignore case."""
    area = ar.async_get(hass).async_create("wC")
    location_name = _innermost_location_name("Home > OG 3 > WC", None)

    assert _suggest_existing_area_id(hass, location_name) == area.id


async def test_area_suggestion_trims_surrounding_whitespace(hass):
    """Whitespace around path segments does not prevent an exact match."""
    area = ar.async_get(hass).async_create("WC")
    location_name = _innermost_location_name(" Home > OG 3 >   WC  ", None)

    assert _suggest_existing_area_id(hass, location_name) == area.id


async def test_area_suggestion_does_not_fuzzy_match(hass):
    """Names that only resemble one another are not area suggestions."""
    ar.async_get(hass).async_create("Room 4")

    assert _suggest_existing_area_id(hass, "Room4") is None


async def test_area_suggestion_does_not_match_area_aliases(hass):
    """Only the HA area name, not its aliases, is used as the fallback."""
    ar.async_get(hass).async_create("Bathroom", aliases={"Room4"})

    assert _suggest_existing_area_id(hass, "Room4") is None
