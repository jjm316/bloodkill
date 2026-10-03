import { memo, useCallback, useEffect, useState } from "react";
import { Icon, type IconName } from "./icons";
import type { MemoApi, MemoColor, MemoEntry, MemoMark, MemoPatch } from "./memoMarkers";
import { memoColorOf } from "./memoMarkers";
import { seatPosition, seatTier, tableShape, type SeatTier } from "./tableSeats";
import type { Action, GameState, Identity, PendingView, PlayerView } from "./types";
import { displayClueIcon, displayFaction, displayRank, displayResource } from "./types";

// The shared projection component: the live game and the replay render the
// exact same projection shape through this board.

function nameOf(players: PlayerView[], playerId: string | null | undefined): string {
  const player = players.find((p) => p.playerId === playerId);
  return player ? player.displayName : "?";
}

// 浮层通用关闭：Escape、尺寸或滚动变化（fixed 定位的浮层会脱离锚点）；点 backdrop 由调用方自备
function useDismissOverlay(active: boolean, close: () => void) {
  useEffect(() => {
    if (!active) return;
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
  }, [active, close]);
}

// 资源图标映射：emoji 换内联 SVG（spec 2026-09-13 拍板），未知资源退回中文本地化名
const RESOURCE_ICONS: Record<string, IconName> = {
  quill: "quill",
  shield: "shield",
  sword: "sword",
  staff: "staff",
  fan: "fan",
};

function Resources({ resources }: { resources: Record<string, number> }) {
  const held = Object.entries(resources).filter(([, count]) => count > 0);
  if (held.length === 0) return null;
  return (
    <div className="resources">
      {held.map(([name, count]) => (
        <span key={name} title={displayResource(name)}>
          {RESOURCE_ICONS[name] ? <Icon name={RESOURCE_ICONS[name]} /> : displayResource(name)}×{count}
        </span>
      ))}
    </div>
  );
}

// 每名玩家恰好三张线索 token：1 等级 + 2 身份标记（组合由等级决定）。
// 槽位填亮数与伤害严格同步（唯一 +1 在 _continue_damage、唯一 -1 是炼金归还，二者同动），
// 因此填亮的槽位本身就是伤害计数（issue 23 裁决）。
// 帮助浮层（HelpOverlay）复用此表渲染"字+色块"，万能标记（wild）由其自带"任"字。
export const MARKER_DOTS: Record<string, { label: string; tone: string; name: string }> = {
  rose: { label: "玫", tone: "rose", name: "玫瑰家族标记" },
  beast: { label: "兽", tone: "beast", name: "野兽家族标记" },
  unknown: { label: "？", tone: "unknown", name: "未知标记" },
};

const TOKEN_LABELS: Record<string, string> = { rank: "等级标记", "marker-0": "身份标记 1", "marker-1": "身份标记 2" };
const COLOR_LABELS: Record<string, string> = { rose: "玫瑰", beast: "野兽" };
const tokenLabel = (token: string) => TOKEN_LABELS[token] ?? token;

// 备忘角标的三色语言复用线索槽配色（玫红/兽蓝/灰），但造型是右上角徽章，与槽位明显不同
const MEMO_COLORS: { value: MemoColor; label: string; name: string }[] = [
  { value: "rose", label: "玫", name: "玫瑰红" },
  { value: "beast", label: "兽", name: "野兽蓝" },
  { value: "gray", label: "？", name: "灰（未知）" },
];
const MEMO_MARKS: MemoMark[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, "审"];

// 备忘选择器浮层的预估尺寸（px）：定位贴边与上下翻转的保守估计
const MEMO_PICKER_EST = { width: 240, height: 260 };

