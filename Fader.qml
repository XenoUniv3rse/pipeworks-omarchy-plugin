import QtQuick
import qs.Commons

// A vertical fader.
//
// Drawn here rather than by rotating the shell's PanelSlider a quarter turn.
// That trick is fine for the cramped bar panel, but this one is the centrepiece
// of a strip: it wants a tall track, a fill in the channel's own accent colour,
// and a knob big enough to grab without aiming.
Item {
  id: root

  property real value: 0
  property real minimum: 0
  property real maximum: 100
  property real step: 2
  property bool interactive: true
  property color accent: Color.accent

  // While a drag is in progress the fader is the truth; the rest of the time it
  // follows the daemon, so the MIDI board and the bar panel move it too.
  property bool dragging: false
  property real liveValue: value

  signal moved(real value)
  signal released(real value)

  implicitWidth: 28
  implicitHeight: 170

  onValueChanged: if (!dragging) liveValue = value

  readonly property real range: Math.max(0.0001, maximum - minimum)
  readonly property real progress: Math.max(0, Math.min(1, (liveValue - minimum) / range))
  readonly property real knobSize: Math.round(Style.space(18))
  readonly property real travel: Math.max(1, height - knobSize)
  readonly property bool hot: area.containsMouse || root.dragging
  readonly property color fillColor: root.interactive
    ? root.accent : Util.alpha(Color.foreground, 0.28)

  Rectangle {
    id: track
    width: Math.max(4, Math.round(Style.space(6)))
    radius: width / 2
    anchors.horizontalCenter: parent.horizontalCenter
    y: root.knobSize / 2
    height: root.travel
    color: Util.alpha(Color.foreground, 0.13)
  }

  Rectangle {
    id: fill
    width: track.width
    radius: track.radius
    anchors.horizontalCenter: parent.horizontalCenter
    y: track.y + root.travel * (1 - root.progress)
    height: root.travel * root.progress
    color: root.fillColor

    // Animated only when something else moved the fader. Easing your own drag
    // makes the knob lag the pointer, which feels broken rather than smooth.
    Behavior on y {
      enabled: !root.dragging
      NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
    }
    Behavior on height {
      enabled: !root.dragging
      NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
    }
  }

  Rectangle {
    id: knob
    width: root.knobSize
    height: root.knobSize
    radius: width / 2
    anchors.horizontalCenter: parent.horizontalCenter
    y: root.travel * (1 - root.progress)
    color: Color.background
    border.width: Math.max(2, Math.round(Style.space(2)))
    border.color: root.fillColor
    scale: root.hot ? 1.12 : 1.0

    Behavior on y {
      enabled: !root.dragging
      NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
    }
    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    enabled: root.interactive
    hoverEnabled: true
    cursorShape: root.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
    acceptedButtons: Qt.LeftButton

    // The knob's centre travels between knobSize/2 and height - knobSize/2, so
    // the pointer is measured against that span rather than the whole item -
    // otherwise the top and bottom of the fader would be unreachable.
    function valueAt(y) {
      var position = Math.max(0, Math.min(root.travel, y - root.knobSize / 2))
      var raw = root.maximum - (position / root.travel) * root.range
      return Math.max(root.minimum, Math.min(root.maximum, Math.round(raw)))
    }

    function apply(y) {
      var next = valueAt(y)
      root.liveValue = next
      root.moved(next)
    }

    onPressed: function (mouse) {
      root.dragging = true
      apply(mouse.y)
    }

    onPositionChanged: function (mouse) {
      if (root.dragging) apply(mouse.y)
    }

    onReleased: {
      root.dragging = false
      root.released(root.liveValue)
      root.liveValue = root.value
    }

    onWheel: function (wheel) {
      var delta = wheel.angleDelta.y > 0 ? root.step : -root.step
      var next = Math.max(root.minimum, Math.min(root.maximum, Math.round(root.liveValue + delta)))
      root.liveValue = next
      root.moved(next)
      root.released(next)
    }
  }
}
