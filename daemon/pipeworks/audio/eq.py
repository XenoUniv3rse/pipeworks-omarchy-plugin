"""The per-channel parametric equaliser.

Every channel can carry an EQ of up to MAX_BANDS bands plus a preamp. It runs
as that channel's own filter chain, sitting between the channel's loopback and
the outputs it is routed to, so it shapes the channel wherever it plays.

A band is one PipeWire builtin biquad. Their frequency, gain and Q are live
controls on the running chain, so dragging a band is heard as it moves; only
changing a band's type, switching a band on or off, or bypassing the whole EQ
rebuilds the graph, which restarts the chain and blips that channel.

Stored shape, on the channel as "eq":
    {"enabled": bool, "preamp": dB,
     "bands": [{"type", "freq" (Hz), "gain" (dB), "q", "enabled"}, ...]}
"""
import copy
import math

MAX_BANDS = 10

# Band type -> PipeWire builtin label. Order is what a picker shows.
BAND_TYPES = {
    "peaking": "bq_peaking",
    "lowshelf": "bq_lowshelf",
    "highshelf": "bq_highshelf",
    "highpass": "bq_highpass",
    "lowpass": "bq_lowpass",
    "notch": "bq_notch",
    "bandpass": "bq_bandpass",
}

# Types whose gain means something. A pass, notch or band-pass filter has a
# shape but no boost or cut, so its gain is ignored and not shown.
GAIN_TYPES = ("peaking", "lowshelf", "highshelf")

LIMITS = {
    "freq": (20.0, 20000.0),
    "gain": (-24.0, 24.0),
    "q": (0.1, 18.0),
    "preamp": (-24.0, 12.0),
}

# The graph rate the response curve is drawn for. Biquad shapes near Nyquist
# depend on it; across the audible band any common rate draws the same.
SAMPLE_RATE = 48000.0


def _band(type_, freq, gain=0.0, q=1.0, enabled=True):
    return {"type": type_, "freq": float(freq), "gain": float(gain),
            "q": float(q), "enabled": enabled}


def _flat_bands():
    return [
        _band("lowshelf", 80, q=0.7),
        _band("peaking", 250),
        _band("peaking", 1000),
        _band("peaking", 4000),
        _band("highshelf", 10000, q=0.7),
    ]


# Starting points rather than corrections for any particular gear - each is a
# few broad moves that are easy to see on the curve and adjust from.
PRESETS = [
    {"id": "flat", "label": "Flat", "preamp": 0.0, "bands": _flat_bands()},
    {"id": "bass_boost", "label": "Bass boost", "preamp": -5.0, "bands": [
        _band("lowshelf", 110, 6.0, 0.7), _band("peaking", 60, 2.0, 1.0),
        _band("peaking", 400, -1.5, 1.2), _band("peaking", 4000, 0.0),
        _band("highshelf", 10000, 0.0, 0.7)]},
    {"id": "bass_cut", "label": "Bass cut", "preamp": 0.0, "bands": [
        _band("highpass", 60, q=0.7), _band("lowshelf", 150, -6.0, 0.7),
        _band("peaking", 1000, 0.0), _band("peaking", 4000, 0.0),
        _band("highshelf", 10000, 0.0, 0.7)]},
    {"id": "treble_boost", "label": "Treble boost", "preamp": -4.0, "bands": [
        _band("lowshelf", 80, 0.0, 0.7), _band("peaking", 250, 0.0),
        _band("peaking", 3000, 1.5, 1.0), _band("peaking", 6000, 2.0, 1.0),
        _band("highshelf", 9000, 5.0, 0.7)]},
    {"id": "loudness", "label": "Loudness", "preamp": -6.0, "bands": [
        _band("lowshelf", 90, 6.0, 0.7), _band("peaking", 250, 0.0),
        _band("peaking", 1200, -2.0, 0.8), _band("peaking", 4000, 0.0),
        _band("highshelf", 9000, 5.0, 0.7)]},
    {"id": "vocal", "label": "Vocal clarity", "preamp": -4.0, "bands": [
        _band("highpass", 90, q=0.7), _band("peaking", 250, -3.0, 1.0),
        _band("peaking", 1500, 1.5, 1.0), _band("peaking", 3200, 3.5, 1.2),
        _band("highshelf", 9000, 1.5, 0.7)]},
    {"id": "podcast", "label": "Podcast / speech", "preamp": -3.0, "bands": [
        _band("highpass", 100, q=0.7), _band("peaking", 200, -2.5, 1.0),
        _band("peaking", 2500, 3.0, 1.0), _band("peaking", 6500, -2.0, 2.0),
        _band("lowpass", 12000, q=0.7)]},
    {"id": "footsteps", "label": "Gaming footsteps", "preamp": -5.0, "bands": [
        _band("lowshelf", 120, -6.0, 0.7), _band("peaking", 400, -2.0, 1.0),
        _band("peaking", 2000, 3.0, 1.2), _band("peaking", 4500, 5.0, 1.4),
        _band("highshelf", 10000, -2.0, 0.7)]},
    {"id": "cinema", "label": "Cinema", "preamp": -6.0, "bands": [
        _band("lowshelf", 70, 5.0, 0.7), _band("peaking", 300, -1.5, 1.0),
        _band("peaking", 2500, 2.5, 1.0), _band("peaking", 5000, 0.0),
        _band("highshelf", 10000, 3.0, 0.7)]},
    {"id": "night", "label": "Night mode", "preamp": 0.0, "bands": [
        _band("highpass", 80, q=0.7), _band("lowshelf", 150, -6.0, 0.7),
        _band("peaking", 2500, 2.0, 0.8), _band("peaking", 4000, 0.0),
        _band("highshelf", 9000, -3.0, 0.7)]},
    {"id": "warm", "label": "Warm", "preamp": -3.0, "bands": [
        _band("lowshelf", 200, 3.0, 0.7), _band("peaking", 500, 1.0, 0.8),
        _band("peaking", 3000, -1.5, 1.0), _band("peaking", 4000, 0.0),
        _band("highshelf", 8000, -3.0, 0.7)]},
    {"id": "bright", "label": "Bright", "preamp": -4.0, "bands": [
        _band("lowshelf", 100, -2.0, 0.7), _band("peaking", 250, -1.0),
        _band("peaking", 2000, 1.0, 1.0), _band("peaking", 5000, 3.0, 1.0),
        _band("highshelf", 10000, 4.0, 0.7)]},
]

