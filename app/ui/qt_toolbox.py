import os
import json
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta, time as dt_time
from dataclasses import dataclass

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    NavigationItemPosition,
    PrimaryPushButton,
    SpinBox,
    SubtitleLabel,
    SegmentedWidget,
    TextEdit,
    Theme,
    setTheme,
)

from tools.danqing.entry import run as run_danqing


def _read_json(file_path: str, default):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(file_path: str, data):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, file_path)


def _daily_cycle_start(now: datetime) -> datetime:
    effective = now - timedelta(hours=7)
    cycle_date = effective.date()
    return datetime.combine(cycle_date, dt_time(7, 0))


def _weekly_cycle_start(now: datetime) -> datetime:
    effective = now - timedelta(hours=7)
    days_since_wed = (effective.weekday() - 2) % 7
    cycle_date = effective.date() - timedelta(days=days_since_wed)
    return datetime.combine(cycle_date, dt_time(7, 0))


def _next_daily_reset(now: datetime) -> datetime:
    today_reset = datetime.combine(now.date(), dt_time(7, 0))
    if now < today_reset:
        return today_reset
    return today_reset + timedelta(days=1)


def _next_weekly_reset(now: datetime) -> datetime:
    anchor = datetime.combine(now.date(), dt_time(7, 0))
    days_until_wed = (2 - now.weekday()) % 7
    candidate = anchor + timedelta(days=days_until_wed)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate


def _format_time_left(now: datetime, target: datetime) -> str:
    diff = target - now
    total_minutes = max(0, int(diff.total_seconds() // 60))
    days = total_minutes // (60 * 24)
    hours = (total_minutes % (60 * 24)) // 60
    minutes = total_minutes % 60
    if days > 0:
        return f"{days}天 {hours}小时"
    return f"{hours}小时 {minutes}分"


ACTIVITY_CALENDAR_TASKS = [
    {
        "id": "guild_meditate",
        "name": "帮派打坐&补灵",
        "type": "daily",
        "schedule": [
            {"day": 1, "time": "12:00"},
            {"day": 2, "time": "12:00"},
            {"day": 3, "time": "12:00"},
            {"day": 4, "time": "12:00"},
            {"day": 5, "time": "12:00"},
            {"day": 6, "time": "12:00"},
            {"day": 7, "time": "12:00"},
        ],
    },
    {
        "id": "pvp_tian_xi",
        "name": "天玺",
        "type": "display_only",
        "schedule": [{"day": 1, "time": "19:00"}, {"day": 3, "time": "19:00"}, {"day": 5, "time": "19:00"}],
    },
    {
        "id": "world_boss",
        "name": "世界BOSS",
        "type": "once_weekly",
        "schedule": [{"day": 2, "time": "19:00"}, {"day": 4, "time": "19:00"}, {"day": 6, "time": "19:00"}],
    },
    {"id": "pvp_luan_wu", "name": "乱武", "type": "unlimited", "schedule": [{"day": 2, "time": "20:00"}, {"day": 4, "time": "20:00"}]},
    {
        "id": "guild_league",
        "name": "帮派联赛",
        "type": "unlimited",
        "schedule": [{"day": 5, "time": "20:00"}, {"day": 5, "time": "21:00"}],
    },
    {
        "id": "hong_jun",
        "name": "鸿钧",
        "type": "unlimited",
        "schedule": [{"day": 6, "time": "13:00"}, {"day": 6, "time": "20:00"}, {"day": 7, "time": "13:00"}, {"day": 7, "time": "20:00"}],
    },
]

WEEK_DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

GAME_TASK_MANAGER_DEFAULT_TASKS = {
    "daily": [
        {"id": "d1", "name": "每日签到", "type": "check"},
        {"id": "d2", "name": "帮派打坐", "type": "check"},
        {"id": "d3", "name": "单双爬塔", "type": "check"},
    ],
    "weekly": [
        {
            "id": "w_map",
            "name": "大地图活动",
            "type": "group",
            "subTasks": [
                {"id": "w1", "name": "世界boss", "total": 1},
                {"id": "w2", "name": "邪枭", "total": 3},
                {"id": "w12", "name": "风云任务", "total": 1},
            ],
        },
        {
            "id": "w_wuxiangling",
            "name": "无相岭活动",
            "type": "group",
            "subTasks": [
                {"id": "w3", "name": "光头boss", "total": 1},
                {"id": "w4", "name": "大老虎", "total": 2},
                {"id": "w5", "name": "小老虎", "total": 5},
                {"id": "w17", "name": "轮回乱境", "total": 6},
            ],
        },
        {
            "id": "w_guild",
            "name": "帮派活动",
            "type": "group",
            "subTasks": [
                {"id": "w6", "name": "钓鱼", "total": 1},
                {"id": "w7", "name": "联赛", "total": 2},
                {"id": "w8", "name": "BOSS", "total": 1},
            ],
        },
        {
            "id": "w_leisure",
            "name": "休闲活动",
            "type": "group",
            "subTasks": [
                {"id": "w9", "name": "钓鱼", "total": 1},
                {"id": "w10", "name": "宠物boss", "total": 1},
                {"id": "w11", "name": "鸿雁行", "total": 1},
                {"id": "w18", "name": "挖宝", "total": 50},
            ],
        },
        {
            "id": "w_pvp",
            "name": "PVP活动",
            "type": "group",
            "subTasks": [
                {"id": "w13", "name": "乱武", "total": 1},
                {"id": "w14", "name": "天玺", "total": 1},
                {"id": "w15", "name": "鸿钧", "total": 1},
                {"id": "w16", "name": "北荒", "total": 1},
            ],
        },
    ],
}


class RiliStorage:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.task_manager_path = os.path.join(self.storage_dir, "game-task-manager-v1.json")
        self.activity_calendar_path = os.path.join(self.storage_dir, "activity-calendar-v1.json")

    def load_task_manager(self) -> dict:
        raw = _read_json(self.task_manager_path, {})
        return raw if isinstance(raw, dict) else {}

    def save_task_manager(self, data: dict):
        _write_json(self.task_manager_path, data)

    def load_activity_calendar(self) -> dict:
        raw = _read_json(self.activity_calendar_path, {})
        return raw if isinstance(raw, dict) else {}

    def save_activity_calendar(self, data: dict):
        _write_json(self.activity_calendar_path, data)


@dataclass(frozen=True)
class DanqingParams:
    deck_ids: list[str]
    level: int
    max_time: float
    seed: int | None


class DanqingWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, params: DanqingParams):
        super().__init__()
        self.params = params

    def run(self):
        started_at = time.time()
        self.log.emit(
            f"开始运行：deck={self.params.deck_ids} level={self.params.level} time={int(self.params.max_time)}s seed={self.params.seed if self.params.seed is not None else '默认'}"
        )
        try:
            result = run_danqing(
                self.params.deck_ids,
                level=self.params.level,
                max_time=self.params.max_time,
                seed=self.params.seed,
            )
            payload = json.dumps(result, ensure_ascii=False, indent=2)
            elapsed = time.time() - started_at
            self.log.emit(f"运行完成：{elapsed:.2f}s")
            self.finished.emit(payload)
        except Exception:
            err = traceback.format_exc()
            self.log.emit(err.rstrip())
            self.failed.emit(err)


class DanqingInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("danqing")
        self._thread: QThread | None = None
        self._worker: DanqingWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        title = SubtitleLabel("丹青模拟器")
        desc = BodyLabel("输入卡组 ID，运行本地计算并查看结果")
        root.addWidget(title)
        root.addWidget(desc)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        form_card = CardWidget()
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.deck = LineEdit()
        self.deck.setText("yanhong,wenmin,linfeng")
        self.deck.setPlaceholderText("卡组ID（逗号分隔）")
        row1.addWidget(self.deck, 1)
        form_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.level = SpinBox()
        self.level.setRange(0, 6)
        self.level.setValue(6)
        self.level.setPrefix("等级 ")
        row2.addWidget(self.level, 0)
        self.max_time = SpinBox()
        self.max_time.setRange(10, 600)
        self.max_time.setValue(180)
        self.max_time.setSuffix(" 秒")
        row2.addWidget(self.max_time, 0)
        self.seed = LineEdit()
        self.seed.setPlaceholderText("随机种子（可空）")
        row2.addWidget(self.seed, 1)
        form_layout.addLayout(row2)

        self.run_btn = PrimaryPushButton("开始")
        self.run_btn.clicked.connect(self._on_run_clicked)
        form_layout.addWidget(self.run_btn, 0, Qt.AlignmentFlag.AlignLeft)

        top_layout.addWidget(form_card, 0)

        self.output = TextEdit()
        self.output.setReadOnly(True)
        top_layout.addWidget(self.output, 1)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)

        bottom_layout.addWidget(BodyLabel("运行日志"), 0)
        self.log = TextEdit()
        self.log.setReadOnly(True)
        bottom_layout.addWidget(self.log, 1)

        splitter.addWidget(top)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

    def _append_log(self, message: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {message}")

    def _on_run_clicked(self):
        if self._thread is not None:
            return

        raw = self.deck.text().strip()
        deck_ids = [x.strip() for x in raw.split(",") if x.strip()]
        level = int(self.level.value())
        max_time = float(self.max_time.value())

        seed_raw = self.seed.text().strip()
        seed = None
        if seed_raw:
            try:
                seed = int(seed_raw)
            except Exception:
                seed = None

        params = DanqingParams(deck_ids=deck_ids, level=level, max_time=max_time, seed=seed)

        self.run_btn.setEnabled(False)
        self.output.clear()
        self._append_log("准备运行…")
        InfoBar.info("开始", "丹青模拟器正在运行", parent=self, position=InfoBarPosition.TOP, duration=1500)

        thread = QThread(self)
        worker = DanqingWorker(params)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log.connect(self._append_log)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_worker_finished(self, payload: str):
        self.output.setPlainText(payload)
        InfoBar.success("完成", "运行结束", parent=self, position=InfoBarPosition.TOP, duration=1500)

    def _on_worker_failed(self, err: str):
        self.output.setPlainText(err)
        InfoBar.error("失败", "运行出错，请看日志/结果", parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _on_thread_finished(self):
        self.run_btn.setEnabled(True)
        self._thread = None
        self._worker = None


class OfflineGameTaskManager(QWidget):
    def __init__(self, storage: RiliStorage, parent=None):
        super().__init__(parent=parent)
        self.storage = storage
        self.data = {}
        self.roles: list[dict] = []
        self.active_role_id: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        timers_card = CardWidget()
        timers_layout = QVBoxLayout(timers_card)
        timers_layout.setContentsMargins(16, 16, 16, 16)
        timers_layout.setSpacing(6)
        timers_layout.addWidget(BodyLabel("距离日常刷新（07:00）"), 0)
        self.daily_timer = BodyLabel("")
        timers_layout.addWidget(self.daily_timer, 0)
        timers_layout.addWidget(BodyLabel("距离周常刷新（周三 07:00）"), 0)
        self.weekly_timer = BodyLabel("")
        timers_layout.addWidget(self.weekly_timer, 0)
        root.addWidget(timers_card, 0)

        role_card = CardWidget()
        role_layout = QGridLayout(role_card)
        role_layout.setContentsMargins(16, 16, 16, 16)
        role_layout.setHorizontalSpacing(10)
        role_layout.setVerticalSpacing(10)

        role_layout.addWidget(BodyLabel("当前角色"), 0, 0, 1, 1)
        self.role_combo = QComboBox()
        role_layout.addWidget(self.role_combo, 0, 1, 1, 3)

        self.rename_input = LineEdit()
        self.rename_input.setPlaceholderText("输入新角色名")
        role_layout.addWidget(self.rename_input, 1, 1, 1, 2)
        self.rename_btn = PrimaryPushButton("改名")
        role_layout.addWidget(self.rename_btn, 1, 3, 1, 1)

        self.new_role_input = LineEdit()
        self.new_role_input.setPlaceholderText("新增角色名")
        role_layout.addWidget(self.new_role_input, 2, 1, 1, 2)
        self.add_role_btn = PrimaryPushButton("新增")
        role_layout.addWidget(self.add_role_btn, 2, 3, 1, 1)

        self.delete_role_btn = QPushButton("删除当前角色")
        role_layout.addWidget(self.delete_role_btn, 3, 1, 1, 3)

        root.addWidget(role_card, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_inner = QWidget()
        self.scroll.setWidget(self.scroll_inner)
        self.scroll_layout = QVBoxLayout(self.scroll_inner)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)
        root.addWidget(self.scroll, 1)

        self.role_combo.currentIndexChanged.connect(self._on_role_changed)
        self.add_role_btn.clicked.connect(self._add_role)
        self.rename_btn.clicked.connect(self._rename_role)
        self.delete_role_btn.clicked.connect(self._delete_role)

        self._load()
        self._render_all()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_timers)
        self._timer.start(60_000)
        self._refresh_timers()

    def _generate_id(self) -> str:
        return uuid.uuid4().hex

    def _create_new_role(self, name: str) -> dict:
        return {
            "id": self._generate_id(),
            "name": name,
            "dailyTasks": [{"id": t["id"], "name": t["name"], "type": t.get("type", "check"), "completed": False} for t in GAME_TASK_MANAGER_DEFAULT_TASKS["daily"]],
            "weeklyTasks": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "type": t.get("type", ""),
                    "subTasks": [{"id": s["id"], "name": s["name"], "total": int(s["total"]), "completed": 0} for s in t.get("subTasks", [])],
                }
                for t in GAME_TASK_MANAGER_DEFAULT_TASKS["weekly"]
            ],
        }

    def _sync_role(self, role: dict) -> dict:
        daily_by_id = {t.get("id"): t for t in role.get("dailyTasks", []) if isinstance(t, dict)}
        weekly_by_id = {t.get("id"): t for t in role.get("weeklyTasks", []) if isinstance(t, dict)}

        synced_daily = []
        for def_task in GAME_TASK_MANAGER_DEFAULT_TASKS["daily"]:
            saved = daily_by_id.get(def_task["id"])
            synced_daily.append(
                {
                    "id": def_task["id"],
                    "name": def_task["name"],
                    "type": def_task.get("type", "check"),
                    "completed": bool(saved.get("completed")) if isinstance(saved, dict) else False,
                }
            )

        synced_weekly = []
        for def_task in GAME_TASK_MANAGER_DEFAULT_TASKS["weekly"]:
            saved = weekly_by_id.get(def_task["id"])
            if def_task.get("type") == "group":
                saved_group = saved if isinstance(saved, dict) else {}
                saved_sub_map = {s.get("id"): s for s in saved_group.get("subTasks", []) if isinstance(s, dict)}
                sub_tasks = []
                for sub in def_task.get("subTasks", []):
                    saved_sub = saved_sub_map.get(sub["id"])
                    completed = int(saved_sub.get("completed")) if isinstance(saved_sub, dict) else 0
                    sub_tasks.append({"id": sub["id"], "name": sub["name"], "total": int(sub["total"]), "completed": completed})
                synced_weekly.append({"id": def_task["id"], "name": def_task["name"], "type": "group", "subTasks": sub_tasks})
            else:
                completed = int(saved.get("completed")) if isinstance(saved, dict) else 0
                synced_weekly.append({"id": def_task["id"], "name": def_task["name"], "type": def_task.get("type", ""), "total": int(def_task.get("total", 1)), "completed": completed})

        return {"id": role.get("id") or self._generate_id(), "name": role.get("name") or "未命名", "dailyTasks": synced_daily, "weeklyTasks": synced_weekly}

    def _apply_resets_if_needed(self):
        now = datetime.now()
        current_daily = _daily_cycle_start(now).isoformat()
        current_weekly = _weekly_cycle_start(now).isoformat()
        meta = self.data.get("meta") if isinstance(self.data.get("meta"), dict) else {}

        changed = False
        if meta.get("dailyCycleStart") != current_daily:
            for role in self.roles:
                for t in role.get("dailyTasks", []):
                    t["completed"] = False
            meta["dailyCycleStart"] = current_daily
            changed = True

        if meta.get("weeklyCycleStart") != current_weekly:
            for role in self.roles:
                for t in role.get("weeklyTasks", []):
                    if t.get("type") == "group":
                        for s in t.get("subTasks", []):
                            s["completed"] = 0
                    else:
                        t["completed"] = 0
            meta["weeklyCycleStart"] = current_weekly
            changed = True

        if changed:
            self.data["meta"] = meta
            self._save()

    def _load(self):
        raw = self.storage.load_task_manager()
        roles = raw.get("roles") if isinstance(raw.get("roles"), list) else []
        self.roles = [self._sync_role(r) for r in roles if isinstance(r, dict)]
        self.active_role_id = raw.get("activeRoleId") if isinstance(raw.get("activeRoleId"), str) else None
        if not self.roles:
            role = self._create_new_role("默认角色")
            self.roles = [role]
            self.active_role_id = role["id"]
        if self.active_role_id not in {r["id"] for r in self.roles}:
            self.active_role_id = self.roles[0]["id"]

        self.data = {"roles": self.roles, "activeRoleId": self.active_role_id, "meta": raw.get("meta", {})}
        self._apply_resets_if_needed()

    def _save(self):
        payload = {"roles": self.roles, "activeRoleId": self.active_role_id, "meta": self.data.get("meta", {})}
        self.storage.save_task_manager(payload)

    def _render_all(self):
        self._reload_role_combo()
        self._render_tasks()

    def _reload_role_combo(self):
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        selected_index = 0
        for idx, role in enumerate(self.roles):
            self.role_combo.addItem(role["name"], role["id"])
            if role["id"] == self.active_role_id:
                selected_index = idx
        self.role_combo.setCurrentIndex(selected_index)
        self.role_combo.blockSignals(False)

    def _get_active_role(self) -> dict | None:
        for r in self.roles:
            if r["id"] == self.active_role_id:
                return r
        return None

    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _render_tasks(self):
        self._clear_layout(self.scroll_layout)
        role = self._get_active_role()
        if role is None:
            self.scroll_layout.addWidget(BodyLabel("没有可用角色"))
            self.scroll_layout.addStretch(1)
            return

        daily_card = CardWidget()
        daily_layout = QVBoxLayout(daily_card)
        daily_layout.setContentsMargins(16, 16, 16, 16)
        daily_layout.setSpacing(10)
        daily_layout.addWidget(SubtitleLabel("每日必做"), 0)
        for task in role.get("dailyTasks", []):
            cb = QCheckBox(task.get("name", ""))
            cb.blockSignals(True)
            cb.setChecked(bool(task.get("completed")))
            cb.blockSignals(False)
            cb.stateChanged.connect(lambda _s, tid=task.get("id"): self._toggle_daily_task(tid))
            daily_layout.addWidget(cb, 0)
        self.scroll_layout.addWidget(daily_card, 0)

        weekly_card = CardWidget()
        weekly_layout = QVBoxLayout(weekly_card)
        weekly_layout.setContentsMargins(16, 16, 16, 16)
        weekly_layout.setSpacing(10)
        weekly_layout.addWidget(SubtitleLabel("每周必做"), 0)

        for task in role.get("weeklyTasks", []):
            if task.get("type") == "group":
                group_card = CardWidget()
                group_layout = QVBoxLayout(group_card)
                group_layout.setContentsMargins(12, 12, 12, 12)
                group_layout.setSpacing(8)
                subs = task.get("subTasks", [])
                done = len([s for s in subs if int(s.get("completed", 0)) >= int(s.get("total", 1))])
                group_layout.addWidget(BodyLabel(f"{task.get('name', '')}（{done}/{len(subs)}）"), 0)

                for sub in subs:
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(10)
                    row_layout.addWidget(QLabel(sub.get("name", "")), 1)
                    total = int(sub.get("total", 1))
                    completed = int(sub.get("completed", 0))
                    if total == 1:
                        cb = QCheckBox("")
                        cb.blockSignals(True)
                        cb.setChecked(completed >= 1)
                        cb.blockSignals(False)
                        cb.stateChanged.connect(
                            lambda _s, gid=task.get("id"), sid=sub.get("id"): self._set_group_subtask(gid, sid, 1)
                        )
                        row_layout.addWidget(cb, 0)
                    else:
                        minus = QPushButton("-")
                        plus = QPushButton("+")
                        count = QLabel(f"{completed}/{total}")
                        minus.clicked.connect(lambda _c=False, gid=task.get("id"), sid=sub.get("id"): self._change_group_subtask(gid, sid, -1))
                        plus.clicked.connect(lambda _c=False, gid=task.get("id"), sid=sub.get("id"): self._change_group_subtask(gid, sid, 1))
                        row_layout.addWidget(minus, 0)
                        row_layout.addWidget(count, 0)
                        row_layout.addWidget(plus, 0)
                    group_layout.addWidget(row, 0)

                weekly_layout.addWidget(group_card, 0)
                continue

            total = int(task.get("total", 1))
            completed = int(task.get("completed", 0))
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            row_layout.addWidget(QLabel(task.get("name", "")), 1)
            if total == 1:
                cb = QCheckBox("")
                cb.blockSignals(True)
                cb.setChecked(completed >= 1)
                cb.blockSignals(False)
                cb.stateChanged.connect(lambda _s, tid=task.get("id"): self._set_weekly_task(tid, 1))
                row_layout.addWidget(cb, 0)
            else:
                minus = QPushButton("-")
                plus = QPushButton("+")
                count = QLabel(f"{completed}/{total}")
                minus.clicked.connect(lambda _c=False, tid=task.get("id"): self._change_weekly_task(tid, -1))
                plus.clicked.connect(lambda _c=False, tid=task.get("id"): self._change_weekly_task(tid, 1))
                row_layout.addWidget(minus, 0)
                row_layout.addWidget(count, 0)
                row_layout.addWidget(plus, 0)
            weekly_layout.addWidget(row, 0)

        self.scroll_layout.addWidget(weekly_card, 0)
        self.scroll_layout.addStretch(1)

    def _refresh_timers(self):
        now = datetime.now()
        self.daily_timer.setText(_format_time_left(now, _next_daily_reset(now)))
        self.weekly_timer.setText(_format_time_left(now, _next_weekly_reset(now)))
        self._apply_resets_if_needed()

    def _on_role_changed(self, index: int):
        role_id = self.role_combo.itemData(index)
        if isinstance(role_id, str) and role_id:
            self.active_role_id = role_id
            self._save()
            self._render_tasks()

    def _add_role(self):
        name = self.new_role_input.text().strip()
        if not name:
            InfoBar.warning("提示", "请先输入角色名", parent=self, position=InfoBarPosition.TOP, duration=1500)
            return
        role = self._create_new_role(name)
        self.roles.append(role)
        self.active_role_id = role["id"]
        self.new_role_input.clear()
        self._save()
        self._render_all()

    def _rename_role(self):
        role = self._get_active_role()
        if role is None:
            return
        name = self.rename_input.text().strip()
        if not name:
            InfoBar.warning("提示", "请先输入新角色名", parent=self, position=InfoBarPosition.TOP, duration=1500)
            return
        role["name"] = name
        self.rename_input.clear()
        self._save()
        self._reload_role_combo()

    def _delete_role(self):
        if len(self.roles) <= 1:
            InfoBar.warning("提示", "至少保留一个角色", parent=self, position=InfoBarPosition.TOP, duration=1500)
            return
        role = self._get_active_role()
        if role is None:
            return
        self.roles = [r for r in self.roles if r["id"] != role["id"]]
        self.active_role_id = self.roles[0]["id"] if self.roles else None
        self._save()
        self._render_all()

    def _toggle_daily_task(self, task_id: str | None):
        if not task_id:
            return
        role = self._get_active_role()
        if role is None:
            return
        for t in role.get("dailyTasks", []):
            if t.get("id") == task_id:
                t["completed"] = not bool(t.get("completed"))
                break
        self._save()
        self._render_tasks()

    def _find_weekly_task(self, role: dict, task_id: str) -> dict | None:
        for t in role.get("weeklyTasks", []):
            if t.get("id") == task_id:
                return t
        return None

    def _change_weekly_task(self, task_id: str | None, delta: int):
        if not task_id:
            return
        role = self._get_active_role()
        if role is None:
            return
        task = self._find_weekly_task(role, task_id)
        if task is None:
            return
        total = int(task.get("total", 1))
        current = int(task.get("completed", 0))
        task["completed"] = max(0, min(total, current + int(delta)))
        self._save()
        self._render_tasks()

    def _set_weekly_task(self, task_id: str | None, value: int):
        if not task_id:
            return
        role = self._get_active_role()
        if role is None:
            return
        task = self._find_weekly_task(role, task_id)
        if task is None:
            return
        task["completed"] = 0 if int(task.get("completed", 0)) >= value else value
        self._save()
        self._render_tasks()

    def _find_group_subtask(self, role: dict, group_id: str, sub_id: str) -> tuple[dict | None, dict | None]:
        for t in role.get("weeklyTasks", []):
            if t.get("id") != group_id:
                continue
            for s in t.get("subTasks", []):
                if s.get("id") == sub_id:
                    return t, s
        return None, None

    def _change_group_subtask(self, group_id: str | None, sub_id: str | None, delta: int):
        if not group_id or not sub_id:
            return
        role = self._get_active_role()
        if role is None:
            return
        _, sub = self._find_group_subtask(role, group_id, sub_id)
        if sub is None:
            return
        total = int(sub.get("total", 1))
        current = int(sub.get("completed", 0))
        sub["completed"] = max(0, min(total, current + int(delta)))
        self._save()
        self._render_tasks()

    def _set_group_subtask(self, group_id: str | None, sub_id: str | None, value: int):
        if not group_id or not sub_id:
            return
        role = self._get_active_role()
        if role is None:
            return
        _, sub = self._find_group_subtask(role, group_id, sub_id)
        if sub is None:
            return
        sub["completed"] = 0 if int(sub.get("completed", 0)) >= value else value
        self._save()
        self._render_tasks()


