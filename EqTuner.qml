import QtQuick
import QtQuick.Layouts
import Quickshell.Io
import qs.Commons
import qs.Ui
import "EqMath.js" as EqMath

// A channel's parametric EQ: the response curve with draggable bands, a live
// spectrum of what the channel is playing, presets, and every band's numbers.
//
// An overlay inside the mixer window like the strip settings, but nearly the
// size of it - an EQ is read from its curve, and a small curve is a guess.
//
// Edits go to a local copy first and are drawn from it, so a dragged band
// follows the pointer at frame rate; the daemon is sent the newest copy at
// its own pace and applies it live. Only switching a band's type, a band on
// or off, or bypassing the EQ restarts the channel's chain.
Item {
  id: root

  required property var model
  // The spectrum helper, daemon/spectrum.py. Given by the window, which knows
  // where the plugin lives.
  property string spectrumScript: ""

  // The strip being tuned: a channel or an input. Ids are unique across
  // kinds, so the id alone says which.
  property string chanId: ""
  readonly property bool open: root.chanId !== ""
  readonly property bool isInput: root.open && !!root.model.entityFor("input", root.chanId)
  readonly property var channel: root.open
    ? (root.model.entityFor("channel", root.chanId) || root.model.entityFor("input", root.chanId)) : null
  readonly property string channelLabel: root.channel ? String(root.channel.label || root.chanId) : ""
  // Channels have colours of their own; inputs use the theme's accent, as on
  // their cards.
  readonly property color accent: root.open && !root.isInput
    ? root.model.accentFor(root.model.channelIndex(root.chanId)) : Color.accent
  // The sink the spectrum listens to. A channel's sink carries its audio
  // before the EQ; an input's carries it after everything - effects and EQ -
  // because the chain plays into it. That is what an app recording the
  // input receives, so it is the honest thing to show, and the "before" is
  // worked back from it instead.
  //
  // Read from the strip itself - an input has target_sink, a channel sink -
  // not via isInput: the two bindings update in no particular order, and the
  // helper was once started with whichever answer came first.
  readonly property string spectrumSink: root.channel
    ? String(root.channel.target_sink || root.channel.sink || "") : ""
  readonly property bool spectrumIsAfter: root.isInput

  // The EQ being edited, and a counter bumped on every change so bindings
  // and the canvas know to look again - a JS object mutated in place does not
  // announce itself.
  property var working: ({ enabled: false, preamp: 0, bands: [] })
  property int revision: 0
  property int selected: 0
  property int hovered: -1
  property bool dragging: false

  // The graph's gain scale, ±dB. Picked with the range buttons; widened
  // automatically - but only once a drag has ended - if a band falls outside.
  property real viewRange: 12

  function neededRange() {
    var widest = 0
    for (var i = 0; i < root.bands.length; i++)
      if ((root.catalogue.gainTypes || []).indexOf(root.bands[i].type) !== -1)
        widest = Math.max(widest, Math.abs(root.bands[i].gain))
    for (var k = 0; k < root.shape.length; k++)
      widest = Math.max(widest, Math.abs(root.shape[k]))
    return widest
  }

  function fitRange() {
    if (root.dragging) return
    var need = root.neededRange()
    // Pinned at the edge counts as wanting more: a band dragged to the top
    // of a ±12 view ends at +12, and the wider view lets it carry on.
    if (need >= root.viewRange - 0.05 && root.viewRange < 24)
      root.viewRange = need >= 11.95 ? 24 : 12
  }

  property bool spectrumOn: true
  // Music and speech fall off steeply towards the treble; tilting the display
  // by 3 dB per octave around 1 kHz makes a balanced mix read as level.
  property bool spectrumTilt: true
  property var spectrumFreqs: []
  property var spectrumLevels: []
  property string spectrumError: ""

  property bool savingPreset: false

  readonly property var catalogue: root.model.eqCatalogue
  readonly property var limits: root.catalogue.limits || ({})
  readonly property int maxBands: root.catalogue.maxBands || 10
  // Read through these, never root.working directly, in any binding: the
  // working copy is edited in place, so a binding on it would never update.
  readonly property bool eqOn: { root.revision; return root.working.enabled === true }
  readonly property real preamp: { root.revision; return Number(root.working.preamp || 0) }
  readonly property var bands: { root.revision; return root.working.bands || [] }
  readonly property var band: { root.revision; return root.bands[root.selected] || null }
  readonly property bool bandHasGain: !!root.band
    && (root.catalogue.gainTypes || []).indexOf(root.band.type) !== -1

  readonly property var typeLabels: ({
    peaking: "Bell", lowshelf: "Low shelf", highshelf: "High shelf",
    highpass: "Low cut (high-pass)", lowpass: "High cut (low-pass)",
    notch: "Notch", bandpass: "Band-pass"
  })

  // The curve, sampled for drawing, and its peak - for the clipping warning
  // and for Auto preamp.
  readonly property var curveFreqs: EqMath.logFreqs(220)
  readonly property var curve: { root.revision; return EqMath.responseDb(root.working, root.curveFreqs) }
  // The shape the bands make, without the preamp: what the handles sit on.
  readonly property var shape: {
    root.revision
    return EqMath.responseDb({ preamp: 0, bands: root.working.bands }, root.curveFreqs)
  }
  readonly property real curvePeak: {
    var peak = -999
    for (var i = 0; i < root.curve.length; i++) peak = Math.max(peak, root.curve[i])
    return peak
  }

  // Which preset the EQ matches, if any, so the picker can say so.
  readonly property string currentPreset: {
    root.revision
    var all = root.model.eqBuiltinPresets.concat(root.model.eqUserPresets)
    for (var i = 0; i < all.length; i++)
      if (root.matches(all[i])) return String(all[i].id)
    return ""
  }
  readonly property bool currentIsUser: root.currentPreset.indexOf("user_") === 0

  readonly property var presetOptions: {
    var options = []
    if (root.currentPreset === "") options.push({ value: "", label: "Custom" })
    for (var i = 0; i < root.model.eqBuiltinPresets.length; i++)
      options.push({ value: String(root.model.eqBuiltinPresets[i].id), label: String(root.model.eqBuiltinPresets[i].label) })
    for (var j = 0; j < root.model.eqUserPresets.length; j++)
      options.push({ value: String(root.model.eqUserPresets[j].id), label: "★ " + String(root.model.eqUserPresets[j].label) })
    return options
  }

  // -------------------------------------------------------------- actions

  function show(chanId) {
    root.chanId = String(chanId)
    root.working = root.model.eqFor(root.chanId)
    root.selected = 0
    root.hovered = -1
    root.savingPreset = false
    root.spectrumLevels = []
    root.revision++
    var need = root.neededRange()
    root.viewRange = need > 12 ? 24 : 12
  }

  function close() {
    root.chanId = ""
    root.savingPreset = false
  }

  function changed() {
    root.revision++
    root.model.setEq(root.chanId, root.working)
    root.fitRange()
  }

  function matches(preset) {
    var mine = root.working.bands || []
    var theirs = preset.bands || []
    if (mine.length !== theirs.length) return false
    if (Math.abs(Number(root.working.preamp || 0) - Number(preset.preamp || 0)) > 0.05) return false
    for (var i = 0; i < mine.length; i++) {
      var a = mine[i], b = theirs[i]
      if (a.type !== b.type || (a.enabled !== false) !== (b.enabled !== false)) return false
      if (Math.abs(a.freq - b.freq) > 0.5 || Math.abs(a.gain - b.gain) > 0.05
          || Math.abs(a.q - b.q) > 0.005) return false
    }
    return true
  }

  function applyPreset(id) {
    var all = root.model.eqBuiltinPresets.concat(root.model.eqUserPresets)
    for (var i = 0; i < all.length; i++) {
      if (String(all[i].id) !== String(id)) continue
      root.working.bands = JSON.parse(JSON.stringify(all[i].bands))
      root.working.preamp = Number(all[i].preamp || 0)
      root.working.enabled = true
      root.selected = 0
      root.changed()
      return
    }
  }

  function clampTo(key, value) {
    var range = root.limits[key] || [-1e9, 1e9]
    return Math.max(range[0], Math.min(range[1], value))
  }

  function setBand(index, key, value) {
    var target = root.working.bands[index]
    if (!target) return
    if (key === "freq" || key === "gain" || key === "q") value = root.clampTo(key, Number(value))
    target[key] = value
    if (!root.working.enabled) root.working.enabled = true
    root.changed()
  }

  function addBand(freq, gain) {
    if (root.working.bands.length >= root.maxBands) return
    root.working.bands.push({
      type: "peaking", freq: root.clampTo("freq", Math.round(freq)), gain: root.clampTo("gain", gain || 0),
      q: 1.0, enabled: true
    })
    root.working.enabled = true
    root.selected = root.working.bands.length - 1
    root.changed()
  }

  function removeBand(index) {
    root.working.bands.splice(index, 1)
    root.selected = Math.max(0, Math.min(root.selected, root.working.bands.length - 1))
    root.changed()
  }

  // A preamp that brings the loudest point of the curve to 0 dB, so boosts
  // cannot clip.
  function autoPreamp() {
    var withoutPreamp = root.curvePeak - Number(root.working.preamp || 0)
    root.working.preamp = root.clampTo("preamp", Math.min(0, -withoutPreamp))
    root.changed()
  }

  // Makes a shell Dropdown open its list above itself when there is not room
  // below. The Dropdown offers no such option, so its popup is found among its
  // children and repositioned each time it is about to show.
  function findPopup(object) {
    var lists = [object.data || [], object.children || []]
    for (var l = 0; l < lists.length; l++) {
      for (var i = 0; i < lists[l].length; i++) {
        var child = lists[l][i]
        if (!child) continue
        if (child.toString().indexOf("Popup") !== -1 && child.aboutToShow !== undefined) return child
        var found = root.findPopup(child)
        if (found) return found
      }
    }
    return null
  }

  function opensUpwardsWhenCramped(dropdown) {
    var popup = root.findPopup(dropdown)
    if (!popup) return
    var below = popup.y
    popup.aboutToShow.connect(function () {
      var anchor = popup.parent
      var bottom = anchor.mapToItem(root, 0, below).y + popup.implicitHeight
      popup.y = bottom > root.height - Style.space(8)
        ? -popup.implicitHeight - Style.spacing.xxs
        : below
    })
  }

  function bandColor(index) {
    return Qt.hsla(((index * 0.13) + 0.55) % 1, 0.62, root.model.darkTheme ? 0.66 : 0.42, 1)
  }

  // -------------------------------------------------------------- spectrum

  Process {
    id: spectrum
    running: root.spectrumWanted
    command: ["python3", "-B", root.spectrumScript, root.spectrumSink, "120", "30"]
    // A helper that dies straight away is almost always numpy missing; say
    // so instead of leaving an empty graph.
    stderr: StdioCollector { id: spectrumErrors; waitForEnd: true }
    onRunningChanged: if (running) root.spectrumError = ""
    onExited: function (exitCode) {
      if (exitCode !== 0 && root.open && root.spectrumOn) {
        var text = String(spectrumErrors.text || "")
        root.spectrumError = text.indexOf("numpy") !== -1
          ? "The spectrum needs python-numpy: sudo pacman -S python-numpy"
          : "The spectrum stopped: " + (text.trim().split("\n").pop() || "exit " + exitCode)
      }
    }
    stdout: SplitParser {
      onRead: function (line) {
        if (line.indexOf("F ") === 0) {
          root.spectrumFreqs = line.substring(2).split(" ").map(Number)
        } else if (line.indexOf("S ") === 0) {
          root.spectrumLevels = line.substring(2).split(" ").map(Number)
          graph.requestPaint()
        }
      }
    }
  }

  // A running Process does not pick up a new command, so a change of sink
  // (another strip opened while this one's spectrum runs) restarts it.
  onSpectrumSinkChanged: {
    root.spectrumLevels = []
    if (spectrum.running) {
      spectrum.running = false
      Qt.callLater(function () { spectrum.running = Qt.binding(function () { return root.spectrumWanted }) })
    }
  }
  readonly property bool spectrumWanted: root.open && root.spectrumOn
    && root.spectrumScript !== "" && root.spectrumSink !== ""

  onRevisionChanged: graph.requestPaint()
  onHoveredChanged: graph.requestPaint()
  onSelectedChanged: graph.requestPaint()
  onSpectrumOnChanged: { root.spectrumLevels = []; graph.requestPaint() }
  onViewRangeChanged: graph.requestPaint()

  // ---------------------------------------------------------------- frame

  visible: root.open
  anchors.fill: parent

  MouseArea {
    anchors.fill: parent
    onClicked: root.close()
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.7)
  }

  Rectangle {
    id: card
    anchors.fill: parent
    anchors.margins: Style.space(18)
    radius: Math.round(Style.space(12))
    color: Color.popups.background
    border.width: 1
    border.color: Util.alpha(Color.foreground, 0.14)

    MouseArea { anchors.fill: parent }

    ColumnLayout {
      anchors.fill: parent
      anchors.margins: Style.space(16)
      spacing: Style.space(10)

      // ---------------------------------------------------------- header

      RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: false
        spacing: Style.space(8)

        Rectangle {
          Layout.preferredWidth: Math.max(3, Style.space(3))
          Layout.preferredHeight: title.implicitHeight
          radius: width / 2
          color: root.accent
        }

        Text {
          id: title
          text: "EQ · " + root.channelLabel
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        Button {
          text: root.eqOn ? "On" : "Bypassed"
          // md-power (U+F0425)
          iconText: "\u{f0425}"
          iconSize: Style.font.bodySmall
          fontSize: Style.font.bodySmall
          bordered: true
          active: root.eqOn
          foreground: root.eqOn ? root.accent : Util.alpha(Color.foreground, 0.55)
          fontFamily: Style.font.family
          tooltipText: root.eqOn
            ? "Bypass the EQ to compare (briefly interrupts " + root.channelLabel + ")"
            : "Switch the EQ on"
          onClicked: { root.working.enabled = !root.eqOn; root.changed() }
        }

        Item { Layout.fillWidth: true }

        Text {
          text: "Preset"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Dropdown {
          Layout.preferredWidth: Style.space(190)
          showLabel: false
          options: root.presetOptions
          value: root.currentPreset
          fontFamily: Style.font.family
          onChanged: function (value) { if (value !== "" && value !== root.currentPreset) root.applyPreset(value) }
        }

        Button {
          visible: !root.savingPreset
          text: "Save preset"
          // md-content_save (U+F0193)
          iconText: "\u{f0193}"
          iconSize: Style.font.bodySmall
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: Color.foreground
          fontFamily: Style.font.family
          tooltipText: "Keep this EQ as a preset of your own"
          onClicked: {
            root.savingPreset = true
            presetName.text = root.channelLabel + " EQ"
            presetName.selectAll()
            presetName.forceActiveFocus()
          }
        }

        TextField {
          id: presetName
          visible: root.savingPreset
          Layout.preferredWidth: Style.space(170)
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          onAccepted: savePreset.apply()
        }

        Button {
          id: savePreset
          visible: root.savingPreset
          text: "Save"
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: root.accent
          fontFamily: Style.font.family
          function apply() {
            var name = presetName.text.trim()
            if (name === "") return
            root.model.saveEqPreset(name, root.working)
            root.savingPreset = false
          }
          onClicked: apply()
        }

        Button {
          visible: root.savingPreset
          text: "Cancel"
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: Util.alpha(Color.foreground, 0.6)
          fontFamily: Style.font.family
          onClicked: root.savingPreset = false
        }

        Button {
          visible: root.currentIsUser && !root.savingPreset
          // md-delete (U+F01B4)
          iconText: "\u{f01b4}"
          iconSize: Style.font.bodySmall
          horizontalPadding: Style.space(5)
          bordered: true
          foreground: Color.urgent
          fontFamily: Style.font.family
          tooltipText: "Delete this preset"
          onClicked: root.model.removeEqPreset(root.currentPreset)
        }

        Button {
          text: "Reset"
          // md-restore (U+F099B)
          iconText: "\u{f099b}"
          iconSize: Style.font.bodySmall
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: Util.alpha(Color.foreground, 0.7)
          fontFamily: Style.font.family
          tooltipText: "Back to flat"
          onClicked: {
            root.working.bands = root.model.flatBands()
            root.working.preamp = 0
            root.selected = 0
            root.changed()
          }
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

      // ----------------------------------------------------------- graph

      Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: Style.space(200)
        radius: Math.round(Style.space(8))
        color: Util.alpha(Color.foreground, 0.035)
        border.width: 1
        border.color: Util.alpha(Color.foreground, 0.08)
        clip: true

        Canvas {
          id: graph
          anchors.fill: parent
          anchors.margins: 1
          renderTarget: Canvas.FramebufferObject

          // Plot area inside the axis labels.
          readonly property real padLeft: Style.space(34)
          readonly property real padRight: Style.space(38)
          readonly property real padTop: Style.space(10)
          readonly property real padBottom: Style.space(20)
          readonly property real plotW: width - padLeft - padRight
          readonly property real plotH: height - padTop - padBottom
          // EQ gain range; widens when a band needs it.
          // The gain scale. Chosen with the range buttons, and never changed
          // while a band is being dragged: the pointer is turned into a gain
          // through this scale, so a scale that moved mid-drag made the band
          // under the pointer jump with it.
          readonly property real dbRange: root.viewRange

          function xOf(freq) { return padLeft + EqMath.freqToX(freq, plotW) }
          function freqAt(x) { return EqMath.xToFreq(x - padLeft, plotW) }
          function yOfGain(db) { return padTop + plotH * (0.5 - db / (2 * dbRange)) }
          function gainAt(y) { return (0.5 - (y - padTop) / plotH) * 2 * dbRange }
          // The spectrum has a scale of its own: dBFS, not EQ gain.
          function yOfLevel(db) { return padTop + plotH * Math.min(1, Math.max(0, -db / 90)) }

          function handlePos(index) {
            var b = root.bands[index]
            var hasGain = (root.catalogue.gainTypes || []).indexOf(b.type) !== -1
            // Cut, notch and band-pass bands sit on the curve itself; their
            // gain is not a thing you can drag.
            var y = hasGain ? b.gain : EqMath.responseDb({ preamp: 0, bands: root.working.bands }, [b.freq])[0]
            return { x: xOf(b.freq), y: yOfGain(Math.max(-dbRange, Math.min(dbRange, y))) }
          }

          function bandAt(x, y) {
            var best = -1, bestDist = Style.space(14)
            for (var i = 0; i < root.bands.length; i++) {
              var p = handlePos(i)
              var d = Math.sqrt((p.x - x) * (p.x - x) + (p.y - y) * (p.y - y))
              if (d < bestDist) { best = i; bestDist = d }
            }
            return best
          }

          onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var fg = Color.foreground
            var rgba = function (c, a) { return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + a + ")" }
            ctx.font = Math.round(Style.font.caption * 0.95) + "px '" + Style.font.family + "'"

            // Grid: decades and their 2s and 5s, and every 6 dB.
            var gridFreqs = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
            ctx.lineWidth = 1
            for (var g = 0; g < gridFreqs.length; g++) {
              var gx = Math.round(xOf(gridFreqs[g])) + 0.5
              ctx.strokeStyle = rgba(fg, gridFreqs[g] === 1000 || gridFreqs[g] === 100 || gridFreqs[g] === 10000 ? 0.12 : 0.06)
              ctx.beginPath(); ctx.moveTo(gx, padTop); ctx.lineTo(gx, padTop + plotH); ctx.stroke()
              ctx.fillStyle = rgba(fg, 0.45)
              var label = gridFreqs[g] >= 1000 ? (gridFreqs[g] / 1000) + "k" : String(gridFreqs[g])
              ctx.textAlign = g === 0 ? "left" : (g === gridFreqs.length - 1 ? "right" : "center")
              ctx.fillText(label, gx, height - Style.space(5))
            }
            var step = dbRange > 12 ? 6 : (dbRange > 6 ? 3 : 2)
            ctx.textAlign = "right"
            for (var db = -dbRange; db <= dbRange + 0.01; db += step) {
              var gy = Math.round(yOfGain(db)) + 0.5
              ctx.strokeStyle = rgba(fg, db === 0 ? 0.2 : 0.06)
              ctx.beginPath(); ctx.moveTo(padLeft, gy); ctx.lineTo(padLeft + plotW, gy); ctx.stroke()
              ctx.fillStyle = rgba(fg, 0.45)
              ctx.fillText((db > 0 ? "+" : "") + db, padLeft - Style.space(5), gy + Style.space(4))
            }

            // The spectrum's own scale, on the right, in dBFS.
            if (root.spectrumOn) {
              ctx.textAlign = "left"
              ctx.fillStyle = rgba(fg, 0.3)
              for (var lv = 0; lv >= -90; lv -= 30)
                ctx.fillText(String(lv), padLeft + plotW + Style.space(4),
                             Math.max(padTop + Style.space(8), Math.min(padTop + plotH, yOfLevel(lv) + Style.space(4))))
            }

            // Spectrum: what the channel plays (grey), and that through the
            // EQ (in the channel's colour) - the curve added to it.
            var levels = root.spectrumLevels
            var sf = root.spectrumFreqs
            if (root.spectrumOn && levels.length > 0 && levels.length === sf.length) {
              var through = root.working.enabled ? EqMath.responseDb(root.working, sf) : null
              // Silence stays on the floor rather than being tilted up off it.
              var tilt = function (f, level) {
                return root.spectrumTilt && level > -99 ? 3 * Math.log(f / 1000) / Math.LN2 : 0
              }
              // A channel is captured before its EQ and an input after it;
              // either way the other side is the capture plus or minus the
              // curve, since an EQ is exactly that change.
              var before = [], after = []
              for (var k = 0; k < sf.length; k++) {
                var shift = through ? through[k] : 0
                // Working back from silence would invent sound: where a cut
                // has pushed the capture to the floor, "before" is unknown
                // rather than the floor plus the cut, so it stays there too.
                before.push(root.spectrumIsAfter
                  ? (levels[k] > -95 ? levels[k] - shift : levels[k]) : levels[k])
                after.push(root.spectrumIsAfter ? levels[k] : levels[k] + shift)
              }
              ctx.beginPath()
              ctx.moveTo(xOf(sf[0]), padTop + plotH)
              for (var s = 0; s < sf.length; s++) ctx.lineTo(xOf(sf[s]), yOfLevel(before[s] + tilt(sf[s], levels[s])))
              ctx.lineTo(xOf(sf[sf.length - 1]), padTop + plotH)
              ctx.closePath()
              ctx.fillStyle = rgba(fg, 0.08)
              ctx.fill()
              if (through) {
                ctx.beginPath()
                for (var o = 0; o < sf.length; o++) {
                  var oy = yOfLevel(after[o] + tilt(sf[o], levels[o]))
                  if (o === 0) ctx.moveTo(xOf(sf[o]), oy); else ctx.lineTo(xOf(sf[o]), oy)
                }
                ctx.strokeStyle = rgba(root.accent, 0.55)
                ctx.lineWidth = 1.25
                ctx.stroke()
              }
            }

            var freqs = root.curveFreqs

            // Each band's own curve, the selected one filled.
            for (var b = 0; b < root.bands.length; b++) {
              var band = root.bands[b]
              if (band.enabled === false) continue
              var coeffs = EqMath.coefficients(band)
              ctx.beginPath()
              for (var i = 0; i < freqs.length; i++) {
                var by = yOfGain(Math.max(-dbRange * 1.5, EqMath.magnitudeDb(coeffs, freqs[i])))
                if (i === 0) ctx.moveTo(xOf(freqs[i]), by); else ctx.lineTo(xOf(freqs[i]), by)
              }
              var colour = root.bandColor(b)
              if (b === root.selected) {
                ctx.lineTo(xOf(freqs[freqs.length - 1]), yOfGain(0))
                ctx.lineTo(xOf(freqs[0]), yOfGain(0))
                ctx.closePath()
                ctx.fillStyle = rgba(colour, 0.14)
                ctx.fill()
              }
              ctx.strokeStyle = rgba(colour, b === root.selected ? 0.75 : 0.35)
              ctx.lineWidth = 1
              ctx.stroke()
            }

            // With the preamp, thin and dashed: what actually comes out.
            if (Math.abs(Number(root.working.preamp || 0)) > 0.05) {
              ctx.beginPath()
              for (var pc = 0; pc < freqs.length; pc++) {
                var py = yOfGain(Math.max(-dbRange * 1.5, Math.min(dbRange * 1.5, root.curve[pc])))
                if (pc === 0) ctx.moveTo(xOf(freqs[pc]), py); else ctx.lineTo(xOf(freqs[pc]), py)
              }
              ctx.setLineDash([4, 4])
              ctx.strokeStyle = rgba(root.working.enabled ? root.accent : fg, 0.5)
              ctx.lineWidth = 1.25
              ctx.stroke()
              ctx.setLineDash([])
            }

            // The shape the bands make together.
            ctx.beginPath()
            for (var c = 0; c < freqs.length; c++) {
              var cy = yOfGain(Math.max(-dbRange * 1.5, Math.min(dbRange * 1.5, root.shape[c])))
              if (c === 0) ctx.moveTo(xOf(freqs[c]), cy); else ctx.lineTo(xOf(freqs[c]), cy)
            }
            ctx.strokeStyle = root.working.enabled ? rgba(root.accent, 1) : rgba(fg, 0.35)
            ctx.lineWidth = 2.5
            ctx.stroke()

            // Handles, numbered.
            ctx.textAlign = "center"
            for (var h = 0; h < root.bands.length; h++) {
              var p = handlePos(h)
              var on = root.bands[h].enabled !== false
              var r = Style.space(h === root.selected ? 9 : 8)
              ctx.beginPath()
              ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
              ctx.fillStyle = on ? rgba(root.bandColor(h), h === root.selected || h === root.hovered ? 1 : 0.8) : rgba(fg, 0.15)
              ctx.fill()
              ctx.lineWidth = h === root.selected ? 2 : 1
              ctx.strokeStyle = h === root.selected ? rgba(fg, 0.9) : rgba(Color.background, 0.8)
              ctx.stroke()
              ctx.fillStyle = on ? rgba(Color.background, 0.95) : rgba(fg, 0.6)
              ctx.fillText(String(h + 1), p.x, p.y + Style.space(4))
            }
          }

          MouseArea {
            id: pointer
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: root.hovered >= 0 ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.CrossCursor

            onPressed: function (mouse) { graph.press(mouse.x, mouse.y, mouse.button === Qt.RightButton) }
            onReleased: graph.release()
            onDoubleClicked: function (mouse) { graph.doubleClick(mouse.x, mouse.y) }
            onPositionChanged: function (mouse) { graph.move(mouse.x, mouse.y) }
            onExited: { root.hovered = -1; readout.freq = 0 }
            onWheel: function (wheel) { graph.wheel(wheel.angleDelta.y) }
          }

          // Pointer handling, in plot coordinates. Kept out of the MouseArea
          // so it reads as what it does, not as event plumbing.
          property int dragIndex: -1

          function press(x, y, secondary) {
            var hit = bandAt(x, y)
            if (secondary) {
              // Right-click a band to switch it on or off.
              if (hit >= 0) root.setBand(hit, "enabled", root.bands[hit].enabled === false)
              return
            }
            if (hit >= 0) {
              root.selected = hit
              dragIndex = hit
              root.dragging = true
              // Where on the handle it was grabbed, so the band keeps that
              // offset rather than snapping its centre to the pointer.
              var p = handlePos(hit)
              grabDx = x - p.x
              grabDy = y - p.y
            }
          }

          property real grabDx: 0
          property real grabDy: 0

          function release() {
            dragIndex = -1
            root.dragging = false
            root.fitRange()
          }

          function doubleClick(x, y) {
            if (bandAt(x, y) < 0)
              root.addBand(freqAt(x), Math.round(gainAt(y) * 2) / 2)
          }

          function move(x, y) {
            if (dragIndex < 0) {
              root.hovered = bandAt(x, y)
              readout.freq = freqAt(x)
              return
            }
            var b = root.bands[dragIndex]
            var fx = Math.max(padLeft, Math.min(padLeft + plotW, x - grabDx))
            var fy = Math.max(padTop, Math.min(padTop + plotH, y - grabDy))
            b.freq = root.clampTo("freq", Math.round(freqAt(fx)))
            if ((root.catalogue.gainTypes || []).indexOf(b.type) !== -1)
              b.gain = root.clampTo("gain", Math.round(gainAt(fy) * 10) / 10)
            root.changed()
          }

          // The wheel sets the width (Q) of the band under the pointer, or
          // the selected one.
          function wheel(delta) {
            var target = root.hovered >= 0 ? root.hovered : root.selected
            var b = root.bands[target]
            if (!b) return
            root.selected = target
            b.q = root.clampTo("q", Math.round(b.q * Math.pow(1.12, delta / 120) * 100) / 100)
            root.changed()
          }

          Text {
            visible: root.spectrumError !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: graph.padBottom + Style.space(8)
            text: root.spectrumError
            color: Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          // What the pointer is over, top left of the plot.
          Text {
            id: readout
            property real freq: 0
            readonly property var focusBand: root.dragging || root.hovered >= 0
              ? root.bands[root.dragging ? root.selected : root.hovered] : null
            x: graph.padLeft + Style.space(8)
            y: graph.padTop + Style.space(4)
            text: {
              root.revision
              if (focusBand)
                return (root.typeLabels[focusBand.type] || focusBand.type) + "  " + EqMath.formatFreq(focusBand.freq)
                  + "  " + EqMath.formatGain(focusBand.gain) + "  Q " + focusBand.q.toFixed(2)
              return freq > 0 ? EqMath.formatFreq(freq) : ""
            }
            color: Util.alpha(Color.foreground, 0.75)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: graph.padRight + Style.space(6)
            anchors.topMargin: graph.padTop + Style.space(4)
            horizontalAlignment: Text.AlignRight
            text: "Drag a band · scroll for width · right-click on/off · double-click to add"
            color: Util.alpha(Color.foreground, 0.35)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }
      }

      // ------------------------------------------------------------ bands

      RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: false
        spacing: Style.space(6)

        Text {
          text: "Bands"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Repeater {
          model: { root.revision; return root.bands.length }
          delegate: Button {
            required property int index
            readonly property bool on: !!root.bands[index] && root.bands[index].enabled !== false
            text: String(index + 1)
            fontSize: Style.font.bodySmall
            horizontalPadding: Style.space(8)
            verticalPadding: Style.space(3)
            bordered: true
            active: index === root.selected
            foreground: on ? root.bandColor(index) : Util.alpha(Color.foreground, 0.35)
            fontFamily: Style.font.family
            tooltipText: {
              root.revision
              var b = root.bands[index]
              return b ? (root.typeLabels[b.type] || b.type) + " · " + EqMath.formatFreq(b.freq) : ""
            }
            onClicked: root.selected = index
          }
        }

        Button {
          visible: root.bands.length < root.maxBands
          text: "Add band"
          // md-plus (U+F0415)
          iconText: "\u{f0415}"
          iconSize: Style.font.bodySmall
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: Color.foreground
          fontFamily: Style.font.family
          onClicked: {
            // Into the widest gap between existing bands, so it does not land
            // on top of one.
            var fs = root.bands.map(function (b) { return b.freq }).concat([20, 20000]).sort(function (a, b) { return a - b })
            var best = 1000, gap = 0
            for (var i = 1; i < fs.length; i++) {
              var g = Math.log(fs[i] / fs[i - 1])
              if (g > gap) { gap = g; best = Math.sqrt(fs[i] * fs[i - 1]) }
            }
            root.addBand(Math.round(best), 0)
          }
        }

        Item { Layout.fillWidth: true }

        Text {
          text: "Range"
          color: Util.alpha(Color.foreground, 0.5)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Repeater {
          model: [6, 12, 24]
          delegate: Button {
            required property var modelData
            text: "±" + modelData
            fontSize: Style.font.bodySmall
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(3)
            bordered: true
            active: root.viewRange === modelData
            foreground: root.viewRange === modelData ? Color.foreground : Util.alpha(Color.foreground, 0.5)
            fontFamily: Style.font.family
            tooltipText: "Show ±" + modelData + " dB"
            onClicked: { root.viewRange = modelData; graph.requestPaint() }
          }
        }

        Item { Layout.preferredWidth: Style.space(8) }

        Button {
          text: "Spectrum"
          // md-chart_bar (U+F0128)
          iconText: "\u{f0128}"
          iconSize: Style.font.bodySmall
          fontSize: Style.font.bodySmall
          bordered: true
          active: root.spectrumOn
          foreground: root.spectrumOn ? root.accent : Util.alpha(Color.foreground, 0.55)
          fontFamily: Style.font.family
          tooltipText: "Show what " + root.channelLabel + " is playing: grey before the EQ, coloured after it"
          onClicked: root.spectrumOn = !root.spectrumOn
        }

        Button {
          visible: root.spectrumOn
          text: "Tilt"
          fontSize: Style.font.bodySmall
          bordered: true
          active: root.spectrumTilt
          foreground: root.spectrumTilt ? Color.foreground : Util.alpha(Color.foreground, 0.55)
          fontFamily: Style.font.family
          tooltipText: "Tilt the spectrum 3 dB per octave, so a balanced mix reads level"
          onClicked: { root.spectrumTilt = !root.spectrumTilt; graph.requestPaint() }
        }
      }

      // ---------------------------------------------------- band editor

      RowLayout {
        visible: !!root.band
        Layout.fillWidth: true
        Layout.fillHeight: false
        spacing: Style.space(10)

        Rectangle {
          Layout.preferredWidth: Style.space(10)
          Layout.preferredHeight: Style.space(10)
          radius: width / 2
          color: root.band && root.band.enabled !== false ? root.bandColor(root.selected) : Util.alpha(Color.foreground, 0.2)
        }

        Dropdown {
          id: typePicker
          Layout.preferredWidth: Style.space(200)
          showLabel: false
          options: (root.catalogue.types || []).map(function (t) { return { value: t, label: root.typeLabels[t] || t } })
          // This picker sits at the bottom of the window, and the shell's
          // dropdown always opens downwards, so its list ran off the edge.
          Component.onCompleted: root.opensUpwardsWhenCramped(typePicker)
          value: root.band ? String(root.band.type) : ""
          fontFamily: Style.font.family
          onChanged: function (value) { if (root.band && value !== root.band.type) root.setBand(root.selected, "type", value) }
        }

        Button {
          text: root.band && root.band.enabled !== false ? "On" : "Off"
          fontSize: Style.font.bodySmall
          bordered: true
          active: !!root.band && root.band.enabled !== false
          foreground: root.band && root.band.enabled !== false ? root.bandColor(root.selected) : Util.alpha(Color.foreground, 0.5)
          fontFamily: Style.font.family
          onClicked: root.setBand(root.selected, "enabled", root.band.enabled === false)
        }

        // Frequency, on a log scale: a linear slider would spend nine
        // tenths of its travel above 2 kHz.
        ValueSlider {
          Layout.fillWidth: true
          label: "Freq"
          position: root.band ? Math.log(root.band.freq / 20) / Math.log(1000) : 0
          display: root.band ? EqMath.formatFreq(root.band.freq) : ""
          editText: root.band ? String(Math.round(root.band.freq)) : ""
          onMoved: function (p) { root.setBand(root.selected, "freq", Math.round(20 * Math.pow(1000, p))) }
          onEdited: function (text) { var v = parseFloat(text); if (!isNaN(v)) root.setBand(root.selected, "freq", text.toLowerCase().indexOf("k") > 0 ? v * 1000 : v) }
        }

        ValueSlider {
          Layout.fillWidth: true
          enabled: root.bandHasGain
          opacity: root.bandHasGain ? 1 : 0.4
          label: "Gain"
          position: root.band ? (root.band.gain + 24) / 48 : 0.5
          display: root.band ? (root.bandHasGain ? EqMath.formatGain(root.band.gain) : "—") : ""
          editText: root.band ? root.band.gain.toFixed(1) : ""
          onMoved: function (p) { root.setBand(root.selected, "gain", Math.round((p * 48 - 24) * 10) / 10) }
          onEdited: function (text) { var v = parseFloat(text); if (!isNaN(v)) root.setBand(root.selected, "gain", v) }
        }

        ValueSlider {
          Layout.fillWidth: true
          label: root.band && (root.band.type === "lowshelf" || root.band.type === "highshelf") ? "Slope Q" : "Q"
          position: root.band ? Math.log(root.band.q / 0.1) / Math.log(180) : 0
          display: root.band ? root.band.q.toFixed(2) : ""
          editText: root.band ? root.band.q.toFixed(2) : ""
          onMoved: function (p) { root.setBand(root.selected, "q", Math.round(0.1 * Math.pow(180, p) * 100) / 100) }
          onEdited: function (text) { var v = parseFloat(text); if (!isNaN(v)) root.setBand(root.selected, "q", v) }
        }

        Button {
          // md-delete (U+F01B4)
          iconText: "\u{f01b4}"
          iconSize: Style.font.bodySmall
          horizontalPadding: Style.space(5)
          bordered: true
          foreground: Util.alpha(Color.urgent, 0.85)
          fontFamily: Style.font.family
          tooltipText: "Remove band " + (root.selected + 1)
          onClicked: root.removeBand(root.selected)
        }
      }

      // ---------------------------------------------------------- preamp

      RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: false
        spacing: Style.space(10)

        ValueSlider {
          // A fixed width: the message beside it changes length as the
          // preamp crosses into clipping, and a slider that shared the row
          // with it was resized mid-drag, moving the knob under the pointer.
          Layout.preferredWidth: Style.space(340)
          Layout.minimumWidth: Style.space(340)
          Layout.maximumWidth: Style.space(340)
          label: "Preamp"
          position: (root.preamp + 24) / 36
          display: EqMath.formatGain(root.preamp)
          editText: root.preamp.toFixed(1)
          onMoved: function (p) { root.working.preamp = Math.round((p * 36 - 24) * 10) / 10; root.changed() }
          onEdited: function (text) { var v = parseFloat(text); if (!isNaN(v)) { root.working.preamp = root.clampTo("preamp", v); root.changed() } }
        }

        Button {
          text: "Auto"
          fontSize: Style.font.bodySmall
          bordered: true
          foreground: Color.foreground
          fontFamily: Style.font.family
          tooltipText: "Lower the preamp so the curve's highest point is 0 dB - boosts can then never clip"
          onClicked: root.autoPreamp()
        }

        Text {
          Layout.fillWidth: true
          // Takes only what is left over, never more: see the slider above.
          Layout.preferredWidth: 0
          Layout.minimumWidth: 0
          text: root.eqOn && root.curvePeak > 0.5
            ? "Peaks at " + EqMath.formatGain(root.curvePeak) + " - loud material may clip. Lower the preamp or use Auto."
            : (root.eqOn ? "Highest point " + EqMath.formatGain(root.curvePeak) + " - no risk of clipping." : "EQ bypassed - " + root.channelLabel + " plays unchanged.")
          color: root.eqOn && root.curvePeak > 0.5 ? Color.urgent : Util.alpha(Color.foreground, 0.45)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }

  // A labelled slider with its value beside it, the value clickable to type
  // an exact number. Positions are 0-1; callers map them to their own scale.
  component ValueSlider: RowLayout {
    id: vs
    Layout.fillHeight: false
    property string label: ""
    property real position: 0
    property string display: ""
    property string editText: ""
    signal moved(real position)
    signal edited(string text)

    spacing: Style.space(6)

    Text {
      text: vs.label
      color: Util.alpha(Color.foreground, 0.6)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    PanelSlider {
      id: slider
      Layout.fillWidth: true
      minimum: 0
      maximum: 1
      step: 0.002
      value: dragging ? liveValue : Math.max(0, Math.min(1, vs.position))
      fillColor: root.accent
      onMoved: function (value) { vs.moved(value) }
      onReleased: function (value) { vs.moved(value) }
    }

    TextField {
      id: field
      Layout.preferredWidth: Style.space(78)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      horizontalAlignment: TextInput.AlignRight
      onActiveFocusChanged: if (activeFocus) { text = vs.editText; selectAll() }
      onAccepted: { vs.edited(text); focus = false }
    }

    // Follows the value except while being typed into.
    Binding {
      target: field
      property: "text"
      value: vs.display
      when: !field.activeFocus
      restoreMode: Binding.RestoreNone
    }
  }
}
