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

# Daemon state published for out-of-process front ends: what is playing, which
# devices exist, whether a MIDI Learn is waiting. Sits beside the config so a
# window watching one is watching the other in the same directory.
STATE_PATH = os.path.expanduser("~/.config/pipeworks/state.json")

# Generated filter-chain configs, one per strip that carries effects. Each is
# run by its own `pipewire -c` process so switching an effect on restarts that
# chain alone rather than the whole audio server.
FX_CONF_DIR = os.path.expanduser("~/.config/pipeworks/effects")

# Prefix for the nodes a filter chain publishes, so the graph can find them.
FX_NODE_PREFIX = "pipeworks_fx"

# Locations used before the application was renamed. Read once to carry a
# user's settings across, and cleaned up so stale virtual-device definitions
# cannot be loaded alongside the current ones.
LEGACY_CONFIG_PATHS = (os.path.expanduser("~/.config/smc-mixer/config.json"),)
LEGACY_PIPEWIRE_CONF_PATHS = (
    os.path.expanduser("~/.config/pipewire/pipewire.conf.d/10-virtual-channels.conf"),
)

# Substring identifying the control surface's MIDI port.
MIDI_PORT_MATCH = "SMC-Mixer-Private"

# Soft takeover: after a level is changed from anywhere but the board, a
# physical fader only takes control again once it comes within this many
# percent of the current level, or passes through it.
SOFT_TAKEOVER_TOLERANCE = 3

# Ducking: a trigger counts as active while its peak is above this level, and
# for this long after it last was - long enough to ride over the gaps between
# words, so a ducked channel does not pump up and down mid-sentence.
DUCK_THRESHOLD_DB = -40.0
DUCK_RELEASE_SECONDS = 0.8
DUCK_DEFAULT_AMOUNT = 50
# A new capture's first moments are not the trigger's audio - pw-record opens
# with a transient that measured near full scale - so they are ignored.
DUCK_SETTLE_SECONDS = 0.3
# Coming back up is eased over a few steps rather than snapped.
DUCK_FADE_STEPS = 4
DUCK_FADE_STEP_MS = 70
# A trigger's capture that died (PipeWire restarting) is retried after this.
DUCK_RETRY_SECONDS = 3

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

# How often published state is refreshed while a window is watching it. Each
# refresh costs a pactl call, so nothing polls unless a window asked it to.
STATE_POLL_SECONDS = 2

# A watching window renews its interest this often; the daemon stops polling
# once a window has gone this long without renewing, so a window that crashed
# or was killed cannot leave the daemon polling forever.
STATE_WATCH_TIMEOUT_SECONDS = 15
