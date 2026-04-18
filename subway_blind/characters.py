from __future__ import annotations
from subway_blind.strings import sx as _sx
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
CHARACTERS: tuple[CharacterDefinition, ...] = (CharacterDefinition(key=_sx(250), name=_sx(251), unlock_cost=0, upgrade_costs=(650, 1350, 2800), perk_kind=_sx(242), description=_sx(252), perk_values=(0.0, 0.06, 0.12, 0.18)), CharacterDefinition(key=_sx(253), name=_sx(254), unlock_cost=2200, upgrade_costs=(900, 1850, 3600), perk_kind=_sx(244), description=_sx(255), perk_values=(0.0, 2.0, 4.0, 6.0)), CharacterDefinition(key=_sx(256), name=_sx(257), unlock_cost=3600, upgrade_costs=(1100, 2300, 4500), perk_kind=_sx(246), description=_sx(258), perk_values=(0.0, 0.08, 0.16, 0.24)), CharacterDefinition(key=_sx(259), name=_sx(260), unlock_cost=4200, upgrade_costs=(1250, 2550, 4900), perk_kind=_sx(248), description=_sx(261), perk_values=(0.0, 1.0, 2.0, 3.0)), CharacterDefinition(key=_sx(262), name=_sx(263), unlock_cost=5100, upgrade_costs=(1400, 2850, 5400), perk_kind=_sx(242), description=_sx(264), perk_values=(0.0, 0.08, 0.16, 0.24)), CharacterDefinition(key=_sx(265), name=_sx(266), unlock_cost=6200, upgrade_costs=(1500, 3100, 5900), perk_kind=_sx(244), description=_sx(267), perk_values=(0.0, 3.0, 6.0, 9.0)), CharacterDefinition(key=_sx(268), name=_sx(269), unlock_cost=8400, upgrade_costs=(1850, 3650, 6800), perk_kind=_sx(242), description=_sx(270), perk_values=(0.0, 0.07, 0.14, 0.21)), CharacterDefinition(key=_sx(271), name=_sx(272), unlock_cost=9800, upgrade_costs=(2000, 3900, 7400), perk_kind=_sx(248), description=_sx(273), perk_values=(0.0, 1.0, 2.0, 3.0)), CharacterDefinition(key=_sx(274), name=_sx(275), unlock_cost=9000, upgrade_costs=(1900, 3800, 7100), perk_kind=_sx(246), description=_sx(276), perk_values=(0.0, 0.09, 0.18, 0.27)), CharacterDefinition(key=_sx(277), name=_sx(278), unlock_cost=9200, upgrade_costs=(1950, 3850, 7200), perk_kind=_sx(244), description=_sx(279), perk_values=(0.0, 2.5, 5.0, 7.5)), CharacterDefinition(key=_sx(280), name=_sx(281), unlock_cost=9400, upgrade_costs=(1950, 3900, 7300), perk_kind=_sx(246), description=_sx(282), perk_values=(0.0, 0.1, 0.2, 0.3)), CharacterDefinition(key=_sx(283), name=_sx(284), unlock_cost=9600, upgrade_costs=(2000, 4000, 7600), perk_kind=_sx(248), description=_sx(285), perk_values=(0.0, 1.0, 2.0, 3.0)), CharacterDefinition(key=_sx(286), name=_sx(287), unlock_cost=7800, upgrade_costs=(1750, 3450, 6400), perk_kind=_sx(246), description=_sx(288), perk_values=(0.0, 0.1, 0.2, 0.3)))
CHARACTERS_BY_KEY = {definition.key: definition for definition in CHARACTERS}
DEFAULT_SELECTED_CHARACTER_KEY = CHARACTERS[0].key

def character_definitions() -> tuple[CharacterDefinition, ...]:
    return CHARACTERS

def character_definition(key: str) -> CharacterDefinition:
    return CHARACTERS_BY_KEY.get(str(key), CHARACTERS_BY_KEY[DEFAULT_SELECTED_CHARACTER_KEY])

def default_character_progress_state() -> dict[str, dict[str, int | bool]]:
    return {definition.key: {_sx(239): definition.unlock_cost == 0, _sx(289): 0} for definition in CHARACTERS}

def ensure_character_progress_state(settings: dict) -> None:
    raw_progress = settings.get(_sx(240))
    if not isinstance(raw_progress, dict):
        raw_progress = {}
    normalized_progress: dict[str, dict[str, int | bool]] = {}
    for definition in CHARACTERS:
        raw_state = raw_progress.get(definition.key)
        unlocked_default = definition.unlock_cost == 0
        if isinstance(raw_state, dict):
            unlocked = bool(raw_state.get(_sx(239), unlocked_default))
            level = max(0, min(definition.max_level, int(raw_state.get(_sx(289), 0))))
        else:
            unlocked = unlocked_default
            level = 0
        if unlocked_default:
            unlocked = True
        if not unlocked:
            level = 0
        normalized_progress[definition.key] = {_sx(239): unlocked, _sx(289): level}
    selected_key = str(settings.get(_sx(241), DEFAULT_SELECTED_CHARACTER_KEY))
    if selected_key not in normalized_progress or not bool(normalized_progress[selected_key][_sx(239)]):
        fallback_key = DEFAULT_SELECTED_CHARACTER_KEY
        for definition in CHARACTERS:
            if bool(normalized_progress[definition.key][_sx(239)]):
                fallback_key = definition.key
                break
        selected_key = fallback_key
    settings[_sx(240)] = normalized_progress
    settings[_sx(241)] = selected_key

def character_state(settings: dict, key: str) -> dict[str, int | bool]:
    ensure_character_progress_state(settings)
    return settings[_sx(240)][character_definition(key).key]

def character_unlocked(settings: dict, key: str) -> bool:
    return bool(character_state(settings, key)[_sx(239)])

def character_level(settings: dict, key: str) -> int:
    return int(character_state(settings, key)[_sx(289)])

def selected_character_key(settings: dict) -> str:
    ensure_character_progress_state(settings)
    return str(settings[_sx(241)])

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
    if definition.perk_kind == _sx(242):
        return _sx(243).format(int(round(value * 100)))
    if definition.perk_kind == _sx(244):
        formatted = _sx(298).format(value).rstrip(_sx(297)).rstrip(_sx(292))
        return _sx(245).format(formatted)
    if definition.perk_kind == _sx(246):
        return _sx(247).format(int(round(value * 100)))
    if definition.perk_kind == _sx(248):
        return _sx(249).format(int(round(value)))
    return definition.description

def character_runtime_bonuses(settings: dict) -> CharacterRuntimeBonuses:
    definition = selected_character_definition(settings)
    level = character_level(settings, definition.key)
    value = definition.perk_values[level]
    if definition.perk_kind == _sx(242):
        return CharacterRuntimeBonuses(banked_coin_bonus_ratio=value)
    if definition.perk_kind == _sx(244):
        return CharacterRuntimeBonuses(hoverboard_duration_bonus=value)
    if definition.perk_kind == _sx(246):
        return CharacterRuntimeBonuses(power_duration_multiplier=1.0 + value)
    if definition.perk_kind == _sx(248):
        return CharacterRuntimeBonuses(starting_multiplier_bonus=int(round(value)))
    return CharacterRuntimeBonuses()
