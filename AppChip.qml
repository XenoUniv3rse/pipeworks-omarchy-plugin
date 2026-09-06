import QtQuick
import qs.Commons

// One application playing into a channel, draggable onto another channel.
//
// While a drag is in progress the chip is reparented to a layer above the whole
// window. Without that it stays clipped inside its own strip's column, which
// both hides it behind neighbouring cards and lets the column fight the drag by
// repositioning it every frame.
Item {
  id: root

  required property var stream
  property color accent: Color.accent
  // The item to reparent into while dragging. Supplied by the window, since
  // only it knows what sits above everything else.
  property Item dragLayer: null

  readonly property bool dragging: handler.active

  implicitWidth: visual.implicitWidth
  implicitHeight: visual.implicitHeight

  Drag.active: handler.active
  Drag.source: root
  Drag.hotSpot.x: width / 2
  Drag.hotSpot.y: height / 2

  Rectangle {
    id: visual
    anchors.fill: parent
    radius: Math.round(Style.space(5))
    color: Util.alpha(root.accent, root.dragging ? 0.34 : 0.18)
    border.width: 1
    border.color: Util.alpha(root.accent, root.dragging ? 0.9 : 0.5)

    implicitWidth: label.implicitWidth + Style.space(14)
    implicitHeight: label.implicitHeight + Style.space(6)

    Text {
      id: label
      anchors.centerIn: parent
      width: Math.min(implicitWidth, root.width - Style.space(14))
      text: String(root.stream.app || "")
      color: root.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
      elide: Text.ElideRight
      horizontalAlignment: Text.AlignHCenter
    }
  }

  DragHandler {
    id: handler
    target: root
    cursorShape: Qt.ClosedHandCursor
    // Dropping is explicit: without it the chip is released wherever it happens
    // to be and no DropArea is ever told about it.
    onActiveChanged: if (!active) root.Drag.drop()
  }

  HoverHandler {
    cursorShape: Qt.OpenHandCursor
  }

  states: State {
    when: handler.active
    ParentChange { target: root; parent: root.dragLayer }
  }
}
