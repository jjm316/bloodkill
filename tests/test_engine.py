from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from blood_bound import (
    Command,
    ContentBundle,
    ContentValidationError,
    ReplayPlayer,
    RuleError,
    RulesEngine,
    SaveError,
    create_debug_link,
    create_save_document,
    dump_game,
    load_content,
    load_game,
    load_game_bytes,
    load_debug_link,
    migrate_save_document,
    migrate_save_file,
    run_deterministic_game,
    save_game,
    validate_content,
)


class FixedClock:
    def __call__(self):
        return 1000.0


def command(engine, command_id, actor, kind, **payload):
    return Command(command_id, engine.state.game_id, actor, engine.state.revision, kind, payload)


def reveal_rank(engine, player_id, command_id="reveal-rank"):
    if engine.state.pending and engine.state.pending.kind == "reveal":
        engine.apply(command(engine, command_id, player_id, "choose-reveal", token="rank"))


class RulesEngineTests(unittest.TestCase):
    def started(self, count=6):
        engine = RulesEngine.new_game("g1", "fixed-seed", clock=FixedClock())
        for index in range(count):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
        engine.apply(command(engine, "start", None, "start-game"))
        return engine

    def test_setup_is_deterministic_and_odd_games_deal_true_and_false_curses(self):
        left = self.started(7)
        right = self.started(7)
        self.assertEqual(
            [(p.player_id, p.faction, p.rank) for p in left.state.players.values()],
            [(p.player_id, p.faction, p.rank) for p in right.state.players.values()],
        )
        self.assertEqual(left.state.curses, ["true-curse-1", "false-curse-1"])
        inquisitor_count = sum(player.faction == "secret-order" for player in left.state.players.values())
        self.assertEqual(len(left.state.curses), inquisitor_count * 2)

    def test_start_logs_clue_icon_showing_pairs_without_icons(self):
        engine = self.started(6)
        start_events = [event for event in engine.state.events if event.command_id == "start"]
        self.assertEqual([event.event_type for event in start_events], ["GameStarted", "ClueIconsShown", "PhaseChanged"])
        payload = next(event for event in start_events if event.event_type == "ClueIconsShown").payload
        self.assertEqual(set(payload), {"pairs"})
        ordered = sorted(engine.state.players.values(), key=lambda player: player.seat)
        expected = [
            {"fromPlayerId": player.player_id, "toPlayerId": ordered[(index + 1) % len(ordered)].player_id}
            for index, player in enumerate(ordered)
        ]
        self.assertEqual(payload["pairs"], expected)
        for pair in payload["pairs"]:
            self.assertEqual(set(pair), {"fromPlayerId", "toPlayerId"})
            self.assertTrue(set(pair.values()) <= set(engine.state.players))

    def test_rank_three_icon_is_hostile_and_inquisitor_icon_contradicts_affiliation(self):
        saw_rank_three = False
        for seed_index in range(20):
            engine = RulesEngine.new_game("g1", f"icon-seed-{seed_index}", clock=FixedClock())
            for index in range(7):
                engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}"))
            engine.apply(command(engine, "start", None, "start-game"))
            for player in engine.state.players.values():
                if player.rank == 3 and player.faction in {"rose", "beast"}:
                    saw_rank_three = True
                    self.assertEqual(player.clue_icon, "beast" if player.faction == "rose" else "rose", player.player_id)
                if player.faction == "secret-order":
                    self.assertIn(player.clue_icon, {"rose", "beast"}, player.player_id)
        self.assertTrue(saw_rank_three)

    def test_pass_dagger_and_idempotency(self):
        engine = self.started()
        holder = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != holder)
        cmd = command(engine, "pass", holder, "pass-dagger", targetPlayerId=target)
        first = engine.apply(cmd)
        second = engine.apply(cmd)
        self.assertEqual(first, second)
        self.assertEqual(engine.state.dagger_holder_id, target)
        self.assertEqual([event.revision for event in first], [10, 11])
        self.assertEqual(len({event.event_id for event in first}), 2)
        self.assertEqual(first[-1].event_type, "PhaseChanged")

    def test_attack_decline_reveals_and_opens_skill_window(self):
        engine = self.started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid, player in engine.state.players.items() if pid != attacker and player.rank in (1, 2))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        events = engine.apply(command(engine, "decline", target, "decline-intervention"))
        reveal_rank(engine, target)
        self.assertIn("DamageApplied", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.pending.kind, "skill")
        engine.apply(command(engine, "skill-no", target, "choose-skill", use=False))
        self.assertIsNone(engine.state.pending)

    def test_alchemist_attack_trigger_does_not_open_skill_window(self):
        engine = self.started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid, player in engine.state.players.items() if pid != attacker and player.rank == 4)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        events = engine.apply(command(engine, "decline", target, "decline-intervention"))
        reveal_rank(engine, target)
        self.assertIn("DamageApplied", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertIsNone(engine.state.pending)

    def test_inquisitor_rank_reveal_does_not_open_skill_window(self):
        engine = self.started(7)
        attacker = engine.state.dagger_holder_id
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        self.assertNotEqual(attacker, inquisitor)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=inquisitor))
        engine.apply(command(engine, "decline", inquisitor, "decline-intervention"))
        reveal_rank(engine, inquisitor)
        self.assertEqual(engine.state.players[inquisitor].damage, 1)
        self.assertIsNone(engine.state.pending)

    def test_intervention_requires_rank_in_supply(self):
        engine = self.started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "request", target, "request-intervention"))
        responder = engine.state.pending.eligible_player_ids[0]
        engine.apply(command(engine, "choose", target, "choose-intervention", responderPlayerId=responder))
        reveal_rank(engine, responder)
        self.assertEqual(engine.state.players[responder].damage, 1)
        self.assertIn("rank", engine.state.players[responder].revealed)

    def test_stale_revision_is_rejected(self):
        engine = self.started()
        with self.assertRaises(RuleError) as error:
            engine.apply(Command("stale", "g1", None, 0, "start-game", {}))
        self.assertEqual(error.exception.code, "game.revision-conflict")

    def test_curse_distribution_is_private_to_the_inquisitor_command(self):
        engine = self.started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        recipients = [pid for pid in engine.state.players if pid != inquisitor][: len(engine.state.curses)]
        assignments = dict(zip(engine.state.curses, recipients))
        events = engine.apply(command(engine, "curse", inquisitor, "distribute-curse", assignments=assignments))
        self.assertEqual([event.event_type for event in events], ["CurseDistributed"] * len(assignments))
        self.assertEqual(engine.state.curses, [])
        self.assertEqual(engine.state.curse_assignments, assignments)

    def test_deterministic_runner_closes_even_and_odd_games(self):
        even_engine, even_replay = run_deterministic_game(6)
        odd_engine, odd_replay = run_deterministic_game(7)
        self.assertEqual(even_engine.state.status, "ended")
        self.assertEqual(odd_engine.state.status, "ended")
        self.assertEqual(even_engine.state.revision, even_replay.final_revision)
        self.assertEqual(odd_engine.state.revision, odd_replay.final_revision)
        self.assertTrue(even_engine.state.result["ranking"])
        self.assertIn("explanationKey", odd_engine.state.result)
        self.assertEqual(
            [event.revision for event in even_engine.state.events],
            list(range(1, even_engine.state.revision + 1)),
        )

    def test_deterministic_runner_supports_maximum_player_count(self):
        engine, replay = run_deterministic_game(12, game_id="max", seed="max-seed")
        self.assertEqual(len(engine.state.players), 12)
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(len(replay.command_ids), len(set(replay.command_ids)))

    def test_checkpoint_resume_continues_without_double_applying(self):
        engine = self.started()
        holder = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != holder)
        checkpoint = engine.checkpoint()
        resumed = RulesEngine.resume_from_checkpoint(checkpoint, clock=FixedClock())
        original = resumed.apply(command(resumed, "resume-pass", holder, "pass-dagger", targetPlayerId=target))
        retry = resumed.apply(Command("resume-pass", "g1", holder, checkpoint.revision, "pass-dagger", {"targetPlayerId": target}))
        self.assertEqual(original, retry)
        self.assertEqual(resumed.state.revision, checkpoint.revision + 2)


