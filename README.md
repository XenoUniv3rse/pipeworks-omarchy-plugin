# Pipeworks — Omarchy plugin

A Voicemeeter-style virtual audio mixer for PipeWire, driven by a MIDI control
surface, packaged as a single Omarchy shell plugin.

Route each application to its own channel, then control those channels from the
top bar or from real faders and buttons.

## Install

```sh
omarchy plugin add https://github.com/XenoUniv3rse/pipeworks-omarchy-plugin.git --enable
omarchy bar put pipeworks.mixer --before omarchy.audio
```

That is the whole install. The plugin bundles the mixer daemon, so there is no
separate application to install and no systemd unit to enable.

### System packages

The daemon is Python and needs two libraries that cannot sensibly come from
PyPI. Install them once:

```sh
sudo pacman -S python-gobject python-rtmidi
```

Effects need three more, and only the effects need them — the mixer runs
without:

```sh
sudo pacman -S noise-suppression-for-voice lsp-plugins-lv2 swh-plugins
```

The EQ tuner's live spectrum needs numpy, and only the spectrum does - the EQ
itself works without it:

```sh
sudo pacman -S python-numpy
```

The daemon draws nothing itself, so it needs no GUI toolkit — `python-gobject`
is there for GLib and its session-bus plumbing, not for GTK.

The bar widget checks for the first two on startup and tells you which are
missing, so you can install the plugin first and sort that out after. It does
not check the effect plugins: an effect you have no plugin for simply cannot be
switched on.

## How it stays running

`omarchy-shell` starts with your graphical session and stays running, so it
makes a perfectly good supervisor: the plugin's `Service.qml` starts the daemon
and keeps it up. Nothing else to enable.

Liveness is decided by asking the session bus whether the daemon's name is
owned, not by watching a child process. The daemon is a single-instance
application, so a second launch hands off to the first and exits immediately —
treating that normal hand-off as a crash would spawn daemons forever.

The daemon is what starts with your session — the window is not. Nothing opens
it until you ask, by middle-clicking the bar icon, choosing "Open mixer" in the
panel, or:

```sh
omarchy-shell shell summon pipeworks.mixer '{}'
```

Closing the mixer window does not stop anything: MIDI, routing and the link
watchdog carry on, and only the level meters stop.

Hyprland tiles the window by default, which suits a mixer poorly. To float it,
in `~/.config/hypr/hyprland.lua`:

```lua
o.window({ class = "^org\\.quickshell$", title = "^Pipeworks$" }, {
  float = true,
  size = "1040 660",
  center = true,
})
```

The title match matters: the window shares the `org.quickshell` class with the
shell's other surfaces, so matching on class alone would float those too.

## Controls

| Action | Effect |
|---|---|
| Left click the bar icon | Open/close the fader panel |
| Middle click the bar icon | Open the mixer window |
| Scroll on the bar icon | Turn one strip up or down (the first output, unless set) |
| Panel fader | Set that strip's level |
| Panel speaker icon | Toggle mute |
| Panel output buttons | Toggle routing of that channel to that output |
| Input output buttons | Monitor that input through that output |
| Panel "Open mixer" | Open the mixer window |
| Panel "Volume: …" | Toggle MIDI-only volume |

The panel is laid out as a mixer: every strip is vertical and they sit side by
side, Inputs then Channels then Outputs, divided by a rule. Each carries a
vertical level meter beside its fader, showing what that strip is actually
playing. Amber starts at -12 dBFS and red at -3, so a colour means headroom
running out rather than a healthy level. Meters run only while the panel is
open, so a closed panel costs nothing.

In the mixer window every channel also carries an **Apps** block listing what is
currently playing into it, one chip per application in that channel's colour.
Drag a chip onto another channel to move that application there. New
applications appear in whichever channel is your default sink, so routing one is
a drag rather than a trip through pavucontrol.

The star in a channel's heading marks your default sink - where newly started
applications land. Click the star on another channel to make that the
default instead. Only channels can be chosen here, so new apps never bypass
the mixer by accident.

## Scenes

A scene is the whole mix saved under a name: every level, mute, solo and
route. **Save scene** in the mixer window stores the mix as it is now; click a
scene to recall it, or use the scene buttons in the bar panel. The scene that
matches the live mix is highlighted. The cog beside a scene renames it,
replaces it with the current mix, binds a button on the control surface to
recall it, or deletes it.

