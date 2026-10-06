/* canvas TextMetrics 墨迹探针：测各字体下全角"？"墨迹相对锚点的偏移 */
const fs = require('fs'); const path = require('path'); const os = require('os');
const { spawn } = require('child_process');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PROFILE = path.join(os.tmpdir(), 'bloodkill-font-probe');
const PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { const p = this.pending.get(m.id); this.pending.delete(m.id);
        m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result || {}); } }); }
  send(method, params = {}) { const id = ++this.id;
    return new Promise((res, rej) => { this.pending.set(id, { resolve: res, reject: rej }); this.ws.send(JSON.stringify({ id, method, params })); }); }
}
async function main() {
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const proc = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-sandbox', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  let page = null;
  for (let i = 0; i < 100 && !page; i++) {
    try { const l = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json(); page = l.find(t => t.type === 'page'); } catch (e) {}
    if (!page) await sleep(300);
  }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const cdp = new CDP(ws);
  await cdp.send('Runtime.enable');
  const expr = `(() => {
    const STACK = '"Noto Serif SC", "Source Han Serif SC", STZhongsong, KaiTi, serif';
    const fonts = ['Noto Serif SC', 'Source Han Serif SC', 'STZhongsong', 'KaiTi', 'SimSun', 'NSimSun', 'FangSong', 'SimHei', 'Microsoft YaHei', 'serif'];
    const rows = [];
    for (const f of fonts) {
      const installed = document.fonts.check('16px "' + f + '", serif', '？');
      const c = document.createElement('canvas'); const ctx = c.getContext('2d');
      ctx.font = '700 40px ' + (f === 'serif' ? 'serif' : '"' + f + '"');
      const m = ctx.measureText('？');
      const m2 = ctx.measureText('?');
      rows.push({ font: f, installed,
        advance40: +m.width.toFixed(2),
        inkLeft40: +m.actualBoundingBoxLeft.toFixed(2),
        inkRight40: +m.actualBoundingBoxRight.toFixed(2),
        inkCenterOffset40: +((m.actualBoundingBoxRight - m.actualBoundingBoxLeft) / 2).toFixed(2),
        halfAdvance40: +m2.width.toFixed(2) });
    }
    const c = document.createElement('canvas'); const ctx = c.getContext('2d');
    ctx.font = '700 40px ' + STACK;
    const m = ctx.measureText('？');
    const stack = { advance40: +m.width.toFixed(2), inkLeft40: +m.actualBoundingBoxLeft.toFixed(2), inkRight40: +m.actualBoundingBoxRight.toFixed(2),
      inkCenterOffset40: +((m.actualBoundingBoxRight - m.actualBoundingBoxLeft) / 2).toFixed(2) };
    return { stack, rows };
  })()`;
  const r = await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true });
  console.log(JSON.stringify(r.result.value, null, 1));
  ws.close(); try { proc.kill(); } catch (e) {} await sleep(400);
}
main().then(() => process.exit(0)).catch(e => { console.error('FATAL ' + (e.stack || e)); process.exit(1); });
