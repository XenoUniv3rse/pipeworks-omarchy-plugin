import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
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

  // The payload may name a strip whose settings should open with the window,
  // or a scene to edit ("new" to save one):
  //   omarchy-shell shell summon pipeworks.mixer '{"settings":{"kind":"channel","id":"game"}}'
  //   omarchy-shell shell summon pipeworks.mixer '{"scene":"new"}'
  //   omarchy-shell shell summon pipeworks.mixer '{"eq":"music"}'
  //   omarchy-shell shell summon pipeworks.mixer '{"preferences":true}'
  function open(payloadJson) {
    closingFromHost = false
    window.visible = true
    var payload = ({})
    try { payload = JSON.parse(String(payloadJson || "{}")) || ({}) } catch (error) {}
    if (payload.scene) root.openScene(String(payload.scene))
    if (payload.eq) root.openEq(String(payload.eq))
    if (payload.preferences) { root.closeOverlays(); globalSettings.show() }
    var target = payload.settings
    root.pendingSettings = target && target.kind && target.id ? target : null
    root.openPendingSettings()
  }

  // Where the plugin lives, for the spectrum helper the EQ tuner runs. The
  // same derivation as Service.qml: third-party manifests lose __sourceDir.
  readonly property string pluginDir: {
    if (manifest && manifest.__sourceDir) return String(manifest.__sourceDir)
    var id = manifest && manifest.id ? String(manifest.id) : "pipeworks.mixer"
    return Quickshell.env("HOME") + "/.config/omarchy/plugins/" + id
  }

  // Only one overlay at a time: they share a layer, so opening a second on top
  // of the first leaves two dialogs stacked with only the upper one reachable.
  function closeOverlays() {
    settings.close()
    addStrip.close()
    sceneSettings.close()
    eqTuner.close()
    globalSettings.close()
  }

  function openEq(chanId) {
    if (!mixer.entityFor("channel", chanId) && !mixer.entityFor("input", chanId)) return
    root.closeOverlays()
    eqTuner.show(chanId)
  }

  function openScene(sceneId) {
    root.closeOverlays()
    if (sceneId === "new") sceneSettings.showNew()
    else sceneSettings.show(sceneId)
  }

  // Held until config has loaded: a window mounted by this very summon has not
  // read it yet, and the strip would not be found.
  property var pendingSettings: null

  function openPendingSettings() {
    if (!root.pendingSettings) return
    var kind = String(root.pendingSettings.kind)
    var entity = mixer.entityFor(kind, String(root.pendingSettings.id))
    if (!entity) return
    root.pendingSettings = null
    root.closeOverlays()
    settings.show(kind, entity)
  }

  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  readonly property bool opened: window.visible

  // Floating or tiled, as chosen in Settings. Hyprland decides that for a new
  // window, so it is applied each time the window opens and whenever the
  // setting changes - daemon/window_mode.py does the asking.
  function applyWindowMode() {
    if (!window.visible) return
    windowMode.command = ["/usr/bin/python3", "-B", root.pluginDir + "/daemon/window_mode.py",
                          mixer.windowFloating ? "floating" : "tiled"]
    windowMode.running = false
    windowMode.running = true
  }

  Process { id: windowMode }

  Connections {
    target: mixer
    function onWindowFloatingChanged() { root.applyWindowMode() }
  }

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
    function onConfigChanged() { root.openPendingSettings() }
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
      if (visible) root.applyWindowMode()
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
              onClicked: { root.closeOverlays(); addStrip.show() }
            }

            Button {
              // md-cog (U+F0493)
              iconText: "\u{f0493}"
              iconSize: Style.font.body
              horizontalPadding: Style.space(6)
              bordered: true
              foreground: Util.alpha(Color.foreground, 0.7)
              fontFamily: Style.font.family
              tooltipText: "Settings: window, start on login, control surface"
              onClicked: { root.closeOverlays(); globalSettings.show() }
            }
          }
        }

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: 1
          color: Util.alpha(Color.foreground, 0.09)
        }

        // ------------------------------------------------------------ scenes
        //
        // A scene is the whole mix - levels, mutes, solos, routing - saved
        // under a name. Click one to recall it; the cog edits it. The scene
        // that matches the live mix is highlighted.

        RowLayout {
          visible: mixer.available
          Layout.fillWidth: true
          Layout.leftMargin: Style.space(20)
          Layout.rightMargin: Style.space(20)
          Layout.topMargin: Style.space(10)
          Layout.bottomMargin: Style.space(10)
          spacing: Style.space(8)

          Text {
            text: "Scenes"
            color: Util.alpha(Color.foreground, 0.5)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Flickable {
            Layout.fillWidth: true
            Layout.preferredHeight: sceneChips.implicitHeight
            contentWidth: sceneChips.implicitWidth
            contentHeight: height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentWidth > width

            RowLayout {
              id: sceneChips
              spacing: Style.space(6)

              Text {
                visible: mixer.scenes.length === 0
                text: "None yet - save the current mix to recall it later."
                color: Util.alpha(Color.foreground, 0.35)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }

              Repeater {
                model: mixer.scenes

                delegate: RowLayout {
                  required property var modelData
                  readonly property bool current: mixer.sceneMatches(modelData)
                  spacing: 0

                  Button {
                    text: String(modelData.label || modelData.id)
                    fontSize: Style.font.bodySmall
                    horizontalPadding: Style.space(8)
                    verticalPadding: Style.space(3)
                    bordered: true
                    active: current
                    foreground: current ? Color.accent : Color.foreground
                    fontFamily: Style.font.family
                    tooltipText: current ? "The mix is set to this scene" : "Recall this scene"
                    onClicked: mixer.recallScene(modelData.id)
                  }

                  Button {
                    // md-cog (U+F0493)
                    iconText: "\u{f0493}"
                    iconSize: Style.font.caption
                    horizontalPadding: Style.space(4)
                    verticalPadding: Style.space(2)
                    foreground: Util.alpha(Color.foreground, 0.5)
                    fontFamily: Style.font.family
                    tooltipText: "Edit " + String(modelData.label || modelData.id)
                    onClicked: root.openScene(String(modelData.id))
                  }
                }
              }
            }
          }

          Button {
            text: "Save scene"
            // md-plus (U+F0415)
            iconText: "\u{f0415}"
            iconSize: Style.font.bodySmall
            fontSize: Style.font.bodySmall
            bordered: true
            foreground: Color.foreground
            fontFamily: Style.font.family
            tooltipText: "Save the current mix as a scene"
            onClicked: root.openScene("new")
          }
        }

        Rectangle {
          visible: mixer.available
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
          contentHeight: sections.height + Style.space(32)
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentWidth > width || contentHeight > height

          RowLayout {
            id: sections
            x: Style.space(20)
            y: Style.space(16)
            // Cards share one height so the mixer reads as a row of equals, but
            // that height is capped: tiled to a tall monitor the window has
            // hundreds of spare pixels, and handing them all to the strips just
            // stretches the apps block into an empty field. Past the cap the
            // slack stays below the cards, where it looks like what it is.
            //
            // There is a floor as well: below it a card's apps block and
            // routing buttons are crushed and clipped, so a short window
            // scrolls instead.
            height: Math.max(Style.space(480), Math.min(body.height - Style.space(32), Style.space(600)))
            spacing: Style.space(20)

            StripGroup {
              model: mixer
              title: "Inputs"
              entities: mixer.inputs
              kind: "input"
              dragLayer: dragLayer
              Layout.fillHeight: true
              Layout.alignment: Qt.AlignTop
              onEqRequested: function (entity) { root.openEq(String(entity.id)) }
              onSettingsRequested: function (kind, entity) {
                root.closeOverlays()
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
              onEqRequested: function (entity) { root.openEq(String(entity.id)) }
              onSettingsRequested: function (kind, entity) {
                root.closeOverlays()
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
                root.closeOverlays()
                settings.show(kind, entity)
              }
            }
          }
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

      EqTuner {
        id: eqTuner
        model: mixer
        spectrumScript: root.pluginDir + "/daemon/spectrum.py"
        z: 100
      }

      SceneSettings {
        id: sceneSettings
        model: mixer
        notice: root.statusText
        z: 100
      }

      StripSettings {
        id: settings
        model: mixer
        notice: root.statusText
        z: 100
      }

      GlobalSettings {
        id: globalSettings
        model: mixer
        z: 100
      }
    }
  }
}
