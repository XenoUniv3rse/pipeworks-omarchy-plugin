"""Port-name discovery.

Port naming cannot be assumed, and guessing it produces links that fail
silently rather than loudly:

* Not every device is stereo. A headset's chat output/mic exposes a single
  "_MONO" port and no FL/FR at all.
* A loopback's outward-facing side is named "output_*" while it is a plain
  Stream, but "capture_*" once it is declared an Audio/Source.

Mono devices get both channels pointed at their single port; PipeWire sums
into it happily.
"""


class PortResolver:
    def __init__(self, runner):
        self._runner = runner

    def playback(self, sink_name):
        """(left, right) input ports of an output device."""
        return self._pair(sink_name, "-i", "playback")

    def capture(self, source_name):
        """(left, right) output ports of a capture device."""
        return self._pair(source_name, "-o", "capture")

    def monitor(self, sink_name):
        """(left, right) monitor taps of an output device."""
        return self._pair(sink_name, "-o", "monitor")

    def node_outputs(self, node_name):
        """(left, right) output ports of a node, whatever they are called.

        Used to tap a strip's post-volume signal for metering, where the prefix
        differs between channel and input loopbacks.
        """
        return self._pair(node_name, "-o")

    def _pair(self, device_name, list_flag, port_prefix=""):
        result = self._runner.capture("pw-link", list_flag)
        ports = []
        if result.returncode == 0:
            prefix = f"{device_name}:{port_prefix}"
            ports = [
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip().startswith(prefix)
            ]

        left = next((p for p in ports if p.endswith("_FL")), None)
        right = next((p for p in ports if p.endswith("_FR")), None)
        if left and right:
            return left, right
        mono = next((p for p in ports if p.endswith("_MONO")), None)
        if mono:
            return mono, mono
        if ports:
            return ports[0], ports[-1]
        # Device absent right now; assume stereo so stored config stays readable.
        return f"{device_name}:{port_prefix}_FL", f"{device_name}:{port_prefix}_FR"
