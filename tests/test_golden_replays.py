"""Golden full-game replay fixtures for 6--12 players.

Each fixture is the portable save document (`create_save_document`) of a
complete `run_deterministic_game`, stored under `tests/fixtures/`. The tests
verify both directions:

- every fixture loads through the full save pipeline (hash chain, snapshot
  checksum, command replay) and reaches the recorded terminal result;
- the current engine still reproduces each fixture byte-for-byte, so any rule
  change that alters a golden run fails loudly instead of drifting silently.

Regenerate after a deliberate ruleset change:

    python -m tests.test_golden_replays
"""

import json
from pathlib import Path
import unittest

from blood_bound import create_save_document, load_game_bytes, run_deterministic_game

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def golden_parameters(count: int) -> dict[str, str]:
    return {"game_id": f"golden-{count}", "seed": f"golden-seed-{count}"}


def regenerate_fixtures() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for count in range(6, 13):
        engine, _ = run_deterministic_game(count, **golden_parameters(count))
        document = create_save_document(engine)
        path = FIXTURE_DIR / f"golden-{count}.json"
        path.write_text(json.dumps(document, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"wrote {path} (revision {engine.state.revision})")


class GoldenReplayTests(unittest.TestCase):
    def fixture(self, count: int) -> dict:
        path = FIXTURE_DIR / f"golden-{count}.json"
        self.assertTrue(path.exists(), f"missing golden fixture {path}; regenerate with python -m tests.test_golden_replays")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_every_player_count_has_a_fixture_that_loads_and_ends(self):
        for count in range(6, 13):
            with self.subTest(count=count):
                document = self.fixture(count)
                self.assertEqual(document["game"]["gameId"], f"golden-{count}")
                self.assertEqual(document["game"]["seed"], f"golden-seed-{count}")
                engine = load_game_bytes(
                    json.dumps(document, ensure_ascii=True, sort_keys=True).encode("utf-8")
                )
                self.assertEqual(len(engine.state.players), count)
                self.assertEqual(engine.state.status, "ended")
                self.assertIsNotNone(engine.state.result)
                self.assertTrue(engine.state.result["ranking"])

    def test_current_engine_reproduces_every_golden_fixture(self):
        for count in range(6, 13):
            with self.subTest(count=count):
                fixture = self.fixture(count)
                engine, _ = run_deterministic_game(count, **golden_parameters(count))
                regenerated = create_save_document(engine)
                self.assertEqual(regenerated, fixture)


class GoldenBranchCoverageTests(unittest.TestCase):
    """The rule-coupling batch (issue 07) deliberately routes the deterministic
    runner through the new branches so every golden regeneration replays them.
    These checks fail loudly if a future runner change quietly drops one, so
    the dedicated unit tests never become the only witnesses."""

    def fixtures(self):
        for count in range(6, 13):
            yield count, json.loads((FIXTURE_DIR / f"golden-{count}.json").read_text(encoding="utf-8"))

    @staticmethod
    def payloads(document, event_type):
        return [record["event"]["payload"] for record in document["events"] if record["event"]["eventType"] == event_type]

    @staticmethod
    def commands(document, command_type):
        return [record for record in document["commands"] if record["type"] == command_type]

    @classmethod
    def skill_use_commands(cls, document, rank):
        """The choose-skill use commands whose owner used the given rank."""
        used = {payload["playerId"]: payload["rank"] for payload in cls.payloads(document, "SkillUsed")}
        return [
            record for record in cls.commands(document, "choose-skill")
            if record["payload"].get("use") and used.get(record["actorPlayerId"]) == rank
        ]

    def test_every_golden_accepts_a_gate_and_relays_it_into_a_poll(self):
        # ADR 0012: every fixture must keep the accept path — the attacked
        # target asking for the volunteer poll — so the poll branch coverage
        # the older fixtures carried never shrinks away.
        for count, document in self.fixtures():
            accepted = [
                record for record in self.commands(document, "answer-intervention-request")
                if record["payload"].get("need") is True
            ]
            self.assertTrue(accepted, f"golden-{count}: the walker must accept at least one request gate")
            self.assertTrue(
                self.payloads(document, "InterventionGateAccepted"),
                f"golden-{count}: an accepted gate must leave an InterventionGateAccepted event",
            )
            opened = self.payloads(document, "InterventionGateOpened")
            declined = self.payloads(document, "InterventionGateDeclined")
            self.assertEqual(
                len(opened), len(self.payloads(document, "InterventionGateAccepted")) + len(declined),
                f"golden-{count}: every opened gate must resolve through exactly one accept or decline",
            )
            self.assertTrue(
                self.payloads(document, "InterventionResponded"),
                f"golden-{count}: the relayed poll must actually gather responder answers",
            )
            # The accept relay: every GateAccepted is immediately followed by
            # the InterventionPollOpened of the same command.
            sequence = [record["event"]["eventType"] for record in document["events"]]
            for index, event_type in enumerate(sequence):
                if event_type != "InterventionGateAccepted":
                    continue
                self.assertEqual(
                    sequence[index + 1 : index + 2],
                    ["InterventionPollOpened"],
                    f"golden-{count}: a gate accept must relay straight into the poll",
                )

    def test_every_golden_mixes_a_target_declined_gate(self):
        # ADR 0012: the walker also declines a gate (need=false), and the
        # declined attack must settle on the target without ever polling.
        for count, document in self.fixtures():
            declined_answers = [
                record for record in self.commands(document, "answer-intervention-request")
                if record["payload"].get("need") is False
            ]
            self.assertTrue(declined_answers, f"golden-{count}: the walker must decline at least one request gate")
            declined_events = [
                payload for payload in self.payloads(document, "InterventionGateDeclined")
                if payload.get("reason") == "target-declined"
            ]
            self.assertTrue(
                declined_events,
                f"golden-{count}: a need=false answer must leave a target-declined InterventionGateDeclined",
            )
            sequence = [record["event"]["eventType"] for record in document["events"]]
            for index, event_type in enumerate(sequence):
                if event_type != "InterventionGateDeclined":
                    continue
                until_next_gate = sequence[index + 1 :]
                if "InterventionGateOpened" in until_next_gate:
                    until_next_gate = until_next_gate[: until_next_gate.index("InterventionGateOpened")]
                self.assertNotIn(
                    "InterventionPollOpened",
                    until_next_gate,
                    f"golden-{count}: a declined gate must settle without opening the poll",
                )
                self.assertNotIn(
                    "InterventionResponded",
                    until_next_gate,
                    f"golden-{count}: a declined gate must not gather responder answers",
                )

    def test_some_golden_uses_the_assassin_skill_and_its_victim_answers_reveal_windows(self):
        # ADR 0006: the rank-2 skill's two wounds open victim-choice reveal
        # windows on a player other than the attack victim.
        for count, document in self.fixtures():
            use_commands = self.skill_use_commands(document, 2)
            if not use_commands:
                continue
            target_id = use_commands[0]["payload"]["targetPlayerId"]
            target = document["snapshot"]["players"][target_id]
            self.assertEqual(target["damage"], 2, f"golden-{count}: the assassin's target should carry exactly the two skill wounds")
            self.assertEqual(
                [token for token in target["revealed"] if token.startswith("marker-")],
                ["marker-0", "marker-1"],
                f"golden-{count}: the wounds must have been revealed through the victim's own choices",
            )
            self.assertTrue(any(c["actorPlayerId"] == target_id for c in self.commands(document, "choose-reveal")))
            return
        self.fail("no golden fixture exercises the assassin's skill damage")

    def test_some_golden_seals_a_rank_through_the_mentalist_skill(self):
        # ADR 0009 plan A: the rank-5 skill force-reveals its target's rank and
        # writes it into skills_used — sealed, so the reveal opens no window.
        for count, document in self.fixtures():
            use_commands = self.skill_use_commands(document, 5)
            if not use_commands:
                continue
            target_id = use_commands[0]["payload"]["targetPlayerId"]
            target = document["snapshot"]["players"][target_id]
            self.assertIn("rank", target["revealed"], f"golden-{count}: the mentalist must have force-revealed the rank")
            self.assertIn(str(target["rank"]), target["skillsUsed"], f"golden-{count}: the forced rank must be sealed into skills_used")
            self.assertFalse(
                any(p["playerId"] == target_id for p in self.payloads(document, "SkillWindowOpened")),
                f"golden-{count}: a sealed rank must never open a skill window",
            )
            return
        self.fail("no golden fixture exercises the mentalist's seal")

    def test_every_golden_carries_a_timeout_reveal_and_one_a_timeout_skill(self):
        # ADR 0011: the scheduler's timeout commands are ordinary public
        # commands, so they replay deterministically through the save pipeline.
        skill_timeout_counts = 0
        for count, document in self.fixtures():
            self.assertTrue(self.commands(document, "timeout-reveal"), f"golden-{count}: the first reveal window must resolve through the timeout command")
            self.assertTrue(
                any(p.get("reason") == "timeout" for p in self.payloads(document, "ClueRevealed")),
                f"golden-{count}: the timed-out reveal must be audited with its reason",
            )
            declined = [p for p in self.payloads(document, "SkillDeclined") if p.get("reason") == "timeout"]
            if self.commands(document, "timeout-skill"):
                self.assertTrue(declined, f"golden-{count}: a timed-out skill window must leave a reasoned SkillDeclined")
                skill_timeout_counts += 1
        self.assertTrue(skill_timeout_counts, "no golden fixture exercises the skill-window timeout")

    def test_some_golden_reveals_a_wild_marker_as_the_question_mark(self):
        # Issue 26: the inquisitor's wild markers can be revealed as the
        # question mark, both by choice and through the timeout default — both
        # reveals must belong to the wild holder, not to any plain "?" marker.
        for count, document in self.fixtures():
            wild_holders = {
                player_id for player_id, player in document["snapshot"]["players"].items()
                if "wild" in player["identityMarkers"]
            }
            chosen = [
                record for record in self.commands(document, "choose-reveal")
                if record["payload"].get("color") == "unknown" and record["actorPlayerId"] in wild_holders
            ]
            timed_out = [
                payload for payload in self.payloads(document, "ClueRevealed")
                if payload.get("reason") == "timeout" and payload["value"] == "unknown" and payload["playerId"] in wild_holders
            ]
            if not chosen or not timed_out:
                continue
            self.assertTrue(
                any(p["kind"].startswith("marker-") for p in timed_out),
                f"golden-{count}: the wild default should time out on a marker token",
            )
            return
        self.fail("no golden fixture reveals a wild marker as the question mark both by choice and by timeout")


if __name__ == "__main__":
    regenerate_fixtures()
