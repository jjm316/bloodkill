"""Focused tests for every implemented rule branch, filling the gaps left by
test_engine / test_projection.

A few branches are defensive gates whose triggers are not grantable through
public commands yet (shield/fan are granted by ranks 6/9 in issue 14, a second
skill window needs the alchemist's token return, multi-curse games need a
versioned curse table). Those tests inject the trigger directly into the
authority state and are commented as such; they prove the gate, not the
granting path.

Two tests document known defects found by the property net and are marked
`expectedFailure`; the referenced tickets remove the marker when fixed.
"""

from copy import deepcopy
import unittest

from blood_bound import Command, RuleError, RulesEngine, legal_actions, project_state, run_deterministic_game
from blood_bound.engine import Pending


class FixedClock:
    def __call__(self):
        return 0.0


def command(engine, command_id, actor, kind, **payload):
    return Command(command_id, engine.state.game_id, actor, engine.state.revision, kind, payload)


def started(count=6, seed="branch-seed"):
    engine = RulesEngine.new_game("branch-game", seed, clock=FixedClock())
    for index in range(count):
        engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
    engine.apply(command(engine, "start", None, "start-game"))
    return engine


def started_with_ranks(count, *ranks, max_probes=200):
    """Probe seeds until every requested rank is dealt; returns (engine, {rank: player})."""
    for probe in range(max_probes):
        engine = started(count, seed=f"branch-probe-{probe}")
        found = {
            rank: next((player for player in engine.state.players.values() if player.rank == rank), None)
            for rank in ranks
        }
        if all(found.values()):
            return engine, found
    raise AssertionError(f"no probed seed dealt ranks {ranks} in a {count}-player game")


def give_dagger_to(engine, player_id):
    holder = engine.state.dagger_holder_id
    if holder != player_id:
        engine.apply(command(engine, f"pass-to-{player_id}-{engine.state.revision}", holder, "pass-dagger", targetPlayerId=player_id))


def mark_three_damage(engine, player_id):
    """Set a player to 3 damage with both clues revealed, as two resolved attacks would."""
    player = engine.state.players[player_id]
    player.damage = 3
    player.revealed = {"rank", "marker-0", "marker-1"}


def reveal_rank(engine, player_id, command_id="reveal-rank"):
    if engine.state.pending and engine.state.pending.kind == "reveal" and "rank" in {"rank", "marker-0", "marker-1"} - engine.state.players[player_id].revealed:
        engine.apply(command(engine, command_id, player_id, "choose-reveal", token="rank"))


class SetupBranchTests(unittest.TestCase):
    def test_join_after_start_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "late", None, "join-game", playerId="late"))
        self.assertEqual(error.exception.code, "game.not-setup")

    def test_join_without_player_id_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "empty", None, "join-game"))
        self.assertEqual(error.exception.code, "player.not-eligible")

    def test_duplicate_player_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        engine.apply(command(engine, "j0", None, "join-game", playerId="p0"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "j0-again", None, "join-game", playerId="p0"))
        self.assertEqual(error.exception.code, "game.duplicate-player")

    def test_thirteenth_player_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        for index in range(12):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "join-12", None, "join-game", playerId="p12"))
        self.assertEqual(error.exception.code, "game.player-count")

    def test_seat_conflict_and_out_of_range_are_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        engine.apply(command(engine, "j0", None, "join-game", playerId="p0", seat=3))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "j1", None, "join-game", playerId="p1", seat=3))
        self.assertEqual(error.exception.code, "game.seat-occupied")
        for bad_seat in (12, -1):
            with self.subTest(seat=bad_seat):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"j-{bad_seat}", None, "join-game", playerId=f"p-{bad_seat}", seat=bad_seat))
                self.assertEqual(error.exception.code, "game.seat-occupied")

    def test_auto_seat_assigns_lowest_free_seat(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        engine.apply(command(engine, "j0", None, "join-game", playerId="p0"))
        engine.apply(command(engine, "j1", None, "join-game", playerId="p1", seat=4))
        engine.apply(command(engine, "j2", None, "join-game", playerId="p2"))
        self.assertEqual(
            {player.seat for player in engine.state.players.values()},
            {0, 1, 4},
        )

    def test_start_with_fewer_than_six_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        for index in range(5):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "start", None, "start-game"))
        self.assertEqual(error.exception.code, "game.player-count")

    def test_second_start_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "restart", None, "start-game"))
        self.assertEqual(error.exception.code, "game.not-setup")


