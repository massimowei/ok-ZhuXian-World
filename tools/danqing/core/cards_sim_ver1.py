import heapq
from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import random
import json
from collections import defaultdict

class EventType(Enum):
    """事件类型枚举"""
    SKILL_CAST = "skill_cast"
    DOT_TICK = "dot_tick"
    BUFF_APPLY = "buff_apply"
    BUFF_EXPIRE = "buff_expire"
    COOLDOWN_READY = "cooldown_ready"
    ICE_ARROW = "ice_arrow"
    BURN_APPLY = "burn_apply"
    PULSE = "pulse"
    BURN_EXPLODE = "burn_explode"
    TRIGGER = "trigger"

@dataclass
class Event:
    """事件数据结构"""
    time: float
    event_type: EventType
    source_card: Optional[dict] = None
    data: dict = field(default_factory=dict)
    priority: int = 0  # 同时间事件的优先级
    
    def __lt__(self, other):
        if self.time == other.time:
            return self.priority < other.priority
        return self.time < other.time

class Aura:
    """光环/Buff系统"""
    def __init__(self, name: str, duration: float, effect: float):
        self.name = name
        self.duration = duration
        self.effect = effect
        self.stacks = 1
        self.expire_time = 0
        
    def refresh(self, current_time: float):
        """刷新光环持续时间"""
        self.expire_time = current_time + self.duration
        
    def add_stack(self):
        """增加层数"""
        self.stacks += 1

class CombatState:
    """战斗状态管理"""
    def __init__(self, base_atk: float, base_dps: float, base_hp: float):
        self.base_atk = base_atk
        self.base_dps = base_dps
        self.base_hp = base_hp
        self.current_time = 0.0
        self.total_damage = 0.0
        
        # 状态追踪
        self.burn_stacks = 0
        self.burn_dot_next_time: Optional[float] = None
        self.burn_explode_pending = False
        self.burn_targets = defaultdict(int)  # 目标ID -> 燃烧层数
        self.ice_arrow_total = 0
        self.ice_arrow_sword_counter = 0
        self.pulse_count = 0
        self.burn_add_total = 0
        self.explode_count = 0
        self.bear_stack_multiplier = 1.0
        self.bear_stack_expires: List[float] = []
        
        # Buff/Debuff管理
        self.auras: Dict[str, Aura] = {}
        self.cooldowns: Dict[str, float] = {}
        
        # 统计数据
        self.damage_breakdown = defaultdict(float)
        self.cast_counts = defaultdict(int)
        
        # 全局修正
        self.global_multiplier = 1.0
        self.special_damage_multiplier = 1.0
        
    def add_aura(self, aura_name: str, aura: Aura):
        """添加光环效果"""
        if aura_name in self.auras:
            self.auras[aura_name].add_stack()
        else:
            self.auras[aura_name] = aura
            
    def remove_aura(self, aura_name: str):
        """移除光环效果"""
        if aura_name in self.auras:
            del self.auras[aura_name]
            
    def is_on_cooldown(self, ability_name: str) -> bool:
        """检查技能是否在冷却中"""
        return ability_name in self.cooldowns and self.cooldowns[ability_name] > self.current_time

