"""PipeWire implementation of the AudioBackend protocol.

Composed from the focused helpers in this package rather than doing the work
itself, so each concern (ports, links, provisioning) stays independently
testable and callers depend only on the slice they need.
"""
import threading


class PipeWireBackend:
    def __init__(self, runner, ports, graph, provisioner):
        self._runner = runner
        self._ports = ports
        self._graph = graph
        self._provisioner = provisioner

    # --- level and mute -------------------------------------------------

    def set_sink_volume(self, sink_name, percent):
        # Off the calling thread: this runs on the UI thread in response to
        # fader movement, and a synchronous spawn per update visibly stutters.
        threading.Thread(
            target=self._runner.run,
            args=("pactl", "set-sink-volume", sink_name, f"{percent}%"),
            daemon=True,
        ).start()

    def set_sink_mute(self, sink_name, muted):
        self._runner.run("pactl", "set-sink-mute", sink_name, "1" if muted else "0")

    # --- graph ----------------------------------------------------------

    def connect(self, source_port, dest_port):
        self._graph.connect(source_port, dest_port)

    def disconnect(self, source_port, dest_port):
        self._graph.disconnect(source_port, dest_port)

    def present_links(self):
        return self._graph.present_links()

    # --- port discovery -------------------------------------------------

    def playback_ports(self, sink_name):
        return self._ports.playback(sink_name)

    def capture_ports(self, source_name):
        return self._ports.capture(source_name)

    def monitor_ports(self, sink_name):
        return self._ports.monitor(sink_name)

    def node_output_ports(self, node_name):
        return self._ports.node_outputs(node_name)

    # --- provisioning ---------------------------------------------------

    def provision(self, channels, inputs):
        self._provisioner.write(channels, inputs)
        self._provisioner.restart()
