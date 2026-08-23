"""Per-strip settings: rename, device selection, MIDI Learn, removal.

Opened from a strip's gear button so everything about that one strip is in a
single place, rather than a global list of every control in the mixer.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

REMOVE_LABELS = {"channel": "Remove Channel", "input": "Remove Input", "output": "Remove Output"}
REMOVE_NOUNS = {"channel": "virtual channel", "input": "input", "output": "output"}


class StripSettingsDialog(Gtk.Window):
    def __init__(self, mixer, midi, devices, kind, entity, on_changed):
        super().__init__(title=f"{entity['label']} Settings")
        self._mixer = mixer
        self._midi = midi
        self._devices = devices
        self._kind = kind
        self._entity = entity
        self._on_changed = on_changed
        self._learn_rows = []
        self.set_default_size(340, 300)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_border_width(12)
        self.add(outer)

        outer.pack_start(self._name_row(), False, False, 0)
        if kind in ("output", "input"):
            outer.pack_start(self._device_row(), False, False, 0)

        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        outer.pack_start(Gtk.Label(label="MIDI Bindings", xalign=0), False, False, 0)
        outer.pack_start(self._bindings_grid(), False, False, 0)

        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        remove = Gtk.Button(label=REMOVE_LABELS[kind])
        remove.connect("clicked", self._on_remove)
        outer.pack_start(remove, False, False, 0)

        self._midi.on_learned = self._on_learned

    # ------------------------------------------------------------------

    def _name_row(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Name:"), False, False, 0)
        self._name_entry = Gtk.Entry()
        self._name_entry.set_text(self._entity["label"])
        self._name_entry.connect("activate", self._on_rename)
        row.pack_start(self._name_entry, True, True, 0)
        button = Gtk.Button(label="Rename")
        button.connect("clicked", self._on_rename)
        row.pack_start(button, False, False, 0)
        return row

    def _device_row(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Device:"), False, False, 0)
        combo = Gtk.ComboBoxText()
        if self._kind == "output":
            current = self._entity["port_l"].split(":")[0]
            available = self._devices.output_devices()
        else:
            current = self._entity["source"]
            available = self._devices.input_devices()
        for name, description in available:
            combo.append(name, description)
        combo.set_active_id(current)
        combo.connect("changed", self._on_device_changed)
        row.pack_start(combo, True, True, 0)
        return row

    def _bindings_grid(self):
        grid = Gtk.Grid(row_spacing=6, column_spacing=8)
        strip_id = self._entity["id"]
        row = 0
        if self._kind == "output":
            row = self._add_learn_row(grid, row, "Volume", "output_volume_cc", strip_id)
            row = self._add_learn_row(grid, row, "Mute", "output_mute_note", strip_id)
            row = self._add_learn_row(grid, row, "Solo", "output_solo_note", strip_id)
        else:
            row = self._add_learn_row(grid, row, "Volume", "volume_cc", strip_id)
            row = self._add_learn_row(grid, row, "Mute", "mute_note", strip_id)
            if self._kind == "channel":
                row = self._add_learn_row(grid, row, "Solo", "solo_note", strip_id)
                for output in self._mixer.config["outputs"]:
                    row = self._add_learn_row(
                        grid,
                        row,
                        f"Route to {output['label']}",
                        "route_note",
                        f"{strip_id}:{output['id']}",
                    )
        return grid

    def _add_learn_row(self, grid, row, caption, kind, key):
        grid.attach(Gtk.Label(label=caption, xalign=0), 0, row, 1, 1)
        current = self._mixer.config["midi"][kind].get(key)
        value = Gtk.Label(label=str(current) if current is not None else "-")
        grid.attach(value, 1, row, 1, 1)
        button = Gtk.Button(label="Learn")
        button.connect("clicked", lambda _b: self._start_learn(kind, key, button))
        grid.attach(button, 2, row, 1, 1)
        self._learn_rows.append((kind, key, value, button))
        return row + 1

    # ------------------------------------------------------------------

    def _start_learn(self, kind, key, button):
        for *_ignored, other in self._learn_rows:
            other.set_label("Learn")
        button.set_label("Waiting...")
        self._midi.start_learn(kind, key)

    def _on_learned(self, kind, key, number):
        GLib.idle_add(self._apply_learned, kind, key, number)

    def _apply_learned(self, kind, key, number):
        for row_kind, row_key, value, button in self._learn_rows:
            if row_kind == kind and row_key == key:
                value.set_text(str(number))
                button.set_label("Learn")
        self._midi.sync_leds()

    def _on_rename(self, _widget):
        text = self._name_entry.get_text().strip()
        if not text:
            return
        self._mixer.rename(self._entity, text)
        self.set_title(f"{text} Settings")
        self._on_changed()

    def _on_device_changed(self, combo):
        selected = combo.get_active_id()
        if not selected:
            return
        if self._kind == "output":
            if selected == self._entity["port_l"].split(":")[0]:
                return
            self._mixer.retarget_output(self._entity["id"], selected)
        else:
            if selected == self._entity["source"]:
                return
            self._mixer.retarget_input(self._entity["id"], selected)
        # Rebuild strips so this strip's meter follows the new device.
        self._on_changed()

    def _on_remove(self, _button):
        confirm = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove '{self._entity['label']}'?",
        )
        confirm.format_secondary_text(
            f"This deletes the {REMOVE_NOUNS[self._kind]} and cannot be undone."
        )
        response = confirm.run()
        confirm.destroy()
        if response != Gtk.ResponseType.YES:
            return

        remove = {
            "channel": self._mixer.remove_channel,
            "input": self._mixer.remove_input,
            "output": self._mixer.remove_output,
        }[self._kind]
        remove(self._entity["id"])
        self._on_changed()
        self.destroy()
