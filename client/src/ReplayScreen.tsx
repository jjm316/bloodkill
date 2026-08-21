import { useState } from "react";
import { Board } from "./Board";
import type { GameState } from "./types";

// Replay renders server-computed spectator projections with the same Board
// component the live game uses.
export function ReplayScreen({ onBack }: { onBack: () => void }) {
  const [code, setCode] = useState("");
  const [steps, setSteps] = useState<GameState[] | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/rooms/${encodeURIComponent(code.trim())}/replay`);
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { code?: string } | null;
        setError(body?.code ?? `replay failed (${response.status})`);
        return;
      }
      const data = (await response.json()) as { steps: GameState[] };
      setSteps(data.steps);
      setIndex(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!steps) {
    return (
      <div className="replay-load">
        <h2>Replay a finished game</h2>
        <p className="hint">The server keeps the last 20 finished games.</p>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="6-digit room code"
          inputMode="numeric"
        />
        <button disabled={busy || !code.trim()} onClick={load}>
          Load replay
        </button>
        {error && <div className="error">{error}</div>}
        <button onClick={onBack}>Back to lobby</button>
      </div>
    );
  }

  const step = steps[Math.min(index, steps.length - 1)];
  return (
    <div className="replay">
      <div className="replay-controls">
        <button disabled={index === 0} onClick={() => setIndex(index - 1)}>
          ◀ Prev
        </button>
        <span>
          Step {index + 1} / {steps.length}
        </span>
        <button disabled={index >= steps.length - 1} onClick={() => setIndex(index + 1)}>
          Next ▶
        </button>
        <button
          onClick={() => {
            setSteps(null);
            setIndex(0);
          }}
        >
          Another game
        </button>
        <button onClick={onBack}>Lobby</button>
      </div>
      <Board game={step} />
    </div>
  );
}
