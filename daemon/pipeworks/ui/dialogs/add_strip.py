"""Adding a strip: a hardware input, a virtual channel, or a physical output."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

CHANNEL = "channel"
INPUT = "input"
OUTPUT = "output"


class AddStripDialog(Gtk.Window):
    def __init__(self, mixer, devices, on_added):
        super().__init__(title="Add")
        self._mixer = mixer
        self._devices = devices
        self._on_added = on_added
        self.set_default_size(360, 180)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self.add(box)

        type_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        type_row.pack_start(Gtk.Label(label="Type:"), False, False, 0)
        self._type_combo = Gtk.ComboBoxText()
        self._type_combo.append(CHANNEL, "Virtual channel (apps play into it)")
        self._type_combo.append(INPUT, "Input (hardware capture device)")
        self._type_combo.append(OUTPUT, "Output (physical device)")
        self._type_combo.set_active_id(CHANNEL)
        self._type_combo.connect("changed", self._on_type_changed)
        type_row.pack_start(self._type_combo, True, True, 0)
        box.pack_start(type_row, False, False, 0)

        name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_row.pack_start(Gtk.Label(label="Name:"), False, False, 0)
        self._name_entry = Gtk.Entry()
        self._name_entry.connect("activate", self._on_add)
        name_row.pack_start(self._name_entry, True, True, 0)
        box.pack_start(name_row, False, False, 0)

        self._device_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._device_row.pack_start(Gtk.Label(label="Device:"), False, False, 0)
        self._device_combo = Gtk.ComboBoxText()
        self._device_row.pack_start(self._device_combo, True, True, 0)
        box.pack_start(self._device_row, False, False, 0)
        self._device_row.set_no_show_all(True)  # only relevant for input/output

        self._status = Gtk.Label(label="")
        box.pack_start(self._status, False, False, 0)

        self._add_button = Gtk.Button(label="Add")
        self._add_button.connect("clicked", self._on_add)
        box.pack_start(self._add_button, False, False, 0)

    def _on_type_changed(self, _combo):
        kind = self._type_combo.get_active_id()
        self._device_combo.remove_all()
        if kind == CHANNEL:
            self._device_row.hide()
            return
        available = (
            self._devices.input_devices() if kind == INPUT else self._devices.output_devices()
        )
        for name, description in available:
            self._device_combo.append(name, description)
        self._device_combo.set_active(0)
        self._device_row.show()

    def _on_add(self, _widget):
        kind = self._type_combo.get_active_id()
        name = self._name_entry.get_text().strip()
        if not name:
            self._status.set_text("Please enter a name.")
            return

        device = self._device_combo.get_active_id()
        if kind in (INPUT, OUTPUT) and not device:
            self._status.set_text("No device available to select.")
            return

        if kind == OUTPUT:
            # Attaches to hardware that already exists, so nothing to restart.
            self._mixer.add_output(name, device)
        else:
            # Channels and inputs need PipeWire reprovisioned, which cuts audio
            # briefly - say so before blocking on it.
            self._status.set_text("Applying - audio will briefly cut out...")
            self._name_entry.set_sensitive(False)
            self._add_button.set_sensitive(False)
            while Gtk.events_pending():
                Gtk.main_iteration()
            if kind == INPUT:
                self._mixer.add_input(name, device)
            else:
                self._mixer.add_channel(name)

        self._on_added()
        self.destroy()
