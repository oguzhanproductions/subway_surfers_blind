from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CharacterDefinition:
    key: str
    name: str
    unlock_cost: int
    upgrade_costs: tuple[int, ...]
    perk_kind: str
    description: str
    perk_values: tuple[float, ...]

    @property
    def max_level(self) -> int:
        return len(self.upgrade_costs)


@dataclass(frozen=True)
class CharacterRuntimeBonuses:
    banked_coin_bonus_ratio: float = 0.0
    hoverboard_duration_bonus: float = 0.0
    power_duration_multiplier: float = 1.0
    starting_multiplier_bonus: int = 0


CHARACTERS: tuple[CharacterDefinition, ...] = (
    CharacterDefinition(
        key="jake",
        name="Jake",
        unlock_cost=0,
        upgrade_costs=(650, 1350, 2800),
        perk_kind="coin_bank_pct",
        description="Banks extra coins at the end of a run.",
        perk_values=(0.0, 0.06, 0.12, 0.18),
    ),
    CharacterDefinition(
        key="tricky",
        name="Tricky",
        unlock_cost=2200,
        upgrade_costs=(900, 1850, 3600),
        perk_kind="hoverboard_duration_sec",
        description="Extends the hoverboard shield when you activate one.",
        perk_values=(0.0, 2.0, 4.0, 6.0),
    ),
    CharacterDefinition(
        key="fresh",
        name="Fresh",
        unlock_cost=3600,
        upgrade_costs=(1100, 2300, 4500),
        perk_kind="power_duration_pct",
        description="Extends temporary power-up duration.",
        perk_values=(0.0, 0.08, 0.16, 0.24),
    ),
    CharacterDefinition(
        key="yutani",
        name="Yutani",
        unlock_cost=4200,
        upgrade_costs=(1250, 2550, 4900),
        perk_kind="starting_multiplier",
        description="Starts each run with a higher score multiplier.",
        perk_values=(0.0, 1.0, 2.0, 3.0),
    ),
    CharacterDefinition(
        key="spike",
        name="Spike",
        unlock_cost=5100,
        upgrade_costs=(1400, 2850, 5400),
        perk_kind="coin_bank_pct",
        description="Banks even more coins at the end of a run.",
        perk_values=(0.0, 0.08, 0.16, 0.24),
    ),
    CharacterDefinition(
        key="dino",
        name="Dino",
        unlock_cost=6200,
        upgrade_costs=(1500, 3100, 5900),
        perk_kind="hoverboard_duration_sec",
        description="Extends hoverboard protection longer than anyone else.",
        perk_values=(0.0, 3.0, 6.0, 9.0),
    ),
    CharacterDefinition(
        key="boombot",
        name="Boombot",
        unlock_cost=7800,
        upgrade_costs=(1750, 3450, 6400),
        perk_kind="power_duration_pct",
        description="Extends temporary power-up duration with a premium robotics edge.",
        perk_values=(0.0, 0.1, 0.2, 0.3),
    ),
)

CHARACTERS_BY_KEY = {definition.key: definition for definition in CHARACTERS}
DEFAULT_SELECTED_CHARACTER_KEY = CHARACTERS[0].key


def character_definitions() -> tuple[CharacterDefinition, ...]:
    return CHARACTERS


def character_definition(key: str) -> CharacterDefinition:
    return CHARACTERS_BY_KEY.get(str(key), CHARACTERS_BY_KEY[DEFAULT_SELECTED_CHARACTER_KEY])


def default_character_progress_state() -> dict[str, dict[str, int | bool]]:
    return {
        definition.key: {
            "unlocked": definition.unlock_cost == 0,
            "level": 0,
        }
        for definition in CHARACTERS
    }


def ensure_character_progress_state(settings: dict) -> None:
    raw_progress = settings.get("character_progress")
    if not isinstance(raw_progress, dict):
        raw_progress = {}

    normalized_progress: dict[str, dict[str, int | bool]] = {}
    for definition in CHARACTERS:
        raw_state = raw_progress.get(definition.key)
        unlocked_default = definition.unlock_cost == 0
        if isinstance(raw_state, dict):
            unlocked = bool(raw_state.get("unlocked", unlocked_default))
            level = max(0, min(definition.max_level, int(raw_state.get("level", 0))))
        else:
            unlocked = unlocked_default
            level = 0
        if unlocked_default:
            unlocked = True
        if not unlocked:
            level = 0
        normalized_progress[definition.key] = {
            "unlocked": unlocked,
            "level": level,
        }

    selected_key = str(settings.get("selected_character", DEFAULT_SELECTED_CHARACTER_KEY))
    if selected_key not in normalized_progress or not bool(normalized_progress[selected_key]["unlocked"]):
        fallback_key = DEFAULT_SELECTED_CHARACTER_KEY
        for definition in CHARACTERS:
            if bool(normalized_progress[definition.key]["unlocked"]):
                fallback_key = definition.key
                break
        selected_key = fallback_key

    settings["character_progress"] = normalized_progress
    settings["selected_character"] = selected_key


def character_state(settings: dict, key: str) -> dict[str, int | bool]:
    ensure_character_progress_state(settings)
    return settings["character_progress"][character_definition(key).key]


def character_unlocked(settings: dict, key: str) -> bool:
    return bool(character_state(settings, key)["unlocked"])


def character_level(settings: dict, key: str) -> int:
    return int(character_state(settings, key)["level"])


def selected_character_key(settings: dict) -> str:
    ensure_character_progress_state(settings)
    return str(settings["selected_character"])


def selected_character_definition(settings: dict) -> CharacterDefinition:
    return character_definition(selected_character_key(settings))


def next_character_upgrade_cost(settings: dict, key: str) -> int | None:
    definition = character_definition(key)
    level = character_level(settings, key)
    if level >= definition.max_level:
        return None
    return definition.upgrade_costs[level]


def character_perk_summary(definition: CharacterDefinition, level: int) -> str:
    normalized_level = max(0, min(definition.max_level, int(level)))
    value = definition.perk_values[normalized_level]
    if definition.perk_kind == "coin_bank_pct":
        return f"Coin banking +{int(round(value * 100))}%"
    if definition.perk_kind == "hoverboard_duration_sec":
        formatted = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"Hoverboard shield +{formatted}s"
    if definition.perk_kind == "power_duration_pct":
        return f"Power duration +{int(round(value * 100))}%"
    if definition.perk_kind == "starting_multiplier":
        return f"Start multiplier +{int(round(value))}"
    return definition.description


def character_runtime_bonuses(settings: dict) -> CharacterRuntimeBonuses:
    definition = selected_character_definition(settings)
    level = character_level(settings, definition.key)
    value = definition.perk_values[level]
    if definition.perk_kind == "coin_bank_pct":
        return CharacterRuntimeBonuses(banked_coin_bonus_ratio=value)
    if definition.perk_kind == "hoverboard_duration_sec":
        return CharacterRuntimeBonuses(hoverboard_duration_bonus=value)
    if definition.perk_kind == "power_duration_pct":
        return CharacterRuntimeBonuses(power_duration_multiplier=1.0 + value)
    if definition.perk_kind == "starting_multiplier":
        return CharacterRuntimeBonuses(starting_multiplier_bonus=int(round(value)))
    return CharacterRuntimeBonuses()
