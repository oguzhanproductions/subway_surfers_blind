from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from subway_blind.boards import DEFAULT_SELECTED_BOARD_KEY, default_board_progress_state, ensure_board_state
from subway_blind.characters import DEFAULT_SELECTED_CHARACTER_KEY, default_character_progress_state
from subway_blind.collections import ensure_collection_state
from subway_blind.controls import default_controller_bindings, default_keyboard_bindings
from subway_blind.events import default_event_state, ensure_event_state
from subway_blind.item_upgrades import default_item_upgrade_state
from subway_blind.progression import ensure_progression_state
from subway_blind.quests import default_quest_state, ensure_quest_state
from subway_blind.characters import ensure_character_progress_state
from subway_blind.controls import ensure_controller_bindings, ensure_keyboard_bindings
from subway_blind.item_upgrades import ensure_item_upgrade_state
from subway_blind.version import APP_NAME

BUNDLED_RESOURCE_BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
RESOURCE_BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
STORAGE_VENDOR_NAME = "Vireon Interactive"
LEGACY_STORAGE_DIR_NAME = "SubwaySurfersBlind"


def _roaming_appdata_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))


def _default_storage_base_dir() -> Path:
    return _roaming_appdata_dir() / STORAGE_VENDOR_NAME / APP_NAME


BASE_DIR = _default_storage_base_dir()

DEFAULT_SETTINGS: dict[str, Any] = {
    "sfx_volume": 0.9,
    "music_volume": 0.6,
    "audio_output_device": "",
    "menu_sound_hrtf": True,
    "speech_enabled": True,
    "sapi_speech_enabled": False,
    "sapi_voice_id": "",
    "sapi_rate": 0,
    "sapi_pitch": 0,
    "sapi_volume": 100,
    "check_updates_on_startup": True,
    "last_seen_version": "",
    "difficulty": "normal",
    "announce_lane": True,
    "announce_coins_every": 10,
    "meter_announcements_enabled": False,
    "coin_counters_enabled": False,
    "quest_changes_enabled": False,
    "pause_on_focus_loss_enabled": True,
    "main_menu_descriptions_enabled": True,
    "confirm_exit_enabled": True,
    "leaderboard_username": "",
    "leaderboard_session_token": "",
    "leaderboard_applied_reward_ids": [],
    "bank_coins": 0,
    "keys": 3,
    "hoverboards": 3,
    "headstarts": 2,
    "score_boosters": 3,
    "item_upgrades": default_item_upgrade_state(),
    "selected_character": DEFAULT_SELECTED_CHARACTER_KEY,
    "character_progress": default_character_progress_state(),
    "selected_board": DEFAULT_SELECTED_BOARD_KEY,
    "board_progress": default_board_progress_state(),
    "mission_set": 1,
    "mission_multiplier_bonus": 0,
    "mission_metrics": {
        "coins": 0,
        "jumps": 0,
        "rolls": 0,
        "dodges": 0,
        "powerups": 0,
        "boxes": 0,
    },
    "word_hunt_day": "",
    "word_hunt_letters": "",
    "word_hunt_streak": 0,
    "word_hunt_completed_on": "",
    "season_hunt_id": "",
    "season_tokens": 0,
    "season_reward_stage": 0,
    "achievement_progress": {
        "total_coins_collected": 0,
        "total_jumps": 0,
        "total_rolls": 0,
        "total_dodges": 0,
        "total_boxes_opened": 0,
        "best_distance": 0,
        "best_word_hunt_streak": 0,
        "total_season_tokens": 0,
    },
    "achievements_unlocked": [],
    "collections_completed": [],
    "quest_state": default_quest_state(),
    "event_state": default_event_state(),
    "word_hunt_active_word": "",
    "keyboard_bindings": default_keyboard_bindings(),
    "controller_bindings": default_controller_bindings(),
}


def resource_path(*parts: str) -> str:
    external_candidate = RESOURCE_BASE_DIR.joinpath(*parts)
    if external_candidate.exists():
        return str(external_candidate)
    return str(BUNDLED_RESOURCE_BASE_DIR.joinpath(*parts))


def _data_directory() -> Path:
    return BASE_DIR / "data"


def _settings_path() -> Path:
    return _data_directory() / "settings.json"


def _settings_backup_path() -> Path:
    return _data_directory() / "settings.json.bak"


def _legacy_storage_base_dirs() -> list[Path]:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / LEGACY_STORAGE_DIR_NAME,
        RESOURCE_BASE_DIR,
        BUNDLED_RESOURCE_BASE_DIR,
    ]
    legacy_dirs: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved == BASE_DIR or resolved in seen:
            continue
        seen.add(resolved)
        legacy_dirs.append(candidate)
    return legacy_dirs


def ensure_storage_layout() -> None:
    data_directory = _data_directory()
    settings_path = _settings_path()
    if settings_path.exists():
        data_directory.mkdir(parents=True, exist_ok=True)
        return
    for legacy_root in _legacy_storage_base_dirs():
        legacy_data_directory = legacy_root / "data"
        legacy_settings_path = legacy_data_directory / "settings.json"
        if not legacy_settings_path.exists():
            continue
        data_directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(legacy_data_directory, data_directory, dirs_exist_ok=True)
        except Exception:
            break
        else:
            return
    data_directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    ensure_storage_layout()
    settings_path = _settings_path()
    backup_path = _settings_backup_path()
    for candidate in (settings_path, backup_path):
        if not candidate.exists():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except Exception:
            continue
        normalized = _normalized_settings(loaded)
        if candidate == backup_path:
            save_settings(normalized)
        return normalized
    return _normalized_settings({})


def save_settings(settings: dict[str, Any]) -> None:
    ensure_storage_layout()
    data_directory = _data_directory()
    data_directory.mkdir(parents=True, exist_ok=True)
    settings_path = _settings_path()
    backup_path = _settings_backup_path()
    serialized = _normalized_settings(settings)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(data_directory),
            delete=False,
        ) as handle:
            json.dump(serialized, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = handle.name
        if settings_path.exists():
            shutil.copy2(settings_path, backup_path)
        os.replace(temporary_path, settings_path)
    except Exception:
        return
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except Exception:
                pass


def _normalized_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    if isinstance(settings, dict):
        for key, default_value in DEFAULT_SETTINGS.items():
            merged[key] = copy.deepcopy(settings.get(key, default_value))
    ensure_progression_state(merged)
    ensure_character_progress_state(merged)
    ensure_board_state(merged)
    ensure_item_upgrade_state(merged)
    ensure_collection_state(merged)
    ensure_quest_state(merged)
    ensure_event_state(merged)
    merged["leaderboard_applied_reward_ids"] = [
        str(value).strip()
        for value in list(merged.get("leaderboard_applied_reward_ids") or [])
        if str(value).strip()
    ][:256]
    merged["keyboard_bindings"] = ensure_keyboard_bindings(merged.get("keyboard_bindings"))
    merged["controller_bindings"] = ensure_controller_bindings(merged.get("controller_bindings"))
    return merged
