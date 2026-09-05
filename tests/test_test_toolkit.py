"""scripts/test_toolkit.py 的纯逻辑单测（不触网、不杀进程、不依赖 WMI）。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import test_toolkit


class BuildParserTest(unittest.TestCase):
    def test_up_defaults(self):
        args = test_toolkit.build_parser().parse_args(["up"])
        self.assertEqual(args.players, 7)  # e19d8a1: 奇数局默认，含审判者
        self.assertEqual(args.port, 8000)
        self.assertIsNone(args.cols)
        self.assertFalse(args.no_build)
        self.assertEqual(args.func, test_toolkit.cmd_up)

    def test_up_full_flags(self):
        args = test_toolkit.build_parser().parse_args(
            ["up", "--players", "7", "--port", "9000", "--cols", "4", "--no-build"]
        )
        self.assertEqual((args.players, args.port, args.cols), (7, 9000, 4))
        self.assertTrue(args.no_build)

    def test_down_clear_saves_flag(self):
        args = test_toolkit.build_parser().parse_args(["down", "--clear-saves", "--port", "9000"])
        self.assertTrue(args.clear_saves)
        self.assertEqual(args.port, 9000)
        self.assertEqual(args.func, test_toolkit.cmd_down)

    def test_every_subcommand_wired(self):
        parser = test_toolkit.build_parser()
        for name, func in (
            ("up", test_toolkit.cmd_up),
            ("serve", test_toolkit.cmd_serve),
            ("restart", test_toolkit.cmd_restart),
            ("down", test_toolkit.cmd_down),
            ("build", test_toolkit.cmd_build),
            ("status", test_toolkit.cmd_status),
            ("close", test_toolkit.cmd_close),
        ):
            with self.subTest(command=name):
                args = parser.parse_args([name])
                self.assertEqual(args.func, func)

    def test_bare_invocation_wraps_to_up(self):
        self.assertEqual(test_toolkit.normalize_argv([]), ["up"])
        self.assertEqual(test_toolkit.normalize_argv(["--players", "7"]), ["up", "--players", "7"])

    def test_normalize_argv_keeps_subcommand(self):
        self.assertEqual(test_toolkit.normalize_argv(["down", "--clear-saves"]), ["down", "--clear-saves"])


class SavesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.saves = Path(self._tmp.name)
        for name in ("g-a.json.gz", "g-a.meta.json", "g-b.json.gz", "unrelated.txt"):
            (self.saves / name).write_bytes(b"")

    def test_count_saved_rooms(self):
        with mock.patch.object(test_toolkit, "SAVES_DIR", self.saves):
            self.assertEqual(test_toolkit.count_saved_rooms(), 2)

    def test_clear_saves_keeps_unrelated_files(self):
        with mock.patch.object(test_toolkit, "SAVES_DIR", self.saves):
            self.assertEqual(test_toolkit.clear_saves(), 3)
        remaining = sorted(path.name for path in self.saves.iterdir())
        self.assertEqual(remaining, ["unrelated.txt"])

    def test_missing_dir_is_zero(self):
        with mock.patch.object(test_toolkit, "SAVES_DIR", self.saves / "nope"):
            self.assertEqual(test_toolkit.count_saved_rooms(), 0)
            self.assertEqual(test_toolkit.clear_saves(), 0)


class GridPositionsTest(unittest.TestCase):
    def test_row_major_layout(self):
        positions = test_toolkit.grid_positions(6, cols=3, cell_w=100, cell_h=50)
        self.assertEqual(
            positions,
            [(0, 0), (100, 0), (200, 0), (0, 50), (100, 50), (200, 50)],
        )


if __name__ == "__main__":
    unittest.main()
