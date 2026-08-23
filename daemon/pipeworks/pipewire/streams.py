"""Listing application playback streams and moving them between sinks."""
import json
from dataclasses import dataclass

MAX_LABEL_CHARS = 45


@dataclass(frozen=True)
class AppStream:
    index: int
    sink_name: str
    label: str


class StreamRouter:
    def __init__(self, runner, devices):
        self._runner = runner
        self._devices = devices

    def list_streams(self, excluded_node_names=()):
        """Application streams, newest last.

        excluded_node_names lets the caller hide the mixer's own loopback
        outputs: they appear in the sink-input list indistinguishably from real
        application streams, so without filtering the mixer lists its own
        plumbing back to the user.
        """
        result = self._runner.capture("pactl", "--format=json", "list", "sink-inputs")
        if result.returncode != 0:
            return []
        try:
            entries = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        excluded = set(excluded_node_names)
        sink_names = self._devices.sink_names_by_index()
        streams = []
        for entry in entries:
            props = entry.get("properties") or {}
            if props.get("node.name") in excluded:
                continue
            streams.append(
                AppStream(
                    index=entry["index"],
                    sink_name=sink_names.get(entry.get("sink"), ""),
                    label=self._label_for(props),
                )
            )
        return streams

    def move(self, stream_index, sink_name):
        self._runner.run("pactl", "move-sink-input", str(stream_index), sink_name)

    @staticmethod
    def _label_for(props):
        app = props.get("application.name") or props.get("node.name") or "Unknown"
        media = props.get("media.name") or ""
        label = f"{app} - {media}" if media and media != app else app
        if len(label) > MAX_LABEL_CHARS:
            label = label[: MAX_LABEL_CHARS - 1] + "…"
        return label
