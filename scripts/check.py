"""本地与 CI 共用的确定性检查；任一失败都阻断后续步骤。"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def run_steps(steps) -> int:
    environment = {**os.environ, "PYTHONUTF8": "1"}
    # 本地测试服务直连回环地址，保留开发者已有的其他代理排除项。
    bypass = ",".join(filter(None, [environment.get("no_proxy"), environment.get("NO_PROXY"), "127.0.0.1,localhost,::1"]))
    environment.update(NO_PROXY=bypass, no_proxy=bypass)
    for label, command, directory in steps:
        print(f"\n检查：{label}", flush=True)
        try:
            result = subprocess.run(command, cwd=directory, check=False, env=environment)
        except OSError as error:
            print(f"检查失败：{label}：{error}", file=sys.stderr)
            return 1
        if result.returncode:
            print(f"检查失败：{label}（退出码 {result.returncode}）", file=sys.stderr)
            return result.returncode if result.returncode > 0 else 1
    return 0


def git_output(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8",
    ).strip()


def python_executable() -> str:
    local = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(local) if local.is_file() else sys.executable


def python_tests(start_dir: Path = ROOT / "tests") -> int:
    missing = [name for name in ("fastapi", "uvicorn", "websockets") if importlib.util.find_spec(name) is None]
    if missing:
        print("检查失败：缺少测试依赖 " + "、".join(missing) + "；请运行 python -m pip install -r requirements-dev.txt。", file=sys.stderr)
        return 1
    # discover 和测试导入均以仓库根目录为基准，不依赖调用方当前目录。
    sys.path.insert(0, str(ROOT))
    suite = unittest.TestLoader().discover(str(start_dir))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.testsRun or result.skipped:
        print(f"检查失败：执行 {result.testsRun} 项，跳过 {len(result.skipped)} 项；完整验证要求测试实际执行。", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def all_checks(base: str | None = None, default_branch: str | None = None) -> int:
    npm = shutil.which("npm")
    if not npm:
        print("检查失败：找不到 npm，请安装 Node.js 并运行 npm ci --prefix client。", file=sys.stderr)
        return 1
    whitespace = [("工作区差异空白", ["git", "diff", "--check"], ROOT),
                  ("暂存区差异空白", ["git", "diff", "--cached", "--check"], ROOT)]
    if base:
        if set(base) == {"0"}:
            # 新分支不重查历史文档/临时素材的格式，仅检查分支新增差异。
            reference = f"refs/remotes/origin/{default_branch}" if default_branch else git_output("symbolic-ref", "refs/remotes/origin/HEAD")
            base = git_output("merge-base", "HEAD", reference)
        whitespace.append(("提交范围差异空白", ["git", "diff", "--check", base, "HEAD"], ROOT))
    whitespace.append(("当前提交差异空白", ["git", "diff-tree", "--root", "-m", "--check", "HEAD"], ROOT))
    return run_steps([
        *whitespace,
        ("Python 全部测试（禁止跳过）", [python_executable(), str(Path(__file__).resolve()), "python-tests"], ROOT),
        ("前端全部测试", [npm, "test"], ROOT / "client"),
        # build 已运行 tsc，完整验证不重复类型检查。
        ("TypeScript 类型检查与生产构建", [npm, "run", "build"], ROOT / "client"),
    ])


def pre_push(lines) -> int:
    updates = []
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            print("检查失败：推送引用信息格式无效。", file=sys.stderr)
            return 1
        if set(fields[1]) != {"0"}:
            updates.append(fields)
    if not updates:
        return 0  # 仅删除远端引用，没有代码需要验证。
    head = git_output("rev-parse", "HEAD")
    for local_ref, local_object, _, _ in updates:
        if git_output("rev-parse", f"{local_object}^{{commit}}") != head:
            print(f"检查失败：{local_ref} 不指向当前 HEAD，请检出该提交后再推送，以验证实际推送内容。", file=sys.stderr)
            return 1
    if git_output("status", "--porcelain", "--untracked-files=normal"):
        print("检查失败：推送前请提交修改，或用 Git stash 保留工作区修改；完整检查必须对应当前提交。", file=sys.stderr)
        return 1
    return all_checks()


def install_hooks() -> int:
    configured = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"], cwd=ROOT, capture_output=True, text=True)
    effective = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=ROOT, capture_output=True, text=True)
    if effective.returncode not in (0, 1) or configured.returncode not in (0, 1):
        print("安装失败：无法读取 Git hooks 配置。", file=sys.stderr)
        return 1
    if effective.returncode == 0 and effective.stdout.strip() != ".githooks":
        print("安装失败：已有 core.hooksPath，请先整合现有 hooks，避免覆盖。", file=sys.stderr)
        return 1
    if effective.returncode == 1:
        old = ROOT / git_output("rev-parse", "--git-path", "hooks")
        if any((old / name).is_file() for name in ("pre-commit", "pre-push")):
            print("安装失败：已有本地检查 hook，请先整合，避免替换。", file=sys.stderr)
            return 1
    for name in ("pre-commit", "pre-push", "run-check"):
        path = ROOT / ".githooks" / name
        path.chmod(path.stat().st_mode | 0o111)
    result = run_steps([("启用本仓库 Git hooks", ["git", "config", "--local", "core.hooksPath", ".githooks"], ROOT)])
    if not result:
        print("已启用：提交前检查暂存区；推送前完整验证。", flush=True)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="all", choices=("all", "staged", "pre-push", "python-tests", "install-hooks"))
    parser.add_argument("--base", help="CI 比较基准提交；全零时比较与远端默认分支的共同祖先")
    parser.add_argument("--default-branch", help="新分支检查使用的远端默认分支名称")
    args = parser.parse_args(argv)
    try:
        if args.command == "staged":
            return run_steps([("暂存区差异空白", ["git", "diff", "--cached", "--check"], ROOT)])
        if args.command == "pre-push":
            return pre_push(sys.stdin)
        if args.command == "python-tests":
            return python_tests()
        if args.command == "install-hooks":
            return install_hooks()
        result = all_checks(args.base, args.default_branch)
        if not result:
            print("\n全部自动检查通过。请继续评审需求、规则与设计取舍。", flush=True)
        return result
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"检查失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
