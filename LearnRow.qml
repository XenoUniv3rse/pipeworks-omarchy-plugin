import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One MIDI Learn row: what it drives, what it is bound to, clear, and Learn -
// with a warning underneath when another binding answers the same control.
// Used by the strip and scene dialogs, as a Repeater delegate fed
// {caption, kind, key}.
ColumnLayout {
  id: root

  required property var modelData
  // The MixerModel. Not called "model": a Repeater would treat a property of
  // that name on its delegate as the slot for its own model data.
  property var mixer: null

  readonly property var table: root.mixer ? root.mixer.midiBindings[modelData.kind] || ({}) : ({})
  readonly property var bound: table[modelData.key]
  readonly property bool isBound: bound !== undefined && bound !== null
  // The daemon publishes which control is waiting, so a Learn started
  // here and a Learn still pending from before look the same.
  readonly property bool waiting: !!root.mixer
    && String(root.mixer.learn.kind) === modelData.kind
    && String(root.mixer.learn.key) === modelData.key
  readonly property var conflicts: root.mixer
    ? root.mixer.bindingConflicts(modelData.kind, modelData.key) : []

  Layout.fillWidth: true
  spacing: Style.space(1)

  RowLayout {
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
      text: root.mixer ? root.mixer.bindingText(bound) : "—"
      color: Util.alpha(Color.foreground, 0.55)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Button {
      // Hidden rather than disabled when there is nothing to clear, so an
      // unbound row does not carry a control that does nothing.
      visible: isBound
      // md-close (U+F0156)
      iconText: "\u{f0156}"
      iconSize: Style.font.caption
      horizontalPadding: Style.space(3)
      verticalPadding: Style.space(2)
      foreground: Util.alpha(Color.foreground, 0.45)
      fontFamily: Style.font.family
      tooltipText: "Clear this binding"
      onClicked: root.mixer.midiUnbind(modelData.kind, modelData.key)
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
      tooltipText: root.mixer && root.mixer.midiConnected
        ? "Move the control you want bound to this"
        : "No control surface is connected"
      onClicked: {
        if (waiting) root.mixer.midiLearnCancel()
        else root.mixer.midiLearn(modelData.kind, modelData.key)
      }
    }
  }

  // Left over from before Learn moved bindings rather than duplicating
  // them, or from a hand-edited config: say which one is dead.
  Text {
    visible: conflicts.length > 0
    Layout.fillWidth: true
    text: "Also bound to " + conflicts.join(", ") + " - only one will respond. Learn again to move it here."
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
}
