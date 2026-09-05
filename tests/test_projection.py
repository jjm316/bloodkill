import unittest

from blood_bound import Command, RulesEngine, project_state


def command(engine, command_id, actor, kind, **payload):
    return Command(command_id, engine.state.game_id, actor, engine.state.revision, kind, payload)


def reveal_rank(engine, player_id, command_id="reveal-rank"):
    if engine.state.pending and engine.state.pending.kind == "reveal":
        engine.apply(command(engine, command_id, player_id, "choose-reveal", token="rank"))


def decline_poll(engine):
    """Answer the open intervention poll: every eligible player declines to volunteer."""
    while engine.state.pending and engine.state.pending.kind == "intervention" and engine.state.pending.context.get("stage") == "poll":
        pending = engine.state.pending
        responses = pending.context["responses"]
        responder = next(pid for pid in pending.eligible_player_ids if pid not in responses)
        engine.apply(command(engine, f"respond-{engine.state.revision}", responder, "respond-intervention", volunteer=False))


class FixedClock:
    def __call__(self):
        return 1000.0


class ProjectionTests(unittest.TestCase):
    def started(self, count=6, game_id="g1", seed="fixed-seed"):
        engine = RulesEngine.new_game(game_id, seed, clock=FixedClock())
        for index in range(count):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
        engine.apply(command(engine, "start", None, "start-game"))
        return engine

    def test_spectator_sees_no_identity_or_seed(self):
        engine = self.started()
        view = project_state(engine.state)
        self.assertIsNone(view["viewer"])
        self.assertEqual(view["legalActions"], [])
        self.assertNotIn("seed", view)
        self.assertNotIn("clueIcon", view)
        self.assertNotIn("seenNeighbourClue", view)
        for player in view["players"]:
            self.assertNotIn("faction", player)
            self.assertNotIn("rank", player)
            self.assertNotIn("clueIcon", player)

    def test_viewer_sees_own_clue_icon_and_right_neighbours_icon(self):
        engine = self.started(7)
        ordered = sorted(engine.state.players.values(), key=lambda player: player.seat)
        for index, player in enumerate(ordered):
            view = project_state(engine.state, player.player_id)
            self.assertEqual(view["viewer"]["clueIcon"], player.clue_icon)
            neighbour = ordered[index - 1]
            self.assertEqual(
                view["viewer"]["seenNeighbourClue"],
                {"playerId": neighbour.player_id, "icon": neighbour.clue_icon},
            )

    def test_projection_hides_clue_icons_of_anyone_but_self_and_right_neighbour(self):
        engine = self.started(6)
        ordered = sorted(engine.state.players.values(), key=lambda player: player.seat)

        def icon_fields(value):
            """Every icon-bearing (key, value) pair anywhere in the view tree."""
            found = []
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ("clueIcon", "icon"):
                        found.append((key, item))
                    found.extend(icon_fields(item))
            elif isinstance(value, list):
                for item in value:
                    found.extend(icon_fields(item))
            return found

        for player in ordered:
            index = ordered.index(player)
            neighbour = ordered[index - 1]
            view = project_state(engine.state, player.player_id)
            # the only icon fields in the whole view are the viewer's own and the
            # right neighbour's; no other player's icon appears anywhere
            self.assertEqual(
                sorted(icon_fields(view)),
                sorted([("clueIcon", player.clue_icon), ("icon", neighbour.clue_icon)]),
            )
        # spectator and replay-style projections carry no icon field at all
        self.assertEqual(icon_fields(project_state(engine.state)), [])

    def test_player_sees_only_their_own_identity(self):
        engine = self.started()
        viewer = next(iter(engine.state.players))
        view = project_state(engine.state, viewer)
        self.assertEqual(view["viewer"]["playerId"], viewer)
        self.assertIn("faction", view["viewer"]["identity"])
        self.assertIn("rank", view["viewer"]["identity"])
        # no other player's identity leaks through the public player list
        for player in view["players"]:
            self.assertNotIn("faction", player)
            self.assertNotIn("rank", player)

    def test_revealed_clues_appear_only_after_damage(self):
        engine = self.started()
        holder = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != holder)
        before = project_state(engine.state, holder)
        self.assertEqual(before["players"][0]["revealed"], {"markers": [None, None]})
        engine.apply(command(engine, "attack", holder, "attack", targetPlayerId=target))
        decline_poll(engine)
        reveal_rank(engine, target)
        after = project_state(engine.state, holder)
        target_view = next(p for p in after["players"] if p["playerId"] == target)
        self.assertIn("rank", target_view["revealed"])

    def test_inquisitor_gets_private_curse_assignment_view(self):
        engine = self.started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        other = next(pid for pid in engine.state.players if pid != inquisitor)
        inquisitor_view = project_state(engine.state, inquisitor)
        other_view = project_state(engine.state, other)
        self.assertEqual(inquisitor_view["viewer"]["cursesToDistribute"], ["true-curse-1", "false-curse-1"])
        self.assertEqual(other_view["viewer"]["cursesToDistribute"], [])
        self.assertIn({"type": "distribute-curse"}, inquisitor_view["legalActions"])
        self.assertNotIn({"type": "distribute-curse"}, other_view["legalActions"])

    def test_dagger_holder_actions_are_derived_from_authority(self):
        engine = self.started()
        holder = engine.state.dagger_holder_id
        actions = project_state(engine.state, holder)["legalActions"]
        types = {action["type"] for action in actions}
        self.assertIn("pass-dagger", types)
        self.assertIn("attack", types)
        # a non-holder has no actions in the action phase
        other = next(pid for pid in engine.state.players if pid != holder)
        self.assertEqual(project_state(engine.state, other)["legalActions"], [])

    def test_rank_two_skill_window_offers_valid_targets(self):
        engine = self.started(6)
        rank_two = next(pid for pid, player in engine.state.players.items() if player.rank == 2)
        attacker = next(pid for pid in engine.state.players if pid != rank_two)
        holder = engine.state.dagger_holder_id
        if holder != attacker:
            engine.apply(command(engine, "pass", holder, "pass-dagger", targetPlayerId=attacker))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=rank_two))
        decline_poll(engine)
        reveal_rank(engine, rank_two)
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 2)
        actions = project_state(engine.state, rank_two)["legalActions"]
        use_actions = [action for action in actions if action.get("use")]
        self.assertTrue(use_actions)
        for action in use_actions:
            target = action["targetPlayerId"]
            self.assertNotEqual(target, rank_two)
            self.assertFalse(engine.state.players[target].captured)


if __name__ == "__main__":
    unittest.main()
