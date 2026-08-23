"""Assigning running applications to channels.

This is the piece that otherwise sends you out to pavucontrol. WirePlumber's
restore-target remembers each application's choice, so something routed here
lands on the same channel the next time it starts.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

OTHER_DEVICE_ID = "__other__"


class AppRoutingDialog(Gtk.Window):
    REFRESH_SECONDS = 2

    def __init__(self, mixer, streams):
        super().__init__(title="Applications")
        self._mixer = mixer
        self._streams = streams
        self._combos = {}
        self._shown_indices = None
        self._suppress_signals = False
        self.set_default_size(460, 260)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(12)
        self.add(outer)
        outer.pack_start(
            Gtk.Label(label="Route each playing application to a channel:", xalign=0),
            False, False, 0,
        )

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroller, True, True, 0)
        self._rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller.add(self._rows)

        self._rebuild()
        self._timer = GLib.timeout_add_seconds(self.REFRESH_SECONDS, self._refresh)
        self.connect("destroy", lambda _w: GLib.source_remove(self._timer))

    # ------------------------------------------------------------------

    def _targets(self):
        """(sink_name, label) for every place an application can be sent."""
        targets = [(c["sink"], c["label"]) for c in self._mixer.config["channels"]]
        targets += [(i["target_sink"], i["label"]) for i in self._mixer.config["inputs"]]
        return targets

    def _current_streams(self):
        return self._streams.list_streams(self._mixer.loopback_output_names())

    def _rebuild(self):
        for child in self._rows.get_children():
            self._rows.remove(child)
            child.destroy()

        streams = self._current_streams()
        self._shown_indices = {stream.index for stream in streams}
        self._combos = {}

        if not streams:
            self._rows.pack_start(
                Gtk.Label(label="Nothing is playing right now.", xalign=0), False, False, 0
            )
            self._rows.show_all()
            return

        targets = self._targets()
        known = dict(targets)
        for stream in streams:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=stream.label, xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            row.pack_start(label, True, True, 0)

            combo = Gtk.ComboBoxText()
            for sink_name, caption in targets:
                combo.append(sink_name, caption)
            combo.append(OTHER_DEVICE_ID, "(other device)")
            combo.set_active_id(
                stream.sink_name if stream.sink_name in known else OTHER_DEVICE_ID
            )
            combo.connect("changed", self._on_target_changed, stream.index)
            row.pack_start(combo, False, False, 0)

            self._combos[stream.index] = combo
            self._rows.pack_start(row, False, False, 0)

        self._rows.show_all()

    def _on_target_changed(self, combo, stream_index):
        if self._suppress_signals:
            return
        sink_name = combo.get_active_id()
        if sink_name and sink_name != OTHER_DEVICE_ID:
            self._streams.move(stream_index, sink_name)

    def _refresh(self):
        streams = self._current_streams()
        if {stream.index for stream in streams} != self._shown_indices:
            self._rebuild()  # applications started or stopped
            return True

        # Same applications: reflect assignments changed elsewhere, without
        # letting the programmatic update fire a move straight back.
        known = dict(self._targets())
        self._suppress_signals = True
        for stream in streams:
            combo = self._combos.get(stream.index)
            if not combo:
                continue
            wanted = stream.sink_name if stream.sink_name in known else OTHER_DEVICE_ID
            if combo.get_active_id() != wanted:
                combo.set_active_id(wanted)
        self._suppress_signals = False
        return True
