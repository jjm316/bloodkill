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


class FakeWebSocket:
    def __init__(self, inbound=None):
        self.inbound = inbound
        self.sent = []
        self.closed = False

    async def receive_json(self):
        if self.inbound is None:
            raise RuntimeError("no inbound message")
        return self.inbound

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
