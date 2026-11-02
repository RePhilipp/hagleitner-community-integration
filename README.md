# Hagleitner Community

An unofficial Home Assistant custom integration for receiving Hagleitner
resource-data messages from Azure Service Bus. This is an independent community
project; it is not maintained, supported, or endorsed by Hagleitner.

The integration discovers devices from incoming messages and asks before
adding each one to Home Assistant. It then creates entities for supported
resources as they arrive, without requiring a restart.

## Local receiver

The standalone receiver uses Python 3.11+ and has one external dependency:
Azure's `azure-servicebus` SDK.

```shell
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

export HAGLEITNER_SERVICE_BUS_CONNECTION_STRING='Endpoint=...'
export HAGLEITNER_QUEUE_NAME='your-queue-name'
python -m custom_components.hagleitner_community.debug_receiver
```

Use a queue dedicated to this receiver while debugging. A queue distributes
messages among competing consumers, so listening on a queue used by another
consumer may mean that each process sees only some messages. The connection
string is read from the environment and should never be committed or pasted
into an issue.

The receiver uses peek-lock mode. Successfully decoded and logged messages are
completed; malformed JSON or messages without a device ID are dead-lettered.
Press `Ctrl+C` to stop the local process.

## Home Assistant setup

For a manual installation, place `custom_components/hagleitner_community` in
your Home Assistant configuration's `custom_components` directory, restart
Home Assistant, then add **Hagleitner Community** from **Settings → Devices &
services → Add integration**. Enter the queue connection string and queue name.

When Home Assistant first receives a message for an unknown device, it offers
the device for adoption. No device-registry entry or entities are created
unless the user confirms. After adoption, the integration registers the device
and creates entities when supported resource values arrive. Supported values
received before adoption are cached and their entities are created once the
device is adopted. Existing disabled entities are not enabled automatically.

The hard-coded catalog currently includes:

| Equivalent ID | Resource | Value handling |
|---|---|---|
| `84b96502-7738-43fb-f3dd-08dace26c91e` | Dispense count | Numeric counter |
| `491d2cd9-92a0-4107-f3de-08dace26c91e` | Refill count | Numeric counter |
| `77d144fd-d7a3-42f7-03aa-08dac1664f9a` | Energy supply status | `0=ok`, `1=low`, `2=empty`, `3=mains_adapter` |
| `4b963ce8-14f4-4f90-03a9-08dac1664f9a` | Refill status | `0=full`, `1=low`, `2=empty` |
| `9a77375d-964c-451f-03ab-08dac1664f9a` | Error status | `0=no_error`, `1=error` |
| `7c178f1d-271f-4554-03ac-08dac1664f9a` | Connection status | `0=offline`, `1=temporarily_offline`, `2=online`, `3=not_connected` |
| `9c336908-7a04-4adc-8bd7-08dc3d205c10` | Fill status | `0=empty`, `1=nearly_full`, `2=full` |
| `f8cdaa9a-4633-4fd4-1d0d-08de5e8412d5` | Passage counter | Numeric counter |

The catalog matches resources by equivalent ID. Resource type and instance
numbers are retained as part of entity identity so separate resources sharing
an equivalent ID do not overwrite one another.

Error values are normalized only to `no_error` or `error`; their detailed
meaning depends on the device. Gateway LONGRANGE connection values are
overridden to `0=not_available` and `2=available` using the device-type
translations. Numeric counts are total-increasing sensors, refill and status
values are enum sensors, and energy supply status adds a battery percentage
sensor (`0=100%`, `1=20%`, `2=0%`) and low-battery binary sensor only after a
battery-powered state is received. Mains-powered state (`3`) alone creates no
battery entities. Error and connection values create Home Assistant problem
and connectivity binary sensors, respectively.

Active maintenance states also create issues in Home Assistant's Repairs UI.
Low battery, low refill, and nearly-full container states are warnings;
empty battery/refill, full containers, active errors, and exactly-offline
devices are errors. Issues clear when a later message reports a normal state.
Temporary-offline and not-connected states do not create connection issues.

## Project status

This repository is private, so it cannot be installed from the Home Assistant
Marketplace/catalog. It is intended for private development and manual use.
Marketplace distribution would require a public repository and a catalog
submission.
