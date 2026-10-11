import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
const CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe";
const URL="http://127.0.0.1:8000/?room=561593&name=%E9%98%BF%E4%B8%91";
const OUT="D:/AIProj/bloodkill/.scratch/e2e-inspect/verify";
const proc=spawn(CHROME,["--headless=new","--disable-gpu","--no-sandbox","--remote-debugging-port=9335","--user-data-dir=D:/AIProj/bloodkill/.scratch/headless-profile-cdp3","--window-size=1440,950","about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const l=await(await fetch("http://127.0.0.1:9335/json/list")).json();const p=l.find(t=>t.type==="page");if(p)return p.webSocketDebuggerUrl;}catch{}await sleep(250);}throw new Error("no devtools");}
const ws=new WebSocket(await getWs());
await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
let id=1;const pend=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pend.has(m.id)){const{resolve,reject}=pend.get(m.id);pend.delete(m.id);m.error?reject(new Error(JSON.stringify(m.error))):resolve(m.result);}};
const send=(m,p={})=>{const i=id++;ws.send(JSON.stringify({id:i,method:m,params:p}));return new Promise((resolve,reject)=>pend.set(i,{resolve,reject}));};
const evalJs=async ex=>{const r=await send("Runtime.evaluate",{expression:ex,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails).slice(0,300));return r.result.value;};
const shot=async p=>{const r=await send("Page.captureScreenshot",{format:"png"});writeFileSync(p,Buffer.from(r.data,"base64"));console.log("SHOT",p);};
await send("Page.enable");await send("Runtime.enable");
await send("Page.navigate",{url:URL});
for(let i=0;i<60;i++){await sleep(500);if(await evalJs("document.querySelectorAll('.seat').length").catch(()=>0))break;}
await sleep(1500);
await send("Emulation.setDeviceMetricsOverride",{width:1440,height:950,deviceScaleFactor:1,mobile:false});
await sleep(600);
await shot(`${OUT}/board-final-1440x950.png`);
const text=await evalJs(`(() => {
  const texts=new Set();
  document.querySelectorAll('button, .status, .hint, label, .seat-name, h1,h2,h3,h4, .legend-name, .note-text strong, [title]').forEach(el=>{
    const t=(el.textContent||'').trim(); if(t) texts.add(t);
    const ti=el.getAttribute('title'); if(ti) texts.add('[title]'+ti);
    const al=el.getAttribute('aria-label'); if(al) texts.add('[aria]'+al);
  });
  return JSON.stringify([...texts].filter(t=>t.length<60));
})()`);
writeFileSync(`${OUT}/ui-texts.json`,text);
console.log("TEXTS saved");
console.log("DONE");ws.close();proc.kill();process.exit(0);
