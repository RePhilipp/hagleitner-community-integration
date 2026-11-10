# Home Assistant integration quality scale

Checklist for tracking this integration against the Home Assistant [integration quality scale rules](https://contributors.home-assistant.io/core/quality-scale/rules/).

The quality scale has four tiers: Bronze, Silver, Gold, and Platinum. A tier includes all requirements from the tiers below it. Check a box only when the requirement is met, and add links to relevant implementation, documentation, or tests as evidence. If a rule is exempt, note why rather than treating it as complete without explanation.

This is a tracking checklist, not an audit: all rules start unchecked until verified.

## Bronze

Baseline requirements for every integration (20 rules).

- [x] [`action-setup`](https://contributors.home-assistant.io/core/quality-scale/action-setup/) — Exempt: this integration registers no custom Home Assistant actions ([`__init__.py`](../custom_components/hagleitner_community/__init__.py)).
- [x] [`appropriate-polling`](https://contributors.home-assistant.io/core/quality-scale/appropriate-polling/) — Exempt: the integration receives queue messages and its entities do not poll ([`service_bus.py`](../custom_components/hagleitner_community/service_bus.py), [`sensor.py`](../custom_components/hagleitner_community/sensor.py), [`binary_sensor.py`](../custom_components/hagleitner_community/binary_sensor.py)).
- [x] [`brands`](https://contributors.home-assistant.io/core/quality-scale/brands/) — Met: custom integration bundles an icon and logo ([`brand/icon.png`](../custom_components/hagleitner_community/brand/icon.png), [`brand/logo.png`](../custom_components/hagleitner_community/brand/logo.png)).
- [x] [`common-modules`](https://contributors.home-assistant.io/core/quality-scale/common-modules/) — Met: the hub/coordinator is in [`coordinator.py`](../custom_components/hagleitner_community/coordinator.py); there is no shared cross-platform base entity to move.
- [x] [`config-flow`](https://contributors.home-assistant.io/core/quality-scale/config-flow/) — Met: setup uses a UI config flow with field descriptions ([`config_flow.py`](../custom_components/hagleitner_community/config_flow.py), [`en.json`](../custom_components/hagleitner_community/translations/en.json)).
- [x] [`config-flow-test-coverage`](https://contributors.home-assistant.io/core/quality-scale/config-flow-test-coverage/) — Met: flow paths and recovery are covered ([`test_config_flow.py`](../tests/test_config_flow.py); 100% flow-module coverage reported in the focused run).
- [ ] [`dependency-transparency`](https://contributors.home-assistant.io/core/quality-scale/dependency-transparency/) — Pending: confirm public CI release provenance for `azure-servicebus`.
- [x] [`docs-actions`](https://contributors.home-assistant.io/core/quality-scale/docs-actions/) — Exempt: the integration registers no custom Home Assistant actions ([`__init__.py`](../custom_components/hagleitner_community/__init__.py)).
- [x] [`docs-conditions`](https://contributors.home-assistant.io/core/quality-scale/docs-conditions/) — Exempt: the integration provides no Home Assistant automation conditions.
- [x] [`docs-high-level-description`](https://contributors.home-assistant.io/core/quality-scale/docs-high-level-description/) — Met: the README describes the product, data path, and integration ([`README.md`](../README.md)).
- [ ] [`docs-installation-instructions`](https://contributors.home-assistant.io/core/quality-scale/docs-installation-instructions/) — Pending: repository README has setup steps, but the required Home Assistant integration-page documentation is not published.
- [ ] [`docs-removal-instructions`](https://contributors.home-assistant.io/core/quality-scale/docs-removal-instructions/) — Pending: repository README has removal steps, but the required Home Assistant integration-page documentation is not published.
- [x] [`docs-triggers`](https://contributors.home-assistant.io/core/quality-scale/docs-triggers/) — Exempt: the integration provides no automation triggers.
- [x] [`entity-event-setup`](https://contributors.home-assistant.io/core/quality-scale/entity-event-setup/) — Met: entities subscribe and unsubscribe through their lifecycle ([`sensor.py`](../custom_components/hagleitner_community/sensor.py), [`binary_sensor.py`](../custom_components/hagleitner_community/binary_sensor.py)).
- [x] [`entity-unique-id`](https://contributors.home-assistant.io/core/quality-scale/entity-unique-id/) — Met: entity IDs include device/resource identity and are tested ([`test_cover_presentation.py`](../tests/test_cover_presentation.py), [`test_consumable_entities.py`](../tests/test_consumable_entities.py)).
- [x] [`has-entity-name`](https://contributors.home-assistant.io/core/quality-scale/has-entity-name/) — Met: sensor and binary-sensor entities set `has_entity_name` ([`sensor.py`](../custom_components/hagleitner_community/sensor.py), [`binary_sensor.py`](../custom_components/hagleitner_community/binary_sensor.py)).
- [ ] [`runtime-data`](https://contributors.home-assistant.io/core/quality-scale/runtime-data/) — Pending: move per-entry hub state from `hass.data` to `ConfigEntry.runtime_data` while preserving shared hub/device lifecycle.
- [ ] [`test-before-configure`](https://contributors.home-assistant.io/core/quality-scale/test-before-configure/) — Test the connection before creating the config entry.
- [ ] [`test-before-setup`](https://contributors.home-assistant.io/core/quality-scale/test-before-setup/) — Check during setup that the integration works and raise the appropriate exception if not.
- [x] [`unique-config-entry`](https://contributors.home-assistant.io/core/quality-scale/unique-config-entry/) — Met: duplicate queues and discovered devices are rejected ([`config_flow.py`](../custom_components/hagleitner_community/config_flow.py), [`test_config_flow.py`](../tests/test_config_flow.py)).

## Silver

Reliability, error handling, reauthentication, and ownership (10 additional rules).

- [ ] [`action-exceptions`](https://contributors.home-assistant.io/core/quality-scale/action-exceptions/) — Raise `ServiceValidationError` or `HomeAssistantError` when actions fail.
- [ ] [`config-entry-unloading`](https://contributors.home-assistant.io/core/quality-scale/config-entry-unloading/) — Support unloading and reloading the config entry without restarting Home Assistant.
- [ ] [`docs-configuration-parameters`](https://contributors.home-assistant.io/core/quality-scale/docs-configuration-parameters/) — Document every option-flow parameter.
- [ ] [`docs-installation-parameters`](https://contributors.home-assistant.io/core/quality-scale/docs-installation-parameters/) — Document every parameter requested during setup.
- [ ] [`entity-unavailable`](https://contributors.home-assistant.io/core/quality-scale/entity-unavailable/) — Mark entities unavailable when the device or service cannot be reached.
- [ ] [`integration-owner`](https://contributors.home-assistant.io/core/quality-scale/integration-owner/) — Have at least one integration owner.
- [ ] [`log-when-unavailable`](https://contributors.home-assistant.io/core/quality-scale/log-when-unavailable/) — Log once when the connection is lost and once when it returns.
- [ ] [`parallel-updates`](https://contributors.home-assistant.io/core/quality-scale/parallel-updates/) — Set `PARALLEL_UPDATES` on every entity platform.
- [ ] [`reauthentication-flow`](https://contributors.home-assistant.io/core/quality-scale/reauthentication-flow/) — Let users enter new credentials without removing the integration.
- [ ] [`test-coverage`](https://contributors.home-assistant.io/core/quality-scale/test-coverage/) — Achieve more than 95% test coverage for every integration module.

## Gold

Discovery, devices, translations, and user-facing documentation (21 additional rules).

- [ ] [`devices`](https://contributors.home-assistant.io/core/quality-scale/devices/) — Group entities into devices and provide complete device information.
- [ ] [`diagnostics`](https://contributors.home-assistant.io/core/quality-scale/diagnostics/) — Let users download diagnostics with sensitive data redacted.
- [ ] [`discovery`](https://contributors.home-assistant.io/core/quality-scale/discovery/) — Discover devices so users do not have to look them up.
- [ ] [`discovery-update-info`](https://contributors.home-assistant.io/core/quality-scale/discovery-update-info/) — Update a known device's address when discovery detects a change.
- [ ] [`docs-data-update`](https://contributors.home-assistant.io/core/quality-scale/docs-data-update/) — Explain how and how often data is updated.
- [ ] [`docs-examples`](https://contributors.home-assistant.io/core/quality-scale/docs-examples/) — Provide automation examples or blueprints.
- [ ] [`docs-known-limitations`](https://contributors.home-assistant.io/core/quality-scale/docs-known-limitations/) — List known limitations.
- [ ] [`docs-supported-devices`](https://contributors.home-assistant.io/core/quality-scale/docs-supported-devices/) — List known supported and unsupported devices.
- [ ] [`docs-supported-functions`](https://contributors.home-assistant.io/core/quality-scale/docs-supported-functions/) — Describe the entities and functionality provided.
- [ ] [`docs-troubleshooting`](https://contributors.home-assistant.io/core/quality-scale/docs-troubleshooting/) — Help users solve common problems.
- [ ] [`docs-use-cases`](https://contributors.home-assistant.io/core/quality-scale/docs-use-cases/) — Show what users can do with the integration.
- [ ] [`dynamic-devices`](https://contributors.home-assistant.io/core/quality-scale/dynamic-devices/) — Add devices that appear after setup without requiring a reload.
- [ ] [`entity-category`](https://contributors.home-assistant.io/core/quality-scale/entity-category/) — Assign entity categories to configuration and diagnostic entities.
- [ ] [`entity-device-class`](https://contributors.home-assistant.io/core/quality-scale/entity-device-class/) — Use an appropriate device class for entities wherever one fits.
- [ ] [`entity-disabled-by-default`](https://contributors.home-assistant.io/core/quality-scale/entity-disabled-by-default/) — Disable entities by default when they are only useful to a subset of users.
- [ ] [`entity-translations`](https://contributors.home-assistant.io/core/quality-scale/entity-translations/) — Define entity names in `strings.json` for translation.
- [ ] [`exception-translations`](https://contributors.home-assistant.io/core/quality-scale/exception-translations/) — Define user-facing errors in `strings.json` for translation.
- [ ] [`icon-translations`](https://contributors.home-assistant.io/core/quality-scale/icon-translations/) — Define entity icons in `icons.json`.
- [ ] [`reconfiguration-flow`](https://contributors.home-assistant.io/core/quality-scale/reconfiguration-flow/) — Let users change an entry's setup without removing it.
- [ ] [`repair-issues`](https://contributors.home-assistant.io/core/quality-scale/repair-issues/) — Create repair issues for problems users can fix.
- [ ] [`stale-devices`](https://contributors.home-assistant.io/core/quality-scale/stale-devices/) — Remove devices that are gone, or let users remove them.

## Platinum

Async dependencies, efficient session handling, and strict typing (3 additional rules).

- [ ] [`async-dependency`](https://contributors.home-assistant.io/core/quality-scale/async-dependency/) — Use an asyncio-based library for the integration.
- [ ] [`inject-websession`](https://contributors.home-assistant.io/core/quality-scale/inject-websession/) — Make the library accept Home Assistant's web session.
- [ ] [`strict-typing`](https://contributors.home-assistant.io/core/quality-scale/strict-typing/) — Fully type the integration and check it with strict mypy settings.
