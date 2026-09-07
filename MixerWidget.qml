import QtQuick
import QtQuick.Layouts
import Quickshell.Services.Pipewire
import qs.Commons
import qs.Ui

// Bar widget for the Pipeworks virtual audio mixer: a fader panel under the
// bar icon, for the everyday reach for a level without opening the window.
//
// Reading state and driving the daemon are MixerModel's job, shared with the
// mixer window. What is left here is the bar icon, the panel's layout, and the
// mute indicator - the parts a window has no use for.
BarWidget {
  id: root
  moduleName: "pipeworks.mixer"

  // The bar sizes each slot from its widget's implicit size. Omitting these
  // leaves the slot zero-wide, which renders nothing and logs nothing.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property bool popupOpen: false

  // State and actions live in MixerModel, shared with the mixer window: both
  // front ends follow the same files and drive the daemon through the same
  // actions, so there is one place for that plumbing rather than two copies
  // drifting apart.
  //
  // watching stays false. It asks the daemon to poll for running applications
  // and devices, which only the window shows - the bar panel would be paying
  // for a pactl call every couple of seconds and displaying none of it.
  MixerModel { id: mixer }

  // The plugin's own service, which supervises the daemon. Consulted only to
  // explain an empty panel: without it the widget still works against a
  // daemon started any other way.
  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("pipeworks.mixer") : null

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color barForegroundColor: bar ? bar.barForeground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Panel geometry.
  //
  // Every strip is pinned to exactly stripWidth so the panel's width can be
  // arithmetic. Measuring the laid-out content instead reads better but does
  // not work here: the content sits inside the panel, so its implicit width
  // feeds back into the panel's own width, and Qt breaks that cycle by keeping
  // a stale value - which sized the panel for fewer strips than it had and
  // dropped the last one off the edge.
  readonly property int stripWidth: Style.space(64)
  readonly property int stripSpacing: Style.space(6)
  readonly property int sectionSpacing: Style.space(10)
  readonly property int faderHeight: Style.space(120)
  readonly property int minPanelWidth: Style.space(340)

  // How many strips each populated section holds. Empty sections are dropped
  // so they cost neither a column nor a dividing rule.
  readonly property var sectionSizes: [
    mixer.inputs.length, mixer.channels.length, mixer.outputs.length
  ].filter(function (count) { return count > 0 })

  readonly property int desiredPanelWidth: {
    if (!mixer.available || root.sectionSizes.length === 0) return root.minPanelWidth
    var total = 0
    for (var i = 0; i < root.sectionSizes.length; i++)
      total += root.sectionSizes[i] * root.stripWidth
        + (root.sectionSizes[i] - 1) * root.stripSpacing
    // Every gap between sections carries a rule plus the spacing either side.
    total += (root.sectionSizes.length - 1) * (root.sectionSpacing * 2 + 1)
    return Math.max(root.minPanelWidth, total)
  }

  // Strips excluded from the bar indicator, by id or by the label shown on
  // screen. An output that normally lives muted - a second set of speakers you
  // rarely use - would otherwise keep the icon lit permanently, which just
  // teaches you to ignore it.
  readonly property var indicatorIgnored: {
    var ignored = ({})
    var tokens = String(root.setting("mutedIndicatorIgnore", "")).split(",")
    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i].trim().toLowerCase()
      if (token !== "") ignored[token] = true
    }
    return ignored
  }

  function labelFor(stripId) {
    var groups = [mixer.inputs, mixer.channels, mixer.outputs]
    for (var g = 0; g < groups.length; g++) {
      var list = groups[g]
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].id === stripId) return String(list[i].label || "")
      }
    }
    return ""
  }

  function countsTowardIndicator(stripId) {
    if (root.indicatorIgnored[String(stripId).toLowerCase()]) return false
    var label = root.labelFor(stripId).toLowerCase()
    return !(label !== "" && root.indicatorIgnored[label])
  }

  // Anything silenced is worth surfacing on the bar itself: a muted channel is
  // the usual answer to "why can I not hear this".
  readonly property bool anyMuted: {
    var key
    for (key in mixer.mutes)
      if (mixer.mutes[key] && root.countsTowardIndicator(key)) return true
    for (key in mixer.outputMutes)
      if (mixer.outputMutes[key] && root.countsTowardIndicator(key)) return true
    return false
  }

  readonly property bool opened: popupOpen
  function open() { root.popupOpen = true }
  function close() { root.popupOpen = false }

  function openWindow() {
    // The window is a panel in this same shell, so summon it directly. Asking
    // the daemon would only have it shell back out to the shell again. The
    // action stays as the fallback for a shell too old to know the panel.
    if (root.bar && root.bar.shell && typeof root.bar.shell.summon === "function")
      root.bar.shell.summon("pipeworks.mixer", "{}")
    else
      mixer.activate("show-window", "[]")
    root.popupOpen = false
  }

  // ------------------------------------------------------------- bar icon

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // md-tune (U+F062E): the mixer-faders glyph.
    text: "󰘮"
    active: mixer.available && root.anyMuted
    dimmed: !mixer.available
    tooltipText: mixer.available
      ? "Pipeworks mixer" + (root.anyMuted ? "  ·  something is muted" : "")
      : "Pipeworks is not running"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.MiddleButton) root.openWindow()
      else root.popupOpen = !root.popupOpen
    }
  }

  // --------------------------------------------------------------- popup

  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.popupOpen
    focusTarget: keyCatcher
    // The width the strips need is the width *inside* the card, so the card's
    // own padding and border have to be added on top - fittedContentHeight
    // does that for height, but the width side leaves it to the caller.
    contentWidth: popup.fittedContentWidth(
      root.desiredPanelWidth + popup.padding * 2
        + Border.left(popup.borderSpec) + Border.right(popup.borderSpec),
      Style.space(1400))
    contentHeight: popup.fittedContentHeight(column.implicitHeight, Style.space(620))

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.close()

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: column.width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height || contentWidth > width

        ColumnLayout {
          id: column
          // Never narrower than the strips need: on a display too small for
          // them the panel scrolls sideways rather than crushing every fader.
          width: Math.max(flick.width, root.desiredPanelWidth)
          spacing: Style.space(6)

          Text {
            visible: !mixer.available
            Layout.fillWidth: true
            text: {
              if (!root.service) return "Pipeworks is not running."
              if (!root.service.dependenciesChecked) return "Checking dependencies..."
              if (!root.service.dependenciesOk)
                return "Missing packages:\n  " + root.service.missingDependencies.join("\n  ")
                  + "\n\nInstall them with:\n  sudo pacman -S "
                  + root.service.missingDependencies.join(" ")
              return "Starting the mixer...\n" + root.service.statusSummary
            }
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            wrapMode: Text.WordWrap
          }

          // Every strip vertical and side by side, sections divided by a rule -
          // the same shape as the mixer window, so the two read as one
          // instrument rather than two different programs.
          RowLayout {
            visible: mixer.available
            Layout.alignment: Qt.AlignHCenter
            spacing: root.sectionSpacing

            StripSection {
              visible: mixer.inputs.length > 0
              title: "Inputs"
              model: mixer.available ? mixer.inputs : []
            }

            SectionRule {
              visible: mixer.inputs.length > 0
                && (mixer.channels.length > 0 || mixer.outputs.length > 0)
            }

            StripSection {
              visible: mixer.channels.length > 0
              title: "Channels"
              model: mixer.available ? mixer.channels : []
              showRoutes: true
            }

            SectionRule {
              visible: mixer.channels.length > 0 && mixer.outputs.length > 0
            }

            StripSection {
              visible: mixer.outputs.length > 0
              title: "Outputs"
              model: mixer.available ? mixer.outputs : []
              isOutput: true
            }
          }

          PanelSeparator {
            visible: mixer.available
            Layout.fillWidth: true
          }

          Button {
            visible: mixer.available
            Layout.fillWidth: true
            text: mixer.volumeLocked ? "Volume: MIDI only" : "Volume: Software + MIDI"
            iconText: mixer.volumeLocked ? "󰌾" : "󰿆"
            fontSize: Style.font.bodySmall
            foreground: mixer.volumeLocked ? root.urgent : root.dim
            fontFamily: root.fontFamily
            bordered: true
            tooltipText: mixer.volumeLocked
              ? "Levels answer only to the control surface. Click to allow software changes."
              : "Click to reserve levels to the control surface."
            onClicked: mixer.activate("toggle-volume-lock", "[]")
          }

          Button {
            visible: mixer.available
            Layout.fillWidth: true
            text: "Open mixer"
            iconText: "󰘮"
            fontSize: Style.font.bodySmall
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: root.openWindow()
          }
        }
      }
    }
  }

  // Vertical segmented level meter. Same colour scheme and dB floor as the
  // mixer window's meters, so the two read as one instrument.
  //
  // The segments live in a Column inside a plain Item rather than in the Item
  // itself: a Column sizes itself from its children, and children measured
  // against their parent's height would make that circular.
  component LevelColumn: Item {
    id: meter
    property real level: 0

    readonly property int segments: 22
    readonly property real gap: 1

    // Where the colours change, in dBFS rather than as fractions of the meter.
    //
    // These used to be 0.64 and 0.88 of the meter's height, which put amber at
    // -18 dBFS - a healthy nominal level, not a warning. With loud content that
    // lit amber at half fader and red at eighty percent, so a channel turned
    // down to barely audible still looked like it was running hot. Amber now
    // means "approaching clipping" and red "at it".
    readonly property real floorDb: -50
    readonly property real amberDb: -12
    readonly property real redDb: -3

    readonly property real amberFrom: (amberDb - floorDb) / -floorDb
    readonly property real redFrom: (redDb - floorDb) / -floorDb

    // Peaks arrive faster than the eye can follow; easing the value keeps the
    // meter readable instead of strobing.
    Behavior on level { NumberAnimation { duration: 80 } }

    Column {
      anchors.fill: parent
      spacing: meter.gap

      Repeater {
        model: meter.segments
        delegate: Rectangle {
          required property int index
          // A Column lays out top-down while a meter fills from the bottom, so
          // the first delegate is the loudest segment, not the quietest.
          readonly property real fraction: (meter.segments - index - 0.5) / meter.segments
          readonly property bool lit: meter.level * meter.segments > meter.segments - index - 1
          readonly property color zone: fraction >= meter.redFrom
            ? Qt.rgba(0.91, 0.30, 0.24, 1)
            : (fraction >= meter.amberFrom ? Qt.rgba(0.95, 0.71, 0.19, 1)
                                           : Qt.rgba(0.35, 0.80, 0.40, 1))
          width: meter.width
          height: Math.max(1, (meter.height - (meter.segments - 1) * meter.gap) / meter.segments)
          radius: 1
          // Unlit segments are neutral rather than a dim tint of their zone:
          // across 22 thin segments the tint read as a rainbow smear under every
          // idle fader, which pulled the eye without meaning anything.
          color: lit ? zone : Qt.rgba(1, 1, 1, 0.10)
        }
      }
    }
  }

  // One titled group of strips - Inputs, Channels or Outputs.
  component StripSection: ColumnLayout {
    id: section

    property string title: ""
    property alias model: strips.model
    property bool isOutput: false
    property bool showRoutes: false

    Layout.alignment: Qt.AlignTop
    spacing: Style.space(4)

    PanelSectionHeader {
      Layout.fillWidth: true
      text: section.title
      foreground: root.dim
      fontFamily: root.fontFamily
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: root.stripSpacing

      Repeater {
        id: strips
        delegate: StripColumn {
          isOutput: section.isOutput
          showRoutes: section.showRoutes
        }
      }
    }
  }

  // The rule between two sections. PanelSeparator is horizontal by
  // construction, and the top margin drops it below the section headings so it
  // divides the strips rather than the titles.
  component SectionRule: Rectangle {
    Layout.preferredWidth: 1
    Layout.fillHeight: true
    Layout.topMargin: Style.font.subtitle + Style.space(6)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
  }

  // One strip: name, meter and fader, mute, and (for channels) per-output
  // routing. Vertical, so strips sit side by side the way a mixer's do.
  component StripColumn: ColumnLayout {
    id: strip

    required property var modelData
    property bool isOutput: false
    property bool showRoutes: false

    readonly property string stripId: strip.modelData.id
    readonly property string stripLabel: strip.modelData.label || strip.stripId
    readonly property real level: {
      var store = strip.isOutput ? mixer.outputVolumes : mixer.volumes
      return store[strip.stripId] !== undefined ? store[strip.stripId] : 0
    }
    readonly property bool muted: strip.isOutput
      ? !!mixer.outputMutes[strip.stripId]
      : !!mixer.mutes[strip.stripId]
    readonly property var routeState: mixer.routes[strip.stripId] || ({})

    // Where this strip's audible signal lives. For a channel or input that is
    // the loopback's output side, which carries the post-volume signal; for a
    // physical output it is the device itself.
    readonly property string meterNodeName: {
      if (strip.isOutput) {
        var port = String(strip.modelData.port_l || "")
        return port.indexOf(":") > 0 ? port.split(":")[0] : ""
      }
      var sink = strip.modelData.target_sink || strip.modelData.sink
      return sink ? String(sink) + "_out" : ""
    }
    readonly property var meterNode: mixer.nodeNamed(strip.meterNodeName)

    spacing: Style.space(3)
    // Pinned at all three bounds: a routing button with a long label would
    // otherwise raise the strip's minimum width and quietly outgrow the panel
    // width computed above.
    Layout.minimumWidth: root.stripWidth
    Layout.preferredWidth: root.stripWidth
    Layout.maximumWidth: root.stripWidth
    Layout.alignment: Qt.AlignTop

    // What the meter should show: what you can actually hear.
    //
    // A channel or input is metered on its loopback output, which is already
    // past the strip's fader. A physical output is metered on the device node,
    // which is *before* the device volume - so an output turned down to zero
    // would otherwise show a full signal it is not playing. Attenuate by the
    // same cubic curve PipeWire uses for volume.
    readonly property real meterPeak: {
      if (strip.muted) return 0
      var raw = peakMonitor.peak || 0
      if (!strip.isOutput) return raw
      var fraction = Math.max(0, Math.min(100, strip.level)) / 100
      return raw * fraction * fraction * fraction
    }

    // Node properties are only valid while the node is bound.
    PwObjectTracker { objects: strip.meterNode ? [strip.meterNode] : [] }

    PwNodePeakMonitor {
      id: peakMonitor
      node: strip.meterNode
      // Metering costs real work, so only while the panel is actually on screen.
      enabled: root.popupOpen && strip.meterNode !== null
    }

    Text {
      Layout.fillWidth: true
      text: strip.stripLabel
      color: strip.muted ? root.dim : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      horizontalAlignment: Text.AlignHCenter
      elide: Text.ElideRight
    }

    RowLayout {
      Layout.alignment: Qt.AlignHCenter
      spacing: Style.space(4)

      LevelColumn {
        Layout.preferredWidth: Style.space(5)
        Layout.preferredHeight: root.faderHeight
        level: mixer.peakToLevel(strip.meterPeak)
      }

      // PanelSlider is horizontal by construction; a quarter turn gives a
      // fader without reimplementing the shell's slider, and keeps its
      // styling, wheel handling and knob animation. Mouse positions arrive in
      // the slider's own unrotated frame, so its drag maths still measures
      // along the track.
      Item {
        Layout.preferredWidth: fader.implicitHeight
        Layout.preferredHeight: root.faderHeight

        PanelSlider {
          id: fader
          width: parent.height
          height: parent.width
          anchors.centerIn: parent
          rotation: -90
          bar: root.bar
          enabled: !mixer.volumeLocked
          opacity: mixer.volumeLocked ? 0.45 : 1.0
          minimum: 0
          maximum: 100
          step: 2
          integer: true
          // While dragging the slider is the truth; otherwise follow the daemon,
          // so the MIDI board and the mixer window move it too.
          value: dragging ? liveValue : strip.level
          fillColor: strip.muted ? root.dim : root.foreground
          onMoved: function(value) { mixer.queueVolume(strip.stripId, value, strip.isOutput) }
          onReleased: function(value) { mixer.queueVolume(strip.stripId, value, strip.isOutput) }
        }
      }
    }

    Button {
      Layout.alignment: Qt.AlignHCenter
      // md-volume_mute (U+F075F) / md-volume_high (U+F057E).
      iconText: strip.muted ? "󰝟" : "󰕾"
      iconSize: Style.font.body
      horizontalPadding: Style.space(5)
      foreground: strip.muted ? root.urgent : root.foreground
      fontFamily: root.fontFamily
      tooltipText: strip.muted ? "Unmute" : "Mute"
      onClicked: {
        if (strip.isOutput) mixer.toggleOutputMute(strip.stripId)
        else mixer.toggleMute(strip.stripId)
      }
    }

    Repeater {
      model: strip.showRoutes ? mixer.outputs : []
      delegate: Button {
        required property var modelData
        Layout.fillWidth: true
        // Free to shrink to the strip, and clipped rather than overflowing
        // into the neighbouring channel when the label is too long for it.
        Layout.minimumWidth: 0
        clip: true
        text: modelData.label || modelData.id
        fontSize: Style.font.caption
        horizontalPadding: Style.space(4)
        verticalPadding: Style.space(2)
        bordered: true
        active: !!strip.routeState[modelData.id]
        foreground: strip.routeState[modelData.id] ? root.foreground : root.dim
        fontFamily: root.fontFamily
        tooltipText: "Route " + strip.stripLabel + " to " + text
        onClicked: mixer.toggleRoute(strip.stripId, modelData.id)
      }
    }
  }
}
