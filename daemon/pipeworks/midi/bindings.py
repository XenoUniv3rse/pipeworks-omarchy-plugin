"""The control-surface binding table.

Owns which MIDI number is attached to which control and how a state change maps
back to an LED. Keeping that knowledge here means adding a bindable control is a
change to these tables rather than to dispatch logic scattered through the
controller.
"""

# Bindings driven by note messages (buttons) and by control changes (faders).
NOTE_KINDS = (
    "mute_note",
    "solo_note",
    "route_note",
    "output_mute_note",
    "output_solo_note",
    "scene_note",
)
CC_KINDS = ("volume_cc", "output_volume_cc")

# Which binding table lights the LED for a given state change.
LED_MAP_FOR_CHANGE = {
    "mute": "mute_note",
    "solo": "solo_note",
    "route": "route_note",
    "output_mute": "output_mute_note",
    "output_solo": "output_solo_note",
}


def binding_number(bound):
    """The note or CC number a binding answers to.

    A binding is stored either as a bare number - written before channels were
    recorded, and answering on every channel - or as {"channel", "number"}.
    """
    if isinstance(bound, dict):
        return bound.get("number")
    return bound


def binding_channel(bound):
    """The MIDI channel (0-15) a binding is limited to, or None for any."""
    if isinstance(bound, dict):
        return bound.get("channel")
    return None


def binding_answers(bound, number, channel):
    """Whether a binding responds to `number` arriving on `channel`.

    A channel of None on either side means "any", so an old bare-number
    binding keeps working whatever channel the board sends on.
    """
    if bound is None or binding_number(bound) != number:
        return False
    bound_channel = binding_channel(bound)
    return bound_channel is None or channel is None or bound_channel == channel


class MidiBindings:
    def __init__(self, config, repository):
        self._config = config
        self._repository = repository

    @property
    def _tables(self):
        return self._config["midi"]

    def get(self, kind, key):
        return self._tables[kind].get(key)

    def assign(self, kind, key, number, channel=None):
        """Binds a control, taking it away from anything else that had it.

        Only the first binding for a control ever fires, so a second one would
        silently do nothing - moving it is the only result that works.
        Returns the [(kind, key)] it was taken from.

        The channel is recorded so boards that reuse the same numbers on
        several channels (layers, banks) bind each one separately.
        """
        displaced = [
            (other_kind, other_key)
            for other_kind, other_key in self._same_class_matches(kind, number, channel)
            if (other_kind, other_key) != (kind, key)
        ]
        for other_kind, other_key in displaced:
            del self._tables[other_kind][other_key]
        self._tables[kind][key] = (
            number if channel is None else {"channel": channel, "number": number}
        )
        self._repository.save(self._config)
        return displaced

    def _same_class_matches(self, kind, number, channel=None):
        """Bindings that would answer the same physical control as `number`.

        Notes and control changes are separate number spaces: note 17 and CC 17
        are different controls.
        """
        if kind in NOTE_KINDS:
            return self.matches_for_note(number, channel)
        if kind in CC_KINDS:
            return self.matches_for_cc(number, channel)
        return []

    def unassign(self, kind, key):
        """Forgets one binding. Returns what it held, or None."""
        table = self._tables.get(kind)
        if table is None or key not in table:
            return None
        number = table.pop(key)
        self._repository.save(self._config)
        return number

    def is_note_kind(self, kind):
        return kind in NOTE_KINDS

    def is_cc_kind(self, kind):
        return kind in CC_KINDS

    def matches_for_note(self, note, channel=None):
        """[(kind, key)] bound to a note, in table order."""
        return [
            (kind, key)
            for kind in NOTE_KINDS
            for key, bound in self._tables[kind].items()
            if binding_answers(bound, note, channel)
        ]

    def matches_for_cc(self, controller, channel=None):
        return [
            (kind, key)
            for kind in CC_KINDS
            for key, bound in self._tables[kind].items()
            if binding_answers(bound, controller, channel)
        ]

    def led_note_for_change(self, change_kind, key):
        table = LED_MAP_FOR_CHANGE.get(change_kind)
        if table is None:
            return None
        return self._tables[table].get(key)

    def led_states(self):
        """[(binding, is_on)] for every bound button, from current mixer state."""
        config = self._config
        states = []
        for key, note in self._tables["mute_note"].items():
            states.append((note, config["muted"].get(key, False)))
        for key, note in self._tables["solo_note"].items():
            states.append((note, config["solo"].get(key, False)))
        for key, note in self._tables["route_note"].items():
            chan_id, _, out_id = key.partition(":")
            states.append((note, config["routes"].get(chan_id, {}).get(out_id, False)))
        for key, note in self._tables["output_mute_note"].items():
            states.append((note, config["output_muted"].get(key, False)))
        for key, note in self._tables["output_solo_note"].items():
            states.append((note, config["output_solo"].get(key, False)))
        return states
