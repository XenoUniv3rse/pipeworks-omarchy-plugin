"""The mixer window: sections of strips plus a status area.

A view onto a MixerService that outlives it. Closing this window must not stop
the service, so nothing here quits the process, and everything it registers on
the service is detached on the way out.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .dialogs.add_strip import AddStripDialog
from .dialogs.app_routing import AppRoutingDialog
from .dialogs.strip_settings import StripSettingsDialog
from .strips import StripBuilder, StripControls

STATUS_CLEAR_SECONDS = 4


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, service, application):
        super().__init__(title="Pipeworks", application=application)
        self._service = service
        self._mixer = service.mixer
        self._meters = []
        self._controls = StripControls()

        self.set_default_size(700, 400)
        self.connect("destroy", self._on_destroy)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(outer)

        self._strips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._strips_box.set_border_width(12)
        outer.pack_start(self._strips_box, True, True, 0)
        outer.pack_start(self._bottom_bar(), False, False, 0)

        self.populate_strips()
        self._mixer.on_state_changed = self._sync_controls
        service.set_status_listener(self._show_status)

    # ------------------------------------------------------------------

    def _on_destroy(self, _widget):
        """Tears down only this view - the service keeps running."""
        self._stop_meters()

    def _bottom_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(6)

        autostart = self._service.autostart
        check = Gtk.CheckButton(label="Start on login")
        check.set_active(autostart.is_enabled())
        check.set_tooltip_text(autostart.describe())
        # Not every strategy is ours to change: when a host process supervises
        # the daemon, the checkbox reports that rather than pretending.
        if getattr(autostart, "can_toggle", True):
            check.connect("toggled", lambda b: autostart.set_enabled(b.get_active()))
        else:
            check.set_sensitive(False)
        bar.pack_start(check, False, False, 0)

        self._status_label = Gtk.Label(label="")
        self._status_label.set_xalign(0)
        bar.pack_start(self._status_label, True, True, 6)

        add_button = Gtk.Button(label="Add...")
        add_button.connect("clicked", lambda _b: self._open_add_strip())
        bar.pack_end(add_button, False, False, 0)

        apps_button = Gtk.Button(label="Apps...")
        apps_button.set_tooltip_text("Assign running applications to channels")
        apps_button.connect("clicked", lambda _b: self._open_app_routing())
        bar.pack_end(apps_button, False, False, 0)
        return bar

    # ------------------------------------------------------------------

    def populate_strips(self):
        for child in self._strips_box.get_children():
            self._strips_box.remove(child)
            child.destroy()
        self._stop_meters()

        self._controls = StripControls()
        builder = StripBuilder(
            self._mixer,
            self._service.backend,
            self._controls,
            start_meter=self._start_meter,
            on_open_settings=self._open_strip_settings,
        )

        config = self._mixer.config
        sections = (
            ("Inputs", [builder.build_strip(inp) for inp in config["inputs"]]),
            ("Virtual Channels", [builder.build_strip(chan) for chan in config["channels"]]),
            ("Physical Outputs", [builder.build_output_strip(out) for out in config["outputs"]]),
        )
        for index, (title, strips) in enumerate(sections):
            if index:
                self._strips_box.pack_start(
                    Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6
                )
            self._strips_box.pack_start(self._section(title, strips), False, False, 0)
        self._strips_box.show_all()

    @staticmethod
    def _section(title, strips):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        heading = Gtk.Label(xalign=0)
        heading.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        box.pack_start(heading, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.pack_start(row, True, True, 0)
        if strips:
            for strip in strips:
                row.pack_start(strip, False, False, 0)
        else:
            placeholder = Gtk.Label(label="(none)")
            placeholder.set_sensitive(False)
            row.pack_start(placeholder, False, False, 12)
        return box

    # ------------------------------------------------------------------

    def _start_meter(self, node_name, source_ports, on_level):
        meter = self._service.create_meter(node_name, source_ports, on_level)
        self._meters.append(meter)
        meter.start()

    def _stop_meters(self):
        for meter in self._meters:
            meter.stop()
        self._meters = []

    def _sync_controls(self):
        self._controls.sync(self._mixer.config)

    def _show_status(self, text):
        self._status_label.set_text(text)
        GLib.timeout_add_seconds(
            STATUS_CLEAR_SECONDS, lambda: (self._status_label.set_text(""), False)[1]
        )

    # ------------------------------------------------------------------

    def _open_add_strip(self):
        AddStripDialog(
            self._mixer, self._service.devices, on_added=self.populate_strips
        ).show_all()

    def _open_app_routing(self):
        AppRoutingDialog(self._mixer, self._service.streams).show_all()

    def _open_strip_settings(self, kind, entity):
        StripSettingsDialog(
            self._mixer,
            self._service.midi,
            self._service.devices,
            kind,
            entity,
            on_changed=self.populate_strips,
        ).show_all()
