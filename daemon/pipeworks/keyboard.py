"""The keyboard's volume keys: a control surface, or kept out of the way.

For a machine without a MIDI board - a laptop, mostly - the volume up, down and
mute keys can drive one chosen strip instead. While a board is in use they can
instead be switched off, so nothing but the board moves a level: not Omarchy's
own volume keys changing the default sink, nor the focused app reacting to
them.

Either way the keys are taken in Hyprland at runtime - each is unbound and
bound again, to this daemon's keyboard-volume action or to nothing - and
Hyprland's own config is never edited. Giving the keys back is a config
reload, which re-runs whatever the user's config binds them to. A reload for
any other reason drops runtime bindings too, so this listens for Hyprland
reloading and binds again afterwards.
"""
import json
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

# The modes, and the description Hyprland lists each binding under - which is
# also how a binding left by an earlier run of this daemon is recognised.
CONTROL = "control"
BLOCK = "block"
RELEASED = "released"
DESCRIPTIONS = {CONTROL: "Pipeworks volume", BLOCK: "Volume keys off (Pipeworks: MIDI board in use)"}


def _command(argument):
    return (
        "gdbus call --session --dest io.github.pipeworks.Pipeworks "
        "--object-path /io/github/pipeworks/Pipeworks "
        "--method org.gtk.Actions.Activate keyboard-volume "
        f"\"[<'{argument}'>]\" \"{{}}\""
    )


def bind_script(mode=CONTROL):
    """The Lua that takes the keys, as one hyprctl eval."""
    lines = []
    for key, argument, repeating in KEYS:
        if mode == CONTROL:
            # Long brackets: the command is full of quotes, and these need none.
            action = f"hl.dsp.exec_cmd([[{_command(argument)}]])"
        else:
            action = "function() end"
        lines.append(f'hl.unbind("{key}")')
        lines.append(
            f'hl.bind("{key}", {action}, '
            f'{{ description = "{DESCRIPTIONS[mode]}", locked = true, '
            f'repeating = {"true" if repeating and mode == CONTROL else "false"} }})'
        )
    return "\n".join(lines)


class KeyboardControl:
    def __init__(self, runner, dispatch):
        self._runner = runner
        self._dispatch = dispatch
        self.mode = RELEASED
        self._listener = None

    @property
    def enabled(self):
        """Whether the keys drive the mixer (rather than being off or free)."""
        return self.mode == CONTROL

    def enable(self):
        """The keys drive the chosen strip."""
        self._take(CONTROL)

    def block(self):
        """The keys do nothing at all."""
        self._take(BLOCK)

    def disable(self):
        """Gives the keys back to whatever the user's config binds them to.

        Only reloads when there is something of ours to undo - here, or left
        by an earlier run - since a reload re-runs the whole Hyprland config.
        """
        was_ours = self.mode != RELEASED or self._ours_bound()
        self.mode = RELEASED
        if was_ours:
            self._runner.run("hyprctl", "reload")

    def _take(self, mode):
        self.mode = mode
        self._bind()
        self._listen()

    def _ours_bound(self):
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return False
        try:
            listed = json.loads(self._runner.capture("hyprctl", "binds", "-j").stdout or "[]")
        except (ValueError, AttributeError):
            return False
        ours = set(DESCRIPTIONS.values())
        return any(entry.get("description") in ours for entry in listed)

    def _bind(self):
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and self.mode != RELEASED:
            self._runner.run("hyprctl", "eval", bind_script(self.mode))

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
                        self._dispatch(self._rebind)
        except OSError:
            pass
        finally:
            self._listener = None

    def _rebind(self):
        if self.mode != RELEASED:
            self._bind()
