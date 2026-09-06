"""The effects a strip can carry, and the filter graph they turn into.

A curated set rather than a general plugin host. Pipeworks is a mixer, not a
DAW: what a microphone actually needs is noise suppression, a high-pass, a gate,
a compressor and some tone, in that order, with a handful of controls each. Two
dozen ports per LSP plugin exposed raw would be worse, not better.

Each effect is described here once - what it is made of, what a front end should
show, and how a value on screen maps to the value the plugin wants. The daemon
turns the enabled ones into a PipeWire filter-chain config; the window renders
the same description as sliders. Neither has its own copy of the list.

Values are stored and shown in units a person recognises - dB, Hz, ms, a ratio -
and converted on the way to the plugin, because LSP takes thresholds as linear
amplitude and nobody thinks in those.
"""

# Order is the signal chain, not a preference: suppression before the gate so it
# is not gating noise, the gate before the compressor so the compressor is not
# lifting the noise floor, tone last.
EFFECTS = [
    {
        "id": "noise",
        "label": "Noise suppression",
        "description": "Removes steady background noise - fans, hiss, traffic - "
                       "while leaving speech alone.",
        "nodes": [
            {
                "name": "noise",
                "type": "ladspa",
                "plugin": "librnnoise_ladspa",
                "label": "noise_suppressor_mono",
                "in_port": "Input",
                "out_port": "Output",
            }
        ],
        "controls": [
            {
                "id": "vad",
                "label": "Voice threshold",
                "help": "How sure it must be that a sound is speech before letting "
                        "it through. Higher cuts more noise and more of you.",
                "node": "noise",
                "port": "VAD Threshold (%)",
                "unit": "%",
                "minimum": 0.0,
                "maximum": 95.0,
                "default": 50.0,
                "scale": "direct",
            }
        ],
    },
    {
        "id": "highpass",
        "label": "High-pass",
        "description": "Cuts rumble, desk knocks and breath below the voice.",
        "nodes": [
            {
                "name": "highpass",
                "type": "builtin",
                "label": "bq_highpass",
                "in_port": "In",
                "out_port": "Out",
            }
        ],
        "controls": [
            {
                "id": "freq",
                "label": "Frequency",
                "help": "Everything below this is removed. 80-120 Hz suits most voices.",
                "node": "highpass",
                "port": "Freq",
                "unit": "Hz",
                "minimum": 20.0,
                "maximum": 300.0,
                "default": 90.0,
                "scale": "direct",
            }
        ],
    },
    {
        "id": "gate",
        "label": "Gate",
        "description": "Silences the microphone when you are not talking.",
        "nodes": [
            {
                "name": "gate",
                "type": "lv2",
                "plugin": "http://lsp-plug.in/plugins/lv2/gate_mono",
                "in_port": "in",
                "out_port": "out",
            }
        ],
        "controls": [
            {
                "id": "threshold",
                "label": "Threshold",
                "help": "Sound quieter than this is muted. Set it just above your "
                        "room's noise floor.",
                "node": "gate",
                "port": "gt",
                "unit": "dB",
                "minimum": -80.0,
                "maximum": 0.0,
                "default": -45.0,
                "scale": "db",
            },
            {
                "id": "attack",
                "label": "Attack",
                "help": "How quickly it opens once you speak.",
                "node": "gate",
                "port": "at",
                "unit": "ms",
                "minimum": 0.0,
                "maximum": 200.0,
                "default": 10.0,
                "scale": "direct",
            },
        ],
    },
    {
        "id": "compressor",
        "label": "Compressor",
        "description": "Evens out loud and quiet speech so your level stays steady.",
        "nodes": [
            {
                "name": "compressor",
                "type": "lv2",
                "plugin": "http://lsp-plug.in/plugins/lv2/compressor_mono",
                "in_port": "in",
                "out_port": "out",
            }
        ],
        "controls": [
            {
                "id": "threshold",
                "label": "Threshold",
                "help": "Speech above this gets turned down.",
                "node": "compressor",
                "port": "al",
                "unit": "dB",
                "minimum": -60.0,
                "maximum": 0.0,
                "default": -18.0,
                "scale": "db",
            },
            {
                "id": "ratio",
                "label": "Ratio",
                "help": "How hard it turns down what crosses the threshold.",
                "node": "compressor",
                "port": "cr",
                "unit": ":1",
                "minimum": 1.0,
                "maximum": 20.0,
                "default": 4.0,
                "scale": "direct",
            },
            {
                "id": "attack",
                "label": "Attack",
                "help": "How quickly it reacts to a loud moment.",
                "node": "compressor",
                "port": "at",
                "unit": "ms",
                "minimum": 0.0,
                "maximum": 200.0,
                "default": 20.0,
                "scale": "direct",
            },
            {
                "id": "makeup",
                "label": "Makeup",
                "help": "Lifts the whole signal back up after compression.",
                "node": "compressor",
                "port": "mk",
                "unit": "dB",
                "minimum": 0.0,
                "maximum": 24.0,
                "default": 6.0,
                "scale": "db",
            },
        ],
    },
    {
        "id": "eq",
        "label": "Tone",
        "description": "Three bands of shelving and mid lift or cut.",
        # One biquad per band, chained inside the effect.
        "nodes": [
            {
                "name": "eq_low",
                "type": "builtin",
                "label": "bq_lowshelf",
                "in_port": "In",
                "out_port": "Out",
                "control": {"Freq": 200.0, "Q": 1.0, "Gain": 0.0},
            },
            {
                "name": "eq_mid",
                "type": "builtin",
                "label": "bq_peaking",
                "in_port": "In",
                "out_port": "Out",
                "control": {"Freq": 1500.0, "Q": 1.0, "Gain": 0.0},
            },
            {
                "name": "eq_high",
                "type": "builtin",
                "label": "bq_highshelf",
                "in_port": "In",
                "out_port": "Out",
                "control": {"Freq": 5000.0, "Q": 1.0, "Gain": 0.0},
            },
        ],
        "links": [("eq_low", "eq_mid"), ("eq_mid", "eq_high")],
        "controls": [
            {
                "id": "low",
                "label": "Low",
                "help": "Body and warmth, below 200 Hz.",
                "node": "eq_low",
                "port": "Gain",
                "unit": "dB",
                "minimum": -12.0,
                "maximum": 12.0,
                "default": 0.0,
                "scale": "direct",
            },
            {
                "id": "mid",
                "label": "Mid",
                "help": "Presence around 1.5 kHz, where speech carries.",
                "node": "eq_mid",
                "port": "Gain",
                "unit": "dB",
                "minimum": -12.0,
                "maximum": 12.0,
                "default": 0.0,
                "scale": "direct",
            },
            {
                "id": "high",
                "label": "High",
                "help": "Air and clarity above 5 kHz.",
                "node": "eq_high",
                "port": "Gain",
                "unit": "dB",
                "minimum": -12.0,
                "maximum": 12.0,
                "default": 0.0,
                "scale": "direct",
            },
        ],
    },
]

