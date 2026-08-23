"""The single place external commands are executed.

Everything that shells out goes through CommandRunner, which keeps subprocess
handling in one module and gives tests a seam to substitute a fake without
touching any domain or PipeWire code.
"""
import subprocess


class CommandRunner:
    def run(self, *args):
        """Fire and forget; output captured so it never leaks to the terminal."""
        return subprocess.run(args, capture_output=True)

    def capture(self, *args):
        """Run and return the CompletedProcess with decoded stdout."""
        return subprocess.run(args, capture_output=True, text=True)

    def succeeded(self, *args):
        return self.run(*args).returncode == 0

    def popen(self, args):
        """Long-lived child whose stdout is streamed by the caller."""
        return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
