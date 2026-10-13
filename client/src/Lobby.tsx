import { useState } from "react";
import { HowToPlayBlock } from "./HelpOverlay";
import type { Account } from "./AccountEntry";

export interface RoomCredentials { code: string; name: string; token: string | null; }
const NAME_KEY = "bloodbound:name";
const hostTokenKey = (code: string) => `bloodbound:host:${code}`;

export function Lobby({ onJoin, onReplay, account }: { onJoin: (c: RoomCredentials) => void; onReplay: () => void; account?: Account }) {
  const [name, setName] = useState(() => account?.username ?? localStorage.getItem(NAME_KEY) ?? "");
  const [joinCode, setJoinCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const createRoom = async () => {
    if (!name.trim()) { setError("请先输入姓名。"); return; }
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/rooms", { method: "POST" });
      if (!response.ok) throw new Error(`创建房间失败（${response.status}）`);
      const data = (await response.json()) as { code: string; hostToken: string };
      localStorage.setItem(hostTokenKey(data.code), data.hostToken); localStorage.setItem(NAME_KEY, name.trim());
      onJoin({ code: data.code, name: name.trim(), token: data.hostToken });
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const joinRoom = (asSpectator: boolean) => {
    const code = joinCode.trim();
    if (!code || (!asSpectator && !name.trim())) { setError(asSpectator ? "请输入房间号。" : "请输入房间号和姓名。"); return; }
    if (!asSpectator) localStorage.setItem(NAME_KEY, name.trim());
    onJoin({ code, name: asSpectator ? "" : name.trim(), token: localStorage.getItem(hostTokenKey(code)) });
  };
  return <div className="lobby" aria-labelledby="lobby-title">
    <h1 id="lobby-title">鲜血盟约</h1>
    {!account && <label className="field" htmlFor="player-name">姓名<input id="player-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="其他玩家看到的名称" maxLength={32} autoComplete="nickname" aria-invalid={Boolean(error)} /></label>}
    <div className="lobby-actions">
      <button disabled={busy} onClick={createRoom}>创建房间</button>
      <label className="field" htmlFor="room-code">房间号<input id="room-code" value={joinCode} onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6位数字房间号" inputMode="numeric" autoComplete="off" /></label>
      <div className="lobby-actions"><button disabled={busy} onClick={() => joinRoom(false)}>加入房间</button><button disabled={busy} onClick={() => joinRoom(true)}>旁观</button></div>
      <button onClick={onReplay}>观看回放</button>
    </div>
    {error && <div className="error" role="alert" aria-live="assertive">{error}</div>}
    <HowToPlayBlock />
    <p className="hint">使用当前账号创建或加入房间。邀请好友时分享六位房间号。</p>
  </div>;
}
