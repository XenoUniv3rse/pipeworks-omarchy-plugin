"""Creating, removing and reading back graph links."""


class GraphLinker:
    def __init__(self, runner):
        self._runner = runner

    def connect(self, source_port, dest_port):
        self._runner.run("pw-link", source_port, dest_port)

    def disconnect(self, source_port, dest_port):
        self._runner.run("pw-link", "-d", source_port, dest_port)

    def present_links(self):
        """Every (source_port, dest_port) currently linked.

        Returns an empty set if the graph cannot be read, which callers treat as
        "cannot tell" rather than "nothing is connected" - reporting everything
        as missing would make the watchdog tear the routing up and rebuild it.
        """
        result = self._runner.capture("pw-link", "-l")
        if result.returncode != 0:
            return set()

        # `pw-link -l` prints each port unindented, then its links on indented
        # "  |-> dest" / "  |<- source" lines.
        links = set()
        current_port = None
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            if not line.startswith((" ", "\t")):
                current_port = line.strip()
            elif current_port:
                stripped = line.strip()
                if stripped.startswith("|->"):
                    links.add((current_port, stripped[3:].strip()))
        return links
