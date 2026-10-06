import { useEffect, useRef, useState } from "react";

/** 对齐服务端墙钟，每秒刷新干涉与单人决策窗口的倒计时。 */
export function useDeadlineSeconds(deadline: number | null | undefined, serverTime: number | undefined) {
  const offsetRef = useRef(0);
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => { if (typeof serverTime === "number") offsetRef.current = serverTime - Date.now() / 1000; }, [serverTime]);
  useEffect(() => {
    if (deadline == null) { setRemaining(null); return; }
    const tick = () => setRemaining(Math.max(0, Math.round(deadline - (Date.now() / 1000 + offsetRef.current))));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);
  return remaining;
}
