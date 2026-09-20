// Shared bootstrap for the Playwright tests: a static server for plugin/web and a Chromium launcher.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
export const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function loadPlaywright() {
  try { return require('playwright'); }
  catch { return require('/opt/node22/lib/node_modules/playwright'); }   // globally installed fallback
}

// Serves plugin/web on a random localhost port; returns { origin, close }.
export async function serve() {
  const server = http.createServer((req, res) => {
    const file = path.join(webDir, req.url === '/' ? 'index.html' : req.url.split('?')[0]);
    if (!file.startsWith(webDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': file.endsWith('.js') || file.endsWith('.mjs') ? 'text/javascript' : 'text/html' });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  return { origin: `http://127.0.0.1:${server.address().port}`, close: () => server.close() };
}

// Launches headless Chromium (CVRIDER_CHROMIUM overrides the executable) with autoplay allowed.
export async function launch() {
  const { chromium } = loadPlaywright();
  return chromium.launch({
    executablePath: process.env.CVRIDER_CHROMIUM || undefined,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
}

// Prints one result line and counts failures; returns the final exit code.
export function makeChecker() {
  let failures = 0;
  const check = (ok, what) => { console.log(`${ok ? '[ OK ]' : '[FAIL]'}  ${what}`); if (!ok) failures++; };
  const finish = () => { console.log(failures ? `\nFAILED (${failures})` : '\nALL PASSED'); return failures ? 1 : 0; };
  return { check, finish };
}
