"""守门回归：真实失败退出、禁止假通过、实际暂存区与推送内容校验。"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import check


class CheckFailureTests(unittest.TestCase):
    def test_local_test_connections_bypass_proxy_without_discarding_existing_exclusions(self):
        command = [sys.executable, "-c", "import os; from urllib.request import proxy_bypass; assert proxy_bypass('127.0.0.1'); assert proxy_bypass('localhost'); assert 'example.invalid' in os.environ['NO_PROXY']"]
        with mock.patch.dict(os.environ, {"NO_PROXY": "example.invalid", "no_proxy": "example.invalid"}):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(check.run_steps([("本机网络隔离", command, check.ROOT)]), 0)

    def test_child_failure_is_returned_and_later_step_does_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "later-step"
            steps = [
                ("失败步骤", [sys.executable, "-c", "raise SystemExit(7)"], directory),
                ("后续步骤", [sys.executable, "-c", "from pathlib import Path; Path('later-step').touch()"], directory),
            ]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(check.run_steps(steps), 7)
            self.assertFalse(marker.exists())

    def test_unavailable_command_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(check.run_steps([("缺命令", [str(Path(directory) / "missing-command")], directory)]), 1)

    def test_python_suite_cannot_pass_with_missing_dependencies(self):
        with mock.patch.object(check.importlib.util, "find_spec", return_value=None):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(check.python_tests(), 1)

    def test_empty_skipped_and_failing_suites_are_rejected(self):
        passing = unittest.FunctionTestCase(lambda: None)
        skipped = unittest.FunctionTestCase(unittest.skip("验证跳过不能假通过")(lambda: None))
        failing = unittest.FunctionTestCase(lambda: self.fail("fixture failure"))
        for cases, expected in (([], 1), ([skipped], 1), ([failing], 1), ([passing], 0)):
            with self.subTest(expected=expected, cases=len(cases)):
                suite = unittest.TestSuite(cases)
                with mock.patch.object(check.importlib.util, "find_spec", return_value=object()), mock.patch.object(check.unittest.TestLoader, "discover", return_value=suite):
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(check.python_tests(), expected)


class GitGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Git hooks 会向子进程传入当前仓库的 Git 环境；测试仓库必须独立。
        self.git_environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment_patch = mock.patch.dict(os.environ, self.git_environment, clear=True)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        self.git("init", "--quiet")
        self.git("config", "user.name", "gate-test")
        self.git("config", "user.email", "gate-test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        (self.root / "file.txt").write_text("baseline\n", encoding="utf-8")
        self.git("add", "file.txt")
        self.git("-c", "core.hooksPath=disabled-test-hooks", "commit", "--quiet", "-m", "baseline")
        self.patch = mock.patch.object(check, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.root, text=True, env=self.git_environment).strip()

    def update(self, object_name=None):
        return [f"refs/heads/test {object_name or self.git('rev-parse', 'HEAD')} refs/heads/test {'0' * 40}\n"]

    def test_staged_whitespace_is_rejected_even_if_worktree_is_fixed(self):
        path = self.root / "file.txt"
        path.write_text("bad \n", encoding="utf-8")
        self.git("add", "file.txt")
        path.write_text("fixed\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(check.main(["staged"]), 0)

    def test_dirty_worktree_cannot_validate_a_push(self):
        (self.root / "file.txt").write_text("uncommitted\n", encoding="utf-8")
        with mock.patch.object(check, "all_checks") as full:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(check.pre_push(self.update()), 1)
            full.assert_not_called()

    def test_push_of_another_commit_cannot_validate_current_head(self):
        previous = self.git("rev-parse", "HEAD")
        self.git("-c", "core.hooksPath=disabled-test-hooks", "commit", "--allow-empty", "--quiet", "-m", "next")
        with mock.patch.object(check, "all_checks") as full:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(check.pre_push(self.update(previous)), 1)
            full.assert_not_called()

    def test_clean_head_runs_full_checks_and_preserves_failure(self):
        with mock.patch.object(check, "all_checks", return_value=7) as full:
            self.assertEqual(check.pre_push(self.update()), 7)
            full.assert_called_once_with()

    def test_delete_only_push_does_not_run_tests(self):
        with mock.patch.object(check, "all_checks") as full:
            self.assertEqual(check.pre_push(self.update("0" * 40)), 0)
            full.assert_not_called()

    def test_hook_installation_preserves_existing_configuration(self):
        self.git("config", "core.hooksPath", "custom-hooks")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(check.install_hooks(), 1)
        self.assertEqual(self.git("config", "core.hooksPath"), "custom-hooks")

    def test_new_branch_checks_its_changes_instead_of_historical_whitespace(self):
        (self.root / "history.txt").write_text("historical \n", encoding="utf-8", newline="\n")
        self.git("add", "history.txt")
        self.git("-c", "core.hooksPath=disabled-test-hooks", "commit", "--quiet", "-m", "old material")
        self.git("update-ref", "refs/remotes/origin/master", self.git("rev-parse", "HEAD"))
        (self.root / "file.txt").write_text("new content\n", encoding="utf-8", newline="\n")
        self.git("add", "file.txt")
        self.git("-c", "core.hooksPath=disabled-test-hooks", "commit", "--quiet", "-m", "new feature")
        run_steps = check.run_steps

        def whitespace_only(steps):
            return run_steps([step for step in steps if step[1][0] == "git"])

        with mock.patch.object(check, "run_steps", side_effect=whitespace_only), mock.patch.object(check.shutil, "which", return_value="npm"):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(check.all_checks("0" * 40, "master"), 0)
                (self.root / "file.txt").write_text("new content \n", encoding="utf-8", newline="\n")
                self.git("add", "file.txt")
                self.git("-c", "core.hooksPath=disabled-test-hooks", "commit", "--quiet", "-m", "bad whitespace")
                self.assertNotEqual(check.all_checks("0" * 40, "master"), 0)


if __name__ == "__main__":
    unittest.main()
