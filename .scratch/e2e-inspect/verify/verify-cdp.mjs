import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const URL = "http://127.0.0.1:8000/?room=561593&name=%E9%98%BF%E4%B8%91";
const PORT = 9333;
const OUT = "D:/AIProj/bloodkill/.scratch/e2e-inspect/verify";

const proc = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--no-sandbox",
  `--remote-debugging-port=${PORT}`,
  "--user-data-dir=D:/AIProj/bloodkill/.scratch/headless-profile-cdp",
  "--force-device-scale-factor=1", "--window-size=1440,950",
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function getTargetWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.find(t => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error("devtools endpoint not reachable");
}

const ws = new WebSocket(await getTargetWs());
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let nextId = 1;
const pending = new Map();
const events = [];
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  } else if (msg.method) events.push(msg);
};

function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evalJs(expression, awaitPromise = false) {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) throw new Error("page eval failed: " + JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result.value;
}

async function shot(path) {
  const r = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(path, Buffer.from(r.data, "base64"));
  console.log("SHOT", path);
}

await send("Page.enable");
await send("Runtime.enable");

// ---- navigate and wait for board ----
await send("Page.navigate", { url: URL });
let seats = 0;
for (let i = 0; i < 60; i++) {
  await sleep(500);
  seats = await evalJs("document.querySelectorAll('.seat').length").catch(() => 0);
  if (seats > 0) break;
}
console.log("SEATS", seats);
await sleep(1200); // let websocket state settle fully

const GEOM = `(() => {
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return { x: +b.x.toFixed(1), y: +b.y.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1), right: +b.right.toFixed(1), bottom: +b.bottom.toFixed(1) }; };
  return JSON.stringify({
    overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    vw: innerWidth, vh: innerHeight,
    seats: [...document.querySelectorAll('.seat')].map(seat => {
      const fact = seat.querySelector(':scope > .fact-badge');
      const memo = seat.querySelector(':scope > .memo-badge');
      const eye = fact ? fact.querySelector('.fact-eye') : null;
      const cs = fact ? getComputedStyle(fact) : null;
      const ecs = eye ? getComputedStyle(eye) : null;
      return {
        name: (seat.querySelector('.seat-name')||{textContent:'?'}).textContent.trim(),
        seat: r(seat),
        self: !!seat.querySelector(':scope > .self-tag'),
        fact: fact ? {
          rect: r(fact), title: fact.title, ariaLabel: fact.getAttribute('aria-label'),
          label: fact.textContent.replace(/\s+/g,''),
          bg: cs.backgroundColor, color: cs.color, border: cs.borderColor + ' ' + cs.borderWidth,
          font: cs.fontSize + ' ' + cs.fontWeight,
          shadow: cs.boxShadow,
          eye: eye ? { rect: r(eye), bg: ecs.backgroundColor, border: ecs.borderColor, hasSvg: !!eye.querySelector('svg'), svgRect: r(eye.querySelector('svg')) } : null
        } : null,
        memo: memo ? { rect: r(memo), cls: memo.className, title: memo.title } : null
      };
    })
  });
})()`;

const geomDesktop = await evalJs(GEOM);
writeFileSync(`${OUT}/geom-1440.json`, geomDesktop);
console.log("GEOM-DESKTOP saved");

await shot(`${OUT}/board-cdp-1440x950.png`);

// ---- open help overlay, scroll to legend ----
await evalJs("document.querySelector('.help-button').click()");
await sleep(600);
const legendInfo = await evalJs(`(() => {
  const h = document.getElementById('rules-legend');
  if (!h) return JSON.stringify({ found: false });
  const rows = [...document.querySelectorAll('.legend-list .legend-row')].map(row => ({
    name: (row.querySelector('.legend-name')||{}).textContent,
    desc: (row.querySelector('.legend-desc')||{}).textContent,
    badges: [...row.querySelectorAll('.fact-badge')].map(b => {
      const s = getComputedStyle(b);
      return { cls: b.className, text: b.textContent.trim(), bg: s.backgroundColor, hasEye: !!b.querySelector('.fact-eye') };
    })
  }));
  const modal = document.querySelector('.rules-modal');
  modal.scrollTop = modal.scrollHeight; // ensure inner scroll container
  h.scrollIntoView({ block: 'start' });
  const body = document.querySelector('.rules-body');
  if (body) body.scrollTop = h.offsetTop - body.offsetTop - 8;
  return JSON.stringify({ found: true, rows, overlayVisible: !!document.querySelector('.rules-overlay') });
})()`);
writeFileSync(`${OUT}/legend.json`, legendInfo);
await sleep(400);
await shot(`${OUT}/legend-rules-1440.png`);

// close overlay
await evalJs("document.querySelector('.rules-close').click()");
await sleep(300);

// ---- mobile viewport ----
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await sleep(800);
const geomMobile = await evalJs(GEOM);
writeFileSync(`${OUT}/geom-390.json`, geomMobile);
console.log("GEOM-MOBILE saved");
await shot(`${OUT}/board-cdp-390x844.png`);

console.log("DONE");
ws.close();
proc.kill();
process.exit(0);
