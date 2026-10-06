/* ui-true-color 视觉验收驱动：CDP 裸驱动无头 Chrome，零依赖（仿 ui-help-legend/drive-v4.cjs）。
 * 对三种真实阵营（rose/beast/secret-order）各开一页：
 *   1) 机械一致性：.own-identity 文案 ↔ 色徽计算背景色 ↔ 贴角定位（top/right = -8px）
 *   2) 截图：桌面 1440 整页 + 自己座位卡特写 + 图例浮层短注区
 * 结果写 result.json，截图落 shots/。 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const DIR = 'D:/AIProj/bloodkill/.scratch/ui-true-color';
const OUT = path.join(DIR, 'shots');
const PROFILE = path.join(os.tmpdir(), 'bloodkill-ui-truecolor-profile');
const PORT = 9337;
const BASE = 'http://127.0.0.1:8000';

const TONE_RGB = {
  rose: 'rgb(142, 39, 35)',   // --rose-bg #8e2723
  beast: 'rgb(51, 96, 143)',  // --beast-bg #33608f
  order: 'rgb(138, 95, 192)', // --order-bg #8a5fc0（P1 重设计：审判者紫罗兰）
};
const GOLD_RING = 'rgb(245, 197, 24)'; // --accent-gold #f5c518（0xc5=197, 0x18=24）
const FACTION_TEXT = { rose: '玫瑰家族', beast: '野兽家族', 'secret-order': '审判者' };

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

async function waitForExpr(cdp, expr, timeoutMs = 12000, interval = 150) {
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
  const params = { format: 'png', captureBeyondViewport: !clip };
  if (clip) params.clip = clip;
  const r = await cdp.send('Page.captureScreenshot', params);
  fs.writeFileSync(path.join(OUT, name), Buffer.from(r.data, 'base64'));
  return name;
}

const METRICS_EXPR = `(() => {
  const seat = document.querySelector('.players .seat.self');
  if (!seat) return { error: 'no self seat' };
  const badge = seat.querySelector(':scope > .true-color-badge');
  const selfTag = seat.querySelector(':scope > .self-tag');
  const identity = seat.querySelector('.own-identity');
  const clue = seat.querySelector('.own-clue-icon');
  const others = document.querySelectorAll('.seat:not(.self) .true-color-badge').length;
  const othersTag = document.querySelectorAll('.seat:not(.self) .self-tag').length;
  let bg = null, border = null, pos = null, top = null, right = null, rect = null, title = null, aria = null;
  if (badge) {
    const cs = getComputedStyle(badge);
    bg = cs.backgroundColor; border = cs.borderColor; pos = cs.position;
    top = cs.top; right = cs.right;
    const r = badge.getBoundingClientRect();
    rect = { x: +r.left.toFixed(1), y: +r.top.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1) };
    title = badge.getAttribute('title'); aria = badge.getAttribute('aria-label');
  }
  return {
    identityText: identity ? identity.textContent.trim() : null,
    clueText: clue ? clue.textContent.trim().slice(0, 40) : null,
    hasBadge: !!badge, bg, border, pos, top, right, rect, title, aria,
    badgesOnOthers: others,
    selfTagText: selfTag ? selfTag.textContent : null,
    selfTagsOnOthers: othersTag,
    seatRect: (() => { const r = seat.getBoundingClientRect(); return { x: r.left, y: r.top, width: r.width, height: r.height }; })(),
  };
})()`;

async function runRoom(cdp, target, info) {
  const res = { target };
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 950, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: `${BASE}/?room=${info.code}&name=${encodeURIComponent(info.browser)}` });
  if (!await waitForExpr(cdp, `!!document.querySelector('.players .seat.self')`)) throw new Error(`[${target}] self seat 未出现`);
  await sleep(500);
  res.metrics = await evalJS(cdp, METRICS_EXPR);

  // 机械一致性断言（P1 重设计后：金环色芯 16px + 左上「你」字标 + 审判者紫）
  const m = res.metrics;
  const expectTone = target === 'secret-order' ? 'order' : target;
  m.factionTextOk = m.identityText !== null && m.identityText.includes(FACTION_TEXT[target]);
  m.toneOk = m.bg === TONE_RGB[expectTone];
  m.ringOk = m.border === GOLD_RING;
  m.cornerOk = m.pos === 'absolute' && m.top === '-8px' && m.right === '-8px';
  m.ariaOk = m.aria === `你的真实阵营：${FACTION_TEXT[target]}`;
  m.onlySelfOk = m.badgesOnOthers === 0;
  m.dotOk = m.rect && m.rect.w === 16 && m.rect.h === 16;
  m.tagOk = m.selfTagText === '你' && m.selfTagsOnOthers === 0;
  res.pass = m.hasBadge && m.factionTextOk && m.toneOk && m.ringOk && m.cornerOk && m.ariaOk && m.onlySelfOk && m.dotOk && m.tagOk;

  await shot(cdp, `board-${target}-1440.png`);
  const sr = m.seatRect;
  await shot(cdp, `self-seat-${target}.png`, {
    x: Math.max(0, Math.floor(sr.x - 12)), y: Math.max(0, Math.floor(sr.y - 12)),
    width: Math.ceil(sr.width + 24), height: Math.ceil(sr.height + 24), scale: 3,
  });

  // 图例浮层：第三条短注 + 三色圆点示意
  await evalJS(cdp, `(() => { const b = document.querySelector('.room-header .help-button'); if (b) b.click(); return !!b; })()`);
  res.overlay = await waitForExpr(cdp, `!!document.querySelector('.modal.rules-modal')`, 6000);
  if (res.overlay) {
    await sleep(350);
    // 滚动到短注区再取证（浮层内竖向滚动，否则短注不在视口内）
    await evalJS(cdp, `(() => { const n = document.querySelector('ul.clue-notes'); if (n) n.scrollIntoView({ block: 'center' }); return !!n; })()`);
    await sleep(350);
    res.legend = await evalJS(cdp, `(() => {
      const note = [...document.querySelectorAll('ul.clue-notes > li.clue-note')].find(li => li.textContent.includes('真实阵营色徽'));
      if (!note) return { found: false };
      const dots = [...note.querySelectorAll('.self-badge-demo .true-color-badge')].map(d => getComputedStyle(d).backgroundColor);
      const nr = note.getBoundingClientRect();
      return { found: true, dots, text: note.textContent.includes('允许与你的徽记矛盾'), rect: { x: nr.left, y: nr.top, width: nr.width, height: nr.height } };
    })()`);
    await shot(cdp, `legend-${target}-1440.png`);
    if (res.legend && res.legend.found) {
      const lr = res.legend.rect;
      await shot(cdp, `legend-note-${target}.png`, {
        x: Math.max(0, Math.floor(lr.x - 8)), y: Math.max(0, Math.floor(lr.y - 8)),
        width: Math.ceil(lr.width + 16), height: Math.ceil(lr.height + 16), scale: 2,
      });
    }
    await evalJS(cdp, `(() => { const b = document.querySelector('.modal.rules-modal .rules-close'); if (b) b.click(); return true; })()`);
    const closed = await waitForExpr(cdp, `!document.querySelector('.modal.rules-modal')`, 4000);
    if (!closed) throw new Error(`[${target}] 图例浮层未关闭`);
    await sleep(250);
  }

  // 窄屏 390：网格分支下色徽仍应贴角
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await sleep(500);
  res.mobile = await evalJS(cdp, METRICS_EXPR);
  const mb = res.mobile;
  const expectToneM = target === 'secret-order' ? 'order' : target;
  res.mobileOk = mb.hasBadge && mb.badgesOnOthers === 0 && mb.pos === 'absolute' && mb.top === '-8px' && mb.right === '-8px'
    && mb.bg === TONE_RGB[expectToneM] && mb.border === GOLD_RING && mb.aria === `你的真实阵营：${FACTION_TEXT[target]}`
    && mb.selfTagText === '你' && mb.selfTagsOnOthers === 0;
  await shot(cdp, `board-${target}-390.png`);
  return res;
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const rooms = JSON.parse(fs.readFileSync(path.join(DIR, 'state.json'), 'utf-8'));
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const chrome = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check',
    '--headless=new', '--disable-gpu', '--window-size=1440,950', 'about:blank',
  ], { stdio: 'ignore' });
  await sleep(1200);

  const pages = await fetch(`http://127.0.0.1:${PORT}/json/list`).then(r => r.json());
  const page = pages.find(p => p.type === 'page');
  if (!page) throw new Error('no page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const cdp = new CDP(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  const results = [];
  try {
    for (const target of Object.keys(rooms)) {
      results.push(await runRoom(cdp, target, rooms[target]));
    }
  } finally {
    try { cdp.ws.close(); } catch (e) {}
    try { chrome.kill(); } catch (e) {}
  }
  fs.writeFileSync(path.join(DIR, 'result.json'), JSON.stringify(results, null, 2));
  for (const r of results) {
    console.log(`[${r.target}] pass=${r.pass} overlay=${r.overlay} legendFound=${r.legend && r.legend.found} mobileOk=${r.mobileOk}`);
    if (!r.pass) console.log('  ', JSON.stringify(r.metrics));
  }
  const allPass = results.every(r => r.pass && r.overlay && r.legend && r.legend.found && r.legend.dots && r.legend.dots.length === 3 && r.mobileOk);
  console.log(allPass ? 'ALL PASS' : 'HAS FAILURE');
  process.exit(allPass ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(2); });
