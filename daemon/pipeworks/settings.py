"""Filesystem locations and tunables.

Kept free of behaviour so every other module can import it without pulling in
GTK, PipeWire or MIDI dependencies.
"""
import os

CONFIG_PATH = os.path.expanduser("~/.config/pipeworks/config.json")
PIPEWIRE_CONF_PATH = os.path.expanduser(
    "~/.config/pipewire/pipewire.conf.d/10-pipeworks.conf"
)
AUTOSTART_PATH = os.path.expanduser("~/.config/autostart/pipeworks.desktop")

# Locations used before the application was renamed. Read once to carry a
# user's settings across, and cleaned up so stale virtual-device definitions
# cannot be loaded alongside the current ones.
LEGACY_CONFIG_PATHS = (os.path.expanduser("~/.config/smc-mixer/config.json"),)
LEGACY_PIPEWIRE_CONF_PATHS = (
    os.path.expanduser("~/.config/pipewire/pipewire.conf.d/10-virtual-channels.conf"),
)

# Substring identifying the control surface's MIDI port.
MIDI_PORT_MATCH = "SMC-Mixer-Private"

# Faders can fire dozens of updates a second; volume writes are coalesced to
# at most one per this interval.
VOLUME_THROTTLE_SECONDS = 0.05

# Peaks at or below this map to the bottom of a meter.
METER_FLOOR_DB = -50.0

# How often the graph watchdog checks for links that PipeWire dropped.
GRAPH_HEAL_SECONDS = 5

# Prefix for the mixer's own metering nodes, used both to name them and to
# recognise strays left behind by a previous run.
METER_NODE_PREFIX = "pipeworks_meter"
