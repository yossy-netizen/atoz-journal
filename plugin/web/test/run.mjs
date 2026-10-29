// Renders the AudioWorklet through an OfflineAudioContext in headless Chromium and checks
// the same behaviours as plugin/cpp/test/test_cvrider.cpp.
//   node plugin/web/test/run.mjs
import { serve, launch, makeChecker } from './harness.mjs';

const server = await serve();
const browser = await launch();
const page = await browser.newPage();
page.on('pageerror', (e) => console.error('page error:', e));
await page.goto(server.origin + '/');

const results = await page.evaluate(async () => {
  const fs = 48000;
  const segs = [[0, .3, -80], [1, 1.0, -30], [2, .15, -30], [1, 1.0, -12], [2, .15, -12], [0, .3, -80]];
  const bounds = []; let total = 0;
  for (const s of segs) { const n = Math.round(s[1] * fs); bounds.push([total, total + n]); total += n; }

  // deterministic gaussian noise (Box–Muller on a small LCG)
  let seed = 1234; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return (seed + 1) / 4294967297; };
  const gauss = () => Math.sqrt(-2 * Math.log(rnd())) * Math.cos(2 * Math.PI * rnd());
  const input = new Float32Array(total); let pos = 0, phase = 0;
  for (const [kind, sec, db] of segs) {
    const n = Math.round(sec * fs), amp = Math.pow(10, db / 20);
    for (let i = 0; i < n; i++) {
      let v;
      if (kind === 1) { let s = 0, norm = 0; for (let k = 1; k <= 8; k++) { s += Math.sin(k * phase) / k; norm += 1 / (2 * k * k); } v = s / Math.sqrt(norm) * amp; phase += 2 * Math.PI * 150 / fs; }
      else if (kind === 2) v = gauss() * amp; else v = gauss() * 1e-4;
      input[pos++] = v;
    }
  }
  const rmsDb = (x, [f, t]) => { let a = 0; for (let i = f; i < t; i++) a += x[i] * x[i]; return 10 * Math.log10(a / (t - f) + 1e-20); };
  const mid = (seg, a, b) => { const [f, t] = bounds[seg], len = t - f; return [f + Math.floor(len * a), f + Math.floor(len * b)]; };

  async function render(params) {
    const ctx = new OfflineAudioContext(1, total, fs);
    await ctx.audioWorklet.addModule('/cv-rider-processor.js');
    const node = new AudioWorkletNode(ctx, 'cv-rider', { outputChannelCount: [1] });
    for (const [k, v] of Object.entries(params)) node.parameters.get(k).value = v;
    const buf = ctx.createBuffer(1, total, fs); buf.copyToChannel(input, 0);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(node); node.connect(ctx.destination); src.start();
    const out = await ctx.startRendering();
    return out.getChannelData(0);
  }

  const r = {};
  const vowelOnly = await render({ vowelTarget: -18, vowelRange: 12, vowelAttack: 30, vowelRelease: 100, consRange: 0 });
  r.quietVowel = rmsDb(vowelOnly, mid(1, .7, 1));
  r.loudVowel = rmsDb(vowelOnly, mid(3, .7, 1));
  r.consDeltaUnderVowelRider = rmsDb(vowelOnly, mid(4, .3, 1)) - rmsDb(input, mid(4, .3, 1));

  const consOnly = await render({ vowelRange: 0, consTarget: -24, consRange: 12, consAttack: 2, consRelease: 20 });
  r.quietCons = rmsDb(consOnly, mid(2, .4, 1));
  r.loudCons = rmsDb(consOnly, mid(4, .4, 1));
  r.vowelDeltaUnderConsRider = rmsDb(consOnly, mid(3, .3, 1)) - rmsDb(input, mid(3, .3, 1));

  const solo = await render({ monitor: 1 });
  r.soloConsKeepsCons = rmsDb(solo, mid(4, .3, 1)) - rmsDb(input, mid(4, .3, 1));
  r.soloConsRemovesVowel = rmsDb(solo, mid(3, .3, 1));

  // a fresh node must apply the configured Output from the very first sample (no ramp-in);
  // the signal starts with a noise floor below the idle threshold, so only Output acts there
  const head = await render({ vowelRange: 0, consRange: 0, lookahead: 0, output: 12 });
  const first20ms = [0, Math.round(0.02 * fs)];
  r.headGainDb = rmsDb(head, first20ms) - rmsDb(input, first20ms);

  const bypass = await render({ bypass: 1, lookahead: 5 });
  let maxDiff = 0; const la = Math.round(0.005 * fs);
  for (let i = la; i < total; i++) maxDiff = Math.max(maxDiff, Math.abs(bypass[i] - input[i - la]));
  r.bypassMaxDiff = maxDiff;
  return r;
});

await browser.close();
server.close();

const { check, finish } = makeChecker();
check(Math.abs(results.quietVowel + 18) < 1.5, `quiet vowel ridden up to -18 dB (got ${results.quietVowel.toFixed(2)})`);
check(Math.abs(results.loudVowel + 18) < 1.5, `loud vowel ridden down to -18 dB (got ${results.loudVowel.toFixed(2)})`);
check(Math.abs(results.consDeltaUnderVowelRider) < 1, `consonant untouched by vowel rider (delta ${results.consDeltaUnderVowelRider.toFixed(2)} dB)`);
check(Math.abs(results.quietCons + 24) < 2, `quiet consonant ridden to -24 dB (got ${results.quietCons.toFixed(2)})`);
check(Math.abs(results.loudCons + 24) < 2, `loud consonant ridden to -24 dB (got ${results.loudCons.toFixed(2)})`);
check(Math.abs(results.vowelDeltaUnderConsRider) < 1, `vowel untouched by consonant rider (delta ${results.vowelDeltaUnderConsRider.toFixed(2)} dB)`);
check(results.soloConsKeepsCons > -1 && results.soloConsRemovesVowel < -40, `monitor: consonants solo (cons ${results.soloConsKeepsCons.toFixed(2)} dB, vowel ${results.soloConsRemovesVowel.toFixed(1)} dBFS)`);
check(results.bypassMaxDiff < 1e-6, `bypass passes the input delayed by the lookahead (max diff ${results.bypassMaxDiff})`);
check(Math.abs(results.headGainDb - 12) < 0.1, `fresh node applies Output from the first sample (first 20 ms: ${results.headGainDb.toFixed(2)} dB)`);
process.exit(finish());
