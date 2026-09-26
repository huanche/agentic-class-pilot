/**
 * Diagnostic: does a click in the PARENT page let a same-origin IFRAME's
 * Audio.play() through, under Chrome's real autoplay policy?
 *
 * Serves parent.html + child.html from 127.0.0.1:8765 (same origin), loads the
 * parent in Edge with `--autoplay-policy=document-user-activation-required`
 * (matches real Chrome behavior), clicks the parent button (which then injects
 * the iframe), and reports the child's play() outcome.
 *
 * Usage: node scripts/diag-iframe-autoplay.mjs
 */
import { createServer } from 'http';
import { chromium } from '@playwright/test';

const toneWav = (() => {
  const sampleRate = 24000;
  const samples = sampleRate; // 1s
  const b = Buffer.alloc(44 + samples * 2);
  b.write('RIFF', 0, 'ascii');
  b.writeUInt32LE(b.length - 8, 4);
  b.write('WAVE', 8, 'ascii');
  b.write('fmt ', 12, 'ascii');
  b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22);
  b.writeUInt32LE(sampleRate, 24);
  b.writeUInt32LE(sampleRate * 2, 28);
  b.writeUInt16LE(2, 32);
  b.writeUInt16LE(16, 34);
  b.write('data', 36, 'ascii');
  b.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) {
    b.writeInt16LE(Math.round(Math.sin((2 * Math.PI * 440 * i) / sampleRate) * 12000), 44 + i * 2);
  }
  return b;
})();

const parentHtml = `<!doctype html><html><body>
<button id="go">进入学习（模拟学生点击）</button>
<div id="result">pending</div>
<script>
window.results = [];
window.addEventListener('message', (e) => {
  results.push(e.data);
  document.getElementById('result').textContent = JSON.stringify(results);
});
document.getElementById('go').addEventListener('click', () => {
  const f = document.createElement('iframe');
  f.src = '/child.html';
  f.width = 300; f.height = 100;
  f.setAttribute('allow', 'autoplay; encrypted-media');
  document.body.appendChild(f);
});
</script></body></html>`;

const childHtml = `<!doctype html><html><body>
child-frame
<script>
(async () => {
  const r = await fetch('/tone.wav');
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  async function attempt(label) {
    const a = new Audio(url);
    a.volume = 1;
    try {
      await a.play();
      parent.postMessage({ label, result: 'PLAYED duration=' + a.duration }, '*');
      a.pause();
    } catch (e) {
      parent.postMessage({ label, result: 'REJECTED ' + e.name + ': ' + e.message }, '*');
    }
  }
  // 1. autoplay immediately on load (the student-embed scenario)
  await attempt('on-load (no in-iframe gesture)');
  // 2. after a click INSIDE the iframe
  document.body.addEventListener('click', () => attempt('after in-iframe click'), { once: true });
})();
</script></body></html>`;

const server = createServer((req, res) => {
  if (req.url === '/tone.wav') {
    res.writeHead(200, { 'content-type': 'audio/wav' });
    res.end(toneWav);
    return;
  }
  res.writeHead(200, { 'content-type': 'text/html' });
  res.end(req.url === '/child.html' ? childHtml : parentHtml);
});
await new Promise((resolve) => server.listen(8765, '127.0.0.1', resolve));

const browser = await chromium.launch({
  channel: 'msedge',
  headless: false,
  args: ['--autoplay-policy=document-user-activation-required'],
});
const page = await browser.newPage();
await page.goto('http://127.0.0.1:8765/parent.html');

// Scenario A: NO gesture at all — click the parent button programmatically
// (JS click does NOT count as a user gesture).
await page.evaluate(() => document.getElementById('go').click());
await page.waitForTimeout(1500);
const scenarioA = await page.evaluate(() => window.results);

// Fresh page for scenario B: REAL user click on the parent button.
const page2 = await browser.newPage();
await page2.goto('http://127.0.0.1:8765/parent.html');
await page2.click('#go'); // real Playwright input event = trusted user gesture
await page2.waitForTimeout(1500);
const scenarioB = await page2.evaluate(() => window.results);

console.log('A 程序化点击(无手势)  →', JSON.stringify(scenarioA));
console.log('B 真实点击父页面后注入 →', JSON.stringify(scenarioB));

// Scenario C: click inside the iframe after load (trusted gesture in-frame).
const frame = page2.frames().find((f) => f.url().includes('child.html'));
if (frame) {
  await frame.click('body');
  await page2.waitForTimeout(800);
  const scenarioC = await page2.evaluate(() => window.results);
  console.log('C iframe 内点击后      →', JSON.stringify(scenarioC));
}

await browser.close();
server.close();
