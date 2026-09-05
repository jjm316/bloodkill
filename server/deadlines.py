"""Reusable asyncio deadline scheduler for server-owned expiry windows.

The engine never stores wall-clock time (replay determinism); a window's
deadline lives on the room (see ``Room.sync_window_deadline``) and is
re-armed whenever the window's stage changes. After every authoritative
mutation the server calls :meth:`DeadlineScheduler.sync`, which keeps at most
one armed timer per room; when the deadline passes the timer submits the
window's timeout command through the same command pipeline as any player
action, so the resolution lands in the event log and stays replayable.

New window kinds plug in by appending a provider to :data:`WINDOW_PROVIDERS`;
each provider maps a room to a ``(command_type, command_payload, deadline)``
window. Issue 23 wires the two intervention phases (volunteer poll and the
target's choice); future windows reuse the machinery unchanged.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

# room -> (command_type, command_payload, deadline) | None
WindowProvider = Callable[[Any], tuple[str, dict[str, Any], float] | None]
# (room, command_type, command_payload) -> coroutine applied through the command pipeline
ExpiryHandler = Callable[[Any, str, dict[str, Any]], Awaitable[None]]


def intervention_window(room: Any) -> tuple[str, dict[str, Any], float] | None:
    """The intervention poll / target-choice window and its timeout command."""
    state = room.engine.state
    pending = getattr(state, "pending", None)
    if pending is None or pending.kind != "intervention":
        return None
    stage = room.window_stage
    deadline = room.window_deadline
    if stage not in {"poll", "choice"} or not isinstance(deadline, (int, float)):
        return None
    return "timeout-intervention", {"stage": stage}, float(deadline)


WINDOW_PROVIDERS: list[WindowProvider] = [intervention_window]


def active_window(room: Any) -> tuple[str, dict[str, Any], float] | None:
    for provider in WINDOW_PROVIDERS:
        window = provider(room)
        if window is not None:
            return window
    return None


class DeadlineScheduler:
    """Arms one asyncio timer per game for the room's current deadline window."""

    def __init__(self, on_expire: ExpiryHandler) -> None:
        self._on_expire = on_expire
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def sync(self, room: Any) -> None:
        game_id = room.game_id
        window = active_window(room)
        current = self._tasks.get(game_id)
        if window is None:
            self._cancel(game_id, current)
            return
        command_type, payload, deadline = window
        if current is not None and not current.done() and self._signature(current) == (command_type, payload, deadline):
            return
        self._cancel(game_id, current)
        task = asyncio.ensure_future(self._watch(room, command_type, payload, deadline))
        task.set_name(f"deadline:{game_id}:{command_type}")
        # The signature lets a later sync see whether the armed timer still
        # matches the room's window without extra bookkeeping.
        setattr(task, "deadline_signature", (command_type, payload, deadline))
        self._tasks[game_id] = task

    async def _watch(self, room: Any, command_type: str, payload: dict[str, Any], deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.0, deadline - time.time()))
            await self._on_expire(room, command_type, payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            if self._tasks.get(room.game_id) is asyncio.current_task():
                del self._tasks[room.game_id]

    def _cancel(self, game_id: str, task: asyncio.Task[None] | None) -> None:
        if task is not None:
            task.cancel()
        self._tasks.pop(game_id, None)

    @staticmethod
    def _signature(task: asyncio.Task[None]) -> tuple[str, dict[str, Any], float] | None:
        return getattr(task, "deadline_signature", None)
