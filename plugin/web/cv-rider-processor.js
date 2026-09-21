// cv-rider-processor.js — AudioWorklet port of plugin/cpp/CVRider.h
//
// Same signal flow as the C++ core, sample by sample:
//   consonant probability c  ← HP-band / total energy ratio (+ HP-band transient)
//   vowel rider     gv ← slow RMS vs. Vowel Target, clamped to ±Vowel Range   (held while c ≈ 1)
//   consonant rider gc ← fast RMS vs. Consonant Target, clamped to ±Consonant Range
//   gain(dB) = c·(gc + consTrim) + (1−c)·(gv + vowelTrim) + output
//
// All parameters are k-rate AudioParams so the page can drive them directly.
// Meters are posted through the MessagePort roughly every 20 ms.

const MAX_LOOKAHEAD_MS = 10;
const EPS = 1e-12;            // floor inside log10
const ANTI_DENORMAL = 1e-20;     // keeps decaying energy envelopes out of the denormal range
const ANTI_DENORMAL_IN = 1e-18;  // alternating-sign offset at the detector input (filter states)

const dbToLin = (db) => Math.pow(10, db * 0.05);
const powToDb = (p) => 10 * Math.log10(p + EPS);
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const smoothstep = (lo, hi, x) => {
  const t = clamp((x - lo) / (hi - lo), 0, 1);
  return t * t * (3 - 2 * t);
};
const tauCoef = (ms, fs) => (ms <= 0 ? 0 : Math.exp(-1 / (ms * 0.001 * fs)));

class BiquadHP {
  constructor() { this.b0 = 1; this.b1 = 0; this.b2 = 0; this.a1 = 0; this.a2 = 0; this.z1 = 0; this.z2 = 0; }
  set(fs, fc, q = Math.SQRT1_2) {
    fc = clamp(fc, 20, fs * 0.45);
    const w0 = 2 * Math.PI * fc / fs, c = Math.cos(w0), a = Math.sin(w0) / (2 * q), a0 = 1 + a;
    this.b0 = (1 + c) * 0.5 / a0; this.b1 = -(1 + c) / a0; this.b2 = this.b0;
    this.a1 = -2 * c / a0; this.a2 = (1 - a) / a0;
  }
  reset() { this.z1 = this.z2 = 0; }
  process(x) {
    const y = this.b0 * x + this.z1;
    this.z1 = this.b1 * x - this.a1 * y + this.z2;
    this.z2 = this.b2 * x - this.a2 * y;
    return y;
  }
}

// first-order DC blocker (~20 Hz) for the detector path
class DcBlocker {
  constructor() { this.r = 0.999; this.x1 = 0; this.y1 = 0; }
  set(fs) { this.r = 1 - 2 * Math.PI * 20 / fs; }
  reset() { this.x1 = this.y1 = 0; }
  process(x) { const y = x - this.x1 + this.r * this.y1; this.x1 = x; this.y1 = y; return y; }
}

class CVRiderProcessor extends AudioWorkletProcessor {
  static get parameterDescriptors() {
    const p = (name, defaultValue, minValue, maxValue) => ({ name, defaultValue, minValue, maxValue, automationRate: 'k-rate' });
    return [
      p('vowelTarget', -18, -40, 0), p('vowelRange', 6, 0, 12), p('vowelAttack', 60, 1, 500), p('vowelRelease', 300, 10, 2000), p('vowelTrim', 0, -12, 12),
      p('consTarget', -24, -40, 0), p('consRange', 6, 0, 12), p('consAttack', 2, 0.1, 50), p('consRelease', 40, 5, 500), p('consTrim', 0, -12, 12),
      p('sensitivity', 0, -12, 12), p('splitFreq', 4000, 2000, 8000), p('idleThreshold', -50, -80, -20), p('lookahead', 3, 0, MAX_LOOKAHEAD_MS),
      p('output', 0, -24, 24), p('monitor', 0, 0, 2), p('bypass', 0, 0, 1),
    ];
  }

