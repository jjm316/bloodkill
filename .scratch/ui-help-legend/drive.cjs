/* 视觉验收驱动：CDP 裸驱动无头 Chrome，零依赖（Node >= 22，自带 fetch/WebSocket）。 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = 'D:/AIProj/bloodkill/.scratch/ui-help-legend/shots/issue-01';
const PROFILE = path.join(os.tmpdir(), 'bloodkill-ui-verify-profile');
const PORT = 9333;
const BASE = 'http://127.0.0.1:8000';
const VIEWPORTS = [1024, 768, 640, 480, 360, 320];
const HEIGHT = 800;
const NAME = '验收专员';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.listeners = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id); this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.method + ' -> ' + JSON.stringify(msg.error)));
        else resolve(msg.result || {});
      } else if (msg.method && this.listeners.has(msg.method)) {
        this.listeners.get(msg.method).forEach((fn) => fn(msg.params));
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function evalJS(cdp, expression) {
  const r = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page eval error: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result ? r.result.value : undefined;
}

async function waitForExpr(cdp, expr, timeoutMs = 10000, interval = 150) {
  const t0 = Date.now();
  for (;;) {
    let ok = false;
    try { ok = await evalJS(cdp, expr); } catch (e) { ok = false; }
    if (ok) return true;
    if (Date.now() - t0 > timeoutMs) return false;
    await sleep(interval);
  }
}

async function shot(cdp, name, clip = null) {
  const params = { format: 'png' };
  if (clip) params.clip = clip;
  const r = await cdp.send('Page.captureScreenshot', params);
  fs.writeFileSync(path.join(OUT, name), Buffer.from(r.data, 'base64'));
  return name;
}

async function shotElement(cdp, rect, name, scale = 6, margin = 8) {
  const clip = {
    x: Math.max(0, Math.floor(rect.x - margin)),
    y: Math.max(0, Math.floor(rect.y - margin)),
    width: Math.ceil(rect.width + margin * 2),
    height: Math.ceil(rect.height + margin * 2),
    scale,
  };
  return shot(cdp, name, clip);
}

const METRICS_EXPR = `(() => {
  const btn = document.querySelector('.room-header .help-button');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  const svg = btn.querySelector('svg');
  const circle = svg && svg.querySelector('circle');
  const text = svg && svg.querySelector('text');
  const cs = getComputedStyle(btn);
  const bareText = [...btn.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  let circleC = null, textC = null, fontFamily = null, fontSize = null, stroke = null, svgSize = null;
  if (circle) { const c = circle.getBoundingClientRect(); circleC = { x: +(c.left + c.width / 2).toFixed(2), y: +(c.top + c.height / 2).toFixed(2) }; stroke = getComputedStyle(circle).stroke; }
  if (text) { const t = text.getBoundingClientRect(); textC = { x: +(t.left + t.width / 2).toFixed(2), y: +(t.top + t.height / 2).toFixed(2) }; const ts = getComputedStyle(text); fontFamily = ts.fontFamily; fontSize = ts.fontSize; }
  if (svg) { const s = svg.getBoundingClientRect(); svgSize = { w: +s.width.toFixed(2), h: +s.height.toFixed(2) }; }
  const doc = document.documentElement;
  const header = document.querySelector('.room-header');
  const hr = header.getBoundingClientRect();
  const headerItems = [...header.children].map(el => { const c = el.getBoundingClientRect(); return { cls: String(el.className || el.tagName), text: el.textContent.trim().slice(0, 30), w: +c.width.toFixed(1), right: +c.right.toFixed(1) }; });
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    btn: { w: +r.width.toFixed(2), h: +r.height.toFixed(2), diff: +Math.abs(r.width - r.height).toFixed(2) },
    hasSvg: !!svg, hasCircle: !!circle, hasText: !!text, bareText,
    viewBox: svg ? svg.getAttribute('viewBox') : null,
    circleR: circle ? circle.getAttribute('r') : null,
    circleCenter: circleC, textCenter: textC,
    dx: (circleC && textC) ? +(textC.x - circleC.x).toFixed(2) : null,
    dy: (circleC && textC) ? +(textC.y - circleC.y).toFixed(2) : null,
    svgSize, fontFamily, fontSize, stroke,
    bg: cs.backgroundColor, color: cs.color,
    borderTop: cs.borderTopWidth, borderStyle: cs.borderTopStyle,
    scrollW: doc.scrollWidth, clientW: doc.clientWidth,
    overflowX: doc.scrollWidth > doc.clientWidth,
    headerW: +hr.width.toFixed(1), headerRight: +hr.right.toFixed(1),
    headerItems,
  };
})()`;

const RULESQ_EXPR = `(() => {
  const q = document.querySelector('.rules-modal .rules-q');
  if (!q) return null;
  const r = q.getBoundingClientRect();
  const cs = getComputedStyle(q);
  return { w: +r.width.toFixed(2), h: +r.height.toFixed(2), diff: +Math.abs(r.width - r.height).toFixed(2),
    x: +r.left.toFixed(1), y: +r.top.toFixed(1), text: q.textContent.trim(),
    border: cs.borderTopWidth, bg: cs.backgroundColor, color: cs.color,
    fontFamily: cs.fontFamily, display: cs.display };
})()`;

async function openOverlay(cdp) {
  await evalJS(cdp, `(() => { const b = document.querySelector('.room-header .help-button'); if (!b) return false; b.click(); return true; })()`);
  return waitForExpr(cdp, `!!document.querySelector('.modal.rules-modal')`, 5000);
}

async function pressEscape(cdp) {
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
}

async function scenario(cdp, w) {
  const res = { viewport: w, height: HEIGHT };
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: w, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: BASE + '/' });
  const ready = await waitForExpr(cdp, `document.readyState === 'complete' && (!!document.querySelector('#player-name') || !!document.querySelector('.room-header .help-button'))`, 15000);
  if (!ready) throw new Error('lobby did not become ready');
  const onRoom = await evalJS(cdp, `!!document.querySelector('.room-header .help-button')`);
  if (!onRoom) {
    res.filledName = await evalJS(cdp, `(() => {
      const input = document.querySelector('#player-name');
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(NAME)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return input.value;
    })()`);
    const clicked = await evalJS(cdp, `(() => {
      const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === '创建房间');
      if (!b) return false; b.click(); return true;
    })()`);
    if (!clicked) throw new Error('create-room button not found');
    const inRoom = await waitForExpr(cdp, `!!document.querySelector('.room-header .help-button')`, 15000);
    if (!inRoom) throw new Error('room header did not appear after create');
  }
  res.enteredRoom = true;
  await evalJS(cdp, `window.scrollTo(0, 0)`);
  await sleep(300);
  res.metrics = await evalJS(cdp, METRICS_EXPR);
  if (!res.metrics) throw new Error('help-button metrics unavailable');
  await shot(cdp, `room-${w}.png`);
  const btnRect = await evalJS(cdp, `(() => { const r = document.querySelector('.room-header .help-button').getBoundingClientRect(); return { x: r.left, y: r.top, width: r.width, height: r.height }; })()`);
  await shotElement(cdp, btnRect, `help-${w}.png`, w <= 360 ? 8 : 6);
  res.overlayOpened = await openOverlay(cdp);
  await sleep(350);
  res.rulesQ = res.overlayOpened ? await evalJS(cdp, RULESQ_EXPR) : null;
  await shot(cdp, `rules-overlay-${w}.png`);
  if (res.rulesQ) {
    const qRect = await evalJS(cdp, `(() => { const r = document.querySelector('.rules-modal .rules-q').getBoundingClientRect(); return { x: r.left, y: r.top, width: r.width, height: r.height }; })()`);
    await shotElement(cdp, qRect, `rules-q-${w}.png`, w <= 360 ? 8 : 6);
  }
  if (res.overlayOpened) {
    await pressEscape(cdp);
    let closed = await waitForExpr(cdp, `!document.querySelector('.modal.rules-modal')`, 3000);
    res.escapeMethod = 'CDP Input.dispatchKeyEvent';
    if (!closed) {
      await evalJS(cdp, `window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))`);
      closed = await waitForExpr(cdp, `!document.querySelector('.modal.rules-modal')`, 2000);
      res.escapeMethod = 'synthetic KeyboardEvent fallback';
    }
    res.escapeClosed = closed;
  }
  return res;
}

async function main() {
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const proc = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--force-device-scale-factor=1', '--window-size=1400,1000', 'about:blank',
  ], { stdio: 'ignore' });
  try {
    let page = null;
    for (let i = 0; i < 100; i++) {
      try {
        const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
        page = list.find(t => t.type === 'page');
        if (page) break;
      } catch (e) { /* not up yet */ }
      await sleep(300);
    }
    if (!page) throw new Error('chrome devtools endpoint never came up');
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
    const cdp = new CDP(ws);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    const results = [];
    for (const w of VIEWPORTS) {
      process.stdout.write('viewport ' + w + ' ... ');
      try {
        const r = await scenario(cdp, w);
        results.push(r);
        console.log('done (btn ' + (r.metrics ? r.metrics.btn.w + 'x' + r.metrics.btn.h : 'n/a') + ', overlay ' + (r.overlayOpened ? 'open' : 'FAILED') + ', esc ' + r.escapeClosed + ')');
      } catch (e) {
        results.push({ viewport: w, error: String(e && e.message || e) });
        console.log('ERROR: ' + (e && e.message || e));
      }
    }
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
    console.log('RESULTS_WRITTEN');
    ws.close();
  } finally {
    try { proc.kill(); } catch (e) {}
    await sleep(500);
  }
}

main().then(() => process.exit(0)).catch((e) => { console.error('FATAL: ' + (e && e.stack || e)); process.exit(1); });