PRESETS_BY_ID = {preset["id"]: preset for preset in PRESETS}


def default_eq():
    """A channel's EQ before anyone touches it: off, and flat if switched on."""
    return {"enabled": False, "preamp": 0.0, "bands": _flat_bands()}


def _clamp(value, limits, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(number) or math.isinf(number):
        return fallback
    return max(limits[0], min(limits[1], number))


def normalize(eq):
    """A clean, bounded copy of an EQ as sent by a front end.

    Anything malformed falls back to a safe value rather than reaching the
    graph: a NaN or an unknown filter type would stop the chain loading.
    """
    eq = eq if isinstance(eq, dict) else {}
    bands = []
    raw_bands = [b for b in (eq.get("bands") or []) if isinstance(b, dict)]
    for raw in raw_bands[:MAX_BANDS]:
        type_ = raw.get("type") if raw.get("type") in BAND_TYPES else "peaking"
        bands.append({
            "type": type_,
            "freq": _clamp(raw.get("freq"), LIMITS["freq"], 1000.0),
            "gain": _clamp(raw.get("gain"), LIMITS["gain"], 0.0),
            "q": _clamp(raw.get("q"), LIMITS["q"], 1.0),
            "enabled": raw.get("enabled", True) is not False,
        })
    return {
        "enabled": eq.get("enabled") is True,
        "preamp": _clamp(eq.get("preamp", 0.0), LIMITS["preamp"], 0.0),
        "bands": bands,
    }


def active(eq):
    """Whether this EQ needs a chain at all: on, with at least one live band."""
    eq = eq or {}
    return bool(eq.get("enabled")) and (
        any(band.get("enabled", True) for band in eq.get("bands") or [])
        or abs(float(eq.get("preamp") or 0.0)) > 1e-6
    )


def structure(eq):
    """What changing would mean rebuilding the graph (everything not live)."""
    eq = eq or {}
    return (
        active(eq),
        tuple((b["type"], bool(b.get("enabled", True))) for b in eq.get("bands") or []),
    )


def node_name(index):
    """A band's node name. By position in the full list, so it stays the same
    when another band is switched off - which is what lets controls stay live."""
    return f"band{index + 1}"


def build_graph(eq):
    """(nodes, links) for the filter chain, in FilterChainHost's format.

    The preamp is a builtin mixer at the head of the chain; the enabled bands
    follow in list order.
    """
    nodes = [{
        "name": "preamp", "type": "builtin", "label": "mixer",
        "in_port": "In 1", "out_port": "Out",
        "control": {"Gain 1": 10 ** (float(eq.get("preamp", 0.0)) / 20)},
    }]
    for index, band in enumerate(eq.get("bands") or []):
        if not band.get("enabled", True):
            continue
        nodes.append({
            "name": node_name(index), "type": "builtin",
            "label": BAND_TYPES[band["type"]],
            "in_port": "In", "out_port": "Out",
            "control": {"Freq": band["freq"], "Q": band["q"], "Gain": band["gain"]},
        })
    links = [
        (a["name"], a["out_port"], b["name"], b["in_port"])
        for a, b in zip(nodes, nodes[1:])
    ]
    return nodes, links


def graph_io(nodes):
    """The chain's input and output ports, named explicitly.

    Required, not tidiness: the preamp is a builtin mixer with eight inputs,
    and without this filter-chain treats all eight as the chain's inputs.
    """
    return ([f'{nodes[0]["name"]}:{nodes[0]["in_port"]}'],
            [f'{nodes[-1]["name"]}:{nodes[-1]["out_port"]}'])


def live_controls(eq):
    """Every live control port and its value, as "<node>:<port>" -> number."""
    controls = {"preamp:Gain 1": 10 ** (float(eq.get("preamp", 0.0)) / 20)}
    for index, band in enumerate(eq.get("bands") or []):
        if not band.get("enabled", True):
            continue
        name = node_name(index)
        controls[f"{name}:Freq"] = band["freq"]
        controls[f"{name}:Q"] = band["q"]
        controls[f"{name}:Gain"] = band["gain"]
    return controls


# ----------------------------------------------------------------------
# Response, for checking the curve the window draws against the real thing.
# The window carries its own copy of these formulas (EqMath.js); tests hold the
# two to the measured response of the actual PipeWire filters.

def coefficients(band, rate=SAMPLE_RATE):
    """Normalised (b0, b1, b2, a1, a2) - Robert Bristow-Johnson's cookbook."""
    f, q, gain = band["freq"], max(band["q"], 1e-4), band["gain"]
    w0 = 2 * math.pi * min(f, rate * 0.499) / rate
    cos_w, sin_w = math.cos(w0), math.sin(w0)
    a = 10 ** (gain / 40)
    alpha = sin_w / (2 * q)
    t = band["type"]
    if t == "peaking":
        b = (1 + alpha * a, -2 * cos_w, 1 - alpha * a)
        d = (1 + alpha / a, -2 * cos_w, 1 - alpha / a)
    elif t in ("lowshelf", "highshelf"):
        # PipeWire takes a shelf's Q as a true Q, not the cookbook's slope S:
        # measured against the real filters, 0.707 is the plain shelf and
        # higher values overshoot into a bump either side of the corner.
        k = 2 * math.sqrt(a) * alpha
        if t == "lowshelf":
            b = (a * ((a + 1) - (a - 1) * cos_w + k), 2 * a * ((a - 1) - (a + 1) * cos_w),
                 a * ((a + 1) - (a - 1) * cos_w - k))
            d = ((a + 1) + (a - 1) * cos_w + k, -2 * ((a - 1) + (a + 1) * cos_w),
                 (a + 1) + (a - 1) * cos_w - k)
        else:
            b = (a * ((a + 1) + (a - 1) * cos_w + k), -2 * a * ((a - 1) + (a + 1) * cos_w),
                 a * ((a + 1) + (a - 1) * cos_w - k))
            d = ((a + 1) - (a - 1) * cos_w + k, 2 * ((a - 1) - (a + 1) * cos_w),
                 (a + 1) - (a - 1) * cos_w - k)
    elif t == "lowpass":
        b = ((1 - cos_w) / 2, 1 - cos_w, (1 - cos_w) / 2)
        d = (1 + alpha, -2 * cos_w, 1 - alpha)
    elif t == "highpass":
        b = ((1 + cos_w) / 2, -(1 + cos_w), (1 + cos_w) / 2)
        d = (1 + alpha, -2 * cos_w, 1 - alpha)
    elif t == "notch":
        b = (1, -2 * cos_w, 1)
        d = (1 + alpha, -2 * cos_w, 1 - alpha)
    else:  # bandpass, constant 0 dB peak gain
        b = (alpha, 0, -alpha)
        d = (1 + alpha, -2 * cos_w, 1 - alpha)
    return (b[0] / d[0], b[1] / d[0], b[2] / d[0], d[1] / d[0], d[2] / d[0])


def band_response_db(band, freq, rate=SAMPLE_RATE):
    b0, b1, b2, a1, a2 = coefficients(band, rate)
    w = 2 * math.pi * freq / rate
    z1 = complex(math.cos(-w), math.sin(-w))
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1 + a1 * z1 + a2 * z2)
    return 20 * math.log10(max(abs(h), 1e-12))


def response_db(eq, freq, rate=SAMPLE_RATE):
    """The whole EQ's gain at one frequency, preamp included."""
    total = float(eq.get("preamp", 0.0))
    for band in eq.get("bands") or []:
        if band.get("enabled", True):
            total += band_response_db(band, freq, rate)
    return total


def catalogue():
    """What a front end needs to draw and edit an EQ."""
    return {
        "maxBands": MAX_BANDS,
        "types": list(BAND_TYPES),
        "gainTypes": list(GAIN_TYPES),
        "limits": {k: list(v) for k, v in LIMITS.items()},
        "sampleRate": SAMPLE_RATE,
        "presets": copy.deepcopy(PRESETS),
    }
