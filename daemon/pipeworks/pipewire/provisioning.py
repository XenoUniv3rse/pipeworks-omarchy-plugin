"""Generation of the persistent PipeWire virtual-device configuration.

Each channel and input is a libpipewire-module-loopback: a virtual sink whose
outward side this application wires up itself. The declarations live in a
drop-in config file so they survive reboots, which means changing the set of
devices needs a PipeWire restart to take effect.
"""
import os
import time

from .. import settings


class LoopbackProvisioner:
    RESTART_SETTLE_SECONDS = 2

    def __init__(self, runner, conf_path=settings.PIPEWIRE_CONF_PATH):
        self._runner = runner
        self._conf_path = conf_path

    def write(self, channels, inputs):
        blocks = [self._block(chan["label"], chan["sink"]) for chan in channels]
        blocks += [
            self._block(inp["label"], inp["target_sink"], exposes_source=True)
            for inp in inputs
        ]
        content = "context.modules = [\n" + "\n".join(blocks) + "\n]\n"
        os.makedirs(os.path.dirname(self._conf_path), exist_ok=True)
        with open(self._conf_path, "w") as handle:
            handle.write(content)
        self._remove_legacy_configs()

    @staticmethod
    def _remove_legacy_configs():
        """Drops definitions left by a previous name.

        PipeWire loads every file in the drop-in directory, so leaving an old
        one in place would declare a second set of loopbacks with the same node
        names alongside the current ones.
        """
        for path in settings.LEGACY_PIPEWIRE_CONF_PATHS:
            if os.path.exists(path):
                os.remove(path)

    def restart(self):
        """Briefly interrupts all audio, so only called when devices change."""
        self._runner.run(
            "systemctl", "--user", "restart", "pipewire", "pipewire-pulse", "wireplumber"
        )
        # Let the new nodes register before anything tries to link to them.
        time.sleep(self.RESTART_SETTLE_SECONDS)

    @staticmethod
    def _block(description, sink_name, exposes_source=False):
        """One loopback module definition.

        For an input the outward side *is* the microphone applications select,
        so it is declared Audio/Source and must not be passive: a passive node
        is treated as internal plumbing, never gets registered by WirePlumber,
        and so never appears in device pickers. It also gets a distinct
        description, because it sits in those pickers right next to the real
        hardware mic and two similar names are impossible to tell apart.

        For a playback channel the outward side is ours to route, so it stays
        passive and non-autoconnecting to stop WirePlumber's default policy
        from claiming it.
        """
        if exposes_source:
            playback_props = f"""                node.name    = "{sink_name}_out"
                node.description = "{description} (Pipeworks)"
                media.class  = Audio/Source"""
        else:
            playback_props = f"""                node.name    = "{sink_name}_out"
                node.passive = true
                node.autoconnect = false"""

        return f"""    {{ name = libpipewire-module-loopback
        args = {{
            node.description = "{description}"
            capture.props = {{
                node.name    = "{sink_name}"
                media.class  = Audio/Sink
                audio.position = [ FL FR ]
            }}
            playback.props = {{
{playback_props}
                audio.position = [ FL FR ]
            }}
        }}
    }}"""
