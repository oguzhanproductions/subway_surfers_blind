from __future__ import annotations
from subway_blind.strings import sx as _sx
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
from subway_blind.controls import detect_keyboard_layout_info
from subway_blind.events import default_event_state, ensure_event_state
from subway_blind.item_upgrades import default_item_upgrade_state
from subway_blind.progression import ensure_progression_state
from subway_blind.quests import default_quest_state, ensure_quest_state
from subway_blind.characters import ensure_character_progress_state
from subway_blind.controls import ensure_controller_bindings, ensure_keyboard_bindings
from subway_blind.controls import sync_keyboard_layout_settings
from subway_blind.item_upgrades import ensure_item_upgrade_state
from subway_blind.version import APP_NAME
BUNDLED_RESOURCE_BASE_DIR = Path(getattr(sys, _sx(361), Path(__file__).resolve().parent.parent))
RESOURCE_BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, _sx(362), False) else Path(__file__).resolve().parent.parent
STORAGE_VENDOR_NAME = _sx(313)
LEGACY_STORAGE_DIR_NAME = _sx(314)

def _roaming_appdata_dir() -> Path:
    return Path(os.environ.get(_sx(380), Path.home() / _sx(383) / _sx(381)))

def _default_storage_base_dir() -> Path:
    return _roaming_appdata_dir() / STORAGE_VENDOR_NAME / APP_NAME
BASE_DIR = _default_storage_base_dir()
CURRENT_KEYBOARD_LAYOUT = detect_keyboard_layout_info()
DEFAULT_SETTINGS: dict[str, Any] = {_sx(130): 0.9, _sx(196): 0.6, _sx(1): _sx(2), _sx(195): True, _sx(315): False, _sx(117): True, _sx(118): False, _sx(119): _sx(2), _sx(120): 0, _sx(121): 0, _sx(122): 100, _sx(316): True, _sx(317): _sx(2), _sx(318): _sx(200), _sx(319): True, _sx(320): 10, _sx(321): False, _sx(322): False, _sx(323): False, _sx(324): True, _sx(325): False, _sx(326): 24, _sx(327): True, _sx(328): True, _sx(329): True, _sx(330): _sx(2), _sx(331): _sx(2), _sx(332): [], _sx(333): 0, _sx(334): 3, _sx(335): 3, _sx(336): 2, _sx(337): 3, _sx(338): default_item_upgrade_state(), _sx(241): DEFAULT_SELECTED_CHARACTER_KEY, _sx(240): default_character_progress_state(), _sx(203): DEFAULT_SELECTED_BOARD_KEY, _sx(202): default_board_progress_state(), _sx(339): 1, _sx(340): 0, _sx(341): {_sx(363): 0, _sx(364): 0, _sx(365): 0, _sx(366): 0, _sx(367): 0, _sx(368): 0}, _sx(342): _sx(2), _sx(343): _sx(2), _sx(344): 0, _sx(345): _sx(2), _sx(346): _sx(2), _sx(347): 0, _sx(348): 0, _sx(349): {_sx(369): 0, _sx(370): 0, _sx(371): 0, _sx(372): 0, _sx(373): 0, _sx(374): 0, _sx(375): 0, _sx(376): 0}, _sx(350): [], _sx(300): [], _sx(351): default_quest_state(), _sx(352): default_event_state(), _sx(353): _sx(2), _sx(354): default_keyboard_bindings(), _sx(355): default_controller_bindings(), _sx(356): CURRENT_KEYBOARD_LAYOUT.signature, _sx(357): CURRENT_KEYBOARD_LAYOUT.locale_code, _sx(358): CURRENT_KEYBOARD_LAYOUT.locale_label, _sx(359): CURRENT_KEYBOARD_LAYOUT.layout_code, _sx(360): CURRENT_KEYBOARD_LAYOUT.layout_label, "language": "english"}

def resource_path(*parts: str) -> str:
    external_candidate = RESOURCE_BASE_DIR.joinpath(*parts)
    if external_candidate.exists():
        return str(external_candidate)
    return str(BUNDLED_RESOURCE_BASE_DIR.joinpath(*parts))

def _data_directory() -> Path:
    return BASE_DIR / _sx(377)

def _settings_path() -> Path:
    return _data_directory() / _sx(378)

def _settings_backup_path() -> Path:
    return _data_directory() / _sx(379)

def _legacy_storage_base_dirs() -> list[Path]:
    candidates = [Path(os.environ.get(_sx(384), Path.home() / _sx(383) / _sx(387))) / LEGACY_STORAGE_DIR_NAME, RESOURCE_BASE_DIR, BUNDLED_RESOURCE_BASE_DIR]
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
        legacy_data_directory = legacy_root / _sx(377)
        legacy_settings_path = legacy_data_directory / _sx(378)
        if not legacy_settings_path.exists():
            continue
        data_directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(legacy_data_directory, data_directory, dirs_exist_ok=True)
        except Exception:
            continue
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
            with candidate.open(_sx(385), encoding=_sx(386)) as handle:
                loaded = json.load(handle)
        except Exception:
            continue
        normalized = _normalized_settings(loaded)
        loaded_signature = str(loaded.get(_sx(356), _sx(2)) or _sx(2)).strip() if isinstance(loaded, dict) else _sx(2)
        if candidate == backup_path or loaded_signature != str(normalized.get(_sx(356), _sx(2)) or _sx(2)).strip():
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
        with tempfile.NamedTemporaryFile(_sx(382), encoding=_sx(386), dir=str(data_directory), delete=False) as handle:
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
    merged[_sx(332)] = [str(value).strip() for value in list(merged.get(_sx(332)) or []) if str(value).strip()][:256]
    merged["language"] = str(merged.get("language", "english") or "english").strip().lower() or "english"
    merged[_sx(354)] = ensure_keyboard_bindings(merged.get(_sx(354)))
    merged[_sx(355)] = ensure_controller_bindings(merged.get(_sx(355)))
    sync_keyboard_layout_settings(merged)
    return merged