// 每个座位的私有备忘：entry 为空对象时角标显示空态；change/clear 只改本机 localStorage
interface SeatMemo {
  entry: MemoEntry | undefined;
  onChange: (patch: MemoPatch) => void;
  onClear: () => void;
}

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
  const closePicker = useCallback(() => setPicker(null), []);
  const hot = new Set(highlight ?? []);
  const self = selfActions !== undefined && onSlotAction !== undefined;
  // 浮层跟随 pending 存活：亮牌/归还窗口一旦结算（hot 消失）即视为关闭
  const activePicker = picker && hot.has(picker.token) ? picker : null;
  useDismissOverlay(Boolean(activePicker), closePicker);

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
  self,
  identity,
  clueLine,
  selfMarkers,
  highlight,
  selfActions,
  onSlotAction,
  memoBadge,
  style,
}: {
  player: PlayerView;
  dagger: boolean;
  /** viewer 自己的座位：桌面端圆桌固定在正下方（CSS .seat.self 描金边） */
  self?: boolean;
  identity?: Identity;
  clueLine?: string;
  selfMarkers?: string[];
  highlight?: string[];
  selfActions?: Record<string, Action[]>;
  onSlotAction?: (action: Action) => void;
  /** 私有备忘角标：不传 = 不渲染（自己座位 / 回放屏） */
  memoBadge?: SeatMemo;
  /** 圆桌坐标（容器百分比）：以 CSS 变量注入，仅 ≥720px 圆桌分支的 CSS 消费
   * （left: var(--seat-x)）；窄屏网格分支不消费变量，避免 relative 定位下
   * 百分比 left/top 变成从网格单元格平移的偏移量 */
  style?: React.CSSProperties;
}) {
  const [memoPickerRect, setMemoPickerRect] = useState<DOMRect | null>(null);
  const closeMemoPicker = useCallback(() => setMemoPickerRect(null), []);
  // 备忘选择器同样跟随锚点存活：Escape / 点外部 / 尺寸或滚动变化即关闭
  useDismissOverlay(Boolean(memoPickerRect), closeMemoPicker);

  const memoEntry = memoBadge?.entry;
  const memoColor = memoColorOf(memoEntry);
  const selectedColor = memoEntry?.color ?? "gray";
  const selectedMark = memoEntry?.mark ?? null;

  return (
    <article
      role="listitem"
      className={`seat${self ? " self" : ""}${player.captured ? " captured" : ""}${dagger ? " dagger" : ""}`}
      style={style}
      aria-label={`${player.displayName}${player.captured ? "，已被捕获" : ""}`}
    >
      <div className="seat-name">
        {dagger && (
          <span className="dagger-icon" title="持有匕首">
            <Icon name="dagger" />
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
      {memoBadge && (
        <button
          type="button"
          className={`memo-badge${memoColor ? ` ${memoColor}` : " empty"}`}
          title="备忘标记（仅保存在本设备）"
          aria-label={`${player.displayName} 的备忘标记${memoColor ? "" : "（空）"}`}
          onClick={(e) => setMemoPickerRect(e.currentTarget.getBoundingClientRect())}
        >
          {memoEntry?.mark ?? ""}
        </button>
      )}
      {memoBadge && memoPickerRect && (
        <>
          <div className="memo-picker-backdrop" onClick={closeMemoPicker} />
          <div
            className="memo-picker"
            role="dialog"
            aria-label={`${player.displayName} 的备忘标记`}
            style={{
              left: Math.max(8, Math.min(memoPickerRect.right - MEMO_PICKER_EST.width, window.innerWidth - MEMO_PICKER_EST.width - 8)),
              top:
                memoPickerRect.bottom + MEMO_PICKER_EST.height > window.innerHeight
                  ? Math.max(8, memoPickerRect.top - MEMO_PICKER_EST.height)
                  : memoPickerRect.bottom + 8,
            }}
          >
            <span className="memo-picker-label">备忘：{player.displayName}</span>
            <div className="memo-colors" role="group" aria-label="猜测的阵营颜色">
              {MEMO_COLORS.map((color) => (
                <button
                  key={color.value}
                  type="button"
                  className={`memo-swatch ${color.value}${selectedColor === color.value ? " selected" : ""}`}
                  aria-pressed={selectedColor === color.value}
                  title={color.name}
                  onClick={() => memoBadge.onChange({ color: color.value })}
                >
                  {color.label}
                </button>
              ))}
            </div>
            <div className="memo-marks" role="group" aria-label="猜测的等级或审判者">
              {MEMO_MARKS.map((mark) => (
                <button
                  key={String(mark)}
                  type="button"
                  className={selectedMark === mark ? "selected" : ""}
                  aria-pressed={selectedMark === mark}
                  title={mark === "审" ? "审判者" : `等级 ${mark}`}
                  onClick={() => memoBadge.onChange({ mark })}
                >
                  {mark}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="memo-clear"
              onClick={() => {
                memoBadge.onClear();
                closeMemoPicker();
              }}
            >
              清除备忘
            </button>
            <span className="memo-picker-note">仅保存在本设备</span>
          </div>
        </>
      )}
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

// 档位 → 圆桌 CSS 类（styles.css 按档给座位宽度；xl 另有紧凑卡片）
const TIER_CLASS: Record<SeatTier, string> = { base: "", lg: " size-lg", xl: " size-xl" };

export function Board({ game, onSlotAction, memos }: { game: GameState; onSlotAction?: (action: Action) => void; memos?: MemoApi }) {
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
  // 圆桌几何（spec 2026-09-13 拍板）：座位坐标来自纯函数 tableSeats，viewer 座位
  // 旋转到正下方、数组前驱（引擎 seenNeighbourClue 的"左邻"）落在其左手边；
  // 回放/旁观无 viewer 时锚定 0 号座位。窄屏坐标由 CSS 网格接管（left/top 失效）。
  const total = game.players.length;
  const viewerIndex = Math.max(0, game.players.findIndex((p) => p.playerId === viewerId));
  const shape = tableShape(total);
  return (
    <section className="board" aria-label="对局桌面">
      {game.status === "ended" && game.result && <ResultBanner result={game.result} players={game.players} />}
      <div
        className={`table-area${TIER_CLASS[seatTier(total)]}`}
        style={{ "--table-h": `${shape.height}px`, "--table-rx": `${shape.rx}%`, "--table-ry": `${shape.ry}%` } as React.CSSProperties}
      >
        {/* 纯 CSS 椭圆桌（深绯红渐变 + 金描边）：装饰性，窄屏隐藏 */}
        <div className="table-oval" aria-hidden="true" />
        {game.pending && <PendingBanner pending={game.pending} players={game.players} />}
        <div className="players" role="list" aria-label="玩家座位">
          {game.players.map((player, index) => {
            const isSelf = player.playerId === viewerId;
            const pos = seatPosition(index, total, viewerIndex);
            return (
              <Seat
                key={player.playerId}
                player={player}
                dagger={game.daggerHolderId === player.playerId}
                self={isSelf}
                identity={isSelf ? viewer?.identity : undefined}
                clueLine={isSelf ? clueLine : undefined}
                selfMarkers={isSelf ? viewer?.identityMarkers : undefined}
                highlight={highlightFor(game.pending, player.playerId)}
                selfActions={onSlotAction && isSelf ? slotActions : undefined}
                onSlotAction={isSelf ? onSlotAction : undefined}
                style={{ "--seat-x": `${pos.x}%`, "--seat-y": `${pos.y}%` } as React.CSSProperties}
                memoBadge={
                  memos && !isSelf
                    ? {
                        entry: memos.markers[player.playerId],
                        onChange: (patch) => memos.change(player.playerId, patch),
                        onClear: () => memos.clear(player.playerId),
                      }
                    : undefined
                }
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}
