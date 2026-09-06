import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Adding a strip: a virtual channel applications play into, a hardware input
// republished as a microphone, or a physical output.
Item {
  id: root

  required property var model
  property bool open: false

  property string kind: "channel"
  property string device: ""
  property bool applying: false

  readonly property var kindOptions: [
    { value: "channel", label: "Virtual channel (apps play into it)" },
    { value: "input", label: "Input (hardware capture device)" },
    { value: "output", label: "Output (physical device)" }
  ]

  readonly property var deviceOptions: {
    if (root.kind === "channel") return []
    var source = root.kind === "output" ? root.model.outputDevices : root.model.inputDevices
    var options = []
    for (var i = 0; i < source.length; i++)
      options.push({ value: String(source[i].name), label: String(source[i].description) })
    return options
  }

  // Channels and inputs are loopback modules declared in a PipeWire drop-in, so
  // adding one rewrites that file and restarts PipeWire. An output attaches to
  // hardware that already exists and costs nothing.
  readonly property bool cutsAudio: root.kind !== "output"
  readonly property bool ready: nameField.text.trim() !== ""
    && (root.kind === "channel" || root.device !== "")

  function show() {
    nameField.text = ""
    root.kind = "channel"
    root.device = ""
    root.applying = false
    root.open = true
    nameField.forceActiveFocus()
  }

  function close() {
    root.open = false
    root.applying = false
  }

  function apply() {
    if (!root.ready || root.applying) return
    var name = nameField.text.trim()
    if (root.kind === "output") {
      root.model.addOutput(name, root.device)
      root.close()
      return
    }
    // The daemon blocks while PipeWire comes back, and the window is a separate
    // process so it stays responsive. Say what is happening rather than looking
    // like the click did nothing for two seconds.
    root.applying = true
    if (root.kind === "input") root.model.addInput(name, root.device)
    else root.model.addChannel(name)
    closeTimer.restart()
  }

  Timer {
    id: closeTimer
    interval: 2500
    onTriggered: root.close()
  }

  onDeviceOptionsChanged: {
    // Default to the first device whenever the list changes under a kind that
    // needs one, so the Add button is not disabled for no visible reason.
    if (root.kind !== "channel" && root.device === "" && root.deviceOptions.length > 0)
      root.device = root.deviceOptions[0].value
  }

  onKindChanged: {
    root.device = root.deviceOptions.length > 0 ? root.deviceOptions[0].value : ""
  }

  visible: root.open
  anchors.fill: parent

  MouseArea {
    anchors.fill: parent
    onClicked: root.close()
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.65)
  }

  Rectangle {
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(48), Style.space(420))
    height: content.implicitHeight + Style.space(32)
    radius: Math.round(Style.space(12))
    color: Color.popups.background
    border.width: 1
    border.color: Util.alpha(Color.foreground, 0.14)

    MouseArea { anchors.fill: parent }

    ColumnLayout {
      id: content
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(16)
      spacing: Style.space(10)

      Text {
        text: "Add a strip"
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.heading
        font.bold: true
      }

      Dropdown {
        Layout.fillWidth: true
        showLabel: false
        options: root.kindOptions
        value: root.kind
        fontFamily: Style.font.family
        onChanged: function (value) { root.kind = value }
      }

      TextField {
        id: nameField
        Layout.fillWidth: true
        placeholderText: "Name"
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        onAccepted: root.apply()
      }

      Dropdown {
        visible: root.kind !== "channel"
        Layout.fillWidth: true
        showLabel: false
        options: root.deviceOptions
        value: root.device
        fontFamily: Style.font.family
        onChanged: function (value) { root.device = value }
      }

      Text {
        visible: root.kind !== "channel" && root.deviceOptions.length === 0
        Layout.fillWidth: true
        text: "No device available to select."
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        visible: root.cutsAudio
        Layout.fillWidth: true
        text: root.applying
          ? "Applying — audio will briefly cut out…"
          : "Adding this restarts PipeWire, so audio will cut out briefly."
        color: Util.alpha(Color.foreground, 0.55)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)

        Item { Layout.fillWidth: true }

        Button {
          text: "Cancel"
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: Util.alpha(Color.foreground, 0.6)
          fontFamily: Style.font.family
          onClicked: root.close()
        }

        Button {
          text: root.applying ? "Applying…" : "Add"
          fontSize: Style.font.bodySmall
          bordered: true
          enabled: root.ready && !root.applying
          opacity: root.ready && !root.applying ? 1.0 : 0.45
          foreground: Color.accent
          fontFamily: Style.font.family
          onClicked: root.apply()
        }
      }
    }
  }
}
