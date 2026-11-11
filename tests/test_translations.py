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


def _translation_keys(
    value: object,
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    """Return every nested translation key path in a locale document."""
    if not isinstance(value, dict):
        return set()
    keys: set[tuple[str, ...]] = set()
    for key, child in value.items():
        path = (*prefix, key)
        keys.add(path)
        keys.update(_translation_keys(child, path))
    return keys


def test_all_locales_have_the_same_translation_keys():
    """Keep every locale structurally complete with English fallback strings."""
    english_keys = _translation_keys(
        json.loads((_TRANSLATIONS_PATH / "en.json").read_text(encoding="utf-8"))
    )

    for locale_file in _TRANSLATIONS_PATH.glob("*.json"):
        locale_keys = _translation_keys(
            json.loads(locale_file.read_text(encoding="utf-8"))
        )
        assert locale_keys == english_keys, locale_file.name


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
    assert {
        "mains_adapter",
        "refill_warning",
        "fill_warning",
        "device_error",
        "automatic_update",
    } <= set(
        binary_sensor_translations
    )
    assert all(
        binary_sensor_translations[key].get("name")
        for key in (
            "mains_adapter",
            "refill_warning",
            "fill_warning",
            "device_error",
            "automatic_update",
        )
    )
    assert binary_sensor_translations["refill_warning"]["state"] == {
        "on": "Refill warning",
        "off": "No refill warning",
    }
    assert binary_sensor_translations["fill_warning"]["state"] == {
        "on": "Fill warning",
        "off": "No fill warning",
    }


def test_german_translates_all_shipped_entity_names_and_states():
    """German covers every shipped entity name and enum state, not just metadata."""
    translations = json.loads(
        (_TRANSLATIONS_PATH / "en.json").read_text(encoding="utf-8")
    )["entity"]
    german_translations = json.loads(
        (_TRANSLATIONS_PATH / "de.json").read_text(encoding="utf-8")
    )["entity"]

    for platform, entities in translations.items():
        german_entities = german_translations[platform]
        assert set(entities) <= set(german_entities)
        for key, english_entity in entities.items():
            german_entity = german_entities[key]
            assert german_entity.get("name"), key
            assert set(english_entity.get("state", {})) <= set(
                german_entity.get("state", {})
            ), key


def test_all_locales_translate_binary_status_sensors():
    """Every locale labels warnings and the read-only update status."""
    for locale_file in _TRANSLATIONS_PATH.glob("*.json"):
        binary_sensors = json.loads(locale_file.read_text(encoding="utf-8"))[
            "entity"
        ]["binary_sensor"]
        assert {
            "refill_warning",
            "fill_warning",
            "device_error",
            "automatic_update",
        } <= set(binary_sensors), locale_file.name
        for key in (
            "refill_warning",
            "fill_warning",
            "device_error",
            "automatic_update",
        ):
            assert binary_sensors[key].get("name"), (locale_file.name, key)
            if key != "device_error":
                assert set(binary_sensors[key].get("state", {})) == {"on", "off"}, (
                    locale_file.name,
                    key,
                )


def test_catalog_backed_resource_names_exist_in_every_locale():
    """Catalog-localized resource names are present in every shipped locale."""
    catalog_backed_keys = {
        "dispense_count",
        "refill_count",
        "passage_count",
        "refill_state",
        "connection_status",
        "fill_status",
    }

    for locale_file in _TRANSLATIONS_PATH.glob("*.json"):
        translations = json.loads(locale_file.read_text(encoding="utf-8"))
        sensors = translations["entity"]["sensor"]
        assert catalog_backed_keys <= set(sensors), locale_file.name
        assert all(sensors[key].get("name") for key in catalog_backed_keys), (
            locale_file.name
        )


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
