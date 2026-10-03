import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "requires server/requirements.txt")
class WebSocketRecoveryTests(unittest.TestCase):
    def setUp(self):
        from server import app
        from server.rooms import RoomManager

        self.app = app
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.original_manager = app.manager
        self.original_conns = app.conns.copy()
        self.addCleanup(self._restore_globals)
        app.manager = RoomManager(Path(self._tmp.name))
        app.conns.clear()
        self.room = app.manager.create_room()
        self.player_ids = [app.manager.join_or_resume(self.room, f"P{index}")[0] for index in range(6)]
        app.manager.start_game(self.room)

    def _restore_globals(self):
        self.app.manager = self.original_manager
        self.app.conns.clear()
        self.app.conns.update(self.original_conns)

    def _connection(self, player_id):
        ws = FakeWebSocket()
        conn = self.app.Conn(ws=ws, room=self.room, player_id=player_id)
        self.app.conns[f"test-{player_id}"] = conn
        return conn, ws

    def test_lost_ack_retransmission_does_not_replay_events(self):
        actor = self.room.engine.state.dagger_holder_id
        target = next(player_id for player_id in self.player_ids if player_id != actor)
        conn, ws = self._connection(actor)
        observer, observer_ws = self._connection(target)
        raw = {
            "type": "command",
            "commandId": "recoverable-attack",
            "command": "attack",
            "payload": {"targetPlayerId": target},
            "expectedRevision": self.room.engine.state.revision,
        }

        asyncio.run(self.app._handle_command(conn, raw))
        revision = self.room.engine.state.revision
        self.assertTrue(any(message["type"] == "ack" and message["status"] == "accepted" for message in ws.sent))
        self.assertTrue(any(message["type"] == "event" for message in observer_ws.sent))

        ws.sent.clear()  # Simulate the accepted acknowledgement being lost in transit.
        observer_ws.sent.clear()
        asyncio.run(self.app._handle_command(conn, raw))

        self.assertEqual(self.room.engine.state.revision, revision)
        self.assertEqual(
            [message["type"] for message in observer_ws.sent if message["type"] == "event"],
            [],
        )
        self.assertTrue(any(message["type"] == "ack" and message["status"] == "accepted" for message in ws.sent))
        self.assertEqual(ws.sent[-1]["type"], "state")

    def test_stale_command_is_rejected_with_current_state(self):
        actor = self.room.engine.state.dagger_holder_id
        target = next(player_id for player_id in self.player_ids if player_id != actor)
        conn, ws = self._connection(actor)
        accepted = {
            "type": "command",
            "commandId": "advance-revision",
            "command": "attack",
            "payload": {"targetPlayerId": target},
            "expectedRevision": self.room.engine.state.revision,
        }
        asyncio.run(self.app._handle_command(conn, accepted))
        ws.sent.clear()

        asyncio.run(
            self.app._handle_command(
                conn,
                {
                    **accepted,
                    "commandId": "stale-command",
                    "expectedRevision": 0,
                },
            )
        )

        self.assertEqual(ws.sent[0]["type"], "error")
        self.assertEqual(ws.sent[0]["code"], "game.revision-conflict")
        self.assertEqual(ws.sent[1]["type"], "ack")
        self.assertEqual(ws.sent[1]["status"], "rejected")
        self.assertEqual(ws.sent[2]["type"], "state")
        self.assertEqual(ws.sent[2]["game"]["revision"], self.room.engine.state.revision)

    def test_host_reconnect_keeps_management_authority(self):
        first_ws = FakeWebSocket({"type": "hello", "name": "P0", "token": self.room.host_token})
        first = self.app.Conn(ws=first_ws, room=self.room)
        self.app.conns["host-first"] = first
        asyncio.run(self.app._handle_hello(first, first_ws))
        self.assertTrue(first.is_host)
        first_state_hash = json.dumps(first_ws.sent[-1]["game"], sort_keys=True)

        resumed_ws = FakeWebSocket({"type": "hello", "name": "P0", "token": self.room.host_token})
        resumed = self.app.Conn(ws=resumed_ws, room=self.room)
        self.app.conns["host-resumed"] = resumed
        asyncio.run(self.app._handle_hello(resumed, resumed_ws))

        self.assertTrue(resumed.is_host)
        self.assertEqual(resumed.player_id, first.player_id)
        self.assertTrue(any(message["type"] == "taken-over" for message in first_ws.sent))
        self.assertEqual(json.dumps(resumed_ws.sent[-1]["game"], sort_keys=True), first_state_hash)

    def test_host_hello_records_seat_for_every_viewer(self):
        room = self.app.manager.create_room()
        host_player = self.app.manager.join_or_resume(room, "Host")[0]
        host_ws = FakeWebSocket({"type": "hello", "name": "Host", "token": room.host_token})
        host_conn = self.app.Conn(ws=host_ws, room=room)
        self.app.conns["bind-host"] = host_conn
        asyncio.run(self.app._handle_hello(host_conn, host_ws))
        self.assertEqual(room.host_player_id, host_player)

        other_ws = FakeWebSocket({"type": "hello", "name": "Guest"})
        other_conn = self.app.Conn(ws=other_ws, room=room)
        self.app.conns["bind-other"] = other_conn
        asyncio.run(self.app._handle_hello(other_conn, other_ws))

        for ws in (host_ws, other_ws):
            state = ws.sent[-1]
            self.assertEqual(state["type"], "state")
            self.assertEqual(state["hostPlayerId"], host_player)

    def test_version_mismatch_is_rejected_before_a_seat_is_resumed(self):
        ws = FakeWebSocket({"type": "hello", "name": "P0", "protocolVersion": "obsolete"})
        conn = self.app.Conn(ws=ws, room=self.room)

        accepted = asyncio.run(self.app._handle_hello(conn, ws))

        self.assertFalse(accepted)
        self.assertEqual(ws.sent[0]["code"], "protocol.version-mismatch")


