"""Per-player and public projections of the authoritative engine state.

The engine holds every hidden fact (identity, ranks, un-revealed tokens, curse
assignments). A projection is the derived, visible slice for one viewer. It is
never persisted as authority and never exposes another player's private data.

Projection rules follow the domain contract (03):

- a player sees every public fact plus only their own hidden identity;
- a spectator sees only the public facts;
- the RNG seed is never included (knowing it would let a viewer reproduce the
  whole identity assignment);
- the clue icon of every player appears only in the viewer block of the player
  who saw it at setup: each viewer sees their own icon and their right-hand
  neighbour's; the public ``players`` list never carries any icon.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import EngineState, Pending, Player


def legal_actions(state: "EngineState", player_id: str) -> list[dict[str, Any]]:
    """Return actions derived from authority; a UI affordance, not a bypass of validation."""
    if state.status == "ended" or player_id not in state.players:
        return []
    player = state.players[player_id]
    pending = state.pending
    if pending is not None:
        if pending.actor_player_id != player_id:
            return []
        if pending.kind == "intervention":
            actions: list[dict[str, Any]] = [{"type": "decline-intervention"}]
            if pending.context.get("requested"):
                actions.extend(
                    {"type": "choose-intervention", "responderPlayerId": responder}
                    for responder in pending.eligible_player_ids
                )
            else:
                actions.insert(0, {"type": "request-intervention"})
            return actions
        if pending.kind == "skill":
            owner = state.players[player_id]
            actions = [{"type": "choose-skill", "use": False}]
            if pending.rank == 7 and owner.resources.get("shield", 0):
                return actions
            if pending.rank == 4 and pending.trigger != "intervention":
                return actions
            if pending.rank == 4:
                actions.append({"type": "choose-skill", "use": True, "mode": "harm"})
                protected = state.players.get(pending.context.get("protectedPlayerId"))
                if protected and protected.damage >= 1 and protected.revealed:
                    actions.append({"type": "choose-skill", "use": True, "mode": "heal"})
                return actions
            if pending.rank == 2:
                actions.extend(
                    {"type": "choose-skill", "use": True, "targetPlayerId": target.player_id}
                    for target in state.players.values()
                    if target.player_id != player_id and not target.captured and not target.resources.get("shield", 0)
                )
            elif pending.rank in {3}:
                live_targets = [target.player_id for target in state.players.values() if target.player_id != player_id and not target.captured]
                actions.extend(
                    {"type": "choose-skill", "use": True, "targetPlayerIds": [first, second]}
                    for index, first in enumerate(live_targets)
                    for second in live_targets[index + 1 :]
                )
            elif pending.rank in {5, 6, 8, 9}:
                actions.extend(
                    {"type": "choose-skill", "use": True, "targetPlayerId": target.player_id}
                    for target in state.players.values()
                    if not target.captured and (pending.rank != 5 or (target.player_id != player_id and not target.resources.get("shield", 0)))
                )
            else:
                actions.append({"type": "choose-skill", "use": True})
            return actions
        if pending.kind == "token-return":
            return [
                {"type": "choose-return", "token": token}
                for token in pending.eligible_player_ids
            ]
        if pending.kind == "reveal":
            target = state.players[pending.actor_player_id]
            tokens = {"rank", "marker-0", "marker-1"} - target.revealed
            if pending.context.get("forceRank") and "rank" in tokens:
                tokens = {"rank"}
            actions = [{"type": "choose-reveal", "token": token} for token in sorted(tokens)]
            for token in sorted(tokens):
                if token.startswith("marker-") and target.identity_markers[int(token[-1])] == "wild":
                    actions = [action for action in actions if action["token"] != token]
                    actions.extend({"type": "choose-reveal", "token": token, "color": color} for color in ("rose", "beast"))
            return actions
        return []
    if state.status != "active":
        return []
    actions = []
    if state.phase.get("kind") == "action" and state.dagger_holder_id == player_id:
        actions.extend(
            {"type": "pass-dagger", "targetPlayerId": target.player_id}
            for target in state.players.values()
            if target.player_id != player_id and not target.captured
        )
        actions.extend(
            {"type": "attack", "targetPlayerId": target.player_id}
            for target in state.players.values()
            if target.player_id != player_id and not target.captured and not target.resources.get("shield", 0)
        )
    if state.curses and player.faction == "secret-order":
        actions.append({"type": "distribute-curse"})
    return actions


def _right_neighbour(state: "EngineState", viewer: "Player") -> "Player | None":
    """The player who showed their clue icon to ``viewer`` at setup.

    Seats are read clockwise, so each player shows to the next seat; the icon a
    viewer saw therefore belongs to the previous seat, cyclically (seat gaps
    tolerated).
    """
    ordered = sorted(state.players.values(), key=lambda player: player.seat)
    if len(ordered) < 2:
        return None
    index = ordered.index(viewer)
    return ordered[index - 1]


def project_state(state: "EngineState", viewer_player_id: str | None = None) -> dict[str, Any]:
    """Derive the visible projection for a player, or the public view for a spectator."""
    viewer = state.players.get(viewer_player_id) if viewer_player_id else None
    neighbour = _right_neighbour(state, viewer) if viewer else None
    neighbour_view = {"playerId": neighbour.player_id, "icon": neighbour.clue_icon} if neighbour else None
    projection: dict[str, Any] = {
        "gameId": state.game_id,
        "revision": state.revision,
        "status": state.status,
        "players": [_public_player(player) for player in sorted(state.players.values(), key=lambda p: p.seat)],
        "daggerHolderId": state.dagger_holder_id,
        "phase": dict(state.phase),
        "pending": _pending_view(state.pending),
        "result": dict(state.result) if state.result else None,
    }
    if viewer is None:
        projection["viewer"] = None
        projection["legalActions"] = []
    else:
        projection["viewer"] = {
            "playerId": viewer.player_id,
            "identity": {"faction": viewer.faction, "rank": viewer.rank},
            "identityMarkers": list(viewer.identity_markers),
            "resources": dict(viewer.resources),
            "skillsUsed": sorted(viewer.skills_used),
            "inspections": {target_id: dict(value) for target_id, value in viewer.inspections.items()},
            "cursesToDistribute": list(state.curses) if viewer.faction == "secret-order" else [],
            "clueIcon": viewer.clue_icon,
            "seenNeighbourClue": neighbour_view,
        }
        projection["legalActions"] = legal_actions(state, viewer_player_id)
    return projection


def _public_player(player: "Player") -> dict[str, Any]:
    revealed: dict[str, Any] = {"markers": [None, None]}
    if "rank" in player.revealed:
        revealed["rank"] = player.revealed_values.get("rank", player.rank)
    for index in range(2):
        token = f"marker-{index}"
        if token in player.revealed:
            revealed["markers"][index] = player.revealed_values.get(token, player.identity_markers[index])
    return {
        "playerId": player.player_id,
        "seat": player.seat,
        "displayName": player.display_name,
        "damage": player.damage,
        "captured": player.captured,
        "revealed": revealed,
        "identityMarkers": [None, None],
        "resources": dict(player.resources),
    }


def _pending_view(pending: "Pending | None") -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "kind": pending.kind,
        "actorPlayerId": pending.actor_player_id,
        "targetPlayerId": pending.target_player_id,
        "eligiblePlayerIds": list(pending.eligible_player_ids),
        "rank": pending.rank,
        "trigger": pending.trigger,
        "eligibleTokens": list(pending.eligible_player_ids) if pending.kind == "token-return" else (list(getattr(pending, "context", {}).get("eligibleTokens", [])) if pending.kind == "reveal" else []),
        "forceRank": bool(getattr(pending, "context", {}).get("forceRank")) if pending.kind == "reveal" else False,
    }
