import os
import sys
import time
import traceback
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TextEdit,
)


IMG_AIM = "stepA.png"
IMG_FIRE = "redpoint1.png"
IMG_MAP = "stepB.png"
IMG_ENTER = "stepC.png"


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _set_dpi_aware() -> None:
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        return


def _load_deps():
    import cv2
    import numpy as np
    import mss
    import pydirectinput

    pydirectinput.PAUSE = 0.001
    pydirectinput.FAILSAFE = False

    return cv2, np, mss, pydirectinput


class HongjunWorker(QObject):
    log = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal(float)
    failed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, *, assets_dir: str, monitor_index: int = 1):
        super().__init__()
        self.assets_dir = assets_dir
        self.monitor_index = int(monitor_index or 1)
        self._running = False

        self._cv2 = None
        self._np = None
        self._mss = None
        self._pydirectinput = None

        self.monitor = {"left": 0, "top": 0, "width": 2560, "height": 1440}
        self.scale_factor = 1.0
        self.templates = {}
        self._scaled_templates: dict[str, dict[float, dict[str, Any]]] = {}
        self._is_standard_resolution = False
        self._th_entry = 0.62
        self._th_fire = 0.72
        self._th_map = 0.70
        self._th_enter = 0.70

        self.status_code = 0
        self._entry_candidate_pos: tuple[int, int] | None = None
        self._entry_candidate_hits = 0
        self._entry_candidate_updated_at = 0.0
        self.dynamic_red_roi = None
        self.last_step3_action_time = 0.0
        self.last_step3_log_time = 0.0
        self.last_step1_wait_log_time = 0.0
        self.aim_pos = None
        self.mission_start_time = None
        self._step3_threshold = 0.7
        self._step3_center_2k = (1510, 476)

    def stop(self):
        self._running = False
        self.status.emit("已停止")

    def _emit_log(self, msg: str):
        t = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log.emit(f"[{t}] {msg}")

    def _resource_path(self, filename: str) -> str | None:
        p1 = os.path.join(self.assets_dir, filename)
        if os.path.exists(p1):
            return p1
        if os.path.exists(filename):
            return filename
        if hasattr(sys, "_MEIPASS"):
            p2 = os.path.join(getattr(sys, "_MEIPASS"), filename)
            if os.path.exists(p2):
                return p2
        return None

    def _is_standard_monitor(self, w: int, h: int) -> bool:
        try:
            w = int(w)
            h = int(h)
        except Exception:
            return False
        return (w, h) in {(1920, 1080), (2560, 1440), (3840, 2160)}

    def _setup_thresholds(self):
        w = int(self.monitor.get("width") or 0)
        h = int(self.monitor.get("height") or 0)
        self._is_standard_resolution = self._is_standard_monitor(w, h)
        if self._is_standard_resolution:
            self._th_entry = 0.80
            self._th_fire = 0.80
            self._th_map = 0.80
            self._th_enter = 0.80
        else:
            self._th_entry = 0.62
            self._th_fire = 0.72
            self._th_map = 0.70
            self._th_enter = 0.70
        mode = "标准" if self._is_standard_resolution else "非标准(自适应)"
        self._emit_log(f"阈值模式：{mode} | entry={self._th_entry:.2f} fire={self._th_fire:.2f} map={self._th_map:.2f} enter={self._th_enter:.2f}")

    def _init_monitor(self):
        with self._mss.mss() as s:
            idx = int(self.monitor_index or 1)
            if idx < 1 or idx >= len(s.monitors):
                idx = 1
            self.monitor_index = idx
            self.monitor = s.monitors[idx]
        base_w, base_h = 2560, 1440
        self.scale_factor = min(self.monitor["width"] / base_w, self.monitor["height"] / base_h)
        self._emit_log(f"显示器：#{self.monitor_index} | 偏移=({self.monitor.get('left')},{self.monitor.get('top')})")
        self._setup_thresholds()

    def _load_images(self):
        required = [IMG_AIM, IMG_FIRE, IMG_MAP, IMG_ENTER]
        for name in required:
            real_path = self._resource_path(name)
            if not real_path:
                raise FileNotFoundError(f"缺失图片: {name}")
            img = self._cv2.imread(real_path)
            if img is None:
                raise ValueError(f"图片损坏: {name}")
            gray = self._cv2.cvtColor(img, self._cv2.COLOR_BGR2GRAY)
            self.templates[name] = {"data": gray, "w": img.shape[1], "h": img.shape[0]}
            self._scaled_templates[name] = {}
            self._emit_log(f"加载图片：{name} -> {real_path} ({img.shape[1]}x{img.shape[0]})")

    def _fast_click(self, x: int, y: int):
        self._pydirectinput.moveTo(int(x), int(y))
        self._pydirectinput.click()

    def _heavy_click(self, x: int, y: int):
        self._pydirectinput.moveTo(int(x), int(y))
        time.sleep(0.1)
        for _ in range(2):
            self._pydirectinput.mouseDown()
            time.sleep(0.15)
            self._pydirectinput.mouseUp()
            time.sleep(0.05)

    def _candidate_scales(self, *, include: list[float]) -> list[float]:
        scales: list[float] = []
        for s in include:
            try:
                v = float(s)
            except Exception:
                continue
            if v <= 0:
                continue
            v = max(0.55, min(1.8, v))
            v = round(v, 2)
            if v not in scales:
                scales.append(v)
        scales.sort()
        return scales

    def _get_scaled_template(self, img_name: str, scale: float) -> dict[str, Any]:
        cache = self._scaled_templates.get(img_name)
        if cache is None:
            cache = {}
            self._scaled_templates[img_name] = cache
        key = round(float(scale), 2)
        cached = cache.get(key)
        if cached is not None:
            return cached

        base = self.templates[img_name]
        gray = base["data"]
        h0, w0 = gray.shape[:2]
        if abs(key - 1.0) < 1e-6:
            out = {"data": gray, "w": int(w0), "h": int(h0), "scale": key}
            cache[key] = out
            return out

        new_w = max(1, int(round(w0 * key)))
        new_h = max(1, int(round(h0 * key)))
        scaled = self._cv2.resize(gray, (new_w, new_h), interpolation=self._cv2.INTER_AREA)
        out = {"data": scaled, "w": int(new_w), "h": int(new_h), "scale": key}
        cache[key] = out
        return out

    def _find_fast(self, sct, img_name: str, roi: dict | None = None, *, threshold: float = 0.8, multi_scale: bool = False):
        scan_area = roi if roi else self.monitor
        sct_img = sct.grab(scan_area)
        screen_gray = self._cv2.cvtColor(self._np.array(sct_img), self._cv2.COLOR_BGRA2GRAY)
        offset_x = scan_area["left"]
        offset_y = scan_area["top"]

        if not multi_scale:
            tpl = self._get_scaled_template(img_name, 1.0)
            res = self._cv2.matchTemplate(screen_gray, tpl["data"], self._cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = self._cv2.minMaxLoc(res)
            if mv >= threshold:
                return (ml[0] + tpl["w"] // 2 + offset_x, ml[1] + tpl["h"] // 2 + offset_y), float(mv)
            return None, float(mv)

        include = [1.0, self.scale_factor, (1.0 / self.scale_factor if self.scale_factor else 1.0)]
        include.extend([x + 0.1 for x in include])
        include.extend([x - 0.1 for x in include])
        scales = self._candidate_scales(include=include)

        best_mv = -1.0
        best_ml = (0, 0)
        best_tpl = None
        for s in scales:
            tpl = self._get_scaled_template(img_name, s)
            if tpl["w"] <= 1 or tpl["h"] <= 1:
                continue
            if tpl["w"] > screen_gray.shape[1] or tpl["h"] > screen_gray.shape[0]:
                continue
            res = self._cv2.matchTemplate(screen_gray, tpl["data"], self._cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = self._cv2.minMaxLoc(res)
            if mv > best_mv:
                best_mv = float(mv)
                best_ml = ml
                best_tpl = tpl

        if best_tpl is None:
            return None, 0.0
        if best_mv >= threshold:
            return (best_ml[0] + best_tpl["w"] // 2 + offset_x, best_ml[1] + best_tpl["h"] // 2 + offset_y), float(best_mv)
        return None, float(best_mv)

    def _calculate_red_roi(self, aim_pos):
        w = self.templates[IMG_AIM]["w"]
        h = self.templates[IMG_AIM]["h"]
        btn_left = aim_pos[0] - w // 2
        btn_top = aim_pos[1] - h // 2
        padding = 30
        roi_left = int(btn_left + w * 0.4) - padding
        roi_top = int(btn_top) - padding
        roi_w = int(w * 0.6) + (padding * 2)
        roi_h = int(h * 0.75) + (padding * 2)
        self.dynamic_red_roi = {"left": max(0, roi_left), "top": max(0, roi_top), "width": roi_w, "height": roi_h}

    def _get_step3_center(self) -> tuple[int, int]:
        x = int(self.monitor.get("left") or 0) + int(self._step3_center_2k[0] * float(self.scale_factor or 1.0))
        y = int(self.monitor.get("top") or 0) + int(self._step3_center_2k[1] * float(self.scale_factor or 1.0))
        return x, y

    def _get_step3_roi(self) -> dict:
        cx, cy = self._get_step3_center()
        enter = self.templates.get(IMG_ENTER) or {}
        w = int(enter.get("w") or 320)
        h = int(enter.get("h") or 140)

        pad_x = int(w * 0.6) + 60
        pad_y = int(h * 0.8) + 60

        left = cx - (w // 2) - pad_x
        top = cy - (h // 2) - pad_y
        right = cx + (w // 2) + pad_x
        bottom = cy + (h // 2) + pad_y

        mon_left = int(self.monitor.get("left") or 0)
        mon_top = int(self.monitor.get("top") or 0)
        mon_right = mon_left + int(self.monitor.get("width") or 0)
        mon_bottom = mon_top + int(self.monitor.get("height") or 0)

        left = max(mon_left, left)
        top = max(mon_top, top)
        right = min(mon_right, right)
        bottom = min(mon_bottom, bottom)

        return {"left": int(left), "top": int(top), "width": int(max(1, right - left)), "height": int(max(1, bottom - top))}

    def _is_step1_fallback_allowed(self) -> bool:
        now = datetime.now()
        sec = now.hour * 3600 + now.minute * 60 + now.second
        windows = [
            (12 * 3600 + 55 * 60 + 1, 14 * 3600 + 0 * 60 + 0),
            (19 * 3600 + 55 * 60 + 1, 21 * 3600 + 0 * 60 + 0),
        ]
        return any(start <= sec <= end for start, end in windows)

    def run(self):
        started_at = time.time()
        self._running = True
        self.status_code = 0
        self._entry_candidate_pos = None
        self._entry_candidate_hits = 0
        self._entry_candidate_updated_at = 0.0
        self.dynamic_red_roi = None
        self.aim_pos = None
        self.mission_start_time = None
        self.last_step3_action_time = 0.0
        self.last_step3_log_time = 0.0
        self.last_step1_wait_log_time = 0.0
        self._step3_threshold = float(self._th_enter)

        terminal = None
        try:
            _set_dpi_aware()
            self._cv2, self._np, self._mss, self._pydirectinput = _load_deps()

            self.status.emit("初始化屏幕与资源…")
            self._init_monitor()
            self._load_images()

            self._emit_log(f"屏幕: {self.monitor['width']}x{self.monitor['height']} | 缩放系数: {self.scale_factor:.2f}")
            self._emit_log("✅ 核心资源加载完毕")
        except Exception:
            terminal = "failed"
            self._running = False
            self.failed.emit(traceback.format_exc())
            return

        try:
            with self._mss.mss() as sct:
                while self._running:
                    if self.status_code == 0:
                        self.status.emit("🔍 全屏搜索入口…")
                        self.mission_start_time = None
                        self._step3_threshold = float(self._th_enter)
                        pos, mv = self._find_fast(sct, IMG_AIM, threshold=self._th_entry, multi_scale=True)
                        if pos:
                            now = time.time()
                            if now - self._entry_candidate_updated_at > 2.0:
                                self._entry_candidate_pos = None
                                self._entry_candidate_hits = 0
                            self._entry_candidate_updated_at = now

                            if self._entry_candidate_pos is None:
                                self._entry_candidate_pos = (int(pos[0]), int(pos[1]))
                                self._entry_candidate_hits = 1
                                self._emit_log(f"入口候选：{pos} conf={mv:.2f}（二次确认中）")
                                time.sleep(0.12)
                                continue

                            dx = int(pos[0]) - int(self._entry_candidate_pos[0])
                            dy = int(pos[1]) - int(self._entry_candidate_pos[1])
                            if (dx * dx + dy * dy) <= (26 * 26):
                                self._entry_candidate_hits += 1
                            else:
                                self._entry_candidate_pos = (int(pos[0]), int(pos[1]))
                                self._entry_candidate_hits = 1
                                self._emit_log(f"入口候选漂移：{pos} conf={mv:.2f}（重新确认）")
                                time.sleep(0.12)
                                continue

                            if self._entry_candidate_hits >= 2:
                                self._emit_log("✅ 锁定入口 -> 死守模式")
                                self._pydirectinput.moveTo(pos[0], pos[1])
                                self.aim_pos = pos
                                self._calculate_red_roi(pos)
                                self.status_code = 1
                                self._entry_candidate_pos = None
                                self._entry_candidate_hits = 0
                                self._entry_candidate_updated_at = 0.0
                                time.sleep(0.1)
                            else:
                                time.sleep(0.12)
                        else:
                            if mv > 0.35 and time.time() - self.last_step1_wait_log_time > 2.0:
                                self._emit_log(f"入口相似度偏低：{mv:.2f}（没匹配到）")
                                self.last_step1_wait_log_time = time.time()
                            time.sleep(0.2)

                    elif self.status_code == 1:
                        self.status.emit("⚡ 死守点击…")
                        roi_to_use = self.dynamic_red_roi if self.dynamic_red_roi else self.monitor
                        fire_pos, _ = self._find_fast(sct, IMG_FIRE, roi=roi_to_use, threshold=self._th_fire, multi_scale=False)

                        if fire_pos:
                            if self.mission_start_time is None:
                                self.mission_start_time = time.time()
                            self._emit_log(">>> [Step 1] 红点触发")
                            self._fast_click(fire_pos[0], fire_pos[1])
                            time.sleep(0.05)
                            self.status_code = 2
                            continue

                        if self.aim_pos and self._is_step1_fallback_allowed():
                            if self.mission_start_time is None:
                                self.mission_start_time = time.time()
                            self._emit_log(">>> [Step 1] 兜底直点")
                            self._fast_click(self.aim_pos[0], self.aim_pos[1])
                            time.sleep(0.05)
                            self.status_code = 2
                            continue

                        now = time.time()
                        if now - self.last_step1_wait_log_time > 5.0:
                            self._emit_log("Step 1 等待开放时间或红点…")
                            self.last_step1_wait_log_time = now
                        time.sleep(0.2)

                    elif self.status_code == 2:
                        self.status.emit("🗺️ 寻找地图…")
                        pos, _ = self._find_fast(sct, IMG_MAP, threshold=self._th_map, multi_scale=True)
                        if pos:
                            self._emit_log(">>> [Step 2] 点击地图")
                            self._fast_click(pos[0], pos[1])
                            time.sleep(0.05)
                            self.status_code = 3
                            self._step3_threshold = float(self._th_enter)

                    elif self.status_code == 3:
                        self.status.emit("🔥 暴力排队中…")
                        step3_roi = self._get_step3_roi()
                        pos, conf = self._find_fast(sct, IMG_ENTER, roi=step3_roi, threshold=self._step3_threshold, multi_scale=True)
                        if pos:
                            now = time.time()
                            if now - self.last_step3_action_time < 0.2:
                                continue

                            self._emit_log(f">>> [Step 3] 锁定目标 {pos} (conf:{conf:.2f})")
                            self._heavy_click(pos[0], pos[1])
                            self.last_step3_action_time = now

                            wait_success = False
                            for _ in range(6):
                                if not self._running:
                                    break
                                time.sleep(0.1)
                                check_roi_dynamic = {"left": max(0, pos[0] - 100), "top": max(0, pos[1] - 50), "width": 200, "height": 100}
                                still_pos, _ = self._find_fast(sct, IMG_ENTER, roi=check_roi_dynamic, threshold=self._step3_threshold, multi_scale=True)
                                if not still_pos:
                                    wait_success = True
                                    break

                            if wait_success:
                                end_time = time.time()
                                duration = (end_time - self.mission_start_time) if self.mission_start_time else 0.0
                                self._emit_log(f"🎉 任务完成！总耗时: {duration:.3f} 秒")
                                self.status.emit(f"完成 (耗时 {duration:.2f}s)")
                                self._running = False
                                self.status_code = 0
                                self.dynamic_red_roi = None
                                terminal = "finished"
                                self.finished.emit(duration)
                                return

                            if now - self.last_step3_log_time > 1.0:
                                self._emit_log("⚠️ 服务器卡顿/按钮未消失，继续重试…")
                                self.last_step3_log_time = now
                        else:
                            self._step3_threshold = max(0.6, float(self._step3_threshold) - 0.01)
                            if conf > 0.5:
                                self._emit_log(f"Step 3 搜索中… 相似度: {conf:.2f}")

        except Exception:
            terminal = "failed"
            self._running = False
            self.failed.emit(traceback.format_exc())
            return
        finally:
            if self._running is False:
                elapsed = time.time() - started_at
                self._emit_log(f"引擎退出，用时 {elapsed:.2f}s")
            if terminal is None:
                self.stopped.emit()


class HongjunInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("hongjun")

        self._thread: QThread | None = None
        self._worker: HongjunWorker | None = None
        self._monitors_loaded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(SubtitleLabel("鸿钧"), 0)
        header_layout.addStretch(1)
        help_btn = PushButton("?")
        help_btn.setFixedSize(26, 26)
        help_btn.setStyleSheet(
            "QPushButton{color:#E0E0E0;background:rgba(255,255,255,0.06);border:1px solid rgba(0,229,255,0.22);border-radius:13px;}"
            "QPushButton:hover{background:rgba(0,229,255,0.10);border:1px solid rgba(0,229,255,0.55);}"
            "QPushButton:pressed{background:rgba(0,229,255,0.16);border:1px solid rgba(0,229,255,0.70);}"
        )
        help_btn.clicked.connect(self._show_help)
        header_layout.addWidget(help_btn, 0)
        root.addWidget(header, 0)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        self.status_lbl = BodyLabel("状态：等待指令")
        card_layout.addWidget(self.status_lbl, 0)

        monitor_row = QHBoxLayout()
        monitor_row.setSpacing(10)
        monitor_row.addWidget(BodyLabel("显示器"), 0)
        self.monitor_combo = ComboBox()
        self.monitor_combo.addItem("1（默认）")
        self.monitor_combo.setItemData(0, 1)
        monitor_row.addWidget(self.monitor_combo, 0)
        monitor_row.addStretch(1)
        card_layout.addLayout(monitor_row, 0)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = PrimaryPushButton("启动挂机")
        self.stop_btn = PushButton("停止")
        self.stop_btn.setEnabled(False)

        btn_row.addWidget(self.start_btn, 0)
        btn_row.addWidget(self.stop_btn, 0)
        btn_row.addStretch(1)

        card_layout.addLayout(btn_row, 0)

        root.addWidget(card, 0)

        self.log_view = TextEdit()
        self.log_view.setReadOnly(True)
        root.addWidget(self.log_view, 1)

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)

    def _show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("鸿钧 - 使用说明")
        dialog.setModal(True)
        dialog.resize(620, 420)
        dialog.setStyleSheet(
            "QDialog{background:#121212;}"
            "QLabel{color:#E0E0E0;}"
            "QTextEdit,QPlainTextEdit{background:#0B0F14;color:#E0E0E0;border:1px solid rgba(0,229,255,0.16);border-radius:12px;padding:12px;}"
        )
        root = QVBoxLayout(dialog)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        title = SubtitleLabel("鸿钧 - 使用说明")
        title.setStyleSheet("color:#E0E0E0;")
        root.addWidget(title, 0)
        text = TextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            "\n".join(
                [
                    "1. 如遇到无法截图/点击，再用管理员身份运行工具箱。",
                    "2. 选择正确的显示器，然后点击“启动挂机”。",
                    "3. 运行中可点击“停止”中断任务。",
                    "4. 首次使用请先在虚拟环境安装 requirements.txt 依赖。",
                ]
            )
        )
        root.addWidget(text, 1)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        ok_btn = PrimaryPushButton("关闭")
        btn_row.addWidget(ok_btn, 0)
        root.addLayout(btn_row, 0)
        ok_btn.clicked.connect(dialog.accept)
        dialog.exec()

    def _refresh_monitors(self):
        try:
            import mss

            with mss.mss() as s:
                monitors = s.monitors
            items = []
            for i in range(1, len(monitors)):
                m = monitors[i]
                label = f"{i}: {m.get('width')}x{m.get('height')}"
                items.append((label, i))
            if not items:
                return
            cur = int(self.monitor_combo.currentData() or 1)
            self.monitor_combo.clear()
            for label, idx in items:
                row = self.monitor_combo.count()
                self.monitor_combo.addItem(label)
                self.monitor_combo.setItemData(row, idx)
            for i in range(self.monitor_combo.count()):
                if int(self.monitor_combo.itemData(i) or 0) == cur:
                    self.monitor_combo.setCurrentIndex(i)
                    break
            self._monitors_loaded = True
        except Exception:
            return

    def _append_log(self, line: str):
        self.log_view.append(str(line or "").rstrip())

    def _set_status(self, text: str):
        self.status_lbl.setText(f"状态：{str(text or '').strip()}")

    def _cleanup_thread(self):
        self._thread = None
        self._worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_start(self):
        if self._thread is not None:
            return

        if not _is_admin():
            InfoBar.warning(
                "未使用管理员权限",
                "若出现无法截图/点击的情况，再用“管理员身份运行”启动工具箱",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )

        try:
            _load_deps()
        except Exception as e:
            InfoBar.error("缺少依赖", f"{e}\n请先在 .venv 里安装 requirements.txt", parent=self, position=InfoBarPosition.TOP, duration=5000)
            return

        if not self._monitors_loaded:
            self._refresh_monitors()

        assets_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
        monitor_index = int(self.monitor_combo.currentData() or 1)

        worker = HongjunWorker(assets_dir=assets_dir, monitor_index=monitor_index)
        thread = QThread(self)

        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.log.connect(self._append_log)
        worker.status.connect(self._set_status)

        worker.finished.connect(lambda _sec: InfoBar.success("完成", "鸿钧任务已完成", parent=self, position=InfoBarPosition.TOP, duration=1800))
        worker.failed.connect(lambda err: InfoBar.error("鸿钧出错", str(err or "").strip(), parent=self, position=InfoBarPosition.TOP, duration=6000))

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.stopped.connect(thread.quit)
        thread.finished.connect(self._cleanup_thread)

        self._worker = worker
        self._thread = thread

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_status("启动中…")
        thread.start()

    def _on_stop(self):
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.quit()
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        try:
            self._on_stop()
        except Exception:
            pass
        return super().closeEvent(event)
