"""Peak metering by streaming raw PCM out of the graph.

Each meter is a pw-cat child process whose stdout this thread reads, reporting
peaks through an injected dispatcher so the caller decides how to get back onto
its UI thread.

Two hard-won details are load-bearing here:

* An earlier version used pulsectl's peak-sample API. Its internal libpulse
  event loop reliably segfaults when combined with GTK's main loop in one
  process, so reading raw audio via pw-cat sidesteps the problem entirely.
* pw-cat's --target does not resolve a sink's PulseAudio-style ".monitor" name;
  it silently falls back to the default source, which produced meters that all
  showed the microphone. Auto-connect is therefore disabled and the wanted
  ports are linked by name once the node registers.
"""
import threading
import time

import numpy as np

from .. import settings


class PeakMeter(threading.Thread):
    CHUNK_BYTES = 4096
    CHUNKS_PER_REPORT = 5  # ~10 reports/sec, plenty for a level meter
    LINK_ATTEMPTS = 20
    LINK_RETRY_SECONDS = 0.1

    def __init__(self, runner, source_ports, node_name, on_peak, dispatch):
        super().__init__(daemon=True)
        self._runner = runner
        self._source_l, self._source_r = source_ports
        self._node_name = node_name
        self._on_peak = on_peak
        self._dispatch = dispatch
        self._stop = threading.Event()
        self._process = None

    def run(self):
        self._process = self._runner.popen(
            [
                "pw-cat", "--record", "--raw",
                "--target", "0",  # linked by name below instead
                "-P", f"node.name={self._node_name}",
                "--format", "s16", "--rate", "48000", "--channels", "2", "-",
            ]
        )
        threading.Thread(target=self._link_when_ready, daemon=True).start()
        try:
            self._read_loop()
        finally:
            self._terminate()

    def _read_loop(self):
        running_peak = 0.0
        chunks = 0
        while not self._stop.is_set():
            chunk = self._process.stdout.read(self.CHUNK_BYTES)
            if not chunk:
                break
            usable = (len(chunk) // 2) * 2
            samples = np.frombuffer(chunk[:usable], dtype="<i2")
            if samples.size:
                running_peak = max(running_peak, float(np.abs(samples).max()) / 32768.0)
            chunks += 1
            if chunks >= self.CHUNKS_PER_REPORT:
                self._dispatch(self._on_peak, running_peak)
                running_peak = 0.0
                chunks = 0

    def _link_when_ready(self):
        """The node takes a moment to appear, so retry rather than race it."""
        for _attempt in range(self.LINK_ATTEMPTS):
            left = self._runner.succeeded("pw-link", self._source_l, f"{self._node_name}:input_FL")
            right = self._runner.succeeded("pw-link", self._source_r, f"{self._node_name}:input_FR")
            if left and right:
                return
            time.sleep(self.LINK_RETRY_SECONDS)

    def _terminate(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()

    def stop(self):
        self._stop.set()
        self._terminate()


def clear_stale_meters(runner):
    """Kills metering processes left behind by a previous run.

    The meters are child processes of a daemon thread: if the app is killed
    rather than closed cleanly it never gets to terminate them, and they
    accumulate across restarts.
    """
    runner.run("pkill", "-f", f"node.name={settings.METER_NODE_PREFIX}")
