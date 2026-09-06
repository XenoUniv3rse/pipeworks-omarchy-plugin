import QtQuick
import qs.Commons

// Vertical segmented level meter, filling from the bottom.
//
// The segments live in a Column inside a plain Item rather than in the Item
// itself: a Column sizes itself from its children, and children measured
// against their parent's height would make that circular.
Item {
  id: root

  property real level: 0

  readonly property int segments: 24
  readonly property real amberFrom: 0.64   // ~-18 dB on a -50..0 scale
  readonly property real redFrom: 0.88     // ~-6 dB
  readonly property real gap: 1

  // Unlit segments are drawn from the theme's foreground rather than a fixed
  // white: at 10% white they were invisible on a light theme, which left an
  // empty gutter beside every idle fader.
  readonly property color unlit: Util.alpha(Color.foreground, 0.13)

  implicitWidth: Math.max(4, Math.round(Style.space(6)))

  // Peaks arrive faster than the eye can follow; easing the value keeps the
  // meter readable instead of strobing.
  Behavior on level { NumberAnimation { duration: 80 } }

  Column {
    anchors.fill: parent
    spacing: root.gap

    Repeater {
      model: root.segments

      delegate: Rectangle {
        required property int index

        // A Column lays out top-down while a meter fills from the bottom, so
        // the first delegate is the loudest segment, not the quietest.
        readonly property real fraction: (root.segments - index - 0.5) / root.segments
        readonly property bool lit: root.level * root.segments > root.segments - index - 1
        readonly property color zone: fraction >= root.redFrom
          ? Qt.rgba(0.85, 0.30, 0.27, 1)
          : (fraction >= root.amberFrom ? Qt.rgba(0.88, 0.66, 0.22, 1)
                                        : Qt.rgba(0.33, 0.72, 0.42, 1))

        width: root.width
        height: Math.max(1, (root.height - (root.segments - 1) * root.gap) / root.segments)
        radius: 1
        // Unlit segments stay neutral rather than a dim tint of their zone:
        // across two dozen thin segments the tint read as a rainbow smear under
        // every idle fader, pulling the eye without meaning anything.
        color: lit ? zone : root.unlit
      }
    }
  }
}