class ContentCatalogTests(unittest.TestCase):
    def test_bundled_content_is_complete_and_localized(self):
        content = load_content()
        self.assertEqual(content.catalog["contentVersion"], "0.1.0")
        self.assertEqual(len(content.catalog["units"]), 19)
        self.assertEqual(content.text("en", "unit.rose"), "Rose identity")
        self.assertEqual(content.text("zh-Hans", "board.supply"), "供应区")

    def test_duplicate_ids_fail_before_a_client_can_consume_catalog(self):
        content = load_content()
        catalog = deepcopy(content.catalog)
        catalog["units"][1]["id"] = catalog["units"][0]["id"]
        invalid = ContentBundle(catalog, content.translations, content.licenses)
        with self.assertRaises(ContentValidationError) as error:
            validate_content(invalid)
        self.assertEqual(error.exception.code, "content.duplicate-id")

    def test_missing_translation_and_asset_license_fail_validation(self):
        content = load_content()
        translations = deepcopy(content.translations)
        del translations["zh-Hans"]["unit.rose"]
        with self.assertRaises(ContentValidationError) as error:
            validate_content(ContentBundle(content.catalog, translations, content.licenses))
        self.assertEqual(error.exception.code, "content.translation-missing")

        catalog = deepcopy(content.catalog)
        catalog["assets"][0]["licenseId"] = "unknown"
        with self.assertRaises(ContentValidationError) as error:
            validate_content(ContentBundle(catalog, content.translations, content.licenses))
        self.assertEqual(error.exception.code, "content.asset-license")


