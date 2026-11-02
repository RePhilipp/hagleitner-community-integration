# Hagleitner Community

An unofficial Home Assistant custom integration for receiving Hagleitner
resource-data messages from Azure Service Bus. This is an independent community
project; it is not maintained, supported, or endorsed by Hagleitner.

The first version is deliberately a receiver/debugging foundation: it creates a
Home Assistant device registry entry on the first message for a device and
logs each resource value. It does not create sensor entities yet.

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

When Home Assistant receives a message, the integration registers the device
using its device ID if it is not already registered, then logs each
`ResourceValue`, including whether the resource is in the supported catalog.
The initial catalog includes the Fragrance dispenser's Refill state:

| Equivalent ID | Resource type ID | Instance | Current handling |
|---|---:|---:|---|
| `4b963ce8-14f4-4f90-03a9-08dac1664f9a` | `12290` | `0` | Log only |

When an equivalent ID is present, the catalog matches on that ID. A
device-type/resource/instance match remains as a fallback for identifiers that
do not include an equivalent ID.

The supplied enum values `0`, `1`, and `2` do not yet define their meanings, so
no state conversion is guessed. Once those meanings and the desired Home
Assistant entities are confirmed, mappings can be added to the resource
catalog.

## Project status

This repository is private, so it cannot be installed from the Home Assistant
Marketplace/catalog. It is intended for private development and manual use.
Marketplace distribution would require a public repository and a catalog
submission.
