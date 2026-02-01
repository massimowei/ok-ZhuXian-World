import os
import importlib.util

_VER1_MODULE = None

def _load_ver1_module():
    global _VER1_MODULE
    if _VER1_MODULE is not None:
        return _VER1_MODULE
    ver1_path = os.path.join(
        os.path.dirname(__file__),
        'core',
        'cards_sim_ver1.py'
    )
    ver1_path = os.path.abspath(ver1_path)
    spec = importlib.util.spec_from_file_location("cards_sim_ver1", ver1_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模拟核心: {ver1_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _VER1_MODULE = mod
    return mod

def load_cards_export() -> dict:
    local_json = os.path.abspath(
        os.path.join(os.path.dirname(__file__), 'data', 'cards_export.json')
    )
    if not os.path.exists(local_json):
        raise FileNotFoundError(f"找不到数据文件: {local_json}")
    import json
    with open(local_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("cards_export.json 格式不正确：根节点应为对象")
    cards = data.get('cards')
    if not isinstance(cards, list) or not cards:
        raise ValueError("cards_export.json 格式不正确：缺少 cards 数组或为空")
    return data

def _load_cards_data():
    data = load_cards_export()
    cards = data.get('cards') or []
    out = {}
    for c in cards:
        if not isinstance(c, dict):
            continue
        cid = c.get('id')
        if not isinstance(cid, str) or not cid:
            continue
        out[cid] = c
    if not out:
        raise ValueError("cards_export.json 中没有可用的卡牌数据")
    return out

def run_demo():
    mod = _load_ver1_module()
    cards_map = _load_cards_data()
    deck_cards = [cards_map["yanhong"]]
    sim = mod.DanqingEventSimulator(10000.0, 50000.0, 200000.0)
    result = sim.simulate(deck_cards, level=6, max_time=60.0, seed=42, stop_on_target=False, card_levels={})
    return {
        "dps": int((result.get("total_damage") or 0) / (result.get("combat_time") or 60)),
        "events": result.get("event_counts"),
        "details": result.get("damage_breakdown")
    }

def run(deck_ids, level=6, base_atk=10000.0, base_hp=200000.0, base_dps=50000.0, max_time=180.0, seed=None):
    mod = _load_ver1_module()
    cards_map = _load_cards_data()
    raw_ids = [str(x).strip() for x in (deck_ids or []) if str(x).strip()]
    if not raw_ids:
        raise ValueError("请先输入卡组ID（用英文逗号分隔）")
    unknown = [cid for cid in raw_ids if cid not in cards_map]
    deck_cards = [cards_map[cid] for cid in raw_ids if cid in cards_map]
    if not deck_cards:
        raise ValueError(f"没有找到任何有效卡牌ID：{', '.join(unknown[:12])}{'…' if len(unknown) > 12 else ''}")
    sim = mod.DanqingEventSimulator(float(base_atk), float(base_dps), float(base_hp))
    result = sim.simulate(deck_cards, level=int(level), max_time=float(max_time), seed=seed, stop_on_target=False, card_levels={})
    return {
        "deck": raw_ids,
        "level": int(level),
        "base_atk": float(base_atk),
        "base_hp": float(base_hp),
        "base_dps": float(base_dps),
        "unknown": unknown,
        "dps": int((result.get("total_damage") or 0) / (result.get("combat_time") or max_time)),
        "combat_time": float(result.get("combat_time") or max_time),
        "total_cost": int(result.get("total_cost") or 0),
        "events": result.get("event_counts"),
        "details": result.get("damage_breakdown")
    }