EFFECTS_BY_ID = {effect["id"]: effect for effect in EFFECTS}


def control_spec(effect_id, control_id):
    effect = EFFECTS_BY_ID.get(effect_id)
    if not effect:
        return None
    return next((c for c in effect["controls"] if c["id"] == control_id), None)


def default_controls(effect_id):
    effect = EFFECTS_BY_ID.get(effect_id)
    return {c["id"]: c["default"] for c in effect["controls"]} if effect else {}


def plugin_value(spec, value):
    """The value on screen, in the units the plugin actually wants.

    LSP takes thresholds and gains as linear amplitude rather than dB, so a
    threshold shown as -45 dB reaches the plugin as 0.0056. Builtin biquads take
    their shelf gains in dB directly, which is why the scale is per control and
    not per unit.
    """
    number = float(value)
    if spec.get("scale") == "db":
        return 10.0 ** (number / 20.0)
    return number


def port_name(spec):
    """How a control is addressed on the live node, as "<node>:<port>"."""
    return f"{spec['node']}:{spec['port']}"


def enabled_effects(strip_effects):
    """The effect ids that are switched on, in signal-chain order."""
    strip_effects = strip_effects or {}
    return [
        effect["id"]
        for effect in EFFECTS
        if (strip_effects.get(effect["id"]) or {}).get("enabled")
    ]


def control_value(strip_effects, effect_id, control_id):
    """A stored control value, falling back to the effect's default."""
    stored = ((strip_effects or {}).get(effect_id) or {}).get("controls") or {}
    if control_id in stored:
        return stored[control_id]
    spec = control_spec(effect_id, control_id)
    return spec["default"] if spec else 0.0


def build_graph(strip_effects):
    """The filter.graph nodes and links for one strip's enabled effects.

    Returns (nodes, links), links being (source, source_port, dest, dest_port).
    Ports are carried per node because every plugin names them differently -
    builtin biquads use In/Out, RNNoise uses Input/Output, LSP uses in/out - and
    guessing produces a graph that fails to load rather than one that sounds
    wrong. Empty when nothing is enabled, which is the caller's cue to run no
    filter chain at all rather than an empty one.
    """
    active = enabled_effects(strip_effects)
    nodes = []
    links = []
    previous_tail = None

    for effect_id in active:
        effect = EFFECTS_BY_ID[effect_id]
        for node in effect["nodes"]:
            entry = {"name": node["name"], "type": node["type"]}
            if node.get("plugin"):
                entry["plugin"] = node["plugin"]
            if node.get("label"):
                entry["label"] = node["label"]
            entry["in_port"] = node["in_port"]
            entry["out_port"] = node["out_port"]
            entry["control"] = dict(node.get("control") or {})
            nodes.append(entry)

        # Wire this effect's own nodes together, then hang it off the previous
        # effect's last node.
        by_name = {node["name"]: node for node in effect["nodes"]}
        for source, dest in effect.get("links", []):
            links.append((source, by_name[source]["out_port"], dest, by_name[dest]["in_port"]))
        head = effect["nodes"][0]
        if previous_tail:
            links.append(
                (previous_tail["name"], previous_tail["out_port"],
                 head["name"], head["in_port"])
            )
        previous_tail = effect["nodes"][-1]

        # Stored control values override the node defaults declared above.
        for spec in effect["controls"]:
            value = plugin_value(spec, control_value(strip_effects, effect_id, spec["id"]))
            for entry in nodes:
                if entry["name"] == spec["node"]:
                    entry["control"][spec["port"]] = value

    return nodes, links


def catalogue():
    """The effect list as a front end needs it: no graph detail, just what to
    show and the range of every control."""
    return [
        {
            "id": effect["id"],
            "label": effect["label"],
            "description": effect["description"],
            "controls": [
                {
                    "id": c["id"],
                    "label": c["label"],
                    "help": c["help"],
                    "unit": c["unit"],
                    "minimum": c["minimum"],
                    "maximum": c["maximum"],
                    "default": c["default"],
                }
                for c in effect["controls"]
            ],
        }
        for effect in EFFECTS
    ]