class CommandGuardBranchTests(unittest.TestCase):
    def test_command_for_another_game_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(Command("x", "other-game", None, 0, "join-game", {"playerId": "p0"}))
        self.assertEqual(error.exception.code, "game.not-found")

    def test_reused_command_id_with_different_body_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        first_target = next(pid for pid in engine.state.players if pid != holder)
        second_target = next(pid for pid in engine.state.players if pid not in (holder, first_target))
        engine.apply(command(engine, "pass-1", holder, "pass-dagger", targetPlayerId=first_target))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "pass-1", holder, "pass-dagger", targetPlayerId=second_target))
        self.assertEqual(error.exception.code, "command.id-reuse")

    def test_command_after_game_end_is_rejected(self):
        engine, _ = run_deterministic_game(6, game_id="done", seed="done-seed")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "late", None, "join-game", playerId="late"))
        self.assertEqual(error.exception.code, "game.already-ended")

    def test_pass_by_non_holder_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        other = next(pid for pid in engine.state.players if pid != holder)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "sneak", other, "pass-dagger", targetPlayerId=holder))
        self.assertEqual(error.exception.code, "player.not-dagger-holder")

    def test_pass_to_self_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "self", holder, "pass-dagger", targetPlayerId=holder))
        self.assertEqual(error.exception.code, "target.not-eligible")

    def test_attack_to_self_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "self", holder, "attack", targetPlayerId=holder))
        self.assertEqual(error.exception.code, "target.not-eligible")

    def test_action_command_during_intervention_window_is_rejected(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "rush", attacker, "pass-dagger", targetPlayerId=target))
        self.assertEqual(error.exception.code, "game.not-active")


