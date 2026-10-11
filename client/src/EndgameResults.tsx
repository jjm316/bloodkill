import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { curseAttributionOf } from "./curseReveal";
import { MarqueeName } from "./MarqueeName";
import type { GameResult, PlayerView, ViewerView } from "./types";
import { displayFaction, displayRank } from "./types";

const GROUPS = [
  { faction: "rose", color: "rose", title: "玫瑰家族" },
  { faction: "beast", color: "beast", title: "野兽家族" },
  { faction: "secret-order", color: "order", title: "审判者" },
  { faction: "unknown", color: "unknown", title: "身份未记录" },
];

const EXPLANATIONS: Record<string, string> = {
  "game.end.captured-leader": "敌方领袖被捕获",
  "game.end.captured-player": "普通玩家被捕获",
  "game.end.inquisitor-captured": "审判者被捕获，由审判者独赢",
  "game.end.inquisitor-active-capture": "审判者主动捕获目标，按规则判负",
  "game.end.inquisitor-true-curse": "胜方领袖持有真诅咒，审判者夺取胜利独赢",
};

export function EndgameResults({ result, players, viewer }: {
  result: GameResult;
  players: PlayerView[];
  viewer: ViewerView | null;
}) {
  const [open, setOpen] = useState(true);
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const roster = useRef<HTMLDivElement>(null);
  const scores = new Map(result.ranking.map((entry) => [entry.playerId, entry.score]));
  const draw = result.winner === "draw";
  const outcome = (playerId: string) => draw ? "平局" : scores.get(playerId) === 1 ? "胜利" : scores.get(playerId) === 0 ? "失败" : "胜负未记录";
  const title = draw ? "对局结束，平局" : `对局结束，${displayFaction(result.winner)}${result.winner === "secret-order" ? "独赢" : "获胜"}`;
  const attribution = curseAttributionOf(result, players);
  const explanation = EXPLANATIONS[result.explanationKey] ?? "规则结算";
  const identities = new Map(players.map((player) => [player.playerId, player.identity ?? (viewer?.playerId === player.playerId ? viewer.identity : undefined)]));

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    roster.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
      // 名单可聚焦以支持方向键/PageDown；Tab 在当前弹窗内循环。
      if (event.key === "Tab") {
        event.preventDefault();
        const targets = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex="0"]') ?? [])];
        const index = targets.findIndex((target) => target === document.activeElement);
        const next = index < 0 ? 0 : (index + (event.shiftKey ? -1 : 1) + targets.length) % targets.length;
        targets[next]?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
      if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus();
      else opener.current?.focus();
    };
  }, [open]);

  return <>
    <div className="result">
      {attribution && <p className="curse-attribution">{attribution}</p>}
      <strong>{title}</strong>（{explanation}）
      <button ref={opener} className="result-open" onClick={() => setOpen(true)}>查看结果</button>
    </div>
    {open && createPortal(
      <div className="modal-overlay endgame-overlay" onClick={(event) => {
        if (event.target === event.currentTarget) setOpen(false);
      }}>
        <section ref={dialog} className="endgame-modal" role="dialog" aria-modal="true" aria-labelledby="endgame-title">
          <header className="endgame-head">
            <p className="endgame-eyebrow">终局揭晓</p>
            <h2 id="endgame-title">{title}</h2>
            {viewer && <p className={`endgame-personal${outcome(viewer.playerId) === "胜利" ? " won" : ""}`}>
              {outcome(viewer.playerId) === "胜利" ? "你胜利了" : outcome(viewer.playerId) === "失败" ? "你失败了" : outcome(viewer.playerId) === "平局" ? "本局平局" : "你的胜负未记录"}
              {` · ${displayFaction(viewer.identity.faction)}`}
            </p>}
          </header>
          <div ref={roster} className="endgame-body" role="region" aria-label="玩家结算名单" tabIndex={0}>
            {attribution && <p className="curse-attribution">{attribution}</p>}
            <p className="endgame-explanation">{explanation}</p>
            <div className="endgame-groups">
              {GROUPS.map((group) => {
                const members = players.filter((player) => {
                  const faction = identities.get(player.playerId)?.faction;
                  return (GROUPS.some((item) => item.faction === faction) ? faction : "unknown") === group.faction;
                }).sort((a, b) => a.seat - b.seat);
                if (!members.length) return null;
                const groupOutcome = draw ? "平局" : group.faction === "unknown" ? "" : result.winner === group.faction ? "胜利" : "失败";
                return <section className={`endgame-group ${group.color}`} key={group.faction} aria-label={group.title}>
                  <div className="endgame-group-head">
                    <h3><span className="endgame-color" aria-hidden="true" />{group.title}</h3>
                    <span className={groupOutcome === "胜利" ? "won" : ""}>{groupOutcome}{groupOutcome && " · "}{members.length} 人</span>
                  </div>
                  <ul className="endgame-roster">
                    {members.map((player) => {
                      const identity = identities.get(player.playerId);
                      const verdict = outcome(player.playerId);
                      return <li key={player.playerId}>
                        <div className="endgame-player">
                          <div className="endgame-name"><MarqueeName name={player.displayName} />{viewer?.playerId === player.playerId && <span className="endgame-you">你</span>}</div>
                          <div className="endgame-identity">{identity ? displayRank(identity.rank) : "等级未记录"} · <span>{group.title}</span></div>
                        </div>
                        <span className={`endgame-verdict${verdict === "胜利" ? " won" : ""}`}>
                          {verdict === "胜利" && <span aria-hidden="true">★ </span>}{verdict}
                        </span>
                      </li>;
                    })}
                  </ul>
                </section>;
              })}
            </div>
          </div>
          <footer className="endgame-footer">
            <span>{players.every((player) => player.identity) ? "全员身份已揭晓" : "部分身份未记录"}</span>
            <button ref={closeButton} onClick={() => setOpen(false)}>关闭，查看棋盘</button>
          </footer>
        </section>
      </div>, document.body,
    )}
  </>;
}