Scenes leave structure alone - which strips exist, their devices and their
effects - and a strip added after a scene was saved keeps its own settings when
that scene is recalled. With MIDI-only volume on, recalling a scene from the
window or the bar restores everything except levels; recalling it from the
control surface restores levels too.

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "recall-scene" "[<'gaming'>]" "{}"
```

Scene ids are made from the name when it is saved (`Gaming` → `gaming`) and
stay the same if it is renamed, which is what makes them safe to bind to a
key.

## EQ

Every channel card has an **EQ** button, lit while that channel's EQ is on. It
opens the tuner:

* **The curve.** Drag a numbered handle to move a band in frequency and gain,
  scroll over it to make it wider or narrower (Q), right-click it to switch it
  off and on, and double-click empty space to add a band there. The thick line
  is the shape the bands make; a dashed line shows the result with the preamp
  when the preamp is not at 0.
* **Bands.** Up to ten, each a bell, low or high shelf, low or high cut, notch
  or band-pass. Pick one from the row under the curve to edit it exactly:
  type, on/off, and frequency, gain and Q, each a slider with a value you can
  click and type into (`2.5k` works for frequency).
* **Spectrum.** What the channel is playing, live: grey before the EQ, in the
  channel's colour after it. **Tilt** leans it 3 dB per octave so a balanced
  mix reads level. The scale on the right is dBFS.
* **Presets.** Flat, Bass boost, Bass cut, Treble boost, Loudness, Vocal
  clarity, Podcast, Gaming footsteps, Cinema, Night mode, Warm and Bright, plus
  any you save yourself (marked ★, deletable). The picker shows which preset
  the EQ currently matches, or Custom.
* **Preamp.** Boosting can clip. The tuner shows the curve's highest point and
  warns when it is above 0 dB; **Auto** lowers the preamp until it is not.
* **On / Bypassed** compares against the untouched sound.

Each channel's EQ is its own filter chain between the channel and its outputs,
so it shapes that channel wherever it is routed. Moving a band is applied live,
without a sound; changing a band's type, switching a band on or off, or
bypassing restarts that one channel's chain, which is a brief blip.

The curve is computed from the same filter formulas PipeWire uses - checked
against measured impulse responses of the real filters - so it is what you
hear, not an approximation. One thing worth knowing: PipeWire takes a shelf's
Q as a true Q, so 0.7 is a plain shelf and higher values add a bump either
side of the corner.

The spectrum comes from `daemon/spectrum.py`, which the tuner runs only while
it is open: a mono capture of the channel at 48 kHz, an 8192-point FFT about
thirty times a second, folded into 120 bands from 20 Hz to 20 kHz.

```sh
# The whole EQ travels as JSON: {"enabled", "preamp", "bands": [{"type", "freq", "gain", "q", "enabled"}]}
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "set-eq" \
  "[<('music', '{\"enabled\": true, \"preamp\": -4, \"bands\": [{\"type\": \"lowshelf\", \"freq\": 100, \"gain\": 4, \"q\": 0.7}]}')>]" "{}"
```

## Ducking

A channel can step aside while another one is carrying sound: music and game
audio dipping whenever someone talks in Chat, or whenever your own microphone
is open. Set it in the channel's settings under **Ducking** - pick what it
should duck under (another channel, or an input) and how far to lower it.

The fader does not move. The level sent to PipeWire is scaled while the trigger
is active, the strip shows "ducked", and the channel comes back up, eased over
a fraction of a second, once the trigger has been quiet for 0.8 s - long enough
not to pump between words. A trigger you have muted or turned all the way down
never ducks anything.

To hear whether a trigger is active, the daemon runs one small `pw-record` per
trigger in use, on that strip's sink monitor at 8 kHz mono; the samples are
measured and thrown away. Nothing runs while no channel ducks.

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "set-duck" "[<('music', 'chat', 50.0)>]" "{}"
```

An empty trigger (`''`) switches ducking off for that channel.

## Selecting a control surface

If more than one MIDI device is plugged in, or the wrong one gets picked by
default, choose the right one from **Control surface** at the bottom of the
mixer window. It lists every board ALSA currently sees; picking one switches
to it immediately, with no restart needed. If your board is not listed, plug
it in and it will appear the next time the window polls (a couple of seconds).

## MIDI-only volume

If you would rather levels answered only to the control surface, turn on
**MIDI-only volume** — the toggle at the bottom of the panel, or the button in
the mixer window's header:

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "set-volume-lock" "[<true>]" "{}"
```

Faders in both the panel and the window stay visible but go inert and dim, so it
is obvious the level is reserved rather than broken. Mute, solo and routing keep
working from software either way, and the setting persists in
`~/.config/pipeworks/config.json` as `volume_locked`.

## Soft takeover

Faders on most control surfaces have no motors, so after a level is changed
anywhere but the board - the window, the bar panel, a scene - the physical
fader no longer matches it. With **Soft takeover** on (the default, in the
mixer window under Control surface), that fader is ignored until it is brought
within 3% of the current level or swept through it, and then it takes over
again. Without it, the first touch makes the level jump to wherever the fader
happens to be.

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "set-soft-takeover" "[<false>]" "{}"
```