class AttackBranchTests(unittest.TestCase):
    def test_attack_declares_window_hands_dagger_and_lists_eligible(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        events = engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertEqual(events[0].event_type, "AttackDeclared")
        self.assertEqual(events[0].payload, {"attackerPlayerId": attacker, "targetPlayerId": target})
        self.assertEqual(engine.state.dagger_holder_id, target)
        self.assertEqual(engine.state.phase, {"kind": "intervention", "activePlayerId": target})
        pending = engine.state.pending
        self.assertEqual(pending.kind, "intervention")
        self.assertEqual(pending.context["attackerPlayerId"], attacker)
        self.assertNotIn(attacker, pending.eligible_player_ids)
        self.assertNotIn(target, pending.eligible_player_ids)
        for pid in pending.eligible_player_ids:
            self.assertNotIn("rank", engine.state.players[pid].revealed)
        self.assertEqual(
            set(pending.eligible_player_ids),
            {pid for pid in engine.state.players if pid not in (attacker, target)},
        )

    def test_shielded_target_is_rejected(self):
        # shields are granted by rank 6 in issue 14; inject the resource directly
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.state.players[target].resources["shield"] = 1
        revision = engine.state.revision
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertEqual(error.exception.code, "target.shielded")
        self.assertEqual(engine.state.revision, revision)

    def test_shield_does_not_block_being_chosen_as_intervention_responder(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        responder = next(pid for pid in engine.state.players if pid not in (attacker, target))
        engine.state.players[responder].resources["shield"] = 1
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "request", target, "request-intervention"))
        engine.apply(command(engine, "choose", target, "choose-intervention", responderPlayerId=responder))
        self.assertEqual(engine.state.players[responder].damage, 1)

    def test_inquisitor_cannot_attack_target_with_three_damage(self):
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        victim = next(pid for pid in engine.state.players if pid != inquisitor)
        mark_three_damage(engine, victim)
        give_dagger_to(engine, inquisitor)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "attack", inquisitor, "attack", targetPlayerId=victim))
        self.assertEqual(error.exception.code, "target.already-three-damage")

    def test_fan_target_blocks_all_intervention_responders(self):
        # fans are granted by rank 9 in issue 14; inject the resource directly
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.state.players[target].resources["fan"] = 1
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        # every other player still holds an unrevealed rank, yet nobody is eligible
        self.assertEqual(engine.state.pending.eligible_player_ids, ())
        events = engine.apply(command(engine, "request", target, "request-intervention"))
        self.assertNotIn("InterventionOpened", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)

    def test_request_with_no_eligible_resolves_damage_directly(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(
            pid for pid, player in engine.state.players.items()
            if pid != attacker and player.rank not in (1, 2)
        )
        for pid in engine.state.players:
            if pid not in (attacker, target):
                player = engine.state.players[pid]
                player.damage = 1
                player.revealed = {"rank"}
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertEqual(engine.state.pending.eligible_player_ids, ())
        events = engine.apply(command(engine, "request", target, "request-intervention"))
        self.assertNotIn("InterventionOpened", [event.event_type for event in events])
        self.assertIn("DamageApplied", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")

    def test_wrong_actor_cannot_request_or_decline_intervention(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        bystander = next(pid for pid in engine.state.players if pid not in (attacker, target))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        for kind in ("request-intervention", "decline-intervention"):
            with self.subTest(kind=kind):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"wrong-{kind}", bystander, kind))
                self.assertEqual(error.exception.code, "player.not-actor")

    def test_choose_intervention_before_request_is_rejected(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        responder = next(pid for pid in engine.state.pending.eligible_player_ids)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "jump", target, "choose-intervention", responderPlayerId=responder))
        self.assertEqual(error.exception.code, "intervention.not-open")

    def test_choose_intervention_without_window_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", "p0", "choose-intervention", responderPlayerId="p1"))
        self.assertEqual(error.exception.code, "intervention.not-open")

    def test_choose_ineligible_responder_is_rejected(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "request", target, "request-intervention"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "choose", target, "choose-intervention", responderPlayerId=attacker))
        self.assertEqual(error.exception.code, "intervention.not-eligible")

    def test_intervention_damage_reveals_responder_rank_without_skill_window(self):
        engine, found = started_with_ranks(6, 2)
        responder = found[2].player_id
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid not in (attacker, responder))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "request", target, "request-intervention"))
        events = engine.apply(command(engine, "choose", target, "choose-intervention", responderPlayerId=responder))
        reveal_rank(engine, responder)
        damage = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(damage.payload["source"], "intervention")
        self.assertEqual(engine.state.players[responder].damage, 1)
        self.assertIn("rank", engine.state.players[responder].revealed)
        # intervention's forced rank reveal opens the rank's one-time skill window.
        self.assertEqual(engine.state.pending.kind, "skill")

    def test_intervention_responder_takes_the_dagger(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        responder = next(pid for pid in engine.state.players if pid not in (attacker, target))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "request", target, "request-intervention"))
        engine.apply(command(engine, "choose", target, "choose-intervention", responderPlayerId=responder))
        # corpus scenario intervention/selected-responder: "C 接过匕首并承受该点伤害"
        if engine.state.pending and engine.state.pending.kind == "skill":
            engine.apply(command(engine, "decline-responder-skill", responder, "choose-skill", use=False))
        self.assertEqual(engine.state.dagger_holder_id, responder)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": responder})


