import { useEffect } from "react";
import { MARKER_DOTS } from "./Board";
import {
  HELP_ADVANCED_NOTES,
  HELP_CLUE_NOTES,
  HELP_INTRO,
  HELP_INTRO_LINK,
  HELP_LEGEND_ITEMS,
  HELP_RANKS,
  HELP_SKILL_NOTE,
  HELP_WINDOW_TIMEOUT_NOTE,
  type HelpClueNote,
  type HelpLegendItem,
  type HelpRankRow,
  type RankMarkerKind,
} from "./helpContent";
import { Icon } from "./icons";

// 规则与图例浮层（.scratch/ui-help-legend/spec.md）：怎么玩 / 等级技能表 /
// 标记图例三区，全部文案来自 helpContent（单一来源）。页头 ✕ 是主关闭路径
// （.scratch/ui-help-close/spec.md：手机没有 Esc、遮罩只剩细边按不中），
// Escape 与点击遮罩两条旧路径保留（与既有弹窗一致的退出方式），
// 内容超一屏在浮层内竖向滚动。

// "字 + 色块"渲染（与 Board 的线索槽同语言）：玫/兽/？沿用 MARKER_DOTS，
// 万能标记（wild）是帮助浮层独有的第四色——金底"任"，亮出时自选玫或兽。
type MarkerKind = "rose" | "beast" | "unknown" | "wild";

const WILD_LABEL = "任";

function markerLabel(kind: MarkerKind): string {
  return kind === "wild" ? WILD_LABEL : MARKER_DOTS[kind]?.label ?? "？";
}

function MarkerChip({ kind }: { kind: MarkerKind }) {
  return (
    <span className={`slot dot filled ${kind}`} aria-hidden="true">
      {markerLabel(kind)}
    </span>
  );
}

// 等级 → 标记组合的展示变体："同色"给出玫/兽两套（实际颜色随其阵营），
// 用"或"分隔让"双同色 / 一同色一？"的构型一眼可读。
const MARKER_VARIANTS: Record<RankMarkerKind, MarkerKind[][]> = {
  "double-faction": [
    ["rose", "rose"],
    ["beast", "beast"],
  ],
  "double-unknown": [["unknown", "unknown"]],
  "faction-unknown": [
    ["rose", "unknown"],
    ["beast", "unknown"],
  ],
  "double-wild": [["wild", "wild"]],
};

function RankMarkers({ kind }: { kind: RankMarkerKind }) {
  const variants = MARKER_VARIANTS[kind];
  return (
    <span className="rank-markers" title="该等级亮牌时可见的身份标记组成">
      {variants.map((variant, index) => (
        <span key={variant.join("-")} className="marker-pair">
          {index > 0 && <span className="or">或</span>}
          {variant.map((marker, chipIndex) => (
            <MarkerChip key={`${chipIndex}-${marker}`} kind={marker} />
          ))}
        </span>
      ))}
    </span>
  );
}

// 行首徽章字与对局线索槽的字位一致（Board 的等级槽）：数字或"审"。
function rankBadge(rank: number | "fleur-cross"): string {
  return rank === "fleur-cross" ? "审" : String(rank);
}

function RankRow({ row }: { row: HelpRankRow }) {
  return (
    <li className="rank-row">
      <span className="rank-badge" aria-hidden="true">
        {rankBadge(row.rank)}
      </span>
      <span className="rank-name">
        {row.name}
        {row.oddOnly && <span className="odd-tag">仅奇数局</span>}
      </span>
      <RankMarkers kind={row.markers} />
      <p className="rank-effect">{row.effect}</p>
    </li>
  );
}

function LegendRow({ item }: { item: HelpLegendItem }) {
  return (
    <li className="legend-row">
      <span className="legend-ico" aria-hidden="true">
        <Icon name={item.icon} />
      </span>
      <span className="legend-name">{item.name}</span>
      <p className="legend-desc">{item.effect}</p>
    </li>
  );
}

// 线索/徽记/真实阵营色短注的可视半边：三格槽示意（3｜玫｜？）、玫/兽色块对，
// 或真实阵营色徽的三色圆点（玫/兽/灰=审判者）。
function ClueNoteVisual({ kind }: { kind: HelpClueNote["kind"] }) {
  if (kind === "slots") {
    return (
      <span className="slot-demo" aria-hidden="true">
        <span className="slot tile filled">3</span>
        <span className="slot dot filled rose">玫</span>
        <span className="slot dot empty dim">？</span>
      </span>
    );
  }
  if (kind === "self-badge") {
    return (
      <span className="self-badge-demo" aria-hidden="true">
        <span className="true-color-badge rose" />
        <span className="true-color-badge beast" />
        <span className="true-color-badge order" />
      </span>
    );
  }
  return (
    <span className="emblem-pair" aria-hidden="true">
      <MarkerChip kind="rose" />
      <MarkerChip kind="beast" />
    </span>
  );
}

function ClueNoteRow({ note }: { note: HelpClueNote }) {
  return (
    <li className="clue-note">
      <ClueNoteVisual kind={note.kind} />
      <p className="note-text">
        <strong>{note.title}</strong> — {note.body}
      </p>
    </li>
  );
}

// 简介五句话在浮层与大厅两处同源渲染。
function IntroLines() {
  return (
    <>
      {HELP_INTRO.map((line) => (
        <p key={line.slice(0, 8)}>{line}</p>
      ))}
    </>
  );
}

export function RulesOverlay({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal rules-modal" role="dialog" aria-modal="true" aria-labelledby="rules-title">
        <div className="rules-head">
          {/* 与页头徽记同源的 help 图标（svg 自带圆环）：全角"？"字体墨迹偏左无法居中，见 icons.tsx */}
          <span className="rules-q" aria-hidden="true"><Icon name="help" /></span>
          <h3 id="rules-title">规则与图例</h3>
          <button className="rules-close" onClick={onClose} aria-label="关闭" title="关闭">
            <Icon name="close" />
          </button>
        </div>
        <div className="rules-body">
          <section className="rules-section" aria-labelledby="rules-how">
            <h4 id="rules-how">怎么玩</h4>
            <div className="rules-intro">
              <IntroLines />
            </div>
          </section>
          <section className="rules-section" aria-labelledby="rules-ranks">
            <h4 id="rules-ranks">等级技能表</h4>
            <ul className="rank-list">
              {HELP_RANKS.map((row) => (
                <RankRow key={String(row.rank)} row={row} />
              ))}
            </ul>
            <p className="rules-note">※ {HELP_SKILL_NOTE}</p>
            {HELP_ADVANCED_NOTES.map((note) => (
              <p className="rules-note" key={note.slice(0, 8)}>
                ※ {note}
              </p>
            ))}
            <p className="rules-note">※ {HELP_WINDOW_TIMEOUT_NOTE}</p>
          </section>
          <section className="rules-section" aria-labelledby="rules-legend">
            <h4 id="rules-legend">标记图例</h4>
            <ul className="legend-list">
              {HELP_LEGEND_ITEMS.map((item) => (
                <LegendRow key={item.icon} item={item} />
              ))}
            </ul>
            <ul className="clue-notes">
              {HELP_CLUE_NOTES.map((note) => (
                <ClueNoteRow key={note.kind} note={note} />
              ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

// 大厅"怎么玩"折叠块：只渲染简介五句话 + 指路句，等级表与图例只在房内浮层。
export function HowToPlayBlock() {
  return (
    <details className="how-to">
      <summary>怎么玩</summary>
      <div className="how-to-body">
        <IntroLines />
        <p className="hint">{HELP_INTRO_LINK}</p>
      </div>
    </details>
  );
}