A fader the board has not moved since the daemon started has nothing to be
compared against, so its first movement always applies.

## On-screen changes

With **Show changes on screen** on (the default, in the mixer window under
Control surface), whatever the board just did appears on the shell's OSD -
"Music 45%" for a fader, "Chat muted" for a button, the scene name for a scene
button. A fader that soft takeover is holding back says where to bring it:
"Game: move up to 70%".

The OSD is reached through `omarchy-shell shell summon omarchy.osd`, because
the shell does not let a third-party plugin summon another plugin directly. A
fader sweep produces dozens of changes a second, so calls run one at a time and
only the newest is sent.

## Scrolling on the bar icon

The mouse wheel over the bar icon turns one strip up or down in 5% steps and
shows the shell's volume OSD. By default that is the first output; to choose
another, name it (or give its id):

```sh
omarchy bar set pipeworks.mixer scrollStrip "Music"
```

With MIDI-only volume on, the wheel changes nothing and the OSD says so.

## The mute indicator

The bar icon highlights whenever anything is muted, which is usually the answer
to "why can I not hear this".

If you keep a strip permanently muted — a second set of speakers you rarely use,
say — exclude it so the icon stays meaningful:

```sh
omarchy bar set pipeworks.mixer mutedIndicatorIgnore "Roof"
```

Accepts a comma-separated list, matched against either the strip's on-screen
name or its id.

## What it does

* **Virtual channels** — sinks that applications play into (System, Game,
  Music, Browser, Chat, or whatever you name them), each with its own fader,
  mute, solo and per-output routing.
* **Inputs** — one or more hardware microphones republished as a single virtual
  capture device, so Discord and OBS see one mic with this mixer's volume and
  mute already applied. An input can carry several: add them in its settings
  and they are summed, each with its own capture level, which is how a headset
  mic and a desk mic reach a call as one device.
* **Physical outputs** — send any channel to any combination of real output
  devices, each with its own fader, mute and solo.
* **Monitoring** — an input can be routed to an output to hear yourself, which
  is how you tell what the effects are actually doing. Per output rather than a
  single switch, so it can go to a headset without howling through speakers.
  Off by default, and it follows the strip's mute and fader.
* **Effects** — a microphone channel strip per input: noise suppression,
  high-pass, gate, compressor, three-band tone and reverb, switched on
  individually and adjusted while you listen. Switching one on briefly
  interrupts that strip; moving a control does not.
* **Channel EQ** — a parametric equaliser on every channel, each tuned
  independently: up to ten bands of seven types, a preamp, presets of its own
  and yours, and a live spectrum of what the channel is playing.
* **Output effects** — high-pass, compressor, three-band tone and a limiter on
  any physical output, processing everything played through that device. Tune
  the room speakers differently from the headset, or keep a ceiling on both.
* **MIDI control** — Learn any fader or button on a control surface, with LED
  feedback on boards that support it. The ✕ beside a binding clears it.
  Learning a control that is already bound elsewhere moves it rather than
  leaving two bindings on one button (only one of which would ever fire), and
  the window says where it was taken from. Bindings record the MIDI channel
  as well as the number, so a board that reuses the same numbers on several
  channels (layers or banks) binds each one separately; bindings learned
  before that are bare numbers and answer on any channel.
* **Application routing** — every channel shows the applications playing into
  it as colour-coded chips; drag a chip onto another channel to move it there,
  and the choice is remembered next time that application starts.

## Layout

```
manifest.json      plugin manifest (id: pipeworks.mixer)
Service.qml        supervises the daemon
MixerWidget.qml    the bar widget and its fader panel
MixerWindow.qml    the mixer window
MixerModel.qml     state and actions shared by the widget and the window
MixerStrip.qml     one channel, input or output as a card
StripGroup.qml     a titled run of strips
Fader.qml          vertical fader
LevelMeter.qml     vertical segmented meter
AppChip.qml        a running application, draggable between channels
StripSettings.qml  rename, device, microphones, effects, MIDI Learn, remove
SceneSettings.qml  save, rename, update, bind and delete a scene
LearnRow.qml       one MIDI Learn row, shared by both dialogs
EqTuner.qml        a channel's EQ: curve, bands, spectrum, presets
EqMath.js          the EQ's frequency response, for drawing it
AddStrip.qml       add a channel, input or output
daemon/            the audio brain — no window, no toolkit
  run.py           launcher
  spectrum.py      live spectrum for the EQ tuner, run only while it is open
  pipeworks/       audio domain, PipeWire adapters, MIDI, effects, published state
```

The split is the thing worth knowing: the daemon owns the audio and nothing
else, and every front end is QML in the Omarchy shell. That is why the window
matches the rest of your desktop — it draws with the shell's own colour and
spacing tokens, so it follows whatever theme is active instead of carrying a
palette of its own.

