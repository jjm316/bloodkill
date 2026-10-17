"""Ticket 24: 旧免账号房间在账号机制首次启用时备份停用，且只切换一次。

存储契约边界（``RoomManager.restore`` 对旧格式存档目录）与真实 uvicorn/HTTP/WS
边界：混合旧等待/进行/已结束存档首次启动时未结束房只备份停用（不伪造终局、
不制作中止回放），旧已结束回放在登录后仍可读；重复启动不误关账号方案的新房
间。故障注入用验证专用钩子 ``BLOOD_BOUND_LEGACY_CUTOVER_FAULT=
<before-backup|after-backup|before-marker>`` 把切换停在精确边界，再以真实
``taskkill /T /F`` 整树终止模拟切换中断（生产不设置该变量即立即返回）。

旧样例的构造说明：规则引擎与存档格式自旧免账号服务端以来未变（账号工单只改
了 server/ 与 client/），因此测试用当前引擎构造对局、按旧服务端的元数据格式
（``hostToken`` 等字段、无 ``hostAccountId``）写盘——这正是旧服务端留下的存档。
"""

import asyncio
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest

import websockets

from blood_bound import Command, RulesEngine, save_game
from server.rooms import (
    LEGACY_BACKUP_DIRECTORY,
    LEGACY_CUTOVER_FAULT_ENV,
    LEGACY_CUTOVER_MARKER,
    RoomManager,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# 本工单测试独占的公共端口段（29280–29299）；29260–29279 归并行中的工单 26。
_PORT_POOL = iter(range(29280, 29300))

LEGACY_NAMES = ["旧房主甲", "旧玩家乙", "旧玩家丙", "旧玩家丁", "旧玩家戊", "旧玩家己"]


def finish_game_deterministically(engine: RulesEngine) -> None:
    """与 test_server_rooms 相同的确定性终局推进（引擎层，不经房间管理）。"""
    holder = engine.state.dagger_holder_id
    victim = next(pid for pid in engine.state.players if pid != holder)

    def apply(actor, kind, payload, prefix):
        engine.apply(Command(f"{prefix}-{secrets.token_hex(4)}", engine.state.game_id,
                             actor, engine.state.revision, kind, payload))

    for turn in range(60):
        current = engine.state.dagger_holder_id
        if current != holder:
            apply(current, "pass-dagger", {"targetPlayerId": holder}, f"pass-{turn}")
        apply(holder, "attack", {"targetPlayerId": victim}, f"attack-{turn}")
        while engine.state.pending and engine.state.pending.kind == "intervention":
            pending = engine.state.pending
            stage = pending.context.get("stage")
            if stage == "gate":
                apply(pending.actor_player_id, "answer-intervention-request", {"need": True}, f"gate-{turn}")
            elif stage == "poll":
                responses = pending.context["responses"]
                responder = next(pid for pid in pending.eligible_player_ids if pid not in responses)
                apply(responder, "respond-intervention", {"volunteer": False}, f"respond-{turn}")
            else:
                apply(victim, "decline-intervention", {}, f"decline-{turn}")
        while engine.state.pending and engine.state.pending.kind == "reveal":
            pending = engine.state.pending
            token = pending.context["eligibleTokens"][0]
            payload = {"token": token}
            if token.startswith("marker-") and engine.state.players[victim].identity_markers[int(token[-1])] == "wild":
                payload["color"] = "rose"
            apply(victim, "choose-reveal", payload, f"reveal-{turn}")
        if engine.state.pending and engine.state.pending.kind == "skill":
            apply(victim, "choose-skill", {"use": False}, f"skill-{turn}")
        if engine.state.status == "ended":
            return
    raise AssertionError("确定性终局推进未在限定回合内结束对局")


def seed_legacy_room(saves_dir: Path, *, code: str, status: str,
                     players: int = 6, created_at: float = 1_000_000.0,
                     finished_at: float | None = None) -> dict:
    """按旧免账号服务端的写盘格式构造一份旧存档（旧 meta 含 hostToken）。"""
    game_id = f"g-{secrets.token_hex(6)}"
    engine = RulesEngine.new_game(game_id, secrets.token_hex(16))
    player_ids: list[str] = []
    for name in LEGACY_NAMES[:players]:
        player_id = f"p-{secrets.token_hex(6)}"
        engine.apply(Command(f"join-{secrets.token_hex(4)}", game_id, None, engine.state.revision,
                             "join-game", {"playerId": player_id, "displayName": name}))
        player_ids.append(player_id)
    if status in {"playing", "ended"}:
        engine.apply(Command(f"start-{secrets.token_hex(4)}", game_id, None, engine.state.revision,
                             "start-game", {}))
    if status == "ended":
        finish_game_deterministically(engine)
        assert engine.state.status == "ended"
    save_game(engine, saves_dir / f"{game_id}.json.gz")
    meta = {
        "code": code,
        "gameId": game_id,
        "hostToken": secrets.token_urlsafe(24),
        "hostPlayerId": player_ids[0],
        "locked": False,
        "status": status,
        "createdAt": created_at,
        "finishedAt": finished_at,
        "windowDeadline": None,
        "windowStage": None,
    }
    (saves_dir / f"{game_id}.meta.json").write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return {"code": code, "gameId": game_id, "status": status,
            "revision": engine.state.revision, "engineStatus": engine.state.status,
            "savePath": saves_dir / f"{game_id}.json.gz",
            "metaPath": saves_dir / f"{game_id}.meta.json"}


def legacy_backup_dir(saves_dir, game_id) -> Path:
    return Path(saves_dir) / LEGACY_BACKUP_DIRECTORY / game_id


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class LegacyCutoverTests(unittest.TestCase):
    """V18.01–V18.05：旧房间备份停用并只切换一次。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saves = Path(self.tmp.name)
        self.port = next(_PORT_POOL)
        self.process = None
        self.log = None
        self.addCleanup(self.stop_server)

    # ---- 服务进程（支持故障注入环境变量与真实整树终止） --------------------

    def start_server(self, extra_env=None, saves_dir=None):
        self.stop_server()
        self.log_path = Path(saves_dir or self.saves) / "server.log"
        self.log = self.log_path.open("ab")
        environment = {**os.environ, "BLOOD_BOUND_SAVES_DIR": str(saves_dir or self.saves),
                       **(extra_env or {})}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(REPO_ROOT), env=environment, stdout=self.log, stderr=self.log)
        self._wait_health()
        return self.log_path

    def start_server_no_wait(self, extra_env=None, saves_dir=None):
        """启动但不等 /health：故障钩子会把切换停在导入期，端口可能尚未绑定。"""
        self.stop_server()
        self.log_path = Path(saves_dir or self.saves) / "server.log"
        self.log = self.log_path.open("ab")
        environment = {**os.environ, "BLOOD_BOUND_SAVES_DIR": str(saves_dir or self.saves),
                       **(extra_env or {})}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(REPO_ROOT), env=environment, stdout=self.log, stderr=self.log)
        return self.log_path

    def _wait_health(self):
        for _ in range(200):
            if self.process.poll() is not None:
                self.fail(f"uvicorn 启动后即退出（端口 {self.port} 被其他进程占用？）："
                          f"{self.log_path.read_text(encoding='utf-8', errors='replace')[-2000:]}")
            try:
                self.request("/health")
                return
            except OSError:
                time.sleep(0.05)
        self.fail("隔离 HTTP 服务未启动")

    def stop_server(self):
        """真实整树终止（与工单 22 相同的故障注入手段，不是 mock）。"""
        if self.process is None:
            return
        if os.name == "nt" and self.process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            self.process.wait(timeout=10)
        elif self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.log is not None:
            self.log.close()
            self.log = None
        self.process = None

    def server_log(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def wait_for_fault_marker(self, point: str, saves_dir=None, timeout: float = 15.0) -> Path:
        saves = Path(saves_dir or self.saves)
        marker = saves / f".legacy-cutover-fault.{point}.marker"
        deadline = time.time() + timeout
        while not marker.exists():
            if time.time() > deadline:
                self.fail(f"故障注入标记未出现：{marker}；日志尾部：\n"
                          f"{self.server_log()[-2000:]}")
            if self.process is not None and self.process.poll() is not None:
                self.fail(f"服务进程提前退出；日志尾部：\n{self.server_log()[-2000:]}")
            time.sleep(0.05)
        return marker

    def clear_fault_files(self, saves_dir=None):
        for path in Path(saves_dir or self.saves).glob(".legacy-cutover-fault.*"):
            path.unlink()

    # ---- HTTP/WS/账号辅助（与工单 21/22 测试同一手法） ----------------------

    def request(self, path, data=None, cookie=None):
        import urllib.error
        import urllib.request
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def signup(self, name, password="123456"):
        status, body, headers = self.request("/api/auth/register", {
            "username": name, "password": password, "confirmPassword": password})
        self.assertEqual(status, 201, body)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    def connect(self, code, cookie, mode="player"):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}",
                                  additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player",
                                      "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 5))

    # ---- V18.01 ------------------------------------------------------------

    def test_v18_01_first_startup_deactivates_old_unfinished_and_keeps_old_replays(self):
        waiting = seed_legacy_room(self.saves, code="210001", status="waiting", players=2)
        playing = seed_legacy_room(self.saves, code="210002", status="playing", players=6)
        ended = seed_legacy_room(self.saves, code="210003", status="ended", players=6,
                                 finished_at=1_234_567.0)
        self.start_server()
        log = self.server_log()

        # 报告如实：两个未结束旧房已备份停用，完成记录到位；已结束旧房不被声称停用。
        for legacy in (waiting, playing):
            self.assertIn(f"旧房间切换：房间 {legacy['code']}（对局 {legacy['gameId']}）已备份并停用", log)
        self.assertIn("旧房间切换完成：共停用 2 个旧房间", log)
        self.assertNotIn(ended["code"], "\n".join(
            line for line in log.splitlines() if "已备份并停用" in line))

        # 未结束旧房只备份：三件套齐全，记录为 legacy-deactivated（不是正常终局，
        # 不伪造胜负/身份揭晓），引擎原样（修订号不变、状态不是 ended）。
        for legacy in (waiting, playing):
            backup = legacy_backup_dir(self.saves, legacy["gameId"])
            self.assertTrue((backup / "game.json.gz").exists(), backup)
            self.assertTrue((backup / "meta.json").exists(), backup)
            record = read_json(backup / "cutover.json")
            self.assertEqual(record["status"], "legacy-deactivated")
            self.assertEqual(record["code"], legacy["code"])
            self.assertEqual(record["gameId"], legacy["gameId"])
            self.assertTrue(record["engineLoadable"])
            self.assertNotIn("result", record, "停用记录不伪造胜负")
            from blood_bound import load_game
            engine = load_game(backup / "game.json.gz")
            self.assertEqual(engine.state.revision, legacy["revision"], "备份的引擎原样、无新增事件")
            self.assertNotEqual(engine.state.status, "ended")
            self.assertFalse(self.saves.joinpath(f"{legacy['gameId']}.meta.json").exists(),
                             "活动存档已移出")
            self.assertFalse(self.saves.joinpath(f"{legacy['gameId']}.json.gz").exists(),
                             "活动存档已移出")

        # 完成标记只登记两个未结束旧房。
        marker = read_json(self.saves / LEGACY_CUTOVER_MARKER)
        self.assertEqual(marker["processedGameIds"], sorted([waiting["gameId"], playing["gameId"]]))
        self.assertEqual(marker["processedCount"], 2)

        # 旧已结束回放保留：活动存档仍在、按原保留规则恢复，登录后可读且是旁观投影。
        self.assertTrue(ended["metaPath"].exists())
        self.assertTrue(ended["savePath"].exists())
        account, cookie = self.signup("新账号一")
        status, info, _ = self.request(f"/api/rooms/{ended['code']}", None, cookie)
        self.assertEqual(status, 200)
        self.assertEqual(info["status"], "ended")
        status, replay, _ = self.request(f"/api/rooms/{ended['code']}/replay", cookie=cookie)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["steps"])
        self.assertEqual(replay["steps"][-1]["status"], "ended")
        for step in replay["steps"]:
            payload = json.dumps(step, ensure_ascii=False)
            self.assertNotIn("clueIcon", payload, "回放是旁观投影，不公开线索情报")
            self.assertNotIn("seenNeighbourClue", payload)
        # 终局步的身份揭晓是正常结束的既定公开事实；进行中步子不得提前泄露：
        # 停用的未结束旧房没有任何 HTTP/WS 入口（下面逐个断言），不存在提前揭晓。
        for step in replay["steps"][:-1]:
            for player in step.get("players", []):
                self.assertNotIn("identity", player, "对局未结束的投影不携带任何玩家的身份")

        # 未结束旧房不能经 HTTP 进入或观看：不存在，也不提供部分回放。
        for legacy in (waiting, playing):
            status, _, _ = self.request(f"/api/rooms/{legacy['code']}", None, cookie)
            self.assertEqual(status, 404)
            status, body, _ = self.request(f"/api/rooms/{legacy['code']}/replay", cookie=cookie)
            self.assertEqual(status, 404, body)

        # 服务照常可用：新账号能开新房（旧姓名/token 不再是进入方式）。
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200, room)
        self.assertTrue(room["code"] not in {waiting["code"], playing["code"], ended["code"]})

    # ---- V18.02 ------------------------------------------------------------

    def test_v18_02_repeated_startups_never_reprocess_or_touch_account_scheme_rooms(self):
        from tests.account_fixtures import account as fixture_account

        legacy = seed_legacy_room(self.saves, code="220001", status="waiting", players=2)
        # 同一存档目录里预置账号方案的新房间：一个等待中的新房（真实账号座位），
        # 一个已管理关闭的房（留下 admin-backup 关闭标记）——重复启动两者都不
        # 能被旧房间切换碰坏。
        seed_manager = RoomManager(self.saves)
        seeded_host = fixture_account("切换新房主")
        new_room = seed_manager.create_room(seeded_host)
        seed_manager.join_or_resume(new_room, fixture_account("切换新玩家"))
        closed_room = seed_manager.create_room(fixture_account("切换弃局房主"))
        seed_manager.admin_close(closed_room)
        closure_bytes = (self.saves / "admin-backup" / closed_room.game_id / "closure.json").read_bytes()
        new_room_revision = new_room.engine.state.revision
        del seed_manager

        self.start_server()
        # 首次启动：旧房切换完成；账号方案的新房照常恢复，关闭房不复活、关闭标记不动。
        self.assertIn(f"旧房间切换：房间 {legacy['code']}（对局 {legacy['gameId']}）已备份并停用",
                      self.server_log())
        _, overview_cookie = self.signup("切换核对员")
        status, info, _ = self.request(f"/api/rooms/{new_room.code}", None, overview_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(info["status"], "waiting")
        self.assertEqual(info["playerCount"], 2)
        status, _, _ = self.request(f"/api/rooms/{closed_room.code}", None, overview_cookie)
        self.assertEqual(status, 404, "已管理关闭的房间不因旧房间切换复活")
        self.assertEqual(
            (self.saves / "admin-backup" / closed_room.game_id / "closure.json").read_bytes(),
            closure_bytes, "管理关闭标记字节不变")
        marker_bytes = (self.saves / LEGACY_CUTOVER_MARKER).read_bytes()
        backup_entries = sorted(p.name for p in (self.saves / LEGACY_BACKUP_DIRECTORY).iterdir())

        # 首次切换后创建新账号房间（真实 API），随后第二/第三次启动都要能恢复它。
        host, host_cookie = self.signup("重启房主")
        friend, friend_cookie = self.signup("重启玩家")
        status, created, _ = self.request("/api/rooms", {}, host_cookie)
        self.assertEqual(status, 200, created)

        async def join_and_remember():
            async with self.connect(created["code"], friend_cookie) as socket:
                state = await self.hello(socket)
                return state["yourPlayerId"]

        friend_player_id = asyncio.run(join_and_remember())

        for restart in (2, 3):
            self.stop_server()
            self.start_server()
            # 新账号房间照常恢复：占用在、座位引用不变、可继续进入。
            status, occupied, _ = self.request("/api/account/room", cookie=friend_cookie)
            self.assertEqual(status, 200)
            self.assertEqual(occupied["room"], {"code": created["code"], "status": "waiting"},
                             f"第 {restart} 次启动后新房间未恢复")
            status, info, _ = self.request(f"/api/rooms/{created['code']}", None, friend_cookie)
            self.assertEqual(info["playerCount"], 2, "重启不释放/不重复释放新房间座位")

            async def resume() -> str:
                async with self.connect(created["code"], friend_cookie) as socket:
                    state = await self.hello(socket)
                    return state["yourPlayerId"]

            self.assertEqual(asyncio.run(resume()), friend_player_id,
                             f"第 {restart} 次启动恢复的是同一座位，没有重复处理")
            # 旧切换不再发生：无新增停用日志，完成标记与备份集合字节级不变。
            self.assertEqual(self.server_log().count("已备份并停用"), 1,
                             "重复启动不再次备份停用旧房")
            self.assertEqual((self.saves / LEGACY_CUTOVER_MARKER).read_bytes(), marker_bytes,
                             "完成标记字节不变")
            self.assertEqual(sorted(p.name for p in (self.saves / LEGACY_BACKUP_DIRECTORY).iterdir()),
                             backup_entries, "备份目录不增不减")
            # 预置的账号方案新房依旧原样（修订号不变，没有被当成旧房处理）。
            status, info, _ = self.request(f"/api/rooms/{new_room.code}", None, overview_cookie)
            self.assertEqual((status, info["status"], info["playerCount"]), (200, "waiting", 2))
        # 存储层核对预置新房的修订号（未被任何切换路径写过）。
        from blood_bound import load_game
        engine = load_game(self.saves / f"{new_room.game_id}.json.gz")
        self.assertEqual(engine.state.revision, new_room_revision, "账号方案新房的存档未被改写")

    # ---- V18.03 ------------------------------------------------------------

    def test_v18_03_fault_injection_backup_failure_partial_crash_and_bad_saves(self):
        for scenario in ("backup-failure", "kill-after-backup", "kill-before-backup",
                         "kill-before-marker", "bad-save", "bad-meta"):
            with self.subTest(scenario=scenario):
                phase = Path(self.tmp.name) / scenario
                phase.mkdir()
                getattr(self, f"_phase_{scenario.replace('-', '_')}")(phase)
        # 全部阶段共用同一端口，逐段真实整树终止；末尾确认端口可用。
        self.start_server(saves_dir=self.saves)

    def _log_tail(self, before_length: int) -> str:
        return self.server_log()[before_length:]

    def _phase_backup_failure(self, phase: Path):
        legacy = seed_legacy_room(phase, code="230001", status="waiting", players=2)
        # 以真实文件占位使 legacy-backup/ 无法创建：备份必失败。
        (phase / LEGACY_BACKUP_DIRECTORY).write_text("占位文件，使备份目录不可写", encoding="utf-8")
        self.start_server(saves_dir=phase)
        log = self.server_log()
        # 如实报告失败：不输出成功摘要、不写完成标记；原文件保留；房间不可进入。
        self.assertIn(f"旧房间切换失败：房间 {legacy['code']}（对局 {legacy['gameId']}）备份失败", log)
        self.assertIn("原存档保留、房间未停用", log)
        self.assertIn("旧房间切换未完成：1 个旧房间处理失败", log)
        self.assertNotIn("已备份并停用", log, "备份失败不得出现成功停用的假报告")
        self.assertFalse((phase / LEGACY_CUTOVER_MARKER).exists())
        self.assertTrue(legacy["metaPath"].exists(), "既有原文件不丢")
        self.assertTrue(legacy["savePath"].exists(), "既有原文件不丢")
        check_cookie = self.signup("备份失败后开房")[1]
        status, _, _ = self.request(f"/api/rooms/{legacy['code']}", None, check_cookie)
        self.assertEqual(status, 404, "切换失败的旧房同样不可恢复、不可进入")
        status, room, _ = self.request("/api/rooms", {}, check_cookie)
        self.assertEqual(status, 200, "服务对其他操作照常可用")
        # 解除占位后真实重启：进度可恢复，切换补完成。
        self.stop_server()
        (phase / LEGACY_BACKUP_DIRECTORY).unlink()
        self.start_server(saves_dir=phase)
        tail = self.server_log()
        self.assertIn(f"旧房间切换：房间 {legacy['code']}（对局 {legacy['gameId']}）已备份并停用", tail)
        marker = read_json(phase / LEGACY_CUTOVER_MARKER)
        self.assertEqual(marker["processedGameIds"], [legacy["gameId"]])
        self.assertFalse(legacy["metaPath"].exists())
        self.stop_server()

    def _phase_kill_after_backup(self, phase: Path):
        self.clear_fault_files(phase)
        first = seed_legacy_room(phase, code="230002", status="waiting", players=2)
        second = seed_legacy_room(phase, code="230003", status="playing", players=6)
        ordered = sorted([first, second], key=lambda item: item["gameId"])
        # 切换在「第一个旧房已备份、活动存档未移出」的边界被真实整树终止：
        # 这是「切换部分完成后异常」的精确现场。
        self.start_server_no_wait({LEGACY_CUTOVER_FAULT_ENV: "after-backup"}, saves_dir=phase)
        self.wait_for_fault_marker("after-backup", saves_dir=phase)
        self.assertTrue((legacy_backup_dir(phase, ordered[0]["gameId"]) / "cutover.json").exists())
        self.assertTrue(ordered[0]["metaPath"].exists(), "中断边界：活动存档尚未移出")
        self.assertFalse(legacy_backup_dir(phase, ordered[1]["gameId"]).exists(),
                         "第二个旧房尚未处理")
        self.stop_server()
        self.assertFalse((phase / LEGACY_CUTOVER_MARKER).exists(), "未完成不得写完成标记")
        # 同一存档目录干净重启：进度可恢复——两个旧房各恰有一个备份目录，标记补齐。
        self.clear_fault_files(phase)
        self.start_server(saves_dir=phase)
        for legacy in ordered:
            self.assertFalse(legacy["metaPath"].exists())
            self.assertFalse(legacy["savePath"].exists())
        entries = sorted(p.name for p in (phase / LEGACY_BACKUP_DIRECTORY).iterdir())
        self.assertEqual(entries, sorted(item["gameId"] for item in ordered), "每房恰一个备份目录")
        marker = read_json(phase / LEGACY_CUTOVER_MARKER)
        self.assertEqual(marker["processedGameIds"], sorted(item["gameId"] for item in ordered))
        self.stop_server()

    def _phase_kill_before_backup(self, phase: Path):
        self.clear_fault_files(phase)
        legacy = seed_legacy_room(phase, code="230004", status="waiting", players=2)
        self.start_server_no_wait({LEGACY_CUTOVER_FAULT_ENV: "before-backup"}, saves_dir=phase)
        self.wait_for_fault_marker("before-backup", saves_dir=phase)
        self.assertFalse((phase / LEGACY_BACKUP_DIRECTORY / legacy["gameId"]).exists(),
                         "备份前边界：尚未写任何备份")
        self.assertTrue(legacy["metaPath"].exists())
        self.stop_server()
        self.clear_fault_files(phase)
        self.start_server(saves_dir=phase)
        self.assertIn("已备份并停用", self.server_log())
        self.assertTrue((phase / LEGACY_CUTOVER_MARKER).exists())
        self.stop_server()

    def _phase_kill_before_marker(self, phase: Path):
        self.clear_fault_files(phase)
        legacy = seed_legacy_room(phase, code="230005", status="waiting", players=2)
        self.start_server_no_wait({LEGACY_CUTOVER_FAULT_ENV: "before-marker"}, saves_dir=phase)
        self.wait_for_fault_marker("before-marker", saves_dir=phase)
        # 全部旧房已处理完、完成标记未写：在此中断。
        self.assertFalse(legacy["metaPath"].exists(), "停用已提交")
        record_before = (legacy_backup_dir(phase, legacy["gameId"]) / "cutover.json").read_bytes()
        self.assertFalse((phase / LEGACY_CUTOVER_MARKER).exists())
        self.stop_server()
        self.clear_fault_files(phase)
        self.start_server(saves_dir=phase)
        # 重启凭备份目录里的停用记录补写完成标记，不重复处理任何房间。
        marker = read_json(phase / LEGACY_CUTOVER_MARKER)
        self.assertEqual(marker["processedGameIds"], [legacy["gameId"]])
        self.assertEqual((legacy_backup_dir(phase, legacy["gameId"]) / "cutover.json").read_bytes(),
                         record_before, "重启不重复处理已停用的旧房")
        self.stop_server()

    def _phase_bad_save(self, phase: Path):
        legacy = seed_legacy_room(phase, code="230006", status="waiting", players=2)
        corrupt = "这根本不是 gzip 存档".encode("utf-8")
        legacy["savePath"].write_bytes(corrupt)
        with redirect_stdout(StringIO()) as captured:
            RoomManager(phase).restore()
        output = captured.getvalue()
        # 坏旧存档：原字节原样备份保留、房间停用、报告如实说明读不出。
        self.assertIn(f"旧房间切换：房间 {legacy['code']}（对局 {legacy['gameId']}）"
                      "存档无法读取，已按原样备份并停用", output)
        backup = legacy_backup_dir(phase, legacy["gameId"])
        self.assertEqual((backup / "game.json.gz").read_bytes(), corrupt, "原文件字节不丢")
        self.assertEqual(read_json(backup / "cutover.json")["engineLoadable"], False)
        self.assertFalse(legacy["metaPath"].exists())
        self.assertTrue((phase / LEGACY_CUTOVER_MARKER).exists(), "坏旧存档不阻塞切换完成")

    def _phase_bad_meta(self, phase: Path):
        garbage = "{这不是合法 JSON"
        bad_meta = phase / "g-badmeta.meta.json"
        bad_meta.write_text(garbage, encoding="utf-8")
        with redirect_stdout(StringIO()) as captured:
            RoomManager(phase).restore()
        self.assertEqual(bad_meta.read_text(encoding="utf-8"), garbage, "无法分类的坏元数据原样保留")
        self.assertFalse((phase / LEGACY_BACKUP_DIRECTORY).exists(), "坏元数据不进入备份")
        self.assertFalse((phase / LEGACY_CUTOVER_MARKER).exists(), "没有可切换的旧房就不写标记")
        self.assertEqual(captured.getvalue(), "", "无事可做时不输出任何切换日志")

    # ---- V18.04 ------------------------------------------------------------

    def test_v18_04_legacy_identity_fields_old_protocol_and_invitation_room_code(self):
        self.start_server()
        host, host_cookie = self.signup("新房房主")
        friend, friend_cookie = self.signup("受邀好友")
        status, room, _ = self.request("/api/rooms", {}, host_cookie)
        self.assertEqual(status, 200, room)

        # 旧姓名/token 的建房请求（旧客户端的请求体）不授权。
        status, body, _ = self.request("/api/rooms", {"name": "旧房主甲"}, host_cookie)
        self.assertEqual(status, 400, body)
        self.assertEqual(body["code"], "protocol.legacy-identity")
        status, body, _ = self.request("/api/rooms", {"token": "legacy-host-secret"}, host_cookie)
        self.assertEqual((status, body["code"]), (400, "protocol.legacy-identity"))

        # 旧协议 WS：hello 携带 name/token 字段 → 明确拒绝刷新，不落座不冒认。
        async def legacy_identity_hello() -> dict:
            async with self.connect(room["code"], friend_cookie) as socket:
                frame = await self.hello(socket, name="旧房主甲", token="legacy-host-secret")
                return frame

        frame = asyncio.run(legacy_identity_hello())
        self.assertEqual(frame["code"], "protocol.legacy-identity")
        self.assertIn("请刷新页面", frame["message"])
        status, info, _ = self.request(f"/api/rooms/{room['code']}", None, host_cookie)
        self.assertEqual(info["playerCount"], 1, "被拒的旧身份 hello 不产生任何座位")

        # 旧协议版本客户端（protocolVersion=3）：版本不匹配的刷新提示。
        async def old_version_hello() -> dict:
            async with self.connect(room["code"], friend_cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player",
                                              "protocolVersion": "3"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 5))

        frame = asyncio.run(old_version_hello())
        self.assertEqual(frame["code"], "protocol.version-mismatch")
        self.assertEqual(frame["details"]["expected"], "4")

        # 旧邀请链接只承接房号：好友登录后以自己的账号进入目标房，得到自己的
        # 座位与自己的名字（链接里的旧姓名/令牌不参与授权、不冒认他人座位）。
        async def invited_join() -> dict:
            async with self.connect(room["code"], friend_cookie) as socket:
                state = await self.hello(socket)
                return state

        state = asyncio.run(invited_join())
        self.assertTrue(state["yourPlayerId"])
        self.assertFalse(state["isHost"], "受邀者不是房主，旧令牌不能取得房主身份")
        names = [player["displayName"] for player in state["game"]["players"]]
        self.assertIn("受邀好友", names)
        self.assertNotIn("旧房主甲", names, "旧姓名不随邀请落座")
        status, info, _ = self.request(f"/api/rooms/{room['code']}", None, host_cookie)
        self.assertEqual(info["playerCount"], 2)

    # ---- V18.05 ------------------------------------------------------------

    def test_v18_05_old_ended_replays_retention_and_no_bypass_of_deactivated_rooms(self):
        from server.rooms import FINISHED_GAMES_TO_KEEP

        total = FINISHED_GAMES_TO_KEEP + 3
        ended_rooms = [seed_legacy_room(self.saves, code=f"25{i:04d}", status="ended", players=6,
                                        created_at=2_000_000.0 + i)
                       for i in range(total)]
        # finishedAt 在 meta 里按递增写入；恢复时按 finishedAt 排序淘汰最早的 3 个。
        for index, seeded in enumerate(ended_rooms):
            meta = read_json(seeded["metaPath"])
            meta["finishedAt"] = 3_000_000.0 + index
            seeded["metaPath"].write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        oldest = ended_rooms[:3]
        kept = ended_rooms[3:]
        unfinished = seed_legacy_room(self.saves, code="259999", status="playing", players=6)
        self.start_server()

        # 原保留规则照常生效：23 个旧终局只留最近 20 个，被清掉的活动存档消失。
        status, metrics, _ = self.request("/metrics")
        self.assertEqual(metrics["activeRooms"], FINISHED_GAMES_TO_KEEP)
        for pruned in oldest:
            self.assertFalse(pruned["metaPath"].exists(), "超出保留上限的旧终局照常清理")
        for retained in kept:
            self.assertTrue(retained["metaPath"].exists(), "保留窗口内的旧终局不动")

        # 旧结束回放登录后可读，不需要迁移到任何虚构账号：全新注册的账号即可观看。
        _, cookie = self.signup("回放观众")
        sample = kept[-1]
        status, replay, _ = self.request(f"/api/rooms/{sample['code']}/replay", cookie=cookie)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["steps"][-1]["status"], "ended")
        status, body, _ = self.request(f"/api/rooms/{oldest[-1]['code']}/replay", cookie=cookie)
        self.assertEqual(status, 404, "被保留规则清掉的旧回放按原规则不可读")

        # 未结束旧局不能经 HTTP/WS 绕过停用：一切入口都只报「不存在」。
        status, _, _ = self.request(f"/api/rooms/{unfinished['code']}", None, cookie)
        self.assertEqual(status, 404)
        status, body, _ = self.request(f"/api/rooms/{unfinished['code']}/replay", cookie=cookie)
        self.assertEqual((status, body["code"]), (404, "room.not-found"))

        async def bypass_attempts() -> None:
            # 登录后的旧 WS：对停用房间的第一条帧就是不存在，hello 内容无关紧要。
            async with self.connect(unfinished["code"], cookie) as socket:
                frame = json.loads(await asyncio.wait_for(socket.recv(), 5))
                self.assertEqual(frame["code"], "room.not-found")
            # 携带旧 name/token 的旧客户端同样拿不到任何房间状态。
            async with self.connect(unfinished["code"], cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player",
                                              "protocolVersion": "4",
                                              "name": "旧玩家乙", "token": "legacy-secret"}))
                frame = json.loads(await asyncio.wait_for(socket.recv(), 5))
                self.assertEqual(frame["code"], "room.not-found")
            # 未登录的旧 WS 也进不来。
            async with websockets.connect(
                    f"ws://127.0.0.1:{self.port}/ws/{unfinished['code']}", proxy=None) as socket:
                frame = json.loads(await asyncio.wait_for(socket.recv(), 5))
                self.assertEqual(frame["code"], "auth.login-required")

        asyncio.run(bypass_attempts())

        # 旧已结束房间不能在线旁观（回放才是入口）；停用备份不伪造终局。
        async def spectate_ended() -> dict:
            async with self.connect(sample["code"], cookie, mode="spectator") as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "spectator",
                                              "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 5))

        frame = asyncio.run(spectate_ended())
        self.assertEqual(frame["code"], "room.ended")
        record = read_json(legacy_backup_dir(self.saves, unfinished["gameId"]) / "cutover.json")
        self.assertNotIn("result", record)
        self.assertEqual(record["engineLoadable"], True)
        from blood_bound import load_game
        engine = load_game(legacy_backup_dir(self.saves, unfinished["gameId"]) / "game.json.gz")
        self.assertNotEqual(engine.state.status, "ended", "停用不是正常终局，不伪造结束")


if __name__ == "__main__":
    unittest.main()
