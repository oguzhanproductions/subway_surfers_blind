from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from subway_blind.characters import character_definitions, selected_character_definition
from subway_blind.progression import daily_word_for


@dataclass(frozen=True)
class DailyEventDefinition:
    key: str
    label: str
    description: str


DAILY_EVENTS_BY_WEEKDAY: dict[int, DailyEventDefinition] = {
    0: DailyEventDefinition(
        key="super_mysterizer",
        label="Super Mysterizer",
        description="Monday boosts Super Mystery Box appearances during runs.",
    ),
    1: DailyEventDefinition(
        key="mega_jackpot",
        label="Mega Jackpot",
        description="Tuesday improves Mystery Box rewards with jackpot-heavy luck.",
    ),
    2: DailyEventDefinition(
        key="featured_character_bonus",
        label="Character Bonus",
        description="Wednesday grants a bonus multiplier if you run with the featured character.",
    ),
    3: DailyEventDefinition(
        key="featured_character_bonus",
        label="Character Bonus",
        description="Thursday grants a bonus multiplier if you run with the featured character.",
    ),
    4: DailyEventDefinition(
        key="super_mystery_box_mania",
        label="Super Mystery Box Mania",
        description="Friday places extra Super Mystery Boxes directly on the track.",
    ),
    5: DailyEventDefinition(
        key="wordy_weekend",
        label="Wordy Weekend",
        description="Weekend Word Hunt uses your selected character and spawns more letters.",
    ),
    6: DailyEventDefinition(
        key="wordy_weekend",
        label="Wordy Weekend",
        description="Weekend Word Hunt uses your selected character and spawns more letters.",
    ),
}

LOGIN_CALENDAR_REWARDS: tuple[dict[str, int | str], ...] = (
    {"kind": "coins", "amount": 350},
    {"kind": "hoverboard", "amount": 1},
    {"kind": "key", "amount": 1},
    {"kind": "headstart", "amount": 1},
    {"kind": "score_booster", "amount": 1},
    {"kind": "event_coins", "amount": 20},
    {"kind": "super_box", "amount": 1},
)

DAILY_HIGH_SCORE_REWARDS: tuple[dict[str, int | str], ...] = (
    {"kind": "event_coins", "amount": 15},
    {"kind": "hoverboard", "amount": 1},
    {"kind": "score_booster", "amount": 1},
    {"kind": "headstart", "amount": 1},
)

COIN_METER_REWARDS: tuple[dict[str, int | str], ...] = (
    {"kind": "coins", "amount": 250},
    {"kind": "key", "amount": 1},
    {"kind": "headstart", "amount": 1},
)

MINI_MYSTERY_BOX_REWARDS = (
    {"kind": "coins", "amount": 180},
    {"kind": "coins", "amount": 260},
    {"kind": "hoverboard", "amount": 1},
    {"kind": "key", "amount": 1},
    {"kind": "headstart", "amount": 1},
    {"kind": "score_booster", "amount": 1},
    {"kind": "event_coins", "amount": 10},
)

MINI_MYSTERY_BOX_WEIGHTS = (30, 22, 15, 12, 10, 8, 10)


def default_event_state() -> dict[str, object]:
    return {
        "event_coins": 0,
        "daily_high_score_day": "",
        "daily_high_score_total": 0,
        "daily_high_score_claimed_tiers": 0,
        "coin_meter_day": "",
        "coin_meter_coins": 0,
        "coin_meter_claimed_tiers": 0,
        "daily_gift_claimed_on": "",
        "login_calendar_cycle_start": "",
        "login_calendar_claimed_days": 0,
        "login_calendar_last_claimed_on": "",
    }


