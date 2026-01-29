import asyncio
import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import websockets


@dataclass(frozen=True)
class BackendUrls:
    http_url: str
    ws_url: str


_ROOT = Path(__file__).resolve().parent
_FRONTEND_DIR = _ROOT / "frontend"
_HTTP_APP_CONFIG: dict | None = None


def _find_free_port(host: str) -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(_FRONTEND_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/__app_config":
            payload = _HTTP_APP_CONFIG or {}
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()


def _pack(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _user_storage_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / "AppData" / "Local"
    return root / "OK-ZhuXian World" / "storage"


def _default_rili_activity_definitions() -> list[dict]:
    return [
        {
            "id": "guild_meditate",
            "name": "帮派打坐&补灵",
            "type": "daily",
            "playstyles": ["PVX"],
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
            "playstyles": ["PVP", "GVG"],
            "schedule": [
                {"day": 1, "time": "19:00"},
                {"day": 3, "time": "19:00"},
                {"day": 5, "time": "19:00"},
            ],
        },
        {
            "id": "world_boss",
            "name": "世界BOSS",
            "type": "once_weekly",
            "playstyles": ["PVE"],
            "schedule": [
                {"day": 2, "time": "19:00"},
                {"day": 4, "time": "19:00"},
                {"day": 6, "time": "19:00"},
            ],
        },
        {
            "id": "pvp_luan_wu",
            "name": "乱武",
            "type": "unlimited",
            "playstyles": ["PVP"],
            "schedule": [
                {"day": 2, "time": "20:00"},
                {"day": 4, "time": "20:00"},
            ],
        },
        {
            "id": "guild_league",
            "name": "帮派联赛",
            "type": "unlimited",
            "playstyles": ["GVG"],
            "schedule": [
                {"day": 5, "time": "20:00"},
                {"day": 5, "time": "21:00"},
            ],
        },
        {
            "id": "hong_jun",
            "name": "鸿钧",
            "type": "unlimited",
            "playstyles": ["PVP"],
            "schedule": [
                {"day": 6, "time": "13:00"},
                {"day": 6, "time": "20:00"},
                {"day": 7, "time": "13:00"},
                {"day": 7, "time": "20:00"},
            ],
        },
    ]


def _tianshu_data_dir() -> Path | None:
    project_root = _ROOT.parent
    zxsj_dir = project_root.parent / "zxsj" / "src" / "data"
    talents_dir = zxsj_dir / "talents"
    if talents_dir.exists():
        return talents_dir
    return None


def _split_desc_lines(desc: Any, max_rank: int) -> list[str]:
    if not isinstance(desc, str):
        return ["" for _ in range(max_rank)]
    pieces = [s.strip() for s in re.split(r";\s*\n|\n|；", desc) if s and s.strip()]
    if max_rank <= 1:
        return [pieces[0] if pieces else desc]
    if len(pieces) >= max_rank:
        return pieces[:max_rank]
    head = pieces[0] if pieces else desc
    return [pieces[i] if i < len(pieces) else head for i in range(max_rank)]


def _normalize_stat(stat: Any) -> dict | None:
    if not isinstance(stat, dict):
        return None
    key = str(stat.get("type_key") or stat.get("type") or "unknown")
    label = str(stat.get("type") or key)
    display = str(stat.get("display_string") or "")
    suffix = "%" if "%" in display else ""
    value = stat.get("value", 0)
    if suffix == "%" and isinstance(value, (int, float)) and value <= 1:
        value = round(float(value) * 100, 4)
    return {"key": key, "label": label, "value": value, "suffix": suffix}


def _normalize_stats_by_rank(stats: Any, max_rank: int) -> list[list[dict]]:
    result: list[list[dict]] = [[] for _ in range(max_rank)]
    if not isinstance(stats, list) or not stats:
        return result
    is_nested = isinstance(stats[0], list)
    normalized = stats if is_nested else [stats]
    for i in range(max_rank):
        rank_stats = normalized[i] if i < len(normalized) else (normalized[0] if normalized else [])
        if not isinstance(rank_stats, list):
            rank_stats = []
        items = []
        for s in rank_stats:
            ns = _normalize_stat(s)
            if ns is not None and ns.get("key"):
                items.append(ns)
        result[i] = items
    return result


def _build_tianshu_tree_data(tree_id: str, data: list[dict]) -> dict:
    first = data[0] if data else {}
    profession = str(first.get("class") or "未知")
    sub_class = str(first.get("sub_class") or "未知")

    nodes = []
    prereq_map: dict[str, list[str]] = {}
    for item in data:
        pid = str(item.get("talent_point_id"))
        for child in item.get("child") or []:
            child_id = str((child or {}).get("child_id"))
            if not child_id:
                continue
            prereq_map.setdefault(child_id, []).append(pid)

    for item in data:
        node_id = str(item.get("talent_point_id"))
        max_rank = int(item.get("talent_point_max") or 1)
        row_index = int(item.get("row_index") or 1)
        col_index = int(item.get("col_index") or 1)
        nodes.append(
            {
                "id": node_id,
                "name": item.get("talent_point_name") or node_id,
                "maxRank": max_rank,
                "rowIndex": row_index,
                "colIndex": col_index,
                "x": (row_index - 1) * 120 + 60,
                "y": (col_index - 1) * 100 + 60,
                "prereqs": prereq_map.get(node_id, []),
                "descLines": _split_desc_lines(item.get("talent_point_desc"), max_rank),
                "statsByRank": _normalize_stats_by_rank(item.get("stats"), max_rank),
            }
        )

    max_points = sum(int(n.get("maxRank") or 0) for n in nodes)
    return {
        "id": tree_id,
        "name": f"{profession}-{sub_class}",
        "profession": profession,
        "subClass": sub_class,
        "maxPoints": max_points,
        "nodes": nodes,
    }


class _TianshuRepo:
    def __init__(self):
        self._trees: dict[str, dict] | None = None

    def list_trees(self) -> list[dict]:
        trees = self._ensure_loaded()
        out = []
        for tree_id, tree in trees.items():
            out.append(
                {
                    "id": tree_id,
                    "name": tree.get("name"),
                    "profession": tree.get("profession"),
                    "subClass": tree.get("subClass"),
                }
            )
        out.sort(key=lambda x: (str(x.get("profession") or ""), str(x.get("subClass") or ""), str(x.get("id") or "")))
        return out

    def get_tree(self, tree_id: str) -> dict:
        trees = self._ensure_loaded()
        tree = trees.get(tree_id)
        if not tree:
            raise ValueError(f"未知天书流派: {tree_id}")
        return tree

    def _ensure_loaded(self) -> dict[str, dict]:
        if self._trees is not None:
            return self._trees

        talents_dir = _tianshu_data_dir()
        if talents_dir is None:
            self._trees = {}
            return self._trees

        trees: dict[str, dict] = {}
        for p in sorted(talents_dir.glob("*.json")):
            tree_id = p.stem
            data = _load_json(p, [])
            if not isinstance(data, list) or not data:
                continue
            trees[tree_id] = _build_tianshu_tree_data(tree_id, data)

        self._trees = trees
        return trees


class Backend:
    def __init__(self, *, host: str = "127.0.0.1", http_port: int = 0, ws_port: int = 0):
        self.host = host
        self.http_port = int(http_port) if http_port else _find_free_port(host)
        self.ws_port = int(ws_port) if ws_port else _find_free_port(host)

        self.urls = BackendUrls(
            http_url=f"http://{self.host}:{self.http_port}/",
            ws_url=f"ws://{self.host}:{self.ws_port}/",
        )

        self._clients: set = set()
        self._httpd: ThreadingHTTPServer | None = None
        self._stop_event = threading.Event()
        self._http_thread: threading.Thread | None = None

        self._state = {
            "activeNav": "home",
            "logs": [],
        }
        self._tianshu = _TianshuRepo()

    def stop(self) -> None:
        self._stop_event.set()
        httpd = self._httpd
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass

    def _start_http(self) -> None:
        global _HTTP_APP_CONFIG
        _HTTP_APP_CONFIG = {"http": self.urls.http_url, "ws": self.urls.ws_url}
        os.chdir(str(_FRONTEND_DIR))
        self._httpd = ThreadingHTTPServer((self.host, self.http_port), _Handler)
        self._httpd.serve_forever()

    def _append_log(self, level: str, message: str) -> None:
        entry = {"id": str(uuid4()), "level": level, "message": message}
        logs = list(self._state.get("logs", []))
        logs.append(entry)
        if len(logs) > 200:
            logs = logs[-200:]
        self._state["logs"] = logs

    async def _broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        raw = _pack(payload)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _rpc(self, method: str, params: dict) -> Any:
        if method == "app.getInfo":
            project_root = _ROOT.parent
            app_cfg = _load_json(project_root / "config" / "app.json", {})
            tools_cfg = _load_json(project_root / "config" / "tools.json", [])
            return {"app": app_cfg, "tools": tools_cfg, "urls": {"http": self.urls.http_url, "ws": self.urls.ws_url}}

        if method == "app.getState":
            return dict(self._state)

        if method == "nav.setActive":
            key = str(params.get("key", "")).strip() or "home"
            self._state["activeNav"] = key
            await self._broadcast({"type": "event", "event": "state.changed", "data": {"activeNav": key}})
            return {"ok": True}

        if method == "log.add":
            level = str(params.get("level", "info")).strip() or "info"
            message = str(params.get("message", "")).strip()
            if message:
                self._append_log(level, message)
                await self._broadcast({"type": "event", "event": "log.append", "data": {"entry": self._state["logs"][-1]}})
            return {"ok": True}

        if method == "tianshu.listTrees":
            return {"trees": self._tianshu.list_trees(), "maxPoints": 31}

        if method == "tianshu.getTree":
            tree_id = str(params.get("treeId") or "").strip()
            if not tree_id:
                raise ValueError("缺少 treeId")
            return {"tree": self._tianshu.get_tree(tree_id)}

        if method == "tianshu.getRanks":
            tree_id = str(params.get("treeId") or "").strip()
            if not tree_id:
                raise ValueError("缺少 treeId")
            p = _user_storage_dir() / "tianshu"
            p.mkdir(parents=True, exist_ok=True)
            ranks_path = p / f"ranks_{tree_id}.json"
            ranks = _load_json(ranks_path, {})
            if not isinstance(ranks, dict):
                ranks = {}
            return {"treeId": tree_id, "ranks": ranks}

        if method == "tianshu.saveRanks":
            tree_id = str(params.get("treeId") or "").strip()
            ranks = params.get("ranks")
            if not tree_id:
                raise ValueError("缺少 treeId")
            if not isinstance(ranks, dict):
                raise ValueError("ranks 必须是对象")
            clean: dict[str, int] = {}
            for k, v in ranks.items():
                kid = str(k)
                try:
                    iv = int(v)
                except Exception:
                    continue
                if iv <= 0:
                    continue
                clean[kid] = iv
            p = _user_storage_dir() / "tianshu"
            p.mkdir(parents=True, exist_ok=True)
            ranks_path = p / f"ranks_{tree_id}.json"
            ranks_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "treeId": tree_id}

        if method == "rili.getTaskManager":
            storage_dir = _user_storage_dir() / "rili"
            path = storage_dir / "game-task-manager-v1.json"
            raw = _load_json(path, None)
            if isinstance(raw, dict) and isinstance(raw.get("roles"), list) and raw.get("activeRoleId") is not None:
                return raw

            default_tasks = {
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

            role_id = "role_default"
            default_role = {
                "id": role_id,
                "name": "默认角色",
                "dailyTasks": [{**t, "completed": False} for t in default_tasks["daily"]],
                "weeklyTasks": [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "type": t.get("type", ""),
                        "subTasks": [{**s, "completed": 0} for s in t.get("subTasks", [])],
                    }
                    for t in default_tasks["weekly"]
                ],
            }
            payload = {"roles": [default_role], "activeRoleId": role_id, "meta": {}}
            return payload

        if method == "rili.saveTaskManager":
            data = params.get("data")
            if not isinstance(data, dict):
                raise ValueError("data 必须是对象")
            storage_dir = _user_storage_dir() / "rili"
            path = storage_dir / "game-task-manager-v1.json"
            _write_json(path, data)
            return {"ok": True}

        if method == "rili.getActivityCalendar":
            storage_dir = _user_storage_dir() / "rili"
            path = storage_dir / "activity-calendar-v1.json"
            raw = _load_json(path, {"completed": {}, "lastUpdated": ""})
            if not isinstance(raw, dict):
                return {"completed": {}, "lastUpdated": ""}
            completed = raw.get("completed") if isinstance(raw.get("completed"), dict) else {}
            last_updated = raw.get("lastUpdated") if isinstance(raw.get("lastUpdated"), str) else ""
            return {"completed": completed, "lastUpdated": last_updated}

        if method == "rili.saveActivityCalendar":
            data = params.get("data")
            if not isinstance(data, dict):
                raise ValueError("data 必须是对象")
            storage_dir = _user_storage_dir() / "rili"
            path = storage_dir / "activity-calendar-v1.json"
            _write_json(path, data)
            return {"ok": True}

        if method == "rili.getActivityDefinitions":
            storage_dir = _user_storage_dir() / "rili"
            path = storage_dir / "activity-definitions-v1.json"
            if not path.exists():
                _write_json(path, _default_rili_activity_definitions())
            raw = _load_json(path, None)
            if isinstance(raw, list):
                return {"activities": raw}
            if isinstance(raw, dict) and isinstance(raw.get("activities"), list):
                return {"activities": raw.get("activities")}
            return {"activities": _default_rili_activity_definitions()}

        raise ValueError(f"未知方法: {method}")

    async def _ws_handler(self, ws):
        self._clients.add(ws)
        try:
            await ws.send(
                _pack(
                    {
                        "type": "event",
                        "event": "hello",
                        "data": {
                            "ws": self.urls.ws_url,
                            "http": self.urls.http_url,
                            "state": dict(self._state),
                        },
                    }
                )
            )

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    await ws.send(_pack({"type": "rpc.error", "id": None, "error": "消息不是合法 JSON"}))
                    continue

                t = str(msg.get("type", "")).strip()
                if t == "ping":
                    await ws.send(_pack({"type": "pong", "ts": int(asyncio.get_running_loop().time() * 1000)}))
                    continue

                if t != "rpc":
                    await ws.send(_pack({"type": "rpc.error", "id": msg.get("id"), "error": f"未知消息类型: {t or '(empty)'}"}))
                    continue

                rpc_id = msg.get("id")
                method = str(msg.get("method", "")).strip()
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                if not rpc_id:
                    rpc_id = str(uuid4())

                try:
                    result = await self._rpc(method, params)
                except Exception as e:
                    await ws.send(_pack({"type": "rpc.error", "id": rpc_id, "error": str(e)}))
                    continue

                await ws.send(_pack({"type": "rpc.result", "id": rpc_id, "result": result}))
        finally:
            self._clients.discard(ws)

    async def serve(self) -> None:
        if not _FRONTEND_DIR.exists():
            raise RuntimeError(f"找不到前端目录: {_FRONTEND_DIR}")

        self._http_thread = threading.Thread(target=self._start_http, daemon=True)
        self._http_thread.start()

        async with websockets.serve(self._ws_handler, self.host, self.ws_port):
            self._append_log("info", f"HTTP: {self.urls.http_url}")
            self._append_log("info", f"WS:   {self.urls.ws_url}")
            await asyncio.to_thread(self._stop_event.wait)