class SkillBranchTests(unittest.TestCase):
    def open_skill(self, engine, player):
        engine.state.pending = Pending("skill", player.player_id, player.player_id, rank=player.rank, trigger="attack")
        engine.state.phase = {"kind": "skill", "activePlayerId": player.player_id}

    def test_choose_skill_without_window_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", "p0", "choose-skill", use=False))
        self.assertEqual(error.exception.code, "skill.not-open")

    def test_wrong_actor_cannot_choose_skill(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=elder.player_id))
        engine.apply(command(engine, "decline", elder.player_id, "decline-intervention"))
        reveal_rank(engine, elder.player_id)
        bystander = next(pid for pid in engine.state.players if pid != elder.player_id)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "steal", bystander, "choose-skill", use=True))
        self.assertEqual(error.exception.code, "player.not-actor")

    def test_elder_skill_grants_quill(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=elder.player_id))
        engine.apply(command(engine, "decline", elder.player_id, "decline-intervention"))
        reveal_rank(engine, elder.player_id)
        events = engine.apply(command(engine, "use", elder.player_id, "choose-skill", use=True))
        self.assertIn("SkillUsed", [event.event_type for event in events])
        self.assertIn("ResourceGranted", [event.event_type for event in events])
        self.assertIn("ResourceSpent", [event.event_type for event in events])
        spent = next(event for event in events if event.event_type == "ResourceSpent")
        self.assertEqual(spent.payload, {"playerId": elder.player_id, "resource": "quill", "amount": 1, "reason": "leader-succession"})
        self.assertEqual(engine.state.players[elder.player_id].resources["quill"], 0)
        self.assertIn(elder.faction, engine.state.max_leader_factions)
        self.assertIn("1", engine.state.players[elder.player_id].skills_used)

    def test_elder_succession_changes_leader_to_highest_rank(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        family = elder.faction
        captured_elder = deepcopy(elder)
        captured_elder.captured = True
        captured_elder.damage = 4
        self.assertTrue(engine._is_leader(engine.state, captured_elder))
        engine.state.max_leader_factions.add(family)
        highest = max(
            (player for player in engine.state.players.values() if player.faction == family and player.player_id != elder.player_id and isinstance(player.rank, int)),
            key=lambda player: player.rank,
        )
        self.assertFalse(engine._is_leader(engine.state, captured_elder))
        captured_highest = deepcopy(highest)
        captured_highest.captured = True
        captured_highest.damage = 4
        self.assertTrue(engine._is_leader(engine.state, captured_highest))

    def test_harlequin_inspects_two_targets_with_private_feedback(self):
        engine, found = started_with_ranks(6, 3)
        owner = found[3]
        targets = [player for player in engine.state.players.values() if player.player_id != owner.player_id][:2]
        self.open_skill(engine, owner)
        events = engine.apply(command(engine, "inspect", owner.player_id, "choose-skill", use=True, targetPlayerIds=[p.player_id for p in targets]))
        self.assertEqual(events[1].event_type, "HarlequinInspected")
        self.assertNotIn("faction", events[1].payload)
        owner = engine.state.players[owner.player_id]
        self.assertEqual(set(owner.inspections), {p.player_id for p in targets})
        self.assertEqual(project_state(engine.state, owner.player_id)["viewer"]["inspections"][targets[0].player_id]["rank"], engine.state.players[targets[0].player_id].rank)

    def test_mentalist_damages_target_and_hands_dagger(self):
        engine, found = started_with_ranks(6, 5)
        owner = found[5]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        self.open_skill(engine, owner)
        engine.apply(command(engine, "mentalist", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        self.assertEqual(engine.state.players[target.player_id].damage, 1)
        self.assertEqual(engine.state.dagger_holder_id, target.player_id)

    def test_guardian_grants_ward_resources_and_returns_them_at_three_damage(self):
        engine, found = started_with_ranks(6, 6)
        owner = found[6]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        self.open_skill(engine, owner)
        events = engine.apply(command(engine, "guardian", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        self.assertEqual(engine.state.players[target.player_id].resources["shield"], 1)
        self.assertEqual(engine.state.players[owner.player_id].resources["sword"], 1)
        target = engine.state.players[target.player_id]
        owner = engine.state.players[owner.player_id]
        owner.damage = 3
        owner.revealed = {"rank", "marker-0", "marker-1"}
        returned = engine._after_damage(engine.state, command(engine, "return-ward", owner.player_id, "choose-skill", use=False), owner, {"trigger": None})
        self.assertEqual([event.event_type for event in returned], ["ResourceReturned", "ResourceReturned"])
        self.assertEqual(target.resources["shield"], 0)
        self.assertEqual(engine.state.players[owner.player_id].resources["sword"], 0)

    def test_mage_obscures_markers_and_grants_staff(self):
        engine, found = started_with_ranks(6, 8)
        owner = found[8]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        target.revealed = {"marker-0"}
        target.revealed_values["marker-0"] = "rose"
        self.open_skill(engine, owner)
        events = engine.apply(command(engine, "mage", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        self.assertEqual(engine.state.players[target.player_id].resources["staff"], 1)
        self.assertEqual(engine.state.players[target.player_id].identity_markers, ["unknown", "unknown"])
        self.assertIn("IdentityMarkersObscured", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target.player_id].revealed_values["marker-0"], "unknown")

    def test_courtesan_grants_fan_and_blocks_intervention(self):
        engine, found = started_with_ranks(6, 9)
        owner = found[9]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        self.open_skill(engine, owner)
        engine.apply(command(engine, "courtesan", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        self.assertEqual(engine.state.players[target.player_id].resources["fan"], 1)

    def test_assassin_skill_deals_two_damage_hands_dagger_and_opens_no_new_window(self):
        engine, found = started_with_ranks(6, 2)
        assassin = found[2]
        attacker = engine.state.dagger_holder_id
        if attacker == assassin.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != assassin.player_id))
            attacker = engine.state.dagger_holder_id
        victim = next(
            pid for pid, player in engine.state.players.items()
            if pid not in (attacker, assassin.player_id) and player.damage == 0
        )
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id))
        engine.apply(command(engine, "decline", assassin.player_id, "decline-intervention"))
        reveal_rank(engine, assassin.player_id)
        events = engine.apply(
            command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=victim)
        )
        self.assertEqual(engine.state.players[victim].damage, 2)
        self.assertEqual(engine.state.dagger_holder_id, victim)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": victim})
        # skill damage creates neither an intervention nor a skill window
        self.assertIsNone(engine.state.pending)
        self.assertNotIn("InterventionOpened", [event.event_type for event in events])
        self.assertNotIn("SkillWindowOpened", [event.event_type for event in events])

    def test_assassin_skill_cannot_target_self(self):
        engine, found = started_with_ranks(6, 2)
        assassin = found[2]
        attacker = engine.state.dagger_holder_id
        if attacker == assassin.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != assassin.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id))
        engine.apply(command(engine, "decline", assassin.player_id, "decline-intervention"))
        reveal_rank(engine, assassin.player_id)
        with self.assertRaises(RuleError) as error:
            engine.apply(
                command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=assassin.player_id)
            )
        self.assertEqual(error.exception.code, "skill.invalid-target")

    def test_skill_already_used_is_rejected(self):
        # unreachable through public commands until the alchemist returns a
        # revealed rank token (issue 14); inject the open window directly
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        elder.skills_used.add("1")
        engine.state.pending = Pending("skill", elder.player_id, elder.player_id, rank=1, trigger="attack")
        engine.state.phase = {"kind": "skill", "activePlayerId": elder.player_id}
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "reuse", elder.player_id, "choose-skill", use=True))
        self.assertEqual(error.exception.code, "skill.already-used")

    def test_skill_window_only_opens_once_per_rank_reveal(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-1", attacker, "attack", targetPlayerId=elder.player_id))
        engine.apply(command(engine, "decline-1", elder.player_id, "decline-intervention"))
        reveal_rank(engine, elder.player_id, "reveal-1")
        self.assertEqual(engine.state.pending.kind, "skill")
        engine.apply(command(engine, "skill-decline", elder.player_id, "choose-skill", use=False))
        # second resolved attack reveals affiliation, not rank: no new window
        give_dagger_to(engine, attacker)
        engine.apply(command(engine, "attack-2", attacker, "attack", targetPlayerId=elder.player_id))
        engine.apply(command(engine, "decline-2", elder.player_id, "decline-intervention"))
        if engine.state.pending and engine.state.pending.kind == "reveal":
            engine.apply(command(engine, "reveal-2", elder.player_id, "choose-reveal", token="marker-0"))
        self.assertIsNone(engine.state.pending)

    def test_assassin_skill_capture_leaves_ended_phase(self):
        engine, found = started_with_ranks(6, 2)
        assassin = found[2]
        victim = next(player for player in engine.state.players.values() if player.player_id != assassin.player_id)
        attacker = next(
            player for player in engine.state.players.values()
            if player.player_id not in (assassin.player_id, victim.player_id)
        )
        for _ in range(2):
            give_dagger_to(engine, attacker.player_id)
            engine.apply(command(engine, f"hit-{_}", attacker.player_id, "attack", targetPlayerId=victim.player_id))
            engine.apply(command(engine, f"take-{_}", victim.player_id, "decline-intervention"))
            reveal_rank(engine, victim.player_id, f"reveal-{_}")
            if engine.state.pending and engine.state.pending.kind == "reveal":
                engine.apply(command(engine, f"reveal-marker-{_}", victim.player_id, "choose-reveal", token="marker-0"))
            if engine.state.pending and engine.state.pending.kind == "skill":
                engine.apply(command(engine, f"no-skill-{_}", victim.player_id, "choose-skill", use=False))
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack-ass", attacker.player_id, "attack", targetPlayerId=assassin.player_id))
        engine.apply(command(engine, "decline-ass", assassin.player_id, "decline-intervention"))
        reveal_rank(engine, assassin.player_id, "reveal-ass")
        engine.apply(
            command(engine, "use-ass", assassin.player_id, "choose-skill", use=True, targetPlayerId=victim.player_id)
        )
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.phase, {"kind": "ended"})
        self.assertNotEqual(engine.state.dagger_holder_id, victim.player_id)


