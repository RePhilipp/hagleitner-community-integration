"""Typed models for the complete Hagleitner Service Bus message contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Mapping, TypeVar


class ValueGeneration(IntEnum):
    """The source of a resource reading."""

    OCCASIONAL = 0
    EVENT_TRIGGERED = 1


class LocationType(IntEnum):
    """HSM location hierarchy types."""

    BUILDING = 0
    BUILDING_AREA = 1
    FLOOR = 2
    FLOOR_AREA = 3
    ROOM = 4


ContractEnum = ValueGeneration | LocationType | str | int
_EnumType = TypeVar("_EnumType", bound=IntEnum)


@dataclass(frozen=True)
class Translation:
    """A language-tagged string in a Service Bus message."""

    language_tag: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class DeviceInfo:
    """Device identity and translated device-type names."""

    device_id: str | None = None
    device_type_id: str | None = None
    device_type_name_translations: tuple[Translation, ...] = ()
    device_type_name_alias_translations: tuple[Translation, ...] = ()


@dataclass(frozen=True)
class ComponentInfo:
    """The component associated with a resource-data message."""

    network_id: str | None = None
    component_id: str | None = None
    component_type_id: str | None = None
    firmware_version_id: str | None = None


@dataclass(frozen=True)
class Gateway:
    """Gateway identity and send time, when the message came through a gateway."""

    iot_hub_device_id: str | None = None
    network_id: str | None = None
    sent_at: str | None = None


@dataclass(frozen=True)
class ResourceIdentifier:
    """The type and instance identifiers for one resource value."""

    resource_type_id: int | None = None
    resource_instance_no: int | None = None
    resource_name_translations: tuple[Translation, ...] = ()
    resource_instance_equivalent_id: str | None = None


@dataclass(frozen=True)
class FactorConstantConversion:
    """The factor and constant in a numeric display conversion."""

    conversion_factor: int | None = None
    conversion_constant: int | None = None


@dataclass(frozen=True)
class UnitConversion:
    """Numeric display conversion metadata."""

    factor_constant_conversion: FactorConstantConversion | None = None


@dataclass(frozen=True)
class DisplayPostfix:
    """Translated abbreviations shown after a numeric value."""

    abbreviations: tuple[Translation, ...] = ()


@dataclass(frozen=True)
class NumericDisplayHint:
    """Optional conversion and postfix hints for numeric values."""

    unit_conversion: UnitConversion | None = None
    display_postfix: DisplayPostfix | None = None


@dataclass(frozen=True)
class DisplayHint:
    """Presentation hints attached to a resource value."""

    numeric_display_hint: NumericDisplayHint | None = None


@dataclass(frozen=True)
class ResourceValue:
    """A typed value and all metadata defined by the Service Bus contract."""

    resource_identifier: ResourceIdentifier | None = None
    string_value: str | None = None
    integer_value: int | None = None
    boolean_value: bool | None = None
    display_hint: DisplayHint | None = None
    value_classification_translations: tuple[Translation, ...] | None = None
    # Keep the source mapping for the existing resource log without making wire
    # spelling or unknown extension fields part of the typed contract API.
    raw_data: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class ResourceReading:
    """One timestamped group of resource values."""

    logged_at: str | None = None
    value_generation: ContractEnum | None = None
    resource_values: tuple[ResourceValue, ...] = ()


@dataclass(frozen=True)
class CustomerInfo:
    """Customer identifiers and name fields carried with a message."""

    customer_id: int | None = None
    synchronization_id: str | None = None
    name1: str | None = None
    name2: str | None = None
    name3: str | None = None
    name4: str | None = None


@dataclass(frozen=True)
class Location:
    """One location in the HSM hierarchy."""

    id: int | None = None
    name: str | None = None
    type: ContractEnum | None = None


@dataclass(frozen=True)
class LocationInfo:
    """Location hierarchy and mount point."""

    locations: tuple[Location, ...] = ()
    mount_point: str | None = None

    @property
    def location_id(self) -> int | None:
        """Return the ID of the last location, matching HSM's computed property."""
        return self.locations[-1].id if self.locations else None

    @property
    def path(self) -> tuple[str, ...]:
        """Return the ordered location names, matching HSM's computed property."""
        return tuple(location.name for location in self.locations if location.name)