class SaveReplayTests(unittest.TestCase):
    def completed_game(self):
        return run_deterministic_game(7, game_id="saved-game", seed="saved-seed")[0]

    def test_completed_game_replays_one_command_at_a_time(self):
        original = self.completed_game()
        document = create_save_document(original)
        replay = ReplayPlayer(document)
        observed_revisions = []
        while step := replay.step():
            observed_revisions.append(step.revision)
        self.assertTrue(replay.complete)
        self.assertEqual(observed_revisions[-1], original.state.revision)
        self.assertEqual(replay.engine.state.result, original.state.result)
        restored = load_game_bytes(dump_game(original))
        self.assertEqual(restored.state.revision, original.state.revision)
        self.assertEqual(restored.state.events, original.state.events)

    def test_gzip_local_save_round_trips(self):
        original = self.completed_game()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paused-game.json.gz"
            save_game(original, path)
            self.assertTrue(path.read_bytes().startswith(b"\x1f\x8b"))
            restored = load_game(path)
        self.assertEqual(restored.state.result, original.state.result)

    def test_paused_game_and_debug_link_round_trip(self):
        engine = RulesEngine.new_game("paused", "paused-seed", clock=FixedClock())
        for index in range(6):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}"))
        engine.apply(command(engine, "start", None, "start-game"))
        holder = engine.state.dagger_holder_id
        target = next(player_id for player_id in engine.state.players if player_id != holder)
        engine.apply(command(engine, "attack", holder, "attack", targetPlayerId=target))
        restored = load_game_bytes(dump_game(engine))
        self.assertEqual(restored.state.pending.kind, "intervention")
        link = create_debug_link(engine, "https://example.test/replay")
        self.assertIn("#save=", link)
        self.assertEqual(load_debug_link(link).state.revision, engine.state.revision)

    def test_tampered_or_truncated_log_has_a_stable_error(self):
        document = create_save_document(self.completed_game())
        document["events"][-1]["event"]["eventType"] = "Changed"
        with self.assertRaises(SaveError) as error:
            load_game_bytes(json.dumps(document).encode("utf-8"))
        self.assertEqual(error.exception.code, "save.hash-chain-broken")
        with self.assertRaises(SaveError) as error:
            load_game_bytes(b'{"schemaVersion":')
        self.assertEqual(error.exception.code, "save.invalid-json")

    def test_schema_one_fixture_migrates_without_changing_ruleset(self):
        original = self.completed_game()
        current = create_save_document(original)
        legacy = {
            "schemaVersion": 1,
            "gameId": current["game"]["gameId"],
            "seed": current["game"]["seed"],
            "rulesetId": current["ruleset"]["id"],
            "rulesetVersion": current["ruleset"]["version"],
            "checkpoint": deepcopy(current["snapshot"]),
            "eventLog": [record["event"] for record in current["events"]],
            "commandLog": deepcopy(current["commands"]),
        }
        migrated = migrate_save_document(legacy)
        self.assertEqual(migrated["migration"], {"fromSchemaVersion": 1, "toSchemaVersion": 2})
        restored = load_game_bytes(json.dumps(legacy).encode("utf-8"))
        self.assertEqual(restored.state.result, original.state.result)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.json"
            target = Path(directory) / "upgraded.json.gz"
            source.write_text(json.dumps(legacy), encoding="utf-8")
            migrate_save_file(source, target)
            self.assertEqual(load_game(target).state.result, original.state.result)


if __name__ == "__main__":
    unittest.main()
