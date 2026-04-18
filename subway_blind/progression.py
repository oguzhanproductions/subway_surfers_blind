from __future__ import annotations
from subway_blind.strings import sx as _sx
import random
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class MissionGoal:
    metric: str
    label: str
    target: int

@dataclass(frozen=True)
class MissionTemplate:
    metric: str
    text: str
    base_target: int
    target_step: int
    cap: int

@dataclass(frozen=True)
class Achievement:
    key: str
    label: str
    description: str
    metric: str
    target: int
MISSION_TEMPLATES: tuple[MissionTemplate, ...] = (MissionTemplate(_sx(363), _sx(2060), 55, 12, 220), MissionTemplate(_sx(364), _sx(2061), 12, 3, 45), MissionTemplate(_sx(365), _sx(2062), 10, 3, 42), MissionTemplate(_sx(366), _sx(2063), 18, 4, 70), MissionTemplate(_sx(367), _sx(2064), 4, 1, 14), MissionTemplate(_sx(368), _sx(2065), 2, 1, 8))
MISSION_METRIC_DEFAULTS = {_sx(363): 0, _sx(364): 0, _sx(365): 0, _sx(366): 0, _sx(367): 0, _sx(368): 0}
WORD_HUNT_WORDS: tuple[str, ...] = (_sx(2046), _sx(2047), _sx(2048), _sx(2049), _sx(2050), _sx(2051), _sx(2052), _sx(2053), _sx(2054), _sx(2055), _sx(2056), _sx(2057))
WORD_HUNT_COIN_REWARDS = {1: 300, 2: 450, 3: 650, 4: 900}
SEASON_REWARD_THRESHOLDS: tuple[int, ...] = (5, 14, 28, 45)
SEASON_REWARD_SEQUENCE: tuple[str, ...] = (_sx(363), _sx(569), _sx(595), _sx(598))
SUPER_MYSTERY_BOX_REWARD_WEIGHTS = {_sx(363): 38, _sx(335): 16, _sx(334): 18, _sx(1017): 10, _sx(336): 10, _sx(337): 8, _sx(639): 6, _sx(2058): 4}
ACHIEVEMENT_PROGRESS_DEFAULTS = {_sx(369): 0, _sx(370): 0, _sx(371): 0, _sx(372): 0, _sx(373): 0, _sx(374): 0, _sx(375): 0, _sx(376): 0}
ACHIEVEMENTS: tuple[Achievement, ...] = (Achievement(_sx(2066), _sx(2067), _sx(2068), _sx(369), 1000), Achievement(_sx(2069), _sx(2070), _sx(2071), _sx(372), 500), Achievement(_sx(2072), _sx(2073), _sx(2074), _sx(370), 300), Achievement(_sx(2075), _sx(2076), _sx(2077), _sx(371), 300), Achievement(_sx(2078), _sx(2079), _sx(2080), _sx(373), 25), Achievement(_sx(2081), _sx(2082), _sx(2083), _sx(374), 1500), Achievement(_sx(2084), _sx(2085), _sx(2086), _sx(375), 3), Achievement(_sx(2087), _sx(2088), _sx(2089), _sx(376), 20))

