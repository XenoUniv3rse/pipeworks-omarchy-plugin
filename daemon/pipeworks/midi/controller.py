"""Control-surface I/O: reads the board, drives its LEDs, runs Learn.

Translates MIDI messages into mixer commands and mixer state back into LED
states. Incoming messages arrive on rtmidi's own thread, so they are handed to
the injected dispatcher before touching anything else.
"""
import rtmidi

from .. import settings

NOTE_ON = 0x90
CONTROL_CHANGE = 0xB0
LED_ON_VELOCITY = 127


class MidiPortsNotFound(RuntimeError):
    pass


class MidiController:
    def __init__(self, mixer, bindings, dispatch, port_match=settings.MIDI_PORT_MATCH):
        self._mixer = mixer
        self._bindings = bindings
        self._dispatch = dispatch

        self._learn_target = None
        self.on_learned = lambda kind, key, number: None

        self._midi_in = rtmidi.MidiIn(rtmidi.API_LINUX_ALSA)
        self._midi_out = rtmidi.MidiOut(rtmidi.API_LINUX_ALSA)
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

    # ------------------------------------------------------------------
    # Learn

    def start_learn(self, kind, key):
        self._learn_target = (kind, key)

    def cancel_learn(self):
        self._learn_target = None

    # ------------------------------------------------------------------
    # LEDs

    def set_led(self, note, on):
        self._midi_out.send_message([NOTE_ON, note, LED_ON_VELOCITY if on else 0])

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
        if status == NOTE_ON:
            note, velocity = message[1], message[2]
            if velocity > 0:  # note-on with velocity 0 is a release
                self._dispatch(self._handle_note, note)
        elif status == CONTROL_CHANGE:
            self._dispatch(self._handle_cc, message[1], message[2])

    def _handle_note(self, note):
        if self._consume_learn(note, self._bindings.is_note_kind):
            return
        for kind, key in self._bindings.matches_for_note(note):
            self._invoke_note_action(kind, key)
            return

    def _handle_cc(self, controller, value):
        if self._consume_learn(controller, self._bindings.is_cc_kind):
            return
        percent = round(value / 127 * 100)
        for kind, key in self._bindings.matches_for_cc(controller):
            if kind == "volume_cc":
                self._mixer.set_volume(key, percent)
            else:
                self._mixer.set_output_volume(key, percent)
            return

    def _consume_learn(self, number, accepts_kind):
        """Assigns a pending Learn if the message type matches what it wants."""
        if not self._learn_target:
            return False
        kind, key = self._learn_target
        if not accepts_kind(kind):
            return True  # swallow: wrong message type for this binding
        self._bindings.assign(kind, key, number)
        self._learn_target = None
        self.on_learned(kind, key, number)
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


class NullMidiController:
    """Stand-in used when no control surface is connected.

    Substitutable for MidiController so the UI never has to test for its
    absence: Learn simply never completes, and LED updates go nowhere.
    """

    def __init__(self):
        self.on_learned = lambda kind, key, number: None

    def start_learn(self, kind, key):
        pass

    def cancel_learn(self):
        pass

    def set_led(self, note, on):
        pass

    def sync_leds(self):
        pass

    def reflect_change(self, change_kind, key, value):
        pass