Because the front ends are out of process, everything they do crosses the
session bus as an `org.gtk.Actions` call — and so can anything else:

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "toggle-mute" "[<'music'>]" "{}"
```

Levels and switches: `set-volume`, `set-output-volume`, `toggle-mute`,
`toggle-output-mute`, `toggle-solo`, `toggle-output-solo`, `toggle-route`,
`set-volume-lock`, `toggle-volume-lock`, `set-soft-takeover`, `set-midi-osd`,
`set-duck`.
Scenes: `save-scene`, `update-scene`, `rename-scene`, `remove-scene`,
`recall-scene`.
Application routing: `move-stream`, `set-default-channel`.
Structural: `add-channel`, `add-input`, `add-output`, `remove-strip`,
`rename-strip`, `retarget-input`, `retarget-output`.
An input's microphones: `add-input-source`, `remove-input-source`,
`set-input-source-volume`. These need no reprovisioning — the sources all feed
one virtual sink that already exists, so adding one is only extra links and does
not interrupt audio the way adding a whole input does.
Channel EQ: `set-eq`, `save-eq-preset`, `remove-eq-preset`.
Effects: `set-effect-enabled`, `set-effect-control`.
Control surface: `midi-learn`, `midi-learn-cancel`, `midi-unbind`, `set-midi-port`.
Housekeeping: `set-autostart`, `set-state-watch`, `show-window`, `quit`.

What a front end needs to *read* rather than command does not fit an action, so
the daemon publishes it as `~/.config/pipeworks/state.json`: running
applications, available devices, MIDI Learn progress, autostart status. It is
only refreshed while a window says it is watching (`set-state-watch`), so an
idle daemon polls nothing.

## Effects

Each strip carrying effects runs its own filter chain: a generated config in
`~/.config/pipeworks/effects/` hosted by a `pipewire -c` process the daemon
supervises. That is the pattern PipeWire ships a systemd unit for, and it is a
process per strip on purpose — switching an effect on rewrites the graph, and a
graph only takes effect when its host restarts. One host per strip means that
restart blips one microphone rather than the whole audio server.

Control values need none of that. Every control port of a running chain is a
node property, so a slider is applied live to the running graph and only the
saved value goes to disk.

With effects on, an input's microphones feed the chain and the chain feeds the
strip's sink, so the strip's own fader and mute still sit after everything. The
chain's nodes are declared `node.autoconnect = false` as well as passive: without
that, WirePlumber helpfully connects the strip's own published microphone into
the chain's input, which is a feedback loop.

Effects come from PipeWire's builtin DSP (the biquads behind high-pass and
tone) plus three plugin packages — RNNoise for noise suppression, LSP for the
gate and compressor, and Steve Harris's plate for the reverb.

The reverb is worth a note, because it took a while to find out. The plate has
one audio input and two outputs, and filter-chain silences a node whose ports
are not all connected: taking only its left output produced a chain that
loaded, exposed all three controls, and passed no audio whatsoever. Both
outputs are summed into a mixer instead, which uses every port and leaves the
effect mono in and mono out, so the graph stays mono and filter-chain still
replicates it per channel.

Outputs carry effects too, from a set suited to a whole device rather than a
voice: high-pass, compressor, tone, and a limiter that only outputs have
(LSP's mono limiter, with its gain boost off so it is a ceiling rather than a
loudness maximiser). With any of them on, every strip routed to that output
links into the output's chain, and the chain links to the device - so the
output's own fader and mute still apply last. The chain adds a few
milliseconds of latency to that output.

A chain that cannot start - a plugin package missing, say - is stopped and
bypassed, so the strip keeps working without its effects instead of going
silent, and the window says so. It is not retried until its settings change.

Values are stored in the units shown on screen — dB, Hz, milliseconds — and
converted on the way to the plugin, because LSP takes thresholds as linear
amplitude and nobody thinks in those.

## Configuration

`~/.config/pipeworks/config.json` holds channels, routing and MIDI bindings.

An input lists its microphones under `sources`, each with its own `volume`. That
level is the capture device's own, so it applies wherever the microphone is
used, not only here — PipeWire has no per-link gain to set instead, and giving
each source its own loopback would mean restarting PipeWire every time one was
added. Its effects are under `effects`, each with an `enabled` flag and its
control values. An input appears in `routes` too, where a `true` means it is
being monitored through that output. A config written before any of this
existed is migrated on load, so an older file keeps working rather than
resetting a carefully learned MIDI map.

Virtual devices are declared in
`~/.config/pipewire/pipewire.conf.d/10-pipeworks.conf`, regenerated when
channels or inputs are added or removed. PipeWire reads that file at startup, so
those two operations restart PipeWire and briefly interrupt audio; adding an
output does not.

## License

MIT
