"""Tests for the standalone Service Bus debug receiver."""

from __future__ import annotations

import logging

import pytest

from custom_components.hagleitner_community import debug_receiver


@pytest.mark.parametrize(
    ("connection_string", "queue_name"),
    [(None, "queue"), ("secret", None), ("", "queue"), ("secret", "")],
)
async def test_run_requires_both_environment_values(
    monkeypatch, connection_string, queue_name
):
    """The local tool fails clearly without either required setting."""
    if connection_string is None:
        monkeypatch.delenv("HAGLEITNER_SERVICE_BUS_CONNECTION_STRING", raising=False)
    else:
        monkeypatch.setenv(
            "HAGLEITNER_SERVICE_BUS_CONNECTION_STRING", connection_string
        )
    if queue_name is None:
        monkeypatch.delenv("HAGLEITNER_QUEUE_NAME", raising=False)
    else:
        monkeypatch.setenv("HAGLEITNER_QUEUE_NAME", queue_name)

    with pytest.raises(SystemExit, match="Set HAGLEITNER_SERVICE_BUS_CONNECTION_STRING"):
        await debug_receiver._run()


async def test_run_receives_messages_and_logs_resource_values(monkeypatch, caplog):
    """The debug handler delegates decoded messages to resource logging."""
    monkeypatch.setenv("HAGLEITNER_SERVICE_BUS_CONNECTION_STRING", "secret")
    monkeypatch.setenv("HAGLEITNER_QUEUE_NAME", "queue-a")
    message = {"deviceInfo": {"deviceId": "device-1"}, "readings": []}
    receiver_args = []
    logged_messages = []

    async def fake_run_receiver(connection_string, queue_name, handler):
        receiver_args.append((connection_string, queue_name))
        await handler(message)

    monkeypatch.setattr(debug_receiver, "run_receiver", fake_run_receiver)
    monkeypatch.setattr(
        debug_receiver,
        "log_resource_values",
        lambda value, _logger: logged_messages.append(value),
    )
    caplog.set_level(logging.INFO, logger=debug_receiver._LOGGER.name)

    await debug_receiver._run()

    assert receiver_args == [("secret", "queue-a")]
    assert logged_messages == [message]
    assert "Received resource-data message" in caplog.text


def test_main_runs_listener(monkeypatch):
    """The executable entry point schedules the async receiver."""
    coroutines = []

    def fake_run(coroutine):
        coroutines.append(coroutine)
        coroutine.close()

    monkeypatch.setattr(debug_receiver.asyncio, "run", fake_run)

    debug_receiver.main()

    assert len(coroutines) == 1


def test_main_logs_clean_keyboard_interrupt(monkeypatch, caplog):
    """Ctrl-C is reported as a normal receiver shutdown."""

    def interrupt(coroutine):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(debug_receiver.asyncio, "run", interrupt)
    caplog.set_level(logging.INFO, logger=debug_receiver._LOGGER.name)

    debug_receiver.main()

    assert "Receiver stopped" in caplog.text
