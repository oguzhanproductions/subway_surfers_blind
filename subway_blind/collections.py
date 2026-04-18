from __future__ import annotations
from subway_blind.strings import sx as _sx
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
COLLECTIONS: tuple[CollectionDefinition, ...] = (CollectionDefinition(key=_sx(301), name=_sx(302), description=_sx(303), required_characters=(_sx(250), _sx(253), _sx(256)), required_boards=(), reward_kind=_sx(248), reward_value=1.0), CollectionDefinition(key=_sx(304), name=_sx(305), description=_sx(306), required_characters=(_sx(259), _sx(265), _sx(286)), required_boards=(), reward_kind=_sx(242), reward_value=0.12), CollectionDefinition(key=_sx(307), name=_sx(308), description=_sx(309), required_characters=(), required_boards=(_sx(204), _sx(209), _sx(214), _sx(219)), reward_kind=_sx(244), reward_value=3.0), CollectionDefinition(key=_sx(310), name=_sx(311), description=_sx(312), required_characters=(), required_boards=(_sx(224), _sx(229), _sx(234)), reward_kind=_sx(246), reward_value=0.12))
COLLECTIONS_BY_KEY = {definition.key: definition for definition in COLLECTIONS}

def collection_definitions() -> tuple[CollectionDefinition, ...]:
    return COLLECTIONS

def ensure_collection_state(settings: dict) -> None:
    completed = settings.get(_sx(300))
    if not isinstance(completed, list):
        completed = []
    valid_keys = {definition.key for definition in COLLECTIONS}
    settings[_sx(300)] = [str(key) for key in completed if str(key) in valid_keys]

def collection_definition(key: str) -> CollectionDefinition:
    return COLLECTIONS_BY_KEY[str(key)]

def collection_completed(settings: dict, key: str) -> bool:
    definition = collection_definition(key)
    return all((character_unlocked(settings, character_key) for character_key in definition.required_characters)) and all((board_unlocked(settings, board_key) for board_key in definition.required_boards))

def completed_collection_keys(settings: dict) -> tuple[str, ...]:
    return tuple((definition.key for definition in COLLECTIONS if collection_completed(settings, definition.key)))

def collection_progress(settings: dict, definition: CollectionDefinition) -> tuple[int, int]:
    owned = 0
    total = len(definition.required_characters) + len(definition.required_boards)
    for character_key in definition.required_characters:
        if character_unlocked(settings, character_key):
            owned += 1
    for board_key in definition.required_boards:
        if board_unlocked(settings, board_key):
            owned += 1
    return (owned, total)

def collection_bonus_summary(definition: CollectionDefinition) -> str:
    if definition.reward_kind == _sx(248):
        return _sx(249).format(int(round(definition.reward_value)))
    if definition.reward_kind == _sx(242):
        return _sx(243).format(int(round(definition.reward_value * 100)))
    if definition.reward_kind == _sx(244):
        formatted = _sx(298).format(definition.reward_value).rstrip(_sx(297)).rstrip(_sx(292))
        return _sx(245).format(formatted)
    if definition.reward_kind == _sx(246):
        return _sx(247).format(int(round(definition.reward_value * 100)))
    return definition.description

def collection_runtime_bonuses(settings: dict) -> CollectionRuntimeBonuses:
    banked_coin_bonus_ratio = 0.0
    hoverboard_duration_bonus = 0.0
    power_duration_multiplier = 1.0
    starting_multiplier_bonus = 0
    for definition in COLLECTIONS:
        if not collection_completed(settings, definition.key):
            continue
        if definition.reward_kind == _sx(242):
            banked_coin_bonus_ratio += float(definition.reward_value)
        elif definition.reward_kind == _sx(244):
            hoverboard_duration_bonus += float(definition.reward_value)
        elif definition.reward_kind == _sx(246):
            power_duration_multiplier += float(definition.reward_value)
        elif definition.reward_kind == _sx(248):
            starting_multiplier_bonus += int(round(definition.reward_value))
    return CollectionRuntimeBonuses(banked_coin_bonus_ratio=banked_coin_bonus_ratio, hoverboard_duration_bonus=hoverboard_duration_bonus, power_duration_multiplier=power_duration_multiplier, starting_multiplier_bonus=starting_multiplier_bonus)
