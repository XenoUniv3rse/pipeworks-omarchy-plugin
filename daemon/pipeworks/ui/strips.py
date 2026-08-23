"""Construction of channel strips and keeping their widgets in sync.

StripControls owns the "widgets reflect config" responsibility; StripBuilder
owns assembling them. Splitting the two keeps the main window from having to
know either job in detail.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .. import settings
from ..audio.levels import peak_to_level
from .level_meter import LevelMeter

FADER_HEIGHT = 160

# Meter node names share one prefix with the stale-process cleanup in
# audio.metering, so both derive it from settings rather than hardcoding it.
_METER = settings.METER_NODE_PREFIX


class StripControls:
    """Widget registry for one populated layout, and the sync that follows state."""

    def __init__(self):
        self.volume_scales = {}
        self.volume_labels = {}
        self.mute_buttons = {}
        self.solo_buttons = {}
        self.route_buttons = {}
        self.output_volume_scales = {}
        self.output_volume_labels = {}
        self.output_mute_buttons = {}
        self.output_solo_buttons = {}

    def sync(self, config):
        """Pushes current state into the widgets.

        Guarded comparisons matter: assigning to a Gtk control re-emits its
        changed signal, which would loop straight back into the mixer.
        """
        for strip_id, scale in self.volume_scales.items():
            if scale.get_value() != config["volume"][strip_id]:
                scale.set_value(config["volume"][strip_id])
        for strip_id, label in self.volume_labels.items():
            label.set_text(f"{round(config['volume'][strip_id])}%")
        for strip_id, button in self.mute_buttons.items():
            if button.get_active() != config["muted"][strip_id]:
                button.set_active(config["muted"][strip_id])
        for strip_id, button in self.solo_buttons.items():
            if button.get_active() != config["solo"][strip_id]:
                button.set_active(config["solo"][strip_id])
        for (strip_id, out_id), button in self.route_buttons.items():
            if button.get_active() != config["routes"][strip_id][out_id]:
                button.set_active(config["routes"][strip_id][out_id])

        for out_id, scale in self.output_volume_scales.items():
            if scale.get_value() != config["output_volume"][out_id]:
                scale.set_value(config["output_volume"][out_id])
        for out_id, label in self.output_volume_labels.items():
            label.set_text(f"{round(config['output_volume'][out_id])}%")
        for out_id, button in self.output_mute_buttons.items():
            if button.get_active() != config["output_muted"][out_id]:
                button.set_active(config["output_muted"][out_id])
        for out_id, button in self.output_solo_buttons.items():
            if button.get_active() != config["output_solo"][out_id]:
                button.set_active(config["output_solo"][out_id])


class StripBuilder:
    def __init__(self, mixer, backend, controls, start_meter, on_open_settings):
        self._mixer = mixer
        self._backend = backend
        self._controls = controls
        self._start_meter = start_meter
        self._on_open_settings = on_open_settings

    # ------------------------------------------------------------------

    def build_strip(self, entity):
        """A channel or input strip: meter, fader, mute, and (channels) solo+routes."""
        strip_id = entity["id"]
        is_input = strip_id in self._mixer.inputs_by_id
        frame, box = self._framed(entity["label"])
        box.pack_start(
            self._gear("input" if is_input else "channel", entity), False, False, 0
        )

        sink = entity["target_sink"] if is_input else entity["sink"]
        self._meter_and_fader(
            box,
            node_name=f"{_METER}_{strip_id}",
            source_ports=self._backend.node_output_ports(f"{sink}_out"),
            value=self._mixer.config["volume"][strip_id],
            on_changed=lambda scale: self._mixer.set_volume(strip_id, scale.get_value()),
            scale_registry=self._controls.volume_scales,
            key=strip_id,
        )

        label = Gtk.Label(label=f"{round(self._mixer.config['volume'][strip_id])}%")
        box.pack_start(label, False, False, 0)
        self._controls.volume_labels[strip_id] = label

        mute = Gtk.ToggleButton(label="Mute")
        mute.set_active(self._mixer.config["muted"][strip_id])
        mute.connect("toggled", lambda b: self._mixer.set_mute(strip_id, b.get_active()))
        box.pack_start(mute, False, False, 0)
        self._controls.mute_buttons[strip_id] = mute

        if not is_input:
            solo = Gtk.ToggleButton(label="Solo")
            solo.set_active(self._mixer.config["solo"][strip_id])
            solo.connect("toggled", lambda b: self._mixer.set_solo(strip_id, b.get_active()))
            box.pack_start(solo, False, False, 0)
            self._controls.solo_buttons[strip_id] = solo

            for output in self._mixer.config["outputs"]:
                out_id = output["id"]
                route = Gtk.ToggleButton(label=output["label"])
                route.set_active(self._mixer.config["routes"][strip_id][out_id])
                route.connect(
                    "toggled",
                    lambda b, c=strip_id, o=out_id: self._mixer.set_route(c, o, b.get_active()),
                )
                box.pack_start(route, False, False, 0)
                self._controls.route_buttons[(strip_id, out_id)] = route

        return frame

    def build_output_strip(self, output):
        """A physical output bus: meter, fader, mute, solo."""
        out_id = output["id"]
        sink = output["port_l"].split(":")[0]
        frame, box = self._framed(output["label"])
        box.pack_start(self._gear("output", output), False, False, 0)

        self._meter_and_fader(
            box,
            node_name=f"{_METER}_out_{out_id}",
            source_ports=self._backend.monitor_ports(sink),
            value=self._mixer.config["output_volume"][out_id],
            on_changed=lambda scale: self._mixer.set_output_volume(out_id, scale.get_value()),
            scale_registry=self._controls.output_volume_scales,
            key=out_id,
        )

        label = Gtk.Label(label=f"{round(self._mixer.config['output_volume'][out_id])}%")
        box.pack_start(label, False, False, 0)
        self._controls.output_volume_labels[out_id] = label

        mute = Gtk.ToggleButton(label="Mute")
        mute.set_active(self._mixer.config["output_muted"][out_id])
        mute.connect("toggled", lambda b: self._mixer.set_output_mute(out_id, b.get_active()))
        box.pack_start(mute, False, False, 0)
        self._controls.output_mute_buttons[out_id] = mute

        solo = Gtk.ToggleButton(label="Solo")
        solo.set_active(self._mixer.config["output_solo"][out_id])
        solo.connect("toggled", lambda b: self._mixer.set_output_solo(out_id, b.get_active()))
        box.pack_start(solo, False, False, 0)
        self._controls.output_solo_buttons[out_id] = solo

        return frame

    # ------------------------------------------------------------------

    @staticmethod
    def _framed(title):
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        frame.add(box)
        return frame, box

    def _gear(self, kind, entity):
        button = Gtk.Button(label="⚙")
        button.set_tooltip_text("Settings")
        button.connect("clicked", lambda _b: self._on_open_settings(kind, entity))
        return button

    def _meter_and_fader(self, box, node_name, source_ports, value, on_changed, scale_registry, key):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.pack_start(row, True, True, 0)

        level = LevelMeter()
        row.pack_start(level, False, False, 0)
        self._start_meter(
            node_name, source_ports, lambda peak: level.set_level(peak_to_level(peak))
        )

        scale = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL)
        scale.set_range(0, 100)
        scale.set_value(value)
        scale.set_inverted(True)
        scale.set_size_request(-1, FADER_HEIGHT)
        scale.set_draw_value(False)
        scale.connect("value-changed", on_changed)
        row.pack_start(scale, True, True, 0)
        scale_registry[key] = scale
