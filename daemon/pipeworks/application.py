"""The GTK application: a resident background process with an optional window.

Lifecycle, which is the whole point of this module:

* Launched with --daemon (by the systemd user unit) it starts the mixer service
  and shows nothing. The control surface works immediately after boot.
* Launched without --daemon it also presents the window. Because the
  application ID is registered on the session bus, a second launch does not
  start a second copy - it reaches the running one and asks it to show its
  window, which is what clicking the desktop entry does.
* Closing the window destroys only the window. hold() keeps the process alive,
  so MIDI, routing and the link watchdog carry on; reopening builds a fresh
  window. Metering processes exist only while a window does, so an idle
  background instance costs almost nothing.

The application also publishes actions on the session bus (GtkApplication
exports org.gtk.Actions for free), which is how external front-ends such as the
Omarchy bar widget drive the mixer. They go through these actions rather than
setting PipeWire volumes directly: the daemon holds the authoritative state and
re-applies it whenever links drop, so an out-of-band change would be silently
reverted.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .service import MixerService
from .ui.main_window import MainWindow

APPLICATION_ID = "io.github.pipeworks.Pipeworks"
DAEMON_FLAG = "--daemon"


class PipeworksApplication(Gtk.Application):
    def __init__(self, service=None):
        super().__init__(
            application_id=APPLICATION_ID,
            # Command line is handled in the primary instance so a second
            # launch can ask it to show its window instead of starting again.
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._service = service
        self._window = None

    # ------------------------------------------------------------------

    def do_startup(self):
        Gtk.Application.do_startup(self)
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
        Gtk.Application.do_shutdown(self)

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Remote control surface (org.gtk.Actions on the session bus)

    def _register_actions(self):
        """Publishes the operations external front-ends need.

        Deliberately narrow: adjust a level, flip a mute, flip a route. Anything
        structural (adding or removing strips) restarts PipeWire and belongs in
        the window, not in a one-shot bus call.
        """
        specs = (
            ("set-volume", "(sd)", self._on_set_volume),
            ("set-output-volume", "(sd)", self._on_set_output_volume),
            ("toggle-mute", "s", self._on_toggle_mute),
            ("toggle-output-mute", "s", self._on_toggle_output_mute),
            ("toggle-route", "(ss)", self._on_toggle_route),
            ("show-window", None, self._on_show_window),
        )
        for name, signature, handler in specs:
            parameter_type = GLib.VariantType.new(signature) if signature else None
            action = Gio.SimpleAction.new(name, parameter_type)
            action.connect("activate", handler)
            self.add_action(action)

    def _mixer(self):
        return self._service.mixer

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

    def _on_toggle_route(self, _action, parameter):
        strip_id, out_id = parameter.unpack()
        routes = self._mixer().config["routes"]
        if strip_id in routes and out_id in routes[strip_id]:
            self._mixer().toggle_route(strip_id, out_id)

    def _on_show_window(self, _action, _parameter):
        self.present_window()

    def present_window(self):
        if self._window is None:
            self._window = MainWindow(self._service, application=self)
            self._window.connect("destroy", self._on_window_destroyed)
        self._window.show_all()
        self._window.present()

    def _on_window_destroyed(self, _window):
        # Drop every reference back into the window so the still-running
        # service cannot call into destroyed widgets.
        self._service.set_status_listener(None)
        self._service.mixer.on_state_changed = lambda: None
        self._window = None


def run(argv):
    GLib.set_prgname(APPLICATION_ID)
    GLib.set_application_name("Pipeworks")
    return PipeworksApplication().run(argv)
