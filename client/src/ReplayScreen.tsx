import { useState } from "react";
import { Board } from "./Board";
import type { GameState } from "./types";

export function ReplayScreen({ onBack }: { onBack: () => void }) {
  const [code, setCode] = useState("");
  const [steps, setSteps] = useState<GameState[] | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/rooms/${encodeURIComponent(code.trim())}/replay`, { credentials: "same-origin" });
      if (!response.ok) {
        // 回放要求登录；界面本身已登录，401 意味着会话失效，引导刷新重新登录。
        if (response.status === 401) { setError("登录已失效，请刷新页面重新登录后再观看回放。"); return; }
        const data = await response.json().catch(() => null);
        setError(data && typeof data.message === "string" && data.message
          ? data.message
          : `加载回放失败（${response.status}），请确认房间号和对局已结束。`);
        return;
      }
      const data = (await response.json()) as { steps: GameState[] }; setSteps(data.steps); setIndex(0);
    } catch { setError("加载回放失败，请稍后重试。"); }
    finally { setBusy(false); }
  };
  if (!steps) return <div className="replay-load">
    <h2>观看已结束对局</h2><p className="hint">服务器保留最近 20 局已结束的对局。</p>
    <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6位数字房间号" inputMode="numeric" />
    <button disabled={busy || !code.trim()} onClick={load}>加载回放</button>
    {error && <div className="error" role="alert" aria-live="assertive">{error}</div>}<button onClick={onBack}>返回大厅</button>
  </div>;
  const step = steps[Math.min(index, steps.length - 1)];
  return <div className="replay"><div className="replay-controls">
    <button disabled={index === 0} onClick={() => setIndex(index - 1)}>上一步</button><span>第 {index + 1} / {steps.length} 步</span>
    <button disabled={index >= steps.length - 1} onClick={() => setIndex(index + 1)}>下一步</button>
    <button onClick={() => { setSteps(null); setIndex(0); }}>选择其他对局</button><button onClick={onBack}>返回大厅</button>
  </div><Board game={step} /></div>;
}
