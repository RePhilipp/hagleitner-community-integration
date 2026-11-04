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

Open the rule and select its **Connection strings** tab. Copy the **Service bus
connection** and **Service bus queue** values into the Home Assistant setup;
the SignalR connection is not used by this integration.

![Hagleitner portal showing the Service Bus connection and queue fields](docs/images/forwarding-rule-connection-strings.png)

ResourceDataForwarding must be enabled for your customer. If the data-forwarding
option or rule is unavailable, contact Hagleitner Sales to ask about enabling
it. Confirm any applicable costs with Sales.

You can use multiple forwarding rules. Add each rule's queue as a separate
integration entry; devices included by more than one rule remain a single
Home Assistant device.

**Use only one active consumer for each queue.** If multiple Home Assistant
instances or integration entries consume the same queue, Service Bus distributes
messages between them, so each instance may miss some readings. If you run
multiple Home Assistant instances, create a separate forwarding rule (and queue)
for each instance.

## Set up Home Assistant

After installing the integration through HACS, restart Home Assistant if
prompted. Go to **Settings → Devices & services → Add integration** and choose
**Hagleitner Community**. Enter the Service Bus connection string and queue name
from the portal.

When a message arrives for a new device, Home Assistant offers it for adoption.
Confirm adoption to add the device. Entities appear as supported values arrive;
there is no fixed list of entities guaranteed for every device. Recognized
connectivity issues, device errors, and component replacement thresholds can
also appear as maintenance tasks in Home Assistant's Repairs page. Battery,
refill, and fill levels remain available as entities, not Repairs issues.

## Developer information

### Run tests locally

Tests target stable Home Assistant 2026.10.4 and require Python 3.14.2 or newer.
The matching test package is a regular release, although the project is marked
Alpha on PyPI. Tests run Home Assistant in-process; they do not start a server
or require Docker. The separate `.venv-ha` environment avoids changing an
existing integration or Python 3.12 environment. From the repository root:

```bash
python3.14 -m venv .venv-ha
source .venv-ha/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements_test.txt
python -m pytest -q
```

Test dependencies are separate from the integration's runtime requirements.

### Try the integration in a local Home Assistant container

This isolated test instance uses Home Assistant 2026.10.4 and mounts the
integration from this checkout. Its configuration, including any credentials
entered in the UI, stays under the ignored `ha-test/` directory. From the
repository root:

```bash
mkdir -p ha-test/config
docker run -d \
  --name hagleitner-ha-test \
  -p 8124:8123 \
  -e TZ=Etc/UTC \
  -v "$PWD/ha-test/config:/config" \
  -v "$PWD/custom_components/hagleitner_community:/config/custom_components/hagleitner_community:ro" \
  ghcr.io/home-assistant/home-assistant:2026.10.4
docker logs -f hagleitner-ha-test
```

Open [http://localhost:8124](http://localhost:8124) to finish Home Assistant
onboarding and add the integration. A live queue connection is needed to
trigger device discovery. Stop and restart the container with
`docker stop hagleitner-ha-test` and `docker start hagleitner-ha-test`; the test
configuration is preserved between runs.

### Local receiver/debug

For troubleshooting from a local checkout, set `HAGLEITNER_SERVICE_BUS_CONNECTION_STRING`
and `HAGLEITNER_QUEUE_NAME` in your environment, then run
`python -m custom_components.hagleitner_community.debug_receiver`. Do not share
the connection string or commit it to files.
