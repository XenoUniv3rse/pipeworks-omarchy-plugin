"""Publishing daemon state for out-of-process front ends.

The mixer window is no longer part of this process - it is QML living in the
Omarchy shell. Commands reach the daemon as org.gtk.Actions, but a window also
needs to *read* things an action cannot return: what is playing, which devices
exist, whether a MIDI Learn is waiting for a knob. Those are published here as
one JSON file the window watches, the same way it already follows config.json.

Two things this deliberately does not do. It holds no timer of its own - the
service owns that, so this module stays free of GLib like the rest of the
domain layer. And it writes nothing unless the content actually changed: the
window watches the file, so a rewrite with identical contents would wake it up
several times a second for nothing.
"""
import json
import os
import tempfile

from . import settings
from .audio import effects as effects_module


class StatePublisher:
    def __init__(self, streams, devices, midi, autostart, mixer, path=settings.STATE_PATH):
        self._streams = streams
        self._devices = devices
        self._midi = midi
        self._autostart = autostart
        self._mixer = mixer
        self._path = path
        self._last = None
        self._status = ""
        self._status_serial = 0

    # ------------------------------------------------------------------

    def set_status(self, message):
        """Records a transient message for the window to surface.

        Carries a serial as well as the text: the window shows a status for a
        few seconds and the same message occurring twice is two events, which
        identical text alone would hide.
        """
        self._status = message
        self._status_serial += 1

    def snapshot(self):
        learning = getattr(self._midi, "learning", None)
        return {
            "streams": [
                {"index": s.index, "sink": s.sink_name, "app": s.app, "label": s.label}
                for s in self._streams.list_streams(self._mixer.loopback_output_names())
            ],
            "devices": {
                "outputs": [
                    {"name": name, "description": description}
                    for name, description in self._devices.output_devices()
                ],
                "inputs": [
                    {"name": name, "description": description}
                    for name, description in self._devices.input_devices()
                ],
            },
            "autostart": {
                "enabled": self._autostart.is_enabled(),
                "canToggle": getattr(self._autostart, "can_toggle", True),
                "description": self._autostart.describe(),
            },
            # A Learn in progress, so the window can show which control is
            # waiting rather than guessing from its own click.
            "learn": {
                "kind": learning[0] if learning else "",
                "key": learning[1] if learning else "",
            },
            "midiConnected": getattr(self._midi, "connected", False),
            # What effects exist and the range of every control. Published
            # rather than hardcoded in the window, so the two cannot disagree
            # about what a slider means.
            "effects": effects_module.catalogue(),
            "status": self._status,
            "statusSerial": self._status_serial,
        }

    def publish(self):
        """Writes the current snapshot, if it differs from the last one."""
        state = self.snapshot()
        if state == self._last:
            return False
        self._last = state
        self._write(state)
        return True

    def clear(self):
        """Forgets the last snapshot so the next publish always writes.

        Used when a window starts watching: it needs a file on disk now, even
        if nothing has changed since the previous window closed.
        """
        self._last = None

    # ------------------------------------------------------------------

    def _write(self, state):
        """Writes atomically, for the same reason the config does: the window
        watches this file, and a torn read there is a blanked panel."""
        directory = os.path.dirname(self._path)
        os.makedirs(directory, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(dir=directory, prefix=".state.", suffix=".json")
        try:
            with os.fdopen(handle, "w") as stream:
                json.dump(state, stream, indent=2)
            os.chmod(temp_path, 0o644)
            os.replace(temp_path, self._path)
        except BaseException:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
