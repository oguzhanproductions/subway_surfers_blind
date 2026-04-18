from __future__ import annotations
from subway_blind.strings import sx as _sx
from dataclasses import dataclass

@dataclass(frozen=True)
class BoardDefinition:
    key: str
    name: str
    unlock_cost: int
    power_key: str
    power_label: str
    description: str
BOARDS: tuple[BoardDefinition, ...] = (BoardDefinition(key=_sx(204), name=_sx(205), unlock_cost=0, power_key=_sx(206), power_label=_sx(207), description=_sx(208)), BoardDefinition(key=_sx(209), name=_sx(210), unlock_cost=1800, power_key=_sx(211), power_label=_sx(212), description=_sx(213)), BoardDefinition(key=_sx(214), name=_sx(215), unlock_cost=2400, power_key=_sx(216), power_label=_sx(217), description=_sx(218)), BoardDefinition(key=_sx(219), name=_sx(220), unlock_cost=2600, power_key=_sx(221), power_label=_sx(222), description=_sx(223)), BoardDefinition(key=_sx(224), name=_sx(225), unlock_cost=2300, power_key=_sx(226), power_label=_sx(227), description=_sx(228)), BoardDefinition(key=_sx(229), name=_sx(230), unlock_cost=2800, power_key=_sx(231), power_label=_sx(232), description=_sx(233)), BoardDefinition(key=_sx(234), name=_sx(235), unlock_cost=2200, power_key=_sx(236), power_label=_sx(237), description=_sx(238)))
BOARDS_BY_KEY = {definition.key: definition for definition in BOARDS}
DEFAULT_SELECTED_BOARD_KEY = BOARDS[0].key

def board_definitions() -> tuple[BoardDefinition, ...]:
    return BOARDS

def board_definition(key: str) -> BoardDefinition:
    return BOARDS_BY_KEY.get(str(key or _sx(2)).strip().lower(), BOARDS_BY_KEY[DEFAULT_SELECTED_BOARD_KEY])

def default_board_progress_state() -> dict[str, dict[str, bool]]:
    return {definition.key: {_sx(239): definition.unlock_cost == 0} for definition in BOARDS}

def ensure_board_state(settings: dict) -> None:
    raw_progress = settings.get(_sx(202))
    if not isinstance(raw_progress, dict):
        raw_progress = {}
    normalized_progress: dict[str, dict[str, bool]] = {}
    for definition in BOARDS:
        raw_state = raw_progress.get(definition.key)
        unlocked_default = definition.unlock_cost == 0
        unlocked = unlocked_default
        if isinstance(raw_state, dict):
            unlocked = bool(raw_state.get(_sx(239), unlocked_default))
        if unlocked_default:
            unlocked = True
        normalized_progress[definition.key] = {_sx(239): unlocked}
    selected_key = str(settings.get(_sx(203), DEFAULT_SELECTED_BOARD_KEY) or _sx(2)).strip().lower()
    if selected_key not in normalized_progress or not bool(normalized_progress[selected_key][_sx(239)]):
        selected_key = DEFAULT_SELECTED_BOARD_KEY
        for definition in BOARDS:
            if bool(normalized_progress[definition.key][_sx(239)]):
                selected_key = definition.key
                break
    settings[_sx(202)] = normalized_progress
    settings[_sx(203)] = selected_key

def board_unlocked(settings: dict, key: str) -> bool:
    ensure_board_state(settings)
    normalized_key = board_definition(key).key
    return bool(settings[_sx(202)][normalized_key][_sx(239)])

def selected_board_key(settings: dict) -> str:
    ensure_board_state(settings)
    return str(settings[_sx(203)])

def selected_board_definition(settings: dict) -> BoardDefinition:
    return board_definition(selected_board_key(settings))