def ensure_event_state(settings: dict, today: date | None = None) -> None:
    current_day = today or date.today()
    raw_state = settings.get("event_state")
    if not isinstance(raw_state, dict):
        raw_state = {}
    state = default_event_state()
    state.update(raw_state)

    today_iso = current_day.isoformat()
    if str(state.get("daily_high_score_day") or "") != today_iso:
        state["daily_high_score_day"] = today_iso
        state["daily_high_score_total"] = 0
        state["daily_high_score_claimed_tiers"] = 0

    if str(state.get("coin_meter_day") or "") != today_iso:
        state["coin_meter_day"] = today_iso
        state["coin_meter_coins"] = 0
        state["coin_meter_claimed_tiers"] = 0

    cycle_start = str(state.get("login_calendar_cycle_start") or "")
    claimed_days = max(0, min(len(LOGIN_CALENDAR_REWARDS), int(state.get("login_calendar_claimed_days", 0) or 0)))
    if not cycle_start:
        cycle_start = today_iso
    if claimed_days >= len(LOGIN_CALENDAR_REWARDS):
        cycle_start = today_iso
        claimed_days = 0
        state["login_calendar_last_claimed_on"] = ""

    state["event_coins"] = max(0, int(state.get("event_coins", 0) or 0))
    state["daily_high_score_total"] = max(0, int(state.get("daily_high_score_total", 0) or 0))
    state["daily_high_score_claimed_tiers"] = max(
        0,
        min(len(DAILY_HIGH_SCORE_REWARDS), int(state.get("daily_high_score_claimed_tiers", 0) or 0)),
    )
    state["coin_meter_coins"] = max(0, int(state.get("coin_meter_coins", 0) or 0))
    state["coin_meter_claimed_tiers"] = max(0, min(len(COIN_METER_REWARDS), int(state.get("coin_meter_claimed_tiers", 0) or 0)))
    state["login_calendar_cycle_start"] = cycle_start
    state["login_calendar_claimed_days"] = claimed_days
    settings["event_state"] = state
    settings["word_hunt_active_word"] = word_hunt_target_word(settings, current_day)


def current_daily_event(today: date | None = None) -> DailyEventDefinition:
    current_day = today or date.today()
    return DAILY_EVENTS_BY_WEEKDAY[current_day.weekday()]


def tomorrow_daily_event(today: date | None = None) -> DailyEventDefinition:
    current_day = today or date.today()
    return current_daily_event(current_day + timedelta(days=1))


def featured_character_key(today: date | None = None) -> str:
    current_day = today or date.today()
    definitions = character_definitions()
    return definitions[current_day.toordinal() % len(definitions)].key


def word_hunt_target_word(settings: dict, today: date | None = None) -> str:
    current_day = today or date.today()
    event = current_daily_event(current_day)
    if event.key == "wordy_weekend":
        return selected_character_definition(settings).name.upper().replace(" ", "")
    return daily_word_for(current_day)


def daily_high_score_thresholds(today: date | None = None) -> tuple[int, ...]:
    current_day = today or date.today()
    base = 1800 + ((current_day.toordinal() % 5) * 350)
    return (
        base,
        base * 2,
        int(base * 3.2),
        int(base * 5.4),
    )


def coin_meter_thresholds(today: date | None = None) -> tuple[int, ...]:
    current_day = today or date.today()
    base = 35 + ((current_day.toordinal() % 4) * 5)
    return (
        base,
        base + 70,
        base + 170,
    )


def record_daily_score(settings: dict, score: int, today: date | None = None) -> int:
    ensure_event_state(settings, today)
    settings["event_state"]["daily_high_score_total"] = max(
        int(settings["event_state"]["daily_high_score_total"]),
        max(0, int(score)),
    )
    return int(settings["event_state"]["daily_high_score_total"])


def record_coin_meter_coins(settings: dict, coins: int, today: date | None = None) -> int:
    ensure_event_state(settings, today)
    settings["event_state"]["coin_meter_coins"] = int(settings["event_state"]["coin_meter_coins"]) + max(0, int(coins))
    return int(settings["event_state"]["coin_meter_coins"])


def next_daily_high_score_threshold(settings: dict, today: date | None = None) -> int | None:
    ensure_event_state(settings, today)
    stage = int(settings["event_state"]["daily_high_score_claimed_tiers"])
    thresholds = daily_high_score_thresholds(today)
    if stage >= len(thresholds):
        return None
    return thresholds[stage]


def next_coin_meter_threshold(settings: dict, today: date | None = None) -> int | None:
    ensure_event_state(settings, today)
    stage = int(settings["event_state"]["coin_meter_claimed_tiers"])
    thresholds = coin_meter_thresholds(today)
    if stage >= len(thresholds):
        return None
    return thresholds[stage]


