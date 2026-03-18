from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from subway_blind.controls import default_controller_bindings, default_keyboard_bindings
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
    "check_updates_on_startup": True,
    "last_seen_version": "",
    "difficulty": "normal",
    "announce_lane": True,
    "announce_coins_every": 10,
    "meter_announcements_enabled": False,
    "coin_counters_enabled": False,
    "quest_changes_enabled": False,
    "bank_coins": 0,
    "keys": 3,
    "hoverboards": 3,
    "headstarts": 2,
    "score_boosters": 3,
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
    if not settings_path.exists():
        return copy.deepcopy(DEFAULT_SETTINGS)
    try:
        with settings_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except Exception:
        return copy.deepcopy(DEFAULT_SETTINGS)
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    for key, default_value in DEFAULT_SETTINGS.items():
        merged[key] = copy.deepcopy(loaded.get(key, default_value))
    return merged


def save_settings(settings: dict[str, Any]) -> None:
    ensure_storage_layout()
    data_directory = _data_directory()
    data_directory.mkdir(parents=True, exist_ok=True)
    settings_path = data_directory / "settings.json"
    try:
        with settings_path.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
    except Exception:
        return
