"""scripts/test_toolkit.py 的纯逻辑单测（不触网、不杀进程、不依赖 WMI）。"""

import os
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


class StaleServerWarningTest(unittest.TestCase):
    """陈旧服务端告警的纯判定逻辑（不查进程、不触网）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.app = self.root / "server" / "app.py"
        self.projection = self.root / "blood_bound" / "projection.py"
        self.compiled = self.root / "blood_bound" / "__pycache__" / "cached.py"
        for path in (self.app, self.projection, self.compiled):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        # 固定 mtime：app 旧、projection 新、__pycache__ 产物最新（应被忽略）
        os.utime(self.app, (1000, 1000))
        os.utime(self.projection, (1000, 2000))
        os.utime(self.compiled, (1000, 3000))
        self.roots = (self.root / "server", self.root / "blood_bound")

    def test_scan_newest_ignores_pycache(self):
        with mock.patch.object(test_toolkit, "SERVER_CODE_ROOTS", self.roots):
            self.assertEqual(test_toolkit.newest_server_code_mtime(), (2000.0, self.projection))

    def test_scan_missing_roots_returns_none(self):
        with mock.patch.object(test_toolkit, "SERVER_CODE_ROOTS", (self.root / "nope",)):
            self.assertIsNone(test_toolkit.newest_server_code_mtime())

    def test_warning_names_file_and_command(self):
        warning = test_toolkit.stale_server_warning((2000.0, self.projection), 1000.0, 8010)
        self.assertIn("projection.py", warning)
        self.assertIn(".venv/Scripts/python.exe", warning)
        self.assertIn("restart", warning)
        self.assertIn("8010", warning)

    def test_warning_shows_relative_path_under_repo_root(self):
        with mock.patch.object(test_toolkit, "REPO_ROOT", self.root):
            warning = test_toolkit.stale_server_warning((2000.0, self.projection), 1000.0, 8000)
        self.assertIn("blood_bound", warning)
        self.assertNotIn(str(self.root), warning)

    def test_silent_within_tolerance(self):
        self.assertIsNone(test_toolkit.stale_server_warning((1002.0, self.projection), 1000.0, 8000))

    def test_warns_beyond_tolerance(self):
        self.assertIsNotNone(test_toolkit.stale_server_warning((1003.0, self.projection), 1000.0, 8000))

    def test_silent_without_code_or_start_time(self):
        self.assertIsNone(test_toolkit.stale_server_warning(None, 1000.0, 8000))
        self.assertIsNone(test_toolkit.stale_server_warning((2000.0, self.projection), None, 8000))

    def test_report_swallows_diagnostics_failure(self):
        # fail-open：进程查询或 mtime 扫描抛错时不得打崩宿主子命令（spec：告警永不阻断）
        with mock.patch.object(
            test_toolkit, "process_start_time", side_effect=OSError("wmi down")
        ), mock.patch.object(
            test_toolkit, "newest_server_code_mtime", side_effect=OSError("stat race")
        ):
            test_toolkit.report_stale_server(8000, {123})


if __name__ == "__main__":
    unittest.main()
