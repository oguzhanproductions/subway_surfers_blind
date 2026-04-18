from __future__ import annotations
from subway_blind.strings import sx as _sx
import random
HEADSTART_DURATION = 9.0
HEADSTART_MAX_USES = 3
HEADSTART_SPEED_BONUS = 12.0
HEADSTART_END_REWARDS = (_sx(633), _sx(634), _sx(635))
HOVERBOARD_DURATION = 30.0
HOVERBOARD_MAX_USES_PER_RUN = 4
REVIVE_MAX_USES_PER_RUN = 3
SCORE_BOOSTER_MULTIPLIER_BONUS = {0: 0, 1: 5, 2: 6, 3: 7}
MYSTERY_BOX_REWARD_WEIGHTS = {_sx(363): 44, _sx(636): 22, _sx(637): 15, _sx(569): 8, _sx(595): 6, _sx(596): 3, _sx(638): 2}
SHOP_PRICES = {_sx(594): 300, _sx(21): 500, _sx(595): 2000, _sx(596): 3000}
SHOP_BOX_REWARD_WEIGHTS = {_sx(363): 52, _sx(636): 18, _sx(569): 12, _sx(595): 10, _sx(596): 6, _sx(639): 0.01, _sx(638): 1}
SHOP_BOX_REWARD_RANGES = {_sx(363): (300, 1000), _sx(636): (1, 3), _sx(569): (1, 1), _sx(595): (1, 2), _sx(596): (1, 1), _sx(639): (100000, 100000)}

def revive_cost(revives_used: int) -> int:
    return 2 ** max(0, revives_used)

def score_booster_bonus(uses: int) -> int:
    clamped_uses = max(0, min(3, uses))
    return SCORE_BOOSTER_MULTIPLIER_BONUS[clamped_uses]

def clamp_headstart_uses(uses: int) -> int:
    return max(0, min(HEADSTART_MAX_USES, uses))

def headstart_duration_for_uses(uses: int) -> float:
    return HEADSTART_DURATION * max(1, clamp_headstart_uses(uses))

def pick_mystery_box_reward() -> str:
    rewards = list(MYSTERY_BOX_REWARD_WEIGHTS.keys())
    weights = list(MYSTERY_BOX_REWARD_WEIGHTS.values())
    return random.choices(rewards, weights=weights, k=1)[0]

def pick_headstart_end_reward() -> str:
    return random.choice(HEADSTART_END_REWARDS)

def pick_shop_mystery_box_reward() -> str:
    rewards = list(SHOP_BOX_REWARD_WEIGHTS.keys())
    weights = list(SHOP_BOX_REWARD_WEIGHTS.values())
    return random.choices(rewards, weights=weights, k=1)[0]

def shop_box_reward_amount(reward: str) -> int:
    low, high = SHOP_BOX_REWARD_RANGES[reward]
    return random.randint(low, high)
