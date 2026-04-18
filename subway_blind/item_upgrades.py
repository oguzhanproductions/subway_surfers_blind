from __future__ import annotations
from subway_blind.strings import sx as _sx
from dataclasses import dataclass

@dataclass(frozen=True)
class ItemUpgradeDefinition:
    key: str
    name: str
    description: str
    upgrade_costs: tuple[int, ...]
    durations: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError(_sx(1933))
        if not self.name or not self.name.strip():
            raise ValueError(_sx(1934))
        if len(self.durations) != len(self.upgrade_costs) + 1:
            raise ValueError(_sx(1935).format(self.key))
        if any((cost <= 0 for cost in self.upgrade_costs)):
            raise ValueError(_sx(1936).format(self.key))
        if tuple(sorted(self.upgrade_costs)) != self.upgrade_costs:
            raise ValueError(_sx(1937).format(self.key))
        if any((duration <= 0 for duration in self.durations)):
            raise ValueError(_sx(1938).format(self.key))
        if tuple(sorted(self.durations)) != self.durations:
            raise ValueError(_sx(1939).format(self.key))

    @property
    def max_level(self) -> int:
        return len(self.upgrade_costs)
ITEM_UPGRADES: tuple[ItemUpgradeDefinition, ...] = (ItemUpgradeDefinition(key=_sx(633), name=_sx(1925), description=_sx(1926), upgrade_costs=(500, 1000, 3000, 10000, 60000), durations=(9.0, 10.0, 15.0, 20.0, 25.0, 30.0)), ItemUpgradeDefinition(key=_sx(1017), name=_sx(1927), description=_sx(1928), upgrade_costs=(500, 1000, 3000, 10000, 60000), durations=(6.5, 10.0, 15.0, 20.0, 25.0, 30.0)), ItemUpgradeDefinition(key=_sx(634), name=_sx(1929), description=_sx(1930), upgrade_costs=(500, 1000, 3000, 10000, 60000), durations=(10.0, 12.0, 16.0, 20.0, 25.0, 30.0)), ItemUpgradeDefinition(key=_sx(635), name=_sx(1931), description=_sx(1932), upgrade_costs=(500, 1000, 3000, 10000, 60000), durations=(10.0, 12.0, 16.0, 20.0, 25.0, 30.0)))
ITEM_UPGRADE_KEYS = tuple((definition.key for definition in ITEM_UPGRADES))
if len(set(ITEM_UPGRADE_KEYS)) != len(ITEM_UPGRADE_KEYS):
    raise ValueError(_sx(1924))
ITEM_UPGRADES_BY_KEY = {definition.key: definition for definition in ITEM_UPGRADES}
DEFAULT_ITEM_UPGRADE_KEY = ITEM_UPGRADES[0].key

def _coerce_level(value: object, maximum: int) -> int:
    try:
        numeric_level = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(maximum, numeric_level))

def item_upgrade_definitions() -> tuple[ItemUpgradeDefinition, ...]:
    return ITEM_UPGRADES

def item_upgrade_definition(key: str) -> ItemUpgradeDefinition:
    return ITEM_UPGRADES_BY_KEY.get(str(key), ITEM_UPGRADES_BY_KEY[DEFAULT_ITEM_UPGRADE_KEY])

def default_item_upgrade_state() -> dict[str, int]:
    return {definition.key: 0 for definition in ITEM_UPGRADES}

def ensure_item_upgrade_state(settings: dict) -> None:
    raw_state = settings.get(_sx(338))
    if not isinstance(raw_state, dict):
        raw_state = {}
    normalized_state: dict[str, int] = {}
    for definition in ITEM_UPGRADES:
        normalized_state[definition.key] = _coerce_level(raw_state.get(definition.key, 0), definition.max_level)
    settings[_sx(338)] = normalized_state

def item_upgrade_level(settings: dict, key: str) -> int:
    ensure_item_upgrade_state(settings)
    definition = item_upgrade_definition(key)
    return int(settings[_sx(338)][definition.key])

def next_item_upgrade_cost(settings: dict, key: str) -> int | None:
    definition = item_upgrade_definition(key)
    level = item_upgrade_level(settings, definition.key)
    if level >= definition.max_level:
        return None
    return definition.upgrade_costs[level]

def item_upgrade_duration(settings: dict, key: str) -> float:
    definition = item_upgrade_definition(key)
    level = item_upgrade_level(settings, definition.key)
    return float(definition.durations[level])
