"""Ducking: lowering some channels while another one is active.

A channel can name a trigger - another channel, or an input - and an amount.
While the trigger is carrying sound, the channel plays that much quieter; when
the trigger has been quiet for a moment it comes back. The classic use is music
and game audio stepping aside while someone talks in Chat, or while your own
microphone is open.

Hearing whether a trigger is active needs its audio, so each trigger in use
gets one small capture process (pw-record on the trigger's sink monitor, mono,
at a low rate) whose samples are only ever measured, never kept. That costs a
process per trigger, not per ducked channel, and nothing at all while no
channel ducks.

The fader is never moved: ducking scales the level the mixer applies, and the
level shown and saved is still the one you set.
"""
import array
import os
import select
import shutil
import threading
import time

from .. import settings

# Prefix for the capture nodes, so strays from a daemon that was killed can be
# found and stopped, and so they are recognisable in a patchbay.
DUCK_NODE_PREFIX = "pipeworks_duck"

_RATE = 8000
_BLOCK_SAMPLES = 160  # 20 ms
_BLOCK_BYTES = _BLOCK_SAMPLES * 2


def duck_amount(channel):
    """How far a channel is lowered while ducked, 0-100, or 0 for not at all."""
    duck = channel.get("duck") or {}
    if not duck.get("trigger"):
        return 0
    return max(0, min(100, float(duck.get("amount", settings.DUCK_DEFAULT_AMOUNT))))


def wanted_triggers(config):
    """Trigger strip id -> sink to listen on, for every trigger some channel uses."""
    sinks = {c["id"]: c["sink"] for c in config["channels"]}
    sinks.update({i["id"]: i["target_sink"] for i in config["inputs"]})
    wanted = {}
    for channel in config["channels"]:
        trigger = (channel.get("duck") or {}).get("trigger")
        if trigger and trigger != channel["id"] and trigger in sinks and duck_amount(channel) > 0:
            wanted[trigger] = sinks[trigger]
    return wanted


class TriggerListener:
    """Watches one trigger's audio and reports when it starts and stops.

    Runs a reader thread; on_change(active) is handed to the dispatcher so it
    lands on the main loop, never on the reader thread.
    """

    def __init__(self, trigger_id, sink, dispatch, on_change, on_exit, popen):
        self.trigger_id = trigger_id
        self.sink = sink
        self._dispatch = dispatch
        self._on_change = on_change
        self._on_exit = on_exit
        self._stopping = False
        self.active = False
        self._process = popen(self._command())
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _command(self):
        node = f"{DUCK_NODE_PREFIX}_{self.trigger_id}"
        props = (
            "{ stream.capture.sink = true node.dont-reconnect = true "
            f"node.name = {node} media.name = \"Pipeworks ducking ({self.trigger_id})\" }}"
        )
        return [
            shutil.which("pw-record") or "pw-record",
            "--target", self.sink, "-P", props,
            "--rate", str(_RATE), "--channels", "1", "--format", "s16", "-",
        ]

    def _read(self):
        threshold = int(32768 * 10 ** (settings.DUCK_THRESHOLD_DB / 20))
        hold = settings.DUCK_RELEASE_SECONDS
        stdout = self._process.stdout
        last_loud = 0.0
        settled_at = time.monotonic() + settings.DUCK_SETTLE_SECONDS
        pending = b""
        while not self._stopping:
            # A timeout as well as data: if the stream stalls (the trigger's
            # sink went away) silence must still end the duck.
            ready, _, _ = select.select([stdout], [], [], 0.1)
            now = time.monotonic()
            if ready:
                chunk = os.read(stdout.fileno(), 4096)
                if not chunk:
                    break  # the capture process exited
                pending += chunk
                usable = len(pending) - len(pending) % 2
                if usable:
                    samples = array.array("h", pending[:usable])
                    pending = pending[usable:]
                    if (now >= settled_at and samples
                            and max(max(samples), -min(samples)) >= threshold):
                        last_loud = now
            loud = now - last_loud < hold
            if loud != self.active:
                self.active = loud
                self._dispatch(self._on_change, self.trigger_id, loud)
        if self.active:
            self.active = False
            self._dispatch(self._on_change, self.trigger_id, False)
        if not self._stopping:
            self._dispatch(self._on_exit, self.trigger_id)

    def stop(self):
        self._stopping = True
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()
        self._thread.join(timeout=1)


class Ducker:
    """Keeps one listener per trigger in use and tells the mixer what is active."""

    def __init__(self, runner, dispatch, scheduler):
        self._runner = runner
        self._dispatch = dispatch
        self._schedule = scheduler
        self._listeners = {}
        self._config = None
        self.on_trigger = lambda trigger_id, active: None
        self.clear_strays()

    def clear_strays(self):
        """Stops capture processes a killed daemon left behind."""
        self._runner.run("pkill", "-f", f"node.name = {DUCK_NODE_PREFIX}_")

    def active_triggers(self):
        return {t for t, listener in self._listeners.items() if listener.active}

    def sync(self, config):
        """Starts and stops listeners to match what the channels ask for."""
        self._config = config
        wanted = wanted_triggers(config)
        for trigger_id in list(self._listeners):
            listener = self._listeners[trigger_id]
            if wanted.get(trigger_id) != listener.sink:
                self._stop(trigger_id)
        for trigger_id, sink in wanted.items():
            if trigger_id not in self._listeners:
                self._listeners[trigger_id] = TriggerListener(
                    trigger_id, sink, self._dispatch,
                    self._changed, self._exited, self._runner.popen,
                )

    def stop_all(self):
        for trigger_id in list(self._listeners):
            self._stop(trigger_id)

    def _stop(self, trigger_id):
        listener = self._listeners.pop(trigger_id, None)
        if listener:
            listener.stop()
            if listener.active:
                self.on_trigger(trigger_id, False)

    def _changed(self, trigger_id, active):
        if trigger_id in self._listeners:
            self.on_trigger(trigger_id, active)

    def _exited(self, trigger_id):
        """A capture died - usually PipeWire restarting. Try again shortly."""
        self._listeners.pop(trigger_id, None)
        self.on_trigger(trigger_id, False)

        def retry():
            if self._config is not None:
                self.sync(self._config)
        self._schedule(int(settings.DUCK_RETRY_SECONDS * 1000), retry)