class DeadlineWindowTests(unittest.TestCase):
    """Server-owned countdown windows: room tracking, scheduler expiry, injection."""

    def setUp(self):
        from server import app
        from server.rooms import RoomManager

        self.app = app
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.original_manager = app.manager
        self.original_conns = app.conns.copy()
        self.addCleanup(self._restore_globals)
        app.manager = RoomManager(Path(self._tmp.name))
        app.conns.clear()
        self.room = app.manager.create_room()
        self.player_ids = [app.manager.join_or_resume(self.room, f"P{index}")[0] for index in range(6)]
        app.manager.start_game(self.room, intervention_timeout_seconds=30)

    def _restore_globals(self):
        self.app.manager = self.original_manager
        self.app.conns.clear()
        self.app.conns.update(self.original_conns)

    def _attack(self):
        from blood_bound import Command

        attacker = self.room.engine.state.dagger_holder_id
        target = next(pid for pid in self.player_ids if pid != attacker)
        self.app.manager.apply_command(
            self.room,
            Command("attack-deadline", self.room.game_id, attacker, self.room.engine.state.revision, "attack", {"targetPlayerId": target}),
        )
        return attacker, target

    def _respond(self, player_id, volunteer, command_id):
        from blood_bound import Command

        self.app.manager.apply_command(
            self.room,
            Command(command_id, self.room.game_id, player_id, self.room.engine.state.revision, "respond-intervention", {"volunteer": volunteer}),
        )

    def test_poll_window_is_tracked_persisted_and_cleared(self):
        import time as time_module

        _, target = self._attack()
        self.assertEqual(self.room.window_stage, "poll")
        self.assertIsNotNone(self.room.window_deadline)
        self.assertGreater(self.room.window_deadline, time_module.time())

        meta = json.loads((Path(self._tmp.name) / f"{self.room.game_id}.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["windowStage"], "poll")

        pending = self.room.engine.state.pending
        for player_id in pending.eligible_player_ids:
            self._respond(player_id, False, f"no-{player_id}")
        # The intervention window closed and, since issue 05, the victim's
        # reveal window takes over the tracked countdown instead of clearing it.
        self.assertIsNotNone(self.room.engine.state.pending)
        self.assertTrue(self.room.window_stage.startswith("reveal:"))
        self.assertIsNotNone(self.room.window_deadline)
        self.assertEqual(self.room.engine.state.players[target].damage, 1)

    def test_state_projection_carries_the_deadline(self):
        _, _target = self._attack()
        conn = self.app.Conn(ws=FakeWebSocket(), room=self.room, player_id=self.player_ids[0])
        state = self.app.build_state(conn)
        pending = state["game"]["pending"]
        self.assertEqual(pending["kind"], "intervention")
        self.assertEqual(pending["stage"], "poll")
        self.assertIsNotNone(pending["deadline"])

    def test_scheduler_expiry_resolves_a_silent_poll(self):
        import time as time_module

        _, target = self._attack()
        self.room.window_deadline = time_module.time() - 1.0

        async def run():
            await self.app.deadline_scheduler.sync(self.room)
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(self.room.engine.state.players[target].damage, 1)
        # The timed-out poll resolved and the victim's reveal window (issue 05)
        # is now the tracked, armed window.
        self.assertTrue(self.room.window_stage.startswith("reveal:"))
        self.assertIn("InterventionDeclined", [event.event_type for event in self.room.engine.state.events])

    def test_scheduler_expiry_auto_declines_the_choice_stage(self):
        import time as time_module

        _, target = self._attack()
        pending = self.room.engine.state.pending
        eligible = list(pending.eligible_player_ids)
        volunteers = eligible[:2]
        for player_id in eligible[2:]:
            self._respond(player_id, False, f"no-{player_id}")
        self._respond(volunteers[0], True, "yes-0")
        self.assertEqual(self.room.window_stage, "poll")
        self._respond(volunteers[1], True, "yes-1")
        self.assertEqual(self.room.window_stage, "choice")
        first_deadline = self.room.window_deadline
        self.room.window_deadline = time_module.time() - 1.0

        async def run():
            await self.app.deadline_scheduler.sync(self.room)
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(self.room.engine.state.players[target].damage, 1)
        for player_id in volunteers:
            self.assertEqual(self.room.engine.state.players[player_id].damage, 0)
        declined = [event for event in self.room.engine.state.events if event.event_type == "InterventionDeclined"]
        self.assertEqual(declined[-1].payload["reason"], "timeout-declined")
        self.assertLess(first_deadline, time_module.time() + 60)

    def test_expired_window_fires_immediately_after_restore(self):
        import time as time_module

        _, target = self._attack()
        # simulate a deadline that expired while the server was down
        meta_path = Path(self._tmp.name) / f"{self.room.game_id}.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["windowDeadline"] = time_module.time() - 5.0
        meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")

        from server.rooms import RoomManager

        restored_manager = RoomManager(Path(self._tmp.name))
        restored_manager.restore()
        restored = restored_manager.get_room(self.room.code)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.window_stage, "poll")
        self.assertLess(restored.window_deadline, time_module.time())

        # the startup hook arms restored rooms; an already-expired window fires
        # with delay 0 through the normal command pipeline and resolves the poll
        self.app.manager = restored_manager

        async def run():
            await self.app.deadline_scheduler.sync(restored)
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(restored.engine.state.players[target].damage, 1)
        self.assertIn("InterventionDeclined", [event.event_type for event in restored.engine.state.events])


class SingleWindowDeadlineTests(unittest.TestCase):
    """Server-owned countdowns for the reveal / skill / token-return windows (issue 05)."""

    def setUp(self):
        from server import app
        from server.rooms import RoomManager

        self.app = app
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.original_manager = app.manager
        self.original_conns = app.conns.copy()
        self.addCleanup(self._restore_globals)
        app.manager = RoomManager(Path(self._tmp.name))
        app.conns.clear()
        self.room = app.manager.create_room()
        self.player_ids = [app.manager.join_or_resume(self.room, f"P{index}")[0] for index in range(6)]
        app.manager.start_game(self.room, single_window_timeout_seconds=60)

    def _restore_globals(self):
        self.app.manager = self.original_manager
        self.app.conns.clear()
        self.app.conns.update(self.original_conns)

    def _wound(self, victim_id, command_id="attack"):
        """Attack a victim and decline the poll, leaving the reveal window open."""
        from blood_bound import Command

        holder = self.room.engine.state.dagger_holder_id
        if holder == victim_id:
            other = next(pid for pid in self.player_ids if pid != victim_id)
            self.app.manager.apply_command(
                self.room,
                Command(f"pass-{command_id}", self.room.game_id, holder, self.room.engine.state.revision, "pass-dagger", {"targetPlayerId": other}),
            )
        attacker = self.room.engine.state.dagger_holder_id
        self.app.manager.apply_command(
            self.room,
            Command(command_id, self.room.game_id, attacker, self.room.engine.state.revision, "attack", {"targetPlayerId": victim_id}),
        )
        pending = self.room.engine.state.pending
        for player_id in list(pending.eligible_player_ids):
            pending = self.room.engine.state.pending
            self.app.manager.apply_command(
                self.room,
                Command(f"no-{command_id}-{player_id}", self.room.game_id, player_id, self.room.engine.state.revision, "respond-intervention", {"volunteer": False}),
            )

    def test_reveal_window_is_tracked_and_re_arms_per_window(self):
        import time as time_module

        victim = next(pid for pid in self.player_ids if pid != self.room.engine.state.dagger_holder_id)
        self._wound(victim)
        self.assertEqual(self.room.engine.state.pending.kind, "reveal")
        self.assertTrue(self.room.window_stage.startswith(f"reveal:{victim}:"))
        first_deadline = self.room.window_deadline
        self.assertIsNotNone(first_deadline)
        self.assertGreater(first_deadline, time_module.time())

        # the victim answers the first window; the next wound re-opens a
        # different reveal window (fewer eligible tokens) which must re-arm
        from blood_bound import Command

        self.app.manager.apply_command(
            self.room,
            Command("reveal-m0", self.room.game_id, victim, self.room.engine.state.revision, "choose-reveal", {"token": "marker-0"}),
        )
        self._wound(victim, "attack-2")
        self.assertTrue(self.room.window_stage.startswith(f"reveal:{victim}:"))
        self.assertGreater(self.room.window_deadline, first_deadline)

    def test_state_projection_carries_the_single_window_deadline(self):
        victim = next(pid for pid in self.player_ids if pid != self.room.engine.state.dagger_holder_id)
        self._wound(victim)
        conn = self.app.Conn(ws=FakeWebSocket(), room=self.room, player_id=victim)
        state = self.app.build_state(conn)
        pending = state["game"]["pending"]
        self.assertEqual(pending["kind"], "reveal")
        self.assertIsNotNone(pending["deadline"])
        self.assertEqual(state["game"]["singleWindowTimeoutSeconds"], 60)

    def test_scheduler_expiry_auto_reveals_the_deterministic_first_token(self):
        import time as time_module

        victim = next(pid for pid in self.player_ids if pid != self.room.engine.state.dagger_holder_id)
        self._wound(victim)
        self.room.window_deadline = time_module.time() - 1.0

        async def run():
            await self.app.deadline_scheduler.sync(self.room)
            await asyncio.sleep(0.05)

        asyncio.run(run())
        player = self.room.engine.state.players[victim]
        self.assertEqual(player.damage, 1)
        self.assertEqual(sorted(player.revealed), ["marker-0"])
        revealed = [event for event in self.room.engine.state.events if event.event_type == "ClueRevealed"]
        self.assertEqual(revealed[-1].payload["reason"], "timeout")
        self.assertIsNone(self.room.engine.state.pending)
        self.assertIsNone(self.room.window_stage)

    def test_scheduler_expiry_auto_declines_the_skill_window(self):
        import time as time_module

        from blood_bound import Command

        # any non-alchemist rank opens its skill window on an attack wound
        victim = next(
            player.player_id
            for player in self.room.engine.state.players.values()
            if player.player_id != self.room.engine.state.dagger_holder_id and player.rank != 4
        )
        self._wound(victim)
        self.app.manager.apply_command(
            self.room,
            Command("reveal-rank", self.room.game_id, victim, self.room.engine.state.revision, "choose-reveal", {"token": "rank"}),
        )
        if self.room.engine.state.pending is None or self.room.engine.state.pending.kind != "skill":
            self.fail("a non-alchemist victim rank always opens its skill window on an attack wound")
        self.assertTrue(self.room.window_stage.startswith(f"skill:{victim}"))
        self.room.window_deadline = time_module.time() - 1.0

        async def run():
            await self.app.deadline_scheduler.sync(self.room)
            await asyncio.sleep(0.05)

        asyncio.run(run())
        declined = [event for event in self.room.engine.state.events if event.event_type == "SkillDeclined"]
        self.assertEqual(declined[-1].payload["reason"], "timeout")
        self.assertIn(str(self.room.engine.state.players[victim].rank), self.room.engine.state.players[victim].skills_used)
        self.assertIsNone(self.room.engine.state.pending)

    def test_scheduler_expiry_auto_returns_the_first_token(self):
        """The token-return window: alchemist heal opens it, expiry returns marker-0."""
        import time as time_module

        from blood_bound import Command as BCommand, RulesEngine
        from server.rooms import Room

        # probe seeds until the deal includes an alchemist (rank 4)
        engine = None
        for probe in range(200):
            candidate = RulesEngine.new_game(f"tok-game-{probe}", f"tok-seed-{probe}")
            for index in range(6):
                candidate.apply(BCommand(f"join-{index}", candidate.state.game_id, None, candidate.state.revision, "join-game", {"playerId": f"p{index}", "displayName": f"P{index}"}))
            candidate.apply(BCommand("start", candidate.state.game_id, None, candidate.state.revision, "start-game", {}))
            if any(player.rank == 4 for player in candidate.state.players.values()):
                engine = candidate
                break
        self.assertIsNotNone(engine)
        room = Room(code="222222", game_id=engine.state.game_id, host_token="t", locked=False, status="waiting", engine=engine, created_at=0.0)
        self.app.manager.rooms[room.code] = room

        def send(command_id, actor, command_type, **payload):
            self.app.manager.apply_command(room, BCommand(command_id, room.game_id, actor, room.engine.state.revision, command_type, payload))

        def decline_poll(prefix):
            while room.engine.state.pending and room.engine.state.pending.kind == "intervention" and room.engine.state.pending.context.get("stage") == "poll":
                pending = room.engine.state.pending
                responder = next(pid for pid in pending.eligible_player_ids if pid not in pending.context["responses"])
                send(f"{prefix}-{room.engine.state.revision}", responder, "respond-intervention", volunteer=False)

        alchemist = next(player.player_id for player in engine.state.players.values() if player.rank == 4)
        attacker = room.engine.state.dagger_holder_id
        if attacker == alchemist:
            # keep the alchemist poll-eligible: hand the dagger to someone else first
            attacker = next(pid for pid in engine.state.players if pid != alchemist)
            send("pass-a", room.engine.state.dagger_holder_id, "pass-dagger", targetPlayerId=attacker)
        victim = next(pid for pid in engine.state.players if pid not in (attacker, alchemist))

        def attack_victim(prefix):
            if room.engine.state.dagger_holder_id != attacker:
                send(f"pass-{prefix}", room.engine.state.dagger_holder_id, "pass-dagger", targetPlayerId=attacker)
            send(f"attack-{prefix}", attacker, "attack", targetPlayerId=victim)
            decline_poll(prefix)

        # wound 1: marker-0 revealed; wound 2: rank revealed (decline any skill window)
        attack_victim("one")
        send("reveal-m0", victim, "choose-reveal", token="marker-0")
        attack_victim("two")
        send("reveal-rank", victim, "choose-reveal", token="rank")
        if room.engine.state.pending and room.engine.state.pending.kind == "skill":
            send("no-skill", victim, "choose-skill", use=False)
        # wound 3: the alchemist alone volunteers, gets wounded, and heals the victim
        if room.engine.state.dagger_holder_id != attacker:
            send("pass-three", room.engine.state.dagger_holder_id, "pass-dagger", targetPlayerId=attacker)
        send("attack-three", attacker, "attack", targetPlayerId=victim)
        while room.engine.state.pending and room.engine.state.pending.kind == "intervention" and room.engine.state.pending.context.get("stage") == "poll":
            pending = room.engine.state.pending
            responder = next(pid for pid in pending.eligible_player_ids if pid not in pending.context["responses"])
            send(f"yes-{room.engine.state.revision}", responder, "respond-intervention", volunteer=responder == alchemist)
        self.assertEqual(room.engine.state.pending.kind, "skill")
        send("heal", alchemist, "choose-skill", use=True, mode="heal")
        self.assertEqual(room.engine.state.pending.kind, "token-return")
        self.assertTrue(room.window_stage.startswith(f"token-return:{victim}:"))
        room.window_deadline = time_module.time() - 1.0

        async def run():
            await self.app.deadline_scheduler.sync(room)
            await asyncio.sleep(0.05)

        asyncio.run(run())
        player = room.engine.state.players[victim]
        self.assertEqual(player.damage, 1)
        self.assertEqual(player.revealed, {"rank"})
        returned = [event for event in room.engine.state.events if event.event_type == "TokenReturned"]
        self.assertEqual(returned[-1].payload["token"], "marker-0")
        self.assertEqual(returned[-1].payload["reason"], "timeout")
        self.assertIsNone(room.engine.state.pending)
        self.assertIsNone(room.window_stage)


class FakeWebSocket:
    def __init__(self, inbound=None):
        self.inbound = inbound
        self.sent = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        if self.inbound is None:
            raise RuntimeError("no inbound message")
        return self.inbound

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True


@unittest.skipUnless(FASTAPI_AVAILABLE, "requires server/requirements.txt")
class WsHandshakeTests(unittest.TestCase):
    def setUp(self):
        from server import app
        from server.rooms import RoomManager

        self.app = app
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.original_manager = app.manager
        self.original_conns = app.conns.copy()
        self.addCleanup(self._restore_globals)
        app.manager = RoomManager(Path(self._tmp.name))
        app.conns.clear()

    def _restore_globals(self):
        self.app.manager = self.original_manager
        self.app.conns.clear()
        self.app.conns.update(self.original_conns)

    def test_unknown_room_gets_error_frame_then_clean_close(self):
        # 回归：错误帧的房间号曾以 code= 关键字传入 error_message，与首参同名
        # 冲突抛 TypeError，客户端只能看到连接异常而非 room.not-found。
        ws = FakeWebSocket()

        asyncio.run(self.app.ws_endpoint(ws, "000000"))

        self.assertTrue(ws.accepted)
        self.assertEqual(len(ws.sent), 1)
        error = ws.sent[0]
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "room.not-found")
        self.assertEqual(error["details"], {"roomCode": "000000"})
        self.assertTrue(ws.closed)


if __name__ == "__main__":
    unittest.main()