@dataclass(frozen=True)
class ResourceDataMessage:
    """The complete resource-data message contract."""

    device_info: DeviceInfo | None = None
    component_info: ComponentInfo | None = None
    gateway: Gateway | None = None
    readings: tuple[ResourceReading, ...] = ()
    customer_info: CustomerInfo | None = None
    location_info: LocationInfo | None = None


def parse_resource_data_message(payload: Mapping[str, Any]) -> ResourceDataMessage:
    """Parse all contract fields while tolerating absent optional/message data."""
    if not isinstance(payload, Mapping):
        raise ValueError("Resource-data message must be a JSON object")

    device_info = _mapping(_get(payload, "deviceInfo"))
    component_info = _mapping(_get(payload, "componentInfo"))
    gateway = _mapping(_get(payload, "gateway"))
    customer_info = _mapping(_get(payload, "customerInfo"))
    location_info = _mapping(_get(payload, "locationInfo"))

    return ResourceDataMessage(
        device_info=_parse_device_info(device_info) if device_info is not None else None,
        component_info=(
            _parse_component_info(component_info)
            if component_info is not None
            else None
        ),
        gateway=_parse_gateway(gateway) if gateway is not None else None,
        readings=tuple(
            _parse_reading(item)
            for item in _items(_get(payload, "readings"))
            if _mapping(item) is not None
        ),
        customer_info=(
            _parse_customer_info(customer_info)
            if customer_info is not None
            else None
        ),
        location_info=(
            _parse_location_info(location_info)
            if location_info is not None
            else None
        ),
    )


