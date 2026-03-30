from __future__ import annotations

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


DAILY_TEMPLATES: tuple[QuestTemplate, ...] = (
    QuestTemplate("coins", "Collect {target} coins", 80, 20, 3),
    QuestTemplate("jumps", "Jump {target} times", 10, 3, 3),
    QuestTemplate("rolls", "Roll {target} times", 10, 3, 3),
    QuestTemplate("dodges", "Change lanes {target} times", 18, 4, 4),
    QuestTemplate("powerups", "Collect {target} power-ups", 4, 1, 4),
    QuestTemplate("boxes", "Open {target} mystery boxes", 2, 1, 5),
    QuestTemplate("distance_meters", "Run {target} meters", 700, 160, 5),
    QuestTemplate("hoverboards_used", "Use hoverboards {target} times", 1, 1, 4),
)

SEASONAL_TEMPLATES: tuple[QuestTemplate, ...] = (
    QuestTemplate("coins", "Collect {target} coins this season", 550, 100, 10),
    QuestTemplate("dodges", "Change lanes {target} times this season", 140, 30, 11),
    QuestTemplate("powerups", "Collect {target} power-ups this season", 28, 5, 12),
    QuestTemplate("distance_meters", "Run {target} meters this season", 6500, 1200, 14),
    QuestTemplate("runs_completed", "Finish {target} runs this season", 6, 1, 12),
    QuestTemplate("boxes", "Open {target} boxes this season", 10, 2, 13),
    QuestTemplate("hoverboards_used", "Use hoverboards {target} times this season", 6, 2, 12),
)

QUEST_METER_THRESHOLDS: tuple[int, ...] = (10, 24, 40, 58)
QUEST_METER_REWARDS: tuple[dict[str, int | str], ...] = (
    {"kind": "coins", "amount": 400},
    {"kind": "key", "amount": 1},
    {"kind": "headstart", "amount": 1},
    {"kind": "super_box", "amount": 1},
)


def default_quest_state() -> dict[str, object]:
    return {
        "daily_id": "",
        "daily_progress": {},
        "daily_claimed": [],
        "season_id": "",
        "season_progress": {},
        "season_claimed": [],
        "sneakers": 0,
        "meter_stage": 0,
    }