class DanqingEventSimulator:
    """基于事件的丹青系统模拟器"""
    
    def __init__(self, base_atk: float, base_dps: float, base_hp: float = 200000.0):
        self.base_atk = base_atk
        self.base_dps = base_dps
        self.base_hp = base_hp
        self.target_damage = 10_000_000
        self.event_queue = []
        self.level = 6
        self.card_levels = {}
        
    def simulate(self, deck: List[dict], level: int = 6, max_time: float = 300.0, seed: Optional[int] = None, stop_on_target: bool = True, card_levels: Optional[dict] = None) -> dict:
        """运行模拟"""
        if seed is not None:
            random.seed(int(seed))
        self.level = int(level)
        self.card_levels = dict(card_levels or {})
        self.event_queue = []
        # 初始化战斗状态
        state = CombatState(self.base_atk, self.base_dps, self.base_hp)
        
        # 计算静态修正
        self._calculate_static_modifiers(deck, state)
        
        # 初始化事件队列
        self._initialize_events(deck, state)
        
        # 主循环
        last_update_time = 0.0
        
        base_rate = state.base_dps * state.global_multiplier
        while state.current_time < max_time and (not stop_on_target or state.total_damage < self.target_damage):
            if not self.event_queue:
                remaining = max_time - last_update_time
                if remaining <= 0:
                    break
                if stop_on_target and base_rate > 0:
                    need = self.target_damage - state.total_damage
                    if need <= 0:
                        break
                    t_to_target = need / base_rate
                    if t_to_target <= remaining:
                        state.total_damage += need
                        state.damage_breakdown['base_dps'] += need
                        state.current_time = last_update_time + t_to_target
                        last_update_time = state.current_time
                        break
                base_damage = base_rate * remaining
                state.total_damage += base_damage
                state.damage_breakdown['base_dps'] += base_damage
                state.current_time = max_time
                last_update_time = max_time
                break

            next_event_time = min(self.event_queue[0].time, max_time)
            time_delta = next_event_time - last_update_time
            if time_delta > 0:
                if stop_on_target and base_rate > 0:
                    need = self.target_damage - state.total_damage
                    if need <= 0:
                        break
                    t_to_target = need / base_rate
                    if t_to_target <= time_delta:
                        state.total_damage += need
                        state.damage_breakdown['base_dps'] += need
                        state.current_time = last_update_time + t_to_target
                        last_update_time = state.current_time
                        break
                base_damage = base_rate * time_delta
                state.total_damage += base_damage
                state.damage_breakdown['base_dps'] += base_damage
                last_update_time = next_event_time

            if not self.event_queue:
                break
            event = heapq.heappop(self.event_queue)
            if event.time > max_time:
                state.current_time = max_time
                break
            state.current_time = event.time
            self._process_event(event, state, deck)
        
        # 计算最终统计
        actual_time = state.current_time
        total_dps = state.total_damage / actual_time if actual_time > 0 else 0
        deck_dps = total_dps - state.base_dps * state.global_multiplier
        
        return {
            'combat_time': actual_time,
            'total_damage': state.total_damage,
            'total_dps': total_dps,
            'deck_dps': deck_dps,
            'base_dps_contribution': state.base_dps * state.global_multiplier,
            'global_multiplier': state.global_multiplier,
            'damage_breakdown': dict(state.damage_breakdown),
            'cast_counts': dict(state.cast_counts),
            'event_counts': {
                'ice_arrow': int(state.ice_arrow_total),
                'burn_add': int(state.burn_add_total),
                'pulse': int(state.pulse_count),
                'explode': int(state.explode_count),
            },
            'total_cost': sum(int(card.get('cost', 0) or 0) for card in deck)
        }
    
    def _calculate_static_modifiers(self, deck: List[dict], state: CombatState):
        """计算静态修正值"""
        # 统计卡组构成
        composition = defaultdict(int)
        for card in deck:
            cat = card.get('category')
            if cat:
                composition[cat] += 1
        
        # 计算全局增益
        for card in deck:
            model = card.get('dpsModel') or {}
            model_type = model.get('type')
            card_id = card.get('id')
            if model_type is None and card_id in ['zhouyixian', 'tiger', 'banner', 'woodsword']:
                model_type = 'GLOBAL_MULTIPLIER'
            
            if model_type == 'GLOBAL_MULTIPLIER' and card_id in ['zhouyixian', 'tiger', 'banner']:
                cat = card.get('category')
                race_count = composition.get(cat, 0) if cat else 0
                bonus = self._calculate_card_value(card, self.level)
                state.global_multiplier *= (1 + bonus * race_count)
            elif model_type == 'GLOBAL_MULTIPLIER' and card_id == 'woodsword':
                bonus = self._calculate_card_value(card, self.level)
                state.global_multiplier *= (1 + bonus)
            
            # 特殊伤害加成（左归）
            elif model_type == 'SPECIAL_DMG_MULTIPLIER':
                bonus = self._calculate_card_value(card, self.level)
                state.special_damage_multiplier *= (1 + bonus)
    
    def _initialize_events(self, deck: List[dict], state: CombatState):
        """初始化事件系统"""
        for card in deck:
            model = card.get('dpsModel') or {}
            model_type = model.get('type')
            card_id = card.get('id')
            
            if card_id == 'wenmin':
                # 文敏的周期性冰箭
                interval = self._calculate_card_value(card, self.level, 'interval')
                self._schedule_event(Event(
                    time=interval,
                    event_type=EventType.ICE_ARROW,
                    source_card=card,
                    data={'count': 3, 'interval': interval}
                ))
            
            elif card_id == 'fan':
                # 折扇的脉冲
                self._schedule_event(Event(
                    time=15.0,
                    event_type=EventType.PULSE,
                    source_card=card,
                    data={'interval': 15.0}
                ))
            elif card_id == 'dice':
                self._schedule_event(Event(
                    time=0.2,
                    event_type=EventType.PULSE,
                    source_card=card,
                    data={'count': 3}
                ))
            
            elif card_id == 'ant':
                interval = 3.0
                self._schedule_event(Event(
                    time=0.5,
                    event_type=EventType.BURN_APPLY,
                    source_card=card,
                    data={'stacks': 1, 'interval': interval}
                ))
            elif model_type == 'ATTACK_SCALING':
                params = model.get('params') or {}
                cd = params.get('cd', 6)
                self._schedule_event(Event(
                    time=0.1,
                    event_type=EventType.SKILL_CAST,
                    source_card=card,
                    data={'cooldown': cd}
                ))
    
    def _process_event(self, event: Event, state: CombatState, deck: List[dict]):
        """处理事件"""
        if event.event_type == EventType.SKILL_CAST:
            self._handle_skill_cast(event, state, deck)
        elif event.event_type == EventType.ICE_ARROW:
            self._handle_ice_arrow(event, state, deck)
        elif event.event_type == EventType.BURN_APPLY:
            self._handle_burn_apply(event, state, deck)
        elif event.event_type == EventType.DOT_TICK:
            self._handle_dot_tick(event, state, deck)
        elif event.event_type == EventType.PULSE:
            self._handle_pulse(event, state, deck)
        elif event.event_type == EventType.BURN_EXPLODE:
            self._handle_burn_explode(event, state, deck)
        elif event.event_type == EventType.BUFF_EXPIRE:
            self._handle_buff_expire(event, state)
    
    def _handle_skill_cast(self, event: Event, state: CombatState, deck: List[dict]):
        """处理技能释放"""
        card = event.source_card
        if not isinstance(card, dict):
            return
        damage_ratio = self._calculate_card_value(card, self.level)
        damage = damage_ratio * state.base_atk * state.global_multiplier
        card_id = card.get('id')
        card_name = card.get('name') or card_id or '未知'
        damage_key = card_name
        dmg_type = None
        if card_id == 'yanhong':
            dmg_type = 'ICE_ARROW'
            damage_key = f"{card_name}-冰箭"
        elif card_id == 'qihao':
            dmg_type = 'STORM'
            damage_key = f"{card_name}-玄冰风暴"
        if dmg_type in ('ICE_ARROW', 'STORM'):
            damage *= state.special_damage_multiplier
        if dmg_type == 'ICE_ARROW':
            damage *= self._get_ice_arrow_multiplier(state)
        
        state.total_damage += damage
        state.damage_breakdown[damage_key] += damage
        state.cast_counts[damage_key] += 1

        if dmg_type == 'ICE_ARROW':
            state.ice_arrow_total += 1
            state.ice_arrow_sword_counter += 1
            self._check_ice_sword_trigger(state, deck)
            self._trigger_ice_arrow_effects(state, deck)
        
        # 安排下次释放
        cd = event.data['cooldown']
        
        # 齐昊的冷却缩减
        if card_id == 'qihao' and state.ice_arrow_total > 0:
            cd = max(1.0, cd - state.ice_arrow_total)
        
        self._schedule_event(Event(
            time=state.current_time + cd,
            event_type=EventType.SKILL_CAST,
            source_card=card,
            data={'cooldown': event.data['cooldown']}
        ))
    
    def _handle_ice_arrow(self, event: Event, state: CombatState, deck: List[dict]):
        """处理冰箭事件"""
        count = event.data['count']
        
        # 林峰的额外冰箭
        for card in deck:
            if card['id'] == 'linfeng':
                extra_chance = self._calculate_card_value(card, self.level, 'ice_arrow_chance')
                extra = 0
                for _ in range(count):
                    if random.random() < extra_chance:
                        extra += 1
                count += extra
        
        for _ in range(count):
            state.ice_arrow_total += 1
            state.ice_arrow_sword_counter += 1
            
            # 上官策的燃烧触发
            for card in deck:
                if card['id'] == 'shangguance':
                    burn_chance = self._calculate_card_value(card, self.level, 'burn_chance')
                    if random.random() < burn_chance:
                        self._apply_burn(state, deck, 1)
            self._trigger_ice_arrow_effects(state, deck)
        
        # 冰箭相关触发
        self._check_ice_sword_trigger(state, deck)
        
        # 安排下次冰箭
        self._schedule_event(Event(
            time=state.current_time + event.data['interval'],
            event_type=EventType.ICE_ARROW,
            source_card=event.source_card,
            data=event.data
        ))
    
    def _handle_burn_apply(self, event: Event, state: CombatState, deck: List[dict]):
        """处理燃烧施加"""
        stacks = int(event.data.get('stacks', 1) or 0)
        if stacks <= 0:
            return
        now = float(state.current_time)
        
        # 林峰的额外燃烧
        for card in deck:
            if card['id'] == 'linfeng':
                extra_burn_chance = self._calculate_card_value(card, self.level, 'extra_burn_chance')
                extra = 0
                for _ in range(stacks):
                    if random.random() < extra_burn_chance:
                        extra += 1
                stacks += extra
        
        # 二尾妖狐的燃烧伤害
        for card in deck:
            if card['id'] == 'twotails':
                trigger_damage = self._calculate_card_value(card, self.level) * stacks * state.base_atk
                trigger_damage *= state.global_multiplier * state.special_damage_multiplier
                state.total_damage += trigger_damage
                state.damage_breakdown['二尾妖狐-被动'] += trigger_damage
        
        state.burn_add_total += int(stacks)
        state.burn_stacks = min(state.burn_stacks + int(stacks), 12)
        
        # 安排燃烧DOT
        if state.burn_stacks > 0 and (state.burn_dot_next_time is None or state.burn_dot_next_time <= now + 1e-9):
            next_time = now + 3.0
            state.burn_dot_next_time = next_time
            self._schedule_event(Event(
                time=next_time,
                event_type=EventType.DOT_TICK,
                source_card=event.source_card,
                data={}
            ))
        
        # 检查爆燃
        if state.burn_stacks >= 8 and not state.burn_explode_pending:
            for card in deck:
                if card['id'] == 'sixtails':
                    state.burn_explode_pending = True
                    self._schedule_event(Event(
                        time=now + 1.5,
                        event_type=EventType.BURN_EXPLODE,
                        source_card=card,
                        priority=-1
                    ))
                    break

        interval = event.data.get('interval')
        if interval is not None and event.source_card and event.source_card.get('id') == 'ant':
            try:
                interval_val = float(interval)
            except Exception:
                interval_val = 0.0
            if interval_val > 0:
                self._schedule_event(Event(
                    time=now + interval_val,
                    event_type=EventType.BURN_APPLY,
                    source_card=event.source_card,
                    data={'stacks': 1, 'interval': interval_val}
                ))
    
    def _handle_dot_tick(self, event: Event, state: CombatState, deck: List[dict]):
        """处理DOT伤害"""
        state.burn_dot_next_time = None
        now = float(state.current_time)
        if state.burn_stacks > 0:
            # 计算燃烧伤害
            burn_ratio = None
            has_ant = False
            for card in deck:
                if card['id'] == 'ant':
                    burn_ratio = self._calculate_card_value(card, self.level, 'burn_tick_ratio')
                    has_ant = True
                    break
            if burn_ratio is None:
                burn_ratio = 0.014 + 0.001 * self.level
            burn_damage = burn_ratio * state.base_atk * state.burn_stacks
            burn_damage *= state.global_multiplier * state.special_damage_multiplier
            state.total_damage += burn_damage
            if has_ant:
                state.damage_breakdown['猩红巨蚁-燃烧'] += burn_damage
            else:
                state.damage_breakdown['燃烧-DOT'] += burn_damage
            
            # 继续DOT
            next_time = now + 3.0
            state.burn_dot_next_time = next_time
            self._schedule_event(Event(
                time=next_time,
                event_type=EventType.DOT_TICK,
                source_card=event.source_card,
                data={}
            ))
    
    def _handle_pulse(self, event: Event, state: CombatState, deck: List[dict]):
        """处理脉冲事件"""
        count = int(event.data.get('count', 1) or 1)
        is_echo = bool(event.data.get('echo'))
        base_ratio = float(event.data.get('base_ratio', 0.0) or 0.0)
        efficiency = float(event.data.get('efficiency', 1.0) or 1.0)
        if is_echo:
            damage = base_ratio * efficiency * state.base_atk
            damage *= state.global_multiplier * state.special_damage_multiplier
            state.total_damage += damage
            state.damage_breakdown['六合镜-回响'] += damage
            return

        state.pulse_count += count
        
        # 折扇伤害
        if event.source_card['id'] == 'fan':
            pulse_ratio = self._calculate_card_value(event.source_card, self.level, 'pulse_ratio')
            damage = pulse_ratio * count * state.base_atk
            damage *= state.global_multiplier * state.special_damage_multiplier
            state.total_damage += damage
            state.damage_breakdown['折扇-脉冲'] += damage
            base_ratio = pulse_ratio
        
        for card in deck:
            if card['id'] == 'dice':
                extra_ratio = self._calculate_card_value(card, self.level, 'dice_ratio')
                for _ in range(count):
                    if random.random() < 0.5:
                        extra_damage = extra_ratio * state.base_atk
                        extra_damage *= state.global_multiplier * state.special_damage_multiplier
                        state.total_damage += extra_damage
                        state.damage_breakdown['神木骰-追加'] += extra_damage

        for card in deck:
            if card['id'] == 'suishou':
                burn_chance = self._calculate_card_value(card, self.level, 'suishou_burn_chance')
                for _ in range(count):
                    if random.random() < burn_chance:
                        self._apply_burn(state, deck, 3)
        
        # 六合镜效果
        for card in deck:
            if card['id'] == 'mirror':
                if base_ratio > 0:
                    for _ in range(count):
                        if random.random() < 0.5:
                            efficiency = self._calculate_card_value(card, self.level, 'mirror_efficiency')
                            for i in range(6):
                                self._schedule_event(Event(
                                    time=state.current_time + i + 1,
                                    event_type=EventType.PULSE,
                                    source_card=card,
                                    data={'echo': True, 'base_ratio': base_ratio, 'efficiency': efficiency}
                                ))
        
        # 安排下次脉冲
        if 'interval' in event.data:
            self._schedule_event(Event(
                time=state.current_time + event.data['interval'],
                event_type=EventType.PULSE,
                source_card=event.source_card,
                data=event.data
            ))
    
    def _handle_burn_explode(self, event: Event, state: CombatState, deck: List[dict]):
        """处理爆燃"""
        state.burn_explode_pending = False

        if state.burn_stacks <= 0:
            return
        state.explode_count += 1

        damage_per_stack = self._calculate_card_value(event.source_card, self.level, 'explode_ratio') * state.base_atk
        total_damage = damage_per_stack * state.burn_stacks
        total_damage *= state.global_multiplier * state.special_damage_multiplier

        state.total_damage += total_damage
        state.damage_breakdown['六尾魔狐-爆燃'] += total_damage
        state.burn_stacks = 0
        state.burn_dot_next_time = None
    
    def _trigger_ice_arrow_effects(self, state: CombatState, deck: List[dict]):
        """触发冰箭相关效果"""
        # 雪地熊叠加
        for card in deck:
            if card['id'] == 'bear':
                buff_mult = float(self._calculate_card_value(card, self.level))
                if buff_mult <= 0:
                    continue
                if state.bear_stack_multiplier == 1.0:
                    state.bear_stack_multiplier = buff_mult
                state.bear_stack_expires.append(state.current_time + 10.0)
    
    def _apply_burn(self, state: CombatState, deck: List[dict], stacks: int):
        """施加燃烧"""
        self._schedule_event(Event(
            time=state.current_time,
            event_type=EventType.BURN_APPLY,
            data={'stacks': stacks},
            priority=1
        ))
    
    def _calculate_card_value(self, card: dict, level: int, value_type: str = 'damage') -> float:
        """计算卡牌数值"""
        card_id = card.get('id')
        if card_id is not None and card_id in self.card_levels:
            try:
                level = int(self.card_levels.get(card_id, level))
            except Exception:
                pass
            if level < 0:
                level = 0
            if level > 6:
                level = 6
        model = card.get('dpsModel') or {}
        scaling = model.get('scaling') or {}
        base = scaling.get('base', 0)
        step = scaling.get('step', 0)
        value = float(base) + level * float(step)
        
        # 特殊处理
        if value_type == 'interval' and card['id'] == 'wenmin':
            return 16 - level
        elif value_type == 'interval' and card['id'] == 'icearrow_card':
            return 16 - level
        elif value_type == 'burn_chance' and card['id'] == 'shangguance':
            return 0.38 + 0.02 * level
        elif value_type == 'ice_arrow_chance' and card['id'] == 'linfeng':
            return 0.70 + 0.05 * level
        elif value_type == 'extra_burn_chance' and card['id'] == 'linfeng':
            return 0.42 + 0.03 * level
        elif value_type == 'burn_tick_ratio' and card['id'] == 'ant':
            return 0.014 + 0.001 * level
        elif value_type == 'explode_ratio' and card['id'] == 'sixtails':
            return 0.52 + 0.03 * level
        elif value_type == 'pulse_ratio' and card['id'] == 'fan':
            return 0.52 + 0.02 * level
        elif value_type == 'dice_ratio' and card['id'] == 'dice':
            return 0.7 + 0.05 * level
        elif value_type == 'mirror_efficiency' and card['id'] == 'mirror':
            return 1.4 + 0.1 * level
        elif value_type == 'suishou_burn_chance' and card['id'] == 'suishou':
            return 0.70 + 0.05 * level
        
        return value

    def _get_ice_arrow_multiplier(self, state: CombatState) -> float:
        if not state.bear_stack_expires:
            return 1.0
        now = state.current_time
        state.bear_stack_expires = [t for t in state.bear_stack_expires if float(t) > now]
        stacks = len(state.bear_stack_expires)
        if stacks <= 0:
            return 1.0
        return float(state.bear_stack_multiplier) ** stacks

    def _check_ice_sword_trigger(self, state: CombatState, deck: List[dict]):
        threshold = None
        for card in deck:
            if card['id'] == 'icearrow_card':
                threshold = self._calculate_card_value(card, self.level, 'interval')
                break
        if threshold is None:
            return
        threshold = int(threshold or 0)
        if threshold <= 0:
            return
        while state.ice_arrow_sword_counter >= threshold:
            state.ice_arrow_sword_counter -= threshold
            self._schedule_event(Event(
                time=state.current_time + 0.1,
                event_type=EventType.PULSE,
                source_card={'id': 'icearrow_card'},
                data={'count': 1}
            ))
    
    def _schedule_event(self, event: Event):
        """调度事件"""
        heapq.heappush(self.event_queue, event)
    
    def _handle_buff_expire(self, event: Event, state: CombatState):
        """处理Buff过期"""
        aura_name = event.data['aura_name']
        state.remove_aura(aura_name)

