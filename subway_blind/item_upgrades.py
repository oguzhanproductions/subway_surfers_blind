from __future__ import annotations

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
            raise ValueError("Item upgrade key must be non-empty.")
        if not self.name or not self.name.strip():
            raise ValueError("Item upgrade name must be non-empty.")
        if len(self.durations) != len(self.upgrade_costs) + 1:
            raise ValueError(f"{self.key} must define one more duration than upgrade cost.")
        if any(cost <= 0 for cost in self.upgrade_costs):
            raise ValueError(f"{self.key} upgrade costs must be positive.")
        if tuple(sorted(self.upgrade_costs)) != self.upgrade_costs:
            raise ValueError(f"{self.key} upgrade costs must be sorted from low to high.")
        if any(duration <= 0 for duration in self.durations):
            raise ValueError(f"{self.key} durations must be positive.")
        if tuple(sorted(self.durations)) != self.durations:
            raise ValueError(f"{self.key} durations must be sorted from low to high.")

    @property
    def max_level(self) -> int:
        return len(self.upgrade_costs)


ITEM_UPGRADES: tuple[ItemUpgradeDefinition, ...] = (
    ItemUpgradeDefinition(
        key="magnet",
        name="Coin Magnet",
        description="Pulls nearby coins into your lane while it is active.",
        upgrade_costs=(500, 1000, 3000, 10000, 60000),
        durations=(9.0, 10.0, 15.0, 20.0, 25.0, 30.0),
    ),
    ItemUpgradeDefinition(
        key="jetpack",
        name="Jetpack",
        description="Lifts you above hazards and collects airborne coin lines automatically.",
        upgrade_costs=(500, 1000, 3000, 10000, 60000),
        durations=(6.5, 10.0, 15.0, 20.0, 25.0, 30.0),
    ),
    ItemUpgradeDefinition(
        key="mult2x",
        name="2X Multiplier",
        description="Temporarily doubles the score multiplier earned during a run.",
        upgrade_costs=(500, 1000, 3000, 10000, 60000),
        durations=(10.0, 12.0, 16.0, 20.0, 25.0, 30.0),
    ),
    ItemUpgradeDefinition(
        key="sneakers",
        name="Super Sneakers",
        description="Boosts jump height so low barriers and bushes are easier to clear.",
        upgrade_costs=(500, 1000, 3000, 10000, 60000),
        durations=(10.0, 12.0, 16.0, 20.0, 25.0, 30.0),
    ),
)

ITEM_UPGRADE_KEYS = tuple(definition.key for definition in ITEM_UPGRADES)
if len(set(ITEM_UPGRADE_KEYS)) != len(ITEM_UPGRADE_KEYS):
    raise ValueError("Item upgrade keys must be unique.")

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
    raw_state = settings.get("item_upgrades")
    if not isinstance(raw_state, dict):
        raw_state = {}

    normalized_state: dict[str, int] = {}
    for definition in ITEM_UPGRADES:
        normalized_state[definition.key] = _coerce_level(raw_state.get(definition.key, 0), definition.max_level)

    settings["item_upgrades"] = normalized_state


def item_upgrade_level(settings: dict, key: str) -> int:
    ensure_item_upgrade_state(settings)
    definition = item_upgrade_definition(key)
    return int(settings["item_upgrades"][definition.key])


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
