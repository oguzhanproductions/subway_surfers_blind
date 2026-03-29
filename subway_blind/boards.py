from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardDefinition:
    key: str
    name: str
    unlock_cost: int
    power_key: str
    power_label: str
    description: str


BOARDS: tuple[BoardDefinition, ...] = (
    BoardDefinition(
        key="classic",
        name="Classic",
        unlock_cost=0,
        power_key="standard",
        power_label="Standard Shield",
        description="The baseline hoverboard with pure protection and no extra modifier.",
    ),
    BoardDefinition(
        key="bouncer",
        name="Bouncer",
        unlock_cost=1800,
        power_key="double_jump",
        power_label="Double Jump",
        description="Lets you jump once more while riding the board.",
    ),
    BoardDefinition(
        key="monster",
        name="Monster",
        unlock_cost=2400,
        power_key="super_jump",
        power_label="Super Jump",
        description="Launches into a stronger jump arc while the board is active.",
    ),
    BoardDefinition(
        key="sharpeed",
        name="Sharpeed",
        unlock_cost=2600,
        power_key="super_speed",
        power_label="Super Speed",
        description="Adds extra forward speed while surfing on the board.",
    ),
    BoardDefinition(
        key="drift_king",
        name="Drift King",
        unlock_cost=2300,
        power_key="smooth_drift",
        power_label="Smooth Drift",
        description="Extends air hang time and makes movement feel glider-light.",
    ),
    BoardDefinition(
        key="zapper",
        name="Zapper",
        unlock_cost=2800,
        power_key="zap_sideways",
        power_label="Zap Sideways",
        description="Lets lane changes snap across two lanes while the board is active.",
    ),
    BoardDefinition(
        key="low_rider",
        name="Low Rider",
        unlock_cost=2200,
        power_key="stay_low",
        power_label="Stay Low",
        description="Keeps rolls active longer and lowers your profile under obstacles.",
    ),
)

BOARDS_BY_KEY = {definition.key: definition for definition in BOARDS}
DEFAULT_SELECTED_BOARD_KEY = BOARDS[0].key


def board_definitions() -> tuple[BoardDefinition, ...]:
    return BOARDS


def board_definition(key: str) -> BoardDefinition:
    return BOARDS_BY_KEY.get(str(key or "").strip().lower(), BOARDS_BY_KEY[DEFAULT_SELECTED_BOARD_KEY])


def default_board_progress_state() -> dict[str, dict[str, bool]]:
    return {
        definition.key: {
            "unlocked": definition.unlock_cost == 0,
        }
        for definition in BOARDS
    }


def ensure_board_state(settings: dict) -> None:
    raw_progress = settings.get("board_progress")
    if not isinstance(raw_progress, dict):
        raw_progress = {}
    normalized_progress: dict[str, dict[str, bool]] = {}
    for definition in BOARDS:
        raw_state = raw_progress.get(definition.key)
        unlocked_default = definition.unlock_cost == 0
        unlocked = unlocked_default
        if isinstance(raw_state, dict):
            unlocked = bool(raw_state.get("unlocked", unlocked_default))
        if unlocked_default:
            unlocked = True
        normalized_progress[definition.key] = {"unlocked": unlocked}
    selected_key = str(settings.get("selected_board", DEFAULT_SELECTED_BOARD_KEY) or "").strip().lower()
    if selected_key not in normalized_progress or not bool(normalized_progress[selected_key]["unlocked"]):
        selected_key = DEFAULT_SELECTED_BOARD_KEY
        for definition in BOARDS:
            if bool(normalized_progress[definition.key]["unlocked"]):
                selected_key = definition.key
                break
    settings["board_progress"] = normalized_progress
    settings["selected_board"] = selected_key


def board_unlocked(settings: dict, key: str) -> bool:
    ensure_board_state(settings)
    normalized_key = board_definition(key).key
    return bool(settings["board_progress"][normalized_key]["unlocked"])


def selected_board_key(settings: dict) -> str:
    ensure_board_state(settings)
    return str(settings["selected_board"])


def selected_board_definition(settings: dict) -> BoardDefinition:
    return board_definition(selected_board_key(settings))
