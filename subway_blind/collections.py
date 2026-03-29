from __future__ import annotations

from dataclasses import dataclass

from subway_blind.boards import board_unlocked
from subway_blind.characters import character_unlocked


@dataclass(frozen=True)
class CollectionDefinition:
    key: str
    name: str
    description: str
    required_characters: tuple[str, ...]
    required_boards: tuple[str, ...]
    reward_kind: str
    reward_value: float


@dataclass(frozen=True)
class CollectionRuntimeBonuses:
    banked_coin_bonus_ratio: float = 0.0
    hoverboard_duration_bonus: float = 0.0
    power_duration_multiplier: float = 1.0
    starting_multiplier_bonus: int = 0


COLLECTIONS: tuple[CollectionDefinition, ...] = (
    CollectionDefinition(
        key="street_crew",
        name="Street Crew",
        description="Unlock Jake, Tricky, and Fresh to gain a stronger opening multiplier.",
        required_characters=("jake", "tricky", "fresh"),
        required_boards=(),
        reward_kind="starting_multiplier",
        reward_value=1.0,
    ),
    CollectionDefinition(
        key="future_set",
        name="Future Set",
        description="Unlock Yutani, Dino, and Boombot for stronger end-of-run coin banking.",
        required_characters=("yutani", "dino", "boombot"),
        required_boards=(),
        reward_kind="coin_bank_pct",
        reward_value=0.12,
    ),
    CollectionDefinition(
        key="board_boosters",
        name="Board Boosters",
        description="Collect Classic, Bouncer, Monster, and Sharpeed for a longer shield ride.",
        required_characters=(),
        required_boards=("classic", "bouncer", "monster", "sharpeed"),
        reward_kind="hoverboard_duration_sec",
        reward_value=3.0,
    ),
    CollectionDefinition(
        key="style_masters",
        name="Style Masters",
        description="Collect Drift King, Zapper, and Low Rider to extend temporary power-ups.",
        required_characters=(),
        required_boards=("drift_king", "zapper", "low_rider"),
        reward_kind="power_duration_pct",
        reward_value=0.12,
    ),
)

COLLECTIONS_BY_KEY = {definition.key: definition for definition in COLLECTIONS}


def collection_definitions() -> tuple[CollectionDefinition, ...]:
    return COLLECTIONS


def ensure_collection_state(settings: dict) -> None:
    completed = settings.get("collections_completed")
    if not isinstance(completed, list):
        completed = []
    valid_keys = {definition.key for definition in COLLECTIONS}
    settings["collections_completed"] = [str(key) for key in completed if str(key) in valid_keys]


def collection_definition(key: str) -> CollectionDefinition:
    return COLLECTIONS_BY_KEY[str(key)]


def collection_completed(settings: dict, key: str) -> bool:
    definition = collection_definition(key)
    return all(character_unlocked(settings, character_key) for character_key in definition.required_characters) and all(
        board_unlocked(settings, board_key) for board_key in definition.required_boards
    )


def completed_collection_keys(settings: dict) -> tuple[str, ...]:
    return tuple(definition.key for definition in COLLECTIONS if collection_completed(settings, definition.key))


def collection_progress(settings: dict, definition: CollectionDefinition) -> tuple[int, int]:
    owned = 0
    total = len(definition.required_characters) + len(definition.required_boards)
    for character_key in definition.required_characters:
        if character_unlocked(settings, character_key):
            owned += 1
    for board_key in definition.required_boards:
        if board_unlocked(settings, board_key):
            owned += 1
    return owned, total


def collection_bonus_summary(definition: CollectionDefinition) -> str:
    if definition.reward_kind == "starting_multiplier":
        return f"Start multiplier +{int(round(definition.reward_value))}"
    if definition.reward_kind == "coin_bank_pct":
        return f"Coin banking +{int(round(definition.reward_value * 100))}%"
    if definition.reward_kind == "hoverboard_duration_sec":
        formatted = f"{definition.reward_value:.1f}".rstrip("0").rstrip(".")
        return f"Hoverboard shield +{formatted}s"
    if definition.reward_kind == "power_duration_pct":
        return f"Power duration +{int(round(definition.reward_value * 100))}%"
    return definition.description


def collection_runtime_bonuses(settings: dict) -> CollectionRuntimeBonuses:
    banked_coin_bonus_ratio = 0.0
    hoverboard_duration_bonus = 0.0
    power_duration_multiplier = 1.0
    starting_multiplier_bonus = 0
    for definition in COLLECTIONS:
        if not collection_completed(settings, definition.key):
            continue
        if definition.reward_kind == "coin_bank_pct":
            banked_coin_bonus_ratio += float(definition.reward_value)
        elif definition.reward_kind == "hoverboard_duration_sec":
            hoverboard_duration_bonus += float(definition.reward_value)
        elif definition.reward_kind == "power_duration_pct":
            power_duration_multiplier += float(definition.reward_value)
        elif definition.reward_kind == "starting_multiplier":
            starting_multiplier_bonus += int(round(definition.reward_value))
    return CollectionRuntimeBonuses(
        banked_coin_bonus_ratio=banked_coin_bonus_ratio,
        hoverboard_duration_bonus=hoverboard_duration_bonus,
        power_duration_multiplier=power_duration_multiplier,
        starting_multiplier_bonus=starting_multiplier_bonus,
    )
