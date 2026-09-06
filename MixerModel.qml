import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import qs.Commons

// Everything the Pipeworks front ends need to know and do, with no appearance
// of its own.
//
// State arrives as two files the daemon writes and this watches: config.json,
// which is the authoritative mixer state, and state.json, which carries what an
// action cannot return - running applications, available devices, MIDI Learn
// progress. Changes go the other way as org.gtk.Actions calls, never by editing
// either file: the daemon re-applies its own state whenever PipeWire drops a
// link, so an out-of-band edit would be silently reverted.
QtObject {
  id: root

  readonly property string busName: "io.github.pipeworks.Pipeworks"
  readonly property string busPath: "/io/github/pipeworks/Pipeworks"
  readonly property string configPath: Quickshell.env("HOME") + "/.config/pipeworks/config.json"
  readonly property string statePath: Quickshell.env("HOME") + "/.config/pipeworks/state.json"

  // Set true by a window that is on screen. The daemon only polls for streams
  // and devices while something is watching, so leaving this false costs it
  // nothing.
  property bool watching: false

  property var config: ({})
  property var state: ({})
  property bool loaded: false

  // Repeater models. Reassigning these rebuilds every delegate, so they are
  // only replaced when the set of strips actually changes - not on every volume
  // tick, which would tear the whole window down several times a second while a
  // fader moves.
  property var inputs: []
  property var channels: []
  property var outputs: []
  property string structure: ""

  readonly property var volumes: config.volume || ({})
  readonly property var mutes: config.muted || ({})
  readonly property var solos: config.solo || ({})
  readonly property var routes: config.routes || ({})
  readonly property var outputVolumes: config.output_volume || ({})
  readonly property var outputMutes: config.output_muted || ({})
  readonly property var outputSolos: config.output_solo || ({})
  readonly property var midiBindings: config.midi || ({})
  readonly property bool volumeLocked: config.volume_locked === true

  readonly property var streams: state.streams instanceof Array ? state.streams : []
  readonly property var outputDevices: state.devices && state.devices.outputs instanceof Array
    ? state.devices.outputs : []
  readonly property var inputDevices: state.devices && state.devices.inputs instanceof Array
    ? state.devices.inputs : []
  readonly property var autostart: state.autostart || ({})
  readonly property var learn: state.learn || ({})
  readonly property bool midiConnected: state.midiConnected === true
  readonly property string status: String(state.status || "")
  readonly property int statusSerial: Number(state.statusSerial || 0)

  readonly property bool available: loaded && (channels.length > 0 || inputs.length > 0)

  // ---------------------------------------------------------------- colour

  // Channels are told apart by colour, in the window and on their application
  // chips. Hues are fixed so a channel keeps its colour across themes; only
  // saturation and lightness follow the theme, because a colour tuned for a
  // dark background is unreadable on a light one.
  readonly property var accentHues: [0.45, 0.57, 0.90, 0.74, 0.09, 0.01, 0.30, 0.51]

  readonly property bool darkTheme: {
    var b = Color.background
    return (0.299 * b.r + 0.587 * b.g + 0.114 * b.b) < 0.5
  }

  function accentFor(index) {
    var count = root.accentHues.length
    var hue = root.accentHues[((index % count) + count) % count]
    return root.darkTheme ? Qt.hsla(hue, 0.58, 0.64, 1) : Qt.hsla(hue, 0.52, 0.40, 1)
  }

  function channelIndex(stripId) {
    for (var i = 0; i < root.channels.length; i++)
      if (root.channels[i] && root.channels[i].id === stripId) return i
    return -1
  }

  // ---------------------------------------------------------------- audio

  readonly property var pwNodes: Pipewire.nodes ? Pipewire.nodes.values : []

  function nodeNamed(name) {
    if (!name) return null
    for (var i = 0; i < root.pwNodes.length; i++)
      if (root.pwNodes[i] && root.pwNodes[i].name === name) return root.pwNodes[i]
    return null
  }

  // Maps a linear peak to a 0-1 meter position on a dB scale. A linear scale is
  // useless here: everyday audio never approaches full scale, so normal content
  // would barely lift the meter off the floor.
  function peakToLevel(peak) {
    if (!peak || peak <= 0) return 0
    var db = 20 * Math.log(peak) / Math.LN10
    return Math.max(0, Math.min(1, (db + 50) / 50))
  }

  // Strips looked up live from config rather than from the cached models.
  //
  // The models are only reassigned when the *structure* changes - which strips
  // exist and what they are called - so anything holding a strip object from
  // them goes stale the moment a value inside it changes. A dialog open on a
  // strip needs the current contents, so it looks the strip up by id instead.
  function entityFor(kind, stripId) {
    var key = kind === "channel" ? "channels" : (kind === "input" ? "inputs" : "outputs")
    var list = root.config[key] instanceof Array ? root.config[key] : []
    for (var i = 0; i < list.length; i++)
      if (String(list[i].id) === String(stripId)) return list[i]
    return null
  }

  // The microphones feeding one input.
  function sourcesFor(inputId) {
    var entity = root.entityFor("input", inputId)
    return entity && entity.sources instanceof Array ? entity.sources : []
  }

  // Just the device names, for use as a Repeater model. Levels deliberately
  // excluded: they change on every drag, and a model that changed with them
  // would rebuild the sliders out from under the finger moving one.
  function sourceNamesFor(inputId) {
    var names = []
    var sources = root.sourcesFor(inputId)
    for (var i = 0; i < sources.length; i++) names.push(String(sources[i].name))
    return names
  }

  function sourceVolume(inputId, name) {
    var sources = root.sourcesFor(inputId)
    for (var i = 0; i < sources.length; i++)
      if (String(sources[i].name) === String(name))
        return sources[i].volume === undefined ? 100 : Number(sources[i].volume)
    return 100
  }

  // A capture device's human name. Falls back to the node name, which is what
  // a microphone unplugged since it was added leaves behind.
  function deviceDescription(name) {
    for (var i = 0; i < root.inputDevices.length; i++)
      if (String(root.inputDevices[i].name) === String(name))
        return String(root.inputDevices[i].description)
    return String(name)
  }

  // Capture devices not already feeding this input, for the add picker.
  function unusedInputDevices(inputId) {
    var used = ({})
    var sources = root.sourcesFor(inputId)
    for (var i = 0; i < sources.length; i++) used[String(sources[i].name)] = true
    var out = []
    for (var d = 0; d < root.inputDevices.length; d++) {
      var device = root.inputDevices[d]
      if (!used[String(device.name)])
        out.push({ value: String(device.name), label: String(device.description) })
    }
    return out
  }

  // Streams currently playing into one channel's sink.
  function streamsFor(sinkName) {
    var out = []
    for (var i = 0; i < root.streams.length; i++)
      if (root.streams[i] && root.streams[i].sink === sinkName) out.push(root.streams[i])
    return out
  }

  // ---------------------------------------------------------------- files

  property var _configFile: FileView {
    path: root.configPath
    watchChanges: true
    printErrors: false
    onLoaded: root.parseConfig(text())
    // Only report unavailable if nothing has ever loaded; a failure after that
    // is transient and the last good state stays on screen.
    onLoadFailed: if (root.structure === "") root.loaded = false
    onFileChanged: reload()
  }

  property var _stateFile: FileView {
    path: root.statePath
    watchChanges: true
    printErrors: false
    onLoaded: {
      try {
        root.state = JSON.parse(text())
      } catch (error) {
        // A torn or half-written read; the previous snapshot stays.
      }
    }
    onFileChanged: reload()
  }

  function parseConfig(raw) {
    var next
    try {
      next = JSON.parse(raw)
    } catch (error) {
      // Keep showing the last good state; a bad read is transient and blanking
      // the window for it is worse than being briefly stale.
      return
    }

    root.config = next
    root.loaded = true

    var signature = root.structureSignature(next)
    if (signature !== root.structure) {
      root.structure = signature
      root.inputs = next.inputs instanceof Array ? next.inputs : []
      root.channels = next.channels instanceof Array ? next.channels : []
      root.outputs = next.outputs instanceof Array ? next.outputs : []
    }
  }

  // Identifies which strips exist and what they are called. Values are
  // deliberately excluded: they update through `config` without touching the
  // models.
  function structureSignature(candidate) {
    function describe(list) {
      if (!(list instanceof Array)) return ""
      var parts = []
      for (var i = 0; i < list.length; i++) {
        var entry = list[i] || ({})
        // JSON rather than a joined string: a label is user text and may
        // well contain whatever separator character seemed safe.
        parts.push(JSON.stringify([String(entry.id), String(entry.label)]))
      }
      return parts.join(",")
    }
    return describe(candidate.inputs) + "|" + describe(candidate.channels)
      + "|" + describe(candidate.outputs)
  }

  // -------------------------------------------------------------- actions

  // Calls run one at a time, in order, through a single process.
  //
  // An earlier version killed whatever was in flight to start the next call.
  // That silently threw commands away: removing a strip sent remove-strip and
  // then, one line later, the dialog's own midi-learn-cancel, which shot the
  // removal dead before gdbus had finished. Anything issued in quick
  // succession was at risk, not just that pair.
  property var _queue: []

  property var _action: Process {
    onRunningChanged: if (!running) root._drain()
  }

  function activate(name, parameter) {
    root._queue.push([
      "gdbus", "call", "--session",
      "--dest", root.busName, "--object-path", root.busPath,
      "--method", "org.gtk.Actions.Activate",
      name, parameter, "{}"
    ])
    root._drain()
  }

  function _drain() {
    if (root._action.running || root._queue.length === 0) return
    root._action.command = root._queue.shift()
    root._action.running = true
  }

  function quoted(value) {
    // Labels and device names are user text heading into a GVariant literal, so
    // a stray quote or backslash would otherwise produce a malformed call.
    return "'" + String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'"
  }

  function toggleMute(id) { root.activate("toggle-mute", "[<" + root.quoted(id) + ">]") }
  function toggleSolo(id) { root.activate("toggle-solo", "[<" + root.quoted(id) + ">]") }
  function toggleOutputMute(id) { root.activate("toggle-output-mute", "[<" + root.quoted(id) + ">]") }
  function toggleOutputSolo(id) { root.activate("toggle-output-solo", "[<" + root.quoted(id) + ">]") }

  function toggleRoute(stripId, outId) {
    root.activate("toggle-route",
      "[<(" + root.quoted(stripId) + ", " + root.quoted(outId) + ")>]")
  }

  function setVolume(id, percent) {
    root.activate("set-volume", "[<(" + root.quoted(id) + ", " + percent.toFixed(1) + ")>]")
  }

  function setOutputVolume(id, percent) {
    root.activate("set-output-volume", "[<(" + root.quoted(id) + ", " + percent.toFixed(1) + ")>]")
  }

  function setVolumeLocked(locked) {
    root.activate("set-volume-lock", "[<" + (locked ? "true" : "false") + ">]")
  }

  function moveStream(index, sinkName) {
    root.activate("move-stream", "[<(" + Math.round(index) + ", " + root.quoted(sinkName) + ")>]")
  }

  function addChannel(label) { root.activate("add-channel", "[<" + root.quoted(label) + ">]") }

  function addInput(label, source) {
    root.activate("add-input", "[<(" + root.quoted(label) + ", " + root.quoted(source) + ")>]")
  }

  function addOutput(label, sink) {
    root.activate("add-output", "[<(" + root.quoted(label) + ", " + root.quoted(sink) + ")>]")
  }

  function removeStrip(kind, id) {
    root.activate("remove-strip", "[<(" + root.quoted(kind) + ", " + root.quoted(id) + ")>]")
  }

  function renameStrip(kind, id, label) {
    root.activate("rename-strip", "[<(" + root.quoted(kind) + ", " + root.quoted(id)
      + ", " + root.quoted(label) + ")>]")
  }

  function retargetInput(id, source) {
    root.activate("retarget-input", "[<(" + root.quoted(id) + ", " + root.quoted(source) + ")>]")
  }

  function retargetOutput(id, sink) {
    root.activate("retarget-output", "[<(" + root.quoted(id) + ", " + root.quoted(sink) + ")>]")
  }

  function addInputSource(inputId, source) {
    root.activate("add-input-source",
      "[<(" + root.quoted(inputId) + ", " + root.quoted(source) + ")>]")
  }

  function removeInputSource(inputId, source) {
    root.activate("remove-input-source",
      "[<(" + root.quoted(inputId) + ", " + root.quoted(source) + ")>]")
  }

  function setInputSourceVolume(inputId, source, percent) {
    root.activate("set-input-source-volume",
      "[<(" + root.quoted(inputId) + ", " + root.quoted(source) + ", "
      + percent.toFixed(1) + ")>]")
  }

  function midiLearn(kind, key) {
    root.activate("midi-learn", "[<(" + root.quoted(kind) + ", " + root.quoted(key) + ")>]")
  }

  function midiLearnCancel() { root.activate("midi-learn-cancel", "[]") }

  function setAutostart(enabled) {
    root.activate("set-autostart", "[<" + (enabled ? "true" : "false") + ">]")
  }

  // ------------------------------------------------------- state watching

  // Renewed rather than set once: the daemon drops the watch if nobody renews,
  // so a window that was killed cannot leave it polling forever.
  property var _watchTimer: Timer {
    interval: 5000
    repeat: true
    running: root.watching
    triggeredOnStart: true
    onTriggered: root.activate("set-state-watch", "[<true>]")
  }

  onWatchingChanged: if (!watching) root.activate("set-state-watch", "[<false>]")

  // Volume drags are coalesced: without this a drag would spawn a gdbus process
  // per frame.
  property var pending: ({})

  property var _flushTimer: Timer {
    interval: 90
    repeat: true
    running: false
    onTriggered: {
      // Wait rather than enqueue while a call is still going. `pending` holds
      // only the newest value per knob, so a skipped tick loses nothing - and
      // a drag over a slow structural call would otherwise queue up a long
      // trail of stale levels to replay afterwards.
      if (root._action.running) return
      for (var key in root.pending) {
        var entry = root.pending[key]
        delete root.pending[key]
        if (entry.kind === "source")
          root.setInputSourceVolume(entry.id, entry.source, entry.value)
        else if (entry.kind === "output") root.setOutputVolume(entry.id, entry.value)
        else root.setVolume(entry.id, entry.value)
        return
      }
      running = false
    }
  }

  function queueVolume(stripId, percent, isOutput) {
    // Keyed by kind as well as id: a strip and a physical output can share an
    // id, and a microphone level is a third thing again.
    var kind = isOutput ? "output" : "strip"
    root.pending[kind + ":" + stripId] = { kind: kind, id: stripId, value: percent }
    root._flushTimer.running = true
  }

  function queueSourceVolume(inputId, source, percent) {
    root.pending["source:" + inputId + "/" + source] = {
      kind: "source", id: inputId, source: source, value: percent
    }
    root._flushTimer.running = true
  }
}
