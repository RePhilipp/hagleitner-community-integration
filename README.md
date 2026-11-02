# Hagleitner Community

An unofficial community integration for bringing Hagleitner device data into
Home Assistant. It is an independent project and is not maintained, supported,
or endorsed by Hagleitner.

## Before you begin

The integration needs a Service Bus connection string and queue name. In the
Hagleitner Hygiene Portal, visit
[Devices → Data forwarding](https://hsm.hygieneportal.com/devices/data-forwarding)
and create a **ResourceDataForwardingRule**. The portal provides the connection
and queue details. **Only devices selected in that rule have their values
forwarded.**

ResourceDataForwarding must be enabled for your customer. If the data-forwarding
option or rule is unavailable, ask Hagleitner support or sales whether it can
be enabled. Pricing is unknown and may apply, so confirm any costs with
Hagleitner.

## Set up Home Assistant

After installing the integration through HACS, restart Home Assistant if
prompted. Go to **Settings → Devices & services → Add integration** and choose
**Hagleitner Community**. Enter the Service Bus connection string and queue name
from the portal.

When a message arrives for a new device, Home Assistant offers it for adoption.
Confirm adoption to add the device. Entities appear as supported values arrive;
there is no fixed list of entities guaranteed for every device. Recognized
battery, refill, connectivity, device-error, and replacement conditions can
also appear as maintenance tasks in Home Assistant's Repairs page.

## Keep your connection details safe

Treat the Service Bus connection string as a password: anyone with access to it
may be able to access the queue. Do not post it in issues, screenshots, or
messages, and protect your Home Assistant configuration and backups.

## Local receiver/debug

For troubleshooting from a local checkout, set `HAGLEITNER_SERVICE_BUS_CONNECTION_STRING`
and `HAGLEITNER_QUEUE_NAME` in your environment, then run
`python -m custom_components.hagleitner_community.debug_receiver`. Do not share
the connection string or commit it to files.
