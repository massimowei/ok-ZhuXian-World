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

def _load_cards_data():
    # 优先读取本地数据文件（若你将 cards_export.json 复制到 tools/danqing/data/）
    local_json = os.path.abspath(
        os.path.join(os.path.dirname(__file__), 'data', 'cards_export.json')
    )
    if os.path.exists(local_json):
        import json
        with open(local_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cards = data.get('cards', [])
        return {c['id']: c for c in cards}
    # 兜底：内置少量关键卡定义，便于本地最小运行
    return {
        "yanhong": {
            "id": "yanhong", "name": "燕虹", "category": "human", "cost": 2,
            "dpsModel": {"type": "ATTACK_SCALING", "scaling": {"base": 0.28, "step": 0.02}, "params": {"cd": 6}}
        },
        "wenmin": {
            "id": "wenmin", "name": "文敏", "category": "human", "cost": 2,
            "dpsModel": {"type": "ATTACK_SCALING", "scaling": {"base": 0.0, "step": 0.0}, "params": {"cd": 0}}
        },
        "linfeng": {"id": "linfeng", "name": "林峰", "category": "human", "cost": 3, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 0.0, "step": 0.0}}},
        "shangguance": {"id": "shangguance", "name": "上官策", "category": "human", "cost": 2, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 0.0, "step": 0.0}}},
        "fan": {"id": "fan", "name": "折扇", "category": "item", "cost": 2, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 0.52, "step": 0.02}}},
        "dice": {"id": "dice", "name": "神木骰", "category": "item", "cost": 2, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 0.7, "step": 0.05}}},
        "mirror": {"id": "mirror", "name": "六合镜", "category": "item", "cost": 3, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 1.4, "step": 0.1}}},
        "ant": {"id": "ant", "name": "猩红巨蚁", "category": "beast", "cost": 2, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 0.014, "step": 0.001}}},
        "sixtails": {"id": "sixtails", "name": "六尾魔狐", "category": "beast", "cost": 3, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 0.52, "step": 0.03}}},
        "zhouyixian": {"id": "zhouyixian", "name": "周一仙", "category": "human", "cost": 2, "dpsModel": {"type": "GLOBAL_MULTIPLIER", "scaling": {"base": 0.012, "step": 0.002}}},
        "tiger": {"id": "tiger", "name": "猛虎", "category": "beast", "cost": 2, "dpsModel": {"type": "GLOBAL_MULTIPLIER", "scaling": {"base": 0.012, "step": 0.002}}},
        "banner": {"id": "banner", "name": "仙人布幡", "category": "item", "cost": 2, "dpsModel": {"type": "GLOBAL_MULTIPLIER", "scaling": {"base": 0.012, "step": 0.002}}},
        "woodsword": {"id": "woodsword", "name": "木剑", "category": "item", "cost": 1, "dpsModel": {"type": "GLOBAL_MULTIPLIER", "scaling": {"base": 0.008, "step": 0.001}}},
        "bear": {"id": "bear", "name": "雪地熊", "category": "beast", "cost": 2, "dpsModel": {"type": "PASSIVE", "scaling": {"base": 1.2, "step": 0.05}}},
        "qihao": {"id": "qihao", "name": "齐昊", "category": "human", "cost": 3, "dpsModel": {"type": "ATTACK_SCALING", "scaling": {"base": 1.5, "step": 0.1}, "params": {"cd": 60}}},
        "icearrow_card": {"id": "icearrow_card", "name": "寒冰箭", "category": "item", "cost": 2, "dpsModel": {"type": "ATTACK_SCALING", "scaling": {"base": 0.28, "step": 0.02}, "params": {"cd": 6}}}
    }

def run_demo():
    mod = _load_ver1_module()
    cards_map = _load_cards_data()
    deck_cards = [cards_map["yanhong"]]
    sim = mod.DanqingEventSimulator(10000.0, 50000.0)
    result = sim.simulate(deck_cards, level=6, max_time=60.0, seed=42, stop_on_target=False, card_levels={})
    return {
        "dps": int((result.get("total_damage") or 0) / (result.get("combat_time") or 60)),
        "events": result.get("event_counts"),
        "details": result.get("damage_breakdown")
    }

def run(deck_ids, level=6, base_atk=10000.0, base_dps=50000.0, max_time=180.0, seed=None):
    mod = _load_ver1_module()
    cards_map = _load_cards_data()
    deck_cards = [cards_map[cid] for cid in deck_ids if cid in cards_map]
    if not deck_cards:
        deck_cards = [cards_map["yanhong"]]
    sim = mod.DanqingEventSimulator(float(base_atk), float(base_dps))
    result = sim.simulate(deck_cards, level=int(level), max_time=float(max_time), seed=seed, stop_on_target=False, card_levels={})
    return {
        "deck": deck_ids,
        "level": int(level),
        "dps": int((result.get("total_damage") or 0) / (result.get("combat_time") or max_time)),
        "events": result.get("event_counts"),
        "details": result.get("damage_breakdown")
    }
