"""Focused checks for Home Assistant entity-platform quality rules."""

from custom_components.hagleitner_community import binary_sensor, sensor


def test_entity_platforms_define_parallel_updates():
    """Both push-based, read-only platforms declare their update limit."""
    assert sensor.PARALLEL_UPDATES == 0
    assert binary_sensor.PARALLEL_UPDATES == 0
