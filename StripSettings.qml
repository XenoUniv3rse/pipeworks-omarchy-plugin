import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Everything about one strip in one place: what it is called, which device it
// is attached to, what on the control surface drives it, and the button that
// deletes it. Opened from a strip's gear rather than presented as a global list
// of every control in the mixer.
//
// An overlay inside the window rather than a window of its own: a second window
// would need its own placement, focus and stacking, all to show four fields.
Item {
  id: root

  required property var model
  property string kind: ""
  property var entity: null

  readonly property bool open: root.entity !== null
  readonly property string stripId: root.entity ? String(root.entity.id) : ""
  readonly property string stripLabel: root.entity
    ? String(root.entity.label || root.entity.id) : ""

  // What a Learn row binds, per kind of strip. A route has one row per output,
  // keyed "channel:output", which is why these are built rather than listed.
  readonly property var learnRows: {
    if (!root.entity) return []
    var rows = []
    if (root.kind === "output") {
      rows.push({ caption: "Volume", kind: "output_volume_cc", key: root.stripId })
      rows.push({ caption: "Mute", kind: "output_mute_note", key: root.stripId })
      rows.push({ caption: "Solo", kind: "output_solo_note", key: root.stripId })
    } else {
      rows.push({ caption: "Volume", kind: "volume_cc", key: root.stripId })
      rows.push({ caption: "Mute", kind: "mute_note", key: root.stripId })
      if (root.kind === "channel") {
        rows.push({ caption: "Solo", kind: "solo_note", key: root.stripId })
        for (var i = 0; i < root.model.outputs.length; i++) {
          var output = root.model.outputs[i]
          rows.push({
            caption: "Route to " + String(output.label || output.id),
            kind: "route_note",
            key: root.stripId + ":" + String(output.id)
          })
        }
      }
    }
    return rows
  }

  readonly property var deviceOptions: {
    var source = root.kind === "output" ? root.model.outputDevices : root.model.inputDevices
    var options = []
    for (var i = 0; i < source.length; i++)
      options.push({ value: String(source[i].name), label: String(source[i].description) })
    return options
  }

  readonly property string currentDevice: {
    if (!root.entity) return ""
    if (root.kind === "output") {
      var port = String(root.entity.port_l || "")
      return port.indexOf(":") > 0 ? port.split(":")[0] : ""
    }
    return String(root.entity.source || "")
  }

  function show(kind, entity) {
    root.kind = kind
    root.entity = entity
    nameField.text = String(entity.label || entity.id)
    confirmingRemoval = false
  }

  function close() {
    // Only when one is actually pending: closing the dialog otherwise sends a
    // cancel for nothing, on every close.
    if (String(root.model.learn.kind) !== "") root.model.midiLearnCancel()
    root.entity = null
    confirmingRemoval = false
  }

  property bool confirmingRemoval: false

  visible: root.open
  anchors.fill: parent

  // Swallows clicks so nothing behind the overlay reacts, and closes on a click
  // outside the card.
  MouseArea {
    anchors.fill: parent
    onClicked: root.close()
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.65)
  }

  Rectangle {
    id: card
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(48), Style.space(420))
    height: Math.min(parent.height - Style.space(48), content.implicitHeight + Style.space(32))
    radius: Math.round(Style.space(12))
    color: Color.popups.background
    border.width: 1
    border.color: Util.alpha(Color.foreground, 0.14)

    // The card itself is not a dismiss surface.
    MouseArea { anchors.fill: parent }

    Flickable {
      anchors.fill: parent
      anchors.margins: Style.space(16)
      contentWidth: width
      contentHeight: content.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      interactive: contentHeight > height

      ColumnLayout {
        id: content
        width: parent.width
        spacing: Style.space(10)

        RowLayout {
          Layout.fillWidth: true

          Text {
            Layout.fillWidth: true
            text: root.stripLabel
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.bold: true
            elide: Text.ElideRight
          }

          Button {
            // md-close (U+F0156)
            iconText: "\u{f0156}"
            iconSize: Style.font.body
            horizontalPadding: Style.space(4)
            foreground: Util.alpha(Color.foreground, 0.6)
            fontFamily: Style.font.family
            tooltipText: "Close"
            onClicked: root.close()
          }
        }

        // ------------------------------------------------------------ name

        Text {
          text: "Name"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          TextField {
            id: nameField
            Layout.fillWidth: true
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            onAccepted: renameButton.apply()
          }

          Button {
            id: renameButton
            text: "Rename"
            fontSize: Style.font.bodySmall
            bordered: true
            fontFamily: Style.font.family
            foreground: Color.foreground

            function apply() {
              var wanted = nameField.text.trim()
              if (wanted !== "" && wanted !== root.stripLabel)
                root.model.renameStrip(root.kind, root.stripId, wanted)
            }

            onClicked: apply()
          }
        }

        // ---------------------------------------------------------- device

        Text {
          visible: root.kind !== "channel"
          text: "Device"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Dropdown {
          visible: root.kind !== "channel"
          Layout.fillWidth: true
          showLabel: false
          options: root.deviceOptions
          value: root.currentDevice
          fontFamily: Style.font.family
          onChanged: function (value) {
            if (!value || value === root.currentDevice) return
            if (root.kind === "output") root.model.retargetOutput(root.stripId, value)
            else root.model.retargetInput(root.stripId, value)
          }
        }

        PanelSeparator { Layout.fillWidth: true }

        // ------------------------------------------------------------ MIDI

        RowLayout {
          Layout.fillWidth: true

          Text {
            Layout.fillWidth: true
            text: "Control surface"
            color: Util.alpha(Color.foreground, 0.5)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            visible: !root.model.midiConnected
            text: "not connected"
            color: Util.alpha(Color.foreground, 0.4)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        Repeater {
          model: root.learnRows

          delegate: RowLayout {
            required property var modelData

            readonly property var table: root.model.midiBindings[modelData.kind] || ({})
            readonly property var bound: table[modelData.key]
            // The daemon publishes which control is waiting, so a Learn started
            // here and a Learn still pending from before look the same.
            readonly property bool waiting: String(root.model.learn.kind) === modelData.kind
              && String(root.model.learn.key) === modelData.key

            Layout.fillWidth: true
            spacing: Style.space(6)

            Text {
              Layout.fillWidth: true
              text: modelData.caption
              color: Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }

            Text {
              text: bound === undefined || bound === null ? "—" : String(bound)
              color: Util.alpha(Color.foreground, 0.55)
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }

            Button {
              text: waiting ? "Waiting…" : "Learn"
              fontSize: Style.font.caption
              horizontalPadding: Style.space(6)
              verticalPadding: Style.space(2)
              bordered: true
              active: waiting
              foreground: waiting ? Color.accent : Util.alpha(Color.foreground, 0.6)
              fontFamily: Style.font.family
              tooltipText: root.model.midiConnected
                ? "Move the control you want bound to this"
                : "No control surface is connected"
              onClicked: {
                if (waiting) root.model.midiLearnCancel()
                else root.model.midiLearn(modelData.kind, modelData.key)
              }
            }
          }
        }

        PanelSeparator { Layout.fillWidth: true }

        // ---------------------------------------------------------- remove

        Text {
          visible: root.confirmingRemoval
          Layout.fillWidth: true
          text: root.kind === "output"
            ? "Removing an output detaches it from the mixer."
            : "Removing this restarts PipeWire, so audio will cut out briefly."
          color: Util.alpha(Color.foreground, 0.55)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Button {
            Layout.fillWidth: true
            text: root.confirmingRemoval
              ? "Remove \"" + root.stripLabel + "\" permanently"
              : "Remove this " + root.kind
            fontSize: Style.font.bodySmall
            bordered: true
            foreground: Color.urgent
            fontFamily: Style.font.family
            onClicked: {
              // Two clicks rather than a modal: deleting a strip is
              // irreversible, and a stray click on the first button should not
              // be enough to do it.
              if (!root.confirmingRemoval) {
                root.confirmingRemoval = true
                return
              }
              root.model.removeStrip(root.kind, root.stripId)
              root.close()
            }
          }

          Button {
            visible: root.confirmingRemoval
            text: "Cancel"
            fontSize: Style.font.bodySmall
            bordered: true
            foreground: Util.alpha(Color.foreground, 0.6)
            fontFamily: Style.font.family
            onClicked: root.confirmingRemoval = false
          }
        }
      }
    }
  }
}
