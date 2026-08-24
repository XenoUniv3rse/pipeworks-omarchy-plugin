import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar widget for the Pipeworks virtual audio mixer.
//
// State is read from Pipeworks' own config file, which the daemon rewrites
// whenever anything changes, so this widget follows the MIDI board and the
// mixer window without polling either.
//
// Changes are sent back as org.gtk.Actions calls on the daemon rather than by
// setting PipeWire volumes directly: the daemon owns the authoritative state
// and re-applies it whenever links drop, so an out-of-band change would be
// quietly reverted.
BarWidget {
  id: root
  moduleName: "pipeworks.mixer"

  // The bar sizes each slot from its widget's implicit size. Omitting these
  // leaves the slot zero-wide, which renders nothing and logs nothing.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property bool popupOpen: false

  readonly property string busName: "io.github.pipeworks.Pipeworks"
  readonly property string busPath: "/io/github/pipeworks/Pipeworks"
  readonly property string configPath: Quickshell.env("HOME") + "/.config/pipeworks/config.json"

  // The plugin's own service, which supervises the daemon. Consulted only to
  // explain an empty panel: without it the widget still works against a
  // daemon started any other way.
  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("pipeworks.mixer") : null

  property var config: ({})
  property bool loaded: false

  // Repeater models. Reassigning these rebuilds every delegate, so they are
  // only replaced when the set of strips actually changes - not on every
  // volume tick, which would otherwise tear the whole panel down and rebuild
  // it several times a second while a fader moves.
  property var inputs: []
  property var channels: []
  property var outputs: []
  property string structure: ""
  readonly property var volumes: config.volume || ({})
  readonly property var mutes: config.muted || ({})
  readonly property var outputVolumes: config.output_volume || ({})
  readonly property var outputMutes: config.output_muted || ({})
  readonly property var routes: config.routes || ({})

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color barForegroundColor: bar ? bar.barForeground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Anything silenced is worth surfacing on the bar itself: a muted channel is
  // the usual answer to "why can I not hear this".
  readonly property bool anyMuted: {
    var key
    for (key in mutes) if (mutes[key]) return true
    for (key in outputMutes) if (outputMutes[key]) return true
    return false
  }
  readonly property bool available: loaded && (channels.length > 0 || inputs.length > 0)

  // ---------------------------------------------------------------- state

  FileView {
    id: configFile
    path: root.configPath
    watchChanges: true
    printErrors: false
    onLoaded: root.parseConfig(text())
    // Only report unavailable if nothing has ever loaded; a failure after
    // that is transient and the last good state stays on screen.
    onLoadFailed: if (root.structure === "") root.loaded = false
    onFileChanged: reload()
  }

  function parseConfig(raw) {
    var next
    try {
      next = JSON.parse(raw)
    } catch (error) {
      // Keep showing the last good state; a bad read is transient and
      // blanking the panel for it is worse than being briefly stale.
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
        parts.push(String(entry.id) + "\u001f" + String(entry.label))
      }
      return parts.join(",")
    }
    return describe(candidate.inputs) + "|" + describe(candidate.channels)
      + "|" + describe(candidate.outputs)
  }

  // --------------------------------------------------------------- actions

  Process { id: action }


  function activate(name, parameter) {
    if (action.running) action.running = false
    action.command = [
      "gdbus", "call", "--session",
      "--dest", root.busName, "--object-path", root.busPath,
      "--method", "org.gtk.Actions.Activate",
      name, parameter, "{}"
    ]
    action.running = true
  }

  function setVolume(stripId, percent) {
    root.activate("set-volume", "[<('" + stripId + "', " + percent.toFixed(1) + ")>]")
  }

  function setOutputVolume(outId, percent) {
    root.activate("set-output-volume", "[<('" + outId + "', " + percent.toFixed(1) + ")>]")
  }

  function toggleMute(stripId) { root.activate("toggle-mute", "[<'" + stripId + "'>]") }
  function toggleOutputMute(outId) { root.activate("toggle-output-mute", "[<'" + outId + "'>]") }
  function toggleRoute(stripId, outId) {
    root.activate("toggle-route", "[<('" + stripId + "', '" + outId + "')>]")
  }
  readonly property bool opened: popupOpen
  function open() { root.popupOpen = true }
  function close() { root.popupOpen = false }

  function openWindow() {
    root.activate("show-window", "[]")
    root.popupOpen = false
  }

  // Slider drags are coalesced: without this a drag would spawn a gdbus
  // process per frame.
  property var pending: ({})

  Timer {
    id: flushTimer
    interval: 90
    repeat: true
    running: false
    onTriggered: {
      for (var key in root.pending) {
        var entry = root.pending[key]
        delete root.pending[key]
        if (entry.isOutput) root.setOutputVolume(entry.id, entry.value)
        else root.setVolume(entry.id, entry.value)
        return  // one call per tick keeps a single gdbus process in flight
      }
      running = false
    }
  }

  function queueVolume(stripId, percent, isOutput) {
    root.pending[stripId] = { "id": stripId, "value": percent, "isOutput": isOutput }
    flushTimer.running = true
  }

  // ------------------------------------------------------------- bar icon

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // md-tune (U+F062E): the mixer-faders glyph.
    text: "󰘮"
    active: root.available && root.anyMuted
    dimmed: !root.available
    tooltipText: root.available
      ? "Pipeworks mixer" + (root.anyMuted ? "  ·  something is muted" : "")
      : "Pipeworks is not running"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.MiddleButton) root.openWindow()
      else root.popupOpen = !root.popupOpen
    }
  }

  // --------------------------------------------------------------- popup

  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.popupOpen
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(340))
    contentHeight: popup.fittedContentHeight(column.implicitHeight, Style.space(620))

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.close()

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        ColumnLayout {
          id: column
          width: parent.width
          spacing: Style.space(6)

          Text {
            visible: !root.available
            Layout.fillWidth: true
            text: {
              if (!root.service) return "Pipeworks is not running."
              if (!root.service.dependenciesChecked) return "Checking dependencies..."
              if (!root.service.dependenciesOk)
                return "Missing packages:\n  " + root.service.missingDependencies.join("\n  ")
                  + "\n\nInstall them with:\n  sudo pacman -S "
                  + root.service.missingDependencies.join(" ")
              return "Starting the mixer...\n" + root.service.statusSummary
            }
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            wrapMode: Text.WordWrap
          }

          PanelSectionHeader {
            visible: root.available && root.inputs.length > 0
            Layout.fillWidth: true
            text: "Inputs"
            foreground: root.dim
            fontFamily: root.fontFamily
          }

          Repeater {
            model: root.available ? root.inputs : []
            delegate: StripRow { Layout.fillWidth: true }
          }

          PanelSectionHeader {
            visible: root.available && root.channels.length > 0
            Layout.fillWidth: true
            text: "Channels"
            foreground: root.dim
            fontFamily: root.fontFamily
          }

          Repeater {
            model: root.available ? root.channels : []
            delegate: StripRow {
              Layout.fillWidth: true
              showRoutes: true
            }
          }

          PanelSectionHeader {
            visible: root.available && root.outputs.length > 0
            Layout.fillWidth: true
            text: "Outputs"
            foreground: root.dim
            fontFamily: root.fontFamily
          }

          Repeater {
            model: root.available ? root.outputs : []
            delegate: StripRow {
              Layout.fillWidth: true
              isOutput: true
            }
          }

          PanelSeparator {
            visible: root.available
            Layout.fillWidth: true
          }

          Button {
            visible: root.available
            Layout.fillWidth: true
            text: "Open mixer"
            iconText: "󰘮"
            fontSize: Style.font.bodySmall
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: root.openWindow()
          }
        }
      }
    }
  }

  // One strip: name, level, mute, and (for channels) per-output routing.
  component StripRow: ColumnLayout {
    id: strip

    required property var modelData
    property bool isOutput: false
    property bool showRoutes: false

    readonly property string stripId: strip.modelData.id
    readonly property string stripLabel: strip.modelData.label || strip.stripId
    readonly property real level: {
      var store = strip.isOutput ? root.outputVolumes : root.volumes
      return store[strip.stripId] !== undefined ? store[strip.stripId] : 0
    }
    readonly property bool muted: strip.isOutput
      ? !!root.outputMutes[strip.stripId]
      : !!root.mutes[strip.stripId]
    readonly property var routeState: root.routes[strip.stripId] || ({})

    spacing: Style.space(2)

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(6)

      Text {
        text: strip.stripLabel
        color: strip.muted ? root.dim : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.subtitle
        elide: Text.ElideRight
        Layout.preferredWidth: Style.space(72)
      }

      PanelSlider {
        Layout.fillWidth: true
        bar: root.bar
        minimum: 0
        maximum: 100
        step: 2
        integer: true
        // While dragging the slider is the truth; otherwise follow the daemon,
        // so the MIDI board and the mixer window move it too.
        value: dragging ? liveValue : strip.level
        fillColor: strip.muted ? root.dim : root.foreground
        onMoved: function(value) { root.queueVolume(strip.stripId, value, strip.isOutput) }
        onReleased: function(value) { root.queueVolume(strip.stripId, value, strip.isOutput) }
      }

      Button {
        // md-volume_mute (U+F075F) / md-volume_high (U+F057E).
        iconText: strip.muted ? "󰝟" : "󰕾"
        iconSize: Style.font.body
        horizontalPadding: Style.space(5)
        foreground: strip.muted ? root.urgent : root.foreground
        fontFamily: root.fontFamily
        tooltipText: strip.muted ? "Unmute" : "Mute"
        onClicked: {
          if (strip.isOutput) root.toggleOutputMute(strip.stripId)
          else root.toggleMute(strip.stripId)
        }
      }
    }

    RowLayout {
      visible: strip.showRoutes && root.outputs.length > 0
      Layout.fillWidth: true
      Layout.leftMargin: Style.space(78)
      spacing: Style.space(4)

      Repeater {
        model: strip.showRoutes ? root.outputs : []
        delegate: Button {
          required property var modelData
          text: modelData.label || modelData.id
          fontSize: Style.font.caption
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(2)
          bordered: true
          active: !!strip.routeState[modelData.id]
          foreground: strip.routeState[modelData.id] ? root.foreground : root.dim
          fontFamily: root.fontFamily
          tooltipText: "Route " + strip.stripLabel + " to " + text
          onClicked: root.toggleRoute(strip.stripId, modelData.id)
        }
      }

      Item { Layout.fillWidth: true }
    }
  }
}