class OfflineActivityCalendar(QWidget):
    def __init__(self, storage: RiliStorage, parent=None):
        super().__init__(parent=parent)
        self.storage = storage
        self.completed: dict[str, bool] = {}
        self.current_week_start: datetime = datetime.now()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(BodyLabel("点击任务可标记完成/取消完成"), 1)
        self.reset_btn = PrimaryPushButton("重置本周进度")
        header_layout.addWidget(self.reset_btn, 0)
        root.addWidget(header, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inner = QWidget()
        self.scroll.setWidget(self.inner)
        self.inner_layout = QHBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_layout.setSpacing(12)
        root.addWidget(self.scroll, 1)

        self.reset_btn.clicked.connect(self._reset_all)

        self._load()
        self._render()

    def _load(self):
        raw = self.storage.load_activity_calendar()
        completed = raw.get("completed") if isinstance(raw.get("completed"), dict) else {}
        self.completed = {str(k): bool(v) for k, v in completed.items()}

        now = datetime.now()
        day = now.isoweekday()
        monday = now - timedelta(days=day - 1)
        self.current_week_start = datetime.combine(monday.date(), dt_time(0, 0))

    def _save(self):
        payload = {"completed": self.completed, "lastUpdated": datetime.now().isoformat()}
        self.storage.save_activity_calendar(payload)

    def _task_key(self, task_id: str, day_index: int, time_index: int) -> str:
        task = next((t for t in ACTIVITY_CALENDAR_TASKS if t["id"] == task_id), None)
        if task is None:
            return task_id
        if task.get("type") == "once_weekly":
            return f"weekly_{task_id}"
        return f"{task_id}_d{day_index}_t{time_index}"

    def _tasks_for_day(self, day_index: int) -> list[dict]:
        day_tasks = []
        for task in ACTIVITY_CALENDAR_TASKS:
            schedule = task.get("schedule", [])
            for idx, slot in enumerate(schedule):
                if int(slot.get("day")) == day_index:
                    day_tasks.append(
                        {
                            "id": task["id"],
                            "name": task["name"],
                            "type": task.get("type", ""),
                            "time": slot.get("time", ""),
                            "timeIndex": idx,
                        }
                    )

        def sort_key(x: dict):
            t = str(x.get("time", ""))
            if t == "全天":
                return ("99:99", x.get("name", ""))
            return (t, x.get("name", ""))

        day_tasks.sort(key=sort_key)
        return day_tasks

    def _day_date_text(self, offset: int) -> str:
        d = self.current_week_start + timedelta(days=offset)
        return f"{d.month}/{d.day}"

    def _clear_layout(self, layout: QHBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _render(self):
        self._clear_layout(self.inner_layout)
        today = datetime.now().isoweekday()

        for i in range(7):
            day_index = i + 1
            card = CardWidget()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 14, 14, 14)
            card_layout.setSpacing(8)

            title = WEEK_DAYS[i]
            if day_index == today:
                title = f"{title}（今天）"
            card_layout.addWidget(SubtitleLabel(title), 0)
            card_layout.addWidget(BodyLabel(self._day_date_text(i)), 0)

            tasks = self._tasks_for_day(day_index)
            if not tasks:
                card_layout.addWidget(BodyLabel("无活动"), 0)
                card_layout.addStretch(1)
                self.inner_layout.addWidget(card, 0)
                continue

            for t in tasks:
                is_display = t.get("type") == "display_only"
                key = self._task_key(t["id"], day_index, int(t["timeIndex"]))
                checked = bool(self.completed.get(key))
                label = f"{t.get('time', '')}  {t.get('name', '')}".strip()
                if is_display:
                    card_layout.addWidget(BodyLabel(label), 0)
                    continue
                cb = QCheckBox(label)
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
                cb.stateChanged.connect(lambda _s, k=key: self._toggle(k))
                card_layout.addWidget(cb, 0)

            card_layout.addStretch(1)
            self.inner_layout.addWidget(card, 0)

        self.inner_layout.addStretch(1)

    def _toggle(self, key: str):
        self.completed[key] = not bool(self.completed.get(key))
        self._save()
        self._render()

    def _reset_all(self):
        self.completed = {}
        self._save()
        InfoBar.success("完成", "已重置本周进度", parent=self, position=InfoBarPosition.TOP, duration=1500)
        self._render()


class RiliInterface(QWidget):
    def __init__(self, storage_dir: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("rili")
        self.storage = RiliStorage(storage_dir=storage_dir)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        root.addWidget(SubtitleLabel("游戏日历"))
        root.addWidget(BodyLabel("离线版：不需要联网也能用"))

        self.segment = SegmentedWidget()
        self.segment.addItem("task_manager", "任务管理", onClick=lambda: self.open("task_manager"), icon=FluentIcon.DOCUMENT)
        self.segment.addItem("activity_calendar", "活动日历", onClick=lambda: self.open("activity_calendar"), icon=FluentIcon.CALENDAR)
        root.addWidget(self.segment, 0)

        self.pages = {
            "task_manager": OfflineGameTaskManager(storage=self.storage, parent=self),
            "activity_calendar": OfflineActivityCalendar(storage=self.storage, parent=self),
        }
        self.stack = QWidget()
        self.stack_layout = QVBoxLayout(self.stack)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.stack_layout.setSpacing(0)
        root.addWidget(self.stack, 1)

        self.segment.setCurrentItem("task_manager")
        self.open("task_manager")

    def open(self, key: str):
        widget = self.pages.get(key)
        if widget is None:
            return
        while self.stack_layout.count():
            item = self.stack_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self.stack_layout.addWidget(widget, 1)


class PlaceholderInterface(QWidget):
    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel(title))
        layout.addWidget(BodyLabel(desc))
        layout.addStretch(1)


class MainWindow(FluentWindow):
    def __init__(self, app_name: str, version: str, rili_storage_dir: str):
        super().__init__()
        self.setWindowTitle(f"{app_name} v{version}")
        self.resize(1180, 720)

        danqing = DanqingInterface(self)
        self.addSubInterface(danqing, FluentIcon.APPLICATION, "丹青模拟器", position=NavigationItemPosition.TOP)

        rili = RiliInterface(storage_dir=rili_storage_dir, parent=self)
        self.addSubInterface(rili, FluentIcon.CALENDAR, "游戏日历", position=NavigationItemPosition.TOP)

        webview_placeholder = PlaceholderInterface("WebView 小工具", "后续会接入 WebView 工具", self)
        webview_placeholder.setObjectName("webview")
        self.addSubInterface(webview_placeholder, FluentIcon.GLOBE, "WebView", position=NavigationItemPosition.TOP)

        about = PlaceholderInterface("关于", f"{app_name} {version}", self)
        about.setObjectName("about")
        self.addSubInterface(about, FluentIcon.INFO, "关于", position=NavigationItemPosition.BOTTOM)


def start(app_name: str = "OK-ZhuXian World", version: str = "0.1.0"):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rili_storage_dir = os.path.join(project_root, "tools", "rili", "storage")
    w = MainWindow(app_name=app_name, version=version, rili_storage_dir=rili_storage_dir)
    w.show()
    app.exec()
