import { useState } from "react";
import { Board } from "./Board";
import type { Action, GameEvent, GameState, PlayerView, RoomState } from "./types";
import { actionToCommand } from "./types";
import { useGameSocket } from "./useSocket";
import type { RoomCredentials } from "./Lobby";

function nameOf(players: PlayerView[], playerId: string | null | undefined): string {
  const player = players.find((p) => p.playerId === playerId);
  return player ? player.displayName : "?";
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="action-group">
      <span className="action-label">{label}:</span>
      <div className="action-buttons">{children}</div>
    </div>
  );
}

function SkillUse({
  actions,
  players,
  send,
}: {
  actions: Action[];
  players: PlayerView[];
  send: (command: string, payload?: Record<string, unknown>) => void;
}) {
  const withTargets = actions.filter((a) => a.targetPlayerId);
  if (withTargets.length > 0) {
    return (
      <Group label="Use your skill against">
        {withTargets.map((action) => (
          <button
            key={action.targetPlayerId}
            onClick={() => send("choose-skill", { use: true, targetPlayerId: action.targetPlayerId })}
          >
            {nameOf(players, action.targetPlayerId)}
          </button>
        ))}
      </Group>
    );
  }
  return <button onClick={() => send("choose-skill", { use: true })}>Use skill</button>;
}

function CursePicker({ game, send }: { game: GameState; send: (c: string, p?: Record<string, unknown>) => void }) {
  const curses = game.viewer?.cursesToDistribute ?? [];
  const self = game.viewer?.playerId;
  const recipients = game.players.filter((p) => p.playerId !== self && !p.captured);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const ready = curses.length > 0 && curses.every((c) => picks[c]);
  return (
    <div className="curse-picker">
      <p>Secretly give the curse card{curses.length > 1 ? "s" : ""} to:</p>
      {curses.map((curseId) => (
        <select
          key={curseId}
          value={picks[curseId] ?? ""}
          onChange={(e) => setPicks({ ...picks, [curseId]: e.target.value })}
        >
          <option value="">choose…</option>
          {recipients.map((p) => (
            <option key={p.playerId} value={p.playerId}>
              {p.displayName}
            </option>
          ))}
        </select>
      ))}
      <button
        disabled={!ready}
        onClick={() => {
          send("distribute-curse", { assignments: picks });
          setPicks({});
        }}
      >
        Distribute
      </button>
    </div>
  );
}

function ActionsPanel({
  game,
  hostActions,
  send,
  sendHost,
}: {
  game: GameState;
  hostActions: Action[];
  send: (command: string, payload?: Record<string, unknown>) => void;
  sendHost: (action: string) => void;
}) {
  const actions = game.legalActions ?? [];
  const passTargets = actions.filter((a) => a.type === "pass-dagger");
  const attackTargets = actions.filter((a) => a.type === "attack");
  const request = actions.find((a) => a.type === "request-intervention");
  const decline = actions.find((a) => a.type === "decline-intervention");
  const responders = actions.filter((a) => a.type === "choose-intervention");
  const skillUse = actions.filter((a) => a.type === "choose-skill" && a.use);
  const skillDecline = actions.find((a) => a.type === "choose-skill" && a.use === false);
  const curse = actions.find((a) => a.type === "distribute-curse");
  const lockActions = hostActions.filter((a) => a.type === "lock" || a.type === "unlock");

  if (actions.length === 0 && lockActions.length === 0) {
    return <p className="hint">Waiting for the dagger holder to act.</p>;
  }
  return (
    <div className="actions">
      {passTargets.length > 0 && (
        <Group label="Pass the dagger to">
          {passTargets.map((action) => (
            <button
              key={action.targetPlayerId}
              onClick={() => {
                const { command, payload } = actionToCommand(action);
                send(command, payload);
              }}
            >
              {nameOf(game.players, action.targetPlayerId)}
            </button>
          ))}
        </Group>
      )}
      {attackTargets.length > 0 && (
        <Group label="Attack">
          {attackTargets.map((action) => (
            <button
              key={action.targetPlayerId}
              onClick={() => {
                const { command, payload } = actionToCommand(action);
                send(command, payload);
              }}
            >
              {nameOf(game.players, action.targetPlayerId)}
            </button>
          ))}
        </Group>
      )}
      {request && <button onClick={() => send("request-intervention")}>Request intervention</button>}
      {responders.length > 0 && (
        <Group label="Choose who intervenes">
          {responders.map((action) => (
            <button
              key={action.responderPlayerId}
              onClick={() => {
                const { command, payload } = actionToCommand(action);
                send(command, payload);
              }}
            >
              {nameOf(game.players, action.responderPlayerId)}
            </button>
          ))}
        </Group>
      )}
      {decline && <button onClick={() => send("decline-intervention")}>Decline intervention</button>}
      {skillDecline && <button onClick={() => send("choose-skill", { use: false })}>Decline skill</button>}
      {skillUse.length > 0 && <SkillUse actions={skillUse} players={game.players} send={send} />}
      {curse && <CursePicker game={game} send={send} />}
      {lockActions.map((action) => (
        <button key={action.type} onClick={() => sendHost(action.type)}>
          {action.type === "lock" ? "Lock room" : "Unlock room"}
        </button>
      ))}
    </div>
  );
}