def season_identifier(today: date | None = None) -> str:
    current_day = today or date.today()
    quarter = ((current_day.month - 1) // 3) + 1
    return f"{current_day.year:04d}-q{quarter}"


def ensure_quest_state(settings: dict, today: date | None = None) -> None:
    current_day = today or date.today()
    raw_state = settings.get("quest_state")
    if not isinstance(raw_state, dict):
        raw_state = {}
    state = default_quest_state()
    state.update(raw_state)

    current_daily_id = current_day.isoformat()
    if str(state.get("daily_id") or "") != current_daily_id:
        state["daily_id"] = current_daily_id
        state["daily_progress"] = {}
        state["daily_claimed"] = []

    current_season_id = season_identifier(current_day)
    if str(state.get("season_id") or "") != current_season_id:
        state["season_id"] = current_season_id
        state["season_progress"] = {}
        state["season_claimed"] = []

    state["daily_progress"] = _normalized_progress_map(state.get("daily_progress"))
    state["season_progress"] = _normalized_progress_map(state.get("season_progress"))
    state["daily_claimed"] = _normalized_claimed(state.get("daily_claimed"), current_day, "daily")
    state["season_claimed"] = _normalized_claimed(state.get("season_claimed"), current_day, "season")
    state["sneakers"] = max(0, int(state.get("sneakers", 0) or 0))
    state["meter_stage"] = max(0, min(len(QUEST_METER_THRESHOLDS), int(state.get("meter_stage", 0) or 0)))
    settings["quest_state"] = state


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


def quests_for_scope(scope: str, today: date | None = None) -> tuple[QuestDefinition, ...]:
    current_day = today or date.today()
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope == "daily":
        rng = random.Random(current_day.toordinal() * 4099)
        templates = rng.sample(DAILY_TEMPLATES, 3)
        definitions: list[QuestDefinition] = []
        for index, template in enumerate(templates):
            scale = rng.randint(0, 2)
            target = template.base_target + (scale * template.target_step)
            definitions.append(
                QuestDefinition(
                    key=f"daily:{template.metric}:{index}",
                    scope="daily",
                    metric=template.metric,
                    label=template.text.format(target=target),
                    target=target,
                    sneaker_reward=template.sneaker_reward + scale,
                )
            )
        return tuple(definitions)

    rng = random.Random(int(season_identifier(current_day).replace("-q", "")) * 6421)
    templates = rng.sample(SEASONAL_TEMPLATES, 3)
    definitions = []
    for index, template in enumerate(templates):
        scale = rng.randint(1, 3)
        target = template.base_target + (scale * template.target_step)
        definitions.append(
            QuestDefinition(
                key=f"season:{template.metric}:{index}",
                scope="season",
                metric=template.metric,
                label=template.text.format(target=target),
                target=target,
                sneaker_reward=template.sneaker_reward + scale,
            )
        )
    return tuple(definitions)


def daily_quests(today: date | None = None) -> tuple[QuestDefinition, ...]:
    return quests_for_scope("daily", today)


def seasonal_quests(today: date | None = None) -> tuple[QuestDefinition, ...]:
    return quests_for_scope("season", today)


def quest_progress(settings: dict, quest: QuestDefinition, today: date | None = None) -> int:
    ensure_quest_state(settings, today)
    scope_key = "daily_progress" if quest.scope == "daily" else "season_progress"
    return int(settings["quest_state"][scope_key].get(quest.key, 0) or 0)


def quest_completed(settings: dict, quest: QuestDefinition, today: date | None = None) -> bool:
    return quest_progress(settings, quest, today) >= quest.target


def quest_claimed(settings: dict, quest: QuestDefinition, today: date | None = None) -> bool:
    ensure_quest_state(settings, today)
    scope_key = "daily_claimed" if quest.scope == "daily" else "season_claimed"
    return quest.key in settings["quest_state"][scope_key]


def record_quest_metric(settings: dict, metric: str, amount: int = 1, today: date | None = None) -> tuple[QuestDefinition, ...]:
    if amount <= 0:
        return ()
    ensure_quest_state(settings, today)
    completed_before = _ready_quest_keys(settings, today)
    for quest in daily_quests(today) + seasonal_quests(today):
        if quest.metric != metric:
            continue
        scope_key = "daily_progress" if quest.scope == "daily" else "season_progress"
        progress = settings["quest_state"][scope_key]
        progress[quest.key] = max(0, int(progress.get(quest.key, 0) or 0) + int(amount))
    completed_after = _ready_quest_keys(settings, today)
    new_ready = completed_after - completed_before
    return tuple(quest for quest in daily_quests(today) + seasonal_quests(today) if quest.key in new_ready)


def claim_quest(settings: dict, quest_key: str, today: date | None = None) -> QuestDefinition | None:
    ensure_quest_state(settings, today)
    quest = _quest_by_key(quest_key, today)
    if quest is None or not quest_completed(settings, quest, today) or quest_claimed(settings, quest, today):
        return None
    scope_key = "daily_claimed" if quest.scope == "daily" else "season_claimed"
    claimed = list(settings["quest_state"][scope_key])
    claimed.append(quest.key)
    settings["quest_state"][scope_key] = claimed
    settings["quest_state"]["sneakers"] = int(settings["quest_state"]["sneakers"]) + quest.sneaker_reward
    return quest


def reset_daily_quest_progress(settings: dict, today: date | None = None) -> tuple[QuestDefinition, ...]:
    ensure_quest_state(settings, today)
    claimed = set(settings["quest_state"]["daily_claimed"])
    progress = dict(settings["quest_state"]["daily_progress"])
    reset_quests: list[QuestDefinition] = []
    for quest in daily_quests(today):
        if quest.key in claimed:
            continue
        if int(progress.get(quest.key, 0) or 0) > 0:
            reset_quests.append(quest)
        progress[quest.key] = 0
    settings["quest_state"]["daily_progress"] = progress
    return tuple(reset_quests)


def quest_sneakers(settings: dict, today: date | None = None) -> int:
    ensure_quest_state(settings, today)
    return int(settings["quest_state"]["sneakers"])


def next_meter_threshold(settings: dict, today: date | None = None) -> int | None:
    ensure_quest_state(settings, today)
    stage = int(settings["quest_state"]["meter_stage"])
    if stage >= len(QUEST_METER_THRESHOLDS):
        return None
    return QUEST_METER_THRESHOLDS[stage]


def can_claim_meter_reward(settings: dict, today: date | None = None) -> bool:
    threshold = next_meter_threshold(settings, today)
    if threshold is None:
        return False
    return quest_sneakers(settings, today) >= threshold


def claim_meter_reward(settings: dict, today: date | None = None) -> dict[str, int | str] | None:
    ensure_quest_state(settings, today)
    if not can_claim_meter_reward(settings, today):
        return None
    stage = int(settings["quest_state"]["meter_stage"])
    settings["quest_state"]["meter_stage"] = stage + 1
    reward = QUEST_METER_REWARDS[min(stage, len(QUEST_METER_REWARDS) - 1)]
    return dict(reward)


def _quest_by_key(quest_key: str, today: date | None = None) -> QuestDefinition | None:
    for quest in daily_quests(today) + seasonal_quests(today):
        if quest.key == str(quest_key):
            return quest
    return None


def _ready_quest_keys(settings: dict, today: date | None = None) -> set[str]:
    ready: set[str] = set()
    for quest in daily_quests(today) + seasonal_quests(today):
        if quest_completed(settings, quest, today) and not quest_claimed(settings, quest, today):
            ready.add(quest.key)
    return ready