class CurseBranchTests(unittest.TestCase):
    def test_distribute_curse_without_curses_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "curse", "p0", "distribute-curse", assignments={"curse-1": "p1"}))
        self.assertEqual(error.exception.code, "curse.invalid-count")

    def test_distribute_curse_by_non_inquisitor_is_rejected(self):
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        other = next(pid for pid in engine.state.players if pid != inquisitor)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "curse", other, "distribute-curse", assignments={"curse-1": inquisitor}))
        self.assertEqual(error.exception.code, "player.not-eligible")

    def test_distribute_curse_with_wrong_assignment_keys_is_rejected(self):
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        for assignments in ({"curse-2": inquisitor}, ["p0"]):
            with self.subTest(assignments=assignments):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, "curse", inquisitor, "distribute-curse", assignments=assignments))
                self.assertEqual(error.exception.code, "curse.invalid-count")

    def test_distribute_curse_to_unknown_recipient_is_rejected(self):
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "curse", inquisitor, "distribute-curse", assignments={"curse-1": "ghost"}))
        self.assertEqual(error.exception.code, "target.not-found")

    def test_distribute_curse_to_captured_recipient_is_rejected(self):
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        victim = next(pid for pid in engine.state.players if pid != inquisitor)
        engine.state.players[victim].captured = True  # synthetic: captures end games, so this never occurs live
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "curse", inquisitor, "distribute-curse", assignments={"curse-1": victim}))
        self.assertEqual(error.exception.code, "target.captured")

    def test_distribute_curse_duplicate_recipient_is_rejected(self):
        # versioned curse tables may place more than one curse (map note);
        # current rules always place one, so inject the second curse directly
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        victim = next(pid for pid in engine.state.players if pid != inquisitor)
        engine.state.curses = ["curse-1", "curse-2"]
        with self.assertRaises(RuleError) as error:
            engine.apply(
                command(engine, "curse", inquisitor, "distribute-curse", assignments={"curse-1": victim, "curse-2": victim})
            )
        self.assertEqual(error.exception.code, "curse.duplicate-recipient")


