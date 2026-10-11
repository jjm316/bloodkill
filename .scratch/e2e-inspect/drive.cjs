/* e2e-inspect 浏览器驱动：CDP 裸驱动无头 Chrome（仿 ui-true-color/drive.cjs）。
 * 场景由 scene.py 摆好：阿丑（rank 3）技能窗已开、180 秒单人窗口计时中。
 * 本脚本接管阿丑座位，验证修复的两半：
 *   A 选择器 —— 两个下拉 + 禁用态「使用技能」；选满两名不同玩家后可发动；
 *               发出后无 .action-error（原 bug：裸命令被 skill.invalid-target 拒）；
 *   B 事实角标 —— 恰好两枚、只在目标座位、审判者紫「审」/普通玩家阵营色数字、
 *               title 文案、与备忘角标（right:-8）并存且在其左侧（right:22）。
 * 附带：移动端 390 网格分支贴角、图例「检视标记」短注、事件日志「检视了」。
 * 结果写 result.json，截图落 shots/。 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const DIR = 'D:/AIProj/bloodkill/.scratch/e2e-inspect';
const OUT = path.join(DIR, 'shots');
const PROFILE = path.join(os.tmpdir(), 'bloodkill-e2e-inspect-profile');
const PORT = 9338;
const BASE = 'http://127.0.0.1:8000';

const TONE_RGB = {
  rose: 'rgb(142, 39, 35)',   // --rose-bg #8e2723
  beast: 'rgb(51, 96, 143)',  // --beast-bg #33608f
  order: 'rgb(138, 95, 192)', // --order-bg #8a5fc0
};
const FACT_TEXT = { rose: '玫瑰家族', beast: '野兽家族' };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class CDP {
  constructor(ws) {
    this.ws = this.id = 0;
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id); this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.method + ' -> ' + JSON.stringify(msg.error))) : resolve(msg.result || {});
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

/* React 受控 <select>：走原型 value setter + 冒泡 change，React 的委托监听可收到 */
const REACT_SELECT = (sel, value) => `(() => {
  const el = document.querySelector(${JSON.stringify(sel)});
  if (!el) return 'no-element';
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
  setter.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()`;

