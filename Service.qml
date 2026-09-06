import QtQuick
import Quickshell
import Quickshell.Io

// Supervises the Pipeworks daemon.
//
// The daemon is what actually does the work: it owns the virtual channels, the
// MIDI control surface, the routing and the link watchdog. It has to be running
// whenever the machine is, or the control surface is dead.
//
// omarchy-shell is itself a long-lived process that starts with the graphical
// session, so it makes a perfectly good supervisor and this plugin needs no
// systemd unit of its own. Liveness is decided by asking the session bus
// whether the daemon's name is owned, rather than by tracking a child process:
// the daemon is a single-instance GTK application, so a second launch delegates
// to the first and exits immediately. Watching process exits would read that
// perfectly normal hand-off as a crash and spawn forever.
Item {
  id: root
  visible: false
  width: 0
  height: 0

  // Injected by the shell.
  property var shell: null
  property var manifest: null

  readonly property string pluginDir: manifest && manifest.__sourceDir
    ? String(manifest.__sourceDir) : ""
  readonly property string launcher: pluginDir ? pluginDir + "/daemon/run.py" : ""

  readonly property string busName: "io.github.pipeworks.Pipeworks"
  readonly property string busPath: "/io/github/pipeworks/Pipeworks"

  property bool daemonRunning: false
  property bool dependenciesChecked: false
  property var missingDependencies: []
  readonly property bool dependenciesOk: dependenciesChecked && missingDependencies.length === 0
  property string lastError: ""

  readonly property string statusSummary: {
    if (!dependenciesChecked) return "Checking dependencies..."
    if (!dependenciesOk) return "Missing: " + missingDependencies.join(", ")
    if (daemonRunning) return "Running"
    return lastError !== "" ? lastError : "Starting..."
  }

  // ------------------------------------------------------------------

  Component.onCompleted: {
    checkDependencies()
    probe.running = true
  }

  Component.onDestruction: stopDaemon()

  // The daemon is only useful with its Python dependencies present, and a
  // missing one otherwise shows up as an unexplained failure to start.
  function checkDependencies() {
    dependencyCheck.running = true
  }

  Process {
    id: dependencyCheck
    command: ["python3", "-c",
      "import sys\n" +
      "missing = []\n" +
      "try:\n" +
      "    from gi.repository import Gio, GLib\n" +
      "except Exception:\n" +
      "    missing.append('python-gobject')\n" +
      "try:\n" +
      "    import rtmidi\n" +
      "except Exception:\n" +
      "    missing.append('python-rtmidi')\n" +
      "print(','.join(missing))\n"
    ]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        root.missingDependencies = raw === "" ? [] : raw.split(",")
        root.dependenciesChecked = true
        if (!root.dependenciesOk) {
          console.warn("pipeworks: missing dependencies: " + root.missingDependencies.join(", "))
        }
      }
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 && !root.dependenciesChecked) {
        root.missingDependencies = ["python3"]
        root.dependenciesChecked = true
      }
    }
  }

  // ------------------------------------------------------------------
  // Liveness

  Timer {
    id: probe
    interval: 5000
    repeat: true
    triggeredOnStart: true
    onTriggered: if (!ping.running) ping.running = true
  }

  Process {
    id: ping
    command: ["gdbus", "call", "--session",
      "--dest", root.busName, "--object-path", root.busPath,
      "--method", "org.freedesktop.DBus.Peer.Ping"]
    onExited: function(exitCode) {
      var alive = exitCode === 0
      root.daemonRunning = alive
      if (!alive && root.dependenciesOk) root.startDaemon()
    }
  }

  // ------------------------------------------------------------------
  // Lifecycle

  function startDaemon() {
    if (launcher === "" || daemon.running) return
    daemon.command = ["python3", root.launcher, "--daemon"]
    daemon.running = true
  }

  function stopDaemon() {
    if (daemon.running) daemon.running = false
  }

  function restartDaemon() {
    stopDaemon()
    Qt.callLater(root.startDaemon)
  }

  Process {
    id: daemon
    // PIPEWORKS_HOST tells the daemon the shell is supervising it, so its
    // "start on login" control reports that rather than offering to install a
    // systemd unit that would then compete with this one.
    environment: ({ "PIPEWORKS_HOST": "omarchy-shell" })
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var message = String(text || "").trim()
        if (message !== "") {
          root.lastError = message.split("\n").pop()
          console.warn("pipeworks daemon: " + message)
        }
      }
    }
    onExited: function(exitCode) {
      // Exit 0 is the normal single-instance hand-off: another copy already
      // owns the bus name. The probe decides whether anything is actually
      // running, so nothing to do here but surface real failures.
      if (exitCode !== 0) root.lastError = "Daemon exited with code " + exitCode
    }
  }

  // Called by the bar widget's "restart" affordance.
  IpcHandler {
    target: "pipeworks.mixer.service"
    function restart(): string { root.restartDaemon(); return "ok" }
    function status(): string { return root.statusSummary }
  }
}
