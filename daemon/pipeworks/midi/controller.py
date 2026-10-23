"""Control-surface I/O: reads the board, drives its LEDs, runs Learn.

Translates MIDI messages into mixer commands and mixer state back into LED
states. Incoming messages arrive on rtmidi's own thread, so they are handed to
the injected dispatcher before touching anything else.
"""
import re

import rtmidi

from .. import settings
from .bindings import binding_channel, binding_number

NOTE_ON = 0x90
CONTROL_CHANGE = 0xB0
LED_ON_VELOCITY = 127

# This process's own ALSA client name. Sequencer ports rtmidi opens are
# otherwise registered under the generic "RtMidiIn Client"/"RtMidiOut Client"
# names, which give probe_ports() nothing distinctive to exclude them by.
CLIENT_NAME = "Pipeworks"

# ALSA names a sequencer port "<client>:<port> <client-id>:<port-id>" - the
# trailing pair is an address, not identity, and is not guaranteed to stay the
# same across a reboot or a reconnect once other MIDI clients are in the mix.
_ADDRESS_SUFFIX = re.compile(r"\s+\d+:\d+$")

# Clients that are never a real controller, excluded so they do not clutter a
# device picker: ALSA's own virtual passthrough, present on every system with
# a sequencer, and this process's own MIDI ports - without the second one,
# the daemon's own LED-output port shows up as if it were a pluggable board,
# since ALSA advertises it with both read and write capability regardless of
# which direction this process actually uses it for.
_IGNORED_CLIENT_PREFIXES = ("Midi Through:", CLIENT_NAME + ":")


class MidiPortsNotFound(RuntimeError):
    pass


def probe_ports():
    """Lists control-surface candidates currently visible to ALSA.

    Each name has its sequencer address stripped, matching what MidiController
    itself searches for - so a name from this list is always a match that will
    resolve, whichever slot ALSA happens to assign the device to next time.
    """
    # Released explicitly: each probe is an ALSA sequencer client, and they
    # were not being freed. This runs on every state publish, so the daemon
    # piled up dozens until ALSA refused to create another - at which point
    # the probe raised, every publish failed, and the window froze on stale
    # state.
    probe = rtmidi.MidiIn(rtmidi.API_LINUX_ALSA)
    try:
        names = probe.get_ports()
    finally:
        probe.delete()
    seen = []
    for name in names:
        if name.startswith(_IGNORED_CLIENT_PREFIXES):
            continue
        stable = _ADDRESS_SUFFIX.sub("", name).strip()
        if stable and stable not in seen:
            seen.append(stable)
    return seen


