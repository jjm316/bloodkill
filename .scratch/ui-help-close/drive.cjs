/* 规则浮层 ✕ 关闭按钮视觉验收驱动：复用 ui-help-legend/drive-v4.cjs 的
   CDP 裸驱动配方（无头 Chrome，零依赖，Node >= 22）。 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = 'D:/AIProj/bloodkill/.scratch/ui-help-close/shots';
const PROFILE = path.join(os.tmpdir(), 'bloodkill-ui-verify-profile');
const PORT = 9334;
const BASE = 'http://127.0.0.1:8000';
const NAME = '关闭验收';

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

// 页头区量化见证：✕ 尺寸/位置/可访问名、旧提示是否已消失、与标题是否重叠
const HEAD_EXPR = `(() => {
  const btn = document.querySelector('.rules-modal .rules-close');
  const head = document.querySelector('.rules-modal .rules-head');
  const h3 = head && head.querySelector('h3');
  const overlayText = document.querySelector('.modal.rules-modal')?.textContent || '';
  if (!btn || !head || !h3) return { btnPresent: !!btn, headPresent: !!head };
  const b = btn.getBoundingClientRect();
  const hr = head.getBoundingClientRect();
  const t = h3.getBoundingClientRect();
  const svg = btn.querySelector('svg');
  const s = svg && svg.getBoundingClientRect();
  return {
    btnPresent: true,
    ariaLabel: btn.getAttribute('aria-label'),
    title: btn.getAttribute('title'),
    w: +b.width.toFixed(1), h: +b.height.toFixed(1),
    rightGap: +(hr.right - b.right).toFixed(1),
    overlapsTitle: b.left < t.right,
    svgW: s ? +s.width.toFixed(1) : null, svgH: s ? +s.height.toFixed(1) : null,
    hasHint: overlayText.includes('Esc / 点击遮罩关闭'),
    color: getComputedStyle(btn).color,
  };
})()`;

async function scenario(cdp, w, h, dpr, tag) {
  const res = { viewport: w, tag };
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dpr, mobile: w < 700 });
  await cdp.send('Page.navigate', { url: BASE + '/' });
  const ready = await waitForExpr(cdp, `document.readyState === 'complete' && (!!document.querySelector('#player-name') || !!document.querySelector('.room-header .help-button'))`, 15000);
  if (!ready) throw new Error('lobby did not become ready');
  if (!(await evalJS(cdp, `!!document.querySelector('.room-header .help-button')`))) {
    await evalJS(cdp, `(() => {
      const input = document.querySelector('#player-name');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(NAME + '-' + tag)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    const clicked = await evalJS(cdp, `(() => {
      const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === '创建房间');
      if (!b) return false; b.click(); return true;
    })()`);
    if (!clicked) throw new Error('create-room button not found');
    if (!(await waitForExpr(cdp, `!!document.querySelector('.room-header .help-button')`, 15000))) throw new Error('room header did not appear');
  }
  res.enteredRoom = true;
  await sleep(300);
  await shot(cdp, `room-${tag}.png`);
  res.overlayOpened = await evalJS(cdp, `(() => { const b = document.querySelector('.room-header .help-button'); if (!b) return false; b.click(); return true; })()`)
    && await waitForExpr(cdp, `!!document.querySelector('.modal.rules-modal')`, 5000);
  if (!res.overlayOpened) throw new Error('overlay did not open');
  await sleep(350);
  await shot(cdp, `overlay-${tag}.png`);
  const headRect = await evalJS(cdp, `(() => { const r = document.querySelector('.rules-modal .rules-head').getBoundingClientRect(); return { x: r.left, y: r.top, width: r.width, height: r.height }; })()`);
  await shot(cdp, `head-${tag}.png`, { x: Math.max(0, headRect.x - 8), y: Math.max(0, headRect.y - 8), width: Math.ceil(headRect.width + 16), height: Math.ceil(headRect.height + 16), scale: 4 });
  res.head = await evalJS(cdp, HEAD_EXPR);
  // P2-a 证据补全：滚到浮层底部，取证「标记图例」区渲染
  await evalJS(cdp, `(() => { const b = document.querySelector('.rules-modal .rules-body'); b.scrollTop = b.scrollHeight; return b.scrollTop; })()`);
  await sleep(350);
  await shot(cdp, `overlay-bottom-${tag}.png`);
  await evalJS(cdp, `(() => { const b = document.querySelector('.rules-modal .rules-body'); b.scrollTop = 0; return true; })()`);
  await sleep(250);
  // P2-b 证据补全：hover 态提亮取证（CDP 鼠标移到 ✕ 中心）
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: Math.round(headRect.x + headRect.width - 26), y: Math.round(headRect.y + headRect.height / 2) });
  await sleep(350);
  await shot(cdp, `head-hover-${tag}.png`, { x: Math.max(0, headRect.x - 8), y: Math.max(0, headRect.y - 8), width: Math.ceil(headRect.width + 16), height: Math.ceil(headRect.height + 16), scale: 4 });
  res.hoverColor = await evalJS(cdp, `(() => { const b = document.querySelector('.rules-modal .rules-close'); return b.matches(':hover') ? getComputedStyle(b).color : 'NOT-HOVERING'; })()`);
  // 主路径见证：点 ✕ 应关闭浮层
  await evalJS(cdp, `document.querySelector('.rules-modal .rules-close').click()`);
  res.closeByX = await waitForExpr(cdp, `!document.querySelector('.modal.rules-modal')`, 3000);
  // 关闭后房间截图（回归：页头布局不变）
  await sleep(250);
  await shot(cdp, `room-after-${tag}.png`);
  return res;
}

async function main() {
  fs.rmSync(PROFILE, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
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
    for (const [w, h, dpr, tag] of [[375, 812, 2, 'mobile-375'], [1024, 800, 1, 'desktop-1024']]) {
      process.stdout.write('viewport ' + tag + ' ... ');
      try {
        const r = await scenario(cdp, w, h, dpr, tag);
        results.push(r);
        console.log('done (closeByX=' + r.closeByX + ', btn=' + (r.head.w ? r.head.w + 'x' + r.head.h : 'n/a') + ', hasHint=' + r.head.hasHint + ')');
      } catch (e) {
        results.push({ viewport: w, tag, error: String(e && e.message || e) });
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
