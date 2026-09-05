import { useCallback, useEffect, useState } from "react";
import type { GameState } from "./types";

// 备忘标记（ADR 0004）：玩家私有 UI 状态，只存本机 localStorage，
// 不进命令、投影或事件——服务端不可见、不存储、不校验。

export type MemoColor = "rose" | "beast" | "gray";
export type MemoMark = number | "审";

/** 选择器单次点选的增量：只改颜色或只改数字（"审"与数字互斥，共用 mark 字段） */
export type MemoPatch = { color?: MemoColor; mark?: MemoMark };

export interface MemoEntry {
  /** Q8：角标一旦有内容，颜色恒为三选一，灰为兜底默认 */
  color?: MemoColor;
  /** 数字 1–9 或"审"，二者互斥；缺省 = 只记了颜色 */
  mark?: MemoMark;
  /** 本局被手动编辑或清空过：自动填充不再触碰（Q9 粘性） */
  touched: boolean;
}

/** Q8 单一出处：有内容必有颜色，只记数字时灰兜底；无内容返回 null（空态） */
export function memoColorOf(entry: Partial<MemoEntry> | undefined): MemoColor | null {
  return entry?.color ?? (entry?.mark !== undefined ? "gray" : null);
}

export interface MemoApi {
  markers: Record<string, MemoEntry>;
  change: (playerId: string, patch: MemoPatch) => void;
  clear: (playerId: string) => void;
}

const memoKey = (roomCode: string, gameId: string) => `bloodbound:memo:${roomCode}:${gameId}`;

function readStore(key: string): Record<string, MemoEntry> {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Record<string, MemoEntry>) : {};
  } catch {
    return {};
  }
}

function writeStore(key: string, markers: Record<string, MemoEntry>) {
  try {
    localStorage.setItem(key, JSON.stringify(markers));
  } catch {
    // 隐私模式 / 配额不足：备忘退化为纯内存，不影响对局
  }
}

// 自动填充（Q9）只认可判色的徽记：玫→玫、兽→兽，其余（含空）一律不填。
function clueColor(icon: string | null): MemoColor | null {
  if (icon === "rose") return "rose";
  if (icon === "beast") return "beast";
  return null;
}

/**
 * 备忘状态：按房间码 + gameId 存取，gameId 变化即清空重读；
 * seenNeighbourClue 指向的玩家若完全没有记录，开局自动填其徽记颜色。
 */
export function useMemoMarkers(roomCode: string, game: GameState | null | undefined): MemoApi {
  const gameId = game?.gameId ?? null;
  const [markers, setMarkers] = useState<Record<string, MemoEntry>>({});

  // 首次拿到对局或换局：重读本局存储，并清掉同房间旧局残留
  useEffect(() => {
    if (!gameId) {
      setMarkers({});
      return;
    }
    const key = memoKey(roomCode, gameId);
    for (let i = localStorage.length - 1; i >= 0; i -= 1) {
      const stored = localStorage.key(i);
      if (stored && stored.startsWith(`bloodbound:memo:${roomCode}:`) && stored !== key) {
        localStorage.removeItem(stored);
      }
    }
    setMarkers(readStore(key));
  }, [roomCode, gameId]);

  // 备忘变化落盘；无对局时无处可存
  useEffect(() => {
    if (!gameId) return;
    writeStore(memoKey(roomCode, gameId), markers);
  }, [markers, roomCode, gameId]);

  // 自动填充：仅当该玩家完全没有记录（含已清空）时填色，只填色不填数；
  // gameId 入依赖：换局清空后即使右邻与徽记色与上局完全相同也必须重填
  const neighbourPlayerId = game?.viewer?.seenNeighbourClue?.playerId ?? null;
  const neighbourIcon = game?.viewer?.seenNeighbourClue?.icon ?? null;
  useEffect(() => {
    const color = clueColor(neighbourIcon);
    if (!gameId || !neighbourPlayerId || !color) return;
    setMarkers((current) => {
      if (current[neighbourPlayerId]) return current;
      return { ...current, [neighbourPlayerId]: { color, touched: false } };
    });
  }, [gameId, neighbourPlayerId, neighbourIcon]);

  const change = useCallback((playerId: string, patch: MemoPatch) => {
    setMarkers((current) => {
      const merged = { ...current[playerId], ...patch };
      return { ...current, [playerId]: { ...merged, color: memoColorOf(merged) ?? undefined, touched: true } };
    });
  }, []);

  const clear = useCallback((playerId: string) => {
    // 清空后保留 touched：本局不再被自动重填（Q9）
    setMarkers((current) => ({ ...current, [playerId]: { touched: true } }));
  }, []);

  return { markers, change, clear };
}