def _parse_device_info(data: Mapping[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        device_id=_string(_get(data, "deviceId")),
        device_type_id=_string(_get(data, "deviceTypeId")),
        device_type_name_translations=_translations(
            _get(data, "deviceTypeNameTranslations")
        ),
        device_type_name_alias_translations=_translations(
            _get(data, "deviceTypeNameAliasTranslations")
        ),
    )


def _parse_component_info(data: Mapping[str, Any]) -> ComponentInfo:
    return ComponentInfo(
        network_id=_string(_get(data, "networkId")),
        component_id=_string(_get(data, "componentId")),
        component_type_id=_string(_get(data, "componentTypeId")),
        firmware_version_id=_string(_get(data, "firmwareVersionId")),
    )


def _parse_gateway(data: Mapping[str, Any]) -> Gateway:
    return Gateway(
        iot_hub_device_id=_string(_get(data, "iotHubDeviceId")),
        network_id=_string(_get(data, "networkId")),
        sent_at=_string(_get(data, "sentAt")),
    )


def _parse_identifier(data: Mapping[str, Any]) -> ResourceIdentifier:
    return ResourceIdentifier(
        resource_type_id=_integer(_get(data, "resourceTypeId")),
        resource_instance_no=_integer(_get(data, "resourceInstanceNo")),
        resource_name_translations=_translations(
            _get(data, "resourceNameTranslations")
        ),
        resource_instance_equivalent_id=_string(
            _get(data, "resourceInstanceEquivalentId")
        ),
    )


def _parse_factor_conversion(data: Mapping[str, Any]) -> FactorConstantConversion:
    return FactorConstantConversion(
        conversion_factor=_integer(_get(data, "conversionFactor")),
        conversion_constant=_integer(_get(data, "conversionConstant")),
    )


def _parse_unit_conversion(data: Mapping[str, Any]) -> UnitConversion:
    factor_conversion = _mapping(_get(data, "factorConstantConversion"))
    return UnitConversion(
        factor_constant_conversion=(
            _parse_factor_conversion(factor_conversion)
            if factor_conversion is not None
            else None
        )
    )


def _parse_display_postfix(data: Mapping[str, Any]) -> DisplayPostfix:
    return DisplayPostfix(abbreviations=_translations(_get(data, "abbreviations")))


def _parse_numeric_display_hint(data: Mapping[str, Any]) -> NumericDisplayHint:
    unit_conversion = _mapping(_get(data, "unitConversion"))
    display_postfix = _mapping(_get(data, "displayPostfix"))
    return NumericDisplayHint(
        unit_conversion=(
            _parse_unit_conversion(unit_conversion)
            if unit_conversion is not None
            else None
        ),
        display_postfix=(
            _parse_display_postfix(display_postfix)
            if display_postfix is not None
            else None
        ),
    )


def _parse_display_hint(data: Mapping[str, Any]) -> DisplayHint:
    numeric_hint = _mapping(_get(data, "numericDisplayHint"))
    return DisplayHint(
        numeric_display_hint=(
            _parse_numeric_display_hint(numeric_hint)
            if numeric_hint is not None
            else None
        )
    )


def _parse_resource_value(data: Mapping[str, Any]) -> ResourceValue:
    identifier = _mapping(_get(data, "resourceIdentifier"))
    display_hint = _mapping(_get(data, "displayHint"))
    classifications = _get(data, "valueClassificationTranslations")
    return ResourceValue(
        resource_identifier=(
            _parse_identifier(identifier) if identifier is not None else None
        ),
        string_value=_string(_get(data, "stringValue")),
        integer_value=_integer(_get(data, "integerValue")),
        boolean_value=_boolean(_get(data, "booleanValue")),
        display_hint=(
            _parse_display_hint(display_hint) if display_hint is not None else None
        ),
        value_classification_translations=(
            _translations(classifications) if classifications is not None else None
        ),
        raw_data=dict(data),
    )


def _parse_reading(data: Mapping[str, Any]) -> ResourceReading:
    return ResourceReading(
        logged_at=_string(_get(data, "loggedAt")),
        value_generation=_enum_value(_get(data, "valueGeneration"), ValueGeneration),
        resource_values=tuple(
            _parse_resource_value(item)
            for item in _items(_get(data, "resourceValues"))
            if _mapping(item) is not None
        ),
    )


def _parse_customer_info(data: Mapping[str, Any]) -> CustomerInfo:
    return CustomerInfo(
        customer_id=_integer(_get(data, "customerId")),
        synchronization_id=_string(_get(data, "synchronizationId")),
        name1=_string(_get(data, "name1")),
        name2=_string(_get(data, "name2")),
        name3=_string(_get(data, "name3")),
        name4=_string(_get(data, "name4")),
    )


def _parse_location(data: Mapping[str, Any]) -> Location:
    return Location(
        id=_integer(_get(data, "id")),
        name=_string(_get(data, "name")),
        type=_enum_value(_get(data, "type"), LocationType),
    )


def _parse_location_info(data: Mapping[str, Any]) -> LocationInfo:
    return LocationInfo(
        locations=tuple(
            _parse_location(item)
            for item in _items(_get(data, "locations"))
            if _mapping(item) is not None
        ),
        mount_point=_string(_get(data, "mountPoint")),
    )


def _translations(value: Any) -> tuple[Translation, ...]:
    return tuple(
        Translation(
            language_tag=_string(_get(item, "languageTag")),
            value=_string(_get(item, "value")),
        )
        for item in _items(value)
        if _mapping(item) is not None
    )


def _enum_value(value: Any, enum_type: type[_EnumType]) -> ContractEnum | None:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return enum_type(value)
        except ValueError:
            return value
    if isinstance(value, str):
        normalized = "".join(
            character
            for character in value.rsplit(".", 1)[-1].strip().casefold()
            if character.isalnum()
        )
        for member in enum_type:
            member_name = "".join(
                character for character in member.name.casefold() if character.isalnum()
            )
            if member_name == normalized:
                return member
        try:
            number = int(normalized)
        except ValueError:
            return value
        try:
            return enum_type(number)
        except ValueError:
            return number
    return None


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _items(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _get(data: Mapping[str, Any], camel_case: str) -> Any:
    """Read a JSON camel-case property or its CLR PascalCase spelling."""
    if camel_case in data:
        return data[camel_case]
    pascal_case = camel_case[0].upper() + camel_case[1:]
    return data.get(pascal_case)
