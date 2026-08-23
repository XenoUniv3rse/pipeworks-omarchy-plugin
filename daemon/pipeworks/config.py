"""Configuration schema and persistence.

DEFAULT_CONFIG describes the shape; ConfigRepository owns reading, migrating and
writing it. Nothing here knows about audio or the UI - callers mutate the plain
dict they get back and ask the repository to save it, so persistence stays out of
the domain layer.
"""
import copy
import json
import os

from . import settings

DEFAULT_CONFIG = {
    # Virtual channels: sinks that applications play into.
    "channels": [
        {"id": "system", "label": "System", "sink": "vchan_system"},
        {"id": "game", "label": "Game", "sink": "vchan_game"},
        {"id": "music", "label": "Music", "sink": "vchan_music"},
        {"id": "browser", "label": "Browser", "sink": "vchan_browser"},
        {"id": "chat", "label": "Chat", "sink": "vchan_chat"},
    ],
    # Hardware capture devices. Each is fed into its own virtual sink whose
    # loopback output is published as an Audio/Source, so apps (Discord, OBS)
    # can select it as a microphone with this mixer's volume/mute applied.
    "inputs": [
        {
            "id": "mic",
            "label": "Mic",
            "source": "alsa_input.usb-MV-SILICON_fifine_Microphone_20190808-00.analog-stereo",
            "target_sink": "virtual_mic",
        }
    ],
    # Physical output devices, addressed by their playback ports.
    "outputs": [
        {
            "id": "master",
            "label": "Headset",
            "port_l": "alsa_output.usb-SteelSeries_Arctis_Pro_Wireless-00.stereo-game:playback_FL",
            "port_r": "alsa_output.usb-SteelSeries_Arctis_Pro_Wireless-00.stereo-game:playback_FR",
        },
        {
            "id": "speakers",
            "label": "Speakers",
            "port_l": "alsa_output.pci-0000_09_00.4.analog-stereo:playback_FL",
            "port_r": "alsa_output.pci-0000_09_00.4.analog-stereo:playback_FR",
        },
    ],
    # Per-strip state for channels and inputs, keyed by strip id.
    "volume": {"system": 70, "game": 70, "music": 70, "browser": 70, "chat": 70, "mic": 70},
    "muted": {"system": False, "game": False, "music": False, "browser": False, "chat": False, "mic": False},
    "solo": {"system": False, "game": False, "music": False, "browser": False, "chat": False},
    "routes": {
        "system": {"master": True, "speakers": True},
        "game": {"master": True, "speakers": True},
        "music": {"master": True, "speakers": True},
        "browser": {"master": True, "speakers": True},
        "chat": {"master": True, "speakers": True},
    },
    # Physical output state, independent of any channel.
    "output_volume": {"master": 100, "speakers": 100},
    "output_muted": {"master": False, "speakers": False},
    "output_solo": {"master": False, "speakers": False},
    # Control-surface bindings.
    "midi": {
        "volume_cc": {"system": 41, "game": 42, "music": 43, "browser": 44, "chat": 45, "mic": 40},
        "mute_note": {"system": 17, "game": 18, "music": 19, "browser": 20, "chat": 21, "mic": 16},
        "solo_note": {"system": 9, "game": 10, "music": 11, "browser": 12, "chat": 13},
        "route_note": {},  # keys are "channel:output"
        "output_volume_cc": {},  # keys are output ids
        "output_mute_note": {},
        "output_solo_note": {},
    },
}


class ConfigRepository:
    def __init__(self, path=settings.CONFIG_PATH):
        self._path = path

    def exists(self):
        return os.path.exists(self._path)

    def load(self):
        source = self._path if self.exists() else self._legacy_config()
        if source is None:
            return copy.deepcopy(DEFAULT_CONFIG)
        with open(source) as handle:
            config = json.load(handle)
        return self._migrate(config)

    @staticmethod
    def _legacy_config():
        """A config written under a previous name, so a rename does not throw
        away learned MIDI bindings and channel layouts."""
        return next(
            (path for path in settings.LEGACY_CONFIG_PATHS if os.path.exists(path)), None
        )

    def save(self, config):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as handle:
            json.dump(config, handle, indent=2)

    @staticmethod
    def _migrate(config):
        """Brings older files up to the current shape.

        Kept permissive on purpose: a config written by an earlier version should
        keep working rather than reset a user's carefully learned MIDI map.
        """
        # Inputs were once a single hardcoded "mic" entry rather than a list.
        if "mic" in config and "inputs" not in config:
            config["inputs"] = [config.pop("mic")]

        for key, value in DEFAULT_CONFIG.items():
            config.setdefault(key, copy.deepcopy(value))
        for key, value in DEFAULT_CONFIG["midi"].items():
            config["midi"].setdefault(key, copy.deepcopy(value))
        return config
