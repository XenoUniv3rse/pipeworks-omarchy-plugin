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

  // Third-party manifests have __sourceDir stripped before reaching plugin
  // code (shell.publicPluginManifest), so the source directory has to be
  // derived from the one thing that survives - the plugin id - against the
  // fixed, documented location every third-party plugin is installed under.
  // __sourceDir is still preferred when present, in case a future shell
  // version restores it or this ever runs as a first-party plugin.
  readonly property string pluginDir: {
    if (manifest && manifest.__sourceDir) return String(manifest.__sourceDir)
    var id = manifest && manifest.id ? String(manifest.id) : ""
    return id ? Quickshell.env("HOME") + "/.config/omarchy/plugins/" + id : ""
  }
  readonly property string launcher: pluginDir ? pluginDir + "/daemon/run.py" : ""

  // Python writes bytecode beside the source it imports, and this plugin's
  // daemon is a package tree living under ~/.config/omarchy/plugins, which
  // omarchy-shell watches recursively to hot-reload plugin code. A cold cache
  // therefore makes our own import look like somebody editing the plugin, and
  // the shell tears down and rebuilds every panel - wallpaper included - on top
  // of a daemon that was only starting up. The cache is worth keeping, so
  // relocate it rather than switching it off.
  readonly property string pycachePrefix: {
    var cache = Quickshell.env("XDG_CACHE_HOME")
    if (!cache) cache = Quickshell.env("HOME") + "/.cache"
    return cache + "/pipeworks/pycache"
  }

  readonly property string busName: "io.github.pipeworks.Pipeworks"
  readonly property string busPath: "/io/github/pipeworks/Pipeworks"

  property bool daemonRunning: false
  property bool dependenciesChecked: false
  property var missingDependencies: []
  readonly property bool dependenciesOk: dependenciesChecked && missingDependencies.length === 0
  // Why each one counted as missing, and which interpreter was asked - so a
  // package that is installed but still reported missing can be explained.
  property var dependencyErrors: ({})
  property string dependencyPython: ""
  readonly property bool checkingDependencies: dependencyCheck.running
  property string lastError: ""

  // The interpreter for the daemon, its dependency check and the spectrum
  // helper. The system one, by path: pacman installs python-gobject and
  // python-rtmidi for /usr/bin/python3, and a "python3" first on PATH - from
  // mise, pyenv, a venv or conda - would not see them however often they
  // were installed.
  readonly property string python: "/usr/bin/python3"

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
  //
  // Run again on request and every few seconds while something is missing:
  // it used to run once, at shell start, so installing the packages changed
  // nothing until the shell was restarted.
  function checkDependencies() {
    if (!dependencyCheck.running) dependencyCheck.running = true
  }

  Timer {
    interval: 10000
    repeat: true
    running: root.dependenciesChecked && !root.dependenciesOk
    onTriggered: root.checkDependencies()
  }

  Process {
    id: dependencyCheck
    command: [root.python, "-c",
      "import json, sys\n" +
      "missing, errors = [], {}\n" +
      "def need(package, attempt):\n" +
      "    try:\n" +
      "        attempt()\n" +
      "    except Exception as error:\n" +
      "        missing.append(package)\n" +
      "        errors[package] = f'{type(error).__name__}: {error}'\n" +
      "def gi_check():\n" +
      "    from gi.repository import Gio, GLib\n" +
      "def rtmidi_check():\n" +
      "    import rtmidi\n" +
      "need('python-gobject', gi_check)\n" +
      "need('python-rtmidi', rtmidi_check)\n" +
      "print(json.dumps({'missing': missing, 'errors': errors,\n" +
      "                  'python': sys.executable + ' ' + sys.version.split()[0]}))\n"
    ]
    stdout: StdioCollector {
      id: dependencyOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var result = null
      try { result = JSON.parse(String(dependencyOutput.text || "").trim()) } catch (error) {}
      if (exitCode !== 0 || !result) {
        // The interpreter itself would not run.
        root.missingDependencies = ["python3"]
        root.dependencyErrors = ({ python3: root.python + " could not be run (exit " + exitCode + ")" })
        root.dependencyPython = root.python
      } else {
        root.missingDependencies = result.missing || []
        root.dependencyErrors = result.errors || ({})
        root.dependencyPython = String(result.python || "")
      }
      root.dependenciesChecked = true
      if (!root.dependenciesOk) {
        console.warn("pipeworks: missing dependencies: " + root.missingDependencies.join(", ")
          + " (" + root.dependencyPython + ")")
      } else if (!root.daemonRunning) {
        // Do not wait for the next liveness tick to start it.
        probe.restart()
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
    daemon.command = [root.python, "-X", "pycache_prefix=" + root.pycachePrefix, root.launcher, "--daemon"]
    daemon.running = true
  }

  function stopDaemon() {
    if (daemon.running) daemon.running = false
  }

  function restartDaemon() {
    if (daemon.running) {
      stopDaemon()
      Qt.callLater(root.startDaemon)
      return
    }
    // Not our child: a plugin reload replaced the instance that started it.
    // Ask it to quit over the bus; the liveness probe starts a fresh one.
    quitter.running = true
  }

  Process {
    id: quitter
    command: ["gdbus", "call", "--session",
      "--dest", root.busName, "--object-path", root.busPath,
      "--method", "org.gtk.Actions.Activate", "quit", "[]", "{}"]
    onExited: probe.restart()
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
    function recheck(): string { root.checkDependencies(); return "checking" }
  }
}
