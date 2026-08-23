"""The audio-engine abstraction the domain layer depends on.

Mixer is written against this protocol rather than against PipeWire, so the
engine can be swapped or faked in tests without touching mixing logic. The
PipeWire implementation lives in pipeworks.pipewire.backend.
"""
from typing import Iterable, Protocol, Tuple


class AudioBackend(Protocol):
    # --- level and mute -------------------------------------------------
    def set_sink_volume(self, sink_name: str, percent: float) -> None: ...

    def set_sink_mute(self, sink_name: str, muted: bool) -> None: ...

    # --- graph ----------------------------------------------------------
    def connect(self, source_port: str, dest_port: str) -> None: ...

    def disconnect(self, source_port: str, dest_port: str) -> None: ...

    def present_links(self) -> set: ...

    # --- port discovery -------------------------------------------------
    def playback_ports(self, sink_name: str) -> Tuple[str, str]: ...

    def capture_ports(self, source_name: str) -> Tuple[str, str]: ...

    # --- provisioning ---------------------------------------------------
    def provision(self, channels: Iterable[dict], inputs: Iterable[dict]) -> None:
        """Persist the virtual-device definitions and make them live."""