function WaitingRoom({
  state,
  sendHost,
  spectating,
}: {
  state: RoomState;
  sendHost: (action: string) => void;
  spectating: boolean;
}) {
  const players = state.game?.players ?? [];
  const canStart = players.length >= 6 && players.length <= 12;
  return (
    <div className="waiting">
      <p>
        Waiting for players ({players.length}/12). Share this code — players only need the code and a
        name.
      </p>
      <ul className="roster">
        {players.map((p) => (
          <li key={p.playerId}>
            {p.displayName}
            {state.connected[p.playerId] ? "" : " (offline)"}
          </li>
        ))}
      </ul>
      {spectating && <p className="hint">You are spectating.</p>}
      {state.isHost && (
        <div className="host-panel">
          <button disabled={!canStart} onClick={() => sendHost("start")}>
            Start game{canStart ? "" : " (need 6–12 players)"}
          </button>
          {state.hostActions
            .filter((a) => a.type === "lock" || a.type === "unlock")
            .map((a) => (
              <button key={a.type} onClick={() => sendHost(a.type)}>
                {a.type === "lock" ? "Lock room" : "Unlock room"}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

function EventLog({ events, players }: { events: GameEvent[]; players?: PlayerView[] }) {
  if (events.length === 0) return null;
  return (
    <details className="log">
      <summary>Event log ({events.length})</summary>
      <ol>
        {events
          .slice(-60)
          .reverse()
          .map((event) => (
            <li key={event.eventId}>
              {event.eventType} {describeEvent(event, players)}
            </li>
          ))}
      </ol>
    </details>
  );
}

function describeEvent(event: GameEvent, players?: PlayerView[]): string {
  const name = (id: unknown) =>
    players?.find((p) => p.playerId === id)?.displayName ?? String(id);
  const payload = event.payload;
  switch (event.eventType) {
    case "PlayerJoined":
      return `${name(payload.playerId)} joined`;
    case "GameStarted":
      return `game started with ${String(payload.playerCount)} players`;
    case "DaggerPassed":
      return `${name(payload.fromPlayerId)} → ${name(payload.toPlayerId)}`;
    case "AttackDeclared":
      return `${name(payload.attackerPlayerId)} attacked ${name(payload.targetPlayerId)}`;
    case "InterventionOpened":
      return `${name(payload.targetPlayerId)} opened intervention`;
    case "InterventionSelected":
      return `${name(payload.responderPlayerId)} intervenes`;
    case "InterventionDeclined":
      return `${name(payload.targetPlayerId)} declined intervention`;
    case "DamageApplied":
      return `${name(payload.targetPlayerId)} took ${String(payload.amount)} damage (${String(payload.source)})`;
    case "ClueRevealed":
      return `${name(payload.playerId)} revealed their ${String(payload.kind)} clue`;
    case "SkillWindowOpened":
      return `${name(payload.playerId)} may use their skill`;
    case "SkillUsed":
      return `${name(payload.playerId)} used their skill`;
    case "SkillDeclined":
      return `${name(payload.playerId)} declined their skill`;
    case "ResourceGranted":
      return `${name(payload.playerId)} gained ${String(payload.resource)}`;
    case "PlayerCaptured":
      return `${name(payload.playerId)} was captured`;
    case "GameEnded":
      return "game ended";
    case "PhaseChanged": {
      const from = payload.from as { kind: string } | undefined;
      const to = payload.to as { kind: string } | undefined;
      return `${from?.kind ?? "?"} → ${to?.kind ?? "?"}`;
    }
    default:
      return "";
  }
}

function Banner({ title, detail, onBack }: { title: string; detail: string; onBack: () => void }) {
  return (
    <div className="banner">
      <h2>{title}</h2>
      <p>{detail}</p>
      <button onClick={onBack}>Back to lobby</button>
    </div>
  );
}

export function GameScreen({ credentials, onLeave }: { credentials: RoomCredentials; onLeave: () => void }) {
  const { state, events, error, closed, reconnecting, takenOver, send, sendHost } = useGameSocket(
    credentials.code,
    credentials.name,
    credentials.token,
  );

  if (takenOver) {
    return (
      <Banner
        title="Seat taken over"
        detail="A new connection with the same name took over this seat. Rejoin with a different name, or reconnect to resume."
        onBack={onLeave}
      />
    );
  }
  if (closed && !state && !reconnecting) {
    return (
      <Banner
        title="Disconnected"
        detail="The connection to the room closed before a game state arrived."
        onBack={onLeave}
      />
    );
  }
  if (error && !state) {
    return <Banner title="Could not join" detail={`${error.code}: ${error.message}`} onBack={onLeave} />;
  }
  if (!state) {
    return <div className="loading">Connecting…</div>;
  }

  const spectating = state.yourPlayerId === null;
  const showTable = state.roomStatus === "playing" || state.roomStatus === "ended";
  return (
    <div className="room">
      <header className="room-header">
        <span>
          Room <strong>{state.roomCode}</strong>
          {state.locked ? " 🔒" : ""} {state.isHost ? "(host)" : ""}
        </span>
        <span className="status">{state.roomStatus}</span>
        {reconnecting && <span className="hint">Reconnecting...</span>}
        <button onClick={onLeave}>Leave</button>
      </header>
      {error && (
        <div className="action-error">
          {error.code}: {error.message}
        </div>
      )}
      {showTable && state.game ? (
        <>
          <Board game={state.game} />
          <ActionsPanel game={state.game} hostActions={state.hostActions} send={send} sendHost={sendHost} />
        </>
      ) : (
        <WaitingRoom state={state} sendHost={sendHost} spectating={spectating} />
      )}
      <EventLog events={events} players={state.game?.players} />
    </div>
  );
}
