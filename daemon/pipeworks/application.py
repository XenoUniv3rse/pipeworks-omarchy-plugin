"""The application: a resident, headless background process.

It owns no window. The mixer window and the bar widget are both QML living in
the Omarchy shell, so this process is purely the audio brain - virtual
channels, routing, MIDI, and the watchdog that repairs links PipeWire drops.

Lifecycle:

* Launched with --daemon (by the shell plugin or the systemd user unit) it
  starts the mixer service and shows nothing.
* Launched without --daemon it asks the shell to summon the mixer window, which
  is what clicking the desktop entry does. Because the application ID is
  registered on the session bus, a second launch does not start a second copy;
  it reaches the running one, which does the summoning.

Front ends drive the mixer through the actions published here. The
org.gtk.Actions interface they call comes from GApplication rather than from
GTK, so this process needs no toolkit at all now that it owns no window - only
GLib, which it already needs for its main loop. rather than setting PipeWire volumes
directly: this process holds the authoritative state and re-applies it whenever
links drop, so an out-of-band change would be silently reverted.

The action list is wide where it used to be deliberately narrow. That comment
was written when the window lived in this process and could call the mixer
directly, so only the bar widget needed a bus. Now every front end is out of
process, and anything the window can do has to cross the bus - including the
structural operations that reprovision PipeWire. What a front end needs to
*read* rather than command does not fit an action at all, and is published as
JSON by publish.StatePublisher instead.
"""
import subprocess

from gi.repository import Gio, GLib

from .service import MixerService

APPLICATION_ID = "io.github.pipeworks.Pipeworks"
DAEMON_FLAG = "--daemon"

# How the window is opened. It is a plugin panel in the Omarchy shell, so
# showing it is a request to that shell rather than anything this process does.
SHELL_COMMAND = ("omarchy-shell", "-q", "shell", "summon", "pipeworks.mixer", "{}")


