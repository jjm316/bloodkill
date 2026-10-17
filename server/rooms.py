"""In-memory room registry and persistence for the authoritative web server.

This module is pure standard-library plus `blood_bound`: it owns room state,
host credentials, seat assignment, auto-save, recovery after restart, and
finished-game retention. It has no web or WebSocket dependency, so it can be
unit-tested without a running server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from blood_bound import (
    Command,
    Event,
    ReplayPlayer,
    RuleError,
    RulesEngine,
    SaveError,
    create_save_document,
    load_game,
    project_state,
    save_game,
)

from .deadlines import SINGLE_WINDOW_KINDS
from .accounts import Account

FINISHED_GAMES_TO_KEEP = 20
# 管理关闭（工单 21）的隔离备份目录：与活动房间恢复扫描（存档根目录）和
# 「最近 N 个正常终局」清理互不相干，清理绝不触碰这个子目录。
ADMIN_BACKUP_DIRECTORY = "admin-backup"

# 旧房间切换（工单 24）：账号机制首次启用时，旧免账号服务端留下的等待/进行
# 房间只备份（原样、不伪造终局）后停用；旧已结束回放照常按保留规则恢复。备份
# 放独立的 legacy-backup/ 子目录，完成事实登记在存档根的 legacy-cutover.json，
# 两者同样不被活动扫描与回放清理触碰。
LEGACY_BACKUP_DIRECTORY = "legacy-backup"
LEGACY_CUTOVER_MARKER = "legacy-cutover.json"

# 工单 22/24 的故障注入钩子：仅当服务进程以该环境变量指定边界时，管理关闭/
# 旧房间切换才会在该边界写标记文件并阻塞等待释放文件。生产不设置此变量，函
# 数立即返回；验证用它把进程停在精确边界，再以真实进程终止模拟中断，或用释
# 放文件门控确定性交错。
FAULT_PAUSE_ENV = "BLOOD_BOUND_ADMIN_CLOSE_FAULT"
LEGACY_CUTOVER_FAULT_ENV = "BLOOD_BOUND_LEGACY_CUTOVER_FAULT"
FAULT_PAUSE_MAX_SECONDS = 300.0


def _fault_pause(env_name: str, marker_prefix: str, point: str,
                 saves_dir: str | Path, subject: str,
                 once_per_process: set[str] | None = None) -> None:
    """验证专用的边界挂起：环境变量命中 ``point`` 时写标记并阻塞等释放文件。

    ``once_per_process`` 传入集合时，同一边界本进程只挂起一次（工单 24 的切换
    在一次启动里连续处理多个旧房间，测试只需在第一个房间处停住）。
    """
    if os.environ.get(env_name, "") != point:
        return
    if once_per_process is not None:
        if point in once_per_process:
            return
        once_per_process.add(point)
    root = Path(saves_dir)
    marker = root / f"{marker_prefix}.{point}.marker"
    release = root / f"{marker_prefix}.{point}.release"
    marker.write_text(subject, encoding="utf-8")
    deadline = time.time() + FAULT_PAUSE_MAX_SECONDS
    while not release.exists():
        if time.time() > deadline:
            raise OSError(f"故障注入边界 {point} 等待释放文件超时")
        time.sleep(0.05)


def admin_close_fault_pause(point: str, saves_dir: str | Path, game_id: str) -> None:
    """在管理关闭的指定边界挂起（验证专用，见 :data:`FAULT_PAUSE_ENV`）。

    ``point`` 取 ``before-backup`` / ``after-backup`` / ``after-commit``。命中
    时先写 ``<存档目录>/.admin-close-fault.<point>.marker``（外部据此同步），
    再阻塞直到 ``.admin-close-fault.<point>.release`` 出现或超时。
    """
    _fault_pause(FAULT_PAUSE_ENV, ".admin-close-fault", point, saves_dir, game_id)


# 旧房间切换钩子的「每进程一次」记录：模块级即可，生产不设置环境变量时永不生效。
_legacy_cutover_fault_triggered: set[str] = set()


def legacy_cutover_fault_pause(point: str, saves_dir: str | Path, subject: str) -> None:
    """在旧房间切换的指定边界挂起（验证专用，见 :data:`LEGACY_CUTOVER_FAULT_ENV`）。

    ``point`` 取 ``before-backup`` / ``after-backup`` / ``before-marker``；同一
    边界每个进程只挂起一次。命名与释放文件协议和管理关闭钩子一致。
    """
    _fault_pause(LEGACY_CUTOVER_FAULT_ENV, ".legacy-cutover-fault", point, saves_dir,
                 subject, once_per_process=_legacy_cutover_fault_triggered)


@dataclass
class Room:
    code: str
    game_id: str
    host_account_id: str
    locked: bool
    status: str  # waiting | playing | ended | closed（管理关闭，工单 21）
    engine: RulesEngine
    created_at: float
    finished_at: float | None = None
    host_player_id: str | None = None
    seat_accounts: dict[str, str] = field(default_factory=dict)
    # Wall-clock expiry of the engine's current decision window (intervention
    # gate/poll/choice or one of the single-player windows). The engine stays
    # deterministic (no real time in state); the room owns the countdown and
    # the server injects the deadline into projections.
    window_deadline: float | None = None
    window_stage: str | None = None

    def player_id_for_account(self, account_id: str) -> str | None:
        return self.seat_accounts.get(account_id)

    def sync_window_deadline(self) -> None:
        """Track the current decision window's expiry; re-arms per window change."""
        key, seconds = self._window_identity(self.engine.state.pending)
        if key is None:
            self.window_deadline = None
            self.window_stage = None
            return
        if self.window_stage != key:
            self.window_stage = key
            self.window_deadline = time.time() + seconds

    def _window_identity(self, pending: Any) -> tuple[str | None, int]:
        """Stable identity of the pending window: same key = same countdown.

        The intervention stages keep their bare stage keys ("gate", "poll",
        "choice") so a stored meta re-arms without resetting the countdown
        after a restart; the request gate (ADR 0012) reuses the room's
        intervention timeout — no separate config. The three single-player
        windows (issue 05 / ADR 0011) key on the actor plus the eligibility
        frozen at open, so a damage chain that re-opens the same actor's
        reveal window re-arms a fresh countdown instead of inheriting a
        possibly-expired deadline.
        """
        state = self.engine.state
        if pending is None:
            return None, 0
        if pending.kind == "intervention":
            stage = pending.context.get("stage")
            if stage in {"gate", "poll", "choice"}:
                return str(stage), state.intervention_timeout_seconds
            return None, 0
        if pending.kind in SINGLE_WINDOW_KINDS:
            # Read the engine-frozen eligibility (context / eligible ids), the
            # same source the expiry submission guards on — never a second
            # recomputation of the rules.
            suffix = ""
            if pending.kind == "reveal":
                suffix = ":" + ",".join(pending.context.get("eligibleTokens", []))
            elif pending.kind == "token-return":
                suffix = ":" + ",".join(pending.eligible_player_ids)
            return f"{pending.kind}:{pending.actor_player_id}{suffix}", state.single_window_timeout_seconds
        return None, 0


