import QtQuick
import QtQuick.Layouts
import qs.Commons

// One titled run of strips - Inputs, Channels or Outputs.
//
// A file of its own rather than an inline component in the window: an inline
// component would have to reach outward for the model, the drag layer and the
// settings overlay, and passing them in makes what a group actually needs
// explicit.
ColumnLayout {
  id: root

  required property var model
  property string title: ""
  property var entities: []
  property string kind: "channel"
  property Item dragLayer: null
  property real stripWidth: Style.space(132)

  signal settingsRequested(string kind, var entity)

  visible: root.entities.length > 0
  spacing: Style.space(8)

  Text {
    text: root.title
    color: Util.alpha(Color.foreground, 0.45)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  RowLayout {
    Layout.fillHeight: true
    spacing: Style.space(10)

    Repeater {
      model: root.entities

      delegate: MixerStrip {
        required property var modelData

        Layout.preferredWidth: root.stripWidth
        Layout.fillHeight: true
        model: root.model
        entity: modelData
        kind: root.kind
        dragLayer: root.dragLayer
        // Only channels are colour-coded: the colour exists to tell apart the
        // places an application can be dragged into, and nothing is dragged
        // into an input or an output.
        accent: root.kind === "channel"
          ? root.model.accentFor(root.model.channelIndex(String(modelData.id)))
          : Color.accent
        onSettingsRequested: root.settingsRequested(root.kind, modelData)
      }
    }
  }
}
