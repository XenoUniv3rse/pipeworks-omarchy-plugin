"""The always-on part of the mixer.

Everything here must keep working with no window open: the control surface is
useless if closing the UI stops MIDI being handled, and links dropped by a
PipeWire restart have to be repaired whether or not anyone is looking.

The window is a view attached to this service, not the other way round.
"""
import sys

from gi.repository import GLib

from . import autostart as autostart_module
from . import settings
from .audio.metering import PeakMeter, clear_stale_meters
from .audio.mixer import Mixer
from .config import ConfigRepository
from .midi.bindings import MidiBindings
from .midi.controller import MidiController, MidiPortsNotFound, NullMidiController
from .pipewire.backend import PipeWireBackend
from .pipewire.devices import DeviceRegistry
from .pipewire.graph import GraphLinker
from .pipewire.ports import PortResolver
from .pipewire.provisioning import LoopbackProvisioner
from .pipewire.streams import StreamRouter
from .runner import CommandRunner


def _glib_scheduler(delay_ms, callback):
    """One-shot deferral, so the domain layer never imports GLib itself."""
    GLib.timeout_add(delay_ms, lambda: (callback(), False)[1])


def _glib_dispatch(callback, *args):
    """Marshals a worker-thread callback onto the main loop."""
    GLib.idle_add(callback, *args)


class MixerService:
    def __init__(self, runner=None, repository=None):
        self.runner = runner or CommandRunner()
        self.repository = repository or ConfigRepository()

        clear_stale_meters(self.runner)

        self.config = self.repository.load()
        if not self.repository.exists():
            self.repository.save(self.config)

        ports = PortResolver(self.runner)
        self.backend = PipeWireBackend(
            self.runner, ports, GraphLinker(self.runner), LoopbackProvisioner(self.runner)
        )
        self.devices = DeviceRegistry(self.runner)
        self.streams = StreamRouter(self.runner, self.devices)

        self.mixer = Mixer(
            self.config, self.repository, self.backend, scheduler=_glib_scheduler
        )
        self.bindings = MidiBindings(self.config, self.repository)
        self.midi = self._open_control_surface()
        self.autostart = autostart_module.create(self.runner)

        self._heal_timer = None
        self._status_listener = None

    # ------------------------------------------------------------------

    def _open_control_surface(self):
        try:
            midi = MidiController(self.mixer, self.bindings, dispatch=_glib_dispatch)
        except MidiPortsNotFound as error:
            # Still fully usable by mouse; the board may just be unplugged.
            print(f"pipeworks: {error}; continuing without control surface", file=sys.stderr)
            return NullMidiController()
        return midi

    def start(self):
        """Brings the graph up to match saved state and starts watching it."""
        self.mixer.on_led = self.midi.reflect_change
        self.mixer.apply_all()
        self.midi.sync_leds()
        if self._heal_timer is None:
            self._heal_timer = GLib.timeout_add_seconds(
                settings.GRAPH_HEAL_SECONDS, self._check_graph
            )

    def stop(self):
        if self._heal_timer is not None:
            GLib.source_remove(self._heal_timer)
            self._heal_timer = None

    # ------------------------------------------------------------------

    def set_status_listener(self, listener):
        """Lets a window display service messages while it happens to be open."""
        self._status_listener = listener

    def _report(self, message):
        if self._status_listener:
            self._status_listener(message)

    def _check_graph(self):
        """Repairs links that PipeWire dropped.

        Runs with or without a window: a restart at boot must be healed before
        anyone opens the UI, or audio silently goes nowhere.
        """
        missing = self.mixer.missing_links()
        if missing:
            self.mixer.apply_all()
            self._report(f"Reconnected {len(missing)} audio link(s)")
        return True

    # ------------------------------------------------------------------

    def create_meter(self, node_name, source_ports, on_level):
        """Meters exist only while a window is open, so the service hands out
        the factory rather than owning any."""
        return PeakMeter(
            self.runner, source_ports, node_name, on_level, dispatch=_glib_dispatch
        )
