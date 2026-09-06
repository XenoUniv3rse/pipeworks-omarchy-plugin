"""Cleanup for the metering processes older versions spawned.

Metering itself has moved to the window, which reads PipeWire peaks directly
rather than streaming raw PCM through a pw-cat child per strip. This module
survives only to clear up after a version that did: those children outlive a
daemon that was killed rather than closed, so an upgrade would otherwise
inherit a pile of them.
"""
from .. import settings


def clear_stale_meters(runner):
    """Kills metering processes left behind by a previous run.

    The meters are child processes of a daemon thread: if the app is killed
    rather than closed cleanly it never gets to terminate them, and they
    accumulate across restarts.
    """
    runner.run("pkill", "-f", f"node.name={settings.METER_NODE_PREFIX}")
