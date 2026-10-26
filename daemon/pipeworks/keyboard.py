"""The keyboard's volume keys as a control surface.

For a machine without a MIDI board - a laptop, mostly - the volume up, down and
mute keys can drive one chosen strip instead. They are taken over in Hyprland
while that is selected: each key is unbound and rebound to a call to this
daemon's keyboard-volume action, with Alt for fine steps, as Omarchy does.

Hyprland's own config is never edited. The bindings are made at runtime, so
giving the keys back is a config reload, which re-runs whatever the user's
config says they do. A reload for any other reason drops runtime bindings
too, so this listens for Hyprland reloading and binds again afterwards.
"""
import os
import socket
import threading

# Key, the argument sent to keyboard-volume, and whether holding it repeats.
KEYS = (
    ("XF86AudioRaiseVolume", "up", True),
    ("XF86AudioLowerVolume", "down", True),
    ("ALT + XF86AudioRaiseVolume", "up-fine", True),
    ("ALT + XF86AudioLowerVolume", "down-fine", True),
    ("XF86AudioMute", "mute", False),
)

STEP = 5
FINE_STEP = 1


def _command(argument):
    return (
        "gdbus call --session --dest io.github.pipeworks.Pipeworks "
        "--object-path /io/github/pipeworks/Pipeworks "
        "--method org.gtk.Actions.Activate keyboard-volume "
        f"\"[<'{argument}'>]\" \"{{}}\""
    )


def bind_script():
    """The Lua that takes the keys over, as one hyprctl eval."""
    lines = []
    for key, argument, repeating in KEYS:
        # Long brackets: the command is full of quotes, and these need none.
        lines.append(f'hl.unbind("{key}")')
        lines.append(
            f'hl.bind("{key}", hl.dsp.exec_cmd([[{_command(argument)}]]), '
            f'{{ description = "Pipeworks volume", locked = true, '
            f'repeating = {"true" if repeating else "false"} }})'
        )
    return "\n".join(lines)


class KeyboardControl:
    def __init__(self, runner, dispatch):
        self._runner = runner
        self._dispatch = dispatch
        self.enabled = False
        self._listener = None

    def enable(self):
        self.enabled = True
        self._bind()
        self._listen()

    def disable(self):
        """Gives the keys back to whatever the user's config binds them to."""
        if not self.enabled:
            return
        self.enabled = False
        self._runner.run("hyprctl", "reload")

    def _bind(self):
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            self._runner.run("hyprctl", "eval", bind_script())

    def _listen(self):
        """Rebinds after Hyprland reloads its config, which drops them."""
        if self._listener is not None:
            return
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not signature or not runtime:
            return
        path = os.path.join(runtime, "hypr", signature, ".socket2.sock")
        self._listener = threading.Thread(target=self._read_events, args=(path,), daemon=True)
        self._listener.start()

    def _read_events(self, path):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as events:
                events.connect(path)
                for line in events.makefile("r", encoding="utf-8", errors="replace"):
                    if line.startswith("configreloaded"):
                        self._dispatch(self._rebind_if_enabled)
        except OSError:
            pass
        finally:
            self._listener = None

    def _rebind_if_enabled(self):
        if self.enabled:
            self._bind()
