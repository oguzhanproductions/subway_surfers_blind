from __future__ import annotations
from subway_blind.strings import sx as _sx
import random
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class QuestTemplate:
    metric: str
    text: str
    base_target: int
    target_step: int
    sneaker_reward: int

@dataclass(frozen=True)
class QuestDefinition:
    key: str
    scope: str
    metric: str
    label: str
    target: int
    sneaker_reward: int
DAILY_TEMPLATES: tuple[QuestTemplate, ...] = (QuestTemplate(_sx(363), _sx(2060), 80, 20, 3), QuestTemplate(_sx(364), _sx(2061), 10, 3, 3), QuestTemplate(_sx(365), _sx(2062), 10, 3, 3), QuestTemplate(_sx(366), _sx(2063), 18, 4, 4), QuestTemplate(_sx(367), _sx(2064), 4, 1, 4), QuestTemplate(_sx(368), _sx(2065), 2, 1, 5), QuestTemplate(_sx(972), _sx(2092), 700, 160, 5), QuestTemplate(_sx(1359), _sx(2093), 1, 1, 4))
SEASONAL_TEMPLATES: tuple[QuestTemplate, ...] = (QuestTemplate(_sx(363), _sx(2094), 550, 100, 10), QuestTemplate(_sx(366), _sx(2095), 140, 30, 11), QuestTemplate(_sx(367), _sx(2096), 28, 5, 12), QuestTemplate(_sx(972), _sx(2097), 6500, 1200, 14), QuestTemplate(_sx(1048), _sx(2098), 6, 1, 12), QuestTemplate(_sx(368), _sx(2099), 10, 2, 13), QuestTemplate(_sx(1359), _sx(2100), 6, 2, 12))
QUEST_METER_THRESHOLDS: tuple[int, ...] = (10, 24, 40, 58)
QUEST_METER_REWARDS: tuple[dict[str, int | str], ...] = ({_sx(592): _sx(363), _sx(593): 400}, {_sx(592): _sx(569), _sx(593): 1}, {_sx(592): _sx(595), _sx(593): 1}, {_sx(592): _sx(598), _sx(593): 1})
PRACTICE_LANE_DAILY_QUEST = QuestDefinition(key=_sx(2101), scope=_sx(1190), metric=_sx(1134), label=_sx(2102), target=1, sneaker_reward=6)

def default_quest_state() -> dict[str, object]:
    return {_sx(2103): _sx(2), _sx(2104): {}, _sx(2105): [], _sx(2106): _sx(2), _sx(2107): {}, _sx(2108): [], _sx(635): 0, _sx(2109): 0}

def season_identifier(today: date | None=None) -> str:
    current_day = today or date.today()
    quarter = (current_day.month - 1) // 3 + 1
    return _sx(2091).format(current_day.year, quarter)

def ensure_quest_state(settings: dict, today: date | None=None) -> None:
    current_day = today or date.today()
    raw_state = settings.get(_sx(351))
    if not isinstance(raw_state, dict):
        raw_state = {}
    state = default_quest_state()
    state.update(raw_state)
    current_daily_id = current_day.isoformat()
    if str(state.get(_sx(2103)) or _sx(2)) != current_daily_id:
        state[_sx(2103)] = current_daily_id
        state[_sx(2104)] = {}
        state[_sx(2105)] = []
    current_season_id = season_identifier(current_day)
    if str(state.get(_sx(2106)) or _sx(2)) != current_season_id:
        state[_sx(2106)] = current_season_id
        state[_sx(2107)] = {}
        state[_sx(2108)] = []
    state[_sx(2104)] = _normalized_progress_map(state.get(_sx(2104)))
    state[_sx(2107)] = _normalized_progress_map(state.get(_sx(2107)))
    state[_sx(2105)] = _normalized_claimed(state.get(_sx(2105)), current_day, _sx(1190))
    state[_sx(2108)] = _normalized_claimed(state.get(_sx(2108)), current_day, _sx(659))
    state[_sx(635)] = max(0, int(state.get(_sx(635), 0) or 0))
    state[_sx(2109)] = max(0, min(len(QUEST_METER_THRESHOLDS), int(state.get(_sx(2109), 0) or 0)))
    settings[_sx(351)] = state

def _normalized_progress_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, amount in value.items():
        normalized[str(key)] = max(0, int(amount or 0))
    return normalized

def _normalized_claimed(value: object, today: date, scope: str) -> list[str]:
    if not isinstance(value, list):
        value = []
    valid_keys = {quest.key for quest in quests_for_scope(scope, today)}
    return [str(key) for key in value if str(key) in valid_keys]

def quests_for_scope(scope: str, today: date | None=None) -> tuple[QuestDefinition, ...]:
    current_day = today or date.today()
    normalized_scope = str(scope or _sx(2)).strip().lower()
    if normalized_scope == _sx(1190):
        rng = random.Random(current_day.toordinal() * 4099)
        templates = rng.sample(DAILY_TEMPLATES, 3)
        definitions: list[QuestDefinition] = []
        for index, template in enumerate(templates):
            scale = rng.randint(0, 2)
            target = template.base_target + scale * template.target_step
            definitions.append(QuestDefinition(key=_sx(2112).format(template.metric, index), scope=_sx(1190), metric=template.metric, label=template.text.format(target=target), target=target, sneaker_reward=template.sneaker_reward + scale))
        definitions.append(PRACTICE_LANE_DAILY_QUEST)
        return tuple(definitions)
    rng = random.Random(int(season_identifier(current_day).replace(_sx(2110), _sx(2))) * 6421)
    templates = rng.sample(SEASONAL_TEMPLATES, 3)
    definitions = []
    for index, template in enumerate(templates):
        scale = rng.randint(1, 3)
        target = template.base_target + scale * template.target_step
        definitions.append(QuestDefinition(key=_sx(2111).format(template.metric, index), scope=_sx(659), metric=template.metric, label=template.text.format(target=target), target=target, sneaker_reward=template.sneaker_reward + scale))
    return tuple(definitions)

