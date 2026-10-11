import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
const CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe";
const URL="http://127.0.0.1:8000/?room=561593&name=%E9%98%BF%E4%B8%91";
const OUT="D:/AIProj/bloodkill/.scratch/e2e-inspect/verify";
const proc=spawn(CHROME,["--headless=new","--disable-gpu","--no-sandbox","--remote-debugging-port=9336","--user-data-dir=D:/AIProj/bloodkill/.scratch/headless-profile-cdp4","--window-size=1440,950","about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const l=await(await fetch("http://127.0.0.1:9336/json/list")).json();const p=l.find(t=>t.type==="page");if(p)return p.webSocketDebuggerUrl;}catch{}await sleep(250);}throw new Error("no devtools");}
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
const info=await evalJs(`(() => {
  const inter=(a,b)=>!(a.right<=b.x||b.right<=a.x||a.bottom<=b.y||b.bottom<=a.y);
  const g=el=>{const b=el.getBoundingClientRect();return{x:b.x,y:b.y,right:b.right,bottom:b.bottom,w:b.width,h:b.height};};
  const out=[];
  for (const seat of document.querySelectorAll('.seat')) {
    const fact=seat.querySelector(':scope > .fact-badge');
    if (!fact) continue;
    const fr=g(fact), eyeEl=fact.querySelector('.fact-eye');
    const er=eyeEl?g(eyeEl):null;
    const nameEl=seat.querySelector('.seat-name');
    const seatCs=getComputedStyle(seat);
    const items=[];
    for (const el of seat.querySelectorAll('.seat-name,.slot,.resources,.resource,.memo-badge')) {
      const r=g(el); if(!r.w) continue;
      items.push({what:el.className.split(' ').slice(0,2).join('.'),text:(el.textContent||'').trim().slice(0,6),rect:r,
        hitFact:inter(fr,r),hitEye:er?inter(er,r):false});
    }
    out.push({seat:(nameEl||{}).textContent,seatBorder:seatCs.borderWidth,factRect:fr,items});
  }
  const self=document.querySelector('.seat .self-tag');
  return JSON.stringify({pairs:out,selfTag:self?{text:self.textContent.trim(),rect:g(self)}:null});
})()`);
writeFileSync(`${OUT}/overlap.json`,info);
console.log(info);
ws.close();proc.kill();process.exit(0);
