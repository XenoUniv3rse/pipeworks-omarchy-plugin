import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Saving a new scene, or everything about an existing one: its name, taking the
// current mix into it, the control that recalls it, and deleting it.
//
// An overlay inside the window, the same as a strip's settings.
Item {
  id: root

  required property var model
  property string notice: ""

  // "" while closed, "new" while naming a scene about to be saved, otherwise
  // the id of the scene being edited - held by id, not as an object, for the
  // same reason StripSettings does: config is replaced on every change.
  property string sceneId: ""

  readonly property bool open: root.sceneId !== ""
  readonly property bool creating: root.sceneId === "new"
  readonly property var scene: root.open && !root.creating ? root.model.sceneFor(root.sceneId) : null
  readonly property string sceneLabel: root.scene ? String(root.scene.label || root.sceneId) : ""

  property bool confirmingRemoval: false

  function showNew() {
    root.sceneId = "new"
    nameField.text = "Scene " + (root.model.scenes.length + 1)
    nameField.selectAll()
    nameField.forceActiveFocus()
    confirmingRemoval = false
  }

  function show(sceneId) {
    root.sceneId = String(sceneId)
    nameField.text = root.sceneLabel
    confirmingRemoval = false
  }

  function close() {
    if (String(root.model.learn.kind) !== "") root.model.midiLearnCancel()
    root.sceneId = ""
    confirmingRemoval = false
  }

  // A scene deleted while open (from another window, or the bus) closes this.
  onSceneChanged: if (root.open && !root.creating && !root.scene) root.close()

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
    id: card
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(48), Style.space(420))
    height: Math.min(parent.height - Style.space(48), content.implicitHeight + Style.space(32))
    radius: Math.round(Style.space(12))
    color: Color.popups.background
    border.width: 1
    border.color: Util.alpha(Color.foreground, 0.14)

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
            text: root.creating ? "Save scene" : root.sceneLabel
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

        Text {
          visible: root.creating
          Layout.fillWidth: true
          text: "Saves every level, mute, solo and route as they are now. Recalling the scene puts them back."
          color: Util.alpha(Color.foreground, 0.55)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
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
            onAccepted: nameButton.apply()
          }

          Button {
            id: nameButton
            text: root.creating ? "Save" : "Rename"
            fontSize: Style.font.bodySmall
            bordered: true
            fontFamily: Style.font.family
            foreground: root.creating ? Color.accent : Color.foreground

            function apply() {
              var wanted = nameField.text.trim()
              if (wanted === "") return
              if (root.creating) {
                root.model.saveScene(wanted)
                root.close()
              } else if (wanted !== root.sceneLabel) {
                root.model.renameScene(root.sceneId, wanted)
              }
            }

            onClicked: apply()
          }
        }

        // ---------------------------------------------------------- contents

        PanelSeparator {
          visible: !root.creating
          Layout.fillWidth: true
        }

        Text {
          visible: !root.creating
          text: "Mix"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          visible: !root.creating
          Layout.fillWidth: true
          text: root.model.sceneMatches(root.scene)
            ? "The mixer is currently set to this scene."
            : "The mixer has changed since this scene was recalled or saved."
          color: Util.alpha(Color.foreground, 0.55)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        RowLayout {
          visible: !root.creating
          Layout.fillWidth: true
          spacing: Style.space(6)

          Button {
            Layout.fillWidth: true
            text: "Recall"
            // md-play (U+F040A)
            iconText: "\u{f040a}"
            iconSize: Style.font.bodySmall
            fontSize: Style.font.bodySmall
            bordered: true
            foreground: Color.accent
            fontFamily: Style.font.family
            onClicked: root.model.recallScene(root.sceneId)
          }

          Button {
            Layout.fillWidth: true
            text: "Save current mix here"
            // md-content_save (U+F0193)
            iconText: "\u{f0193}"
            iconSize: Style.font.bodySmall
            fontSize: Style.font.bodySmall
            bordered: true
            foreground: Color.foreground
            fontFamily: Style.font.family
            tooltipText: "Replace this scene with the mix as it is now"
            onClicked: root.model.updateScene(root.sceneId)
          }
        }

        // ------------------------------------------------------------ MIDI

        PanelSeparator {
          visible: !root.creating
          Layout.fillWidth: true
        }

        RowLayout {
          visible: !root.creating
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

        Text {
          visible: !root.creating && root.notice !== ""
          Layout.fillWidth: true
          text: root.notice
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: root.creating || !root.open ? []
            : [{ caption: "Recall", kind: "scene_note", key: root.sceneId }]
          delegate: LearnRow { mixer: root.model }
        }

        // ---------------------------------------------------------- remove

        PanelSeparator {
          visible: !root.creating
          Layout.fillWidth: true
        }

        RowLayout {
          visible: !root.creating
          Layout.fillWidth: true
          spacing: Style.space(6)

          Button {
            Layout.fillWidth: true
            text: root.confirmingRemoval
              ? "Delete \"" + root.sceneLabel + "\" permanently"
              : "Delete this scene"
            fontSize: Style.font.bodySmall
            bordered: true
            foreground: Color.urgent
            fontFamily: Style.font.family
            onClicked: {
              if (!root.confirmingRemoval) {
                root.confirmingRemoval = true
                return
              }
              root.model.removeScene(root.sceneId)
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
