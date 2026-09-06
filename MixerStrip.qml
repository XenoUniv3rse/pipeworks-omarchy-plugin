import QtQuick
import QtQuick.Layouts
import Quickshell.Services.Pipewire
import qs.Commons
import qs.Ui

// One channel, input or output as a card: name, meter and fader, level, mute
// and solo, and - for a channel - where it goes and what is playing into it.
Rectangle {
  id: root

  required property var model
  required property var entity
  // "channel", "input" or "output". A channel is the only kind that routes and
  // the only kind applications play into.
  required property string kind
  property color accent: Color.accent
  property Item dragLayer: null

  signal settingsRequested()

  readonly property bool isOutput: kind === "output"
  readonly property bool isChannel: kind === "channel"
  readonly property string stripId: String(entity.id)
  readonly property string stripLabel: String(entity.label || entity.id)
  readonly property string sinkName: String(entity.sink || "")

  readonly property real level: {
    var store = root.isOutput ? root.model.outputVolumes : root.model.volumes
    return store[root.stripId] !== undefined ? store[root.stripId] : 0
  }
  readonly property bool muted: root.isOutput
    ? !!root.model.outputMutes[root.stripId] : !!root.model.mutes[root.stripId]
  readonly property bool soloed: root.isOutput
    ? !!root.model.outputSolos[root.stripId] : !!root.model.solos[root.stripId]
  readonly property var routeState: root.model.routes[root.stripId] || ({})
  readonly property var apps: root.isChannel ? root.model.streamsFor(root.sinkName) : []

  // Where this strip's audible signal lives. For a channel or input that is the
  // loopback's output side, which carries the post-volume signal; for a
  // physical output it is the device itself.
  readonly property string meterNodeName: {
    if (root.isOutput) {
      var port = String(root.entity.port_l || "")
      return port.indexOf(":") > 0 ? port.split(":")[0] : ""
    }
    var sink = root.entity.target_sink || root.entity.sink
    return sink ? String(sink) + "_out" : ""
  }
  readonly property var meterNode: root.model.nodeNamed(root.meterNodeName)

  // What the meter should show: what you can actually hear.
  //
  // A channel or input is metered on its loopback output, which is already past
  // the strip's fader. A physical output is metered on the device node, which is
  // *before* the device volume - so an output turned down to zero would
  // otherwise show a full signal it is not playing. Attenuate by the same cubic
  // curve PipeWire uses for volume.
  readonly property real meterPeak: {
    if (root.muted) return 0
    var raw = peakMonitor.peak || 0
    if (!root.isOutput) return raw
    var fraction = Math.max(0, Math.min(100, root.level)) / 100
    return raw * fraction * fraction * fraction
  }

  radius: Math.round(Style.space(10))
  color: Util.alpha(Color.foreground, 0.04)
  border.width: 1
  border.color: Util.alpha(Color.foreground, dropArea.containsDrag ? 0.0 : 0.09)

  // A channel lights up in its own colour while a chip hovers over it, so it is
  // obvious which one a drop will land in.
  Rectangle {
    anchors.fill: parent
    radius: parent.radius
    visible: dropArea.containsDrag
    color: Util.alpha(root.accent, 0.10)
    border.width: 2
    border.color: Util.alpha(root.accent, 0.85)
  }

  // Node properties are only valid while the node is bound.
  PwObjectTracker { objects: root.meterNode ? [root.meterNode] : [] }

  PwNodePeakMonitor {
    id: peakMonitor
    node: root.meterNode
    // Metering costs real work, so only while the window is actually on screen.
    enabled: root.model.watching && root.meterNode !== null
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.space(10)
    spacing: Style.space(8)

    // ---------------------------------------------------------- heading

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(4)

      // The accent only appears on channels: inputs and outputs are not
      // colour-coded, because nothing is ever dragged into them.
      Rectangle {
        visible: root.isChannel
        Layout.preferredWidth: Math.max(3, Style.space(3))
        Layout.preferredHeight: heading.implicitHeight
        radius: width / 2
        color: root.accent
      }

      Text {
        id: heading
        Layout.fillWidth: true
        text: root.stripLabel
        color: root.muted ? Util.alpha(Color.foreground, 0.45) : Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }

      Button {
        // md-cog (U+F0493)
        iconText: "\u{f0493}"
        iconSize: Style.font.bodySmall
        horizontalPadding: Style.space(4)
        verticalPadding: Style.space(2)
        foreground: Util.alpha(Color.foreground, 0.55)
        fontFamily: Style.font.family
        tooltipText: "Settings for " + root.stripLabel
        onClicked: root.settingsRequested()
      }
    }

    // ------------------------------------------------------ meter + fader

    RowLayout {
      Layout.alignment: Qt.AlignHCenter
      // A fixed height rather than fillHeight. The window is often tiled to the
      // full height of a monitor, and a fader stretched over eight hundred
      // pixels is no more usable than this - just stranger to look at. The
      // spare height goes to the apps block below, where it buys something.
      //
      // fillHeight has to be turned off explicitly: a layout nested in another
      // layout defaults it to true, unlike an ordinary item, so preferredHeight
      // alone is quietly ignored.
      Layout.fillHeight: false
      Layout.preferredHeight: Style.space(210)
      spacing: Style.space(8)

      LevelMeter {
        Layout.preferredWidth: Math.max(4, Style.space(6))
        Layout.fillHeight: true
        level: root.model.peakToLevel(root.meterPeak)
      }

      Fader {
        id: fader
        Layout.fillHeight: true
        accent: root.accent
        interactive: !root.model.volumeLocked
        opacity: root.model.volumeLocked ? 0.5 : 1.0
        minimum: 0
        maximum: 100
        step: 2
        value: root.level
        onMoved: function (value) { root.model.queueVolume(root.stripId, value, root.isOutput) }
        onReleased: function (value) { root.model.queueVolume(root.stripId, value, root.isOutput) }
      }
    }

    Text {
      Layout.alignment: Qt.AlignHCenter
      // The live value while dragging, so the number tracks the knob rather
      // than lagging a bus round trip behind it.
      text: Math.round(fader.dragging ? fader.liveValue : root.level) + "%"
      color: Util.alpha(Color.foreground, 0.65)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    // ------------------------------------------------------------ switches

    RowLayout {
      Layout.fillWidth: true
      Layout.fillHeight: false
      spacing: Style.space(4)

      Button {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        text: "Mute"
        fontSize: Style.font.caption
        horizontalPadding: Style.space(4)
        verticalPadding: Style.space(3)
        bordered: true
        active: root.muted
        foreground: root.muted ? Color.urgent : Util.alpha(Color.foreground, 0.6)
        fontFamily: Style.font.family
        onClicked: {
          if (root.isOutput) root.model.toggleOutputMute(root.stripId)
          else root.model.toggleMute(root.stripId)
        }
      }

      Button {
        // Inputs have no solo: soloing silences everything else on the way to
        // an output, which an input is not on.
        visible: !(root.kind === "input")
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        text: "Solo"
        fontSize: Style.font.caption
        horizontalPadding: Style.space(4)
        verticalPadding: Style.space(3)
        bordered: true
        active: root.soloed
        foreground: root.soloed ? Color.accent : Util.alpha(Color.foreground, 0.6)
        fontFamily: Style.font.family
        onClicked: {
          if (root.isOutput) root.model.toggleOutputSolo(root.stripId)
          else root.model.toggleSolo(root.stripId)
        }
      }
    }

    // ------------------------------------------------------------- routing

    ColumnLayout {
      visible: root.isChannel && root.model.outputs.length > 0
      Layout.fillWidth: true
      Layout.fillHeight: false
      spacing: Style.space(3)

      Repeater {
        model: root.isChannel ? root.model.outputs : []

        delegate: Button {
          required property var modelData
          readonly property bool on: !!root.routeState[modelData.id]

          Layout.fillWidth: true
          Layout.minimumWidth: 0
          clip: true
          text: String(modelData.label || modelData.id)
          fontSize: Style.font.caption
          horizontalPadding: Style.space(4)
          verticalPadding: Style.space(2)
          bordered: true
          active: on
          foreground: on ? Color.foreground : Util.alpha(Color.foreground, 0.45)
          fontFamily: Style.font.family
          tooltipText: (on ? "Stop sending " : "Send ") + root.stripLabel
            + (on ? " to " : " to ") + text
          onClicked: root.model.toggleRoute(root.stripId, modelData.id)
        }
      }
    }

    Item {
      // Inputs and outputs carry no apps block, so this takes the slack in a
      // window taller than the card needs.
      visible: !root.isChannel
      Layout.fillHeight: true
    }

    // ---------------------------------------------------------------- apps

    ColumnLayout {
      visible: root.isChannel
      Layout.fillWidth: true
      Layout.fillHeight: true
      spacing: Style.space(3)

      Text {
        text: "Apps"
        color: Util.alpha(Color.foreground, 0.4)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: Math.max(Style.space(64), chips.implicitHeight + Style.space(10))
        radius: Math.round(Style.space(6))
        color: Util.alpha(Color.foreground, 0.05)
        border.width: 1
        border.color: Util.alpha(Color.foreground, 0.08)

        Column {
          id: chips
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(5)
          spacing: Style.space(4)

          Repeater {
            model: root.apps

            delegate: AppChip {
              required property var modelData
              stream: modelData
              accent: root.accent
              dragLayer: root.dragLayer
            }
          }
        }

        Text {
          anchors.centerIn: parent
          visible: root.apps.length === 0
          text: "drop here"
          color: Util.alpha(Color.foreground, 0.25)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  // Covers the whole card, not just the apps block: aiming at a small box while
  // dragging is fussy, and a channel is an unambiguous drop target anywhere.
  DropArea {
    id: dropArea
    anchors.fill: parent
    enabled: root.isChannel

    onDropped: function (drop) {
      var source = drop.source
      if (!source || !source.stream) return
      if (String(source.stream.sink) === root.sinkName) return  // already here
      root.model.moveStream(source.stream.index, root.sinkName)
      drop.accept()
    }
  }
}
