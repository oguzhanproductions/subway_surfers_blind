from __future__ import annotations

import random

HEADSTART_DURATION = 9.0
HEADSTART_MAX_USES = 3
HEADSTART_SPEED_BONUS = 12.0
HEADSTART_END_REWARDS = ("magnet", "mult2x", "sneakers")
HOVERBOARD_DURATION = 30.0
HOVERBOARD_MAX_USES_PER_RUN = 4
REVIVE_MAX_USES_PER_RUN = 3

SCORE_BOOSTER_MULTIPLIER_BONUS = {
    0: 0,
    1: 5,
    2: 6,
    3: 7,
}

MYSTERY_BOX_REWARD_WEIGHTS = {
    "coins": 44,
    "hover": 22,
    "mult": 15,
    "key": 8,
    "headstart": 6,
    "score_booster": 3,
    "nothing": 2,
}

SHOP_PRICES = {
    "hoverboard": 300,
    "mystery_box": 500,
    "headstart": 2000,
    "score_booster": 3000,
}

SHOP_BOX_REWARD_WEIGHTS = {
    "coins": 52,
    "hover": 18,
    "key": 12,
    "headstart": 10,
    "score_booster": 6,
    "jackpot": 0.01,
    "nothing": 1,
}

SHOP_BOX_REWARD_RANGES = {
    "coins": (300, 1000),
    "hover": (1, 3),
    "key": (1, 1),
    "headstart": (1, 2),
    "score_booster": (1, 1),
    "jackpot": (100000, 100000),
}


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