def can_claim_daily_high_score_reward(settings: dict, today: date | None = None) -> bool:
    threshold = next_daily_high_score_threshold(settings, today)
    if threshold is None:
        return False
    return int(settings["event_state"]["daily_high_score_total"]) >= threshold


def claim_daily_high_score_reward(settings: dict, today: date | None = None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    if not can_claim_daily_high_score_reward(settings, today):
        return None
    stage = int(settings["event_state"]["daily_high_score_claimed_tiers"])
    settings["event_state"]["daily_high_score_claimed_tiers"] = stage + 1
    return dict(DAILY_HIGH_SCORE_REWARDS[min(stage, len(DAILY_HIGH_SCORE_REWARDS) - 1)])


def can_claim_coin_meter_reward(settings: dict, today: date | None = None) -> bool:
    threshold = next_coin_meter_threshold(settings, today)
    if threshold is None:
        return False
    return int(settings["event_state"]["coin_meter_coins"]) >= threshold


def claim_coin_meter_reward(settings: dict, today: date | None = None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    if not can_claim_coin_meter_reward(settings, today):
        return None
    stage = int(settings["event_state"]["coin_meter_claimed_tiers"])
    settings["event_state"]["coin_meter_claimed_tiers"] = stage + 1
    return dict(COIN_METER_REWARDS[min(stage, len(COIN_METER_REWARDS) - 1)])


def daily_gift_available(settings: dict, today: date | None = None) -> bool:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    return str(settings["event_state"]["daily_gift_claimed_on"] or "") != current_day.isoformat()


def claim_daily_gift(settings: dict, today: date | None = None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    if not daily_gift_available(settings, current_day):
        return None
    settings["event_state"]["daily_gift_claimed_on"] = current_day.isoformat()
    rng = random.Random((current_day.toordinal() * 1831) + int(settings["event_state"]["event_coins"]))
    reward = rng.choices(MINI_MYSTERY_BOX_REWARDS, weights=MINI_MYSTERY_BOX_WEIGHTS, k=1)[0]
    return dict(reward)


def login_calendar_next_day(settings: dict, today: date | None = None) -> int:
    ensure_event_state(settings, today)
    return min(len(LOGIN_CALENDAR_REWARDS), int(settings["event_state"]["login_calendar_claimed_days"]) + 1)


def login_calendar_available(settings: dict, today: date | None = None) -> bool:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    last_claimed = str(settings["event_state"]["login_calendar_last_claimed_on"] or "")
    return last_claimed != current_day.isoformat()


def claim_login_calendar_reward(settings: dict, today: date | None = None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    if not login_calendar_available(settings, current_day):
        return None
    claimed_days = int(settings["event_state"]["login_calendar_claimed_days"])
    reward = dict(LOGIN_CALENDAR_REWARDS[min(claimed_days, len(LOGIN_CALENDAR_REWARDS) - 1)])
    settings["event_state"]["login_calendar_claimed_days"] = claimed_days + 1
    settings["event_state"]["login_calendar_last_claimed_on"] = current_day.isoformat()
    if int(settings["event_state"]["login_calendar_claimed_days"]) >= len(LOGIN_CALENDAR_REWARDS):
        settings["event_state"]["login_calendar_cycle_start"] = current_day.isoformat()
    return reward


def event_runtime_profile(settings: dict, today: date | None = None) -> dict[str, object]:
    current_day = today or date.today()
    event = current_daily_event(current_day)
    featured_key = featured_character_key(current_day)
    active_character_key = selected_character_definition(settings).key
    featured_active = event.key == "featured_character_bonus" and active_character_key == featured_key
    return {
        "event": event,
        "featured_character_key": featured_key,
        "featured_character_active": featured_active,
        "featured_multiplier_bonus": 3 if featured_active else 0,
        "super_box_bonus": 0.15 if event.key == "super_mysterizer" else (0.24 if event.key == "super_mystery_box_mania" else 0.0),
        "word_bonus": 0.16 if event.key == "wordy_weekend" else 0.0,
        "box_bonus": 0.12 if event.key == "mega_jackpot" else 0.0,
        "jackpot_bonus": event.key == "mega_jackpot",
    }