class RoomManager:
    """Owns room state, persistence, and the finished-game retention window."""

    def __init__(self, saves_dir: str | Path) -> None:
        self.saves_dir = Path(saves_dir)
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        self.rooms: dict[str, Room] = {}
        # One active room per account (issue 12): the occupancy check and the
        # seat commit of create/join must be one atomic step, so concurrent
        # requests (multiple devices, threadpool callers) can never claim two
        # unfinished rooms even when persistence yields the GIL mid-flight.
        self._seats_lock = threading.Lock()

    # ---- creation ------------------------------------------------------

    def room_for_account(self, account_id: str) -> Room | None:
        return next((room for room in self.rooms.values()
                     if room.status in {"waiting", "playing"} and account_id in room.seat_accounts), None)

    def create_room(self, account: Account) -> Room:
        with self._seats_lock:
            existing = self.room_for_account(account.account_id)
            if existing is not None:
                if existing.host_account_id != account.account_id:
                    raise RuleError("account.room-occupied", "你已有未结束房间，请返回原房间。", roomCode=existing.code)
                return existing
            code = self._new_code()
            game_id = f"g-{secrets.token_hex(6)}"
            engine = RulesEngine.new_game(game_id, secrets.token_hex(16))
            player_id = f"p-{secrets.token_hex(6)}"
            engine.apply(Command(f"join-{secrets.token_hex(4)}", game_id, None, engine.state.revision,
                                 "join-game", {"playerId": player_id, "displayName": account.username}))
            room = Room(
                code=code,
                game_id=game_id,
                host_account_id=account.account_id,
                locked=False,
                status="waiting",
                engine=engine,
                created_at=time.time(),
                host_player_id=player_id,
                seat_accounts={account.account_id: player_id},
            )
            try:
                self._persist(room)
            except (OSError, SaveError):
                for path in (self._save_path(room), self._meta_path(room), self._meta_path(room).with_suffix(".tmp")):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise
            self.rooms[code] = room
            return room

    def get_room(self, code: str) -> Room | None:
        return self.rooms.get(code)

    # ---- joining -------------------------------------------------------

    def join_or_resume(self, room: Room, account: Account) -> tuple[str, bool]:
        """Join or restore only the seat bound to this authenticated account.

        The account's own recovery and a newcomer's join are decided
        separately: an account that already holds a seat may resume it even
        when the room is locked or the game has started (or ended, to keep
        browsing the result), while newcomers may only join an unlocked
        waiting room that is not full — and only if the account holds no seat
        in any other unfinished room (one active room per account, issue 12).
        """
        with self._seats_lock:
            if room.status == "closed":
                # 工单 22：已关闭房间对任何人都不再可用——包括持有旧座位引用
                # 的重连（关闭竞态窗口里排队的 hello 只能拿到明确拒绝，不能
                # 拿到一个看似可用的已关房状态）。
                raise RuleError("room.admin-closed", "房间已被管理员关闭，不能再进入。")
            existing = room.player_id_for_account(account.account_id)
            if existing is not None:
                return existing, False
            occupied = self.room_for_account(account.account_id)
            if occupied is not None:
                raise RuleError(
                    "account.room-occupied",
                    "你已有未结束房间，请返回原房间。",
                    roomCode=occupied.code,
                )
            if room.status == "ended":
                raise RuleError("room.ended", "对局已结束，不能加入；可观看回放。")
            if room.status != "waiting":
                raise RuleError("room.already-started", "游戏已开始，不能加入；若你已在房间，返回原房间即可恢复座位。")
            if room.locked:
                raise RuleError("room.locked", "房间已锁定，暂不能加入。")
            if len(room.engine.state.players) >= 12:
                raise RuleError("room.full", "房间已满员（12 人），不能加入。")
            player_id = f"p-{secrets.token_hex(6)}"
            command = Command(
                f"join-{secrets.token_hex(4)}",
                room.game_id,
                None,
                room.engine.state.revision,
                "join-game",
                {"playerId": player_id, "displayName": account.username},
            )
            room.seat_accounts[account.account_id] = player_id
            try:
                self.apply_command(room, command)
            except RuleError:
                room.seat_accounts.pop(account.account_id, None)
                raise
            return player_id, True

    # ---- commands ------------------------------------------------------

    def apply_command(self, room: Room, command: Command) -> tuple[Event, ...]:
        if room.status == "closed":
            # 管理关闭后的房间不再接受任何命令（含调度器迟到的超时代发），
            # 持久化也随之停止，活动存档不会被重建。
            raise RuleError("room.admin-closed", "房间已被管理员关闭，不能再操作。")
        events = room.engine.apply(command)
        room.sync_window_deadline()
        status = room.engine.state.status
        if status == "active" and room.status == "waiting":
            room.status = "playing"
        elif status == "ended" and room.status != "ended":
            room.status = "ended"
            room.finished_at = time.time()
        self._persist(room)
        if room.status == "ended":
            self._prune_finished()
        return events

    def start_game(
        self,
        room: Room,
        *,
        intervention_timeout_seconds: int | None = None,
        single_window_timeout_seconds: int | None = None,
    ) -> tuple[Event, ...]:
        # 与 exit_seat 共用占用锁（工单 13）：开局读取的玩家集合与等待玩家
        # 的退座互斥，退座/开局并发竞争最终只有一种合法状态。
        with self._seats_lock:
            payload: dict[str, Any] = {}
            if intervention_timeout_seconds is not None:
                payload["interventionTimeoutSeconds"] = int(intervention_timeout_seconds)
            if single_window_timeout_seconds is not None:
                payload["singleWindowTimeoutSeconds"] = int(single_window_timeout_seconds)
            command = Command(
                f"start-{secrets.token_hex(4)}",
                room.game_id,
                None,
                room.engine.state.revision,
                "start-game",
                payload,
            )
            return self.apply_command(room, command)

    def exit_seat(self, room: Room, account: Account) -> tuple[Event, ...]:
        """等待阶段普通玩家的主动退座（工单 13）：真正释放座位与占用。

        只覆盖这一条路径——房主返回大厅、对局中离开、断线/刷新/退出登录
        都不走这里：那些情形保留座位，只是断开连接。退座经引擎 leave-game
        命令产生 PlayerLeft 事件（ADR 0001），持久化后重启重放一致；座位
        映射与占用在引擎命令成功的同一临界区内提交。
        """
        with self._seats_lock:
            player_id = room.player_id_for_account(account.account_id)
            if player_id is None:
                raise RuleError("seat.not-held", "你在此房间没有座位。")
            if account.account_id == room.host_account_id:
                raise RuleError(
                    "room.host-seat-kept",
                    "房主返回大厅不会退座；你的座位和房主身份会保留，可随时返回本房间。",
                    roomCode=room.code,
                )
            if room.status != "waiting":
                raise RuleError(
                    "room.in-progress",
                    "对局进行中不能退出座位；返回大厅仅断开连接，你的座位会保留。",
                    roomCode=room.code,
                )
            command = Command(
                f"leave-{secrets.token_hex(4)}",
                room.game_id,
                player_id,
                room.engine.state.revision,
                "leave-game",
                {"playerId": player_id},
            )
            room.seat_accounts.pop(account.account_id, None)
            try:
                return self.apply_command(room, command)
            except RuleError:
                room.seat_accounts[account.account_id] = player_id
                raise

    def set_locked(self, room: Room, locked: bool) -> None:
        if room.status == "closed":
            # 已关闭房间的任何持久化路径都不得再写（防活动存档被重建）。
            raise RuleError("room.admin-closed", "房间已被管理员关闭，不能再操作。")
        room.locked = locked
        self._persist(room)

    # ---- persistence ---------------------------------------------------

    def _persist(self, room: Room) -> None:
        save_game(room.engine, self._save_path(room))
        self._write_meta(room)

    def _write_meta(self, room: Room) -> None:
        meta = {
            "code": room.code,
            "gameId": room.game_id,
            "hostAccountId": room.host_account_id,
            "seatAccounts": room.seat_accounts,
            "hostPlayerId": room.host_player_id,
            "locked": room.locked,
            "status": room.status,
            "createdAt": room.created_at,
            "finishedAt": room.finished_at,
            "windowDeadline": room.window_deadline,
            "windowStage": room.window_stage,
        }
        path = self._meta_path(room)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def _save_path(self, room: Room) -> Path:
        return self.saves_dir / f"{room.game_id}.json.gz"

    def _meta_path(self, room: Room) -> Path:
        return self.saves_dir / f"{room.game_id}.meta.json"

    # ---- admin close (issue 21) ----------------------------------------

    def admin_close(self, room: Room) -> dict[str, Any]:
        """管理关闭一个未结束房间：先备份，成功后才停用并释放占用。

        顺序保证「备份失败则不关闭」：存档、元数据（含座位归属记录）先写
        入隔离的 ``admin-backup/<gameId>/`` 目录并落关闭事实；随后才把该房
        的活动存档移出存档根目录、把房间停用并移出活跃注册表。任何一步失
        败都以 :class:`RuleError` 报告，房间保持可用，已写入的备份无害
        （下次重试整目录重写）。关闭未提交时留下的 stale 关闭记录会被移除
        （见 :meth:`_discard_stale_closure`），它描述的关闭从未发生。
        """
        with self._seats_lock:
            if self.rooms.get(room.code) is not room:
                raise RuleError("room.admin-closed", f"房间 {room.code} 已被管理员关闭，无需重复处理。")
            if room.status not in {"waiting", "playing"}:
                raise RuleError("room.ended", f"房间 {room.code} 已正常结束，无需管理关闭。")
            admin_close_fault_pause("before-backup", self.saves_dir, room.game_id)
            backup_dir = self.saves_dir / ADMIN_BACKUP_DIRECTORY / room.game_id
            affected = [
                room.engine.state.players[player_id].display_name
                for player_id in room.seat_accounts.values()
            ]
            closure = {
                "code": room.code,
                "gameId": room.game_id,
                "status": "closed",
                "closedAt": time.time(),
                "affectedPlayers": affected,
                "seatAccounts": dict(room.seat_accounts),
                "backupPath": str(backup_dir.resolve()),
            }
            try:
                backup_dir.mkdir(parents=True, exist_ok=True)
                self._copy_into_backup(self._save_path(room), backup_dir / "game.json.gz")
                self._copy_into_backup(self._meta_path(room), backup_dir / "meta.json")
                self._write_backup_json(backup_dir / "closure.json", closure)
            except OSError as error:
                raise RuleError(
                    "admin.backup-failed",
                    f"备份失败（{error}）。房间 {room.code} 未关闭，保持可用；请处理备份目录后重试。",
                ) from None
            admin_close_fault_pause("after-backup", self.saves_dir, room.game_id)
            try:
                self._meta_path(room).unlink(missing_ok=True)
                self._save_path(room).unlink(missing_ok=True)
            except OSError as error:
                # 备份完好但关闭未提交：stale 关闭记录不得继续冒充已关闭。
                self._discard_stale_closure(room.game_id)
                raise RuleError(
                    "admin.close-failed",
                    f"备份已完成，但移出活动存档失败（{error}）。房间 {room.code} 关闭未完成，"
                    "仍保持可用；请处理后重试（重试会覆盖同一备份目录）。",
                ) from None
            # 提交内存关闭：停用、清空决策窗口（调度器随后的 sync 会取消计
            # 时器）、移出注册表即释放全部座位占用。closed 不是正常终局，
            # 引擎状态原样留在备份里（无胜负、无身份揭晓）。
            room.status = "closed"
            room.window_deadline = None
            room.window_stage = None
            del self.rooms[room.code]
        return {
            "code": room.code,
            "gameId": room.game_id,
            "affectedPlayers": affected,
            "backupPath": str(backup_dir.resolve()),
        }

    def closed_room_record(self, code: str) -> dict[str, Any] | None:
        """某房号最近一次管理关闭记录；没有则 None（重复处理时明确报告）。"""
        backup_root = self.saves_dir / ADMIN_BACKUP_DIRECTORY
        try:
            closure_paths = list(backup_root.glob("*/closure.json"))
        except OSError:
            return None
        records: list[dict[str, Any]] = []
        for path in closure_paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and data.get("code") == code:
                records.append(data)
        if not records:
            return None
        return max(records, key=lambda item: item.get("closedAt") or 0.0)

    @staticmethod
    def _copy_into_backup(source: Path, target: Path) -> None:
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(source.read_bytes())
        temporary.replace(target)

    @staticmethod
    def _write_backup_json(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def _discard_stale_closure(self, game_id: str) -> None:
        """移除「从未提交的关闭」留下的 stale 关闭记录（工单 22）。

        只有活动存档仍在（房间可恢复/仍活跃）时才会调用：closure.json 声称
        已关闭、而关闭实际没有提交，这样的记录继续存在会让后续查询把活房
        误报成已关闭。备份里的存档与元数据副本保留（无害，重试会整目录重
        写），只移除会撒谎的关闭事实。
        """
        try:
            (self.saves_dir / ADMIN_BACKUP_DIRECTORY / game_id / "closure.json").unlink(missing_ok=True)
        except OSError:
            pass

    # ---- legacy cutover (issue 24) --------------------------------------

    def cutover_legacy_rooms(self) -> dict[str, Any]:
        """账号机制首次启用时，把旧免账号的未结束房间备份后停用（只做一次）。

        旧服务端元数据（含 ``hostToken``、无 ``hostAccountId``）代表免账号时代
        的房间：等待/进行的旧房**只备份**到 ``legacy-backup/<对局号>/``（存档与
        元数据原样，另附 ``cutover.json`` 停用事实——不是正常终局，不伪造胜负
        或身份揭晓，也不制作中止回放），成功后把活动存档移出存档根目录；旧已
        结束回放不属于切换范围，照常按保留规则恢复供登录后观看。

        每个房间独立提交，切换因此可重复执行与恢复：某房备份失败时原文件保持
        原样、如实报告失败且不写完成标记，下次启动继续处理剩余旧房；账号方案
        的新房间（元数据带 ``hostAccountId``）无论何时都不在处理范围内，重复
        启动绝不会误关新房。全部处理成功后写 ``legacy-cutover.json`` 完成标记。
        """
        report: dict[str, Any] = {"processed": [], "failed": [], "markerWritten": False}
        marker_path = self.saves_dir / LEGACY_CUTOVER_MARKER
        targets: list[tuple[Path, dict[str, Any]]] = []
        for meta_path in sorted(self.saves_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue  # 无法分类的坏元数据保持原样，与既有恢复扫描一致
            if not isinstance(meta, dict) or not meta.get("gameId"):
                continue
            if "hostAccountId" in meta:
                continue  # 账号方案的房间：不属于旧房间切换
            if meta.get("status", "waiting") == "ended":
                continue  # 旧已结束回放按原保留规则继续可读
            targets.append((meta_path, meta))
        for meta_path, meta in targets:
            game_id = str(meta["gameId"])
            code = str(meta.get("code") or game_id)
            legacy_cutover_fault_pause("before-backup", self.saves_dir, game_id)
            # 先核对存档可读性，让停用记录如实区分「可读原样备份」与「坏旧存档
            # 按字节原样备份」；读不出也不丢原文件——仍原样备份并停用。
            save_path = self.saves_dir / f"{game_id}.json.gz"
            engine_loadable = False
            players: list[str] = []
            try:
                engine = load_game(save_path)
                engine_loadable = True
                players = [player.display_name for player in engine.state.players.values()]
            except (SaveError, OSError):
                pass
            backup_dir = self.saves_dir / LEGACY_BACKUP_DIRECTORY / game_id
            record = {
                "code": code,
                "gameId": game_id,
                "status": "legacy-deactivated",
                "deactivatedAt": time.time(),
                "engineLoadable": engine_loadable,
                "players": players,
                "backupPath": str(backup_dir.resolve()),
            }
            try:
                backup_dir.mkdir(parents=True, exist_ok=True)
                if save_path.exists():
                    self._copy_into_backup(save_path, backup_dir / "game.json.gz")
                self._copy_into_backup(meta_path, backup_dir / "meta.json")
                self._write_backup_json(backup_dir / "cutover.json", record)
            except OSError as error:
                report["failed"].append({"code": code, "gameId": game_id, "reason": str(error)})
                print(f"旧房间切换失败：房间 {code}（对局 {game_id}）备份失败（{error}）；"
                      "原存档保留、房间未停用，下次启动将重试。", flush=True)
                continue
            legacy_cutover_fault_pause("after-backup", self.saves_dir, game_id)
            try:
                # 先移除恢复扫描入口（meta），再移除对局存档：两步之间中断只会
                # 留下一个不被扫描的孤立存档文件，重试安全（与 admin_close 同序）。
                meta_path.unlink()
                save_path.unlink(missing_ok=True)
            except OSError as error:
                report["failed"].append({"code": code, "gameId": game_id, "reason": str(error)})
                print(f"旧房间切换失败：房间 {code}（对局 {game_id}）移出活动存档失败（{error}）；"
                      "原存档保留、房间未停用，下次启动将重试。", flush=True)
                continue
            report["processed"].append(record)
            outcome = ("已备份并停用" if engine_loadable
                       else "存档无法读取，已按原样备份并停用")
            print(f"旧房间切换：房间 {code}（对局 {game_id}）{outcome}，"
                  f"备份目录 {record['backupPath']}。", flush=True)
        backup_root = self.saves_dir / LEGACY_BACKUP_DIRECTORY
        try:
            accumulated = sorted(path.parent.name for path in backup_root.glob("*/cutover.json"))
        except OSError:
            accumulated = []
        if report["failed"]:
            print(f"旧房间切换未完成：{len(report['failed'])} 个旧房间处理失败，"
                  "未写完成标记；下次启动会继续处理。", flush=True)
            return report
        # 完成标记：有新完成的房间时刷新；此前已写好且无新变化时保持字节不变。
        # 中断发生在「全部处理完、标记未写」边界时，重启凭备份目录里的停用记录
        # 补写标记，不重复处理任何房间。
        if report["processed"] or (accumulated and not marker_path.exists()):
            legacy_cutover_fault_pause("before-marker", self.saves_dir, "marker")
            self._write_backup_json(marker_path, {
                "completedAt": time.time(),
                "processedGameIds": accumulated,
                "processedCount": len(accumulated),
            })
            report["markerWritten"] = True
            print(f"旧房间切换完成：共停用 {len(accumulated)} 个旧房间，"
                  f"完成记录 {marker_path.resolve()}。", flush=True)
        return report

    # ---- recovery & retention -----------------------------------------

    def restore(self) -> list[Room]:
        """Load persisted rooms after a restart; finished rooms are pruned to the cap."""
        # 首次启用账号机制时先完成旧房间切换（工单 24）：旧等待/进行房间备份后
        # 停用，绝不恢复成可加入的房间（含切换失败的：原文件保留但同样不可用）。
        self.cutover_legacy_rooms()
        for meta_path in sorted(self.saves_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            code, game_id = meta.get("code"), meta.get("gameId")
            if not code or not game_id:
                continue
            if "hostAccountId" not in meta and meta.get("status", "waiting") != "ended":
                continue  # 旧免账号未结束房：只备份停用，不恢复
            try:
                engine = load_game(self.saves_dir / f"{game_id}.json.gz")
            except (SaveError, OSError):
                continue
            self.rooms[code] = Room(
                code=code,
                game_id=game_id,
                host_account_id=meta.get("hostAccountId", ""),
                seat_accounts=meta.get("seatAccounts", {}),
                locked=bool(meta.get("locked", False)),
                status=meta.get("status", "waiting"),
                engine=engine,
                created_at=float(meta.get("createdAt", 0.0)),
                finished_at=meta.get("finishedAt"),
                host_player_id=meta.get("hostPlayerId"),
                window_deadline=meta.get("windowDeadline"),
                window_stage=meta.get("windowStage"),
            )
            # 工单 22：房间从活动存档恢复 = 它的关闭从未提交。清掉中断尝试
            # 留下的 stale 关闭记录，避免该房之后消失时被误报成已关闭。
            self._discard_stale_closure(game_id)
        self._prune_finished()
        return list(self.rooms.values())

    def _prune_finished(self) -> None:
        finished = sorted(
            (room for room in self.rooms.values() if room.status == "ended"),
            key=lambda room: room.finished_at or 0.0,
        )
        for room in finished[:-FINISHED_GAMES_TO_KEEP]:
            for path in (self._save_path(room), self._meta_path(room)):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            del self.rooms[room.code]

    # ---- replay --------------------------------------------------------

    def replay(self, room: Room) -> list[dict[str, Any]]:
        """Public (spectator) projections at each command boundary, for the replay UI."""
        player = ReplayPlayer(create_save_document(room.engine))
        steps: list[dict[str, Any]] = []
        while player.step() is not None:
            steps.append(project_state(player.engine.state, None))
        return steps

    # ---- helpers -------------------------------------------------------

    def _new_code(self) -> str:
        for _ in range(1000):
            code = f"{secrets.randbelow(10 ** 6):06d}"
            if code not in self.rooms:
                return code
        raise RuntimeError("could not allocate a unique room code")