def optimize_decks(base_atk: float, base_dps: float, cards_data: dict) -> dict:
    """优化卡组配置"""
    simulator = DanqingEventSimulator(base_atk, base_dps)
    cards = cards_data['cards']
    
    results = defaultdict(list)
    
    # 生成有效组合的优化算法
    def generate_combinations_dp(cards: List[dict], target_cost: int) -> List[List[int]]:
        """使用动态规划生成组合"""
        n = len(cards)
        dp = [[] for _ in range(target_cost + 1)]
        dp[0] = [[]]  # 空组合
        
        for i in range(n):
            card_cost = cards[i]['cost']
            for cost in range(target_cost, card_cost - 1, -1):
                for combo in dp[cost - card_cost]:
                    new_combo = combo + [i]
                    dp[cost].append(new_combo)
        
        return dp[target_cost]
    
    # 为每个cost等级寻找最优组合
    for cost_limit in range(10, 26):
        print(f"正在优化 {cost_limit} cost 卡组...")
        
        combinations = generate_combinations_dp(cards, cost_limit)
        print(f"找到 {len(combinations)} 个有效组合")
        
        # 模拟每个组合
        for combo_indices in combinations[:1000]:  # 限制数量避免过长计算
            deck = [cards[i] for i in combo_indices]
            
            # 重置模拟器状态
            simulator.event_queue = []
            
            # 运行模拟
            result = simulator.simulate(deck)
            result['deck_names'] = [card['name'] for card in deck]
            result['deck_ids'] = [card['id'] for card in deck]
            
            results[cost_limit].append(result)
        
        # 按DPS排序
        results[cost_limit].sort(key=lambda x: x['deck_dps'], reverse=True)
        results[cost_limit] = results[cost_limit][:10]
    
    return dict(results)