def ensure_progression_state(settings: dict, today: date | None=None) -> None:
    current_day = today or date.today()
    settings[_sx(339)] = max(1, int(settings.get(_sx(339), 1)))
    settings[_sx(340)] = max(0, min(29, int(settings.get(_sx(340), 0))))
    metrics = settings.get(_sx(341))
    if not isinstance(metrics, dict):
        metrics = {}
    normalized_metrics: dict[str, int] = {}
    for metric, default_value in MISSION_METRIC_DEFAULTS.items():
        normalized_metrics[metric] = max(0, int(metrics.get(metric, default_value)))
    settings[_sx(341)] = normalized_metrics
    today_iso = current_day.isoformat()
    settings.setdefault(_sx(344), 0)
    settings.setdefault(_sx(345), _sx(2))
    if settings.get(_sx(342)) != today_iso:
        settings[_sx(342)] = today_iso
        settings[_sx(343)] = _sx(2)
    current_letters = settings.get(_sx(343), _sx(2))
    if not isinstance(current_letters, str):
        current_letters = _sx(2)
    active_word = active_word_for_settings(settings, current_day)
    if not active_word.startswith(current_letters):
        current_letters = _sx(2)
    settings[_sx(343)] = current_letters
    season_id = season_identifier(current_day)
    if settings.get(_sx(346)) != season_id:
        settings[_sx(346)] = season_id
        settings[_sx(347)] = 0
        settings[_sx(348)] = 0
    settings[_sx(347)] = max(0, int(settings.get(_sx(347), 0)))
    settings[_sx(348)] = max(0, int(settings.get(_sx(348), 0)))
    achievement_progress = settings.get(_sx(349))
    if not isinstance(achievement_progress, dict):
        achievement_progress = {}
    normalized_achievement_progress: dict[str, int] = {}
    for metric, default_value in ACHIEVEMENT_PROGRESS_DEFAULTS.items():
        normalized_achievement_progress[metric] = max(0, int(achievement_progress.get(metric, default_value)))
    settings[_sx(349)] = normalized_achievement_progress
    unlocked = settings.get(_sx(350))
    if not isinstance(unlocked, list):
        unlocked = []
    valid_keys = {achievement.key for achievement in ACHIEVEMENTS}
    settings[_sx(350)] = [str(key) for key in unlocked if str(key) in valid_keys]

def mission_goals_for_set(set_number: int) -> tuple[MissionGoal, ...]:
    normalized_set = max(1, int(set_number))
    rng = random.Random(normalized_set * 7919)
    templates = rng.sample(MISSION_TEMPLATES, 3)
    goals: list[MissionGoal] = []
    for template in templates:
        target = min(template.cap, template.base_target + (normalized_set - 1) * template.target_step)
        goals.append(MissionGoal(metric=template.metric, label=template.text.format(target=target), target=target))
    return tuple(goals)

def completed_mission_metrics(settings: dict) -> set[str]:
    metrics = settings.get(_sx(341), {})
    completed: set[str] = set()
    for goal in mission_goals_for_set(int(settings.get(_sx(339), 1))):
        if int(metrics.get(goal.metric, 0)) >= goal.target:
            completed.add(goal.metric)
    return completed

def daily_word_for(today: date | None=None) -> str:
    current_day = today or date.today()
    return WORD_HUNT_WORDS[current_day.toordinal() % len(WORD_HUNT_WORDS)]

def active_word_for_settings(settings: dict, today: date | None=None) -> str:
    configured_word = str(settings.get(_sx(353), _sx(2)) or _sx(2)).strip().upper()
    if configured_word:
        return configured_word
    return daily_word_for(today)

def remaining_word_letters(settings: dict, today: date | None=None) -> str:
    current_day = today or date.today()
    if settings.get(_sx(342)) != current_day.isoformat():
        return active_word_for_settings(settings, current_day)
    collected = str(settings.get(_sx(343), _sx(2)))
    word = active_word_for_settings(settings, current_day)
    if not word.startswith(collected):
        return word
    return word[len(collected):]

def register_word_letter(settings: dict, today: date | None=None) -> tuple[str, bool]:
    current_day = today or date.today()
    ensure_progression_state(settings, current_day)
    word = active_word_for_settings(settings, current_day)
    collected = str(settings.get(_sx(343), _sx(2)))
    next_letter = word[len(collected):len(collected) + 1]
    if not next_letter:
        return (_sx(2), True)
    settings[_sx(343)] = collected + next_letter
    return (next_letter, settings[_sx(343)] == word)

def update_word_hunt_streak(settings: dict, today: date | None=None) -> int:
    current_day = today or date.today()
    ensure_progression_state(settings, current_day)
    previous_completion = str(settings.get(_sx(345), _sx(2)))
    yesterday_iso = (current_day - timedelta(days=1)).isoformat()
    if previous_completion == yesterday_iso:
        streak = int(settings.get(_sx(344), 0)) + 1
    elif previous_completion == current_day.isoformat():
        streak = int(settings.get(_sx(344), 1))
    else:
        streak = 1
    settings[_sx(344)] = streak
    settings[_sx(345)] = current_day.isoformat()
    return streak

