import { memo } from "react";
import type { GameState, Identity, PendingView, PlayerView } from "./types";
import { displayClueIcon, displayFaction, displayRank, displayResource } from "./types";

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
        <span key={name} title={displayResource(name)}>
          {RESOURCE_ICONS[name] ?? name}×{count}
        </span>
      ))}
    </div>
  );
}

// 每名玩家恰好三张线索 token：1 等级 + 2 身份标记（组合由等级决定）。
// 槽位填亮数与伤害严格同步（唯一 +1 在 _continue_damage、唯一 -1 是炼金归还，二者同动），
// 因此填亮的槽位本身就是伤害计数（issue 23 裁决）。
const MARKER_DOTS: Record<string, { label: string; tone: string; name: string }> = {
  rose: { label: "玫", tone: "rose", name: "玫瑰家族标记" },
  beast: { label: "兽", tone: "beast", name: "野兽家族标记" },
  unknown: { label: "？", tone: "unknown", name: "未知标记" },
};

function ClueSlots({
  player,
  selfMarkers,
  selfRank,
  highlight,
}: {
  player: PlayerView;
  selfMarkers?: string[];
  selfRank?: number | string;
  highlight?: string[];
}) {
  const hot = new Set(highlight ?? []);
  const slots: { token: string; className: string; label: string; title: string }[] = [];
  const described: string[] = [];
  if (player.revealed.rank !== undefined) {
    const rank = player.revealed.rank;
    slots.push({
      token: "rank",
      className: "slot tile filled",
      label: rank === "fleur-cross" ? "审" : String(rank),
      title: displayRank(rank),
    });
    described.push(`已亮出${displayRank(rank)}`);
  } else {
    const dim = selfRank === undefined ? "" : selfRank === "fleur-cross" ? "审" : String(selfRank);
    slots.push({ token: "rank", className: `slot tile empty${dim ? " dim" : ""}`, label: dim, title: "未亮出的等级" });
  }
  player.revealed.markers.forEach((marker, index) => {
    const token = `marker-${index}`;
    if (marker !== null) {
      const dot = MARKER_DOTS[marker] ?? { label: "？", tone: "unknown", name: String(marker) };
      slots.push({ token, className: `slot dot filled ${dot.tone}`, label: dot.label, title: dot.name });
      described.push(`已亮出${dot.name}`);
    } else {
      const raw = selfMarkers?.[index];
      if (raw === "wild") {
        slots.push({ token, className: "slot dot empty dim", label: "任", title: "未亮出的任选标记（亮出时自选红/蓝）" });
      } else if (raw && MARKER_DOTS[raw]) {
        slots.push({ token, className: "slot dot empty dim", label: MARKER_DOTS[raw].label, title: `未亮出的${MARKER_DOTS[raw].name}` });
      } else {
        slots.push({ token, className: "slot dot empty", label: "", title: "未亮出的身份标记" });
      }
    }
  });
  return (
    <div
      className="clue-slots"
      role="img"
      aria-label={`受到 ${player.damage} 点伤害${described.length ? `，${described.join("，")}` : "，尚未亮出线索"}`}
    >
      {slots.map((slot) => (
        <span key={slot.token} className={`${slot.className}${hot.has(slot.token) ? " hot" : ""}`} title={slot.title}>
          {slot.label}
        </span>
      ))}
    </div>
  );
}

