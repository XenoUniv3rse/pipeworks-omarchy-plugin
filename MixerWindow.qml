import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui

// The Pipeworks mixer window.
//
// It runs in the Omarchy shell rather than in the daemon, which is why it looks
// like the rest of the desktop: it draws with the shell's own colour and
// spacing tokens, so it follows whatever theme is active instead of carrying a
// palette of its own. The daemon owns the audio and this owns none of it -
// every change here is an action on the session bus, and everything shown comes
// from the two files the daemon publishes.
//
// Summoned with: omarchy-shell shell summon pipeworks.mixer "{}"
Item {
  id: root

  // Injected by the shell.
  property var shell: null
  property var manifest: null

  property bool closingFromHost: false

  function open(_payloadJson) {
    closingFromHost = false
    window.visible = true
  }

  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  readonly property bool opened: window.visible

  MixerModel {
    id: mixer
    // Metering and the daemon's stream polling both cost real work, so they
    // only run while the window is actually on screen.
    watching: window.visible
  }

  // A status the daemon reported - a repaired link, usually. Held briefly and
  // keyed on the serial, so the same message twice reads as two events.
  property string statusText: ""

  Connections {
    target: mixer
    function onStatusSerialChanged() {
      if (mixer.statusSerial <= 0 || mixer.status === "") return
      root.statusText = mixer.status
      statusTimer.restart()
    }
  }

  Timer {
    id: statusTimer
    interval: 5000
    onTriggered: root.statusText = ""
  }

  FloatingWindow {
    id: window
    title: "Pipeworks"
    color: Color.background
    implicitWidth: 1040
    implicitHeight: 660
    minimumSize: Qt.size(560, 520)
    // Hidden until summoned. A FloatingWindow shows itself by default, so
    // whenever the shell mounts this plugin early - which it does for a panel
    // marked keepLoaded - the mixer would appear on screen at login without
    // anyone asking for it. open() is the only thing that shows it.
    visible: false

    onVisibleChanged: {
      if (!visible && !root.closingFromHost && root.shell
          && typeof root.shell.hide === "function")
        root.shell.hide("pipeworks.mixer")
    }

    Item {
      anchors.fill: parent

      ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------------ header

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: header.implicitHeight + Style.space(24)
          color: Util.alpha(Color.foreground, 0.03)

          RowLayout {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(20)
            anchors.rightMargin: Style.space(20)
            spacing: Style.space(12)

            ColumnLayout {
              spacing: 0

              Text {
                text: "Pipeworks"
                color: Color.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.heading
                font.bold: true
              }

              Text {
                text: root.statusText !== "" ? root.statusText
                  : (mixer.available ? "Virtual audio mixer" : "Waiting for the mixer daemon…")
                color: root.statusText !== "" ? Color.accent : Util.alpha(Color.foreground, 0.45)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            Item { Layout.fillWidth: true }

            Button {
              text: mixer.volumeLocked ? "MIDI only" : "Software + MIDI"
              // md-lock (U+F033E) / md-lock_open_variant (U+F0FC6)
              iconText: mixer.volumeLocked ? "\u{f033e}" : "\u{f0fc6}"
              iconSize: Style.font.bodySmall
              fontSize: Style.font.bodySmall
              bordered: true
              active: mixer.volumeLocked
              foreground: mixer.volumeLocked ? Color.urgent : Util.alpha(Color.foreground, 0.65)
              fontFamily: Style.font.family
              tooltipText: mixer.volumeLocked
                ? "Levels answer only to the control surface. Click to allow software changes."
                : "Click to reserve levels to the control surface."
              onClicked: mixer.setVolumeLocked(!mixer.volumeLocked)
            }

            Button {
              text: "Add"
              // md-plus (U+F0415)
              iconText: "\u{f0415}"
              iconSize: Style.font.bodySmall
              fontSize: Style.font.bodySmall
              bordered: true
              foreground: Color.foreground
              fontFamily: Style.font.family
              tooltipText: "Add a channel, input or output"
              // Only one overlay at a time: they share a layer, so opening the
              // second on top of the first leaves two dialogs stacked with only
              // the upper one reachable.
              onClicked: { settings.close(); addStrip.show() }
            }
          }
        }

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: 1
          color: Util.alpha(Color.foreground, 0.09)
        }

        // -------------------------------------------------------------- body

        Text {
          visible: !mixer.available
          Layout.fillWidth: true
          Layout.margins: Style.space(24)
          text: "The Pipeworks daemon is not running, or has no channels configured yet."
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }

        Flickable {
          id: body
          visible: mixer.available
          Layout.fillWidth: true
          Layout.fillHeight: true
          // The row takes its own implicit width from the strips; reading that
          // here is safe because nothing sets the row's width back from it.
          contentWidth: sections.implicitWidth + Style.space(40)
          contentHeight: height
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentWidth > width

          RowLayout {
            id: sections
            x: Style.space(20)
            y: Style.space(16)
            // Cards share one height so the mixer reads as a row of equals, but
            // that height is capped: tiled to a tall monitor the window has
            // hundreds of spare pixels, and handing them all to the strips just
            // stretches the apps block into an empty field. Past the cap the
            // slack stays below the cards, where it looks like what it is.
            height: Math.min(body.height - Style.space(32), Style.space(600))
            spacing: Style.space(20)

            StripGroup {
              model: mixer
              title: "Inputs"
              entities: mixer.inputs
              kind: "input"
              dragLayer: dragLayer
              Layout.fillHeight: true
              Layout.alignment: Qt.AlignTop
              onSettingsRequested: function (kind, entity) {
                addStrip.close()
                settings.show(kind, entity)
              }
            }

            StripGroup {
              model: mixer
              title: "Channels"
              entities: mixer.channels
              kind: "channel"
              dragLayer: dragLayer
              Layout.fillHeight: true
              Layout.alignment: Qt.AlignTop
              onSettingsRequested: function (kind, entity) {
                addStrip.close()
                settings.show(kind, entity)
              }
            }

            StripGroup {
              model: mixer
              title: "Outputs"
              entities: mixer.outputs
              kind: "output"
              dragLayer: dragLayer
              Layout.fillHeight: true
              Layout.alignment: Qt.AlignTop
              onSettingsRequested: function (kind, entity) {
                addStrip.close()
                settings.show(kind, entity)
              }
            }
          }
        }

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: 1
          color: Util.alpha(Color.foreground, 0.09)
        }

        // ------------------------------------------------------------ footer

        Toggle {
          Layout.fillWidth: true
          Layout.margins: Style.space(12)
          label: "Start on login"
          description: String(mixer.autostart.description || "")
          checked: mixer.autostart.enabled === true
          // Not every strategy is ours to change: when the shell supervises the
          // daemon it reports that rather than offering a switch that lies.
          enabled: mixer.autostart.canToggle !== false
          opacity: enabled ? 1.0 : 0.55
          fontFamily: Style.font.family
          onClicked: if (enabled) mixer.setAutostart(!checked)
        }
      }

      // Chips are reparented here while being dragged, so they float above
      // every card instead of being clipped inside the one they started in.
      Item {
        id: dragLayer
        anchors.fill: parent
        z: 50
      }

      AddStrip {
        id: addStrip
        model: mixer
        z: 100
      }

      StripSettings {
        id: settings
        model: mixer
        z: 100
      }
    }
  }
}
