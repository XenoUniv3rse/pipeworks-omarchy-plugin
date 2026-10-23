"""Showing control-surface changes on screen.

Moving a fader or pressing a button on the board changes something you cannot
see unless the mixer happens to be open. This puts it on the shell's own OSD -
the same one the volume keys use - so a press reads as "Chat muted" and a fader
as "Music 45%".

The OSD is reached through the shell's IPC command line. A plugin's QML may not
summon another plugin directly, and this process is not QML at all; the
command line is the documented way in for both. A fader sweep produces dozens
of changes a second and each call is a process, so calls run one at a time on
a worker thread and only the newest pending payload is ever sent.
"""
import json
import shutil
import subprocess
import threading


class OsdNotifier:
    COMMAND = ("omarchy-shell", "-q", "shell", "summon", "omarchy.osd")

    def __init__(self):
        self._available = shutil.which(self.COMMAND[0]) is not None
        self._pending = None
        self._wake = threading.Condition()
        # Whether a worker is running, changed only under the lock: a worker
        # deciding to exit and a new payload arriving must not miss each other.
        self._working = False

    def show(self, payload):
        """Queues a payload, replacing any not yet sent."""
        if not self._available:
            return
        with self._wake:
            self._pending = json.dumps(payload)
            if not self._working:
                self._working = True
                threading.Thread(target=self._run, daemon=True).start()
            self._wake.notify()

    def _run(self):
        while True:
            with self._wake:
                if self._pending is None:
                    # Idle a while: let the thread go rather than keep one
                    # parked for a board nobody is touching.
                    self._wake.wait(timeout=5)
                    if self._pending is None:
                        self._working = False
                        return
                payload, self._pending = self._pending, None
            try:
                subprocess.run(
                    (*self.COMMAND, payload), capture_output=True, timeout=3
                )
            except (OSError, subprocess.SubprocessError):
                pass


class NullOsdNotifier:
    def show(self, payload):
        pass


def describe_surface_change(mixer, event, kind, key, value=None):
    """The OSD payload for something the board just did, or None.

    event is "level" (a fader moved a level), "pickup" (a fader is waiting to
    take over and is not at the level yet) or "press" (a button did its thing).
    """
    def label(strip_id):
        entity = (mixer.channels_by_id.get(strip_id) or mixer.inputs_by_id.get(strip_id)
                  or mixer.outputs_by_id.get(strip_id))
        return entity.get("label", strip_id) if entity else strip_id

    config = mixer.config
    if event in ("level", "pickup"):
        store = "volume" if kind == "volume_cc" else "output_volume"
        current = round(config[store].get(key, 0))
        name = label(key)
        if event == "pickup":
            # Where the level is, and which way to move: the fader is ignored
            # until it gets there.
            direction = "up" if value is not None and value < current else "down"
            return {"icon": "volume", "value": current,
                    "progressText": f"{name}: move {direction} to {current}%"}
        icon = "volume-muted" if current <= 0 else "volume"
        if key in mixer.inputs_by_id:
            icon = "microphone-muted" if current <= 0 else "microphone"
        return {"icon": icon, "value": current, "progressText": f"{name}  {current}%"}

    if kind == "mute_note":
        muted = config["muted"].get(key, False)
        if key in mixer.inputs_by_id:
            icon = "microphone-muted" if muted else "microphone"
        else:
            icon = "volume-muted" if muted else "volume"
        return {"icon": icon, "message": f"{label(key)} {'muted' if muted else 'unmuted'}"}
    if kind == "output_mute_note":
        muted = config["output_muted"].get(key, False)
        return {"icon": "volume-muted" if muted else "volume",
                "message": f"{label(key)} {'muted' if muted else 'unmuted'}"}
    if kind in ("solo_note", "output_solo_note"):
        store = "solo" if kind == "solo_note" else "output_solo"
        on = config[store].get(key, False)
        return {"icon": "volume", "message": f"{label(key)} solo {'on' if on else 'off'}"}
    if kind == "route_note":
        chan_id, _, out_id = key.partition(":")
        on = config["routes"].get(chan_id, {}).get(out_id, False)
        arrow = "→" if on else "↛"
        return {"icon": "volume", "message": f"{label(chan_id)} {arrow} {label(out_id)}"}
    if kind == "scene_note":
        scene = mixer.scene(key)
        return {"icon": "volume", "message": f"Scene: {scene.get('label', key) if scene else key}"}
    return None
