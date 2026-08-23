"""Pipeworks - a Voicemeeter-style virtual mixer for PipeWire, driven by a
SINCO SMC-Mixer MIDI control surface.

Layout:
    settings      paths and tunables
    config        schema and persistence
    runner        the one place external commands are executed
    autostart     desktop autostart entry
    audio/        domain: mixing rules, metering, the backend abstraction
    pipewire/     the PipeWire implementation of that abstraction
    midi/         control-surface bindings and I/O
    ui/           GTK presentation
    app           composition root
"""
