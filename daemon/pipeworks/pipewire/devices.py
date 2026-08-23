"""Enumeration of real hardware playback and capture devices."""
import json

_VIRTUAL_PREFIXES = ("vchan_", "virtual_")


class DeviceRegistry:
    def __init__(self, runner):
        self._runner = runner

    def output_devices(self):
        """Real (non-virtual) output devices as [(node_name, description)]."""
        return [
            (entry["name"], entry.get("description") or entry["name"])
            for entry in self._list("sinks")
            if not entry.get("name", "").startswith(_VIRTUAL_PREFIXES)
        ]

    def input_devices(self):
        """Real capture devices as [(node_name, description)].

        Excludes ".monitor" sources, which are loopbacks of a sink rather than
        capture hardware. The monitor_of_sink field is unreliable here -
        PipeWire reports null for all of them - so the name suffix is what
        actually identifies them.
        """
        devices = []
        for entry in self._list("sources"):
            name = entry.get("name", "")
            if name.endswith(".monitor") or name.startswith(_VIRTUAL_PREFIXES):
                continue
            devices.append((name, entry.get("description") or name))
        return devices

    def sink_names_by_index(self):
        """Maps numeric sink index to node name, for resolving stream targets."""
        try:
            return {entry["index"]: entry["name"] for entry in self._list("sinks")}
        except KeyError:
            return {}

    def _list(self, kind):
        result = self._runner.capture("pactl", "--format=json", "list", kind)
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
