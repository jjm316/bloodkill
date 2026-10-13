import json
import tempfile
import unittest
from pathlib import Path
from tests.account_fixtures import account, account_for_player, cookie, store
from server.protocol import PROTOCOL_VERSION

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
        return self.manager.create_room(account(f"Host{len(self.manager.rooms)}"))

    def test_create_room_allocates_six_digit_code_and_persists(self):
        room = self.create_room()
        self.assertEqual(len(room.code), 6)
        self.assertTrue(room.code.isdigit())
        self.assertEqual(room.status, "waiting")
        self.assertTrue(room.host_account_id)
        self.assertTrue((self.manager.saves_dir / f"{room.game_id}.json.gz").exists())

    def test_join_then_resume_by_account(self):
        room = self.create_room()
        player_id, is_new = self.manager.join_or_resume(room, account("Alice"))
        self.assertTrue(is_new)
        self.assertEqual(room.player_id_for_account(account("Alice").account_id), player_id)
        resumed, is_new = self.manager.join_or_resume(room, account("Alice"))
        self.assertFalse(is_new)
        self.assertEqual(resumed, player_id)

    def test_occupied_account_cannot_join_a_second_unfinished_room(self):
        first = self.create_room()
        migrant = account("双房玩家")
        self.manager.join_or_resume(first, migrant)
        second = self.create_room()
        with self.assertRaises(RuleError) as error:
            self.manager.join_or_resume(second, migrant)
        self.assertEqual(error.exception.code, "account.room-occupied")
        self.assertIn("返回原房间", str(error.exception))
        self.assertEqual(error.exception.details["roomCode"], first.code)
        self.assertIsNone(second.player_id_for_account(migrant.account_id), "被拒后不能在目标房残留幽灵座位")
        self.assertEqual(len(second.engine.state.players), 1)
        # 本人恢复原房不算新占用，仍得到原座位。
        player_id, is_new = self.manager.join_or_resume(first, migrant)
        self.assertFalse(is_new)
        self.assertEqual(player_id, first.player_id_for_account(migrant.account_id))

    def test_exit_seat_releases_occupancy_and_next_join_is_a_new_player(self):
        # 工单 13：等待普通玩家主动退座——真释放，与断线保留座位区分。
        room = self.create_room()
        leaver = account("退座玩家")
        old_player_id, _ = self.manager.join_or_resume(room, leaver)
        events = self.manager.exit_seat(room, leaver)
        self.assertEqual([event.event_type for event in events], ["PlayerLeft"])
        self.assertIsNone(room.player_id_for_account(leaver.account_id), "退座后座位映射移除")
        self.assertNotIn(old_player_id, room.engine.state.players, "引擎玩家集合收缩")
        self.assertIsNone(self.manager.room_for_account(leaver.account_id), "占用释放")
        self.assertIn("PlayerLeft", [event.event_type for event in room.engine.state.events], "事件历史保留退座")
        # 重新加入生成新的玩家引用，且可加入别的房间。
        new_player_id, is_new = self.manager.join_or_resume(room, leaver)
        self.assertTrue(is_new)
        self.assertNotEqual(new_player_id, old_player_id)
        other = self.create_room()
        self.manager.exit_seat(room, leaver)
        self.manager.join_or_resume(other, leaver)
        self.assertIsNotNone(other.player_id_for_account(leaver.account_id), "释放后可加入别的房间")

    def test_exit_seat_rejects_host_playing_and_seatless_callers(self):
        host = account("退座房主")
        room = self.manager.create_room(host)
        with self.assertRaises(RuleError) as error:
            self.manager.exit_seat(room, host)
        self.assertEqual(error.exception.code, "room.host-seat-kept", "房主返回大厅不是退座")
        self.assertIn("房主", str(error.exception))
        self.assertIsNotNone(room.player_id_for_account(host.account_id), "房主座位保留")
        member = account("在局玩家")
        self.manager.join_or_resume(room, member)
        with self.assertRaises(RuleError) as error:
            self.manager.exit_seat(room, account("无座玩家"))
        self.assertEqual(error.exception.code, "seat.not-held")
        for index in range(4):
            self.manager.join_or_resume(room, account(f"补位{index}"))
        self.manager.start_game(room)
        with self.assertRaises(RuleError) as error:
            self.manager.exit_seat(room, member)
        self.assertEqual(error.exception.code, "room.in-progress", "对局中不能退座，仅断开连接")
        self.assertIsNotNone(room.player_id_for_account(member.account_id), "对局中座位保留")
        self.assertIsNotNone(self.manager.room_for_account(member.account_id), "对局中占用保留")

    def test_exit_seat_survives_restore_with_consistent_seat_map(self):
        room = self.create_room()
        leaver = account("重启退座")
        self.manager.join_or_resume(room, leaver)
        stayer = account("重启留座")
        self.manager.join_or_resume(room, stayer)
        self.manager.exit_seat(room, leaver)
        restored_manager = RoomManager(Path(self._tmp.name))
        restored_manager.restore()
        restored = restored_manager.get_room(room.code)
        self.assertIsNone(restored.player_id_for_account(leaver.account_id), "重启后不残留已退出账号")
        self.assertIsNotNone(restored.player_id_for_account(stayer.account_id), "留座账号不受影响")
        self.assertEqual(
            sorted(restored.seat_accounts.values()),
            sorted(restored.engine.state.players),
            "seat_accounts 与引擎玩家集合一致，无重复座位",
        )
        self.assertNotIn(leaver.account_id, {a for a in restored.seat_accounts})

    def test_concurrent_exit_and_start_race_ends_in_one_legal_state(self):
        # 工单 13 / V07.04：退座与开局竞争，最终只有一种合法状态。
        room = self.create_room()
        leaver = account("竞争退座")
        self.manager.join_or_resume(room, leaver)
        for index in range(4):
            self.manager.join_or_resume(room, account(f"竞争补位{index}"))
        self.assertEqual(len(room.engine.state.players), 6)
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)
        outcomes: dict[str, object] = {}

        def exit_attempt():
            barrier.wait(timeout=5)
            try:
                outcomes["exit"] = self.manager.exit_seat(room, leaver)
            except RuleError as error:
                outcomes["exit_error"] = error

        def start_attempt():
            barrier.wait(timeout=5)
            try:
                outcomes["start"] = self.manager.start_game(room)
            except RuleError as error:
                outcomes["start_error"] = error

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(exit_attempt)
            pool.submit(start_attempt)
        exited = "exit" in outcomes
        started = "start" in outcomes
        self.assertNotEqual(exited, started, "退座与开局竞争最终恰好一个成功，不允许都成或都败")
        if exited:
            # 退座先落：5 人开局被拒，账号已释放、不在局中。
            self.assertEqual(outcomes["start_error"].code, "game.player-count")
            self.assertEqual(room.status, "waiting")
            self.assertIsNone(self.manager.room_for_account(leaver.account_id))
        else:
            # 开局先落：退座被拒（已不是等待房），座位与占用保留。
            self.assertEqual(outcomes["exit_error"].code, "room.in-progress")
            self.assertEqual(room.status, "playing")
            self.assertIsNotNone(self.manager.room_for_account(leaver.account_id))

    def test_concurrent_create_attempts_allocate_one_room_per_account(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        owner = account("并发房主")
        barrier = Barrier(4)

        def attempt(_):
            barrier.wait(timeout=5)
            return self.manager.create_room(owner)

        with ThreadPoolExecutor(max_workers=4) as pool:
            rooms = list(pool.map(attempt, range(4)))
        self.assertEqual(len({room.code for room in rooms}), 1, "同账号并发建房必须收敛到同一房间")
        occupied = [room for room in self.manager.rooms.values()
                    if room.status != "ended" and owner.account_id in room.seat_accounts]
        self.assertEqual(len(occupied), 1, "并发竞争后账号最多占一个未结束房间")

    def test_concurrent_join_of_two_rooms_leaves_a_single_seat(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        first, second = self.create_room(), self.create_room()
        migrant = account("并发入座")
        barrier = Barrier(2)
        outcomes: dict[str, object] = {}

        def attempt(key, room):
            barrier.wait(timeout=5)
            try:
                outcomes[key] = self.manager.join_or_resume(room, migrant)
            except RuleError as error:
                outcomes[key + "_error"] = error

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(attempt, "first", first)
            pool.submit(attempt, "second", second)
        occupied = [room for room in self.manager.rooms.values()
                    if room.status != "ended" and migrant.account_id in room.seat_accounts]
        self.assertEqual(len(occupied), 1, "并发加入两房后最终只能有一个未结束占用")
        successes = [key for key in outcomes if not key.endswith("_error")]
        self.assertEqual(len(successes), 1, "必须恰好一个请求成功")
        for key, value in outcomes.items():
            if key.endswith("_error"):
                self.assertEqual(value.code, "account.room-occupied", key)
                self.assertEqual(value.details["roomCode"], occupied[0].code, "失败方得到原房引导")
        loser_room = second if occupied[0] is first else first
        self.assertIsNone(loser_room.player_id_for_account(migrant.account_id), "失败方不能留下幽灵座位")

    def test_concurrent_create_and_join_race_leaves_a_single_occupancy(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        other_room = self.create_room()
        migrant = account("并发混合")
        barrier = Barrier(2)
        outcomes: dict[str, object] = {}

        def create_attempt():
            barrier.wait(timeout=5)
            try:
                outcomes["create"] = self.manager.create_room(migrant)
            except RuleError as error:
                outcomes["create_error"] = error

        def join_attempt():
            barrier.wait(timeout=5)
            try:
                outcomes["join"] = self.manager.join_or_resume(other_room, migrant)
            except RuleError as error:
                outcomes["join_error"] = error

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(create_attempt)
            pool.submit(join_attempt)
        occupied = [room for room in self.manager.rooms.values()
                    if room.status != "ended" and migrant.account_id in room.seat_accounts]
        self.assertEqual(len(occupied), 1, "建房与加入混合竞争后仍只能占一个房间")
        for key, value in outcomes.items():
            if key.endswith("_error"):
                self.assertEqual(value.code, "account.room-occupied", key)
                self.assertEqual(value.details["roomCode"], occupied[0].code, "失败方得到原房引导")

    def test_created_host_seat_survives_restore(self):
        room = self.create_room()
        player_id = room.host_player_id
        self.assertIsNotNone(player_id)
        self.assertEqual(room.host_player_id, player_id)
        restored_manager = RoomManager(Path(self._tmp.name))
        restored_manager.restore()
        restored = restored_manager.get_room(room.code)
        self.assertEqual(restored.host_player_id, player_id)

    def test_join_after_start_is_rejected(self):
        room = self.create_room()
        for index in range(5):
            self.manager.join_or_resume(room, account(f"P{index}"))
        self.manager.start_game(room)
        self.assertEqual(room.status, "playing")
        with self.assertRaises(RuleError) as error:
            self.manager.join_or_resume(room, account("Latecomer"))
        self.assertEqual(error.exception.code, "room.already-started")

    def test_locked_room_rejects_new_players_but_lets_known_resume(self):
        room = self.create_room()
        self.manager.join_or_resume(room, account("Alice"))
        self.manager.set_locked(room, True)
        with self.assertRaises(RuleError) as error:
            self.manager.join_or_resume(room, account("Bob"))
        self.assertEqual(error.exception.code, "room.locked")
        player_id, is_new = self.manager.join_or_resume(room, account("Alice"))
        self.assertFalse(is_new)

    def test_start_requires_six_players(self):
        room = self.create_room()
        for index in range(4):
            self.manager.join_or_resume(room, account(f"P{index}"))
        with self.assertRaises(RuleError) as error:
            self.manager.start_game(room)
        self.assertEqual(error.exception.code, "game.player-count")

    def test_auto_save_updates_after_each_command_and_restore_recovers(self):
        room = self.create_room()
        for index in range(5):
            self.manager.join_or_resume(room, account(f"P{index}"))
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
        self.assertEqual(restored.host_account_id, room.host_account_id)

    def test_finished_games_are_retained_to_cap(self):
        # create, fill, and end more rooms than the cap
        for _ in range(FINISHED_GAMES_TO_KEEP + 3):
            room = self.create_room()
            for index in range(5):
                self.manager.join_or_resume(room, account(f"P{index}"))
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
                while room.engine.state.pending and room.engine.state.pending.kind == "intervention":
                    pending = room.engine.state.pending
                    stage = pending.context.get("stage")
                    if stage == "gate":
                        self.manager.apply_command(
                            room, command(room.engine, f"gate-{turn}-{room.engine.state.revision}", pending.actor_player_id, "answer-intervention-request", need=True)
                        )
                    elif stage == "poll":
                        responses = pending.context["responses"]
                        responder = next(pid for pid in pending.eligible_player_ids if pid not in responses)
                        self.manager.apply_command(
                            room, command(room.engine, f"respond-{turn}-{responder}", responder, "respond-intervention", volunteer=False)
                        )
                    else:
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
        for index in range(5):
            self.manager.join_or_resume(room, account(f"P{index}"))
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
            while room.engine.state.pending and room.engine.state.pending.kind == "intervention":
                pending = room.engine.state.pending
                stage = pending.context.get("stage")
                if stage == "gate":
                    self.manager.apply_command(
                        room, command(room.engine, f"gate-{turn}-{room.engine.state.revision}", pending.actor_player_id, "answer-intervention-request", need=True)
                    )
                elif stage == "poll":
                    responses = pending.context["responses"]
                    responder = next(pid for pid in pending.eligible_player_ids if pid not in responses)
                    self.manager.apply_command(
                        room, command(room.engine, f"respond-{turn}-{responder}", responder, "respond-intervention", volunteer=False)
                    )
                else:
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
