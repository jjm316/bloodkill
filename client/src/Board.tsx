import { memo, useEffect, useState } from "react";
import type { Action, GameState, Identity, PendingView, PlayerView } from "./types";
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

const TOKEN_LABELS: Record<string, string> = { rank: "等级标记", "marker-0": "身份标记 1", "marker-1": "身份标记 2" };
const COLOR_LABELS: Record<string, string> = { rose: "玫瑰", beast: "野兽" };
const tokenLabel = (token: string) => TOKEN_LABELS[token] ?? token;

// 浮层的预估尺寸（px）：定位时用于贴边与上下翻转的保守估计。
const PICKER_EST_SIZE = 132;

function ClueSlots({
  player,
  selfMarkers,
  selfRank,
  highlight,
  selfActions,
  onSlotAction,
}: {
  player: PlayerView;
  selfMarkers?: string[];
  selfRank?: number | string;
  highlight?: string[];
  /** 仅自身座位：token -> 该槽位的合法动作（恰 2 个 = wild 标记需选阵营） */
  selfActions?: Record<string, Action[]>;
  onSlotAction?: (action: Action) => void;
}) {
  const [picker, setPicker] = useState<{ token: string; options: Action[]; rect: DOMRect } | null>(null);
  const hot = new Set(highlight ?? []);
  const self = selfActions !== undefined && onSlotAction !== undefined;
  // 浮层跟随 pending 存活：亮牌/归还窗口一旦结算（hot 消失）即视为关闭
  const activePicker = picker && hot.has(picker.token) ? picker : null;
  useEffect(() => {
    if (!activePicker) return;
    const close = () => setPicker(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [activePicker]);

  const pickSlot = (token: string, rect: DOMRect) => {
    const options = selfActions?.[token];
    if (!options || options.length === 0) return;
    if (options.length === 1) {
      onSlotAction?.(options[0]);
      return;
    }
    setPicker({ token, options, rect });
  };

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
    <>
      <div
        className="clue-slots"
        role={self ? "group" : "img"}
        aria-label={`受到 ${player.damage} 点伤害${described.length ? `，${described.join("，")}` : "，尚未亮出线索"}`}
      >
        {slots.map((slot) => {
          const isHot = self && hot.has(slot.token);
          if (!self) {
            return (
              <span key={slot.token} className={`${slot.className}${isHot ? " hot" : ""}`} title={slot.title}>
                {slot.label}
              </span>
            );
          }
          return (
            <button
              key={slot.token}
              type="button"
              className={`${slot.className}${isHot ? " hot" : ""}`}
              aria-label={slot.title}
              disabled={!isHot}
              onClick={(e) => pickSlot(slot.token, e.currentTarget.getBoundingClientRect())}
            >
              {slot.label}
            </button>
          );
        })}
      </div>
      {activePicker && (
        <>
          <div className="slot-picker-backdrop" onClick={() => setPicker(null)} />
          <div
            className="slot-picker"
            role="dialog"
            aria-label={`亮出${tokenLabel(activePicker.token)}时选择阵营`}
            style={{
              left: Math.max(8, Math.min(activePicker.rect.left, window.innerWidth - PICKER_EST_SIZE)),
              top:
                activePicker.rect.bottom + PICKER_EST_SIZE > window.innerHeight
                  ? Math.max(8, activePicker.rect.top - PICKER_EST_SIZE)
                  : activePicker.rect.bottom + 8,
            }}
          >
            <span className="slot-picker-label">亮出{tokenLabel(activePicker.token)}时选择阵营：</span>
            {activePicker.options.map((a, index) => (
              <button
                key={a.color ?? index}
                autoFocus={index === 0}
                onClick={() => {
                  setPicker(null);
                  onSlotAction?.(a);
                }}
              >
                <span aria-hidden="true" className={`slot dot filled ${a.color === "rose" ? "rose" : "beast"}`}>
                  {MARKER_DOTS[a.color ?? ""]?.label ?? "？"}
                </span>
                {COLOR_LABELS[a.color ?? ""] ?? a.color}
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}

const Seat = memo(function Seat({
  player,
  dagger,
  identity,
  clueLine,
  selfMarkers,
  highlight,
  selfActions,
  onSlotAction,
}: {
  player: PlayerView;
  dagger: boolean;
  identity?: Identity;
  clueLine?: string;
  selfMarkers?: string[];
  highlight?: string[];
  selfActions?: Record<string, Action[]>;
  onSlotAction?: (action: Action) => void;
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
      <ClueSlots player={player} selfMarkers={selfMarkers} selfRank={identity?.rank} highlight={highlight} selfActions={selfActions} onSlotAction={onSlotAction} />
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

export function Board({ game, onSlotAction }: { game: GameState; onSlotAction?: (action: Action) => void }) {
  const viewer = game.viewer;
  const viewerId = viewer?.playerId ?? null;
  const clueLine = viewer
    ? `你的徽记：${displayClueIcon(viewer.clueIcon)}${
        viewer.seenNeighbourClue ? ` · 已看到 ${nameOf(game.players, viewer.seenNeighbourClue.playerId)} 的：${displayClueIcon(viewer.seenNeighbourClue.icon)}` : ""
      }`
    : undefined;
  // 亮牌 / 归还窗口：把当事玩家的合法动作按 token 分组交给可点击槽位（甲）。
  const slotActions: Record<string, Action[]> = {};
  const pending = game.pending;
  if (onSlotAction && pending && (pending.kind === "reveal" || pending.kind === "token-return") && pending.actorPlayerId === viewerId) {
    for (const action of game.legalActions) {
      if ((action.type !== "choose-reveal" && action.type !== "choose-return") || !action.token) continue;
      (slotActions[action.token] ??= []).push(action);
    }
  }
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
            selfActions={onSlotAction && player.playerId === viewerId ? slotActions : undefined}
            onSlotAction={player.playerId === viewerId ? onSlotAction : undefined}
          />
        ))}
      </div>
    </section>
  );
}
