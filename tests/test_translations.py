"""Validate shipped translation data and coverage for generated entities."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.hagleitner_community.resource_data import (
    SUPPORTED_RESOURCES_BY_EQUIVALENT_ID,
    SUPPORTED_RESOURCES_BY_TYPE_INSTANCE,
)

_INTEGRATION_PATH = (
    Path(__file__).parents[1] / "custom_components" / "hagleitner_community"
)
_TRANSLATIONS_PATH = _INTEGRATION_PATH / "translations"
_SENSOR_KINDS = {"counter", "measurement", "diagnostic", "enum", "opening", "connection"}


def test_all_locale_files_are_valid_json():
    """All locale files should remain parseable after translation updates."""
    locale_files = sorted(_TRANSLATIONS_PATH.glob("*.json"))

    assert locale_files
    for locale_file in locale_files:
        json.loads(locale_file.read_text(encoding="utf-8"))


def test_english_translates_all_shipped_entity_names_and_states():
    """Every generated entity has a key, English name, and enum-state labels."""
    translations = json.loads(
        (_TRANSLATIONS_PATH / "en.json").read_text(encoding="utf-8")
    )["entity"]
    sensor_translations = translations["sensor"]
    binary_sensor_translations = translations["binary_sensor"]

    definitions = (
        *SUPPORTED_RESOURCES_BY_EQUIVALENT_ID.values(),
        *SUPPORTED_RESOURCES_BY_TYPE_INSTANCE.values(),
    )
    for definition in definitions:
        if definition.kind not in _SENSOR_KINDS:
            continue

        key = definition.entity_translation_key
        assert key is not None, definition.name
        assert key in sensor_translations, definition.name
        assert sensor_translations[key].get("name"), definition.name
        if definition.kind in {"enum", "opening", "connection"}:
            assert set(definition.enum_values.values()) <= set(
                sensor_translations[key].get("state", {})
            ), definition.name

    assert {
        "battery_level",
        "metadata_customer_name",
        "metadata_customer_id",
        "metadata_location",
        "metadata_mount_point",
    } <= set(sensor_translations)
    assert {"mains_adapter", "refill_empty", "device_error"} <= set(
        binary_sensor_translations
    )
    assert all(
        binary_sensor_translations[key].get("name")
        for key in ("mains_adapter", "refill_empty", "device_error")
    )
    # This one entity covers both low/empty refill state and nearly-full fill
    # status, so its binary state labels must describe a warning, not imply that
    # refilling is already required or that a full refill is currently OK.
    assert binary_sensor_translations["refill_empty"]["state"] == {
        "on": "Refill warning",
        "off": "No refill warning",
    }


def test_exception_translations_cover_user_facing_setup_errors():
    """All translated Home Assistant setup exceptions have English messages."""
    translations = json.loads(
        (_TRANSLATIONS_PATH / "en.json").read_text(encoding="utf-8")
    )["exceptions"]

    assert {
        "service_bus_credentials_invalid",
        "service_bus_queue_unavailable",
        "service_bus_queue_not_found",
        "service_bus_queue_validation_failed",
        "waiting_for_queue_connection",
    } <= set(translations)
    assert all(exception.get("message") for exception in translations.values())


def test_custom_entity_icons_are_defined_for_translatable_entities():
    """Every icons.json key references an English entity translation key."""
    translations = json.loads(
        (_TRANSLATIONS_PATH / "en.json").read_text(encoding="utf-8")
    )["entity"]
    icons = json.loads((_INTEGRATION_PATH / "icons.json").read_text(encoding="utf-8"))

    for platform, entities in icons["entity"].items():
        assert set(entities) <= set(translations[platform])
        assert all(entity_icons.get("default") for entity_icons in entities.values())