  constructor(options) {
    super();
    this.fs = sampleRate;
    const channels = (options && options.outputChannelCount && options.outputChannelCount[0]) || 2;
    this.maxDelay = Math.ceil(MAX_LOOKAHEAD_MS * 0.001 * this.fs) + 1;
    this.delay = Array.from({ length: channels }, () => new Float32Array(this.maxDelay));
    this.writePos = 0;
    this.dc = new DcBlocker();
    this.hp = new BiquadHP();
    this.hfEnv = this.totEnv = this.hfFast = this.hfSlow = this.lvEnv = this.lcEnv = 0;
    this.lvDbPrev = -120;
    this.c = 0; this.gv = 0; this.gc = 0;
    this.vowelTrimSm = 0; this.consTrimSm = 0; this.outputSm = 0; this.gainSm = 1;
    this.ditherSign = 1;
    this.snapPending = true;   // smoothers jump to the current parameters on the next processed sample
    this.cached = {};
    this.meterCounter = 0;
    this.meters = { levelDb: -120, consonantProb: 0, vowelGainDb: 0, consGainDb: 0, gainDb: 0 };
    this.port.onmessage = (e) => { if (e.data === 'reset') this.reset(); };
  }

  reset() {
    this.dc.reset();
    this.hp.reset();
    this.hfEnv = this.totEnv = this.hfFast = this.hfSlow = this.lvEnv = this.lcEnv = 0;
    this.lvDbPrev = -120;
    this.c = this.gv = this.gc = 0;
    for (const d of this.delay) d.fill(0);
    this.writePos = 0;
    this.snapPending = true;
  }

  updateCoefficients(P) {
    const fs = this.fs;
    const changed = (k) => { const v = P[k][0]; if (this.cached[k] === v) return false; this.cached[k] = v; return true; };
    if (changed('splitFreq') || this.kEnergy === undefined) {
      this.dc.set(fs);
      this.hp.set(fs, P.splitFreq[0]);
      this.kEnergy = tauCoef(6, fs);
      this.kOffset = tauCoef(10, fs);   // trims / output smoothing (~10 ms)
      this.kGain = tauCoef(1, fs);      // final linear gain (~1 ms): de-clicks bypass / monitor / range steps
      this.kHfFastRise = tauCoef(0.5, fs); this.kHfFastFall = tauCoef(5, fs); this.kHfSlow = tauCoef(30, fs);
      this.kLv = tauCoef(40, fs); this.kLc = tauCoef(5, fs);
      this.kCRise = tauCoef(1, fs); this.kCFall = tauCoef(20, fs);
    }
    if (changed('vowelAttack'))  this.kGvFall = tauCoef(P.vowelAttack[0], fs);
    if (changed('vowelRelease')) this.kGvRise = tauCoef(P.vowelRelease[0], fs);
    if (changed('consAttack'))   this.kGcFall = tauCoef(P.consAttack[0], fs);
    if (changed('consRelease'))  this.kGcRise = tauCoef(P.consRelease[0], fs);
    if (changed('sensitivity'))  this.thr = -9 - P.sensitivity[0];
    if (changed('lookahead'))    this.lookaheadSamples = clamp(Math.round(P.lookahead[0] * 0.001 * fs), 0, this.maxDelay - 1);
  }

