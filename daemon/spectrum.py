#!/usr/bin/env python3
"""Live spectrum of one channel, for the EQ tuner.

Run by the EQ window while it is open, never by the daemon: nothing listens to
a channel unless someone is looking at its spectrum.

    spectrum.py <sink-name> [bins] [fps]

Captures the sink's monitor (what the channel's applications are playing,
before its EQ), and prints:

    F <freq> <freq> ...        once: the centre of every band, in Hz
    S <dB> <dB> ...            per frame: each band's level in dBFS

The bands are log-spaced from 20 Hz to 20 kHz. Levels fall back slowly rather
than dropping between frames, so the display is readable instead of flickering.
The window adds its own EQ curve to this to show what comes out.
"""
import os
import select
import shutil
import signal
import subprocess
import sys
import time

import numpy as np

RATE = 48000
FFT_SIZE = 8192          # 5.9 Hz per bin: enough to separate the bass bands
FLOOR_DB = -100.0
RELEASE_DB_PER_S = 40.0  # how fast a band falls after a peak


def band_edges(count, low=20.0, high=20000.0):
    centres = np.geomspace(low, high, count)
    ratio = (high / low) ** (1 / (count - 1))
    lower = centres / np.sqrt(ratio)
    upper = centres * np.sqrt(ratio)
    return centres, lower, upper


def main():
    if len(sys.argv) < 2:
        print("usage: spectrum.py <sink-name> [bins] [fps]", file=sys.stderr)
        return 2
    sink = sys.argv[1]
    bins = int(sys.argv[2]) if len(sys.argv) > 2 else 96
    fps = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    hop = int(RATE / fps)

    safe = "".join(c if c.isalnum() else "_" for c in sink)
    props = ("{ stream.capture.sink = true node.dont-reconnect = true "
             f"node.name = pipeworks_spectrum_{safe} "
             'media.name = "Pipeworks spectrum" }')
    capture = subprocess.Popen(
        [shutil.which("pw-record") or "pw-record", "--target", sink, "-P", props,
         # --raw: without it the stream opens with an AU header, whose bytes
         # read as samples include NaNs.
         "--raw", "--rate", str(RATE), "--channels", "1", "--format", "f32", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    def finish(*_):
        if capture.poll() is None:
            capture.terminate()
        sys.exit(0)
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)

    centres, lower, upper = band_edges(bins)
    freqs = np.fft.rfftfreq(FFT_SIZE, 1 / RATE)
    # For each band, the FFT bins inside it. A bass band can be narrower than
    # one bin; it then takes the nearest one, so no band is ever empty.
    spans = []
    for lo, hi, centre in zip(lower, upper, centres):
        start = int(np.searchsorted(freqs, lo))
        stop = int(np.searchsorted(freqs, hi))
        if stop <= start:
            start = int(np.argmin(np.abs(freqs - centre)))
            stop = start + 1
        spans.append((start, stop))

    window = np.hanning(FFT_SIZE).astype(np.float32)
    scale = 2.0 / window.sum()          # a full-scale sine reads 0 dBFS
    history = np.zeros(FFT_SIZE, dtype=np.float32)
    shown = np.full(bins, FLOOR_DB)
    pending = b""
    fd = capture.stdout.fileno()
    last = time.monotonic()

    try:
        sys.stdout.write("F " + " ".join(f"{c:.1f}" for c in centres) + "\n")
        sys.stdout.flush()
        while capture.poll() is None:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                pending += chunk
            if len(pending) < hop * 4:
                continue
            take = len(pending) - len(pending) % (hop * 4)
            # Scrubbed all the same: a single NaN would otherwise stick in the
            # slow-release display below for good.
            samples = np.nan_to_num(np.frombuffer(pending[:take], dtype=np.float32),
                                    nan=0.0, posinf=0.0, neginf=0.0)
            pending = pending[take:]
            # Only the newest hop matters for what is drawn: older audio that
            # piled up while the window was busy is history, not a backlog.
            history = np.concatenate([history, samples])[-FFT_SIZE:]
            magnitude = np.abs(np.fft.rfft(history * window)) * scale
            levels = np.array([magnitude[a:b].max() for a, b in spans])
            levels = 20 * np.log10(np.maximum(levels, 1e-10))
            now = time.monotonic()
            fallen = shown - RELEASE_DB_PER_S * (now - last)
            last = now
            shown = np.fmax(np.fmax(levels, fallen), FLOOR_DB)
            sys.stdout.write("S " + " ".join(f"{v:.1f}" for v in shown) + "\n")
            sys.stdout.flush()
    except BrokenPipeError:
        pass  # the window closed
    finally:
        if capture.poll() is None:
            capture.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
