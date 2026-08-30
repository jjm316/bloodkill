import json
import tempfile
import unittest
from pathlib import Path

from blood_bound import Command, RuleError, RulesEngine, project_state

from server.rooms import FINISHED_GAMES_TO_KEEP, Room, RoomManager


def command(engine, command_id, actor, kind, **payload):
    return Command(command_id, engine.state.game_id, actor, engine.state.revision, kind, payload)


def resolve_reveal_windows(manager, room, actor, prefix):
    while room.engine.state.pending and room.engine.state.pending.kind == "reveal":
        pending = room.engine.state.pending
        token = pending.context["eligibleTokens"][0]
        payload = {"token": token}
        if token.startswith("marker-") and room.engine.state.players[actor].identity_markers[int(token[-1])] == "wild":
            payload["color"] = "rose"
        manager.apply_command(room, command(room.engine, f"{prefix}-{room.engine.state.revision}", actor, "choose-reveal", **payload))


class RoomManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.manager = RoomManager(Path(self._tmp.name))

    def create_room(self):
        return self.manager.create_room()

    def test_create_room_allocates_six_digit_code_and_persists(self):
        room = self.create_room()
        self.assertEqual(len(room.code), 6)
        self.assertTrue(room.code.isdigit())
        self.assertEqual(room.status, "waiting")
        self.assertTrue(room.host_token)
        self.assertTrue((self.manager.saves_dir / f"{room.game_id}.json.gz").exists())

    def test_join_then_resume_by_name(self):
        room = self.create_room()
        player_id, is_new = self.manager.join_or_resume(room, "Alice")
        self.assertTrue(is_new)
        self.assertEqual(room.player_id_for_name("Alice"), player_id)
        resumed, is_new = self.manager.join_or_resume(room, "Alice")
        self.assertFalse(is_new)
        self.assertEqual(resumed, player_id)

    def test_bind_host_records_seat_and_survives_restore(self):
        room = self.create_room()
        self.assertIsNone(room.host_player_id)
        player_id, _ = self.manager.join_or_resume(room, "Alice")
        self.manager.bind_host(room, player_id)
        self.assertEqual(room.host_player_id, player_id)
        restored_manager = RoomManager(Path(self._tmp.name))
        restored_manager.restore()
        restored = restored_manager.get_room(room.code)
        self.assertEqual(restored.host_player_id, player_id)

    def test_join_after_start_is_rejected(self):
        room = self.create_room()
        for index in range(6):
            self.manager.join_or_resume(room, f"P{index}")
        self.manager.start_game(room)
        self.assertEqual(room.status, "playing")
        with self.assertRaises(RuleError) as error:
            self.manager.join_or_resume(room, "Latecomer")
        self.assertEqual(error.exception.code, "room.already-started")

    def test_locked_room_rejects_new_players_but_lets_known_resume(self):
        room = self.create_room()
        self.manager.join_or_resume(room, "Alice")
        self.manager.set_locked(room, True)
        with self.assertRaises(RuleError) as error:
            self.manager.join_or_resume(room, "Bob")
        self.assertEqual(error.exception.code, "room.locked")
        player_id, is_new = self.manager.join_or_resume(room, "Alice")
        self.assertFalse(is_new)

    def test_start_requires_six_players(self):
        room = self.create_room()
        for index in range(5):
            self.manager.join_or_resume(room, f"P{index}")
        with self.assertRaises(RuleError) as error:
            self.manager.start_game(room)
        self.assertEqual(error.exception.code, "game.player-count")

    def test_auto_save_updates_after_each_command_and_restore_recovers(self):
        room = self.create_room()
        for index in range(6):
            self.manager.join_or_resume(room, f"P{index}")
        self.manager.start_game(room)
        holder = room.engine.state.dagger_holder_id
        target = next(pid for pid in room.engine.state.players if pid != holder)
        self.manager.apply_command(
            room, command(room.engine, "attack", holder, "attack", targetPlayerId=target)
        )
        # a fresh manager restoring from disk sees the same game at the same revision
        restored_manager = RoomManager(Path(self._tmp.name))
        restored_manager.restore()
        restored = restored_manager.get_room(room.code)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.engine.state.revision, room.engine.state.revision)
        self.assertEqual(restored.engine.state.dagger_holder_id, room.engine.state.dagger_holder_id)
        self.assertEqual(restored.host_token, room.host_token)

    def test_finished_games_are_retained_to_cap(self):
        # create, fill, and end more rooms than the cap
        for _ in range(FINISHED_GAMES_TO_KEEP + 3):
            room = self.create_room()
            for index in range(6):
                self.manager.join_or_resume(room, f"P{index}")
            self.manager.start_game(room)
            # finish deterministically: keep attacking the same victim until ended
            holder = room.engine.state.dagger_holder_id
            victim = next(pid for pid in room.engine.state.players if pid != holder)
            for turn in range(40):
                current = room.engine.state.dagger_holder_id
                if current != holder:
                    self.manager.apply_command(
                        room, command(room.engine, f"pass-{turn}", current, "pass-dagger", targetPlayerId=holder)
                    )
                self.manager.apply_command(
                    room, command(room.engine, f"attack-{turn}", holder, "attack", targetPlayerId=victim)
                )
                if room.engine.state.pending and room.engine.state.pending.kind == "intervention":
                    self.manager.apply_command(
                        room, command(room.engine, f"decline-{turn}", victim, "decline-intervention")
                    )
                resolve_reveal_windows(self.manager, room, victim, f"reveal-{turn}")
                if room.engine.state.pending and room.engine.state.pending.kind == "skill":
                    self.manager.apply_command(
                        room, command(room.engine, f"skill-{turn}", victim, "choose-skill", use=False)
                    )
                if room.status == "ended":
                    break
            self.assertEqual(room.status, "ended")
        finished = [room for room in self.manager.rooms.values() if room.status == "ended"]
        self.assertEqual(len(finished), FINISHED_GAMES_TO_KEEP)

    def test_replay_returns_public_spectator_steps(self):
        room = self.create_room()
        for index in range(6):
            self.manager.join_or_resume(room, f"P{index}")
        self.manager.start_game(room)
        holder = room.engine.state.dagger_holder_id
        victim = next(pid for pid in room.engine.state.players if pid != holder)
        for turn in range(40):
            current = room.engine.state.dagger_holder_id
            if current != holder:
                self.manager.apply_command(
                    room, command(room.engine, f"pass-{turn}", current, "pass-dagger", targetPlayerId=holder)
                )
            self.manager.apply_command(
                room, command(room.engine, f"attack-{turn}", holder, "attack", targetPlayerId=victim)
            )
            if room.engine.state.pending and room.engine.state.pending.kind == "intervention":
                self.manager.apply_command(
                    room, command(room.engine, f"decline-{turn}", victim, "decline-intervention")
                )
            resolve_reveal_windows(self.manager, room, victim, f"reveal-{turn}")
            if room.engine.state.pending and room.engine.state.pending.kind == "skill":
                self.manager.apply_command(
                    room, command(room.engine, f"skill-{turn}", victim, "choose-skill", use=False)
                )
            if room.status == "ended":
                break
        steps = self.manager.replay(room)
        self.assertTrue(steps)
        self.assertIsNone(steps[-1]["viewer"])
        self.assertEqual(steps[-1]["status"], "ended")
        self.assertIsNotNone(steps[-1]["result"])
        # replay steps are spectator projections: no clue icon fields anywhere
        for step in steps:
            self.assertNotIn("clueIcon", json.dumps(step))
            self.assertNotIn("seenNeighbourClue", json.dumps(step))


if __name__ == "__main__":
    unittest.main()
