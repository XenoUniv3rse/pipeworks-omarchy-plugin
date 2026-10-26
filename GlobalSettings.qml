import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Settings for Pipeworks as a whole, rather than for one strip: how the window
// opens, starting with the session, and the control surface. Opened from the
// cog in the window's header.
//
// An overlay inside the window, like a strip's settings.
Item {
  id: root

  required property var model

  property bool open: false

  function show() { root.open = true }
  function close() { root.open = false }

  visible: root.open
  anchors.fill: parent

  // The stored match is a substring, matched the same way the daemon matches
  // it (containment, not equality) - a legacy short match like
  // "SMC-Mixer-Private" is genuinely connected even though it is not equal to
  // the full name "SINCO:SINCO SMC-Mixer-Private" that probing reports.
  // Resolving it to that full name is what lets the dropdown highlight the
  // right row instead of showing nothing selected on a working setup.
  // What the volume keys can drive: any strip, or the first output.
  readonly property var keyboardTargets: {
    var options = [{ value: "", label: "The first output" + (root.model.outputs.length
      ? " (" + String(root.model.outputs[0].label || root.model.outputs[0].id) + ")" : "") }]
    var groups = [[root.model.outputs, "output"], [root.model.channels, "channel"], [root.model.inputs, "input"]]
    for (var g = 0; g < groups.length; g++)
      for (var i = 0; i < groups[g][0].length; i++) {
        var strip = groups[g][0][i]
        options.push({ value: String(strip.id), label: String(strip.label || strip.id) + " (" + groups[g][1] + ")" })
      }
    return options
  }

  readonly property string resolvedPort: {
    for (var i = 0; i < root.model.midiPorts.length; i++) {
      if (root.model.midiPortMatch !== ""
          && root.model.midiPorts[i].indexOf(root.model.midiPortMatch) !== -1)
        return root.model.midiPorts[i]
    }
    return root.model.midiPortMatch
  }

  // Every board ALSA can see, plus whatever is configured even if it is not
  // detected right now - unplugged and unconfigured are different situations,
  // and both deserve to be visible.
  readonly property bool keyboard: root.model.controlSurface === "keyboard"

  // The keyboard first: on a laptop it is usually the only choice there is.
  // Only what can be chosen right now: the keyboard, and the boards ALSA can
  // see. A saved board that is not plugged in is not offered - it is said
  // below the list instead, so it neither looks selectable nor goes unsaid.
  readonly property var midiOptions: {
    var options = [{ value: "keyboard", label: "Keyboard (volume keys)" }]
    for (var i = 0; i < root.model.midiPorts.length; i++)
      options.push({ value: root.model.midiPorts[i], label: root.model.midiPorts[i] })
    return options
  }

  // Whether the saved board is one of those detected.
  readonly property bool boardDetected: root.model.midiPorts.indexOf(root.resolvedPort) !== -1

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
    width: Math.min(parent.width - Style.space(48), Style.space(520))
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
            text: "Settings"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.bold: true
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

        // ---------------------------------------------------------- general

        Text {
          text: "General"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Toggle {
          Layout.fillWidth: true
          label: "Open as a floating window"
          description: root.model.windowFloating
            ? "The mixer opens centred, floating over your other windows."
            : "The mixer is tiled into your layout like any other window."
          checked: root.model.windowFloating
          fontFamily: Style.font.family
          onClicked: root.model.setWindowFloating(!checked)
        }

        Toggle {
          Layout.fillWidth: true
          label: "Start on login"
          description: String(root.model.autostart.description || "")
          checked: root.model.autostart.enabled === true
          // Not every strategy is ours to change: when the shell supervises the
          // daemon it reports that rather than offering a switch that lies.
          enabled: root.model.autostart.canToggle !== false
          opacity: enabled ? 1.0 : 0.55
          fontFamily: Style.font.family
          onClicked: if (enabled) root.model.setAutostart(!checked)
        }

        PanelSeparator { Layout.fillWidth: true }

        // -------------------------------------------------- control surface

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Text {
            text: "Control surface"
            color: Util.alpha(Color.foreground, 0.5)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          // The meter's own green, rather than a colour found nowhere else.
          Rectangle {
            width: Style.space(6)
            height: Style.space(6)
            radius: width / 2
            color: root.keyboard || root.model.midiConnected ? Qt.rgba(0.35, 0.80, 0.40, 1) : Color.urgent
          }

          Text {
            text: root.keyboard ? "volume keys" : (root.model.midiConnected ? "connected" : "not connected")
            color: Util.alpha(Color.foreground, 0.4)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        Dropdown {
          Layout.fillWidth: true
          showLabel: false
          options: root.midiOptions
          value: root.keyboard ? "keyboard" : (root.boardDetected ? root.resolvedPort : "")
          fontFamily: Style.font.family
          // Selecting a listed board stores its full name, replacing whatever
          // match was configured before - so picking a board once is also how
          // an old short match upgrades to an exact one.
          onChanged: function (value) {
            if (value === "keyboard") { if (!root.keyboard) root.model.useKeyboard() }
            else root.model.setMidiPort(value)
          }
        }

        Text {
          visible: !root.keyboard && !root.boardDetected
          Layout.fillWidth: true
          text: (root.model.midiPortMatch !== ""
                  ? root.model.midiPortMatch + " is not connected. "
                  : "No MIDI board selected. ")
            + (root.model.midiPorts.length === 0
                  ? "Plug it in, or choose Keyboard to use the volume keys."
                  : "Plug it in, or choose another board or Keyboard above.")
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        // ----------------------------------------------------- keyboard

        RowLayout {
          visible: root.keyboard
          Layout.fillWidth: true
          Layout.fillHeight: false
          spacing: Style.space(8)

          Text {
            text: "Volume keys adjust"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Dropdown {
            id: keyboardTarget
            Layout.fillWidth: true
            showLabel: false
            options: root.keyboardTargets
            value: root.model.keyboardTarget
            fontFamily: Style.font.family
            onChanged: function (value) {
              if (value !== root.model.keyboardTarget) root.model.setKeyboardTarget(value)
            }
          }
        }

        Text {
          visible: root.keyboard
          Layout.fillWidth: true
          text: "Volume up and down move it 5% (1% with Alt), and Mute mutes it."
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Toggle {
          visible: !root.keyboard
          Layout.fillWidth: true
          label: "Turn off the volume keys while a board is in use"
          description: !root.model.blockVolumeKeys
            ? "The volume keys keep doing whatever your Hyprland config binds them to."
            : (root.model.midiConnected
                ? "Only the board changes levels: the volume keys do nothing, in every app."
                : "The board is not connected, so the volume keys work as usual until it is.")
          checked: root.model.blockVolumeKeys
          fontFamily: Style.font.family
          onClicked: root.model.setBlockVolumeKeys(!checked)
        }

        Toggle {
          // Faders only: the volume keys step from wherever the level is.
          visible: !root.keyboard
          Layout.fillWidth: true
          label: "Soft takeover"
          description: "After a level changes in software, a fader takes over again only once it is brought to that level, so nothing jumps."
          checked: root.model.softTakeover
          fontFamily: Style.font.family
          onClicked: root.model.setSoftTakeover(!checked)
        }

        Toggle {
          Layout.fillWidth: true
          label: "Show changes on screen"
          description: root.keyboard
            ? "The volume keys show what they changed on the shell's OSD."
            : "Faders and buttons on the board show what they changed on the shell's OSD."
          checked: root.model.midiOsd
          fontFamily: Style.font.family
          onClicked: root.model.setMidiOsd(!checked)
        }
      }
    }
  }
}
