import os
import json
import re
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta, time as dt_time
from dataclasses import dataclass

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot, QPointF, QRectF, QUrl
from PyQt6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QScrollArea,
    QSplitter,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
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

from tools.danqing.entry import load_cards_export, run as run_danqing
from tools.tianshu.entry import find_talents_dir as find_tianshu_talents_dir


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


def _parse_desc_lines(desc: str, max_rank: int) -> list[str]:
    if not isinstance(desc, str):
        return ["" for _ in range(max(1, int(max_rank)))]
    max_rank = max(1, int(max_rank))
    pieces = [s.strip() for s in re.split(r";\s*\n|\n|；", desc) if s and s.strip()]
    if max_rank <= 1:
        return [pieces[0] if pieces else desc]
    if len(pieces) >= max_rank:
        return pieces[:max_rank]
    first = pieces[0] if pieces else desc
    return [pieces[i] if i < len(pieces) else first for i in range(max_rank)]


def _normalize_stat(stat: dict) -> dict:
    if not isinstance(stat, dict):
        return {"key": "unknown", "label": "unknown", "value": 0, "suffix": ""}
    type_key = str(stat.get("type_key") or stat.get("type") or "unknown")
    label = str(stat.get("type") or type_key)
    display = str(stat.get("display_string") or "")
    suffix = "%" if "%" in display else ""
    value = stat.get("value", 0)
    if suffix == "%" and isinstance(value, (int, float)) and value <= 1:
        value = round(float(value) * 100, 2)
    return {"key": type_key, "label": label, "value": value, "suffix": suffix}


def _normalize_stats_by_rank(stats, max_rank: int) -> list[list[dict]]:
    max_rank = max(1, int(max_rank))
    result: list[list[dict]] = [[] for _ in range(max_rank)]
    if not isinstance(stats, list) or not stats:
        return result
    is_nested = isinstance(stats[0], list)
    normalized = stats if is_nested else [stats]
    for i in range(max_rank):
        rank_stats = normalized[i] if i < len(normalized) else (normalized[0] if normalized else [])
        if not isinstance(rank_stats, list):
            rank_stats = []
        result[i] = [_normalize_stat(s) for s in rank_stats]
    return result


def _build_tianshu_tree_data(tree_id: str, data: list[dict]) -> dict:
    first = data[0] if data else {}
    profession = str(first.get("class") or "未知")
    sub_class = str(first.get("sub_class") or "未知")

    nodes = []
    for item in data:
        tid = str(item.get("talent_point_id") or "")
        if not tid:
            continue
        max_rank = int(item.get("talent_point_max") or 1)
        row_index = int(item.get("row_index") or 0)
        col_index = int(item.get("col_index") or 0)
        nodes.append(
            {
                "id": tid,
                "name": str(item.get("talent_point_name") or tid),
                "maxRank": max_rank,
                "rowIndex": row_index,
                "colIndex": col_index,
                "x": (row_index - 1) * 120 + 60,
                "y": (col_index - 1) * 100 + 60,
                "prereqs": [],
                "descLines": _parse_desc_lines(str(item.get("talent_point_desc") or ""), max_rank),
                "statsByRank": _normalize_stats_by_rank(item.get("stats"), max_rank),
            }
        )

    prereq_map: dict[str, list[str]] = {}
    for item in data:
        parent_id = str(item.get("talent_point_id") or "")
        if not parent_id:
            continue
        for child in item.get("child") or []:
            if not isinstance(child, dict):
                continue
            child_id = str(child.get("child_id") or "")
            if not child_id:
                continue
            prereq_map.setdefault(child_id, []).append(parent_id)

    for n in nodes:
        n["prereqs"] = prereq_map.get(n["id"], [])

    max_points = sum(int(n.get("maxRank") or 1) for n in nodes)
    return {
        "id": tree_id,
        "name": f"{profession}-{sub_class}",
        "profession": profession,
        "subClass": sub_class,
        "maxPoints": max_points,
        "nodes": nodes,
    }


def _load_tianshu_data(talents_dir: str) -> tuple[dict[str, dict], list[dict]]:
    files = []
    try:
        for name in os.listdir(talents_dir):
            if re.fullmatch(r"p\d+_s\d+\.json", name):
                files.append(name)
    except Exception:
        files = []
    files.sort()

    data_map: dict[str, dict] = {}
    tree_list: list[dict] = []
    for name in files:
        tree_id = os.path.splitext(name)[0]
        raw = _read_json(os.path.join(talents_dir, name), [])
        if not isinstance(raw, list) or not raw:
            continue
        tree = _build_tianshu_tree_data(tree_id, raw)
        data_map[tree_id] = tree
        tree_list.append(
            {
                "id": tree_id,
                "name": tree.get("name", tree_id),
                "profession": tree.get("profession", "未知"),
                "subClass": tree.get("subClass", "未知"),
            }
        )
    return data_map, tree_list


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
        self.definitions_path = os.path.join(self.storage_dir, "rili-definitions-v1.json")

    def load_definitions(self) -> dict:
        raw = _read_json(self.definitions_path, {})
        return raw if isinstance(raw, dict) else {}

    def save_definitions(self, data: dict) -> None:
        _write_json(self.definitions_path, data)

    def reset_definitions(self) -> None:
        try:
            if os.path.isfile(self.definitions_path):
                os.remove(self.definitions_path)
        except Exception:
            pass

    def get_task_defaults(self) -> dict:
        defs = self.load_definitions()
        task_defaults = defs.get("taskDefaults") if isinstance(defs.get("taskDefaults"), dict) else None
        if isinstance(task_defaults, dict):
            daily = task_defaults.get("daily") if isinstance(task_defaults.get("daily"), list) else []
            weekly = task_defaults.get("weekly") if isinstance(task_defaults.get("weekly"), list) else []
            return {"daily": [x for x in daily if isinstance(x, dict)], "weekly": [x for x in weekly if isinstance(x, dict)]}
        return GAME_TASK_MANAGER_DEFAULT_TASKS

    def set_task_defaults(self, task_defaults: dict) -> None:
        if not isinstance(task_defaults, dict):
            return
        daily = task_defaults.get("daily") if isinstance(task_defaults.get("daily"), list) else []
        weekly = task_defaults.get("weekly") if isinstance(task_defaults.get("weekly"), list) else []
        payload = {"daily": [x for x in daily if isinstance(x, dict)], "weekly": [x for x in weekly if isinstance(x, dict)]}
        defs = self.load_definitions()
        defs["taskDefaults"] = payload
        self.save_definitions(defs)

    def get_activity_definitions(self) -> list[dict]:
        defs = self.load_definitions()
        activity_defs = defs.get("activityDefinitions") if isinstance(defs.get("activityDefinitions"), list) else None
        if isinstance(activity_defs, list):
            return [x for x in activity_defs if isinstance(x, dict)]
        return ACTIVITY_CALENDAR_TASKS

    def set_activity_definitions(self, activity_defs: list[dict]) -> None:
        if not isinstance(activity_defs, list):
            return
        payload = [x for x in activity_defs if isinstance(x, dict)]
        defs = self.load_definitions()
        defs["activityDefinitions"] = payload
        self.save_definitions(defs)

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


class TianshuStorage:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.path = os.path.join(self.storage_dir, "tianshu-v1.json")

    def load(self) -> dict:
        raw = _read_json(self.path, {})
        return raw if isinstance(raw, dict) else {}

    def save(self, data: dict):
        _write_json(self.path, data)


@dataclass(frozen=True)
class DanqingParams:
    deck_ids: list[str]
    level: int
    base_atk: float
    base_hp: float
    base_dps: float
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
            f"开始运行：卡牌数={len(self.params.deck_ids)} 等级={self.params.level} 攻击={int(self.params.base_atk)} 气血={int(self.params.base_hp)} 秒伤={int(self.params.base_dps)} 时长={int(self.params.max_time)}秒"
        )
        try:
            result = run_danqing(
                self.params.deck_ids,
                level=self.params.level,
                base_atk=self.params.base_atk,
                base_hp=self.params.base_hp,
                base_dps=self.params.base_dps,
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


class _DanqingBoardCard(CardWidget):
    def __init__(self, *, on_click, parent=None):
        super().__init__(parent=parent)
        self._on_click = on_click
        self._selected = False
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(0, 229, 255, 0))
        self.setGraphicsEffect(self._glow)

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        try:
            self._glow.setBlurRadius(0)
            self._glow.setColor(QColor(0, 229, 255, 0))
        except Exception:
            pass

    def _emit_click(self):
        try:
            cb = self._on_click
            if cb is not None:
                cb()
        except Exception:
            pass

    def mousePressEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self._emit_click()
        except Exception:
            pass
        return super().mousePressEvent(event)

    def enterEvent(self, event):
        try:
            self._glow.setBlurRadius(18)
            self._glow.setColor(QColor(0, 229, 255, 140))
        except Exception:
            pass
        return super().enterEvent(event)

    def leaveEvent(self, event):
        try:
            self._glow.setBlurRadius(0)
            self._glow.setColor(QColor(0, 229, 255, 0))
        except Exception:
            pass
        return super().leaveEvent(event)


class DanqingInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("danqing")
        self._thread: QThread | None = None
        self._worker: DanqingWorker | None = None
        self._deck_history: list[str] = []
        self._cards: list[dict] = []
        self._id_to_name: dict[str, str] = {}
        self._name_to_id: dict[str, str] = {}
        self._stats_table: dict[int, list[dict]] = {}
        self._default_level = 6
        self._base_atk = 10000.0
        self._base_hp = 200000.0
        self._base_dps = 50000.0
        self._accent = "#00E5FF"
        self._bg = "#121212"
        self._panel = "#1E1E1E"
        self._card = "rgba(45,45,45,0.70)"
        self._text = "#E0E0E0"
        self._muted = "#A0A0A0"

        self._scrollbar_qss = (
            "QScrollBar:vertical{background:rgba(255,255,255,0.06);width:10px;margin:10px 3px 10px 3px;border-radius:5px;}"
            "QScrollBar::handle:vertical{background:rgba(0,229,255,0.55);min-height:28px;border-radius:5px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(0,229,255,0.80);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
            "QScrollBar:horizontal{background:rgba(255,255,255,0.06);height:10px;margin:3px 10px 3px 10px;border-radius:5px;}"
            "QScrollBar::handle:horizontal{background:rgba(0,229,255,0.55);min-width:28px;border-radius:5px;}"
            "QScrollBar::handle:horizontal:hover{background:rgba(0,229,255,0.80);}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0px;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        )

        self.setStyleSheet(f"QWidget#danqing{{background:{self._bg};}}QScrollArea{{background:transparent;}}{self._scrollbar_qss}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        title = SubtitleLabel("丹青模拟器")
        desc = BodyLabel("输入卡组 ID，运行本地计算并查看结果")
        title.setStyleSheet(f"color:{self._text};")
        desc.setStyleSheet(f"color:{self._muted};")
        root.addWidget(title)
        root.addWidget(desc)

        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(1)
        main_splitter.setStyleSheet(f"QSplitter::handle{{background:rgba(0,229,255,0.22);}}")
        root.addWidget(main_splitter, 1)

        board = QWidget()
        board_layout = QVBoxLayout(board)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(10)
        board_title = SubtitleLabel("丹青看板")
        board_title.setStyleSheet(f"color:{self._text};")
        board_layout.addWidget(board_title, 0)

        board_filter = CardWidget()
        board_filter.setStyleSheet(f"background:{self._panel};border:1px solid rgba(0,229,255,0.15);border-radius:12px;")
        board_filter_layout = QGridLayout(board_filter)
        board_filter_layout.setContentsMargins(16, 16, 16, 16)
        board_filter_layout.setHorizontalSpacing(10)
        board_filter_layout.setVerticalSpacing(8)

        search_label = BodyLabel("搜索")
        search_label.setStyleSheet(f"color:{self._text};")
        board_filter_layout.addWidget(search_label, 0, 0, 1, 1)
        self.board_search = LineEdit()
        self.board_search.setPlaceholderText("输入卡牌名或ID")
        self.board_search.setStyleSheet(
            f"QLineEdit{{background:transparent;color:{self._text};border:0;border-bottom:2px solid rgba(0,229,255,0.55);padding:6px 2px;}}"
            f"QLineEdit:focus{{border-bottom:2px solid {self._accent};}}"
        )
        board_filter_layout.addWidget(self.board_search, 0, 1, 1, 3)

        cat_label = BodyLabel("分类")
        cat_label.setStyleSheet(f"color:{self._text};")
        board_filter_layout.addWidget(cat_label, 1, 0, 1, 1)
        self.board_category = QComboBox()
        self.board_category.setStyleSheet(
            f"QComboBox{{background:{self._panel};color:{self._text};border:1px solid rgba(0,229,255,0.22);border-radius:8px;padding:6px 10px;}}"
            "QComboBox::drop-down{border:0;}"
            f"QComboBox QAbstractItemView{{background-color:{self._panel};color:{self._text};selection-background-color:rgba(0,229,255,0.18);}}"
        )
        board_filter_layout.addWidget(self.board_category, 1, 1, 1, 1)

        self.board_count = BodyLabel("")
        self.board_count.setStyleSheet(f"color:{self._muted};")
        board_filter_layout.addWidget(self.board_count, 1, 2, 1, 2)

        board_layout.addWidget(board_filter, 0)

        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.board_scroll.setStyleSheet(f"QScrollArea{{background:transparent;}}QWidget{{background:transparent;}}{self._scrollbar_qss}")
        self.board_inner = QWidget()
        self.board_inner.setStyleSheet("background:transparent;")
        self.board_scroll.setWidget(self.board_inner)
        self.board_list_layout = QVBoxLayout(self.board_inner)
        self.board_list_layout.setContentsMargins(0, 0, 0, 0)
        self.board_list_layout.setSpacing(12)
        board_layout.addWidget(self.board_scroll, 1)

        sim = QWidget()
        sim_layout = QVBoxLayout(sim)
        sim_layout.setContentsMargins(0, 0, 0, 0)
        sim_layout.setSpacing(12)
        sim_title = SubtitleLabel("仿真模拟")
        sim_title.setStyleSheet(f"color:{self._text};")
        sim_layout.addWidget(sim_title, 0)

        sim_splitter = QSplitter(Qt.Orientation.Vertical, sim)
        sim_splitter.setChildrenCollapsible(False)
        sim_splitter.setHandleWidth(1)
        sim_splitter.setStyleSheet(f"QSplitter::handle{{background:rgba(0,229,255,0.22);}}")
        sim_layout.addWidget(sim_splitter, 1)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        form_card = CardWidget()
        form_card.setStyleSheet(f"background:{self._panel};border:1px solid rgba(0,229,255,0.15);border-radius:12px;")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.deck = LineEdit()
        self.deck.setPlaceholderText("卡组（用逗号分隔，单击左侧卡片可选中/取消）")
        self.deck.setStyleSheet(
            f"QLineEdit{{background:transparent;color:{self._text};border:0;border-bottom:2px solid rgba(0,229,255,0.55);padding:6px 2px;}}"
            f"QLineEdit:focus{{border-bottom:2px solid {self._accent};}}"
        )
        row1.addWidget(self.deck, 1)
        form_layout.addLayout(row1)

        self.run_btn = PrimaryPushButton("开始")
        self.run_btn.clicked.connect(self._on_run_clicked)
        action_btn_qss = (
            f"QPushButton{{background:transparent;color:{self._accent};border:2px solid {self._accent};border-radius:10px;padding:7px 16px;font-weight:750;}}"
            f"QPushButton:hover{{background:rgba(0,229,255,0.12);}}"
            "QPushButton:pressed{background:rgba(0,229,255,0.18);}"
            "QPushButton:disabled{background:transparent;border-color:rgba(0,229,255,0.20);color:rgba(224,224,224,0.55);}"
        )
        for btn in [self.run_btn]:
            btn.setFixedHeight(36)
            btn.setFixedWidth(110)
            btn.setStyleSheet(action_btn_qss)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.base_attr_btn = QPushButton("属性设置")
        self.base_attr_btn.setIcon(FluentIcon.SETTING.icon())
        self.base_attr_btn.clicked.connect(self._show_base_attr_dialog)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_deck)
        self.history_btn = QPushButton("历史")
        self.history_btn.clicked.connect(self._show_deck_history)

        for btn in [self.base_attr_btn, self.clear_btn, self.history_btn]:
            btn.setFixedHeight(36)
            btn.setFixedWidth(110)
            btn.setStyleSheet(action_btn_qss)

        actions.addWidget(self.base_attr_btn, 0)
        actions.addWidget(self.clear_btn, 0)
        actions.addWidget(self.history_btn, 0)
        actions.addWidget(self.run_btn, 0)
        actions.addStretch(1)
        form_layout.addLayout(actions)

        top_layout.addWidget(form_card, 0)

        self.output = TextEdit()
        self.output.setReadOnly(True)
        self._output_qss_normal = (
            f"QTextEdit,QPlainTextEdit{{background:#0B0F14;color:{self._text};border:1px solid rgba(0,229,255,0.16);border-radius:12px;padding:12px;font-family:Consolas, 'Courier New', monospace;}}{self._scrollbar_qss}"
        )
        self._output_qss_hint = (
            f"QTextEdit,QPlainTextEdit{{background:#0B0F14;color:{self._muted};border:1px solid rgba(0,229,255,0.10);border-radius:12px;padding:12px;font-family:Consolas, 'Courier New', monospace;}}{self._scrollbar_qss}"
        )
        self.output.setStyleSheet(self._output_qss_hint)
        top_layout.addWidget(self.output, 1)
        self._set_output_hint()

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)

        log_title = BodyLabel("运行日志")
        log_title.setStyleSheet(f"color:{self._muted};")
        bottom_layout.addWidget(log_title, 0)
        self.log = TextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            f"QTextEdit,QPlainTextEdit{{background:#0B0F14;color:{self._muted};border:1px solid rgba(0,229,255,0.10);border-radius:12px;padding:10px;font-family:Consolas, 'Courier New', monospace;}}{self._scrollbar_qss}"
        )
        bottom_layout.addWidget(self.log, 1)

        sim_splitter.addWidget(top)
        sim_splitter.addWidget(bottom)
        sim_splitter.setStretchFactor(0, 3)
        sim_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(board)
        main_splitter.addWidget(sim)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)

        self.board_search.textChanged.connect(self._render_board)
        self.board_category.currentIndexChanged.connect(self._render_board)
        self.deck.textChanged.connect(self._render_board)
        self._load_cards()
        self._render_board()

    def _token_to_cid(self, token: str) -> str:
        t = str(token or "").strip()
        if not t:
            return ""
        if t in self._id_to_name:
            return t
        cid = self._name_to_id.get(t)
        if cid:
            return cid
        return t

    def _current_deck_ids(self) -> list[str]:
        raw = (self.deck.text() or "").replace("，", ",").strip()
        tokens = [x.strip() for x in raw.split(",") if x.strip()]
        return [self._token_to_cid(t) for t in tokens if self._token_to_cid(t)]

    def _append_log(self, message: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {message}")

    def _set_output_hint(self):
        hint = "请从左侧单击卡牌选中/取消加入卡组…\n也可以在上方输入卡牌名或ID（英文逗号分隔）"
        self.output.setStyleSheet(self._output_qss_hint)
        try:
            self.output.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except Exception:
            pass
        self.output.setPlainText(hint)

    def _on_run_clicked(self):
        if self._thread is not None:
            return

        raw = (self.deck.text() or "").replace("，", ",").strip()
        tokens = [x.strip() for x in raw.split(",") if x.strip()]
        deck_ids = []
        for t in tokens:
            if t in self._id_to_name:
                deck_ids.append(t)
                continue
            cid = self._name_to_id.get(t)
            if cid:
                deck_ids.append(cid)
                continue
            deck_ids.append(t)
        level = self._default_level
        max_time = 180.0
        seed = None

        params = DanqingParams(
            deck_ids=deck_ids,
            level=level,
            base_atk=float(self._base_atk),
            base_hp=float(self._base_hp),
            base_dps=float(self._base_dps),
            max_time=max_time,
            seed=seed,
        )

        self.run_btn.setEnabled(False)
        self.output.setStyleSheet(self._output_qss_normal)
        self.output.clear()
        try:
            self.output.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        except Exception:
            pass
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
        try:
            obj = json.loads(payload)
            if isinstance(obj, dict):
                deck = obj.get("deck")
                if isinstance(deck, list):
                    deck_text = ",".join([str(x) for x in deck if str(x).strip()])
                    if deck_text and (not self._deck_history or self._deck_history[-1] != deck_text):
                        self._deck_history.append(deck_text)
        except Exception:
            pass
        self.output.setStyleSheet(self._output_qss_normal)
        try:
            self.output.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        except Exception:
            pass
        self.output.setPlainText(self._format_result_payload(payload))
        InfoBar.success("完成", "运行结束", parent=self, position=InfoBarPosition.TOP, duration=1500)

    def _clear_deck(self):
        self.deck.setText("")

    def _show_deck_history(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("历史卡组")
        dialog.setFixedSize(520, 420)
        dialog.setStyleSheet(
            f"QDialog{{background:{self._panel};}}"
            f"QLabel{{color:{self._text};}}"
            f"QPushButton{{background:transparent;color:{self._text};border:1px solid rgba(255,255,255,0.14);border-radius:8px;padding:6px 14px;}}"
            f"QPushButton:hover{{border:1px solid {self._accent};}}"
            "QPushButton:pressed{background:rgba(0,229,255,0.10);}"
            f"{self._scrollbar_qss}"
        )

        root = QVBoxLayout(dialog)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        tip = BodyLabel("这里记录本次启动后，成功运行过的卡组（按运行时的卡牌ID保存）")
        tip.setStyleSheet(f"color:{self._muted};")
        root.addWidget(tip, 0)

        text = TextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(self._output_qss_hint)
        if not self._deck_history:
            text.setPlainText("暂无历史记录")
        else:
            lines = []
            for i, deck in enumerate(reversed(self._deck_history[-50:]), 1):
                lines.append(f"{i}. {deck}")
            text.setPlainText("\n".join(lines))
        root.addWidget(text, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close_btn = PrimaryPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btns.addWidget(close_btn, 0)
        root.addLayout(btns)

        dialog.exec()

    def _on_worker_failed(self, err: str):
        self.output.setStyleSheet(self._output_qss_normal)
        try:
            self.output.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        except Exception:
            pass
        self.output.setPlainText(err)
        InfoBar.error("失败", "运行出错，请看日志/结果", parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _on_thread_finished(self):
        self.run_btn.setEnabled(True)
        self._thread = None
        self._worker = None

    def _load_cards(self):
        try:
            raw = load_cards_export()
            cards = raw.get("cards") if isinstance(raw, dict) else None
            if not isinstance(cards, list):
                cards = []
            stats_table = raw.get("statsTable") if isinstance(raw, dict) else None
        except Exception:
            cards = []
            stats_table = None
        self._cards = [c for c in cards if isinstance(c, dict)]
        self._cards.sort(key=lambda c: (int(c.get("cost", 0) or 0), str(c.get("name", ""))))

        self._id_to_name = {}
        self._name_to_id = {}
        for c in self._cards:
            cid = str(c.get("id", "") or "").strip()
            name = str(c.get("name", "") or "").strip()
            if cid:
                self._id_to_name[cid] = name or cid
            if name and cid and name not in self._name_to_id:
                self._name_to_id[name] = cid

        self._stats_table = {}
        if isinstance(stats_table, dict):
            for k, v in stats_table.items():
                try:
                    cost_key = int(k)
                except Exception:
                    continue
                if not isinstance(v, list):
                    continue
                rows = [x for x in v if isinstance(x, dict)]
                if rows:
                    self._stats_table[cost_key] = rows

        cats = []
        seen = set()
        for c in self._cards:
            cat = c.get("category")
            if not isinstance(cat, str) or not cat:
                continue
            if cat in seen:
                continue
            seen.add(cat)
            cats.append(cat)
        cats.sort()
        self.board_category.blockSignals(True)
        self.board_category.clear()
        self.board_category.addItem("全部", None)
        cat_labels = {"human": "人族", "beast": "兽族", "item": "物品"}
        for cat in cats:
            label = cat_labels.get(cat, str(cat))
            self.board_category.addItem(label, cat)
        self.board_category.blockSignals(False)

    def _sync_default_deck_text(self):
        return

    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _add_card_to_deck(self, token: str):
        token = str(token or "").strip()
        cid = self._token_to_cid(token)
        if not cid:
            return
        existing_ids = set(self._current_deck_ids())
        if cid in existing_ids:
            InfoBar.warning("已存在", "这张卡已经在卡组里了", parent=self, position=InfoBarPosition.TOP, duration=1200)
            return
        new_name = self._id_to_name.get(cid)
        if new_name:
            existing_names = {str(self._id_to_name.get(x) or "") for x in existing_ids if x in self._id_to_name}
            if new_name in existing_names:
                InfoBar.warning("同名已存在", f"卡组里已经有「{new_name}」了", parent=self, position=InfoBarPosition.TOP, duration=1400)
                return
        display_token = new_name or cid
        raw = self.deck.text().strip()
        if not raw:
            self.deck.setText(display_token)
            return
        raw = raw.replace("，", ",")
        parts = [x.strip() for x in raw.split(",") if x.strip()]
        parts.append(display_token)
        self.deck.setText(",".join(parts))

    def _toggle_card_in_deck(self, token: str):
        cid = self._token_to_cid(token)
        if not cid:
            return
        raw = (self.deck.text() or "").replace("，", ",").strip()
        tokens = [x.strip() for x in raw.split(",") if x.strip()]
        kept = []
        removed = False
        for t in tokens:
            if not removed and self._token_to_cid(t) == cid:
                removed = True
                continue
            kept.append(t)
        if removed:
            self.deck.setText(",".join(kept))
            return
        self._add_card_to_deck(cid)

    def _parse_base_number(self, raw: str) -> float | None:
        t = str(raw or "").strip().lower()
        if not t:
            return None
        t = t.replace(",", "").replace("，", "")
        mult = 1.0
        if t.endswith(("w", "万")):
            mult = 10000.0
            t = t[:-1].strip()
        elif t.endswith(("k", "千")):
            mult = 1000.0
            t = t[:-1].strip()
        try:
            return float(t) * mult
        except Exception:
            return None

    def _show_base_attr_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("基础属性")
        dialog.setFixedWidth(420)
        dialog.setStyleSheet(
            f"QDialog{{background:{self._panel};}}"
            f"QLabel{{color:{self._text};}}"
            f"QLineEdit{{background:rgba(0,0,0,0.22);color:{self._text};border:1px solid rgba(0,229,255,0.22);border-radius:8px;padding:7px 10px;}}"
            f"QLineEdit:focus{{border:1px solid {self._accent};}}"
            f"QPushButton{{background:transparent;color:{self._text};border:1px solid rgba(255,255,255,0.14);border-radius:8px;padding:6px 14px;}}"
            f"QPushButton:hover{{border:1px solid {self._accent};}}"
            "QPushButton:pressed{background:rgba(0,229,255,0.10);}"
            f"{self._scrollbar_qss}"
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(BodyLabel("这些数值会影响仿真结果与倍率类描述的换算"), 0)

        row_atk = QHBoxLayout()
        row_atk.setSpacing(10)
        row_atk.addWidget(BodyLabel("攻击力"), 0)
        atk_input = LineEdit()
        atk_input.setText(str(int(self._base_atk)))
        row_atk.addWidget(atk_input, 1)
        layout.addLayout(row_atk)

        row_hp = QHBoxLayout()
        row_hp.setSpacing(10)
        row_hp.addWidget(BodyLabel("气血"), 0)
        hp_input = LineEdit()
        hp_input.setText(str(int(self._base_hp)))
        row_hp.addWidget(hp_input, 1)
        layout.addLayout(row_hp)

        row_dps = QHBoxLayout()
        row_dps.setSpacing(10)
        row_dps.addWidget(BodyLabel("基础秒伤"), 0)
        dps_input = LineEdit()
        dps_input.setText(str(int(self._base_dps)))
        row_dps.addWidget(dps_input, 1)
        layout.addLayout(row_dps)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        cancel_btn = QPushButton("取消")
        ok_btn = PrimaryPushButton("确认")
        btns.addWidget(cancel_btn, 0)
        btns.addWidget(ok_btn, 0)
        layout.addLayout(btns)

        cancel_btn.clicked.connect(dialog.reject)

        def _apply():
            atk = self._parse_base_number(atk_input.text())
            hp = self._parse_base_number(hp_input.text())
            dps = self._parse_base_number(dps_input.text())
            if atk is None or hp is None or dps is None or atk <= 0 or hp <= 0 or dps < 0:
                InfoBar.error("输入无效", "请填入有效数字（如 10000 / 20w / 50k）", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            self._base_atk = float(atk)
            self._base_hp = float(hp)
            self._base_dps = float(dps)
            dialog.accept()
            self._render_board()
            InfoBar.success(
                "已更新",
                f"攻击={int(self._base_atk)} 气血={int(self._base_hp)} 秒伤={int(self._base_dps)}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=1500,
            )

        ok_btn.clicked.connect(_apply)
        dialog.exec()

    def _match_card(self, card: dict, q: str, raw_category: str | None) -> bool:
        if raw_category is not None:
            if str(card.get("category", "") or "") != raw_category:
                return False
        if not q:
            return True
        terms = [t for t in re.split(r"[\s,，]+", str(q or "").strip().lower()) if t]
        if not terms:
            return True

        name = str(card.get("name", "") or "")
        cid = str(card.get("id", "") or "")
        desc = str(card.get("skillDescription", "") or "")
        tag_labels = self._display_tags(card.get("tags"))
        tags_raw = ""
        if isinstance(card.get("tags"), list):
            tags_raw = " ".join([str(x or "") for x in card.get("tags") if str(x or "").strip()])
        model_label = self._display_model_type(card)
        category_label = self._display_category(str(card.get("category", "") or ""))

        hay = " ".join([name, cid, desc, tag_labels, tags_raw, model_label, category_label]).lower()
        return all(t in hay for t in terms)

    def _display_category(self, raw: str) -> str:
        return {"human": "人族", "beast": "兽族", "item": "物品"}.get(raw, raw or "未知")

    def _display_model_type(self, card: dict) -> str:
        model = card.get("dpsModel") if isinstance(card.get("dpsModel"), dict) else {}
        t = str(model.get("type", "") or "")
        cid = str(card.get("id", "") or "")
        if not t and cid in ["zhouyixian", "tiger", "banner", "woodsword"]:
            t = "GLOBAL_MULTIPLIER"
        labels = {
            "ATTRIBUTE_CONVERSION": "属性提升",
            "ATTACK_SCALING": "攻击倍率伤害",
            "FLAT_DPS": "固定触发",
            "MECHANISM": "机制触发",
            "SYNERGY_MULTIPLIER": "联动增益",
            "SPECIAL_DMG_MULTIPLIER": "特殊伤害加成",
            "GLOBAL_MULTIPLIER": "全局加成",
            "STACK_EXPLODE": "叠层爆燃",
        }
        if not t:
            return ""
        return labels.get(t, "未知")

    def _display_tags(self, tags) -> str:
        if not isinstance(tags, list) or not tags:
            return ""
        labels = {
            "ICE_ARROW_SOURCE": "冰箭来源",
            "ICE_ARROW_SYNERGY": "冰箭联动",
            "BURN_SOURCE": "燃烧来源",
            "BURN_SYNERGY": "燃烧联动",
            "BURN_EXPLODE": "爆燃",
            "SPECIAL_DMG_BUFF": "特殊伤害提升",
            "GLOBAL_BUFF": "全局增益",
            "ATTRIBUTE": "属性",
            "CD_REDUCTION": "冷却缩减",
            "FLAT_DMG": "固定伤害",
        }
        out = []
        for t in tags:
            key = str(t or "")
            if not key:
                continue
            label = labels.get(key)
            if label:
                out.append(label)
        return "、".join(out)

    def _cost_stats_text(self, cost: int, level: int) -> str:
        rows = self._stats_table.get(int(cost)) or []
        idx = int(level)
        if idx < 0:
            idx = 0
        if idx > 6:
            idx = 6
        if idx >= len(rows):
            return ""
        row = rows[idx]
        try:
            core = int(row.get("core", 0) or 0)
            body = int(row.get("body", 0) or 0)
        except Exception:
            return ""
        if core <= 0 and body <= 0:
            return ""
        return f"核心+{core}  体+{body}"

    def _display_skill_text(self, card: dict, level: int) -> str:
        level = int(getattr(self, "_default_level", level) or level)
        desc = str(card.get("skillDescription", "") or "")
        model = card.get("dpsModel") if isinstance(card.get("dpsModel"), dict) else {}
        t = str(model.get("type", "") or "")
        cid = str(card.get("id", "") or "")
        if t != "ATTRIBUTE_CONVERSION":
            if t == "ATTACK_SCALING":
                scaling = model.get("scaling") if isinstance(model.get("scaling"), dict) else {}
                base = float(scaling.get("base", 0) or 0)
                step = float(scaling.get("step", 0) or 0)
                ratio = base + float(level) * step
                dmg = ratio * float(self._base_atk)
                params = model.get("params") if isinstance(model.get("params"), dict) else {}
                cd = params.get("cd")
                try:
                    dmg_int = int(round(dmg))
                except Exception:
                    dmg_int = None
                if dmg_int is None:
                    return self._resolve_skill_formula(desc, level)
                if cd is not None:
                    try:
                        cd_int = int(cd)
                    except Exception:
                        cd_int = cd
                    if cid == "yanhong":
                        return f"释放技能时，向目标发射一枚冰箭，造成{dmg_int:,}固定伤害（{cd_int}秒冷却）"
                    if cid == "qihao":
                        return f"召唤冰霜元素，向目标发射玄冰风暴，造成{dmg_int:,}固定伤害（{cd_int}秒冷却）"
                return self._resolve_skill_formula(desc, level)

            if t == "GLOBAL_MULTIPLIER":
                scaling = model.get("scaling") if isinstance(model.get("scaling"), dict) else {}
                base = float(scaling.get("base", 0) or 0)
                step = float(scaling.get("step", 0) or 0)
                value = base + float(level) * step
                pct = value * 100
                try:
                    pct_text = f"{pct:.2f}%"
                except Exception:
                    pct_text = ""
                if cid == "woodsword" and pct_text:
                    return f"主属性提高 {pct_text}"
                if cid in ("zhouyixian", "tiger", "banner") and pct_text:
                    return f"每装备一张同类卡片，攻击力提高 {pct_text}"
                return desc

            if t == "SPECIAL_DMG_MULTIPLIER":
                scaling = model.get("scaling") if isinstance(model.get("scaling"), dict) else {}
                base = float(scaling.get("base", 0) or 0)
                step = float(scaling.get("step", 0) or 0)
                value = base + float(level) * step
                pct = value * 100
                try:
                    pct_text = f"{pct:.0f}%"
                except Exception:
                    pct_text = ""
                if cid == "zuogui" and pct_text:
                    return f"冰箭/玄冰风暴/燃烧/脉冲造成的伤害提高 {pct_text}"
                return desc

            if t == "SYNERGY_MULTIPLIER":
                scaling = model.get("scaling") if isinstance(model.get("scaling"), dict) else {}
                base = float(scaling.get("base", 0) or 0)
                step = float(scaling.get("step", 0) or 0)
                value = base + float(level) * step
                pct = (value - 1) * 100
                try:
                    pct_text = f"{pct:.0f}%"
                except Exception:
                    pct_text = ""
                if cid == "linfeng" and pct_text:
                    return f"燃烧联动强度提高 {pct_text}"
                return desc

            if t == "STACK_EXPLODE":
                scaling = model.get("scaling") if isinstance(model.get("scaling"), dict) else {}
                base = float(scaling.get("base", 0) or 0)
                step = float(scaling.get("step", 0) or 0)
                ratio = base + float(level) * step
                dmg = ratio * float(self._base_atk)
                try:
                    dmg_int = int(round(dmg))
                except Exception:
                    return desc
                if cid == "sixtails":
                    return f"燃烧叠加至8层以上触发爆燃：引爆每层燃烧造成{dmg_int:,}伤害"
                return desc

            return self._resolve_skill_formula(desc, level)
        scaling = model.get("scaling") if isinstance(model.get("scaling"), dict) else {}
        base = float(scaling.get("base", 0) or 0)
        step = float(scaling.get("step", 0) or 0)
        value = base + float(level) * step
        attr = ""
        params = model.get("params") if isinstance(model.get("params"), dict) else {}
        a = str(params.get("attribute", "") or "")
        attr_map = {"crit": "会心", "special": "化伤和秽灭", "mastery": "专精", "def": "防御"}
        attr = attr_map.get(a, "")
        if not attr:
            return desc
        try:
            iv = int(round(value))
        except Exception:
            return self._resolve_skill_formula(desc, level)
        return self._resolve_skill_formula(f"增加{attr}值{iv}", level)

    def _resolve_skill_formula(self, text: str, level: int) -> str:
        s = str(text or "")
        if not s:
            return s
        level = int(getattr(self, "_default_level", level) or level)

        base_vars = {"atk": float(self._base_atk), "hp": float(self._base_hp), "dps": float(self._base_dps)}

        def _safe_eval(expr: str) -> tuple[float | None, bool]:
            raw = (expr or "").strip().lower()
            has_percent = "%" in raw
            e = raw.replace("lv", str(int(level)))
            e = re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", e)
            e = e.replace(" ", "")
            if not re.fullmatch(r"[0-9\.\+\-\*\/\(\)]+", e):
                return None, has_percent
            try:
                return float(eval(e, {"__builtins__": None}, {})), has_percent
            except Exception:
                return None, has_percent

        def _format_number(v: float) -> str:
            try:
                iv = int(round(v))
            except Exception:
                return str(v)
            if abs(v - float(iv)) < 1e-9:
                return str(iv)
            return f"{v:.4f}".rstrip("0").rstrip(".")

        def _format_percent(ratio: float) -> str:
            p = ratio * 100
            return f"{p:.2f}".rstrip("0").rstrip(".") + "%"

        pattern_mul = re.compile(r"(\([^\)]*lv[^\)]*\)|[0-9\.\+\-\*\/\s%]*lv[0-9\.\+\-\*\/\s%]*)\s*\*\s*(atk|hp|dps)\b", re.I)

        def _repl(m: re.Match) -> str:
            expr = m.group(1)
            var = m.group(2).lower()
            v, _has_pct = _safe_eval(expr)
            if v is None:
                return m.group(0)
            base = base_vars.get(var)
            if base is None:
                return m.group(0)
            total = v * base
            return f"{total:,.0f}"

        out = pattern_mul.sub(_repl, s)

        pattern_paren = re.compile(r"[\(\（]([0-9\.\+\-\*\/\s%]*lv[0-9\.\+\-\*\/\s%]*)[\)\）]", re.I)

        def _repl_paren(m: re.Match) -> str:
            expr = m.group(1)
            v, has_pct = _safe_eval(expr)
            if v is None:
                return m.group(0)
            if has_pct:
                return _format_percent(v)
            return _format_number(v)

        out = pattern_paren.sub(_repl_paren, out)
        return out

    def _format_result_payload(self, payload: str) -> str:
        try:
            obj = json.loads(payload)
        except Exception:
            return payload
        if not isinstance(obj, dict):
            return payload

        deck_ids = obj.get("deck") if isinstance(obj.get("deck"), list) else []
        deck_names = []
        for x in deck_ids:
            token = str(x or "").strip()
            cid = self._token_to_cid(token)
            deck_names.append(self._id_to_name.get(cid, token) if (cid or token) else "")
        unknown = obj.get("unknown") if isinstance(obj.get("unknown"), list) else []
        unknown_text = "、".join([str(x) for x in unknown]) if unknown else ""

        dps = obj.get("dps")
        try:
            dps_int = int(dps)
        except Exception:
            dps_int = None

        combat_time = obj.get("combat_time")
        try:
            combat_time_f = float(combat_time)
        except Exception:
            combat_time_f = None

        total_cost = obj.get("total_cost")
        try:
            total_cost_i = int(total_cost)
        except Exception:
            total_cost_i = None

        base_atk = obj.get("base_atk")
        base_hp = obj.get("base_hp")
        base_dps = obj.get("base_dps")
        try:
            base_atk_i = int(float(base_atk))
        except Exception:
            base_atk_i = None
        try:
            base_hp_i = int(float(base_hp))
        except Exception:
            base_hp_i = None
        try:
            base_dps_i = int(float(base_dps))
        except Exception:
            base_dps_i = None

        lines = []
        lines.append("仿真结果")
        lines.append("")
        lines.append(f"卡组：{'、'.join(deck_names) if deck_names else '（空）'}")
        if total_cost_i is not None:
            lines.append(f"费用：{total_cost_i}    卡数：{len(deck_names)}")
        else:
            lines.append(f"卡数：{len(deck_names)}")
        if base_atk_i is not None or base_hp_i is not None or base_dps_i is not None:
            lines.append(
                f"基础属性：攻击={base_atk_i if base_atk_i is not None else '-'}    气血={base_hp_i if base_hp_i is not None else '-'}    秒伤={base_dps_i if base_dps_i is not None else '-'}"
            )
        if combat_time_f is not None:
            lines.append(f"战斗时长：{combat_time_f:.1f} 秒")
        if dps_int is not None:
            lines.append(f"最终 DPS：{dps_int:,}")
        if unknown_text:
            lines.append(f"未识别卡牌：{unknown_text}")

        events = obj.get("events") if isinstance(obj.get("events"), dict) else {}
        if events:
            lines.append("")
            lines.append("关键触发次数")
            for k in ["ice_arrow", "burn_add", "pulse", "explode"]:
                if k not in events:
                    continue
                label = {"ice_arrow": "冰箭", "burn_add": "燃烧叠加", "pulse": "脉冲", "explode": "爆燃"}.get(k, k)
                try:
                    v = int(events.get(k) or 0)
                except Exception:
                    v = events.get(k)
                lines.append(f"- {label}：{v}")

        details = obj.get("details") if isinstance(obj.get("details"), dict) else {}
        if details:
            lines.append("")
            lines.append("伤害构成（从高到低）")
            items = []
            for k, v in details.items():
                try:
                    vv = float(v)
                except Exception:
                    continue
                label = "基础输出" if k == "base_dps" else str(k)
                items.append((label, vv))
            items.sort(key=lambda x: x[1], reverse=True)
            for label, vv in items[:12]:
                lines.append(f"- {label}：{int(round(vv)):,}")

        return "\n".join(lines)

    def _make_text_label(self, text: str, *, color: str, font_size: int | None = None, bold: bool = False) -> QLabel:
        w = QLabel(text)
        parts = [f"color:{color};"]
        if font_size is not None:
            parts.append(f"font-size:{int(font_size)}px;")
        if bold:
            parts.append("font-weight:600;")
        w.setStyleSheet("".join(parts))
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        w.setWordWrap(True)
        return w

    def _make_pill(self, text: str) -> QLabel:
        w = QLabel(text)
        w.setStyleSheet(
            f"background:transparent;color:{self._accent};border:1px solid rgba(0,229,255,0.65);border-radius:999px;padding:3px 10px;"
        )
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return w

    def _render_board(self):
        self._clear_layout(self.board_list_layout)
        q = (self.board_search.text() or "").strip().lower()
        raw_category = self.board_category.currentData()
        selected_ids = set(self._current_deck_ids())

        filtered = []
        for c in self._cards:
            if self._match_card(c, q, raw_category):
                filtered.append(c)

        self.board_count.setText(f"共 {len(filtered)} / {len(self._cards)} 张")

        if not self._cards:
            self.board_list_layout.addWidget(BodyLabel("未找到 cards_export.json 的卡牌数据"), 0)
            self.board_list_layout.addStretch(1)
            return

        if not filtered:
            self.board_list_layout.addWidget(BodyLabel("没有符合条件的卡牌"), 0)
            self.board_list_layout.addStretch(1)
            return

        card_qss = (
            f"QWidget#danqingBoardCard{{background:{self._card};border:1px solid rgba(0,0,0,0.0);border-radius:14px;}}"
            f"QWidget#danqingBoardCard:hover{{border:1px solid rgba(0,229,255,0.95);background:rgba(0,229,255,0.06);}}"
        )
        card_qss_selected = (
            f"QWidget#danqingBoardCard{{background:rgba(0,229,255,0.06);border:1px solid rgba(0,229,255,0.95);border-radius:14px;}}"
            f"QWidget#danqingBoardCard:hover{{border:1px solid rgba(0,229,255,0.95);background:rgba(0,229,255,0.06);}}"
        )

        for c in filtered:
            cid = str(c.get("id", "") or "")
            name = str(c.get("name", "") or "")
            cost = int(c.get("cost", 0) or 0)
            category_text = self._display_category(str(c.get("category", "") or ""))
            stats_text = self._cost_stats_text(cost, self._default_level)
            tags_text = self._display_tags(c.get("tags"))
            desc = self._display_skill_text(c, self._default_level)

            token = cid
            card = _DanqingBoardCard(on_click=lambda x=token: self._toggle_card_in_deck(x))
            card.setObjectName("danqingBoardCard")
            is_selected = bool(cid and cid in selected_ids)
            card.setStyleSheet(card_qss_selected if is_selected else card_qss)
            card.set_selected(is_selected)
            card_layout = QGridLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setHorizontalSpacing(10)
            card_layout.setVerticalSpacing(8)

            title = self._make_text_label(name, color=self._text, font_size=16, bold=True)
            card_layout.addWidget(title, 0, 0, 1, 3)

            cost_badge = QLabel(f"{cost}费")
            cost_badge.setStyleSheet(
                f"background:{self._accent};color:#051014;border:0;border-radius:999px;padding:5px 10px;font-weight:800;"
            )
            cost_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            card_layout.addWidget(cost_badge, 0, 3, 1, 1, Qt.AlignmentFlag.AlignRight)

            if stats_text:
                stats = QLabel(stats_text)
                stats.setStyleSheet(
                    f"background:rgba(0,0,0,0.24);color:{self._text};border:1px solid rgba(0,229,255,0.12);border-radius:10px;padding:8px 10px;font-family:Consolas, 'Courier New', monospace;"
                )
                stats.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                card_layout.addWidget(stats, 1, 0, 1, 4)
                row = 2
            else:
                row = 1

            chips = QWidget()
            chips.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            chips_layout = QHBoxLayout(chips)
            chips_layout.setContentsMargins(0, 0, 0, 0)
            chips_layout.setSpacing(8)

            if category_text and category_text != "未知":
                chips_layout.addWidget(self._make_pill(category_text), 0)
            if tags_text:
                first_tag = tags_text.split("、", 1)[0].strip()
                if first_tag:
                    chips_layout.addWidget(self._make_pill(first_tag), 0)
            chips_layout.addStretch(1)
            card_layout.addWidget(chips, row, 0, 1, 4)
            row += 1

            if desc:
                desc_label = self._make_text_label(desc, color=self._muted, font_size=12)
                card_layout.addWidget(desc_label, row, 0, 1, 4)

            self.board_list_layout.addWidget(card, 0)
        self.board_list_layout.addStretch(1)


class OfflineGameTaskManager(QWidget):
    def __init__(self, storage: RiliStorage, parent=None):
        super().__init__(parent=parent)
        self.storage = storage
        self.task_defaults = self.storage.get_task_defaults()
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
            "dailyTasks": [
                {"id": t["id"], "name": t["name"], "type": t.get("type", "check"), "completed": False} for t in self.task_defaults.get("daily", [])
            ],
            "weeklyTasks": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "type": t.get("type", ""),
                    "subTasks": [{"id": s["id"], "name": s["name"], "total": int(s["total"]), "completed": 0} for s in t.get("subTasks", [])],
                }
                for t in self.task_defaults.get("weekly", [])
            ],
        }

    def _sync_role(self, role: dict) -> dict:
        daily_by_id = {t.get("id"): t for t in role.get("dailyTasks", []) if isinstance(t, dict)}
        weekly_by_id = {t.get("id"): t for t in role.get("weeklyTasks", []) if isinstance(t, dict)}

        synced_daily = []
        for def_task in self.task_defaults.get("daily", []):
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
        for def_task in self.task_defaults.get("weekly", []):
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
        self.activity_defs = self.storage.get_activity_definitions()
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
        task = next((t for t in self.activity_defs if t.get("id") == task_id), None)
        if task is None:
            return task_id
        if task.get("type") == "once_weekly":
            return f"weekly_{task_id}"
        return f"{task_id}_d{day_index}_t{time_index}"

    def _tasks_for_day(self, day_index: int) -> list[dict]:
        day_tasks = []
        for task in self.activity_defs:
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

        config_row = QHBoxLayout()
        config_row.setContentsMargins(0, 0, 0, 0)
        config_row.setSpacing(10)
        self.import_btn = QPushButton("导入配置")
        self.export_btn = QPushButton("导出配置")
        self.reset_cfg_btn = QPushButton("恢复默认配置")
        config_row.addWidget(self.import_btn, 0)
        config_row.addWidget(self.export_btn, 0)
        config_row.addWidget(self.reset_cfg_btn, 0)
        config_row.addStretch(1)
        root.addLayout(config_row, 0)

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

        self.import_btn.clicked.connect(self._import_config)
        self.export_btn.clicked.connect(self._export_config)
        self.reset_cfg_btn.clicked.connect(self._reset_config)

        self.segment.setCurrentItem("task_manager")
        self.open("task_manager")

    def _recreate_pages(self, keep_key: str):
        key = keep_key if keep_key in ("task_manager", "activity_calendar") else "task_manager"
        self.pages = {
            "task_manager": OfflineGameTaskManager(storage=self.storage, parent=self),
            "activity_calendar": OfflineActivityCalendar(storage=self.storage, parent=self),
        }
        self.open(key)

    def _export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", "rili-config.json", "JSON 文件 (*.json)")
        if not path:
            return
        payload = {
            "taskDefaults": self.storage.get_task_defaults(),
            "activityDefinitions": self.storage.get_activity_definitions(),
        }
        try:
            _write_json(path, payload)
            InfoBar.success("完成", "已导出配置", parent=self, position=InfoBarPosition.TOP, duration=1500)
        except Exception:
            InfoBar.error("失败", "导出失败（请检查路径权限）", parent=self, position=InfoBarPosition.TOP, duration=2200)

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON 文件 (*.json)")
        if not path:
            return
        raw = _read_json(path, None)
        if not isinstance(raw, dict):
            InfoBar.error("失败", "配置文件格式不正确（根必须是对象）", parent=self, position=InfoBarPosition.TOP, duration=2400)
            return
        task_defaults = raw.get("taskDefaults")
        activity_defs = raw.get("activityDefinitions")
        if isinstance(task_defaults, dict):
            self.storage.set_task_defaults(task_defaults)
        if isinstance(activity_defs, list):
            self.storage.set_activity_definitions(activity_defs)
        current = self.segment.currentItem()
        self._recreate_pages(str(current or "task_manager"))
        InfoBar.success("完成", "已导入配置", parent=self, position=InfoBarPosition.TOP, duration=1500)

    def _reset_config(self):
        self.storage.reset_definitions()
        current = self.segment.currentItem()
        self._recreate_pages(str(current or "task_manager"))
        InfoBar.success("完成", "已恢复默认配置", parent=self, position=InfoBarPosition.TOP, duration=1500)

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


class _TianshuEdgeItem(QGraphicsLineItem):
    def __init__(self, parent_id: str, child_id: str, parent_pos: QPointF, child_pos: QPointF):
        super().__init__(parent_pos.x(), parent_pos.y(), child_pos.x(), child_pos.y())
        self.parent_id = parent_id
        self.child_id = child_id
        self.setZValue(0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)


class _TianshuNodeItem(QGraphicsEllipseItem):
    def __init__(self, node_id: str, radius: float, graph):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.node_id = node_id
        self.radius = radius
        self.graph = graph
        self.setAcceptHoverEvents(True)
        self.setZValue(10)

        self._rank_text = QGraphicsSimpleTextItem("", self)
        self._rank_text.setFont(QFont("Segoe UI", 9))
        self._rank_text.setBrush(QBrush(QColor("#ffffff")))

        self._name_text = QGraphicsSimpleTextItem("", self)
        self._name_text.setFont(QFont("Segoe UI", 8))
        self._name_text.setBrush(QBrush(QColor("#d0d0d0")))

    def _center_text(self, item: QGraphicsSimpleTextItem, dy: float = 0):
        rect = item.boundingRect()
        item.setPos(-rect.width() / 2, -rect.height() / 2 + dy)

    def set_rank_text(self, text: str):
        self._rank_text.setText(text)
        self._center_text(self._rank_text, dy=0)

    def set_name_text(self, text: str):
        self._name_text.setText(text)
        rect = self._name_text.boundingRect()
        self._name_text.setPos(-rect.width() / 2, self.radius + 4)

    def hoverEnterEvent(self, event):
        self.graph._on_node_hover_enter(event, self.node_id)

    def hoverLeaveEvent(self, event):
        self.graph._on_node_hover_leave(event)

    def mousePressEvent(self, event):
        self.graph._on_node_mouse(event, self.node_id)


class _TianshuGraphView(QGraphicsView):
    def __init__(self, owner, parent=None):
        super().__init__(parent=parent)
        self.owner = owner
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)

        self._tree_id: str | None = None
        self._nodes: dict[str, _TianshuNodeItem] = {}
        self._edges: list[_TianshuEdgeItem] = []

        self._panning = False
        self._pan_last = QPointF(0, 0)
        self.setMouseTracking(True)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            steps = delta / 120.0
            factor = 1.15 ** steps
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.scale(factor, factor)
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(int(event.position().x()), int(event.position().y()))
            if item is None:
                self._panning = True
                self._pan_last = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.translate(delta.x(), delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def load_tree(self, tree_id: str, tree: dict, ranks: dict[str, int]):
        if self._tree_id == tree_id:
            self.update_state(ranks)
            return

        self._tree_id = tree_id
        self._scene.clear()
        self._nodes = {}
        self._edges = []

        nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
        nodes = [n for n in nodes if isinstance(n, dict) and n.get("id")]

        radius = 28
        for node in nodes:
            node_id = str(node.get("id"))
            item = _TianshuNodeItem(node_id=node_id, radius=radius, graph=self)
            item.setPos(float(node.get("x") or 0), float(node.get("y") or 0))
            item.set_name_text(str(node.get("name") or node_id))

            self._scene.addItem(item)
            self._nodes[node_id] = item

        for node in nodes:
            child_id = str(node.get("id"))
            child_item = self._nodes.get(child_id)
            if child_item is None:
                continue
            child_pos = child_item.pos()
            for pid in node.get("prereqs") or []:
                parent_id = str(pid)
                parent_item = self._nodes.get(parent_id)
                if parent_item is None:
                    continue
                parent_pos = parent_item.pos()
                edge = _TianshuEdgeItem(parent_id=parent_id, child_id=child_id, parent_pos=parent_pos, child_pos=child_pos)
                self._scene.addItem(edge)
                self._edges.append(edge)

        if self._nodes:
            rect = self._scene.itemsBoundingRect().adjusted(-120, -120, 120, 120)
        else:
            rect = QRectF(0, 0, 2000, 2000)
        self._scene.setSceneRect(rect)
        self.resetTransform()
        self.scale(0.65, 0.65)
        self.centerOn(rect.center())

        self.update_state(ranks)

    def _on_node_hover_enter(self, _event, node_id: str):
        text = self.owner._get_node_tooltip(node_id)
        if text:
            QToolTip.showText(QCursor.pos(), text)

    def _on_node_hover_leave(self, _event):
        QToolTip.hideText()

    def _on_node_mouse(self, event, node_id: str):
        if event.button() == Qt.MouseButton.LeftButton:
            current = int(self.owner.ranks.get(node_id, 0))
            self.owner._apply_rank_change(node_id, current + 1)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            current = int(self.owner.ranks.get(node_id, 0))
            self.owner._apply_rank_change(node_id, current - 1)
            event.accept()
            return
        event.ignore()

    def update_state(self, ranks: dict[str, int]):
        for node_id, item in self._nodes.items():
            node = self.owner._node_by_id.get(node_id)
            if not isinstance(node, dict):
                continue
            max_rank = int(node.get("maxRank") or 1)
            rank = int(ranks.get(node_id, 0))
            unlocked = self.owner._is_unlocked(node_id)

            if rank >= max_rank and max_rank > 0:
                brush = QBrush(QColor("#2ea043"))
                pen = QPen(QColor("#3fb950"), 2)
            elif rank > 0:
                brush = QBrush(QColor("#1f6feb"))
                pen = QPen(QColor("#58a6ff"), 2)
            elif unlocked:
                brush = QBrush(QColor("#2b2b2b"))
                pen = QPen(QColor("#58a6ff"), 2)
            else:
                brush = QBrush(QColor("#1f1f1f"))
                pen = QPen(QColor("#555555"), 2)

            item.setBrush(brush)
            item.setPen(pen)
            item.set_rank_text("" if rank <= 0 else f"{rank}/{max_rank}")

        for edge in self._edges:
            parent = self.owner._node_by_id.get(edge.parent_id)
            if isinstance(parent, dict):
                parent_max = int(parent.get("maxRank") or 1)
            else:
                parent_max = 1
            parent_rank = int(ranks.get(edge.parent_id, 0))
            active = parent_rank >= parent_max and parent_max > 0
            pen = QPen(QColor("#58a6ff" if active else "#555555"), 2 if active else 1)
            edge.setPen(pen)


class TianshuInterface(QWidget):
    MAX_POINTS = 31

    def __init__(self, storage_dir: str, talents_dir: str | None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("tianshu")
        self.storage = TianshuStorage(storage_dir=storage_dir)
        self.talents_dir = talents_dir

        self.tianshu_data: dict[str, dict] = {}
        self.tianshu_list: list[dict] = []
        self.current_tree_id: str | None = None
        self.ranks: dict[str, int] = {}

        self._node_by_id: dict[str, dict] = {}
        self._dependents: dict[str, list[str]] = {}
        self._updating = False
        self._refresh_scheduled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        root.addWidget(SubtitleLabel("天书模拟器"), 0)
        root.addWidget(BodyLabel("离线版：本地加点 + 本地存档（上限 31 点）"), 0)

        header_card = CardWidget()
        header_layout = QGridLayout(header_card)
        header_layout.setContentsMargins(16, 16, 16, 16)
        header_layout.setHorizontalSpacing(10)
        header_layout.setVerticalSpacing(10)

        header_layout.addWidget(BodyLabel("流派选择"), 0, 0, 1, 1)
        self.tree_combo = QComboBox()
        header_layout.addWidget(self.tree_combo, 0, 1, 1, 3)

        self.reset_btn = PrimaryPushButton("重置当前流派")
        header_layout.addWidget(self.reset_btn, 1, 1, 1, 1)

        self.points_label = BodyLabel("")
        header_layout.addWidget(self.points_label, 1, 2, 1, 2)

        root.addWidget(header_card, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        left_layout.addWidget(BodyLabel("节点图：左键加点，右键减点；拖动空白处平移；Ctrl+滚轮缩放"), 0)
        self.graph = _TianshuGraphView(owner=self, parent=left)
        self.graph.setFrameShape(QFrame.Shape.NoFrame)
        left_layout.addWidget(self.graph, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addWidget(BodyLabel("效果/属性汇总"), 0)
        self.summary = TextEdit()
        self.summary.setReadOnly(True)
        right_layout.addWidget(self.summary, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.tree_combo.currentIndexChanged.connect(self._on_tree_changed)
        self.reset_btn.clicked.connect(self._reset_current_tree)

        self._init_data()

    def _init_data(self):
        if not self.talents_dir or not os.path.isdir(self.talents_dir):
            InfoBar.error(
                "缺少数据",
                "找不到 talents 数据目录，天书模拟器无法加载",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )
            self.tree_combo.setEnabled(False)
            self.reset_btn.setEnabled(False)
            self.points_label.setText("数据未加载")
            self.summary.setPlainText("请确认 tools/tianshu/data/talents 或 zxsj/src/data/talents 目录存在。")
            return

        self.tianshu_data, self.tianshu_list = _load_tianshu_data(self.talents_dir)
        if not self.tianshu_list:
            self.tree_combo.setEnabled(False)
            self.reset_btn.setEnabled(False)
            self.points_label.setText("未找到天书数据")
            self.summary.setPlainText("talents 目录为空或数据格式不正确。")
            return

        self.tree_combo.blockSignals(True)
        self.tree_combo.clear()
        for t in self.tianshu_list:
            self.tree_combo.addItem(str(t.get("name") or t.get("id") or ""), t.get("id"))
        self.tree_combo.blockSignals(False)

        state = self.storage.load()
        last_tree_id = state.get("lastTreeId")
        if not isinstance(last_tree_id, str) or last_tree_id not in self.tianshu_data:
            last_tree_id = self.tianshu_list[0]["id"]
        self._switch_tree(last_tree_id)

        idx = self.tree_combo.findData(last_tree_id)
        if idx >= 0:
            self.tree_combo.setCurrentIndex(idx)

    def _load_all_ranks(self) -> dict[str, dict[str, int]]:
        raw = self.storage.load()
        ranks_by_tree = raw.get("ranksByTree")
        if not isinstance(ranks_by_tree, dict):
            return {}
        cleaned: dict[str, dict[str, int]] = {}
        for tree_id, ranks in ranks_by_tree.items():
            if not isinstance(tree_id, str) or not isinstance(ranks, dict):
                continue
            cleaned[tree_id] = {str(k): int(v) for k, v in ranks.items() if str(k) and isinstance(v, (int, float))}
        return cleaned

    def _save_state(self):
        ranks_by_tree = self._load_all_ranks()
        if self.current_tree_id:
            ranks_by_tree[self.current_tree_id] = {k: int(v) for k, v in self.ranks.items() if int(v) > 0}
        payload = {
            "version": "tianshu_v1",
            "lastTreeId": self.current_tree_id,
            "ranksByTree": ranks_by_tree,
            "meta": {"updatedAt": datetime.now().isoformat()},
        }
        self.storage.save(payload)

    def _total_points(self, ranks: dict[str, int] | None = None) -> int:
        if ranks is None:
            ranks = self.ranks
        return sum(int(v) for v in ranks.values() if isinstance(v, int))

    def _on_tree_changed(self, index: int):
        tree_id = self.tree_combo.itemData(index)
        if isinstance(tree_id, str) and tree_id:
            self._switch_tree(tree_id)

    def _switch_tree(self, tree_id: str):
        tree = self.tianshu_data.get(tree_id)
        if not isinstance(tree, dict):
            return
        self.current_tree_id = tree_id

        self._node_by_id = {str(n.get("id")): n for n in tree.get("nodes", []) if isinstance(n, dict) and n.get("id")}
        self._dependents = {}
        for node in self._node_by_id.values():
            for pid in node.get("prereqs") or []:
                if not pid:
                    continue
                self._dependents.setdefault(str(pid), []).append(str(node.get("id")))

        all_ranks = self._load_all_ranks()
        ranks = all_ranks.get(tree_id, {})
        if not isinstance(ranks, dict):
            ranks = {}
        cleaned: dict[str, int] = {}
        for nid, val in ranks.items():
            node = self._node_by_id.get(str(nid))
            if node is None:
                continue
            max_rank = int(node.get("maxRank") or 1)
            cleaned[str(nid)] = max(0, min(max_rank, int(val)))

        cleaned = self._normalize_ranks(cleaned)
        self.ranks = cleaned
        self._save_state()
        self._refresh_now()

    def _reset_current_tree(self):
        if not self.current_tree_id:
            return
        self.ranks = {}
        self._save_state()
        InfoBar.success("完成", "已重置当前流派", parent=self, position=InfoBarPosition.TOP, duration=1500)
        self._refresh_now()

    def _normalize_ranks(self, ranks: dict[str, int]) -> dict[str, int]:
        changed = True
        while changed:
            changed = False
            for node_id, val in list(ranks.items()):
                if int(val) <= 0:
                    ranks.pop(node_id, None)
                    changed = True
                    continue
                if not self._is_unlocked(node_id, ranks):
                    ranks.pop(node_id, None)
                    changed = True
        return {k: int(v) for k, v in ranks.items() if int(v) > 0}

    def _is_unlocked(self, node_id: str, ranks: dict[str, int] | None = None) -> bool:
        if ranks is None:
            ranks = self.ranks
        node = self._node_by_id.get(node_id)
        if node is None:
            return False
        prereqs = node.get("prereqs") or []
        if not prereqs:
            return True
        for pid in prereqs:
            parent = self._node_by_id.get(str(pid))
            if parent is None:
                continue
            parent_rank = int(ranks.get(str(pid), 0))
            if parent_rank >= int(parent.get("maxRank") or 1):
                return True
        return False

    def _can_upgrade(self, node_id: str) -> tuple[bool, str]:
        node = self._node_by_id.get(node_id)
        if node is None:
            return False, "节点不存在"
        current_rank = int(self.ranks.get(node_id, 0))
        max_rank = int(node.get("maxRank") or 1)
        if current_rank >= max_rank:
            return False, "已点满"
        if not self._is_unlocked(node_id):
            return False, "未解锁（需要点满前置）"
        if self._total_points() >= self.MAX_POINTS:
            return False, f"点数已满（{self.MAX_POINTS}）"
        return True, ""

    def _can_downgrade(self, node_id: str) -> tuple[bool, str]:
        current_rank = int(self.ranks.get(node_id, 0))
        if current_rank <= 0:
            return False, "未加点"
        if current_rank == 1:
            for dep_id in self._dependents.get(node_id, []):
                if int(self.ranks.get(dep_id, 0)) > 0:
                    return False, "后置节点已加点，不能清零"
        return True, ""

    def _apply_rank_change(self, node_id: str, target_rank: int):
        if self._updating:
            return
        node = self._node_by_id.get(node_id)
        if node is None:
            return

        self._updating = True
        try:
            current = int(self.ranks.get(node_id, 0))
            target_rank = max(0, min(int(node.get("maxRank") or 1), int(target_rank)))

            if target_rank > current:
                for _ in range(target_rank - current):
                    ok, msg = self._can_upgrade(node_id)
                    if not ok:
                        InfoBar.warning("提示", msg, parent=self, position=InfoBarPosition.TOP, duration=1500)
                        break
                    self.ranks[node_id] = int(self.ranks.get(node_id, 0)) + 1
            elif target_rank < current:
                for _ in range(current - target_rank):
                    ok, msg = self._can_downgrade(node_id)
                    if not ok:
                        InfoBar.warning("提示", msg, parent=self, position=InfoBarPosition.TOP, duration=1500)
                        break
                    next_rank = int(self.ranks.get(node_id, 0)) - 1
                    if next_rank <= 0:
                        self.ranks.pop(node_id, None)
                    else:
                        self.ranks[node_id] = next_rank

            self.ranks = self._normalize_ranks(self.ranks)
            self._save_state()
        finally:
            self._updating = False
        self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        QTimer.singleShot(0, self._refresh_now)

    def _refresh_now(self):
        self._refresh_scheduled = False
        tree = self.tianshu_data.get(self.current_tree_id or "")
        if isinstance(tree, dict) and self.current_tree_id:
            self.graph.load_tree(self.current_tree_id, tree, self.ranks)
        self._render_summary()

    def _get_node_tooltip(self, node_id: str) -> str:
        node = self._node_by_id.get(node_id)
        if not isinstance(node, dict):
            return ""
        name = str(node.get("name") or node_id)
        max_rank = int(node.get("maxRank") or 1)
        rank = int(self.ranks.get(node_id, 0))
        unlocked = self._is_unlocked(node_id)

        prereqs = node.get("prereqs") or []
        prereq_names = []
        for pid in prereqs:
            parent = self._node_by_id.get(str(pid))
            if isinstance(parent, dict):
                prereq_names.append(str(parent.get("name") or pid))
        prereq_text = " / ".join(prereq_names)

        desc_lines = node.get("descLines") or []
        desc = ""
        if isinstance(desc_lines, list) and desc_lines:
            idx = max(0, rank - 1)
            desc = str(desc_lines[idx] if idx < len(desc_lines) else desc_lines[0])

        stats_lines = []
        stats_by_rank = node.get("statsByRank") or []
        if isinstance(stats_by_rank, list) and rank > 0 and rank - 1 < len(stats_by_rank):
            for s in stats_by_rank[rank - 1] or []:
                if not isinstance(s, dict):
                    continue
                label = str(s.get("label") or s.get("key") or "")
                if not label:
                    continue
                val = s.get("value", 0)
                suffix = str(s.get("suffix") or "")
                if isinstance(val, float):
                    val_str = f"{val:.2f}".rstrip("0").rstrip(".")
                else:
                    val_str = str(val)
                stats_lines.append(f"{label} {val_str}{suffix}")

        lines = [name, f"点数：{rank}/{max_rank}", f"状态：{'已解锁' if unlocked else '未解锁'}"]
        if prereq_text:
            lines.append(f"前置：{prereq_text}（满足其一即可）")
        if stats_lines:
            lines.append("属性：")
            lines.extend(stats_lines[:12])
        if desc:
            lines.append("描述：")
            lines.append(desc)
        return "\n".join(lines)

    def _render_summary(self):
        points = self._total_points()
        self.points_label.setText(f"已投入点数：{points} / {self.MAX_POINTS}")

        tree = self.tianshu_data.get(self.current_tree_id or "")
        nodes = tree.get("nodes", []) if isinstance(tree, dict) else []

        stats: dict[str, dict] = {}
        special: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            rank = int(self.ranks.get(node_id, 0))
            if rank <= 0:
                continue
            stats_by_rank = node.get("statsByRank") or []
            stat_list = []
            if isinstance(stats_by_rank, list) and 0 <= rank - 1 < len(stats_by_rank):
                stat_list = stats_by_rank[rank - 1] or []
            if isinstance(stat_list, list) and stat_list:
                for s in stat_list:
                    if not isinstance(s, dict):
                        continue
                    key = str(s.get("key") or "")
                    if not key:
                        continue
                    if key not in stats:
                        stats[key] = {"label": str(s.get("label") or key), "value": 0.0, "suffix": str(s.get("suffix") or "")}
                    val = s.get("value", 0)
                    if isinstance(val, (int, float)):
                        stats[key]["value"] = float(stats[key]["value"]) + float(val)
            else:
                desc_lines = node.get("descLines") or []
                if isinstance(desc_lines, list) and desc_lines:
                    idx = max(0, rank - 1)
                    text = str(desc_lines[idx] if idx < len(desc_lines) else (desc_lines[0] if desc_lines else ""))
                else:
                    text = ""
                if text:
                    special.append(f"{node.get('name') or node_id}：{text}")

        lines = [f"流派：{(tree or {}).get('name', self.current_tree_id or '')}", f"点数：{points} / {self.MAX_POINTS}", ""]
        if stats:
            lines.append("属性汇总：")
            for key in sorted(stats.keys()):
                entry = stats[key]
                val = entry.get("value", 0)
                if isinstance(val, float):
                    val_str = f"{val:.2f}".rstrip("0").rstrip(".")
                else:
                    val_str = str(val)
                lines.append(f"- {entry.get('label')}: {val_str}{entry.get('suffix')}")
            lines.append("")
        if special:
            lines.append("效果汇总：")
            for s in special:
                lines.append(f"- {s}")
        if not stats and not special:
            lines.append("还没有加点。")
        self.summary.setPlainText("\n".join(lines))


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


class WebViewBridge(QObject):
    MAX_TIANSHU_POINTS = 31

    def __init__(
        self,
        *,
        tool_id: str = "",
        rili_storage_dir: str | None = None,
        tianshu_storage_dir: str | None = None,
        tianshu_talents_dir: str | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.tool_id = str(tool_id or "").strip().lower()
        self._rili_storage = RiliStorage(rili_storage_dir) if self.tool_id == "rili" and rili_storage_dir else None
        self._tianshu_storage = TianshuStorage(tianshu_storage_dir) if self.tool_id == "tianshu" and tianshu_storage_dir else None
        self._tianshu_talents_dir = tianshu_talents_dir if self.tool_id == "tianshu" else None

        self._tianshu_data: dict[str, dict] = {}
        self._tianshu_list: list[dict] = []
        self._tianshu_tree_id: str | None = None
        self._tianshu_ranks: dict[str, int] = {}
        self._tianshu_node_by_id: dict[str, dict] = {}
        self._tianshu_dependents: dict[str, list[str]] = {}
        self._tianshu_loaded = False

    @pyqtSlot(result=str)
    def ping(self) -> str:
        return "pong"

    @pyqtSlot(str)
    def log(self, message: str) -> None:
        msg = str(message or "").strip()
        if not msg:
            return
        InfoBar.success("WebView", msg, parent=self.parent(), position=InfoBarPosition.TOP, duration=1600)

    @pyqtSlot(result=str)
    def riliGetTaskDefaults(self) -> str:
        if self._rili_storage is None:
            return json.dumps(GAME_TASK_MANAGER_DEFAULT_TASKS, ensure_ascii=False)
        return json.dumps(self._rili_storage.get_task_defaults(), ensure_ascii=False)

    @pyqtSlot(result=str)
    def riliGetActivityDefinitions(self) -> str:
        if self._rili_storage is None:
            return json.dumps(ACTIVITY_CALENDAR_TASKS, ensure_ascii=False)
        return json.dumps(self._rili_storage.get_activity_definitions(), ensure_ascii=False)

    @pyqtSlot(str)
    def riliSaveTaskDefaults(self, payload: str) -> None:
        if self._rili_storage is None:
            return
        try:
            data = json.loads(payload or "")
        except Exception:
            return
        if isinstance(data, dict):
            self._rili_storage.set_task_defaults(data)

    @pyqtSlot(str)
    def riliSaveActivityDefinitions(self, payload: str) -> None:
        if self._rili_storage is None:
            return
        try:
            data = json.loads(payload or "")
        except Exception:
            return
        if isinstance(data, list):
            self._rili_storage.set_activity_definitions([x for x in data if isinstance(x, dict)])

    @pyqtSlot(result=str)
    def riliGetTaskManager(self) -> str:
        if self._rili_storage is None:
            return "{}"
        raw = self._rili_storage.load_task_manager()
        return json.dumps(raw if isinstance(raw, dict) else {}, ensure_ascii=False)

    @pyqtSlot(str)
    def riliSaveTaskManager(self, payload: str) -> None:
        if self._rili_storage is None:
            return
        try:
            data = json.loads(payload or "")
        except Exception:
            return
        if isinstance(data, dict):
            self._rili_storage.save_task_manager(data)

    @pyqtSlot(result=str)
    def riliGetActivityCalendar(self) -> str:
        if self._rili_storage is None:
            return "{}"
        raw = self._rili_storage.load_activity_calendar()
        return json.dumps(raw if isinstance(raw, dict) else {}, ensure_ascii=False)

    @pyqtSlot(str)
    def riliSaveActivityCalendar(self, payload: str) -> None:
        if self._rili_storage is None:
            return
        try:
            data = json.loads(payload or "")
        except Exception:
            return
        if isinstance(data, dict):
            self._rili_storage.save_activity_calendar(data)

    def _tianshu_ensure_loaded(self) -> None:
        if self._tianshu_loaded:
            return
        self._tianshu_loaded = True
        if not self._tianshu_talents_dir or not os.path.isdir(self._tianshu_talents_dir):
            self._tianshu_data, self._tianshu_list = {}, []
            return
        self._tianshu_data, self._tianshu_list = _load_tianshu_data(self._tianshu_talents_dir)

    def _tianshu_load_all_ranks(self) -> dict[str, dict[str, int]]:
        if self._tianshu_storage is None:
            return {}
        raw = self._tianshu_storage.load()
        ranks_by_tree = raw.get("ranksByTree")
        if not isinstance(ranks_by_tree, dict):
            return {}
        cleaned: dict[str, dict[str, int]] = {}
        for tree_id, ranks in ranks_by_tree.items():
            if not isinstance(tree_id, str) or not isinstance(ranks, dict):
                continue
            cleaned[tree_id] = {str(k): int(v) for k, v in ranks.items() if str(k) and isinstance(v, (int, float))}
        return cleaned

    def _tianshu_save_state(self) -> None:
        if self._tianshu_storage is None:
            return
        ranks_by_tree = self._tianshu_load_all_ranks()
        if self._tianshu_tree_id:
            ranks_by_tree[self._tianshu_tree_id] = {k: int(v) for k, v in self._tianshu_ranks.items() if int(v) > 0}
        payload = {
            "version": "tianshu_v1",
            "lastTreeId": self._tianshu_tree_id,
            "ranksByTree": ranks_by_tree,
            "meta": {"updatedAt": datetime.now().isoformat()},
        }
        self._tianshu_storage.save(payload)

    def _tianshu_total_points(self) -> int:
        return sum(int(v) for v in self._tianshu_ranks.values() if isinstance(v, int))

    def _tianshu_is_unlocked(self, node_id: str) -> bool:
        node = self._tianshu_node_by_id.get(node_id)
        if node is None:
            return False
        prereqs = node.get("prereqs") or []
        if not prereqs:
            return True
        for pid in prereqs:
            parent = self._tianshu_node_by_id.get(str(pid))
            if parent is None:
                continue
            parent_rank = int(self._tianshu_ranks.get(str(pid), 0))
            if parent_rank >= int(parent.get("maxRank") or 1):
                return True
        return False

    def _tianshu_normalize_ranks(self) -> None:
        changed = True
        while changed:
            changed = False
            for node_id, val in list(self._tianshu_ranks.items()):
                if int(val) <= 0:
                    self._tianshu_ranks.pop(node_id, None)
                    changed = True
                    continue
                if not self._tianshu_is_unlocked(node_id):
                    self._tianshu_ranks.pop(node_id, None)
                    changed = True
        self._tianshu_ranks = {k: int(v) for k, v in self._tianshu_ranks.items() if int(v) > 0}

    def _tianshu_can_upgrade(self, node_id: str) -> tuple[bool, str]:
        node = self._tianshu_node_by_id.get(node_id)
        if node is None:
            return False, "节点不存在"
        current_rank = int(self._tianshu_ranks.get(node_id, 0))
        max_rank = int(node.get("maxRank") or 1)
        if current_rank >= max_rank:
            return False, "已点满"
        if not self._tianshu_is_unlocked(node_id):
            return False, "未解锁（需要点满前置）"
        if self._tianshu_total_points() >= self.MAX_TIANSHU_POINTS:
            return False, f"点数已满（{self.MAX_TIANSHU_POINTS}）"
        return True, ""

    def _tianshu_can_downgrade(self, node_id: str) -> tuple[bool, str]:
        current_rank = int(self._tianshu_ranks.get(node_id, 0))
        if current_rank <= 0:
            return False, "未加点"
        if current_rank == 1:
            for dep_id in self._tianshu_dependents.get(node_id, []):
                if int(self._tianshu_ranks.get(dep_id, 0)) > 0:
                    return False, "后置节点已加点，不能清零"
        return True, ""

    def _tianshu_render_summary(self) -> str:
        tree = self._tianshu_data.get(self._tianshu_tree_id or "")
        nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
        points = self._tianshu_total_points()

        stats: dict[str, dict] = {}
        special: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            rank = int(self._tianshu_ranks.get(node_id, 0))
            if rank <= 0:
                continue
            stats_by_rank = node.get("statsByRank") or []
            stat_list = []
            if isinstance(stats_by_rank, list) and 0 <= rank - 1 < len(stats_by_rank):
                stat_list = stats_by_rank[rank - 1] or []
            if isinstance(stat_list, list) and stat_list:
                for s in stat_list:
                    if not isinstance(s, dict):
                        continue
                    key = str(s.get("key") or "")
                    if not key:
                        continue
                    if key not in stats:
                        stats[key] = {"label": str(s.get("label") or key), "value": 0.0, "suffix": str(s.get("suffix") or "")}
                    val = s.get("value", 0)
                    if isinstance(val, (int, float)):
                        stats[key]["value"] = float(stats[key]["value"]) + float(val)
            else:
                desc_lines = node.get("descLines") or []
                if isinstance(desc_lines, list) and desc_lines:
                    idx = max(0, rank - 1)
                    text = str(desc_lines[idx] if idx < len(desc_lines) else (desc_lines[0] if desc_lines else ""))
                else:
                    text = ""
                if text:
                    special.append(f"{node.get('name') or node_id}：{text}")

        lines = [f"流派：{(tree or {}).get('name', self._tianshu_tree_id or '')}", f"点数：{points} / {self.MAX_TIANSHU_POINTS}", ""]
        if stats:
            lines.append("属性汇总：")
            for key in sorted(stats.keys()):
                entry = stats[key]
                val = entry.get("value", 0)
                if isinstance(val, float):
                    val_str = f"{val:.2f}".rstrip("0").rstrip(".")
                else:
                    val_str = str(val)
                lines.append(f"- {entry.get('label')}: {val_str}{entry.get('suffix')}")
            lines.append("")
        if special:
            lines.append("效果汇总：")
            for s in special:
                lines.append(f"- {s}")
        if not stats and not special:
            lines.append("还没有加点。")
        return "\n".join(lines)

    def _tianshu_switch_tree(self, tree_id: str) -> None:
        self._tianshu_ensure_loaded()
        tree = self._tianshu_data.get(tree_id)
        if not isinstance(tree, dict):
            return
        self._tianshu_tree_id = tree_id
        self._tianshu_node_by_id = {str(n.get("id")): n for n in tree.get("nodes", []) if isinstance(n, dict) and n.get("id")}
        self._tianshu_dependents = {}
        for node in self._tianshu_node_by_id.values():
            for pid in node.get("prereqs") or []:
                if not pid:
                    continue
                self._tianshu_dependents.setdefault(str(pid), []).append(str(node.get("id")))

        all_ranks = self._tianshu_load_all_ranks()
        ranks = all_ranks.get(tree_id, {})
        if not isinstance(ranks, dict):
            ranks = {}
        cleaned: dict[str, int] = {}
        for nid, val in ranks.items():
            node = self._tianshu_node_by_id.get(str(nid))
            if node is None:
                continue
            max_rank = int(node.get("maxRank") or 1)
            cleaned[str(nid)] = max(0, min(max_rank, int(val)))
        self._tianshu_ranks = cleaned
        self._tianshu_normalize_ranks()
        self._tianshu_save_state()

    @pyqtSlot(result=str)
    def tianshuInit(self) -> str:
        self._tianshu_ensure_loaded()
        if not self._tianshu_list:
            return json.dumps(
                {
                    "ok": False,
                    "error": "找不到 talents 数据目录或数据为空",
                    "trees": [],
                    "maxPoints": self.MAX_TIANSHU_POINTS,
                },
                ensure_ascii=False,
            )

        last_tree_id = None
        if self._tianshu_storage is not None:
            state = self._tianshu_storage.load()
            v = state.get("lastTreeId")
            if isinstance(v, str):
                last_tree_id = v
        if not last_tree_id or last_tree_id not in self._tianshu_data:
            last_tree_id = str(self._tianshu_list[0].get("id") or "")

        self._tianshu_switch_tree(last_tree_id)
        tree = self._tianshu_data.get(self._tianshu_tree_id or "")
        return json.dumps(
            {
                "ok": True,
                "trees": self._tianshu_list,
                "treeId": self._tianshu_tree_id,
                "tree": tree if isinstance(tree, dict) else {},
                "ranks": self._tianshu_ranks,
                "points": self._tianshu_total_points(),
                "maxPoints": self.MAX_TIANSHU_POINTS,
                "summary": self._tianshu_render_summary(),
            },
            ensure_ascii=False,
        )

    @pyqtSlot(str, result=str)
    def tianshuSelectTree(self, tree_id: str) -> str:
        tid = str(tree_id or "")
        if not tid:
            return json.dumps({"ok": False, "error": "tree_id 为空"}, ensure_ascii=False)
        self._tianshu_switch_tree(tid)
        tree = self._tianshu_data.get(self._tianshu_tree_id or "")
        return json.dumps(
            {
                "ok": True,
                "treeId": self._tianshu_tree_id,
                "tree": tree if isinstance(tree, dict) else {},
                "ranks": self._tianshu_ranks,
                "points": self._tianshu_total_points(),
                "maxPoints": self.MAX_TIANSHU_POINTS,
                "summary": self._tianshu_render_summary(),
            },
            ensure_ascii=False,
        )

    @pyqtSlot(result=str)
    def tianshuResetCurrentTree(self) -> str:
        if not self._tianshu_tree_id:
            return json.dumps({"ok": False, "error": "未选择流派"}, ensure_ascii=False)
        self._tianshu_ranks = {}
        self._tianshu_save_state()
        return json.dumps(
            {
                "ok": True,
                "treeId": self._tianshu_tree_id,
                "ranks": self._tianshu_ranks,
                "points": self._tianshu_total_points(),
                "maxPoints": self.MAX_TIANSHU_POINTS,
                "summary": self._tianshu_render_summary(),
            },
            ensure_ascii=False,
        )

    @pyqtSlot(str, result=str)
    def tianshuUpgrade(self, node_id: str) -> str:
        nid = str(node_id or "")
        ok, msg = self._tianshu_can_upgrade(nid)
        if not ok:
            return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)
        self._tianshu_ranks[nid] = int(self._tianshu_ranks.get(nid, 0)) + 1
        self._tianshu_normalize_ranks()
        self._tianshu_save_state()
        return json.dumps(
            {
                "ok": True,
                "ranks": self._tianshu_ranks,
                "points": self._tianshu_total_points(),
                "maxPoints": self.MAX_TIANSHU_POINTS,
                "summary": self._tianshu_render_summary(),
            },
            ensure_ascii=False,
        )

    @pyqtSlot(str, result=str)
    def tianshuDowngrade(self, node_id: str) -> str:
        nid = str(node_id or "")
        ok, msg = self._tianshu_can_downgrade(nid)
        if not ok:
            return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)
        next_rank = int(self._tianshu_ranks.get(nid, 0)) - 1
        if next_rank <= 0:
            self._tianshu_ranks.pop(nid, None)
        else:
            self._tianshu_ranks[nid] = next_rank
        self._tianshu_normalize_ranks()
        self._tianshu_save_state()
        return json.dumps(
            {
                "ok": True,
                "ranks": self._tianshu_ranks,
                "points": self._tianshu_total_points(),
                "maxPoints": self.MAX_TIANSHU_POINTS,
                "summary": self._tianshu_render_summary(),
            },
            ensure_ascii=False,
        )


class WebViewInterface(QWidget):
    def __init__(
        self,
        *,
        title: str = "WebView",
        desc: str = "用于承载非 Python 的工具页面（这次开始改用 React）。",
        default_hash: str = "",
        tool_id: str = "",
        rili_storage_dir: str | None = None,
        tianshu_storage_dir: str | None = None,
        tianshu_talents_dir: str | None = None,
        show_address_bar: bool = True,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.setObjectName(str(title or "webview"))
        self._default_hash = str(default_hash or "").strip()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        root.addWidget(SubtitleLabel(title))
        root.addWidget(BodyLabel(desc))

        self.reload_btn = QPushButton("刷新")
        if show_address_bar:
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(10)
            self.url_input = LineEdit()
            self.url_input.setPlaceholderText("输入 URL 或本地文件路径（可留空用内置 React 示例页）")
            self.open_btn = PrimaryPushButton("打开")
            actions.addWidget(self.url_input, 1)
            actions.addWidget(self.open_btn, 0)
            actions.addWidget(self.reload_btn, 0)
            root.addLayout(actions, 0)
        else:
            toolbar = QHBoxLayout()
            toolbar.setContentsMargins(0, 0, 0, 0)
            toolbar.setSpacing(10)
            toolbar.addStretch(1)
            toolbar.addWidget(self.reload_btn, 0)
            root.addLayout(toolbar, 0)

        self.web = QWebEngineView(self)
        self.web.setStyleSheet("background: transparent;")
        try:
            self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))
        except Exception:
            pass
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        root.addWidget(self.web, 1)

        self._channel = QWebChannel(self.web.page())
        self._bridge = WebViewBridge(
            tool_id=tool_id,
            rili_storage_dir=rili_storage_dir,
            tianshu_storage_dir=tianshu_storage_dir,
            tianshu_talents_dir=tianshu_talents_dir,
            parent=self,
        )
        self._channel.registerObject("bridge", self._bridge)
        self.web.page().setWebChannel(self._channel)

        self.reload_btn.clicked.connect(self.web.reload)
        if show_address_bar:
            self.open_btn.clicked.connect(self._open)

        self._load_default()

    def _load_default(self) -> None:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        html_path = os.path.join(base_dir, "webview_react.html")
        if os.path.isfile(html_path):
            url = QUrl.fromLocalFile(html_path)
            if self._default_hash:
                url.setFragment(self._default_hash)
            self.web.setUrl(url)
            return
        self.web.setHtml("<h3 style='color:#fff;background:#0b0f14'>webview_react.html 缺失</h3>")

    def _open(self) -> None:
        raw = str(self.url_input.text() or "").strip()
        if not raw:
            self._load_default()
            return

        if raw.startswith("http://") or raw.startswith("https://"):
            self.web.setUrl(QUrl(raw))
            return

        if raw.startswith("file:///"):
            self.web.setUrl(QUrl(raw))
            return

        if os.path.isabs(raw) and os.path.exists(raw):
            self.web.setUrl(QUrl.fromLocalFile(os.path.abspath(raw)))
            return

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        guess = os.path.join(base_dir, raw)
        if os.path.exists(guess):
            self.web.setUrl(QUrl.fromLocalFile(os.path.abspath(guess)))
            return

        InfoBar.error("无法打开", "请输入可访问的 URL 或正确的本地路径", parent=self, position=InfoBarPosition.TOP, duration=2200)


class MainWindow(FluentWindow):
    def __init__(self, app_name: str, version: str, rili_storage_dir: str, tianshu_storage_dir: str, tianshu_talents_dir: str | None):
        super().__init__()
        self.setWindowTitle(f"{app_name} v{version}")
        self.resize(1180, 720)

        danqing = DanqingInterface(self)
        self.addSubInterface(danqing, FluentIcon.APPLICATION, "丹青模拟器", position=NavigationItemPosition.TOP)

        rili_web = WebViewInterface(
            title="游戏日历",
            desc="离线版（React）：任务管理 + 活动日历",
            default_hash="rili",
            tool_id="rili",
            rili_storage_dir=rili_storage_dir,
            show_address_bar=False,
            parent=self,
        )
        self.addSubInterface(rili_web, FluentIcon.CALENDAR, "游戏日历", position=NavigationItemPosition.TOP)

        tianshu_web = WebViewInterface(
            title="天书模拟器",
            desc="非主要用 Python：用 WebView 承载（React）。",
            default_hash="tianshu",
            tool_id="tianshu",
            tianshu_storage_dir=tianshu_storage_dir,
            tianshu_talents_dir=tianshu_talents_dir,
            show_address_bar=False,
            parent=self,
        )
        self.addSubInterface(tianshu_web, FluentIcon.DOCUMENT, "天书模拟器", position=NavigationItemPosition.TOP)

        about = PlaceholderInterface("关于", f"{app_name} {version}", self)
        about.setObjectName("about")
        self.addSubInterface(about, FluentIcon.INFO, "关于", position=NavigationItemPosition.BOTTOM)


def start(app_name: str = "OK-ZhuXian World", version: str = "0.1.0"):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    extra_qss = (
        "QScrollBar:vertical{background:rgba(255,255,255,0.06);width:10px;margin:10px 3px 10px 3px;border-radius:5px;}"
        "QScrollBar::handle:vertical{background:rgba(0,229,255,0.55);min-height:28px;border-radius:5px;}"
        "QScrollBar::handle:vertical:hover{background:rgba(0,229,255,0.80);}"
        "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}"
        "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        "QScrollBar:horizontal{background:rgba(255,255,255,0.06);height:10px;margin:3px 10px 3px 10px;border-radius:5px;}"
        "QScrollBar::handle:horizontal{background:rgba(0,229,255,0.55);min-width:28px;border-radius:5px;}"
        "QScrollBar::handle:horizontal:hover{background:rgba(0,229,255,0.80);}"
        "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0px;}"
        "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        "QTextEdit,QPlainTextEdit{background:#0B0F14;color:#E0E0E0;}"
    )
    app.setStyleSheet((app.styleSheet() or "") + extra_qss)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rili_storage_dir = os.path.join(project_root, "tools", "rili", "storage")
    tianshu_storage_dir = os.path.join(project_root, "tools", "tianshu", "storage")
    tianshu_talents_dir = find_tianshu_talents_dir(project_root)
    w = MainWindow(
        app_name=app_name,
        version=version,
        rili_storage_dir=rili_storage_dir,
        tianshu_storage_dir=tianshu_storage_dir,
        tianshu_talents_dir=tianshu_talents_dir,
    )
    w.show()
    app.exec()
