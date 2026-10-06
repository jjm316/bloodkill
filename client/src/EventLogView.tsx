import { useState } from "react";
import type { GameEvent, PlayerView } from "./types";
import type { EventCategoryId } from "./eventLog";
import {
  EVENT_CATEGORIES, categoryOf, describeEvent, isLogVisible,
  loadMutedCategories, saveMutedCategories,
} from "./eventLog";

// 日志模块拥有整份阅读视图及本机筛选偏好，房间页面只提供公开事件与玩家名单。
export function EventLog({ events, players }: { events: GameEvent[]; players?: PlayerView[] }) {
  const [muted, setMuted] = useState<Set<EventCategoryId>>(loadMutedCategories);
  if (!events.length) return null;

  const shown = events
    .filter((event) => isLogVisible(event.eventType) && !muted.has(categoryOf(event.eventType).id))
    .slice(-60)
    .reverse();
  const allMuted = muted.size === EVENT_CATEGORIES.length;
  const allSelected = muted.size === 0;
  const applyMuted = (next: Set<EventCategoryId>) => {
    setMuted(next);
    saveMutedCategories(next);
  };
  const toggleCategory = (id: EventCategoryId) => {
    const next = new Set(muted);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    applyMuted(next);
  };
  const toggleAll = () => applyMuted(
    allSelected ? new Set(EVENT_CATEGORIES.map((category) => category.id)) : new Set<EventCategoryId>(),
  );

  return <details className="log">
    <summary>事件日志（{shown.length}）</summary>
    <div className="log-filters" role="group" aria-label="按类别筛选事件日志">
      <button type="button" className={`filter-tab${allSelected ? " selected" : ""}`} aria-pressed={allSelected} onClick={toggleAll}>全选</button>
      {EVENT_CATEGORIES.map((category) => <button
        key={category.id}
        type="button"
        className={`filter-tab ${category.className}${muted.has(category.id) ? "" : " selected"}`}
        aria-pressed={!muted.has(category.id)}
        onClick={() => toggleCategory(category.id)}
      >{category.label}</button>)}
    </div>
    {allMuted
      ? <p className="log-empty">已屏蔽全部类别</p>
      : <ol aria-live="polite">{shown.map((event) => {
        const category = categoryOf(event.eventType);
        return <li key={event.eventId}>
          <span className={`cat-tag ${category.className}`}>{category.label}</span>
          {describeEvent(event, players)}
        </li>;
      })}</ol>}
  </details>;
}
