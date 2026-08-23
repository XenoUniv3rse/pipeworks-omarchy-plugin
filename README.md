# Pipeworks — Omarchy plugin

A Voicemeeter-style virtual audio mixer for PipeWire, driven by a MIDI control
surface, packaged as a single Omarchy shell plugin.

Route each application to its own channel, then control those channels from the
top bar or from real faders and buttons.

## Install

```sh
omarchy plugin add https://github.com/ebirkhoff/pipeworks-omarchy-plugin.git --enable
omarchy bar put pipeworks.mixer --before omarchy.audio
```

That is the whole install. The plugin bundles the mixer daemon, so there is no
separate application to install and no systemd unit to enable.

### System packages

The daemon is Python and needs three libraries that cannot sensibly come from
PyPI. Install them once:

```sh
sudo pacman -S python-gobject python-rtmidi python-numpy
```

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
| Middle click the bar icon | Open the full mixer window |
| Panel fader | Set that strip's level |
| Panel speaker icon | Toggle mute |
| Panel output buttons | Toggle routing of that channel to that output |
| "Open mixer" | Open the full window |

The bar icon highlights whenever anything is muted, which is usually the answer
to "why can I not hear this".

## What it does

* **Virtual channels** — sinks that applications play into (System, Game,
  Music, Browser, Chat, or whatever you name them), each with its own fader,
  mute, solo and per-output routing.
* **Inputs** — a hardware microphone is republished as a virtual capture device,
  so Discord and OBS see a mic with this mixer's volume and mute already
  applied.
* **Physical outputs** — send any channel to any combination of real output
  devices, each with its own fader, mute and solo.
* **MIDI control** — Learn any fader or button on a control surface, with LED
  feedback on boards that support it.
* **Application routing** — assign running applications to channels; the choice
  is remembered next time they start.

## Layout

```
manifest.json      plugin manifest (id: pipeworks.mixer)
Service.qml        supervises the daemon
MixerWidget.qml    the bar widget and its fader panel
daemon/            the mixer itself
  run.py           launcher
  pipeworks/       audio domain, PipeWire adapters, MIDI, GTK window
```

The daemon publishes `org.gtk.Actions` on the session bus, which is how the bar
widget drives it — and how anything else could:

```sh
gdbus call --session --dest io.github.pipeworks.Pipeworks \
  --object-path /io/github/pipeworks/Pipeworks \
  --method org.gtk.Actions.Activate "toggle-mute" "[<'music'>]" "{}"
```

Actions: `set-volume`, `set-output-volume`, `toggle-mute`,
`toggle-output-mute`, `toggle-route`, `show-window`.

## Configuration

`~/.config/pipeworks/config.json` holds channels, routing and MIDI bindings.

Virtual devices are declared in
`~/.config/pipewire/pipewire.conf.d/10-pipeworks.conf`, regenerated when
channels or inputs are added or removed. PipeWire reads that file at startup, so
those two operations restart PipeWire and briefly interrupt audio; adding an
output does not.

## License

MIT
