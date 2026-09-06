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

Effects need two more, and only the effects need them — the mixer runs without:

```sh
sudo pacman -S noise-suppression-for-voice lsp-plugins-lv2 swh-plugins
```

It draws nothing itself, so it needs no GUI toolkit — `python-gobject` is here
for GLib and its session-bus plumbing, not for GTK.

The bar widget checks for them on startup and tells you which are missing, so
you can install the plugin first and sort this out after.

## How it stays running

`omarchy-shell` starts with your graphical session and stays running, so it
makes a perfectly good supervisor: the plugin's `Service.qml` starts the daemon
and keeps it up. Nothing else to enable.

Liveness is decided by asking the session bus whether the daemon's name is
owned, not by watching a child process. The daemon is a single-instance
application, so a second launch hands off to the first and exits immediately —
treating that normal hand-off as a crash would spawn daemons forever.

Closing the mixer window does not stop anything: MIDI, routing and the link
watchdog carry on, and only the level meters stop.

## Controls

| Action | Effect |
|---|---|
| Left click the bar icon | Open/close the fader panel |
| Middle click the bar icon | Open the mixer window |
| Panel fader | Set that strip's level |
| Panel speaker icon | Toggle mute |
| Panel output buttons | Toggle routing of that channel to that output |
| Input output buttons | Monitor that input through that output |

The panel is laid out as a mixer: every strip is vertical and they sit side by
side, Inputs then Channels then Outputs, divided by a rule. Each carries a
vertical level meter beside its fader, showing what that strip is actually
playing. Meters run only while the panel is open, so a closed panel costs
nothing.

In the mixer window every channel also carries an **Apps** block listing what is
currently playing into it, one chip per application in that channel's colour.
Drag a chip onto another channel to move that application there. New
applications appear in whichever channel is your default sink, so routing one is
a drag rather than a trip through pavucontrol.
| "Open mixer" | Open the full window |
| "Volume: …" button | Toggle MIDI-only volume |

## MIDI-only volume

If you would rather levels answered only to the control surface, turn on
**MIDI-only volume** — the toggle at the bottom of the panel, or the "MIDI-only
volume" checkbox in the mixer window:

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "set-volume-lock" "[<true>]" "{}"
```

Faders in both the panel and the window stay visible but go inert and dim, so it
is obvious the level is reserved rather than broken. Mute, solo and routing keep
working from software either way, and the setting persists in
`~/.config/pipeworks/config.json` as `volume_locked`.

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
  individually and adjusted while you listen. Switching one on briefly interrupts that strip;
  moving a control does not.
* **MIDI control** — Learn any fader or button on a control surface, with LED
  feedback on boards that support it.
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
StripSettings.qml  rename, device, MIDI Learn, remove
AddStrip.qml       add a channel, input or output
daemon/            the audio brain — no window, no toolkit
  run.py           launcher
  pipeworks/       audio domain, PipeWire adapters, MIDI, published state
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
`set-volume-lock`, `toggle-volume-lock`.
Application routing: `move-stream`.
Structural: `add-channel`, `add-input`, `add-output`, `remove-strip`,
`rename-strip`, `retarget-input`, `retarget-output`.
An input's microphones: `add-input-source`, `remove-input-source`,
`set-input-source-volume`.
Effects: `set-effect-enabled`, `set-effect-control`. These need no reprovisioning — the sources all feed
one virtual sink that already exists, so adding one is only extra links and
does not interrupt audio the way adding a whole input does.
Control surface: `midi-learn`, `midi-learn-cancel`.
Housekeeping: `set-autostart`, `set-state-watch`, `show-window`.

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
replicates it per channel. Values are stored in the units shown on screen, in dB, Hz and
milliseconds, and converted on the way to the plugin, because LSP takes
thresholds as linear amplitude.

## Configuration

`~/.config/pipeworks/config.json` holds channels, routing and MIDI bindings.

An input lists its microphones under `sources`, each with its own `volume`. That
level is the capture device's own, so it applies wherever the microphone is
used, not only here — PipeWire has no per-link gain to set instead, and giving
each source its own loopback would mean restarting PipeWire every time one was
added. A config written before an input could hold more than one microphone is
migrated on load.

Virtual devices are declared in
`~/.config/pipewire/pipewire.conf.d/10-pipeworks.conf`, regenerated when
channels or inputs are added or removed. PipeWire reads that file at startup, so
those two operations restart PipeWire and briefly interrupt audio; adding an
output does not.

## License

MIT
