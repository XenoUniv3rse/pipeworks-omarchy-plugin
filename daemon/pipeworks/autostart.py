"""Controlling whether the mixer starts with the session.

Three interchangeable strategies behind one interface:

* ShellManagedAutostart is used when a host process (the Omarchy shell plugin)
  already supervises the daemon. Nothing to enable, and installing a systemd
  unit here would create a second supervisor competing with the first.

* SystemdAutostart is preferred when the packaged user unit is installed. A
  service unit is the stronger guarantee - systemd restarts it if it ever dies,
  which matters because a dead process means a dead control surface.
* DesktopEntryAutostart is the fallback for running from a source checkout,
  where no unit has been installed.
"""
import os
import shutil
import sys

from . import settings

UNIT_NAME = "pipeworks.service"
UNIT_SEARCH_PATHS = (
    os.path.expanduser(f"~/.config/systemd/user/{UNIT_NAME}"),
    f"/usr/lib/systemd/user/{UNIT_NAME}",
    f"/usr/local/lib/systemd/user/{UNIT_NAME}",
    f"/etc/systemd/user/{UNIT_NAME}",
)


class ShellManagedAutostart:
    """No-op strategy for when an external supervisor owns the lifecycle."""

    can_toggle = False

    def is_enabled(self):
        return True

    def set_enabled(self, enabled):
        pass  # not ours to decide

    def describe(self):
        return (
            "Managed by the Omarchy shell plugin, which starts the mixer with "
            "your session and restarts it if it stops."
        )


class SystemdAutostart:
    """Enables/disables the packaged systemd user unit."""

    can_toggle = True

    def __init__(self, runner, unit=UNIT_NAME):
        self._runner = runner
        self._unit = unit

    def is_enabled(self):
        result = self._runner.capture("systemctl", "--user", "is-enabled", self._unit)
        return result.stdout.strip() == "enabled"

    def set_enabled(self, enabled):
        action = "enable" if enabled else "disable"
        self._runner.run("systemctl", "--user", action, self._unit)

    def describe(self):
        return (
            "Runs as a systemd user service, restarted automatically if it stops. "
            "The mixer keeps running in the background when this window is closed."
        )


class DesktopEntryAutostart:
    """Writes an XDG autostart entry; used when no systemd unit is installed."""

    can_toggle = True

    def __init__(self, launch_command, path=settings.AUTOSTART_PATH):
        self._path = path
        self._command = launch_command

    def is_enabled(self):
        return os.path.exists(self._path)

    def set_enabled(self, enabled):
        if not enabled:
            if os.path.exists(self._path):
                os.remove(self._path)
            return
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as handle:
            handle.write(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Pipeworks\n"
                f"Exec={self._command}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )

    def describe(self):
        return (
            "Starts via an XDG autostart entry. Install the systemd unit for "
            "automatic restarts if the process ever stops."
        )


def unit_is_installed():
    return any(os.path.exists(path) for path in UNIT_SEARCH_PATHS)


def daemon_command():
    """How to relaunch this installation in the background."""
    executable = shutil.which("pipeworks")
    if executable:
        return f"{executable} --daemon"
    package_dir = os.path.dirname(os.path.abspath(__file__))
    launcher = os.path.join(os.path.dirname(package_dir), "run.py")
    return f"{sys.executable} {launcher} --daemon"


def create(runner):
    """Picks the strongest strategy available on this installation."""
    if os.environ.get("PIPEWORKS_HOST") == "omarchy-shell":
        return ShellManagedAutostart()
    if unit_is_installed():
        return SystemdAutostart(runner)
    return DesktopEntryAutostart(daemon_command())
