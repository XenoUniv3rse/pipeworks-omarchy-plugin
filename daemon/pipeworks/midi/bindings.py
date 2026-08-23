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


class MidiBindings:
    def __init__(self, config, repository):
        self._config = config
        self._repository = repository

    @property
    def _tables(self):
        return self._config["midi"]

    def get(self, kind, key):
        return self._tables[kind].get(key)

    def assign(self, kind, key, number):
        self._tables[kind][key] = number
        self._repository.save(self._config)

    def is_note_kind(self, kind):
        return kind in NOTE_KINDS

    def is_cc_kind(self, kind):
        return kind in CC_KINDS

    def matches_for_note(self, note):
        """[(kind, key)] bound to a note, in table order."""
        return [
            (kind, key)
            for kind in NOTE_KINDS
            for key, bound in self._tables[kind].items()
            if bound == note
        ]

    def matches_for_cc(self, controller):
        return [
            (kind, key)
            for kind in CC_KINDS
            for key, bound in self._tables[kind].items()
            if bound == controller
        ]

    def led_note_for_change(self, change_kind, key):
        table = LED_MAP_FOR_CHANGE.get(change_kind)
        if table is None:
            return None
        return self._tables[table].get(key)

    def led_states(self):
        """[(note, is_on)] for every bound button, from current mixer state."""
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
