.pragma library

// Frequency response of the EQ, for drawing it.
//
// The same Robert Bristow-Johnson cookbook biquads as daemon/pipeworks/audio/eq.py,
// which are checked against the measured response of PipeWire's own builtin
// filters - so the curve on screen is what the chain actually does. Keep the
// two in step: a change to one is a change to both.

var RATE = 48000

function coefficients(band, rate) {
  rate = rate || RATE
  var f = Math.min(band.freq, rate * 0.499)
  var q = Math.max(band.q, 1e-4)
  var w0 = 2 * Math.PI * f / rate
  var cosw = Math.cos(w0), sinw = Math.sin(w0)
  var A = Math.pow(10, band.gain / 40)
  var alpha = sinw / (2 * q)
  var b0, b1, b2, a0, a1, a2
  switch (band.type) {
  case "peaking":
    b0 = 1 + alpha * A; b1 = -2 * cosw; b2 = 1 - alpha * A
    a0 = 1 + alpha / A; a1 = -2 * cosw; a2 = 1 - alpha / A
    break
  case "lowshelf":
  case "highshelf":
    // PipeWire treats a shelf's Q as a true Q (0.707 is the plain shelf).
    var k = 2 * Math.sqrt(A) * alpha
    if (band.type === "lowshelf") {
      b0 = A * ((A + 1) - (A - 1) * cosw + k); b1 = 2 * A * ((A - 1) - (A + 1) * cosw)
      b2 = A * ((A + 1) - (A - 1) * cosw - k)
      a0 = (A + 1) + (A - 1) * cosw + k; a1 = -2 * ((A - 1) + (A + 1) * cosw)
      a2 = (A + 1) + (A - 1) * cosw - k
    } else {
      b0 = A * ((A + 1) + (A - 1) * cosw + k); b1 = -2 * A * ((A - 1) + (A + 1) * cosw)
      b2 = A * ((A + 1) + (A - 1) * cosw - k)
      a0 = (A + 1) - (A - 1) * cosw + k; a1 = 2 * ((A - 1) - (A + 1) * cosw)
      a2 = (A + 1) - (A - 1) * cosw - k
    }
    break
  case "lowpass":
    b0 = (1 - cosw) / 2; b1 = 1 - cosw; b2 = (1 - cosw) / 2
    a0 = 1 + alpha; a1 = -2 * cosw; a2 = 1 - alpha
    break
  case "highpass":
    b0 = (1 + cosw) / 2; b1 = -(1 + cosw); b2 = (1 + cosw) / 2
    a0 = 1 + alpha; a1 = -2 * cosw; a2 = 1 - alpha
    break
  case "notch":
    b0 = 1; b1 = -2 * cosw; b2 = 1
    a0 = 1 + alpha; a1 = -2 * cosw; a2 = 1 - alpha
    break
  default: // bandpass, 0 dB peak
    b0 = alpha; b1 = 0; b2 = -alpha
    a0 = 1 + alpha; a1 = -2 * cosw; a2 = 1 - alpha
  }
  return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0]
}

// |H(e^jw)| in dB for precomputed coefficients.
function magnitudeDb(c, freq, rate) {
  rate = rate || RATE
  var w = 2 * Math.PI * freq / rate
  var cos1 = Math.cos(w), sin1 = Math.sin(w)
  var cos2 = Math.cos(2 * w), sin2 = Math.sin(2 * w)
  // numerator and denominator at z = e^-jw
  var nr = c[0] + c[1] * cos1 + c[2] * cos2
  var ni = -(c[1] * sin1 + c[2] * sin2)
  var dr = 1 + c[3] * cos1 + c[4] * cos2
  var di = -(c[3] * sin1 + c[4] * sin2)
  var mag2 = (nr * nr + ni * ni) / Math.max(dr * dr + di * di, 1e-30)
  return 10 * Math.log(Math.max(mag2, 1e-24)) / Math.LN10
}

function bandResponseDb(band, freq, rate) {
  return magnitudeDb(coefficients(band, rate), freq, rate)
}

// The whole EQ's gain at each frequency, preamp included. Coefficients are
// computed once per band, not once per point, since this runs on every drag.
function responseDb(eq, freqs, rate) {
  var out = []
  var coeffs = []
  var bands = eq && eq.bands ? eq.bands : []
  for (var b = 0; b < bands.length; b++)
    if (bands[b].enabled !== false) coeffs.push(coefficients(bands[b], rate))
  var preamp = eq && eq.preamp ? Number(eq.preamp) : 0
  for (var i = 0; i < freqs.length; i++) {
    var total = preamp
    for (var k = 0; k < coeffs.length; k++) total += magnitudeDb(coeffs[k], freqs[i], rate)
    out.push(total)
  }
  return out
}

// Log-spaced frequencies across the audible band.
function logFreqs(count, low, high) {
  low = low || 20; high = high || 20000
  var out = []
  var ratio = Math.pow(high / low, 1 / (count - 1))
  for (var i = 0; i < count; i++) out.push(low * Math.pow(ratio, i))
  return out
}

function freqToX(freq, width) {
  return width * Math.log(freq / 20) / Math.log(1000)
}

function xToFreq(x, width) {
  return 20 * Math.pow(1000, Math.max(0, Math.min(1, x / width)))
}

function formatFreq(freq) {
  if (freq >= 10000) return (freq / 1000).toFixed(1) + " kHz"
  if (freq >= 1000) return (freq / 1000).toFixed(2) + " kHz"
  return Math.round(freq) + " Hz"
}

function formatGain(db) {
  var text = db.toFixed(1)
  if (text === "-0.0") text = "0.0"
  return (Number(text) > 0 ? "+" : "") + text + " dB"
}
