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
  // The strip is held by id, not as the object the caller passed in: that
  // object comes from a model only rebuilt when strips are added, removed or
  // renamed, so it would not show a microphone added while this is open.
  property string stripId: ""

  readonly property bool open: root.stripId !== ""
  readonly property var entity: root.open
    ? root.model.entityFor(root.kind, root.stripId) : null
  readonly property string stripLabel: root.entity
    ? String(root.entity.label || root.stripId) : root.stripId

  // What a Learn row binds, per kind of strip. A route has one row per output,
  // keyed "channel:output", which is why these are built rather than listed.
  readonly property var learnRows: {
    if (!root.open) return []
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

  // Outputs only: an input picks its microphones from the list below instead,
  // because it can have more than one.
  readonly property var deviceOptions: {
    var devices = root.model.outputDevices
    var options = []
    for (var i = 0; i < devices.length; i++)
      options.push({ value: String(devices[i].name), label: String(devices[i].description) })
    return options
  }

  // Names only, so adjusting a level does not rebuild the row carrying it.
  readonly property var sourceNames: root.model.sourceNamesFor(root.stripId)
  readonly property var addableSources: root.model.unusedInputDevices(root.stripId)

  readonly property string currentDevice: {
    if (!root.entity || root.kind !== "output") return ""
    var port = String(root.entity.port_l || "")
    return port.indexOf(":") > 0 ? port.split(":")[0] : ""
  }

  function show(kind, entity) {
    root.kind = kind
    root.stripId = String(entity.id)
    nameField.text = String(entity.label || entity.id)
    confirmingRemoval = false
  }

  function close() {
    // Only when one is actually pending: closing the dialog otherwise sends a
    // cancel for nothing, on every close.
    if (String(root.model.learn.kind) !== "") root.model.midiLearnCancel()
    root.stripId = ""
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
          visible: root.kind === "output"
          text: "Device"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Dropdown {
          visible: root.kind === "output"
          Layout.fillWidth: true
          showLabel: false
          options: root.deviceOptions
          value: root.currentDevice
          fontFamily: Style.font.family
          onChanged: function (value) {
            if (!value || value === root.currentDevice) return
            root.model.retargetOutput(root.stripId, value)
          }
        }

        // ----------------------------------------------------- microphones
        //
        // An input can carry several. They are summed into the one virtual
        // microphone the strip's fader controls, and each keeps its own capture
        // level here - that level is the device's own, so it applies wherever
        // the microphone is used, not only to this mixer.

        Text {
          visible: root.kind === "input"
          text: root.sourceNames.length === 1 ? "Microphone" : "Microphones"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          visible: root.kind === "input" && root.sourceNames.length === 0
          Layout.fillWidth: true
          text: "No microphone is feeding this input."
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: root.kind === "input" ? root.sourceNames : []

          delegate: ColumnLayout {
            required property var modelData

            readonly property string sourceName: String(modelData)
            readonly property real sourceVolume: root.model.sourceVolume(
              root.stripId, sourceName)

            Layout.fillWidth: true
            Layout.bottomMargin: Style.space(4)
            spacing: Style.space(2)

            RowLayout {
              Layout.fillWidth: true
              spacing: Style.space(6)

              Text {
                Layout.fillWidth: true
                text: root.model.deviceDescription(sourceName)
                color: Color.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }

              Text {
                text: Math.round(level.dragging ? level.liveValue : sourceVolume) + "%"
                color: Util.alpha(Color.foreground, 0.55)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }

              Button {
                // md-close (U+F0156)
                iconText: "\u{f0156}"
                iconSize: Style.font.bodySmall
                horizontalPadding: Style.space(4)
                verticalPadding: Style.space(2)
                foreground: Util.alpha(Color.foreground, 0.5)
                fontFamily: Style.font.family
                tooltipText: "Remove this microphone from " + root.stripLabel
                onClicked: root.model.removeInputSource(root.stripId, sourceName)
              }
            }

            PanelSlider {
              id: level
              Layout.fillWidth: true
              minimum: 0
              maximum: 100
              step: 2
              integer: true
              value: dragging ? liveValue : sourceVolume
              fillColor: Color.accent
              onMoved: function (value) {
                root.model.queueSourceVolume(root.stripId, sourceName, value)
              }
              onReleased: function (value) {
                root.model.queueSourceVolume(root.stripId, sourceName, value)
              }
            }
          }
        }

        RowLayout {
          visible: root.kind === "input"
          Layout.fillWidth: true
          spacing: Style.space(6)

          Dropdown {
            id: addSource
            Layout.fillWidth: true
            showLabel: false
            options: root.addableSources
            value: root.addableSources.length > 0 ? root.addableSources[0].value : ""
            fontFamily: Style.font.family
            enabled: root.addableSources.length > 0
            opacity: root.addableSources.length > 0 ? 1.0 : 0.5
          }

          Button {
            text: "Add"
            // md-plus (U+F0415)
            iconText: "\u{f0415}"
            iconSize: Style.font.bodySmall
            fontSize: Style.font.bodySmall
            bordered: true
            enabled: root.addableSources.length > 0
            opacity: root.addableSources.length > 0 ? 1.0 : 0.5
            foreground: Color.accent
            fontFamily: Style.font.family
            tooltipText: "Also feed this microphone into " + root.stripLabel
            onClicked: {
              if (addSource.value) root.model.addInputSource(root.stripId, addSource.value)
            }
          }
        }

        Text {
          visible: root.kind === "input" && root.addableSources.length === 0
          Layout.fillWidth: true
          text: "Every capture device is already feeding this input."
          color: Util.alpha(Color.foreground, 0.4)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        PanelSeparator {
          visible: root.kind === "input"
          Layout.fillWidth: true
        }

        // --------------------------------------------------------- effects
        //
        // Switching one on rebuilds the strip's filter graph, which its chain
        // host only picks up when it restarts - so a switch blips this strip's
        // audio, while every slider below is live.

        Text {
          visible: root.kind === "input"
          text: "Effects"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Repeater {
          model: root.kind === "input" ? root.model.effectsCatalogue : []

          delegate: ColumnLayout {
            required property var modelData

            readonly property string effectId: String(modelData.id)
            readonly property bool on: root.model.effectEnabled(root.stripId, effectId)

            Layout.fillWidth: true
            Layout.bottomMargin: Style.space(2)
            spacing: Style.space(2)

            RowLayout {
              Layout.fillWidth: true
              spacing: Style.space(6)

              Button {
                text: String(modelData.label)
                fontSize: Style.font.bodySmall
                horizontalPadding: Style.space(6)
                verticalPadding: Style.space(3)
                bordered: true
                active: on
                foreground: on ? Color.accent : Util.alpha(Color.foreground, 0.55)
                fontFamily: Style.font.family
                tooltipText: String(modelData.description)
                onClicked: root.model.setEffectEnabled(root.stripId, effectId, !on)
              }

              Text {
                Layout.fillWidth: true
                text: String(modelData.description)
                color: Util.alpha(Color.foreground, on ? 0.5 : 0.32)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            // Controls appear only for an effect that is on: a slider for
            // something not in the graph would move nothing.
            Repeater {
              model: on ? modelData.controls : []

              delegate: RowLayout {
                required property var modelData

                readonly property real amount: root.model.effectControl(
                  root.stripId, effectId, modelData)

                Layout.fillWidth: true
                Layout.leftMargin: Style.space(10)
                spacing: Style.space(6)

                Text {
                  Layout.preferredWidth: Style.space(74)
                  text: String(modelData.label)
                  color: Util.alpha(Color.foreground, 0.6)
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }

                PanelSlider {
                  id: knob
                  Layout.fillWidth: true
                  minimum: Number(modelData.minimum)
                  maximum: Number(modelData.maximum)
                  step: (Number(modelData.maximum) - Number(modelData.minimum)) / 50
                  value: dragging ? liveValue : amount
                  fillColor: Color.accent
                  onMoved: function (value) {
                    root.model.queueEffectControl(root.stripId, effectId, modelData.id, value)
                  }
                  onReleased: function (value) {
                    root.model.queueEffectControl(root.stripId, effectId, modelData.id, value)
                  }
                }

                Text {
                  Layout.preferredWidth: Style.space(52)
                  horizontalAlignment: Text.AlignRight
                  text: (knob.dragging ? knob.liveValue : amount).toFixed(
                          Number(modelData.maximum) - Number(modelData.minimum) > 40 ? 0 : 1)
                        + " " + String(modelData.unit)
                  color: Util.alpha(Color.foreground, 0.55)
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
              }
            }
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