def daily_quests(today: date | None=None) -> tuple[QuestDefinition, ...]:
    return quests_for_scope(_sx(1190), today)

def seasonal_quests(today: date | None=None) -> tuple[QuestDefinition, ...]:
    return quests_for_scope(_sx(659), today)

def quest_progress(settings: dict, quest: QuestDefinition, today: date | None=None) -> int:
    ensure_quest_state(settings, today)
    scope_key = _sx(2104) if quest.scope == _sx(1190) else _sx(2107)
    return int(settings[_sx(351)][scope_key].get(quest.key, 0) or 0)

def quest_completed(settings: dict, quest: QuestDefinition, today: date | None=None) -> bool:
    return quest_progress(settings, quest, today) >= quest.target

def quest_claimed(settings: dict, quest: QuestDefinition, today: date | None=None) -> bool:
    ensure_quest_state(settings, today)
    scope_key = _sx(2105) if quest.scope == _sx(1190) else _sx(2108)
    return quest.key in settings[_sx(351)][scope_key]

def record_quest_metric(settings: dict, metric: str, amount: int=1, today: date | None=None) -> tuple[QuestDefinition, ...]:
    if amount <= 0:
        return ()
    ensure_quest_state(settings, today)
    completed_before = _ready_quest_keys(settings, today)
    for quest in daily_quests(today) + seasonal_quests(today):
        if quest.metric != metric:
            continue
        scope_key = _sx(2104) if quest.scope == _sx(1190) else _sx(2107)
        progress = settings[_sx(351)][scope_key]
        progress[quest.key] = max(0, int(progress.get(quest.key, 0) or 0) + int(amount))
    completed_after = _ready_quest_keys(settings, today)
    new_ready = completed_after - completed_before
    return tuple((quest for quest in daily_quests(today) + seasonal_quests(today) if quest.key in new_ready))

def claim_quest(settings: dict, quest_key: str, today: date | None=None) -> QuestDefinition | None:
    ensure_quest_state(settings, today)
    quest = _quest_by_key(quest_key, today)
    if quest is None or not quest_completed(settings, quest, today) or quest_claimed(settings, quest, today):
        return None
    scope_key = _sx(2105) if quest.scope == _sx(1190) else _sx(2108)
    claimed = list(settings[_sx(351)][scope_key])
    claimed.append(quest.key)
    settings[_sx(351)][scope_key] = claimed
    settings[_sx(351)][_sx(635)] = int(settings[_sx(351)][_sx(635)]) + quest.sneaker_reward
    return quest

def reset_daily_quest_progress(settings: dict, today: date | None=None) -> tuple[QuestDefinition, ...]:
    ensure_quest_state(settings, today)
    claimed = set(settings[_sx(351)][_sx(2105)])
    progress = dict(settings[_sx(351)][_sx(2104)])
    reset_quests: list[QuestDefinition] = []
    for quest in daily_quests(today):
        if quest.key in claimed:
            continue
        if int(progress.get(quest.key, 0) or 0) > 0:
            reset_quests.append(quest)
        progress[quest.key] = 0
    settings[_sx(351)][_sx(2104)] = progress
    return tuple(reset_quests)

def quest_sneakers(settings: dict, today: date | None=None) -> int:
    ensure_quest_state(settings, today)
    return int(settings[_sx(351)][_sx(635)])

def next_meter_threshold(settings: dict, today: date | None=None) -> int | None:
    ensure_quest_state(settings, today)
    stage = int(settings[_sx(351)][_sx(2109)])
    if stage >= len(QUEST_METER_THRESHOLDS):
        return None
    return QUEST_METER_THRESHOLDS[stage]

def can_claim_meter_reward(settings: dict, today: date | None=None) -> bool:
    threshold = next_meter_threshold(settings, today)
    if threshold is None:
        return False
    return quest_sneakers(settings, today) >= threshold

def claim_meter_reward(settings: dict, today: date | None=None) -> dict[str, int | str] | None:
    ensure_quest_state(settings, today)
    if not can_claim_meter_reward(settings, today):
        return None
    stage = int(settings[_sx(351)][_sx(2109)])
    settings[_sx(351)][_sx(2109)] = stage + 1
    reward = QUEST_METER_REWARDS[min(stage, len(QUEST_METER_REWARDS) - 1)]
    return dict(reward)

def _quest_by_key(quest_key: str, today: date | None=None) -> QuestDefinition | None:
    for quest in daily_quests(today) + seasonal_quests(today):
        if quest.key == str(quest_key):
            return quest
    return None

def _ready_quest_keys(settings: dict, today: date | None=None) -> set[str]:
    ready: set[str] = set()
    for quest in daily_quests(today) + seasonal_quests(today):
        if quest_completed(settings, quest, today) and (not quest_claimed(settings, quest, today)):
            ready.add(quest.key)
    return ready
