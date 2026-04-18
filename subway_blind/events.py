from __future__ import annotations
from subway_blind.strings import sx as _sx
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
DAILY_EVENTS_BY_WEEKDAY: dict[int, DailyEventDefinition] = {0: DailyEventDefinition(key=_sx(618), label=_sx(619), description=_sx(620)), 1: DailyEventDefinition(key=_sx(621), label=_sx(622), description=_sx(623)), 2: DailyEventDefinition(key=_sx(624), label=_sx(625), description=_sx(626)), 3: DailyEventDefinition(key=_sx(624), label=_sx(625), description=_sx(627)), 4: DailyEventDefinition(key=_sx(628), label=_sx(629), description=_sx(630)), 5: DailyEventDefinition(key=_sx(609), label=_sx(631), description=_sx(632)), 6: DailyEventDefinition(key=_sx(609), label=_sx(631), description=_sx(632))}
LOGIN_CALENDAR_REWARDS: tuple[dict[str, int | str], ...] = ({_sx(592): _sx(363), _sx(593): 350}, {_sx(592): _sx(594), _sx(593): 1}, {_sx(592): _sx(569), _sx(593): 1}, {_sx(592): _sx(595), _sx(593): 1}, {_sx(592): _sx(596), _sx(593): 1}, {_sx(592): _sx(597), _sx(593): 20}, {_sx(592): _sx(598), _sx(593): 1})
DAILY_HIGH_SCORE_REWARDS: tuple[dict[str, int | str], ...] = ({_sx(592): _sx(597), _sx(593): 15}, {_sx(592): _sx(594), _sx(593): 1}, {_sx(592): _sx(596), _sx(593): 1}, {_sx(592): _sx(595), _sx(593): 1})
COIN_METER_REWARDS: tuple[dict[str, int | str], ...] = ({_sx(592): _sx(363), _sx(593): 250}, {_sx(592): _sx(569), _sx(593): 1}, {_sx(592): _sx(595), _sx(593): 1})
MINI_MYSTERY_BOX_REWARDS = ({_sx(592): _sx(363), _sx(593): 180}, {_sx(592): _sx(363), _sx(593): 260}, {_sx(592): _sx(594), _sx(593): 1}, {_sx(592): _sx(569), _sx(593): 1}, {_sx(592): _sx(595), _sx(593): 1}, {_sx(592): _sx(596), _sx(593): 1}, {_sx(592): _sx(597), _sx(593): 10})
MINI_MYSTERY_BOX_WEIGHTS = (30, 22, 15, 12, 10, 8, 10)

def default_event_state() -> dict[str, object]:
    return {_sx(597): 0, _sx(599): _sx(2), _sx(600): 0, _sx(601): 0, _sx(602): _sx(2), _sx(603): 0, _sx(604): 0, _sx(605): _sx(2), _sx(606): _sx(2), _sx(607): 0, _sx(608): _sx(2)}

def ensure_event_state(settings: dict, today: date | None=None) -> None:
    current_day = today or date.today()
    raw_state = settings.get(_sx(352))
    if not isinstance(raw_state, dict):
        raw_state = {}
    state = default_event_state()
    state.update(raw_state)
    today_iso = current_day.isoformat()
    if str(state.get(_sx(599)) or _sx(2)) != today_iso:
        state[_sx(599)] = today_iso
        state[_sx(600)] = 0
        state[_sx(601)] = 0
    if str(state.get(_sx(602)) or _sx(2)) != today_iso:
        state[_sx(602)] = today_iso
        state[_sx(603)] = 0
        state[_sx(604)] = 0
    cycle_start = str(state.get(_sx(606)) or _sx(2))
    claimed_days = max(0, min(len(LOGIN_CALENDAR_REWARDS), int(state.get(_sx(607), 0) or 0)))
    if not cycle_start:
        cycle_start = today_iso
    if claimed_days >= len(LOGIN_CALENDAR_REWARDS):
        last_claimed = str(state.get(_sx(608)) or _sx(2))
        if last_claimed != today_iso:
            cycle_start = today_iso
            claimed_days = 0
            state[_sx(608)] = _sx(2)
    state[_sx(597)] = max(0, int(state.get(_sx(597), 0) or 0))
    state[_sx(600)] = max(0, int(state.get(_sx(600), 0) or 0))
    state[_sx(601)] = max(0, min(len(DAILY_HIGH_SCORE_REWARDS), int(state.get(_sx(601), 0) or 0)))
    state[_sx(603)] = max(0, int(state.get(_sx(603), 0) or 0))
    state[_sx(604)] = max(0, min(len(COIN_METER_REWARDS), int(state.get(_sx(604), 0) or 0)))
    state[_sx(606)] = cycle_start
    state[_sx(607)] = claimed_days
    settings[_sx(352)] = state
    settings[_sx(353)] = word_hunt_target_word(settings, current_day)