class PipeworksApplication(Gio.Application):
    def __init__(self, service=None):
        super().__init__(
            application_id=APPLICATION_ID,
            # Command line is handled in the primary instance so a second
            # launch can ask it to show its window instead of starting again.
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._service = service

    # ------------------------------------------------------------------

    def do_startup(self):
        Gio.Application.do_startup(self)
        if self._service is None:
            self._service = MixerService()
        self._service.start()
        self._register_actions()
        # Without this the process would exit as soon as the last window
        # closed, taking the control surface with it.
        self.hold()

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        if DAEMON_FLAG not in arguments:
            self.activate()
        return 0

    def do_activate(self):
        self.present_window()

    def do_shutdown(self):
        self._service.stop()
        Gio.Application.do_shutdown(self)

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Remote control surface (org.gtk.Actions on the session bus)

    def _register_actions(self):
        """Publishes every operation a front end needs.

        Grouped the way a window uses them: levels and switches, which happen
        constantly; structural edits, which reprovision PipeWire and briefly
        cut audio; MIDI Learn; and housekeeping.
        """
        specs = (
            # Levels and switches
            ("set-volume", "(sd)", self._on_set_volume),
            ("set-output-volume", "(sd)", self._on_set_output_volume),
            ("toggle-mute", "s", self._on_toggle_mute),
            ("toggle-output-mute", "s", self._on_toggle_output_mute),
            ("toggle-solo", "s", self._on_toggle_solo),
            ("toggle-output-solo", "s", self._on_toggle_output_solo),
            ("toggle-route", "(ss)", self._on_toggle_route),
            ("set-volume-lock", "b", self._on_set_volume_lock),
            ("toggle-volume-lock", None, self._on_toggle_volume_lock),
            # Application routing
            ("move-stream", "(is)", self._on_move_stream),
            # Structural edits
            ("add-channel", "s", self._on_add_channel),
            ("add-input", "(ss)", self._on_add_input),
            ("add-output", "(ss)", self._on_add_output),
            ("remove-strip", "(ss)", self._on_remove_strip),
            ("rename-strip", "(sss)", self._on_rename_strip),
            ("retarget-input", "(ss)", self._on_retarget_input),
            ("retarget-output", "(ss)", self._on_retarget_output),
            # Control surface
            ("midi-learn", "(ss)", self._on_midi_learn),
            ("midi-learn-cancel", None, self._on_midi_learn_cancel),
            # Housekeeping
            ("set-autostart", "b", self._on_set_autostart),
            ("set-state-watch", "b", self._on_set_state_watch),
            ("show-window", None, self._on_show_window),
        )
        for name, signature, handler in specs:
            parameter_type = GLib.VariantType.new(signature) if signature else None
            action = Gio.SimpleAction.new(name, parameter_type)
            action.connect("activate", handler)
            self.add_action(action)

    def _mixer(self):
        return self._service.mixer

    def _entity(self, kind, entity_id):
        """The config dict for one strip, or None.

        Front ends address strips by kind and id, since an id alone is only
        unique within its kind.
        """
        table = {
            "channel": self._mixer().channels_by_id,
            "input": self._mixer().inputs_by_id,
            "output": self._mixer().outputs_by_id,
        }.get(kind)
        return table.get(entity_id) if table else None

    def _republish(self):
        """Pushes fresh state after something a front end just asked for.

        Without this the window waits for the next poll to see its own edit,
        which reads as the click not having worked.
        """
        self._service.state.publish()

    # ------------------------------------------------------------------
    # Levels and switches

    def _on_set_volume(self, _action, parameter):
        strip_id, percent = parameter.unpack()
        if strip_id in self._mixer().config["volume"]:
            self._mixer().set_volume(strip_id, percent)

    def _on_set_output_volume(self, _action, parameter):
        out_id, percent = parameter.unpack()
        if out_id in self._mixer().config["output_volume"]:
            self._mixer().set_output_volume(out_id, percent)

    def _on_toggle_mute(self, _action, parameter):
        strip_id = parameter.unpack()
        if strip_id in self._mixer().config["muted"]:
            self._mixer().toggle_mute(strip_id)

    def _on_toggle_output_mute(self, _action, parameter):
        out_id = parameter.unpack()
        if out_id in self._mixer().config["output_muted"]:
            self._mixer().toggle_output_mute(out_id)

    def _on_toggle_solo(self, _action, parameter):
        strip_id = parameter.unpack()
        if strip_id in self._mixer().config["solo"]:
            self._mixer().toggle_solo(strip_id)

    def _on_toggle_output_solo(self, _action, parameter):
        out_id = parameter.unpack()
        if out_id in self._mixer().config["output_solo"]:
            self._mixer().toggle_output_solo(out_id)

    def _on_toggle_route(self, _action, parameter):
        strip_id, out_id = parameter.unpack()
        routes = self._mixer().config["routes"]
        if strip_id in routes and out_id in routes[strip_id]:
            self._mixer().toggle_route(strip_id, out_id)

    def _on_set_volume_lock(self, _action, parameter):
        self._mixer().set_volume_locked(parameter.unpack())

    def _on_toggle_volume_lock(self, _action, _parameter):
        mixer = self._mixer()
        mixer.set_volume_locked(not mixer.volume_locked)

    # ------------------------------------------------------------------
    # Application routing

    def _on_move_stream(self, _action, parameter):
        stream_index, sink_name = parameter.unpack()
        self._service.streams.move(stream_index, sink_name)
        self._republish()

    # ------------------------------------------------------------------
    # Structural edits
    #
    # Adding or removing a channel or input rewrites the PipeWire drop-in and
    # restarts PipeWire, so each of these blocks for a couple of seconds and
    # cuts audio while it happens. That is why they are separate actions rather
    # than something a front end can do by editing config: only this process
    # knows how to bring the graph back afterwards.

    def _on_add_channel(self, _action, parameter):
        label = parameter.unpack().strip()
        if label:
            self._mixer().add_channel(label)
            self._republish()

    def _on_add_input(self, _action, parameter):
        label, source_name = parameter.unpack()
        if label.strip() and source_name:
            self._mixer().add_input(label.strip(), source_name)
            self._republish()

    def _on_add_output(self, _action, parameter):
        label, sink_name = parameter.unpack()
        if label.strip() and sink_name:
            self._mixer().add_output(label.strip(), sink_name)
            self._republish()

    def _on_remove_strip(self, _action, parameter):
        kind, entity_id = parameter.unpack()
        remove = {
            "channel": self._mixer().remove_channel,
            "input": self._mixer().remove_input,
            "output": self._mixer().remove_output,
        }.get(kind)
        if remove and self._entity(kind, entity_id):
            remove(entity_id)
            self._republish()

    def _on_rename_strip(self, _action, parameter):
        kind, entity_id, label = parameter.unpack()
        entity = self._entity(kind, entity_id)
        if entity and label.strip():
            self._mixer().rename(entity, label.strip())
            self._republish()

    def _on_retarget_input(self, _action, parameter):
        input_id, source_name = parameter.unpack()
        if source_name and self._entity("input", input_id):
            self._mixer().retarget_input(input_id, source_name)
            self._republish()

    def _on_retarget_output(self, _action, parameter):
        out_id, sink_name = parameter.unpack()
        if sink_name and self._entity("output", out_id):
            self._mixer().retarget_output(out_id, sink_name)
            self._republish()

    # ------------------------------------------------------------------
    # Control surface

    def _on_midi_learn(self, _action, parameter):
        kind, key = parameter.unpack()
        self._service.midi.start_learn(kind, key)
        self._republish()

    def _on_midi_learn_cancel(self, _action, _parameter):
        self._service.midi.cancel_learn()
        self._republish()

    # ------------------------------------------------------------------
    # Housekeeping

    def _on_set_autostart(self, _action, parameter):
        autostart = self._service.autostart
        if getattr(autostart, "can_toggle", True):
            autostart.set_enabled(parameter.unpack())
            self._republish()

    def _on_set_state_watch(self, _action, parameter):
        self._service.set_state_watch(parameter.unpack())

    def _on_show_window(self, _action, _parameter):
        self.present_window()

    def present_window(self):
        """Asks the shell to summon the mixer window.

        Failure is deliberately quiet: the shell may not be running (a bare
        session, or this daemon started from a systemd unit before the shell),
        and there is nothing useful to say to a caller who just clicked an icon.
        """
        try:
            subprocess.run(SHELL_COMMAND, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def run(argv):
    GLib.set_prgname(APPLICATION_ID)
    GLib.set_application_name("Pipeworks")
    return PipeworksApplication().run(argv)
