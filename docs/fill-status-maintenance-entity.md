# Fill status, Maintenance, and Repairs

## Fill-status resource

The fill-status resource is equivalent ID
`9c336908-7a04-4adc-8bd7-08dc3d205c10`, catalog resource type `12293`,
instance `0`. It is an enumerated status with these catalog classifications:

| Raw value | Classification |
| ---: | --- |
| `0` | Full |
| `1` | Nearly full |
| `2` | Empty |

The integration exposes this as an enum sensor. It is not a binary sensor with
`device_class: problem`, so its state alone does not make it a candidate for
Home Assistant's Maintenance view.

## Maintenance and Repairs are separate

The Maintenance view's candidate selection is frontend logic, not something
assigned by Home Assistant Core or by an integration's internal resource kind.
Per the supplied frontend reference, Maintenance candidates include
`binary_sensor` entities with `device_class: problem` and battery-class
entities. A problem binary sensor is counted as a warning when its state is
`on`; its state does not create a Repairs entry.

Repairs entries are stored in Home Assistant's issue registry and must be
explicitly created by Home Assistant or an integration. This integration
creates Repairs issues for specific device faults and component-replacement
thresholds; a fill enum state does not meet those conditions.

The integration exposes the fill-status and refill-state enums alongside a
problem binary sensor. That sensor is `on` when either resource maps to
`empty`, and `off` for the recognized non-empty states. It has
`device_class: problem`, so it is eligible for the Maintenance view; this
entity does not create a Repairs issue.