# 使用示例
if __name__ == "__main__":
    # 加载卡牌数据
    with open('cards_export.json', 'r', encoding='utf-8') as f:
        cards_data = json.load(f)
    
    # 设置参数
    base_atk = 10000
    base_dps = 50000
    
    # 运行优化
    optimal_results = optimize_decks(base_atk, base_dps, cards_data)
    
    # 输出结果
    for cost, decks in optimal_results.items():
        print(f"\n{'='*50}")
        print(f"{cost} Cost 最优卡组 TOP 3")
        print(f"{'='*50}")
        
        for i, result in enumerate(decks[:3], 1):
            print(f"\n【第{i}名】")
            print(f"卡组配置: {' + '.join(result['deck_names'])}")
            print(f"总DPS: {result['total_dps']:,.0f}")
            print(f"卡组DPS贡献: {result['deck_dps']:,.0f}")
            print(f"战斗时间: {result['combat_time']:.1f}秒")
            print(f"全局增幅: {(result['global_multiplier'] - 1) * 100:.1f}%")
            
            # 伤害占比
            if result['damage_breakdown']:
                print("\n伤害构成:")
                sorted_damage = sorted(
                    result['damage_breakdown'].items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )
                for source, damage in sorted_damage[:5]:
                    percentage = (damage / result['total_damage']) * 100
                    print(f"  - {source}: {damage:,.0f} ({percentage:.1f}%)")
