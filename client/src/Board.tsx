import type { GameState, Identity, PendingView, PlayerView } from "./types";
import { displayFaction, displayRank } from "./types";

// The shared projection component: the live game and the replay render the
// exact same projection shape through this board.

function nameOf(players: PlayerView[], playerId: string | null | undefined): string {
  const player = players.find((p) => p.playerId === playerId);
  return player ? player.displayName : "?";
}

const RESOURCE_ICONS: Record<string, string> = {
  quill: "🪶",
  shield: "🛡",
  sword: "⚔",
  staff: "🪄",
  fan: "🌀",
};

function Resources({ resources }: { resources: Record<string, number> }) {
  const held = Object.entries(resources).filter(([, count]) => count > 0);
  if (held.length === 0) return null;
  return (
    <div className="resources">
      {held.map(([name, count]) => (
        <span key={name} title={name}>
          {RESOURCE_ICONS[name] ?? name}×{count}
        </span>
      ))}
    </div>
  );
}

function Seat({ player, dagger, identity }: { player: PlayerView; dagger: boolean; identity?: Identity }) {
  const clues: string[] = [];
  if (player.revealed.rank !== undefined) clues.push(displayRank(player.revealed.rank));
  player.revealed.markers.forEach((marker) => {
    if (marker !== null) clues.push(displayFaction(marker));
  });
  return (
    <div className={`seat${player.captured ? " captured" : ""}${dagger ? " dagger" : ""}`}>
      <div className="seat-name">
        {dagger && (
          <span className="dagger-icon" title="holds the dagger">
            🗡️
          </span>
        )}
        {player.displayName}
        {identity && (
          <span className="own-identity">
            {" "}
            ({displayFaction(identity.faction)} · {displayRank(identity.rank)})
          </span>
        )}
      </div>
      <div className="damage" aria-label={`${player.damage} damage`}>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={i < player.damage ? "pip filled" : "pip"} />
        ))}
      </div>
      {clues.length > 0 && <div className="revealed">{clues.join(" · ")}</div>}
      <Resources resources={player.resources} />
    </div>
  );
}

function PendingBanner({ pending, players }: { pending: PendingView; players: PlayerView[] }) {
  if (pending.kind === "intervention") {
    const target = nameOf(players, pending.targetPlayerId);
    const eligible = pending.eligiblePlayerIds.map((id) => nameOf(players, id)).join(", ");
    return (
      <div className="pending">
        <strong>{target}</strong> was attacked and may ask someone to intervene or decline. Eligible
        responders: {eligible || "nobody"}.
      </div>
    );
  }
  if (pending.kind === "skill") {
    return (
      <div className="pending">
        <strong>{nameOf(players, pending.actorPlayerId)}</strong>&rsquo;s skill window is open
        {typeof pending.rank === "number" ? ` (rank ${pending.rank})` : ""}.
      </div>
    );
  }
  if (pending.kind === "reveal") {
    return (
      <div className="pending">
        <strong>{nameOf(players, pending.actorPlayerId)}</strong> must reveal one identity marker.
      </div>
    );
  }
  return null;
}

function ResultBanner({ result, players }: { result: NonNullable<GameState["result"]>; players: PlayerView[] }) {
  return (
    <div className="result">
      <strong>Game over — {displayFaction(result.winner)} wins</strong> ({result.explanationKey})
      {result.ranking.length > 0 && (
        <ol className="ranking">
          {result.ranking.map((entry) => (
            <li key={entry.playerId}>{nameOf(players, entry.playerId)}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function Board({ game }: { game: GameState }) {
  const viewerId = game.viewer?.playerId ?? null;
  return (
    <div className="board">
      {game.status === "ended" && game.result && <ResultBanner result={game.result} players={game.players} />}
      {game.pending && <PendingBanner pending={game.pending} players={game.players} />}
      <div className="players">
        {game.players.map((player) => (
          <Seat
            key={player.playerId}
            player={player}
            dagger={game.daggerHolderId === player.playerId}
            identity={viewerId === player.playerId ? game.viewer?.identity : undefined}
          />
        ))}
      </div>
    </div>
  );
}
