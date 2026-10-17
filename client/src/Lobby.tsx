import { useEffect, useRef, useState } from "react";
import { HowToPlayBlock } from "./HelpOverlay";
import type { Account } from "./AccountEntry";

export interface RoomCredentials { code: string; accountId: string; mode: "player" | "spectator"; }
interface ExistingRoom { code: string; status: string; }

/** 服务端错误帧解析出的结构化错误：携带错误码与消息，用于与网络失败等本地异常区分（工单 03）。 */
export class ServerApiError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "ServerApiError";
  }
}

export function Lobby({ onJoin, onReplay, account }: { onJoin: (c: RoomCredentials) => void; onReplay: () => void; account: Account }) {
  const [joinCode, setJoinCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [existing, setExisting] = useState<ExistingRoom | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);
  const lookupGeneration = useRef(0);

  async function refreshRoom() {
    const generation = ++lookupGeneration.current;
    try {
      const response = await fetch("/api/account/room", { credentials: "same-origin" });
      if (response.ok) { const body = await response.json(); if (generation === lookupGeneration.current) setExisting(body.room); }
    } catch { /* 创建请求的错误仍可见，并保留再次查询入口。 */ }
  }
  useEffect(() => { void refreshRoom(); }, [account.accountId]);
  const enter = (code: string, mode: RoomCredentials["mode"] = "player") => onJoin({ code, accountId: account.accountId, mode });
  const createRoom = async () => {
    if (submitting.current) return;
    submitting.current = true;
    lookupGeneration.current += 1;
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/rooms", { method: "POST", credentials: "same-origin" });
      const data = await response.json();
      if (!response.ok) {
        if (data.details?.roomCode) setExisting({ code: data.details.roomCode, status: "waiting" });
        throw new ServerApiError(String(data.code ?? ""), data.message ?? "创建房间失败，请稍后重试。");
      }
      enter(data.code);
    } catch (err) {
      setError(err instanceof ServerApiError ? err.message : "创建房间失败，请查询已有房间或重试。");
      await refreshRoom();
    } finally { submitting.current = false; setBusy(false); }
  };
  const joinRoom = (mode: RoomCredentials["mode"]) => {
    const code = joinCode.trim();
    if (!/^\d{6}$/.test(code)) { setError("请输入六位数字房间号。"); return; }
    enter(code, mode);
  };
  return <div className="lobby" aria-labelledby="lobby-title">
    <h1 id="lobby-title">鲜血盟约</h1>
    <div className="lobby-actions">
      {existing && <button disabled={busy} onClick={() => enter(existing.code)}>返回房间 {existing.code}</button>}
      <button disabled={busy} onClick={createRoom}>创建房间</button>
      <label className="field" htmlFor="room-code">房间号<input id="room-code" value={joinCode} onChange={e => setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6位数字房间号" inputMode="numeric" autoComplete="off" /></label>
      {/* 工单 16：已有未结束房间的账号不能同时旁观（前端看守；跨设备由服务端校验兜底）。 */}
      <div className="lobby-actions"><button disabled={busy} onClick={() => joinRoom("player")}>加入房间</button><button disabled={busy || !!existing} onClick={() => joinRoom("spectator")}>旁观</button></div>
      {existing && <p className="hint" role="status">你已有未结束房间，不能同时旁观其他对局；可返回原房间，已结束的对局仍可观看回放。</p>}
      <button onClick={onReplay}>观看回放</button>
    </div>
    {error && <div className="error" role="alert" aria-live="assertive">{error}<button disabled={busy} onClick={() => void refreshRoom()}>查询已有房间</button></div>}
    <HowToPlayBlock />
    <p className="hint">使用当前账号创建或加入房间。邀请好友时分享六位房间号。</p>
  </div>;
}