class MidiController:
    def __init__(self, mixer, bindings, dispatch, port_match=settings.MIDI_PORT_MATCH):
        self._mixer = mixer
        self._bindings = bindings
        self._dispatch = dispatch

        self._learn_target = None
        self.on_learned = lambda kind, key, number, displaced: None
        # Something the board just did: ("level" | "pickup" | "press", kind,
        # key, fader position). For showing it on screen.
        self.on_surface = lambda event, kind, key, value: None

        # Soft takeover, per (kind, key): the level this board last set, and
        # where the fader physically was last time it moved.
        self._surface_set = {}
        self._surface_seen = {}

        self._midi_in = rtmidi.MidiIn(rtmidi.API_LINUX_ALSA)
        self._midi_out = rtmidi.MidiOut(rtmidi.API_LINUX_ALSA)
        self._midi_in.set_client_name(CLIENT_NAME)
        self._midi_out.set_client_name(CLIENT_NAME)
        in_index = self._find_port(self._midi_in, port_match)
        out_index = self._find_port(self._midi_out, port_match)
        if in_index is None or out_index is None:
            raise MidiPortsNotFound(f"No MIDI port matching '{port_match}'")

        self._midi_in.open_port(in_index)
        self._midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        self._midi_out.open_port(out_index)
        self._midi_in.set_callback(self._on_message)

    @staticmethod
    def _find_port(port, match):
        return next((i for i, name in enumerate(port.get_ports()) if match in name), None)

    def close(self):
        """Releases the ALSA ports, so a new controller can open the same or a
        different device without them still being held open."""
        self._midi_in.cancel_callback()
        self._midi_in.close_port()
        self._midi_out.close_port()

    # ------------------------------------------------------------------
    # Learn

    # A board is open, so Learn can actually complete. Published so a front end
    # can say "no control surface" rather than leaving Learn waiting forever.
    connected = True

    @property
    def learning(self):
        """(kind, key) awaiting a control, or None."""
        return self._learn_target

    def start_learn(self, kind, key):
        self._learn_target = (kind, key)

    def cancel_learn(self):
        self._learn_target = None

    # ------------------------------------------------------------------
    # LEDs

    def set_led(self, binding, on):
        """Lights a button's LED, on the channel it was learned on.

        Takes a binding as stored - a bare note or {"channel", "number"} - so
        a board that layers buttons across channels lights the right one.
        """
        number = binding_number(binding)
        if number is None:
            return
        channel = binding_channel(binding) or 0
        self._midi_out.send_message(
            [NOTE_ON | channel, number, LED_ON_VELOCITY if on else 0]
        )

    def sync_leds(self):
        for note, is_on in self._bindings.led_states():
            self.set_led(note, is_on)

    def reflect_change(self, change_kind, key, value):
        """Mirrors a mixer state change onto the matching button LED."""
        note = self._bindings.led_note_for_change(change_kind, key)
        if note is not None:
            self.set_led(note, value)

    # ------------------------------------------------------------------
    # Incoming messages

    def _on_message(self, event, _data=None):
        message, _delta = event
        if len(message) < 3:
            return
        status = message[0] & 0xF0
        # The low nibble is the channel. It used to be thrown away, which made
        # boards that reuse numbers across channels trigger the wrong strip.
        channel = message[0] & 0x0F
        if status == NOTE_ON:
            note, velocity = message[1], message[2]
            if velocity > 0:  # note-on with velocity 0 is a release
                self._dispatch(self._handle_note, note, channel)
        elif status == CONTROL_CHANGE:
            self._dispatch(self._handle_cc, message[1], message[2], channel)

    def _handle_note(self, note, channel=None):
        if self._consume_learn(note, channel, self._bindings.is_note_kind):
            return
        for kind, key in self._bindings.matches_for_note(note, channel):
            self._invoke_note_action(kind, key)
            self.on_surface("press", kind, key, None)
            return

    def _handle_cc(self, controller, value, channel=None):
        if self._consume_learn(controller, channel, self._bindings.is_cc_kind):
            return
        percent = round(value / 127 * 100)
        for kind, key in self._bindings.matches_for_cc(controller, channel):
            if not self._takes_over(kind, key, percent):
                self.on_surface("pickup", kind, key, percent)
                return
            # from_surface: the lock exists to keep software out, not the board.
            if kind == "volume_cc":
                self._mixer.set_volume(key, percent, from_surface=True)
            else:
                self._mixer.set_output_volume(key, percent, from_surface=True)
            self._surface_set[(kind, key)] = percent
            self.on_surface("level", kind, key, percent)
            return

    def _takes_over(self, kind, key, percent):
        """Whether a fader movement should change the level (soft takeover).

        If the level is still what this board last set it to, the fader is in
        control. If something else has moved it since - the window, a scene -
        the fader and the level disagree, and applying the fader would make
        the level jump. It is ignored until it comes close to the level or
        crosses it, the way motorless hardware mixers pick up.

        A fader this board has not moved since the daemon started has no
        record, so it is trusted: there is nothing to compare it against.
        """
        binding = (kind, key)
        previous = self._surface_seen.get(binding)
        self._surface_seen[binding] = percent
        if not self._mixer.config.get("midi_soft_takeover", True):
            return True
        last_set = self._surface_set.get(binding)
        if last_set is None:
            return True
        store = "volume" if kind == "volume_cc" else "output_volume"
        current = self._mixer.config[store].get(key)
        if current is None or abs(current - last_set) < 0.5:
            return True
        if abs(percent - current) <= settings.SOFT_TAKEOVER_TOLERANCE:
            return True
        # Crossed it between two messages: a quick move can step right over
        # the tolerance window without ever landing inside it.
        return previous is not None and (previous - current) * (percent - current) <= 0

    def _consume_learn(self, number, channel, accepts_kind):
        """Assigns a pending Learn if the message type matches what it wants."""
        if not self._learn_target:
            return False
        kind, key = self._learn_target
        if not accepts_kind(kind):
            return True  # swallow: wrong message type for this binding
        displaced = self._bindings.assign(kind, key, number, channel)
        self._learn_target = None
        self.on_learned(kind, key, number, displaced)
        return True

    def _invoke_note_action(self, kind, key):
        if kind == "mute_note":
            self._mixer.toggle_mute(key)
        elif kind == "solo_note":
            self._mixer.toggle_solo(key)
        elif kind == "route_note":
            chan_id, _, out_id = key.partition(":")
            self._mixer.toggle_route(chan_id, out_id)
        elif kind == "output_mute_note":
            self._mixer.toggle_output_mute(key)
        elif kind == "output_solo_note":
            self._mixer.toggle_output_solo(key)
        elif kind == "scene_note":
            self._mixer.recall_scene(key, from_surface=True)


class NullMidiController:
    """Stand-in used when no control surface is connected.

    Substitutable for MidiController so the UI never has to test for its
    absence: Learn simply never completes, and LED updates go nowhere.
    """

    connected = False
    learning = None

    def __init__(self):
        self.on_learned = lambda kind, key, number, displaced: None
        self.on_surface = lambda event, kind, key, value: None

    def start_learn(self, kind, key):
        pass

    def cancel_learn(self):
        pass

    def set_led(self, binding, on):
        pass

    def sync_leds(self):
        pass

    def reflect_change(self, change_kind, key, value):
        pass

    def close(self):
        pass