const Seat = memo(function Seat({
  player,
  dagger,
  identity,
  clueLine,
  selfMarkers,
  highlight,
}: {
  player: PlayerView;
  dagger: boolean;
  identity?: Identity;
  clueLine?: string;
  selfMarkers?: string[];
  highlight?: string[];
}) {
  return (
    <article role="listitem" className={`seat${player.captured ? " captured" : ""}${dagger ? " dagger" : ""}`} aria-label={`${player.displayName}${player.captured ? "，已被捕获" : ""}`}>
      <div className="seat-name">
        {dagger && (
          <span className="dagger-icon" title="持有匕首">
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
      {identity && clueLine && <div className="own-clue-icon">{clueLine}</div>}
      <ClueSlots player={player} selfMarkers={selfMarkers} selfRank={identity?.rank} highlight={highlight} />
      <Resources resources={player.resources} />
    </article>
  );
});

function PendingBanner({ pending, players }: { pending: PendingView; players: PlayerView[] }) {
  if (pending.kind === "intervention") {
    const target = nameOf(players, pending.targetPlayerId);
    const responses = pending.responses ?? {};
    if (pending.stage === "choice") {
      const volunteers = (pending.volunteerPlayerIds ?? []).map((id) => nameOf(players, id)).join("、");
      return (
        <div className="pending">
          <strong>{target}</strong> 被攻击，{volunteers} 愿意挡刀，等待其选择其一或全部拒绝。
        </div>
      );
    }
    const answered = pending.eligiblePlayerIds.filter((id) => responses[id] !== undefined);
    const waiting = pending.eligiblePlayerIds.filter((id) => responses[id] === undefined);
    const summary = answered.length
      ? answered.map((id) => `${nameOf(players, id)}（${responses[id] ? "挡刀" : "不干涉"}）`).join("、")
      : "暂无表态";
    return (
      <div className="pending">
        <strong>{target}</strong> 被攻击，干涉投票进行中：{summary}
        {waiting.length > 0 ? `；等待 ${waiting.map((id) => nameOf(players, id)).join("、")} 表态。` : "。"}
      </div>
    );
  }
  if (pending.kind === "skill") {
    return (
      <div className="pending">
        <strong>{nameOf(players, pending.actorPlayerId)}</strong> 的技能窗口已开启
        {typeof pending.rank === "number" || pending.rank === "fleur-cross" ? `（${displayRank(pending.rank)}）` : ""}。
      </div>
    );
  }
  if (pending.kind === "reveal") {
    return (
      <div className="pending">
        <strong>{nameOf(players, pending.actorPlayerId)}</strong> 必须展示一个身份标记。
      </div>
    );
  }
  return null;
}

function ResultBanner({ result, players }: { result: NonNullable<GameState["result"]>; players: PlayerView[] }) {
  const explanation = ({
    "game.end.captured-leader": "敌方领袖被捕获",
    "game.end.captured-player": "普通玩家被捕获",
    "game.end.inquisitor-captured": "审判者被捕获",
    "game.end.inquisitor-active-capture": "审判者主动捕获目标",
  } as Record<string, string>)[result.explanationKey] ?? "规则结算";
  return (
    <div className="result">
      <strong>对局结束，{displayFaction(result.winner)}获胜</strong>（{explanation}）
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

// 亮牌 / 归还标记窗口：当事玩家的可选槽位高亮（甲）。
function highlightFor(pending: PendingView | null, playerId: string): string[] | undefined {
  if (!pending) return undefined;
  if (pending.kind !== "reveal" && pending.kind !== "token-return") return undefined;
  if (pending.actorPlayerId !== playerId) return undefined;
  return pending.eligibleTokens;
}

export function Board({ game }: { game: GameState }) {
  const viewer = game.viewer;
  const viewerId = viewer?.playerId ?? null;
  const clueLine = viewer
    ? `你的徽记：${displayClueIcon(viewer.clueIcon)}${
        viewer.seenNeighbourClue ? ` · 已看到 ${nameOf(game.players, viewer.seenNeighbourClue.playerId)} 的：${displayClueIcon(viewer.seenNeighbourClue.icon)}` : ""
      }`
    : undefined;
  return (
    <section className="board" aria-label="对局桌面">
      {game.status === "ended" && game.result && <ResultBanner result={game.result} players={game.players} />}
      {game.pending && <PendingBanner pending={game.pending} players={game.players} />}
      <div className="players" role="list" aria-label="玩家座位">
        {game.players.map((player) => (
          <Seat
            key={player.playerId}
            player={player}
            dagger={game.daggerHolderId === player.playerId}
            identity={viewerId === player.playerId ? viewer?.identity : undefined}
            clueLine={viewerId === player.playerId ? clueLine : undefined}
            selfMarkers={viewerId === player.playerId ? viewer?.identityMarkers : undefined}
            highlight={highlightFor(game.pending, player.playerId)}
          />
        ))}
      </div>
    </section>
  );
}