def current_daily_event(today: date | None=None) -> DailyEventDefinition:
    current_day = today or date.today()
    return DAILY_EVENTS_BY_WEEKDAY[current_day.weekday()]

def tomorrow_daily_event(today: date | None=None) -> DailyEventDefinition:
    current_day = today or date.today()
    return current_daily_event(current_day + timedelta(days=1))

def featured_character_key(today: date | None=None) -> str:
    current_day = today or date.today()
    definitions = character_definitions()
    return definitions[current_day.toordinal() % len(definitions)].key

def word_hunt_target_word(settings: dict, today: date | None=None) -> str:
    current_day = today or date.today()
    event = current_daily_event(current_day)
    if event.key == _sx(609):
        return selected_character_definition(settings).name.upper().replace(_sx(4), _sx(2))
    return daily_word_for(current_day)

def daily_high_score_thresholds(today: date | None=None) -> tuple[int, ...]:
    current_day = today or date.today()
    base = 1800 + current_day.toordinal() % 5 * 350
    return (base, base * 2, int(base * 3.2), int(base * 5.4))

def coin_meter_thresholds(today: date | None=None) -> tuple[int, ...]:
    current_day = today or date.today()
    base = 35 + current_day.toordinal() % 4 * 5
    return (base, base + 70, base + 170)

def record_daily_score(settings: dict, score: int, today: date | None=None) -> int:
    ensure_event_state(settings, today)
    settings[_sx(352)][_sx(600)] = max(int(settings[_sx(352)][_sx(600)]), max(0, int(score)))
    return int(settings[_sx(352)][_sx(600)])

def record_coin_meter_coins(settings: dict, coins: int, today: date | None=None) -> int:
    ensure_event_state(settings, today)
    settings[_sx(352)][_sx(603)] = int(settings[_sx(352)][_sx(603)]) + max(0, int(coins))
    return int(settings[_sx(352)][_sx(603)])

def next_daily_high_score_threshold(settings: dict, today: date | None=None) -> int | None:
    ensure_event_state(settings, today)
    stage = int(settings[_sx(352)][_sx(601)])
    thresholds = daily_high_score_thresholds(today)
    if stage >= len(thresholds):
        return None
    return thresholds[stage]

def next_coin_meter_threshold(settings: dict, today: date | None=None) -> int | None:
    ensure_event_state(settings, today)
    stage = int(settings[_sx(352)][_sx(604)])
    thresholds = coin_meter_thresholds(today)
    if stage >= len(thresholds):
        return None
    return thresholds[stage]

def can_claim_daily_high_score_reward(settings: dict, today: date | None=None) -> bool:
    threshold = next_daily_high_score_threshold(settings, today)
    if threshold is None:
        return False
    return int(settings[_sx(352)][_sx(600)]) >= threshold

