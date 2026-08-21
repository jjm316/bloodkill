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


if __name__ == "__main__":
    regenerate_fixtures()
