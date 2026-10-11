import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const URL = "http://127.0.0.1:8000/?room=561593&name=%E9%98%BF%E4%B8%91";
const OUT = "D:/AIProj/bloodkill/.scratch/e2e-inspect/verify";
const proc = spawn(CHROME, ["--headless=new","--disable-gpu","--no-sandbox","--remote-debugging-port=9334","--user-data-dir=D:/AIProj/bloodkill/.scratch/headless-profile-cdp2","--force-device-scale-factor=1","--window-size=1440,950","about:blank"],{stdio:"ignore"});
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const l=await(await fetch("http://127.0.0.1:9334/json/list")).json();const p=l.find(t=>t.type==="page");if(p)return p.webSocketDebuggerUrl;}catch{}await sleep(250);}throw new Error("no devtools");}
const ws=new WebSocket(await getWs());
await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
let id=1;const pend=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pend.has(m.id)){const{resolve,reject}=pend.get(m.id);pend.delete(m.id);m.error?reject(new Error(JSON.stringify(m.error))):resolve(m.result);}};
const send=(method,params={})=>{const i=id++;ws.send(JSON.stringify({id:i,method,params}));return new Promise((resolve,reject)=>pend.set(i,{resolve,reject}));};
const evalJs=async ex=>{const r=await send("Runtime.evaluate",{expression:ex,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails).slice(0,300));return r.result.value;};
const shot=async p=>{const r=await send("Page.captureScreenshot",{format:"png"});writeFileSync(p,Buffer.from(r.data,"base64"));console.log("SHOT",p);};
await send("Page.enable");await send("Runtime.enable");
await send("Page.navigate",{url:URL});
for(let i=0;i<60;i++){await sleep(500);if(await evalJs("document.querySelectorAll('.seat').length").catch(()=>0))break;}
await sleep(1500);
await evalJs("document.querySelector('.help-button').click()");
await sleep(700);
const info=await evalJs(`(() => {
  const notes=[...document.querySelectorAll('.clue-notes .clue-note')].map(li=>({
    title:(li.querySelector('strong')||{}).textContent,
    text:li.querySelector('.note-text').textContent,
    badges:[...li.querySelectorAll('.fact-badge')].map(b=>{const s=getComputedStyle(b);return{cls:b.className,text:b.textContent.trim(),bg:s.backgroundColor,w:s.width,h:s.height,hasEye:!!b.querySelector('.fact-eye')};}),
    others:[...li.querySelectorAll('.true-color-badge,.slot-demo')].length
  }));
  const inspect=notes.find(n=>(n.title||'').includes('检视标记'));
  let rect=null;
  if(inspect){const li=[...document.querySelectorAll('.clue-notes .clue-note')].find(l=>l.querySelector('strong')&&l.querySelector('strong').textContent.includes('检视标记'));li.scrollIntoView({block:'center'});const b=li.getBoundingClientRect();rect={x:b.x,y:b.y,w:b.width,h:b.height};}
  const overlayClass=(document.querySelector('#rules-title')||{}).closest('[role=dialog]')?.className;
  return JSON.stringify({notes,inspectRect:rect,overlayClass,overlayOpen:!!document.querySelector('[role=dialog]')});
})()`);
writeFileSync(`${OUT}/legend-notes.json`,info);
await sleep(400);
await shot(`${OUT}/legend-inspect-note-1440.png`);
console.log(info);
console.log("DONE");ws.close();proc.kill();process.exit(0);