  process(inputs, outputs, P) {
    const input = inputs[0], output = outputs[0];
    const numCh = Math.min(output.length, this.delay.length);
    const n = output[0] ? output[0].length : 128;
    if (numCh === 0) return true;
    this.updateCoefficients(P);

    const vowelTarget = P.vowelTarget[0], vowelRange = P.vowelRange[0], vowelTrim = P.vowelTrim[0];
    const consTarget = P.consTarget[0], consRange = P.consRange[0], consTrim = P.consTrim[0];
    const idleThr = P.idleThreshold[0], monitor = Math.round(P.monitor[0]), bypass = P.bypass[0] > 0.5, outputDb = P.output[0];
    const thr = this.thr, invCh = 1 / numCh, LA = this.lookaheadSamples, maxDelay = this.maxDelay;

    if (this.snapPending) {
      // first sample after construction / reset: start from the current parameters, not from a ramp
      this.vowelTrimSm = vowelTrim; this.consTrimSm = consTrim; this.outputSm = outputDb;
      this.gainSm = bypass ? 1 : (monitor !== 0 ? 0 : dbToLin(vowelTrim + outputDb));
      this.snapPending = false;
    }

    let c = this.c, gv = this.gv, gc = this.gc, lcDb = -120, gainDb = 0;

    for (let i = 0; i < n; i++) {
      // ---- detector input: mono mix of the undelayed signal ----
      let x = 0;
      for (let ch = 0; ch < numCh; ch++) { const inCh = input[ch] || input[0]; x += inCh ? inCh[i] : 0; }
      // a tiny alternating offset keeps the recursive filter states out of the denormal range
      this.ditherSign = -this.ditherSign;
      x = this.dc.process(x * invCh + this.ditherSign * ANTI_DENORMAL_IN);

      // ---- consonant classification ----
      const h = this.hp.process(x), h2 = h * h + ANTI_DENORMAL, x2 = x * x + ANTI_DENORMAL;
      this.hfEnv = h2 + this.kEnergy * (this.hfEnv - h2);
      this.totEnv = x2 + this.kEnergy * (this.totEnv - x2);
      const ratioDb = powToDb(this.hfEnv) - powToDb(this.totEnv);
      const sib = smoothstep(thr - 4, thr + 4, ratioDb);

      this.hfFast = h2 + (h2 > this.hfFast ? this.kHfFastRise : this.kHfFastFall) * (this.hfFast - h2);
      this.hfSlow = h2 + this.kHfSlow * (this.hfSlow - h2);
      const transDb = powToDb(this.hfFast) - powToDb(this.hfSlow);
      const trans = smoothstep(5, 11, transDb) * smoothstep(thr - 12, thr - 4, ratioDb);

      // ---- level detectors ----
      this.lcEnv = x2 + this.kLc * (this.lcEnv - x2);
      lcDb = powToDb(this.lcEnv);
      const idle = lcDb < idleThr && this.lvDbPrev < idleThr;

      // below the idle threshold the (broadband) noise floor must not count as a consonant
      const cRaw = idle ? 0 : Math.max(sib, trans);
      c = cRaw + (cRaw > c ? this.kCRise : this.kCFall) * (c - cRaw);

      // the vowel level detector is frozen while a consonant is present (see CVRider.h)
      this.lvEnv += (idle ? 1 : 1 - c) * (1 - this.kLv) * (x2 - this.lvEnv);
      const lvDb = powToDb(this.lvEnv);
      this.lvDbPrev = lvDb;

      // ---- riders ----
      let gvT = 0, gcT = 0;
      if (!idle) {
        gvT = clamp(vowelTarget - lvDb, -vowelRange, vowelRange);
        gcT = clamp(consTarget - lcDb, -consRange, consRange);
      }
      { // vowel gain is held while a consonant is detected; when idle it returns to 0 dB normally
        const k0 = gvT > gv ? this.kGvRise : this.kGvFall;
        const k = 1 - (idle ? 1 : 1 - c) * (1 - k0);
        gv = gvT + k * (gv - gvT);
      }
      gc = gcT + (gcT > gc ? this.kGcRise : this.kGcFall) * (gc - gcT);

      // smoothed static offsets
      this.vowelTrimSm = vowelTrim + this.kOffset * (this.vowelTrimSm - vowelTrim);
      this.consTrimSm = consTrim + this.kOffset * (this.consTrimSm - consTrim);
      this.outputSm = outputDb + this.kOffset * (this.outputSm - outputDb);

      gainDb = c * (gc + this.consTrimSm) + (1 - c) * (gv + this.vowelTrimSm);
      let gainTarget = dbToLin(gainDb + this.outputSm);
      if (bypass) gainTarget = 1; else if (monitor === 1) gainTarget = c; else if (monitor === 2) gainTarget = 1 - c;
      this.gainSm = gainTarget + this.kGain * (this.gainSm - gainTarget);

      // ---- audio path: lookahead delay, then gain ----
      const readPos = (this.writePos - LA + maxDelay) % maxDelay;
      for (let ch = 0; ch < numCh; ch++) {
        const inCh = input[ch] || input[0];
        const d = this.delay[ch];
        d[this.writePos] = inCh ? inCh[i] : 0;
        output[ch][i] = d[readPos] * this.gainSm;
      }
      if (++this.writePos >= maxDelay) this.writePos = 0;
    }

    this.c = c; this.gv = gv; this.gc = gc;
    this.meterCounter += n;
    if (this.meterCounter >= this.fs * 0.02) {
      this.meterCounter = 0;
      this.meters.levelDb = lcDb; this.meters.consonantProb = c;
      this.meters.vowelGainDb = gv + this.vowelTrimSm; this.meters.consGainDb = gc + this.consTrimSm;
      this.meters.gainDb = bypass ? 0 : gainDb + this.outputSm;
      this.port.postMessage(this.meters);
    }
    return true;
  }
}

registerProcessor('cv-rider', CVRiderProcessor);
