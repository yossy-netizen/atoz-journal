// Browser smoke test for the demo page: the built-in test signal plays, the meters move,
// and the WAV export produces a valid 24-bit RIFF file.
//   node plugin/web/test/ui.mjs
import fs from 'node:fs';
import { serve, launch, makeChecker } from './harness.mjs';

const server = await serve();
const browser = await launch();
const page = await browser.newPage({ acceptDownloads: true });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
await page.goto(server.origin + '/');

const { check, finish } = makeChecker();

await page.click('#btnTest');
await page.click('#btnPlay');
await page.waitForTimeout(1500);
const gainText = await page.textContent('#mG');
check(/dB/.test(gainText) && gainText !== '–', `meters update while playing (applied gain: ${gainText})`);
check(!(await page.isDisabled('#btnStop')), 'stop button enabled while playing');
await page.click('#btnStop');
check(await page.isDisabled('#btnStop'), 'stop button disabled after stopping');

// parameter change reaches the worklet without errors
await page.fill('#vowelTarget', '-12');
await page.dispatchEvent('#vowelTarget', 'input');
check((await page.textContent('#vowelTargetOut')).startsWith('-12.0'), 'slider readout follows the slider');

// export
const [download] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), page.click('#btnExport')]);
const file = await download.path();
const bytes = fs.readFileSync(file);
const riff = bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WAVE';
const bits = bytes.readUInt16LE(34), channels = bytes.readUInt16LE(22), rate = bytes.readUInt32LE(24), dataLen = bytes.readUInt32LE(40), riffLen = bytes.readUInt32LE(4);
check(riff && bits === 24, `export is a 24-bit RIFF/WAVE file (${bits}-bit, ${channels} ch, ${rate} Hz)`);
check(dataLen > 0 && dataLen + (dataLen & 1) === bytes.length - 44 && riffLen === bytes.length - 8, `data chunk + pad byte match the file (${dataLen} bytes${dataLen & 1 ? ' + pad' : ''})`);
check(download.suggestedFilename().endsWith('.wav'), `download name: ${download.suggestedFilename()}`);
check((await page.textContent('#status')).startsWith('書き出し完了'), 'status reports export completion');

// a 96 kHz mono 16-bit WAV with an odd frame count: must decode at its own rate (not the device rate),
// export at 96 kHz, and the 24-bit mono data chunk (odd size) must get its pad byte
{
  const rate = 96000, frames = 96001, pcm = Buffer.alloc(44 + frames * 2);
  pcm.write('RIFF', 0); pcm.writeUInt32LE(36 + frames * 2, 4); pcm.write('WAVE', 8);
  pcm.write('fmt ', 12); pcm.writeUInt32LE(16, 16); pcm.writeUInt16LE(1, 20); pcm.writeUInt16LE(1, 22);
  pcm.writeUInt32LE(rate, 24); pcm.writeUInt32LE(rate * 2, 28); pcm.writeUInt16LE(2, 32); pcm.writeUInt16LE(16, 34);
  pcm.write('data', 36); pcm.writeUInt32LE(frames * 2, 40);
  for (let i = 0; i < frames; i++) pcm.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 220 * i / rate) * 8000), 44 + i * 2);
  await page.setInputFiles('#file', { name: 'tone96k.wav', mimeType: 'audio/wav', buffer: pcm });
  await page.waitForFunction(() => document.querySelector('#status').textContent.includes('tone96k.wav'));
  const st = await page.textContent('#status');
  check(st.includes('96000 Hz'), `uploaded WAV decoded at its native rate (${st})`);
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), page.click('#btnExport')]);
  const b = fs.readFileSync(await dl.path());
  const outRate = b.readUInt32LE(24), outData = b.readUInt32LE(40), outRiff = b.readUInt32LE(4);
  check(outRate === 96000, `export keeps the file's sample rate (${outRate} Hz)`);
  check(outData === frames * 3 && (outData & 1) === 1 && b.length === 44 + outData + 1 && outRiff === b.length - 8, `odd data chunk is padded to a word boundary (${outData} bytes + 1 pad)`);
  check(dl.suggestedFilename() === 'tone96k_cvrider.wav', `export name derives from the file name (${dl.suggestedFilename()})`);
}

check(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);

await browser.close();
server.close();
process.exit(finish());