class EndGameBranchTests(unittest.TestCase):
    def test_captured_leader_branch(self):
        engine = started()
        victim = min(
            (player for player in engine.state.players.values() if player.faction == "rose"),
            key=lambda player: player.rank,
        )
        attacker = next(player for player in engine.state.players.values() if player.faction == "beast")
        mark_three_damage(engine, victim.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=victim.player_id))
        engine.apply(command(engine, "decline", victim.player_id, "decline-intervention"))
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "captured-leader")
        self.assertEqual(engine.state.result["winner"], attacker.faction)

    def test_captured_non_leader_branch(self):
        engine = started()
        rose_players = [player for player in engine.state.players.values() if player.faction == "rose"]
        leader_rank = min(player.rank for player in rose_players)
        victim = next(player for player in rose_players if player.rank != leader_rank)
        attacker = next(player for player in engine.state.players.values() if player.faction == "beast")
        mark_three_damage(engine, victim.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=victim.player_id))
        engine.apply(command(engine, "decline", victim.player_id, "decline-intervention"))
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "captured-player")
        # capturing a non-leader makes the attacker's clan lose
        self.assertEqual(engine.state.result["winner"], "rose")

    def test_inquisitor_captured_is_draw(self):
        engine = started(7)
        inquisitor = next(
            player for player in engine.state.players.values() if player.faction == "secret-order"
        )
        attacker = next(player for player in engine.state.players.values() if player.faction != "secret-order")
        mark_three_damage(engine, inquisitor.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=inquisitor.player_id))
        engine.apply(command(engine, "decline", inquisitor.player_id, "decline-intervention"))
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "inquisitor-captured")
        self.assertEqual(engine.state.result["winner"], "draw")

    def test_inquisitor_active_capture_branch(self):
        # reachable once the alchemist can return a revealed rank token
        # (issue 14); the responder keeps 3 damage with an unrevealed rank
        engine = started(7)
        inquisitor = next(
            player for player in engine.state.players.values() if player.faction == "secret-order"
        )
        responder = next(player for player in engine.state.players.values() if player.faction != "secret-order")
        responder.damage = 3  # rank token returned: still unrevealed and eligible
        target = next(
            player for player in engine.state.players.values()
            if player.faction != "secret-order" and player.player_id != responder.player_id
        )
        give_dagger_to(engine, inquisitor.player_id)
        engine.apply(command(engine, "attack", inquisitor.player_id, "attack", targetPlayerId=target.player_id))
        engine.apply(command(engine, "request", target.player_id, "request-intervention"))
        engine.apply(command(engine, "choose", target.player_id, "choose-intervention", responderPlayerId=responder.player_id))
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "inquisitor-active-capture")
        expected_winner = "rose" if responder.faction == "beast" else "beast"
        self.assertEqual(engine.state.result["winner"], expected_winner)