const BADGE_METRICS = `(() => {
  const seats = [...document.querySelectorAll('.players .seat')];
  const out = [];
  for (const seat of seats) {
    const badge = seat.querySelector(':scope > .fact-badge');
    if (!badge) continue;
    const cs = getComputedStyle(badge);
    const memo = seat.querySelector(':scope > .memo-badge');
    const eye = badge.querySelector('.fact-eye');
    const eyeSvg = eye ? eye.querySelector('svg') : null;
    const br = badge.getBoundingClientRect(), sr = seat.getBoundingClientRect(), mr = memo ? memo.getBoundingClientRect() : null;
    out.push({
      seat: seat.getAttribute('aria-label'),
      self: seat.classList.contains('self'),
      cls: badge.className, text: badge.textContent,
      title: badge.getAttribute('title'), aria: badge.getAttribute('aria-label'),
      bg: cs.backgroundColor, pos: cs.position, top: cs.top, right: cs.right, zIndex: cs.zIndex,
      size: { w: br.width, h: br.height },
      hasEye: !!eyeSvg, eyeSize: eye ? { w: eye.getBoundingClientRect().width, h: eye.getBoundingClientRect().height } : null,
      memoRight: mr ? mr.right : null, badgeRight: br.right,
      leftOfMemo: mr ? br.right < mr.right : null,
      seatRect: { x: sr.left, y: sr.top, w: sr.width, h: sr.height },
    });
  }
  return { badges: out, total: document.querySelectorAll('.fact-badge').length };
})()`;

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const state = JSON.parse(fs.readFileSync(path.join(DIR, 'state.json'), 'utf-8'));
  const [t0, t1] = state.targets;
  const res = { room: state.code, seat: '阿丑', targets: state.targets };

  fs.rmSync(PROFILE, { recursive: true, force: true });
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--window-size=1440,950', 'about:blank',
  ], { stdio: 'ignore' });
  await sleep(1200);
  try {
    const pages = await fetch(`http://127.0.0.1:${PORT}/json/list`).then((r) => r.json());
    const page = pages.find((p) => p.type === 'page');
    if (!page) throw new Error('no page target');
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.addEventListener('open', resolve); ws.addEventListener('error', reject); });
    const cdp = new CDP(ws);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 950, deviceScaleFactor: 1, mobile: false });

    /* ── A 选择器 ── */
    await cdp.send('Page.navigate', { url: `${BASE}/?room=${state.code}&name=${encodeURIComponent('阿丑')}` });
    if (!await waitForExpr(cdp, `!!document.querySelector('.inspect-picker')`)) throw new Error('选择器面板未出现');
    await sleep(400);
    res.selector = await evalJS(cdp, `(() => {
      const selects = [...document.querySelectorAll('.inspect-picker select')];
      const submit = document.querySelector('.inspect-picker .inspect-confirm');
      const options = selects.map(s => [...s.options].map(o => o.value).filter(Boolean));
      return {
        selectCount: selects.length,
        labels: selects.map(s => s.closest('label').textContent.trim()),
        submitText: submit ? submit.textContent : null,
        submitDisabled: submit ? submit.disabled : null,
        candidateCount: options[0] ? options[0].length : 0,
        declineButton: !!([...document.querySelectorAll('.actions button')].find(b => b.textContent === '放弃技能')),
        errorBanner: !!document.querySelector('.action-error'),
      };
    })()`);
    const s = res.selector;
    s.layoutOk = s.selectCount === 2 && s.candidateCount === 6;
    s.submitGateOk = s.submitDisabled === true;
    s.noErrorOk = s.errorBanner === false;
    await shot(cdp, 'selector-1440.png');

    /* 选两名目标（审判者 + 普通玩家）并发动 */
    await evalJS(cdp, REACT_SELECT('#inspect-first', t0.playerId));
    await evalJS(cdp, REACT_SELECT('#inspect-second', t1.playerId));
    await sleep(200);
    res.submitEnabledAfterPick = await evalJS(cdp, `!document.querySelector('.inspect-picker .inspect-confirm').disabled`);
    await evalJS(cdp, `document.querySelector('.inspect-picker .inspect-confirm').click()`);
    if (!await waitForExpr(cdp, `!!document.querySelector('.players .fact-badge')`, 10000)) throw new Error('发动后未见事实角标');
    await sleep(400);

    /* ── B 事实角标 ── */
    res.badges = await evalJS(cdp, BADGE_METRICS);
    const b = res.badges;
    res.badgeChecks = { totalOk: b.total === 2, noneSelf: b.badges.every(x => !x.self) };
    const expectBadge = (x, t) => {
      if (!x) return { found: false };
      const inquisitor = t.faction === 'secret-order';
      const tone = inquisitor ? 'order' : t.faction;
      const mark = inquisitor ? '审' : String(t.rank);
      const title = inquisitor ? '已检视：审判者（仅你可见）' : `已检视：${FACT_TEXT[t.faction]}·等级${t.rank}（仅你可见）`;
      return {
        found: true,
        onSeat: x.seat.includes(t.name),
        toneOk: x.cls === `fact-badge ${tone}`,
        markOk: x.text === mark,
        titleOk: x.title === title && x.aria === title,
        colorOk: x.bg === TONE_RGB[tone],
        posOk: x.pos === 'absolute' && x.top === '-8px' && x.right === '22px',
        sizeOk: Math.round(x.size.w) === 24 && Math.round(x.size.h) === 24,
        eyeOk: x.hasEye && Math.round(x.eyeSize.w) === 13,
        withMemoOk: x.memoRight !== null && x.leftOfMemo === true,
      };
    };
    res.target0 = expectBadge(b.badges.find(x => x.seat.includes(t0.name)), t0);
    res.target1 = expectBadge(b.badges.find(x => x.seat.includes(t1.name)), t1);
    res.errorAfterUse = await evalJS(cdp, `!!document.querySelector('.action-error')`);
    res.skillWindowClosed = await evalJS(cdp, `!document.querySelector('.inspect-picker')`);
    res.logLine = await evalJS(cdp, `(() => {
      const log = document.querySelector('.log');
      return log ? log.textContent.includes('检视了') : false;
    })()`);

    await shot(cdp, 'board-after-1440.png');
    for (const x of b.badges) {
      const sr = x.seatRect;
      await shot(cdp, `seat-${x.seat.split('，')[0]}.png`, {
        x: Math.max(0, Math.floor(sr.x - 12)), y: Math.max(0, Math.floor(sr.y - 12)),
        width: Math.ceil(sr.w + 24), height: Math.ceil(sr.h + 24), scale: 3,
      });
    }

    /* 图例短注 */
    await evalJS(cdp, `document.querySelector('.room-header .help-button').click()`);
    if (await waitForExpr(cdp, `!!document.querySelector('.modal.rules-modal')`, 6000)) {
      await sleep(300);
      await evalJS(cdp, `(() => { const n = document.querySelector('ul.clue-notes'); if (n) n.scrollIntoView({ block: 'center' }); return true; })()`);
      await sleep(300);
      res.legend = await evalJS(cdp, `(() => {
        const note = [...document.querySelectorAll('ul.clue-notes > li.clue-note')].find(li => li.textContent.includes('检视标记'));
        if (!note) return { found: false };
        const r = note.getBoundingClientRect();
        return { found: true, mentionsEye: note.textContent.includes('眼睛角点'), rect: { x: r.left, y: r.top, width: r.width, height: r.height } };
      })()`);
      await shot(cdp, 'legend-1440.png');
      if (res.legend && res.legend.found) {
        const lr = res.legend.rect;
        await shot(cdp, 'legend-note.png', {
          x: Math.max(0, Math.floor(lr.x - 8)), y: Math.max(0, Math.floor(lr.y - 8)),
          width: Math.ceil(lr.width + 16), height: Math.ceil(lr.height + 16), scale: 2,
        });
      }
      await evalJS(cdp, `document.querySelector('.modal.rules-modal .rules-close').click()`);
      await waitForExpr(cdp, `!document.querySelector('.modal.rules-modal')`, 4000);
    }

    /* 移动端 390：网格分支下角标仍贴角、与备忘并存 */
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await sleep(500);
    res.mobile = await evalJS(cdp, BADGE_METRICS);
    const m = res.mobile;
    res.mobileOk = m.total === 2 && m.badges.every(x =>
      x.pos === 'absolute' && x.top === '-8px' && x.right === '22px' && x.leftOfMemo === true);
    await shot(cdp, 'board-mobile-390.png');

    res.pass = s.layoutOk && s.submitGateOk && s.noErrorOk && res.submitEnabledAfterPick
      && res.badgeChecks.totalOk && res.badgeChecks.noneSelf && res.errorAfterUse === false && res.skillWindowClosed
      && res.target0.found && Object.entries(res.target0).every(([k, v]) => k === 'found' || v === true)
      && res.target1.found && Object.entries(res.target1).every(([k, v]) => k === 'found' || v === true)
      && res.mobileOk && res.logLine;
  } finally {
    try { chrome.kill(); } catch (e) { /* 已退出 */ }
  }
  fs.writeFileSync(path.join(DIR, 'result.json'), JSON.stringify(res, null, 2));
  console.log(res.pass ? 'PASS' : 'FAIL');
  if (!res.pass) console.log(JSON.stringify(res, null, 2));
  process.exit(res.pass ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });
