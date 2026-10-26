"""The always-on part of the mixer.

Everything here must keep working with no window open: the control surface is
useless if closing the UI stops MIDI being handled, and links dropped by a
PipeWire restart have to be repaired whether or not anyone is looking.

The window is a view attached to this service, not the other way round - and it
now lives in another process entirely, so "attached" means it watches the state
this service publishes and sends commands back over the session bus.
"""
import sys

from gi.repository import GLib

from . import autostart as autostart_module
from . import settings
from .audio.ducking import Ducker
from .audio.metering import clear_stale_meters
from .audio.mixer import Mixer
from .config import ConfigRepository
from .midi.bindings import MidiBindings, binding_channel
from .midi.controller import MidiController, MidiPortsNotFound, NullMidiController, probe_ports
from .keyboard import FINE_STEP, STEP, KeyboardControl
from .osd import OsdNotifier, describe_surface_change
from .pipewire.backend import PipeWireBackend
from .publish import StatePublisher
from .pipewire.devices import DeviceRegistry
from .pipewire.filters import FilterChainHost
from .pipewire.graph import GraphLinker
from .pipewire.ports import PortResolver
from .pipewire.provisioning import LoopbackProvisioner
from .pipewire.streams import StreamRouter
from .runner import CommandRunner


def fit_defaults_to_machine(config, devices, ports, boards=()):
    """Points a first-run config at this machine's own devices.

    The built-in defaults name one particular desktop's headset, speakers and
    microphone; on any other machine they are devices that do not exist, so a
    fresh install played into nothing. Use this machine's default output and
    microphone instead, falling back to the first real one of each.
    """
    outputs = devices.output_devices()
    default_sink = devices.default_sink()
    sink = next((name for name, _ in outputs if name == default_sink),
                outputs[0][0] if outputs else None)

    output_ids = []
    if sink:
        port_l, port_r = ports.playback(sink)
        config["outputs"] = [{"id": "master", "label": "Main", "port_l": port_l,
                              "port_r": port_r, "effects": {}}]
        output_ids = ["master"]
    else:
        config["outputs"] = []
    for store, value in (("output_volume", 100), ("output_muted", False), ("output_solo", False)):
        config[store] = {out_id: value for out_id in output_ids}

    inputs = devices.input_devices()
    default_source = devices.default_source()
    source = next((name for name, _ in inputs if name == default_source),
                  inputs[0][0] if inputs else None)
    for inp in config["inputs"]:
        inp["sources"] = [{"name": source, "volume": 100}] if source else []

    for chan in config["channels"]:
        config["routes"][chan["id"]] = {out_id: True for out_id in output_ids}
    for inp in config["inputs"]:
        config["routes"][inp["id"]] = {out_id: False for out_id in output_ids}

    # No board plugged in - a laptop, typically - means the volume keys are
    # the control surface to start with, on the first output. Otherwise they
    # would keep changing the default sink, which is now a channel, behind
    # the mixer's back.
    if not boards:
        config["control_surface"] = "keyboard"
        config["keyboard_target"] = ""
    elif not any(config.get("midi_port_match", "") in board for board in boards):
        config["midi_port_match"] = boards[0]


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

        ports = PortResolver(self.runner)
        self.devices = DeviceRegistry(self.runner)

        self.config = self.repository.load()
        # A config carried over from the plugin's old name is not a first run:
        # its devices are someone's real setup.
        self.first_run = not self.repository.exists() and self.repository.legacy_source() is None
        if self.first_run:
            fit_defaults_to_machine(self.config, self.devices, ports, self._detected_boards())
            self.repository.save(self.config)

        self.backend = PipeWireBackend(
            self.runner, ports, GraphLinker(self.runner), LoopbackProvisioner(self.runner)
        )
        self.streams = StreamRouter(self.runner, self.devices)

        self.filters = FilterChainHost(self.runner)
        self.filters.on_failed = self._on_effects_failed
        self.mixer = Mixer(
            self.config, self.repository, self.backend,
            scheduler=_glib_scheduler, filters=self.filters,
        )
        self.osd = OsdNotifier()
        self.ducker = Ducker(self.runner, dispatch=_glib_dispatch, scheduler=_glib_scheduler)
        self.bindings = MidiBindings(self.config, self.repository)
        self.keyboard = KeyboardControl(self.runner, dispatch=_glib_dispatch)
        self.midi = self._open_control_surface()
        self.autostart = autostart_module.create(self.runner)
        self.state = StatePublisher(
            self.streams, self.devices, self.midi, self.autostart, self.mixer,
            keyboard=self.keyboard,
        )

        self._heal_timer = None
        self._status_listener = None
        self._state_timer = None
        self._watch_expiry = 0

    # ------------------------------------------------------------------

    @staticmethod
    def _detected_boards():
        try:
            return probe_ports()
        except Exception:
            return []

    def _open_control_surface(self, port_match=None):
        # With the keyboard as the control surface no board is opened: the
        # two are alternatives, and a board left open would still answer.
        if self.config.get("control_surface") == "keyboard":
            return NullMidiController()
        if port_match is None:
            port_match = self.config.get("midi_port_match", settings.MIDI_PORT_MATCH)
        try:
            midi = MidiController(
                self.mixer, self.bindings, dispatch=_glib_dispatch, port_match=port_match
            )
        except MidiPortsNotFound as error:
            # Still fully usable by mouse; the board may just be unplugged.
            print(f"pipeworks: {error}; continuing without control surface", file=sys.stderr)
            return NullMidiController()
        return midi

    def set_midi_port(self, port_match):
        """Switches to a different control surface.

        The board just picked may not currently be plugged in - the same as at
        startup, that falls back to NullMidiController rather than raising, so
        a stale or wrong choice leaves the mixer usable by mouse instead of
        breaking the daemon.
        """
        self.config["midi_port_match"] = port_match
        self.config["control_surface"] = "midi"
        self.repository.save(self.config)

        self.midi.close()
        self.midi = self._open_control_surface(port_match)
        self.mixer.on_led = self.midi.reflect_change
        self.midi.on_learned = self._on_learned
        self.midi.on_surface = self._on_surface
        self.midi.sync_leds()
        self.state.set_midi(self.midi)
        self.apply_volume_keys()
        self._report(
            f"Connected to {port_match}" if self.midi.connected
            else f"{port_match} not found; still usable by mouse"
        )

    def use_keyboard(self):
        """Makes the volume keys the control surface, in place of a board."""
        self.config["control_surface"] = "keyboard"
        self.repository.save(self.config)
        self.midi.close()
        self.midi = NullMidiController()
        self.mixer.on_led = self.midi.reflect_change
        self.midi.on_learned = self._on_learned
        self.midi.on_surface = self._on_surface
        self.state.set_midi(self.midi)
        self.apply_volume_keys()
        self._report("The keyboard's volume keys now control Pipeworks")

    def apply_volume_keys(self):
        """What the volume keys do, from the control surface in use.

        Keyboard: they drive the chosen strip. A board that is connected, with
        the option on: they do nothing, so only the board moves levels.
        Otherwise - the option off, or a board chosen but not plugged in, when
        blocking them would leave no way to change the volume - they are left
        to whatever Hyprland binds them to.
        """
        if self.config.get("control_surface") == "keyboard":
            self.keyboard.enable()
        elif self.midi.connected and self.config.get("block_volume_keys_with_board", True):
            self.keyboard.block()
        else:
            self.keyboard.disable()

    def set_block_volume_keys(self, block):
        self.config["block_volume_keys_with_board"] = bool(block)
        self.repository.save(self.config)
        self.apply_volume_keys()
        self.state.publish()

    def keyboard_volume(self, command):
        """One press of a volume key."""
        kind, strip_id = self.mixer.keyboard_target()
        if strip_id is None:
            return
        if command == "mute":
            if kind == "output":
                self.mixer.toggle_output_mute(strip_id)
                self._on_surface("press", "output_mute_note", strip_id, None)
            else:
                self.mixer.toggle_mute(strip_id)
                self._on_surface("press", "mute_note", strip_id, None)
            return
        step = {"up": STEP, "down": -STEP, "up-fine": FINE_STEP, "down-fine": -FINE_STEP}.get(command)
        if step is None:
            return
        self.mixer.nudge(kind, strip_id, step)
        self._on_surface("level", "output_volume_cc" if kind == "output" else "volume_cc",
                         strip_id, None)

    def unbind(self, kind, key):
        """Clears one control-surface binding.

        A button that no longer controls anything must not keep showing the
        state of the thing it used to, so its LED goes dark - and the rest are
        re-synced in case another binding shares that note and should stay lit.
        """
        bound = self.bindings.unassign(kind, key)
        if bound is None:
            return
        if self.bindings.is_note_kind(kind):
            self.midi.set_led(bound, False)
            self.midi.sync_leds()

    def start(self):
        """Brings the graph up to match saved state and starts watching it."""
        self.mixer.on_led = self.midi.reflect_change
        self.midi.on_surface = self._on_surface
        # Through self.midi at call time: set_midi_port swaps the controller.
        self.mixer.on_leds_changed = lambda: self.midi.sync_leds()
        self.mixer.on_status = self._report
        self.ducker.on_trigger = self.mixer.set_trigger_active
        self.mixer.on_ducking_changed = lambda: self.ducker.sync(self.config)
        self.midi.on_learned = self._on_learned
        provisioned = self.backend.ensure_provisioned(self.config["channels"], self.config["inputs"])
        self.mixer.apply_all()
        self.midi.sync_leds()
        self.ducker.sync(self.config)
        # Runtime bindings do not survive a login, so take the keys again.
        self.apply_volume_keys()
        if self.first_run and self.config["channels"]:
            # A mixer nobody plays into does nothing: send new apps to the
            # first channel, once, on the very first start.
            self.devices.set_default_sink(self.config["channels"][0]["sink"])
        if provisioned:
            self._report("Created the virtual channels and microphone")
        if self._heal_timer is None:
            self._heal_timer = GLib.timeout_add_seconds(
                settings.GRAPH_HEAL_SECONDS, self._check_graph
            )

    def stop(self):
        if self._heal_timer is not None:
            GLib.source_remove(self._heal_timer)
            self._heal_timer = None
        self._stop_state_timer()
        # Effect chains are our children; leaving them running would orphan a
        # pipewire process per strip every time the daemon restarts.
        self.filters.stop_all()
        self.ducker.stop_all()

    # ------------------------------------------------------------------
    # Published state
    #
    # Refreshing it costs a pactl call, so it runs only while a window says it
    # is looking. The window renews that interest periodically rather than
    # promising to switch it off, because a window that was killed never gets
    # to send anything again - and a daemon left polling forever is a bug
    # nobody would notice until they looked at a process list.

    def set_state_watch(self, watching):
        if not watching:
            self._stop_state_timer()
            return
        self._watch_expiry = (
            GLib.get_monotonic_time() / 1e6 + settings.STATE_WATCH_TIMEOUT_SECONDS
        )
        # Publish at once: the window is waiting on the file right now.
        self.state.clear()
        self.state.publish()
        if self._state_timer is None:
            self._state_timer = GLib.timeout_add_seconds(
                settings.STATE_POLL_SECONDS, self._refresh_state
            )

    def _refresh_state(self):
        if GLib.get_monotonic_time() / 1e6 > self._watch_expiry:
            self._state_timer = None
            return False
        self.state.publish()
        return True

    def _stop_state_timer(self):
        if self._state_timer is not None:
            GLib.source_remove(self._state_timer)
            self._state_timer = None

    def _on_learned(self, kind, key, number, displaced=()):
        """A control surface binding just completed.

        The controller has already stored and saved it, so all that is left is
        lighting the board correctly and telling the window - which is watching
        the state file for exactly this, since "waiting for a knob" has to stop
        looking like it is still waiting. If the control was taken from another
        binding, that is said out loud: the other one just stopped working.

        Runs on the main loop: the controller marshals MIDI messages there
        before handling them, so this is not on the rtmidi thread.
        """
        self.midi.sync_leds()
        if displaced:
            control = ("Note " if self.bindings.is_note_kind(kind) else "CC ") + str(number)
            channel = binding_channel(self.bindings.get(kind, key))
            if channel is not None:
                control += f" (ch {channel + 1})"
            previous = ", ".join(self.describe_binding(k, s) for k, s in displaced)
            self._report(f"{control} moved from {previous} to {self.describe_binding(kind, key)}")
        else:
            self.state.publish()

    _BINDING_CAPTIONS = {
        "scene_note": "Recall",
        "volume_cc": "Volume", "mute_note": "Mute", "solo_note": "Solo",
        "output_volume_cc": "Volume", "output_mute_note": "Mute",
        "output_solo_note": "Solo",
    }

    def _on_surface(self, event, kind, key, value):
        """The board changed something: show it, unless that is switched off."""
        if not self.config.get("midi_osd", True):
            return
        payload = describe_surface_change(self.mixer, event, kind, key, value)
        if payload:
            self.osd.show(payload)

    def _on_effects_failed(self, strip_id):
        entity = self.mixer.inputs_by_id.get(strip_id) or self.mixer.outputs_by_id.get(strip_id)
        label = entity.get("label", strip_id) if entity else strip_id
        self._report(f"Effects on {label} could not start - playing without them")

    def describe_binding(self, kind, key):
        """What a binding drives, the way the window names it: "Game · Mute"."""
        mixer = self.mixer

        def label(table, strip_id):
            entity = table.get(strip_id)
            return entity.get("label", strip_id) if entity else strip_id

        if kind == "scene_note":
            scene = self.mixer.scene(key)
            return f"Scene {scene.get('label', key) if scene else key} · Recall"
        if kind == "route_note":
            chan_id, _, out_id = key.partition(":")
            strips = {**mixer.channels_by_id, **mixer.inputs_by_id}
            return f"{label(strips, chan_id)} · Route to {label(mixer.outputs_by_id, out_id)}"
        if kind.startswith("output_"):
            strip = label(mixer.outputs_by_id, key)
        else:
            strip = label({**mixer.channels_by_id, **mixer.inputs_by_id}, key)
        return f"{strip} · {self._BINDING_CAPTIONS.get(kind, kind)}"

    # ------------------------------------------------------------------

    def set_status_listener(self, listener):
        """Lets a window display service messages while it happens to be open."""
        self._status_listener = listener

    def _report(self, message):
        # Published as well as pushed: the window that shows this is in another
        # process and reads it from the state file.
        self.state.set_status(message)
        self.state.publish()
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