def claim_daily_high_score_reward(settings: dict, today: date | None=None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    if not can_claim_daily_high_score_reward(settings, today):
        return None
    stage = int(settings[_sx(352)][_sx(601)])
    settings[_sx(352)][_sx(601)] = stage + 1
    return dict(DAILY_HIGH_SCORE_REWARDS[min(stage, len(DAILY_HIGH_SCORE_REWARDS) - 1)])

def can_claim_coin_meter_reward(settings: dict, today: date | None=None) -> bool:
    threshold = next_coin_meter_threshold(settings, today)
    if threshold is None:
        return False
    return int(settings[_sx(352)][_sx(603)]) >= threshold

def claim_coin_meter_reward(settings: dict, today: date | None=None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    if not can_claim_coin_meter_reward(settings, today):
        return None
    stage = int(settings[_sx(352)][_sx(604)])
    settings[_sx(352)][_sx(604)] = stage + 1
    return dict(COIN_METER_REWARDS[min(stage, len(COIN_METER_REWARDS) - 1)])

def daily_gift_available(settings: dict, today: date | None=None) -> bool:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    return str(settings[_sx(352)][_sx(605)] or _sx(2)) != current_day.isoformat()

def claim_daily_gift(settings: dict, today: date | None=None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    if not daily_gift_available(settings, current_day):
        return None
    settings[_sx(352)][_sx(605)] = current_day.isoformat()
    rng = random.Random(current_day.toordinal() * 1831 + int(settings[_sx(352)][_sx(597)]))
    reward = rng.choices(MINI_MYSTERY_BOX_REWARDS, weights=MINI_MYSTERY_BOX_WEIGHTS, k=1)[0]
    return dict(reward)

def login_calendar_next_day(settings: dict, today: date | None=None) -> int:
    ensure_event_state(settings, today)
    return min(len(LOGIN_CALENDAR_REWARDS), int(settings[_sx(352)][_sx(607)]) + 1)

def login_calendar_available(settings: dict, today: date | None=None) -> bool:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    last_claimed = str(settings[_sx(352)][_sx(608)] or _sx(2))
    return last_claimed != current_day.isoformat()

def claim_login_calendar_reward(settings: dict, today: date | None=None) -> dict[str, int | str] | None:
    ensure_event_state(settings, today)
    current_day = today or date.today()
    if not login_calendar_available(settings, current_day):
        return None
    claimed_days = int(settings[_sx(352)][_sx(607)])
    reward = dict(LOGIN_CALENDAR_REWARDS[min(claimed_days, len(LOGIN_CALENDAR_REWARDS) - 1)])
    settings[_sx(352)][_sx(607)] = claimed_days + 1
    settings[_sx(352)][_sx(608)] = current_day.isoformat()
    if int(settings[_sx(352)][_sx(607)]) >= len(LOGIN_CALENDAR_REWARDS):
        settings[_sx(352)][_sx(606)] = current_day.isoformat()
    return reward

def reset_daily_event_progress(settings: dict, today: date | None=None) -> tuple[bool, bool]:
    ensure_event_state(settings, today)
    event_state = settings[_sx(352)]
    daily_high_score_reset = int(event_state.get(_sx(600), 0) or 0) > 0
    coin_meter_reset = int(event_state.get(_sx(603), 0) or 0) > 0
    event_state[_sx(600)] = 0
    event_state[_sx(603)] = 0
    return (daily_high_score_reset, coin_meter_reset)

def event_runtime_profile(settings: dict, today: date | None=None) -> dict[str, object]:
    current_day = today or date.today()
    event = current_daily_event(current_day)
    featured_key = featured_character_key(current_day)
    active_character_key = selected_character_definition(settings).key
    featured_active = event.key == _sx(624) and active_character_key == featured_key
    return {_sx(610): event, _sx(611): featured_key, _sx(612): featured_active, _sx(613): 3 if featured_active else 0, _sx(614): 0.15 if event.key == _sx(618) else 0.24 if event.key == _sx(628) else 0.0, _sx(615): 0.16 if event.key == _sx(609) else 0.0, _sx(616): 0.12 if event.key == _sx(621) else 0.0, _sx(617): event.key == _sx(621)}
