"""Segmented LED level meter.

Drawn with Cairo rather than using Gtk.LevelBar, which renders as a single flat
themed trough. Levels arrive as 0.0-1.0 positions on a dB scale. The bar jumps
straight to a new peak and falls back smoothly so transients stay readable
instead of flickering, and the peak marker hangs at the loudest recent level
before drifting down.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402


class LevelMeter(Gtk.DrawingArea):
    SEGMENTS = 18
    TICK_MS = 50
    RELEASE_PER_TICK = 0.055
    PEAK_HOLD_TICKS = 22  # ~1.1s before the peak marker starts dropping
    PEAK_FALL_PER_TICK = 0.018

    AMBER_FROM = 0.64  # ~-18 dB on a -50..0 scale
    RED_FROM = 0.88  # ~-6 dB

    GREEN = (0.35, 0.80, 0.40)
    AMBER = (0.95, 0.71, 0.19)
    RED = (0.91, 0.30, 0.24)
    TROUGH = (0.10, 0.10, 0.11)
    UNLIT_FACTOR = 0.16  # dim but visible, so the scale reads when silent

    # Every meter animates off one shared timer: eight independent GLib
    # timeouts waking up separately is pure overhead for a window that sits
    # open in the background.
    _instances = []
    _shared_timer = None

    def __init__(self, width=15, height=160):
        super().__init__()
        self.set_size_request(width, height)
        self._level = 0.0
        self._display = 0.0
        self._peak = 0.0
        self._peak_hold = 0

        self.connect("draw", self._on_draw)
        self.connect("destroy", self._on_destroy)

        LevelMeter._instances.append(self)
        if LevelMeter._shared_timer is None:
            LevelMeter._shared_timer = GLib.timeout_add(self.TICK_MS, LevelMeter._tick_all)

    def _on_destroy(self, _widget):
        if self in LevelMeter._instances:
            LevelMeter._instances.remove(self)

    @classmethod
    def _tick_all(cls):
        for meter in list(cls._instances):
            meter._tick()
        return True

    def set_level(self, value):
        self._level = max(0.0, min(1.0, value))
        if self._level > self._display:
            self._display = self._level
            self.queue_draw()
        if self._level >= self._peak:
            self._peak = self._level
            self._peak_hold = self.PEAK_HOLD_TICKS

    def _tick(self):
        changed = False
        if self._display > self._level:
            self._display = max(self._level, self._display - self.RELEASE_PER_TICK)
            changed = True
        if self._peak_hold > 0:
            self._peak_hold -= 1
        elif self._peak > self._display:
            self._peak = max(self._display, self._peak - self.PEAK_FALL_PER_TICK)
            changed = True
        if changed:
            self.queue_draw()

    def _zone_color(self, fraction):
        if fraction >= self.RED_FROM:
            return self.RED
        if fraction >= self.AMBER_FROM:
            return self.AMBER
        return self.GREEN

    def _on_draw(self, _widget, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()

        cr.set_source_rgb(*self.TROUGH)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        gap = 2
        segment_height = max(1.0, (height - gap * (self.SEGMENTS + 1)) / self.SEGMENTS)
        lit_count = self._display * self.SEGMENTS

        for index in range(self.SEGMENTS):
            red, green, blue = self._zone_color((index + 0.5) / self.SEGMENTS)
            if lit_count > index:
                cr.set_source_rgb(red, green, blue)
            else:
                dim = self.UNLIT_FACTOR
                cr.set_source_rgb(red * dim, green * dim, blue * dim)
            y = height - gap - index * (segment_height + gap) - segment_height
            cr.rectangle(gap, y, width - 2 * gap, segment_height)
            cr.fill()

        if self._peak > 0.001:
            red, green, blue = self._zone_color(self._peak)
            cr.set_source_rgb(min(1.0, red + 0.25), min(1.0, green + 0.25), min(1.0, blue + 0.25))
            y = height - gap - self._peak * (height - 2 * gap)
            cr.rectangle(gap, max(gap, y - 1), width - 2 * gap, 2)
            cr.fill()
