"""Tests for the full Hagleitner Service Bus message contract."""

from __future__ import annotations

from custom_components.hagleitner_community.service_bus_contract import (
    LocationType,
    ValueGeneration,
    parse_resource_data_message,
)


def test_parser_maps_the_complete_service_bus_contract():
    """All defined message, component, gateway and reading fields are retained."""
    message = parse_resource_data_message(
        {
            "deviceInfo": {
                "deviceId": "device-guid",
                "deviceTypeId": "type-guid",
                "deviceTypeNameTranslations": [
                    {"languageTag": "en", "value": "Dispenser"}
                ],
                "deviceTypeNameAliasTranslations": [
                    {"languageTag": "de", "value": "Spender"}
                ],
            },
            "componentInfo": {
                "networkId": "component-network",
                "componentId": "component-guid",
                "componentTypeId": "component-type-guid",
                "firmwareVersionId": "firmware-guid",
            },
            "gateway": {
                "iotHubDeviceId": "iot-hub-device",
                "networkId": "gateway-network",
                "sentAt": "2026-11-10T12:00:00Z",
            },
            "readings": [
                {
                    "loggedAt": "2026-11-10T11:59:00Z",
                    "valueGeneration": "EventTriggered",
                    "resourceValues": [
                        {
                            "resourceIdentifier": {
                                "resourceTypeId": 12,
                                "resourceInstanceNo": 3,
                                "resourceNameTranslations": [
                                    {"languageTag": "en", "value": "Volume"}
                                ],
                                "resourceInstanceEquivalentId": "resource-guid",
                            },
                            "stringValue": "custom value",
                            "integerValue": 42,
                            "booleanValue": True,
                            "displayHint": {
                                "numericDisplayHint": {
                                    "unitConversion": {
                                        "factorConstantConversion": {
                                            "conversionFactor": 100,
                                            "conversionConstant": 5,
                                        }
                                    },
                                    "displayPostfix": {
                                        "abbreviations": [
                                            {"languageTag": "en", "value": "ml"}
                                        ]
                                    },
                                }
                            },
                            "valueClassificationTranslations": [
                                {"languageTag": "en", "value": "Normal"}
                            ],
                        }
                    ],
                }
            ],
            "customerInfo": {
                "customerId": 987,
                "synchronizationId": "customer-sync-id",
                "name1": "Customer",
                "name2": "Second",
                "name3": "Third",
                "name4": "Fourth",
            },
            "locationInfo": {
                "locations": [
                    {"id": 10, "name": "Building", "type": 0},
                    {"id": 11, "name": "Room", "type": "Room"},
                ],
                "mountPoint": "Wall",
            },
        }
    )

    assert message.device_info is not None
    assert message.device_info.device_id == "device-guid"
    assert message.device_info.device_type_id == "type-guid"
    assert message.device_info.device_type_name_translations[0].value == "Dispenser"
    assert message.device_info.device_type_name_alias_translations[0].value == "Spender"

    assert message.component_info is not None
    assert message.component_info.network_id == "component-network"
    assert message.component_info.component_id == "component-guid"
    assert message.component_info.component_type_id == "component-type-guid"
    assert message.component_info.firmware_version_id == "firmware-guid"

    assert message.gateway is not None
    assert message.gateway.iot_hub_device_id == "iot-hub-device"
    assert message.gateway.network_id == "gateway-network"
    assert message.gateway.sent_at == "2026-11-10T12:00:00Z"

    reading = message.readings[0]
    assert reading.logged_at == "2026-11-10T11:59:00Z"
    assert reading.value_generation is ValueGeneration.EVENT_TRIGGERED
    resource = reading.resource_values[0]
    assert resource.resource_identifier is not None
    assert resource.resource_identifier.resource_type_id == 12
    assert resource.resource_identifier.resource_instance_no == 3
    assert resource.resource_identifier.resource_name_translations[0].value == "Volume"
    assert resource.resource_identifier.resource_instance_equivalent_id == "resource-guid"
    assert resource.string_value == "custom value"
    assert resource.integer_value == 42
    assert resource.boolean_value is True
    assert resource.display_hint is not None
    numeric_hint = resource.display_hint.numeric_display_hint
    assert numeric_hint is not None
    unit_conversion = numeric_hint.unit_conversion
    assert unit_conversion is not None
    factor_conversion = unit_conversion.factor_constant_conversion
    assert factor_conversion is not None
    assert factor_conversion.conversion_factor == 100
    assert factor_conversion.conversion_constant == 5
    assert numeric_hint.display_postfix is not None
    assert numeric_hint.display_postfix.abbreviations[0].value == "ml"
    assert resource.value_classification_translations is not None
    assert resource.value_classification_translations[0].value == "Normal"

    assert message.customer_info is not None
    assert message.customer_info.customer_id == 987
    assert message.customer_info.synchronization_id == "customer-sync-id"
    assert (
        message.customer_info.name1,
        message.customer_info.name2,
        message.customer_info.name3,
        message.customer_info.name4,
    ) == ("Customer", "Second", "Third", "Fourth")

    assert message.location_info is not None
    assert message.location_info.locations[0].type is LocationType.BUILDING
    assert message.location_info.locations[1].type is LocationType.ROOM
    assert message.location_info.location_id == 11
    assert message.location_info.path == ("Building", "Room")
    assert message.location_info.mount_point == "Wall"


def test_parser_accepts_pascal_case_and_preserves_unknown_enum_values():
    """CLR property names and future enum values don't lose message data."""
    message = parse_resource_data_message(
        {
            "DeviceInfo": {"DeviceId": "device", "DeviceTypeId": "type"},
            "Readings": [
                {
                    "ValueGeneration": "FutureGeneration",
                    "ResourceValues": [],
                }
            ],
            "LocationInfo": {
                "Locations": [{"Id": 1, "Name": "Area", "Type": "FutureArea"}],
                "MountPoint": "Ceiling",
            },
        }
    )

    assert message.device_info is not None
    assert message.device_info.device_id == "device"
    assert message.readings[0].value_generation == "FutureGeneration"
    assert message.location_info is not None
    assert message.location_info.locations[0].type == "FutureArea"


def test_parser_handles_optional_sections_and_invalid_enum_values():
    """Absent optional sections remain absent and invalid enums are ignored."""
    message = parse_resource_data_message(
        {
            "deviceInfo": {"deviceId": "device"},
            "readings": [{"valueGeneration": True}],
        }
    )

    assert message.component_info is None
    assert message.gateway is None
    assert message.customer_info is None
    assert message.location_info is None
    assert message.readings[0].value_generation is None