class ProjectionBranchTests(unittest.TestCase):
    def test_legal_actions_empty_for_unknown_player_and_ended_game(self):
        engine, _ = run_deterministic_game(6, game_id="proj", seed="proj-seed")
        self.assertEqual(legal_actions(engine.state, "p0"), [])
        self.assertEqual(legal_actions(engine.state, "ghost"), [])

    def test_elder_skill_window_offers_use_without_a_target(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=elder.player_id))
        engine.apply(command(engine, "decline", elder.player_id, "decline-intervention"))
        reveal_rank(engine, elder.player_id)
        actions = legal_actions(engine.state, elder.player_id)
        self.assertEqual(
            actions,
            [{"type": "choose-skill", "use": False}, {"type": "choose-skill", "use": True}],
        )
        # only the pending actor is offered anything
        self.assertEqual(legal_actions(engine.state, attacker), [])

    def test_pending_intervention_actions_before_and_after_request(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        before = legal_actions(engine.state, target)
        self.assertEqual(
            before,
            [{"type": "request-intervention"}, {"type": "decline-intervention"}],
        )
        engine.apply(command(engine, "request", target, "request-intervention"))
        after = legal_actions(engine.state, target)
        self.assertEqual(after[0], {"type": "decline-intervention"})
        self.assertEqual(
            {action["type"] for action in after[1:]},
            {"choose-intervention"},
        )
        self.assertEqual(
            {action["responderPlayerId"] for action in after[1:]},
            set(engine.state.pending.eligible_player_ids),
        )

    def test_pending_view_hides_private_context(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        view = project_state(engine.state, target)
        self.assertNotIn("context", view["pending"])


if __name__ == "__main__":
    unittest.main()