def reset_daily_word_hunt_progress(settings: dict, today: date | None=None) -> bool:
    current_day = today or date.today()
    ensure_progression_state(settings, current_day)
    today_iso = current_day.isoformat()
    if str(settings.get(_sx(345), _sx(2)) or _sx(2)) == today_iso:
        return False
    had_progress = bool(str(settings.get(_sx(343), _sx(2)) or _sx(2)))
    settings[_sx(342)] = today_iso
    settings[_sx(343)] = _sx(2)
    return had_progress

def word_hunt_reward_for_streak(streak: int) -> tuple[str, int]:
    normalized_streak = max(1, int(streak))
    if normalized_streak >= 5:
        return (_sx(598), 1)
    return (_sx(363), WORD_HUNT_COIN_REWARDS.get(normalized_streak, WORD_HUNT_COIN_REWARDS[4]))

def season_identifier(today: date | None=None) -> str:
    current_day = today or date.today()
    return _sx(2059).format(current_day.year, current_day.month)

def next_season_reward_threshold(settings: dict) -> int | None:
    stage = int(settings.get(_sx(348), 0))
    if stage >= len(SEASON_REWARD_THRESHOLDS):
        return None
    return SEASON_REWARD_THRESHOLDS[stage]

def register_season_token(settings: dict) -> tuple[int, int | None]:
    settings[_sx(347)] = max(0, int(settings.get(_sx(347), 0))) + 1
    return (int(settings[_sx(347)]), next_season_reward_threshold(settings))

def can_claim_season_reward(settings: dict) -> bool:
    threshold = next_season_reward_threshold(settings)
    if threshold is None:
        return False
    return int(settings.get(_sx(347), 0)) >= threshold

def claim_season_reward(settings: dict) -> str | None:
    if not can_claim_season_reward(settings):
        return None
    stage = int(settings.get(_sx(348), 0))
    reward = SEASON_REWARD_SEQUENCE[min(stage, len(SEASON_REWARD_SEQUENCE) - 1)]
    settings[_sx(348)] = stage + 1
    return reward

def pick_super_mystery_box_reward() -> str:
    rewards = list(SUPER_MYSTERY_BOX_REWARD_WEIGHTS.keys())
    weights = list(SUPER_MYSTERY_BOX_REWARD_WEIGHTS.values())
    return random.choices(rewards, weights=weights, k=1)[0]

def achievement_definitions() -> tuple[Achievement, ...]:
    return ACHIEVEMENTS

def achievement_progress(settings: dict) -> dict[str, int]:
    ensure_progression_state(settings)
    return settings[_sx(349)]

def record_achievement_progress(settings: dict, metric: str, amount: int=1) -> int:
    ensure_progression_state(settings)
    if amount <= 0:
        return int(settings[_sx(349)].get(metric, 0))
    progress = settings[_sx(349)]
    progress[metric] = max(0, int(progress.get(metric, 0)) + int(amount))
    return int(progress[metric])

def set_achievement_progress_max(settings: dict, metric: str, value: int) -> int:
    ensure_progression_state(settings)
    progress = settings[_sx(349)]
    progress[metric] = max(int(progress.get(metric, 0)), max(0, int(value)))
    return int(progress[metric])

def newly_unlocked_achievements(settings: dict) -> tuple[Achievement, ...]:
    ensure_progression_state(settings)
    progress = settings[_sx(349)]
    unlocked = set(settings.get(_sx(350), []))
    new_unlocks: list[Achievement] = []
    for achievement in ACHIEVEMENTS:
        if achievement.key in unlocked:
            continue
        if int(progress.get(achievement.metric, 0)) >= achievement.target:
            unlocked.add(achievement.key)
            new_unlocks.append(achievement)
    if new_unlocks:
        settings[_sx(350)] = [achievement.key for achievement in ACHIEVEMENTS if achievement.key in unlocked]
    return tuple(new_unlocks)
