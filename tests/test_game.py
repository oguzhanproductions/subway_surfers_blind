import os
import shutil
import sys
import tempfile
import time
import unittest
import copy
import io
import json
import wave
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from subway_blind import config as config_module
from subway_blind import updater as updater_module
from subway_blind.audio import (
    Audio,
    Speaker,
    SAPI_PITCH_MAX,
    SAPI_PITCH_MIN,
    SAPI_RATE_MAX,
    SAPI_RATE_MIN,
    SAPI_SPEAK_IS_XML,
    SYSTEM_DEFAULT_OUTPUT_LABEL,
)
from subway_blind.balance import SPEED_PROFILES, speed_profile_for_difficulty
from subway_blind.controls import ConnectedController, PLAYSTATION_FAMILY, XBOX_FAMILY, family_label
from subway_blind.features import (
    HEADSTART_SPEED_BONUS,
    HOVERBOARD_DURATION,
    HOVERBOARD_MAX_USES_PER_RUN,
    REVIVE_MAX_USES_PER_RUN,
    headstart_duration_for_uses,
)
from subway_blind.features import SHOP_PRICES
from subway_blind.game import (
    ACTIVE_GAMEPLAY_SOUND_KEYS,
    HEADSTART_SHAKE_CHANNEL,
    HEADSTART_SPRAY_CHANNEL,
    HOW_TO_TOPICS,
    LEADERBOARD_CACHE_TTL_SECONDS,
    LEARN_SOUND_LOOP_PREVIEW_DURATION,
    LEARN_SOUND_PREVIEW_CHANNEL,
    MENU_REPEAT_INITIAL_DELAY,
    MENU_REPEAT_INTERVAL,
    SubwayBlindGame,
    help_topic_segments,
    load_whats_new_content,
)
from subway_blind.hrtf_audio import OpenALHrtfEngine
from subway_blind.item_upgrades import (
    ItemUpgradeDefinition,
    ensure_item_upgrade_state,
    item_upgrade_duration,
    next_item_upgrade_cost,
)
from subway_blind.menu import Menu, MenuItem
from subway_blind.models import Obstacle, lane_name
from subway_blind.native_windows_credentials import CredentialPromptCancelled, CredentialPromptResult
from subway_blind.native_windows_issue_dialog import IssueDialogCancelled
from subway_blind.quests import daily_quests
from subway_blind.spatial_audio import SpatialThreatAudio
from subway_blind.spawn import PATTERNS, PatternEntry, RoutePattern, SpawnDirector
from subway_blind.updater import (
    GitHubReleaseUpdater,
    ReleaseAsset,
    ReleaseInfo,
    UpdateCheckResult,
    UpdateInstallProgress,
    UpdateInstallResult,
    normalize_version,
    version_key,
)
from subway_blind.version import APP_VERSION


class DummySpeaker:
    def __init__(self):
        self.enabled = True
        self.use_sapi = False
        self.sapi_voice_id = ""
        self.sapi_rate = 0
        self.sapi_pitch = 0
        self.sapi_volume = 100
        self._sapi_voices = [
            ("voice-zira", "Microsoft Zira Desktop - English (United States)"),
            ("voice-david", "Microsoft David Desktop - English (United States)"),
            ("voice-yelda", "VE Turkish Yelda 22kHz"),
        ]
        self.messages: list[tuple[str, bool]] = []
        self.speed_factors: list[float] = []

    def speak(self, text: str, interrupt: bool = True) -> None:
        self.messages.append((text, interrupt))

    def set_speed_factor(self, speed_factor: float) -> None:
        self.speed_factors.append(speed_factor)

    def apply_settings(self, settings: dict) -> None:
        self.enabled = bool(settings.get("speech_enabled", True))
        self.use_sapi = bool(settings.get("sapi_speech_enabled", False))
        self.sapi_rate = max(SAPI_RATE_MIN, min(SAPI_RATE_MAX, int(settings.get("sapi_rate", 0))))
        self.sapi_pitch = max(SAPI_PITCH_MIN, min(SAPI_PITCH_MAX, int(settings.get("sapi_pitch", 0))))
        self.sapi_volume = max(0, min(100, int(settings.get("sapi_volume", 100))))
        requested_voice_id = str(settings.get("sapi_voice_id", "") or "").strip()
        if any(voice_id == requested_voice_id for voice_id, _ in self._sapi_voices):
            self.sapi_voice_id = requested_voice_id
        elif self._sapi_voices:
            self.sapi_voice_id = self._sapi_voices[0][0]
        else:
            self.sapi_voice_id = ""

    def current_sapi_voice_display_name(self) -> str:
        for voice_id, name in self._sapi_voices:
            if voice_id == self.sapi_voice_id:
                return name
        if self._sapi_voices:
            return self._sapi_voices[0][1]
        return "Unavailable"

    def cycle_sapi_voice(self, direction: int) -> str:
        if not self._sapi_voices:
            return "Unavailable"
        current_ids = [voice_id for voice_id, _ in self._sapi_voices]
        try:
            current_index = current_ids.index(self.sapi_voice_id)
        except ValueError:
            current_index = 0
        next_index = (current_index + (-1 if direction < 0 else 1)) % len(self._sapi_voices)
        self.sapi_voice_id = self._sapi_voices[next_index][0]
        return self._sapi_voices[next_index][1]


class DummyAudio:
    def __init__(self, settings: dict):
        self.settings = settings
        self.sounds = {}
        self.played: list[tuple[str, str | None, bool]] = []
        self.play_calls: list[dict[str, object]] = []
        self.spatial_played: list[tuple[str, str, float, float, float, float, float, float | None]] = []
        self.spatial_updated: list[tuple[str, float, float, float, float, float, float | None]] = []
        self.stopped: list[str] = []
        self.refreshed = 0
        self.music_started = 0
        self.music_stopped = 0
        self.music_started_tracks: list[str] = []
        self.music_update_calls: list[float] = []
        self.music_idle = False
        self._output_device_name = settings.get("audio_output_device") or None

    def play(self, key: str, pan=None, loop: bool = False, channel: str | None = None, gain: float = 1.0) -> None:
        self.play_calls.append({"key": key, "channel": channel, "loop": loop, "pan": pan, "gain": gain})
        self.played.append((key, channel, loop))

    def stop(self, channel: str) -> None:
        self.stopped.append(channel)

    def has_sound(self, key: str) -> bool:
        return True

    def play_spatial(
        self,
        key: str,
        channel: str,
        x: float,
        y: float,
        z: float,
        gain: float,
        pitch: float = 1.0,
        fallback_pan: float | None = None,
        velocity_x: float = 0.0,
        velocity_y: float = 0.0,
        velocity_z: float = 0.0,
    ) -> None:
        self.spatial_played.append(
            (key, channel, x, y, z, gain, pitch, fallback_pan, velocity_x, velocity_y, velocity_z)
        )

    def update_spatial(
        self,
        channel: str,
        x: float,
        y: float,
        z: float,
        gain: float,
        pitch: float = 1.0,
        fallback_pan: float | None = None,
        velocity_x: float = 0.0,
        velocity_y: float = 0.0,
        velocity_z: float = 0.0,
    ) -> None:
        self.spatial_updated.append((channel, x, y, z, gain, pitch, fallback_pan, velocity_x, velocity_y, velocity_z))

    def refresh_volumes(self) -> None:
        self.refreshed += 1

    def music_start(self, track_key: str = "gameplay") -> None:
        self.music_started += 1
        self.music_started_tracks.append(track_key)
        self.music_idle = False

    def music_stop(self, immediate: bool = False) -> None:
        self.music_stopped += 1
        self.music_idle = True

    def update(self, delta_time: float) -> None:
        self.music_update_calls.append(delta_time)

    def music_is_idle(self) -> bool:
        return self.music_idle

    def _get_channel(self, name: str):
        return None

    def output_device_display_name(self) -> str:
        return self._output_device_name or SYSTEM_DEFAULT_OUTPUT_LABEL

    def current_output_device_name(self) -> str | None:
        return self._output_device_name

    def output_device_choices(self) -> list[str | None]:
        return [None, "External USB Headphones", "Studio Speakers"]

    def apply_output_device(self, device_name: str | None) -> str | None:
        self._output_device_name = device_name
        self.settings["audio_output_device"] = device_name or ""
        return self._output_device_name


class DummyUpdater:
    def __init__(self):
        self.check_results: list[UpdateCheckResult] = [
            UpdateCheckResult(
                status="no_releases",
                current_version=APP_VERSION,
                message="No published releases were found.",
            )
        ]
        self.check_calls = 0
        self.download_calls: list[ReleaseInfo] = []
        self.open_calls: list[ReleaseInfo | None] = []
        self.install_result = UpdateInstallResult(
            success=True,
            message="Update installed. Restart the game to finish applying it.",
            restart_required=True,
            restart_script_path=r"C:\Users\oguzhan\AppData\Local\Temp\apply_update.cmd",
        )
        self.open_success = True
        self.launch_restart_calls: list[str | None] = []

    def enqueue_result(self, result: UpdateCheckResult) -> None:
        self.check_results.append(result)

    def check_for_updates(self, current_version: str) -> UpdateCheckResult:
        self.check_calls += 1
        if self.check_results:
            return self.check_results.pop(0)
        return UpdateCheckResult(
            status="no_releases",
            current_version=current_version,
            message="No published releases were found.",
        )

    def has_installable_package(self, release: ReleaseInfo) -> bool:
        return any(asset.name.endswith(".zip") for asset in release.assets)

    def download_and_install(self, release: ReleaseInfo, progress_callback=None) -> UpdateInstallResult:
        self.download_calls.append(release)
        if progress_callback is not None:
            progress_callback(UpdateInstallProgress("download", 100.0, "Downloading update package. 100 percent."))
            progress_callback(UpdateInstallProgress("extract", 100.0, "Extracting update package. 100 percent."))
        return self.install_result

    def open_release_page(self, release: ReleaseInfo | None = None) -> bool:
        self.open_calls.append(release)
        return self.open_success

    def launch_restart_script(self, restart_script_path: str | None) -> bool:
        self.launch_restart_calls.append(restart_script_path)
        return restart_script_path is not None


class DummyControllerDevice:
    def __init__(self, name: str):
        self.name = name
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


def make_release_info(version: str = "1.1.3") -> ReleaseInfo:
    return ReleaseInfo(
        version=version,
        page_url=f"https://github.com/oguzhanproductions/subway_surfers_blind/releases/tag/v{version}",
        published_at="2026-03-08T10:00:00Z",
        title=f"v{version}",
        notes="Important fixes.",
        assets=(
            ReleaseAsset(
                name="SubwaySurfersBlind.zip",
                download_url="https://example.com/SubwaySurfersBlind.zip",
                content_type="application/zip",
                size=2048,
            ),
        ),
    )


class MenuTests(unittest.TestCase):
    def test_menu_navigation_and_selection(self):
        speaker = DummySpeaker()
        audio = DummyAudio({})
        menu = Menu(speaker, audio, "Main Menu", [MenuItem("Start", "start"), MenuItem("Quit", "quit")])

        menu.open()
        self.assertEqual(menu.index, 0)
        self.assertIn(("menuopen", "ui", False), audio.played)
        self.assertEqual(speaker.messages[0][0], "Main Menu. Start")

        self.assertIsNone(menu.handle_key(pygame.K_DOWN))
        self.assertEqual(menu.index, 1)
        self.assertEqual(speaker.messages[-1][0], "Quit")

        action = menu.handle_key(pygame.K_RETURN)
        self.assertEqual(action, "quit")
        self.assertIn(("confirm", "ui", False), audio.played)

    def test_menu_open_starts_from_left_and_moves_right_by_index(self):
        speaker = DummySpeaker()
        audio = DummyAudio({})
        menu = Menu(
            speaker,
            audio,
            "Main Menu",
            [MenuItem("Start", "start"), MenuItem("Shop", "shop"), MenuItem("Options", "options")],
        )

        menu.open(start_index=0)
        self.assertAlmostEqual(audio.play_calls[-1]["pan"], -0.8)

        menu.open(start_index=2)
        self.assertAlmostEqual(audio.play_calls[-1]["pan"], 0.8)

    def test_menu_home_and_end_jump_to_bounds(self):
        speaker = DummySpeaker()
        audio = DummyAudio({})
        menu = Menu(
            speaker,
            audio,
            "Main Menu",
            [MenuItem("Start", "start"), MenuItem("Shop", "shop"), MenuItem("Quit", "quit")],
        )

        menu.open(start_index=1)
        menu.handle_key(pygame.K_END)
        self.assertEqual(menu.index, 2)
        self.assertEqual(speaker.messages[-1][0], "Quit")

        menu.handle_key(pygame.K_HOME)
        self.assertEqual(menu.index, 0)
        self.assertEqual(speaker.messages[-1][0], "Start")

    def test_menu_navigation_and_confirm_use_current_item_pan(self):
        speaker = DummySpeaker()
        audio = DummyAudio({})
        menu = Menu(
            speaker,
            audio,
            "Main Menu",
            [MenuItem("Start", "start"), MenuItem("Shop", "shop"), MenuItem("Quit", "quit")],
        )

        menu.open(start_index=0)
        menu.handle_key(pygame.K_DOWN)
        self.assertAlmostEqual(audio.play_calls[-1]["pan"], 0.0)

        menu.handle_key(pygame.K_DOWN)
        self.assertAlmostEqual(audio.play_calls[-1]["pan"], 0.8)

        menu.handle_key(pygame.K_RETURN)
        self.assertAlmostEqual(audio.play_calls[-1]["pan"], 0.8)

    def test_menu_sound_hrtf_setting_disables_menu_pan(self):
        speaker = DummySpeaker()
        audio = DummyAudio({"menu_sound_hrtf": False})
        menu = Menu(
            speaker,
            audio,
            "Main Menu",
            [MenuItem("Start", "start"), MenuItem("Shop", "shop"), MenuItem("Quit", "quit")],
        )

        menu.open(start_index=2)
        self.assertIsNone(audio.play_calls[-1]["pan"])

        menu.handle_key(pygame.K_DOWN)
        self.assertIsNone(audio.play_calls[-1]["pan"])


class ConfigTests(unittest.TestCase):
    def test_settings_round_trip_preserves_defaults(self):
        original_base_dir = config_module.BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            config_module.BASE_DIR = Path(temp_directory)
            config_module.save_settings({"sfx_volume": 0.4})
            loaded = config_module.load_settings()
        config_module.BASE_DIR = original_base_dir

        self.assertEqual(loaded["sfx_volume"], 0.4)
        self.assertEqual(loaded["music_volume"], config_module.DEFAULT_SETTINGS["music_volume"])
        self.assertEqual(loaded["menu_sound_hrtf"], config_module.DEFAULT_SETTINGS["menu_sound_hrtf"])
        self.assertEqual(loaded["sapi_speech_enabled"], config_module.DEFAULT_SETTINGS["sapi_speech_enabled"])
        self.assertEqual(loaded["sapi_voice_id"], config_module.DEFAULT_SETTINGS["sapi_voice_id"])
        self.assertEqual(loaded["sapi_rate"], config_module.DEFAULT_SETTINGS["sapi_rate"])
        self.assertEqual(loaded["sapi_pitch"], config_module.DEFAULT_SETTINGS["sapi_pitch"])
        self.assertEqual(loaded["sapi_volume"], config_module.DEFAULT_SETTINGS["sapi_volume"])
        self.assertEqual(
            loaded["check_updates_on_startup"],
            config_module.DEFAULT_SETTINGS["check_updates_on_startup"],
        )
        self.assertEqual(loaded["difficulty"], "normal")
        self.assertEqual(loaded["selected_character"], config_module.DEFAULT_SETTINGS["selected_character"])
        self.assertEqual(loaded["character_progress"], config_module.DEFAULT_SETTINGS["character_progress"])
        self.assertEqual(loaded["item_upgrades"], config_module.DEFAULT_SETTINGS["item_upgrades"])
        self.assertEqual(
            loaded["main_menu_descriptions_enabled"],
            config_module.DEFAULT_SETTINGS["main_menu_descriptions_enabled"],
        )
        self.assertEqual(
            loaded["pause_on_focus_loss_enabled"],
            config_module.DEFAULT_SETTINGS["pause_on_focus_loss_enabled"],
        )
        self.assertEqual(
            loaded["confirm_exit_enabled"],
            config_module.DEFAULT_SETTINGS["confirm_exit_enabled"],
        )

    def test_settings_round_trip_preserves_item_upgrades(self):
        original_base_dir = config_module.BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            config_module.BASE_DIR = Path(temp_directory)
            settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
            settings["bank_coins"] = 7200
            settings["item_upgrades"]["magnet"] = 3
            settings["item_upgrades"]["jetpack"] = 1
            config_module.save_settings(settings)
            loaded = config_module.load_settings()
        config_module.BASE_DIR = original_base_dir

        self.assertEqual(loaded["bank_coins"], 7200)
        self.assertEqual(
            loaded["item_upgrades"],
            {
                "magnet": 3,
                "jetpack": 1,
                "mult2x": 0,
                "sneakers": 0,
            },
        )

    def test_settings_round_trip_preserves_leaderboard_session_token(self):
        original_base_dir = config_module.BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            config_module.BASE_DIR = Path(temp_directory)
            settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
            settings["leaderboard_username"] = "runner01"
            settings["leaderboard_session_token"] = "session-token-123"
            config_module.save_settings(settings)
            loaded = config_module.load_settings()
        config_module.BASE_DIR = original_base_dir

        self.assertEqual(loaded["leaderboard_username"], "runner01")
        self.assertEqual(loaded["leaderboard_session_token"], "session-token-123")

    def test_item_upgrade_state_normalizes_invalid_values(self):
        settings = {"item_upgrades": {"magnet": "2", "jetpack": "bad", "mult2x": -9, "sneakers": 999}}

        ensure_item_upgrade_state(settings)

        self.assertEqual(
            settings["item_upgrades"],
            {
                "magnet": 2,
                "jetpack": 0,
                "mult2x": 0,
                "sneakers": 5,
            },
        )

    def test_item_upgrade_definition_rejects_invalid_duration_scale(self):
        with self.assertRaises(ValueError):
            ItemUpgradeDefinition(
                key="invalid",
                name="Invalid Upgrade",
                description="Broken",
                upgrade_costs=(500, 1000),
                durations=(5.0, 10.0),
            )

    def test_default_storage_base_dir_uses_roaming_appdata_vendor_and_game_name(self):
        with patch.dict(os.environ, {"APPDATA": r"C:\Users\Test\AppData\Roaming"}, clear=False):
            storage_path = config_module._default_storage_base_dir()

        self.assertEqual(
            storage_path,
            Path(r"C:\Users\Test\AppData\Roaming") / "Vireon Interactive" / "Subway Surfers Blind Edition",
        )

    def test_resource_path_prefers_external_resource_directory(self):
        original_resource_base_dir = config_module.RESOURCE_BASE_DIR
        original_bundled_resource_base_dir = config_module.BUNDLED_RESOURCE_BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            external_assets = temp_root / "external" / "assets" / "sfx"
            bundled_assets = temp_root / "bundled" / "assets" / "sfx"
            external_assets.mkdir(parents=True, exist_ok=True)
            bundled_assets.mkdir(parents=True, exist_ok=True)
            (external_assets / "coin.wav").write_bytes(b"external")
            (bundled_assets / "coin.wav").write_bytes(b"bundled")
            config_module.RESOURCE_BASE_DIR = temp_root / "external"
            config_module.BUNDLED_RESOURCE_BASE_DIR = temp_root / "bundled"

            resolved_path = config_module.resource_path("assets", "sfx", "coin.wav")
        config_module.RESOURCE_BASE_DIR = original_resource_base_dir
        config_module.BUNDLED_RESOURCE_BASE_DIR = original_bundled_resource_base_dir

        self.assertEqual(resolved_path, str(external_assets / "coin.wav"))

    def test_load_settings_migrates_legacy_localappdata_data(self):
        original_base_dir = config_module.BASE_DIR
        original_resource_base_dir = config_module.RESOURCE_BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            roaming_base_dir = temp_root / "Roaming" / "Vireon Interactive" / "Subway Surfers Blind Edition"
            legacy_local_root = temp_root / "Local" / "SubwaySurfersBlind"
            legacy_data_directory = legacy_local_root / "data"
            legacy_data_directory.mkdir(parents=True, exist_ok=True)
            legacy_settings_path = legacy_data_directory / "settings.json"
            legacy_settings_path.write_text(
                json.dumps({"sfx_volume": 0.2, "bank_coins": 321}),
                encoding="utf-8",
            )
            config_module.BASE_DIR = roaming_base_dir
            config_module.RESOURCE_BASE_DIR = temp_root / "bundle"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(temp_root / "Local")}, clear=False):
                loaded = config_module.load_settings()
            migrated_settings_path = roaming_base_dir / "data" / "settings.json"
            self.assertTrue(migrated_settings_path.exists())
        config_module.BASE_DIR = original_base_dir
        config_module.RESOURCE_BASE_DIR = original_resource_base_dir

        self.assertEqual(loaded["sfx_volume"], 0.2)
        self.assertEqual(loaded["bank_coins"], 321)

    def test_load_settings_uses_backup_when_primary_file_is_corrupt(self):
        original_base_dir = config_module.BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            config_module.BASE_DIR = Path(temp_directory)
            settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
            settings["bank_coins"] = 1800
            settings["item_upgrades"]["mult2x"] = 2
            config_module.save_settings(settings)
            settings_path = config_module._settings_path()
            backup_path = config_module._settings_backup_path()
            shutil.copy2(settings_path, backup_path)
            settings_path.write_text("{broken json", encoding="utf-8")

            loaded = config_module.load_settings()
        config_module.BASE_DIR = original_base_dir

        self.assertEqual(loaded["bank_coins"], 1800)
        self.assertEqual(loaded["item_upgrades"]["mult2x"], 2)


class BalanceTests(unittest.TestCase):
    def test_normal_profile_reaches_cap_at_three_minutes(self):
        profile = SPEED_PROFILES["normal"]
        self.assertAlmostEqual(profile.speed_for_elapsed(0.0), 18.4)
        self.assertAlmostEqual(profile.speed_for_elapsed(180.0), 33.9)
        self.assertAlmostEqual(profile.speed_for_elapsed(240.0), 33.9)

    def test_unknown_difficulty_falls_back_to_normal(self):
        self.assertIs(speed_profile_for_difficulty("unknown"), SPEED_PROFILES["normal"])


class AudioTests(unittest.TestCase):
    def test_footstep_pan_does_not_follow_lane(self):
        self.assertEqual(Audio._normalize_pan_for_key("left_foot", 0.9), -0.18)
        self.assertEqual(Audio._normalize_pan_for_key("right_foot", -0.9), 0.18)
        self.assertEqual(Audio._normalize_pan_for_key("jump", 0.9), 0.0)
        self.assertEqual(Audio._normalize_pan_for_key("dodge", -0.9), 0.0)

    def test_audio_loads_standard_jetpack_loop_asset(self):
        loaded: list[tuple[str, str]] = []

        def capture_load(_self, key: str, path: str) -> None:
            loaded.append((key, path))

        with patch.object(Audio, "_load_sound", autospec=True, side_effect=capture_load), patch(
            "subway_blind.audio.OpenALHrtfEngine",
            return_value=type(
                "FakeHrtf",
                (),
                {
                    "available": False,
                    "register_sound": staticmethod(lambda *_args, **_kwargs: None),
                    "set_listener_gain": staticmethod(lambda *_args, **_kwargs: None),
                    "stop": staticmethod(lambda *_args, **_kwargs: None),
                    "play_sound": staticmethod(lambda *_args, **_kwargs: False),
                    "update_source": staticmethod(lambda *_args, **_kwargs: False),
                },
            )(),
        ):
            Audio(copy.deepcopy(config_module.DEFAULT_SETTINGS))

        jetpack_entry = next(path for key, path in loaded if key == "jetpack_loop")
        self.assertTrue(jetpack_entry.endswith("assets\\sfx\\jetpack_loop.wav"))

    def test_audio_loads_leaderboard_feedback_assets(self):
        loaded: list[tuple[str, str]] = []

        def capture_load(_self, key: str, path: str) -> None:
            loaded.append((key, path))

        with patch.object(Audio, "_load_sound", autospec=True, side_effect=capture_load), patch(
            "subway_blind.audio.OpenALHrtfEngine",
            return_value=type(
                "FakeHrtf",
                (),
                {
                    "available": False,
                    "register_sound": staticmethod(lambda *_args, **_kwargs: None),
                    "set_listener_gain": staticmethod(lambda *_args, **_kwargs: None),
                    "stop": staticmethod(lambda *_args, **_kwargs: None),
                    "play_sound": staticmethod(lambda *_args, **_kwargs: False),
                    "update_source": staticmethod(lambda *_args, **_kwargs: False),
                },
            )(),
        ):
            Audio(copy.deepcopy(config_module.DEFAULT_SETTINGS))

        loaded_map = dict(loaded)
        self.assertTrue(loaded_map["connect"].endswith("assets\\sfx\\connect.mp3"))
        self.assertTrue(loaded_map["high"].endswith("assets\\sfx\\high.mp3"))

    def test_transient_player_channels_are_collapsed(self):
        self.assertEqual(Audio._normalize_channel_for_key("jump", "act"), "player_jump")
        self.assertEqual(Audio._normalize_channel_for_key("dodge", "move"), "player_dodge")
        self.assertEqual(Audio._normalize_channel_for_key("left_foot", "foot"), "player_footstep")
        self.assertEqual(Audio._normalize_channel_for_key("coin", "coin"), "player_pickup")
        self.assertEqual(Audio._normalize_channel_for_key("powerup", "act"), "player_power")

    def test_output_device_choices_keep_default_first_and_current_device_present(self):
        audio = Audio.__new__(Audio)
        audio.settings = {"audio_output_device": "Studio Monitor"}
        with patch("subway_blind.audio.list_output_devices", return_value=["USB DAC", "Studio Monitor"]):
            self.assertEqual(audio.output_device_choices(), [None, "USB DAC", "Studio Monitor"])

    def test_cycle_output_device_wraps_back_to_system_default(self):
        audio = Audio.__new__(Audio)
        audio.settings = {"audio_output_device": "USB DAC"}
        audio.apply_output_device = lambda device_name: device_name
        with patch.object(audio, "output_device_choices", return_value=[None, "USB DAC"]):
            requested, applied = audio.cycle_output_device()
        self.assertIsNone(requested)
        self.assertIsNone(applied)

    def test_discover_music_catalog_uses_first_matching_slot_file(self):
        audio = Audio.__new__(Audio)
        with patch("subway_blind.audio.resource_path", side_effect=lambda *parts: "/".join(parts)), patch(
            "subway_blind.audio.os.path.exists",
            side_effect=lambda path: path in {"assets/music/menu_intro.ogg", "assets/music/theme.ogg"},
        ):
            catalog = audio._discover_music_catalog()

        self.assertEqual(catalog["menu"], "assets/music/menu_intro.ogg")
        self.assertEqual(catalog["gameplay"], "assets/music/theme.ogg")

    def test_load_sound_keeps_running_when_hrtf_registration_fails(self):
        audio = Audio.__new__(Audio)
        audio.settings = {"sfx_volume": 1.0}
        audio.sounds = {}
        audio.sound_paths = {}
        audio.sound_channel_counts = {}
        audio._mixer_ready = False

        class RaisingHrtf:
            def register_sound(self, key: str, path: str) -> None:
                raise RuntimeError("boom")

        audio.hrtf = RaisingHrtf()

        with patch("subway_blind.audio.os.path.exists", return_value=True):
            audio._load_sound("coin", "coin.wav")

        self.assertEqual(audio.sound_paths["coin"], "coin.wav")

    def test_resolve_playback_path_forces_menu_feedback_to_mono(self):
        audio = Audio.__new__(Audio)
        audio.hrtf = type(
            "FakeHrtf",
            (),
            {
                "_prepare_openal_path": staticmethod(
                    lambda source, refresh=False, spatialize=False: "menuopen_mono.wav" if spatialize else str(source)
                )
            },
        )()

        with patch.object(Audio, "_read_sound_channel_count", side_effect=lambda path: 1 if path == "menuopen_mono.wav" else 2):
            self.assertEqual(audio._resolve_playback_path("menuopen", "menuopen.wav"), "menuopen_mono.wav")
            self.assertEqual(audio._resolve_playback_path("mission_reward", "mission_reward.wav"), "mission_reward.wav")

    def test_play_uses_mixer_for_stereo_assets_even_when_hrtf_is_available(self):
        audio = Audio.__new__(Audio)
        audio.settings = {"sfx_volume": 1.0, "menu_sound_hrtf": True}
        audio.sound_paths = {"mission_reward": "mission_reward.wav"}
        audio.sound_channel_counts = {"mission_reward": 2}
        audio.sounds = {"mission_reward": object()}
        audio.channels = {}
        audio._mixer_ready = True
        audio._get_channel = lambda _name: type(
            "Channel",
            (),
            {
                "volumes": [],
                "plays": [],
                "set_volume": lambda self, *values: self.volumes.append(values),
                "play": lambda self, sound, loops=0: self.plays.append((sound, loops)),
            },
        )()

        class FakeHrtf:
            available = True

            def play_sound(self, *args, **kwargs):
                raise AssertionError("Stereo assets should not be routed through HRTF in normal playback")

        audio.hrtf = FakeHrtf()

        audio.play("mission_reward", channel="player_reward")

    def test_play_uses_hrtf_for_mono_assets_when_available(self):
        audio = Audio.__new__(Audio)
        audio.settings = {"sfx_volume": 1.0, "menu_sound_hrtf": True}
        audio.sound_paths = {"warning": "warning.wav"}
        audio.sound_channel_counts = {"warning": 1}
        audio.sounds = {}
        audio.channels = {}
        audio._mixer_ready = False
        hrtf_calls: list[dict[str, object]] = []

        class FakeHrtf:
            available = True

            def play_sound(self, **kwargs):
                hrtf_calls.append(kwargs)
                return True

        audio.hrtf = FakeHrtf()

        audio.play("warning", channel="warn_lane", pan=-0.4)

        self.assertEqual(len(hrtf_calls), 1)
        self.assertFalse(bool(hrtf_calls[0]["spatialize"]))

    def test_play_respects_menu_hrtf_setting_for_ui_channels(self):
        audio = Audio.__new__(Audio)
        audio.settings = {"sfx_volume": 1.0, "menu_sound_hrtf": False}
        audio.sound_paths = {"menuopen": "menuopen.wav"}
        audio.sound_channel_counts = {"menuopen": 1}
        audio.sounds = {"menuopen": object()}
        audio.channels = {}
        audio._mixer_ready = True
        captured_channel = type(
            "Channel",
            (),
            {
                "volumes": [],
                "plays": [],
                "set_volume": lambda self, *values: self.volumes.append(values),
                "play": lambda self, sound, loops=0: self.plays.append((sound, loops)),
            },
        )()
        audio._get_channel = lambda _name: captured_channel

        class FakeHrtf:
            available = True

            def play_sound(self, *args, **kwargs):
                raise AssertionError("UI playback should bypass HRTF when menu_sound_hrtf is disabled")

        audio.hrtf = FakeHrtf()

        audio.play("menuopen", channel="ui", pan=0.25)

        self.assertEqual(captured_channel.plays, [(audio.sounds["menuopen"], 0)])

    def test_update_starts_pending_track_after_music_fades_out(self):
        audio = Audio.__new__(Audio)
        audio._mixer_ready = True
        audio._music_transition = "fade_out"
        audio._music_current_track = "menu"
        audio._music_pending_track = "gameplay"
        audio._music_fade_level = 0.05
        audio._apply_music_volume = lambda: None
        played_tracks: list[str] = []

        def stop_music_immediately() -> None:
            audio._music_current_track = None
            audio._music_pending_track = None
            audio._music_fade_level = 0.0
            audio._music_transition = None

        audio._stop_music_immediately = stop_music_immediately
        audio._play_music_track = lambda track_key: played_tracks.append(track_key) or True

        audio.update(1.0)

        self.assertEqual(played_tracks, ["gameplay"])


class UpdaterTests(unittest.TestCase):
    def test_normalize_version_handles_semver_and_v_prefix(self):
        self.assertEqual(normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("2.0"), "2.0.0")

    def test_version_key_orders_versions_correctly(self):
        self.assertGreater(version_key("1.4.0"), version_key("1.3.9"))
        self.assertEqual(version_key("v2.0"), (2, 0, 0))

    def test_check_for_updates_returns_update_available_when_release_is_newer(self):
        updater = GitHubReleaseUpdater(timeout_seconds=2.0)
        next_patch_version = f"{'.'.join(APP_VERSION.split('.')[:-1])}.{int(APP_VERSION.split('.')[-1]) + 1}"
        release_payload = {
            "tag_name": f"v{next_patch_version}",
            "name": f"v{next_patch_version}",
            "html_url": f"https://github.com/oguzhanproductions/subway_surfers_blind/releases/tag/v{next_patch_version}",
            "published_at": "2026-03-08T10:00:00Z",
            "body": "Notes",
            "assets": [
                {
                    "name": "SubwaySurfersBlind.zip",
                    "browser_download_url": "https://example.com/SubwaySurfersBlind.zip",
                    "content_type": "application/zip",
                    "size": 2048,
                }
            ],
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(release_payload).encode("utf-8")

        with patch("subway_blind.updater.urllib.request.urlopen", return_value=FakeResponse()):
            result = updater.check_for_updates(APP_VERSION)

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, next_patch_version)
        self.assertEqual(result.release.assets[0].name, "SubwaySurfersBlind.zip")

    def test_download_and_install_stages_release_and_removes_archive(self):
        updater = GitHubReleaseUpdater(timeout_seconds=2.0)
        release = make_release_info("0.2.0")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("SubwaySurfersBlind/SubwaySurfersBlind.exe", b"updated-exe")
            archive.writestr("SubwaySurfersBlind/assets/manifest.txt", b"manifest")
        payload = zip_buffer.getvalue()

        class FakeResponse:
            def __init__(self, data: bytes):
                self._stream = io.BytesIO(data)
                self.headers = {"Content-Length": str(len(data))}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size: int = -1):
                return self._stream.read(size)

        progress_updates: list[UpdateInstallProgress] = []
        with tempfile.TemporaryDirectory() as temp_directory, patch.object(
            updater_module, "BASE_DIR", Path(temp_directory)
        ), patch("subway_blind.updater.urllib.request.urlopen", return_value=FakeResponse(payload)), patch.object(
            sys, "frozen", True, create=True
        ):
            result = updater.download_and_install(release, progress_callback=progress_updates.append)
            updates_root = Path(temp_directory) / "updates"
            self.assertTrue(result.success)
            self.assertIsNotNone(result.restart_script_path)
            self.assertFalse((updates_root / "SubwaySurfersBlind.zip").exists())
            staged_executable = next(updates_root.rglob("SubwaySurfersBlind.exe"))
            staged_manifest = next(updates_root.rglob("manifest.txt"))
            self.assertEqual(staged_executable.read_bytes(), b"updated-exe")
            self.assertEqual(staged_manifest.read_bytes(), b"manifest")
            script_text = Path(result.restart_script_path).read_text(encoding="utf-8")
            self.assertIn("Copy-Item -LiteralPath '%STAGE%\\*'", script_text)
            self.assertIn("rmdir /S /Q \"%STAGE%\"", script_text)
            self.assertIn("del /Q \"%ARCHIVE%\"", script_text)
        self.assertEqual(progress_updates[-1].stage, "ready")


class SpeakerTests(unittest.TestCase):
    def test_set_speed_factor_applies_rate_to_supported_outputs(self):
        class RateOutput:
            def __init__(self):
                self.rate = None

            def has_rate(self):
                return True

            def min_rate(self):
                return -10

            def max_rate(self):
                return 10

            def set_rate(self, value):
                self.rate = value
        speaker = Speaker(enabled=False)
        speaker._driver = type("Driver", (), {"outputs": [RateOutput()]})()

        speaker.set_speed_factor(1.0)

        rate_output = speaker._driver.outputs[0]
        self.assertIsNotNone(rate_output.rate)
        self.assertGreater(rate_output.rate, 0.0)

    def test_sapi_rate_combines_manual_setting_with_speed_factor(self):
        class FakeSapiVoice:
            def __init__(self):
                self.Rate = 0

        speaker = Speaker(enabled=False, sapi_rate=3)
        speaker.enabled = True
        speaker._sapi_voice = FakeSapiVoice()

        speaker.set_speed_factor(1.0)

        self.assertEqual(speaker._sapi_voice.Rate, 7)

    def test_sapi_speak_wraps_text_in_pitch_xml(self):
        class FakeSapiVoice:
            def __init__(self):
                self.calls: list[tuple[str, int]] = []

            def Speak(self, text: str, flags: int) -> None:
                self.calls.append((text, flags))

        speaker = Speaker(enabled=False, use_sapi=True, sapi_pitch=4)
        speaker.enabled = True
        speaker._sapi_voice = FakeSapiVoice()

        speaker.speak("Ready & go", interrupt=True)

        text, flags = speaker._sapi_voice.calls[-1]
        self.assertEqual(text, '<pitch middle="+4">Ready &amp; go</pitch>')
        self.assertTrue(flags & SAPI_SPEAK_IS_XML)



class FakeOpenALSource:
    def __init__(self):
        self.reference_distance = 0.0
        self.rolloff_factor = 0.0
        self.max_distance = 0.0
        self.relative = False
        self.looping = False
        self.gain = 0.0
        self.pitch = 1.0
        self.playing = False
        self.calls: list[tuple[str, object | None]] = []

    def set_buffer(self, buffer) -> None:
        self.calls.append(("set_buffer", buffer))

    def set_position(self, x: float, y: float, z: float) -> None:
        self.calls.append(("set_position", (x, y, z)))

    def set_velocity(self, x: float, y: float, z: float) -> None:
        self.calls.append(("set_velocity", (x, y, z)))

    def stop(self) -> None:
        self.calls.append(("stop", None))
        self.playing = False

    def play(self) -> None:
        self.calls.append(("play", None))
        self.playing = True


class FakeOpenALModule:
    def __init__(self, source: FakeOpenALSource):
        self._source = source

    def Source(self) -> FakeOpenALSource:
        return self._source


class HrtfEngineTests(unittest.TestCase):
    def _write_wav(self, path: Path, channels: int) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(2)
            writer.setframerate(44100)
            writer.writeframes((b"\x00\x00" * channels) * 64)

    def test_changing_buffer_stops_source_before_rebinding(self):
        source = FakeOpenALSource()
        engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
        engine.available = True
        engine._al = FakeOpenALModule(source)
        engine._buffers = {
            "box::direct": object(),
            "jump::direct": object(),
        }
        engine._buffer_paths = {}
        engine._sources = {}
        engine._channel_keys = {}
        engine._listener_gain = 1.0
        engine.register_sound = lambda key, path, spatialize=False: OpenALHrtfEngine._buffer_cache_key(key, spatialize)

        engine.play_sound("box", "box.wav", "player_action", 0.0, 0.0, -1.0, 1.0)
        source.calls.clear()
        source.playing = True

        engine.play_sound("jump", "jump.wav", "player_action", 0.0, 0.0, -1.0, 1.0)

        self.assertEqual(source.calls[0][0], "stop")
        self.assertEqual(source.calls[1][0], "set_buffer")
        self.assertEqual(engine._channel_keys["player_action"], "jump")

    def test_stop_clears_channel_key(self):
        source = FakeOpenALSource()
        engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
        engine.available = True
        engine._al = FakeOpenALModule(source)
        engine._buffers = {}
        engine._buffer_paths = {}
        engine._sources = {"player_action": source}
        engine._channel_keys = {"player_action": "box"}
        engine._listener_gain = 1.0

        engine.stop("player_action")

        self.assertNotIn("player_action", engine._channel_keys)
        self.assertEqual(source.calls[-1][0], "stop")

    def test_update_source_ignores_missing_or_stopped_sources(self):
        source = FakeOpenALSource()
        engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
        engine.available = True
        engine._sources = {"player_action": source}
        engine._listener_gain = 1.0

        self.assertFalse(engine.update_source("missing", 0.0, 0.0, -1.0, 1.0))
        self.assertFalse(engine.update_source("player_action", 0.0, 0.0, -1.0, 1.0))

    def test_update_source_repositions_playing_source(self):
        source = FakeOpenALSource()
        source.playing = True
        engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
        engine.available = True
        engine._sources = {"spatial_0": source}
        engine._listener_gain = 1.0

        updated = engine.update_source("spatial_0", 1.2, -0.1, -4.0, 0.8, 1.1, True)

        self.assertTrue(updated)
        self.assertEqual(source.calls[-2], ("set_position", (1.2, -0.1, -4.0)))
        self.assertEqual(source.calls[-1], ("set_velocity", (0.0, 0.0, 0.0)))
        self.assertTrue(source.relative)

    def test_prepare_openal_path_stages_unicode_wav_into_ascii_cache(self):
        engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_directory = root / ("profile_" + chr(0x0130))
            source_directory.mkdir(parents=True, exist_ok=True)
            program_data = root / "ProgramData"
            source_path = source_directory / "coin.wav"
            self._write_wav(source_path, channels=2)

            with patch("subway_blind.hrtf_audio.BASE_DIR", source_directory), patch.dict(
                os.environ,
                {"PROGRAMDATA": str(program_data)},
                clear=False,
            ):
                prepared_path = Path(engine._prepare_openal_path(source_path, spatialize=True))

            self.assertNotEqual(prepared_path, source_path)
            self.assertTrue(prepared_path.exists())
            self.assertTrue(str(prepared_path).isascii())
            with wave.open(str(prepared_path), "rb") as reader:
                self.assertEqual(reader.getnchannels(), 1)

            try:
                import pyopenalsoft as openal
            except Exception:
                openal = None

            if openal is not None and os.name == "nt":
                with self.assertRaises(RuntimeError):
                    openal.AudioData(str(source_path))
                self.assertEqual(openal.AudioData(str(prepared_path)).channels, 1)

    def test_prepare_openal_path_preserves_stereo_wav_when_not_spatialized(self):
        engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
        with tempfile.TemporaryDirectory() as temp_root:
            source_path = Path(temp_root) / "reward.wav"
            self._write_wav(source_path, channels=2)

            prepared_path = Path(engine._prepare_openal_path(source_path, spatialize=False))

            self.assertEqual(prepared_path, source_path)
            with wave.open(str(prepared_path), "rb") as reader:
                self.assertEqual(reader.getnchannels(), 2)

    def test_register_sound_returns_without_raising_when_openal_load_fails(self):
        class FailingOpenALModule:
            def AudioData(self, path: str):
                raise RuntimeError("invalid audio")

            def Buffer(self, audio_data):
                raise AssertionError("Buffer should not be created when AudioData fails")

        with tempfile.TemporaryDirectory() as temp_root:
            source_path = Path(temp_root) / "coin.wav"
            self._write_wav(source_path, channels=1)
            engine = OpenALHrtfEngine.__new__(OpenALHrtfEngine)
            engine.available = True
            engine._al = FailingOpenALModule()
            engine._buffers = {}
            engine._buffer_paths = {}
            engine._sources = {}
            engine._channel_keys = {}
            engine._listener_gain = 1.0

            engine.register_sound("coin", str(source_path))

            self.assertNotIn("coin", engine._buffers)
            self.assertNotIn("coin", engine._buffer_paths)


class SpatialAudioTests(unittest.TestCase):
    def test_build_threat_cues_prefers_nearest_hazard_per_lane(self):
        engine = SpatialThreatAudio()
        obstacles = [
            Obstacle(kind="low", lane=-1, z=16.0),
            Obstacle(kind="train", lane=-1, z=9.0),
            Obstacle(kind="high", lane=1, z=7.5),
            Obstacle(kind="coin", lane=0, z=4.0),
        ]

        cues = engine.build_threat_cues(0, 20.0, obstacles)

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].kind, "train")
        self.assertEqual(cues[0].lane, -1)
        self.assertEqual(cues[1].kind, "high")
        self.assertEqual(cues[1].lane, 1)

    def test_close_current_lane_threat_generates_action_prompt(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="high", lane=0, z=5.0)

        cue = engine.build_threat_cues(0, 20.0, [obstacle])[0]

        self.assertEqual(cue.prompt, "roll now")
        self.assertLess(cue.interval, 0.5)
        self.assertGreater(cue.gain, 0.7)

    def test_prompt_is_announced_earlier_for_current_lane_train(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="train", lane=0, z=14.5)

        cue = engine.build_threat_cues(0, 20.0, [obstacle])[0]

        self.assertEqual(cue.prompt, "turn left now")

    def test_prompt_shortens_at_high_speed(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="high", lane=0, z=15.5)

        cue = engine.build_threat_cues(0, 33.9, [obstacle])[0]

        self.assertEqual(cue.prompt, "roll")

    def test_prompt_moves_earlier_as_speed_increases(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="high", lane=0, z=22.5)

        normal_speed_cue = engine.build_threat_cues(0, 20.0, [obstacle])[0]
        high_speed_cue = engine.build_threat_cues(0, 33.9, [obstacle])[0]

        self.assertIsNone(normal_speed_cue.prompt)
        self.assertEqual(high_speed_cue.prompt, "roll")

    def test_prompt_moves_even_earlier_at_top_speed_band(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="high", lane=0, z=23.5)

        medium_high_speed_cue = engine.build_threat_cues(0, 24.0, [obstacle])[0]
        top_speed_cue = engine.build_threat_cues(0, 33.9, [obstacle])[0]

        self.assertIsNone(medium_high_speed_cue.prompt)
        self.assertEqual(top_speed_cue.prompt, "roll")

    def test_center_lane_train_prefers_clearer_escape_side(self):
        engine = SpatialThreatAudio()
        obstacles = [
            Obstacle(kind="train", lane=0, z=12.0),
            Obstacle(kind="high", lane=-1, z=6.0),
            Obstacle(kind="low", lane=1, z=18.0),
        ]

        cue = next(cue for cue in engine.build_threat_cues(0, 20.0, obstacles) if cue.lane == 0)

        self.assertEqual(cue.prompt, "turn right now")

    def test_off_lane_threat_does_not_speak(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="low", lane=1, z=5.0)

        cue = engine.build_threat_cues(0, 20.0, [obstacle])[0]

        self.assertIsNone(cue.prompt)

    def test_update_emits_spatial_audio_coordinates(self):
        engine = SpatialThreatAudio()
        audio = DummyAudio({})
        speaker = DummySpeaker()
        obstacle = Obstacle(kind="train", lane=1, z=8.0)

        engine.update(0.1, 0, 20.0, [obstacle], audio, speaker)

        self.assertEqual(len(audio.spatial_played), 1)
        key, channel, x, _, z, gain, pitch, fallback_pan, _, _, velocity_z = audio.spatial_played[0]
        self.assertEqual(key, "train_pass")
        self.assertEqual(channel, "spatial_1")
        self.assertGreater(x, 0.0)
        self.assertLess(z, 0.0)
        self.assertGreater(gain, 0.0)
        self.assertGreater(pitch, 0.9)
        self.assertIsNotNone(fallback_pan)
        self.assertLess(velocity_z, 0.0)

    def test_critical_prompt_interrupts_current_screen_reader_speech(self):
        engine = SpatialThreatAudio()
        audio = DummyAudio({})
        speaker = DummySpeaker()
        obstacle = Obstacle(kind="high", lane=0, z=7.0)

        engine.update(0.1, 0, 20.0, [obstacle], audio, speaker)

        self.assertIn(("announcer_roll_now", "announcer_prompt", False), audio.played)
        self.assertEqual(speaker.messages, [])

    def test_train_prompt_uses_announcer_direction_clip(self):
        engine = SpatialThreatAudio()
        audio = DummyAudio({})
        speaker = DummySpeaker()
        obstacle = Obstacle(kind="train", lane=0, z=14.5)

        engine.update(0.1, 0, 20.0, [obstacle], audio, speaker)

        self.assertIn(("announcer_move_left_now", "announcer_prompt", False), audio.played)
        self.assertEqual(speaker.messages, [])

    def test_non_train_threat_does_not_emit_spatial_warning_sound(self):
        engine = SpatialThreatAudio()
        audio = DummyAudio({})
        speaker = DummySpeaker()
        obstacle = Obstacle(kind="low", lane=0, z=7.0)

        engine.update(0.1, 0, 20.0, [obstacle], audio, speaker)

        self.assertFalse(audio.spatial_played)
        self.assertIn(("announcer_jump_now", "announcer_prompt", False), audio.played)

    def test_update_repositions_active_spatial_sources_and_stops_inactive_ones(self):
        engine = SpatialThreatAudio()
        audio = DummyAudio({})
        speaker = DummySpeaker()
        obstacle = Obstacle(kind="train", lane=1, z=8.0)

        engine.update(0.1, 0, 20.0, [obstacle], audio, speaker)

        self.assertTrue(any(update[0] == "spatial_1" for update in audio.spatial_updated))
        self.assertIn("spatial_-1", audio.stopped)
        self.assertIn("spatial_0", audio.stopped)

    def test_train_cue_continues_behind_listener(self):
        engine = SpatialThreatAudio()
        obstacle = Obstacle(kind="train", lane=0, z=-3.0)

        cue = engine.build_threat_cues(0, 20.0, [obstacle])[0]

        self.assertGreater(cue.source_z, 0.0)
        self.assertGreater(cue.velocity_z, 0.0)
        self.assertIsNone(cue.prompt)

    def test_obstacle_height_changes_vertical_spatial_position(self):
        engine = SpatialThreatAudio()

        high_cue = engine.build_threat_cues(0, 20.0, [Obstacle(kind="high", lane=0, z=6.0)])[0]
        low_cue = engine.build_threat_cues(0, 20.0, [Obstacle(kind="low", lane=0, z=6.0)])[0]

        self.assertGreater(high_cue.source_y, 0.0)
        self.assertLess(low_cue.source_y, 0.0)


class SpawnDirectorTests(unittest.TestCase):
    def test_patterns_always_leave_a_safe_lane(self):
        for pattern in PATTERNS:
            self.assertTrue(pattern.safe_lanes)
            self.assertTrue(set(pattern.safe_lanes).issubset({-1, 0, 1}))
            blocked_by_step: dict[float, set[int]] = {}
            for entry in pattern.entries:
                if entry.kind not in {"train", "low", "high"}:
                    continue
                blocked_by_step.setdefault(entry.z_offset, set()).add(entry.lane)
            self.assertTrue(all(len(blocked_lanes) < 3 for blocked_lanes in blocked_by_step.values()))

    def test_support_lane_uses_last_safe_lane(self):
        director = SpawnDirector()

        with patch("subway_blind.spawn.random.choices", return_value=[PATTERNS[0]]), patch(
            "subway_blind.spawn.random.choice",
            side_effect=[1],
        ):
            director.choose_pattern(0.0)

        with patch("subway_blind.spawn.random.choice", return_value=-1), patch(
            "subway_blind.spawn.random.choices",
            return_value=[1],
        ):
            self.assertEqual(director.support_lane(0), 1)

    def test_support_lane_can_spawn_in_front_of_current_lane(self):
        director = SpawnDirector()
        director.last_safe_lane = 0

        with patch("subway_blind.spawn.random.choice", return_value=-1), patch(
            "subway_blind.spawn.random.choices",
            return_value=[1],
        ):
            self.assertEqual(director.support_lane(1), 1)

    def test_candidate_patterns_expand_single_lane_templates_across_all_lanes(self):
        director = SpawnDirector()

        candidates = director.candidate_patterns(0.0)
        single_train_variants = [pattern for pattern in candidates if pattern.name.startswith("single_train:")]

        self.assertEqual({pattern.entries[0].lane for pattern in single_train_variants}, {-1, 0, 1})

    def test_easy_difficulty_filters_out_harder_patterns_at_same_progress(self):
        director = SpawnDirector()

        easy_candidates = director.candidate_patterns(0.4, difficulty="easy")
        normal_candidates = director.candidate_patterns(0.4, difficulty="normal")

        easy_names = {pattern.name.split(":")[0] for pattern in easy_candidates}
        normal_names = {pattern.name.split(":")[0] for pattern in normal_candidates}

        self.assertNotIn("stagger_jump_route", easy_names)
        self.assertIn("stagger_jump_route", normal_names)

    def test_easy_difficulty_spaces_encounters_farther_than_hard(self):
        director = SpawnDirector()

        with patch("subway_blind.spawn.random.uniform", return_value=1.5):
            easy_gap = director.next_encounter_gap(0.5, difficulty="easy")
            hard_gap = director.next_encounter_gap(0.5, difficulty="hard")

        self.assertGreater(easy_gap, hard_gap)

    def test_transformed_pattern_updates_safe_lanes_with_lane_shift(self):
        shifted = SpawnDirector._transform_pattern(PATTERNS[0], 1, -1)

        self.assertIsNotNone(shifted)
        self.assertEqual(tuple(entry.lane for entry in shifted.entries), (-1,))
        self.assertEqual(shifted.safe_lanes, (0, 1))

    def test_support_reward_pool_contains_only_expected_types(self):
        director = SpawnDirector()

        for _ in range(100):
            self.assertIn(director.choose_support_kind(), {"power", "box", "key"})

    def test_pattern_is_rejected_when_it_closes_all_lanes_with_active_hazards(self):
        director = SpawnDirector()
        existing = [
            Obstacle(kind="train", lane=-1, z=32.2),
            Obstacle(kind="train", lane=1, z=32.4),
        ]

        playable = director.pattern_is_playable(PATTERNS[0], 32.0, existing, current_lane=0)

        self.assertFalse(playable)

    def test_pattern_is_rejected_when_open_lane_is_not_reachable_from_current_lane(self):
        director = SpawnDirector()
        pattern = RoutePattern(
            "right_wall",
            (PatternEntry("train", 1),),
            (-1,),
            0.0,
            1.0,
        )
        existing = [Obstacle(kind="train", lane=0, z=2.4)]

        playable = director.pattern_is_playable(pattern, 2.4, existing, current_lane=1)

        self.assertFalse(playable)

    def test_spawn_is_delayed_when_near_hazard_is_still_active(self):
        director = SpawnDirector()

        self.assertTrue(director.should_delay_spawn([Obstacle(kind="train", lane=0, z=11.0)]))
        self.assertFalse(director.should_delay_spawn([Obstacle(kind="train", lane=0, z=26.0)]))


class GameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        cls.screen = pygame.display.set_mode((320, 240))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def make_game(self, updater: DummyUpdater | None = None, packaged_build: bool = False):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        settings["speech_enabled"] = False
        speaker = DummySpeaker()
        speaker.apply_settings(settings)
        audio = DummyAudio(settings)
        with patch("subway_blind.game.Speaker.from_settings", return_value=speaker), patch(
            "subway_blind.game.Audio",
            return_value=audio,
        ):
            game = SubwayBlindGame(
                self.screen,
                pygame.time.Clock(),
                settings,
                updater=updater or DummyUpdater(),
                packaged_build=packaged_build,
            )
        speaker.messages.clear()
        speaker.speed_factors.clear()
        audio.played.clear()
        audio.play_calls.clear()
        audio.spatial_played.clear()
        audio.spatial_updated.clear()
        audio.stopped.clear()
        audio.refreshed = 0
        audio.music_started = 0
        audio.music_stopped = 0
        audio.music_started_tracks.clear()
        audio.music_update_calls.clear()
        audio.music_idle = False
        game._persist_settings = lambda: None
        game._sync_music_context()
        return game, speaker, audio

    def attach_controller(self, game: SubwayBlindGame, family: str = XBOX_FAMILY, name: str | None = None, instance_id: int = 41):
        controller_name = name or family_label(family)
        device = DummyControllerDevice(controller_name)
        game.controls.connected[instance_id] = ConnectedController(
            instance_id=instance_id,
            name=controller_name,
            family=family,
            controller=device,
        )
        game.controls.active_controller_instance_id = instance_id
        game._refresh_control_menus()
        return device

    def test_main_menu_is_english(self):
        game, _, _ = self.make_game()
        self.assertEqual(game.main_menu.title, f"Main Menu   Version: {APP_VERSION}")
        self.assertEqual(
            [item.label for item in game.main_menu.items],
            [
                "Start Game",
                "Events",
                "Missions",
                "Me",
                "Shop",
                "Leaderboard",
                "Report a Bug",
                "What's New",
                "Options",
                "How to Play",
                "Learn Game Sounds",
                "Check for Updates",
                "Exit",
            ],
        )

    def test_main_menu_open_announces_item_description_when_enabled(self):
        game, speaker, _ = self.make_game()

        game.main_menu.open()

        self.assertEqual(
            speaker.messages[-1][0],
            f"Main Menu   Version: {APP_VERSION}. Start Game. Set your loadout, then launch a new run when you are ready to hit the tracks.",
        )

    def test_leaderboard_requires_login_before_opening(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.main_menu

        result = game._handle_menu_action("leaderboard")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.main_menu)
        self.assertIn(("menuedge", "ui", False), audio.played)
        self.assertEqual(
            speaker.messages[-1][0],
            "Sign in from Options, Set User Name, before opening the leaderboard.",
        )

    def test_issue_reports_open_without_login_and_request_server_refresh(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu

        with patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            result = game._handle_menu_action("issue_reports")

        self.assertTrue(result)
        self.assertEqual(start_operation.call_args.args[0], "issue_connect")
        self.assertIs(start_operation.call_args.kwargs["return_menu"], game.main_menu)

    def test_issue_submission_requires_username_before_prompting(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.issue_menu

        result = game._handle_menu_action("issue_submit")

        self.assertTrue(result)
        self.assertIn(("menuedge", "ui", False), audio.played)
        self.assertEqual(
            speaker.messages[-1][0],
            "Sign in from Options, Set User Name, before submitting a bug report.",
        )

    def test_issue_submission_requests_auth_for_remembered_username(self):
        game, _, _ = self.make_game()
        game._leaderboard_username = "runner01"
        game.settings["leaderboard_username"] = "runner01"
        game.active_menu = game.issue_menu

        with patch(
            "subway_blind.game.prompt_for_credentials",
            return_value=CredentialPromptResult(username="runner01", password="secret"),
        ), patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            game._handle_menu_action("issue_submit")

        self.assertTrue(game._issue_submit_after_leaderboard_auth)
        self.assertEqual(start_operation.call_args.args[0], "leaderboard_auth")
        self.assertIs(start_operation.call_args.kwargs["return_menu"], game.issue_menu)

    def test_issue_submission_opens_compose_menu_for_authenticated_player(self):
        game, speaker, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game.active_menu = game.issue_menu

        result = game._handle_menu_action("issue_submit")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.issue_compose_menu)
        self.assertEqual(game.issue_compose_menu.items[0].label, "Title: Not set")
        self.assertEqual(speaker.messages[-1], ("Report a Bug   Compose. Title: Not set", True))

    def test_issue_compose_title_edit_updates_menu_without_popup_window(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.issue_compose_menu
        game._refresh_issue_compose_menu()

        with patch("subway_blind.game.prompt_for_inline_issue_text", return_value="Focus breaks on submit"), patch.object(
            game,
            "_reset_input_after_native_modal",
        ) as reset_input:
            result = game._handle_menu_action("issue_edit_title")

        self.assertTrue(result)
        self.assertEqual(game._issue_draft_title, "Focus breaks on submit")
        self.assertEqual(game.issue_compose_menu.items[0].label, "Title: Focus breaks on submit")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1], ("Title: Focus breaks on submit", True))
        reset_input.assert_called_once()

    def test_issue_compose_message_edit_updates_menu_and_preview(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.issue_compose_menu
        game._refresh_issue_compose_menu()

        with patch(
            "subway_blind.game.prompt_for_inline_issue_text",
            return_value="Open the bug menu.\nPress Enter.\nFocus stops.",
        ), patch.object(game, "_reset_input_after_native_modal") as reset_input:
            result = game._handle_menu_action("issue_edit_message")

        self.assertTrue(result)
        self.assertEqual(game._issue_draft_message, "Open the bug menu.\nPress Enter.\nFocus stops.")
        self.assertIn("3 lines", game.issue_compose_menu.items[1].label)
        self.assertEqual(game._issue_draft_preview_lines()[0], "Open the bug menu.")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][1], True)
        reset_input.assert_called_once()

    def test_issue_compose_cancel_resets_native_modal_input_state(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.issue_compose_menu
        game._refresh_issue_compose_menu()

        with patch(
            "subway_blind.game.prompt_for_inline_issue_text",
            side_effect=IssueDialogCancelled(),
        ), patch.object(game, "_reset_input_after_native_modal") as reset_input:
            result = game._handle_menu_action("issue_edit_message")

        self.assertTrue(result)
        self.assertIn(("menuclose", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1], ("Editing cancelled.", True))
        reset_input.assert_called_once()

    def test_reset_input_after_native_modal_clears_repeat_and_key_events(self):
        game, _, _ = self.make_game()
        game._menu_repeat_key = pygame.K_RETURN
        game._menu_repeat_delay_remaining = 0.2

        with patch("pygame.event.pump") as pump_events, patch("pygame.event.clear") as clear_events, patch(
            "pygame.key.set_mods"
        ) as set_mods:
            game._reset_input_after_native_modal()

        self.assertIsNone(game._menu_repeat_key)
        self.assertEqual(game._menu_repeat_delay_remaining, 0.0)
        pump_events.assert_called_once()
        set_mods.assert_called_once_with(0)
        clear_events.assert_any_call(pygame.KEYDOWN)
        clear_events.assert_any_call(pygame.KEYUP)
        clear_events.assert_any_call(pygame.ACTIVEEVENT)

    def test_prompt_for_leaderboard_credentials_resets_input_after_success(self):
        game, _, _ = self.make_game()

        with patch(
            "subway_blind.game.prompt_for_credentials",
            return_value=CredentialPromptResult(username="runner01", password="secret"),
        ), patch.object(game, "_reset_input_after_native_modal") as reset_input:
            credentials = game._prompt_for_leaderboard_credentials()

        self.assertEqual(credentials, ("runner01", "secret"))
        reset_input.assert_called_once()

    def test_prompt_for_leaderboard_credentials_resets_input_after_cancel(self):
        game, _, _ = self.make_game()

        with patch(
            "subway_blind.game.prompt_for_credentials",
            side_effect=CredentialPromptCancelled(),
        ), patch.object(game, "_reset_input_after_native_modal") as reset_input:
            credentials = game._prompt_for_leaderboard_credentials()

        self.assertIsNone(credentials)
        reset_input.assert_called_once()

    def test_issue_compose_submit_requires_title_and_message(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.issue_compose_menu
        game._refresh_issue_compose_menu()

        result = game._handle_menu_action("issue_submit_confirm")

        self.assertTrue(result)
        self.assertIn(("menuedge", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1], ("Issue title is required.", True))
        self.assertEqual(game.issue_compose_menu.index, 0)

    def test_issue_compose_submit_starts_server_operation(self):
        game, _, _ = self.make_game()
        game.active_menu = game.issue_compose_menu
        game._issue_draft_title = "Focus breaks on submit"
        game._issue_draft_message = "Open the bug menu.\nPress Enter.\nFocus stops."
        game._refresh_issue_compose_menu()

        with patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            result = game._handle_menu_action("issue_submit_confirm")

        self.assertTrue(result)
        self.assertEqual(start_operation.call_args.args[0], "issue_submit")
        self.assertIs(start_operation.call_args.kwargs["return_menu"], game.issue_compose_menu)

    def test_leaderboard_auth_success_continues_pending_issue_submission(self):
        game, _, _ = self.make_game()
        game._issue_submit_after_leaderboard_auth = True

        with patch.object(game, "_begin_issue_submission") as begin_issue_submission:
            game._handle_leaderboard_success(
                "leaderboard_auth",
                {
                    "just_connected": False,
                    "username": "runner01",
                    "status": "logged_in",
                    "account_sync": {},
                },
            )

        self.assertFalse(game._issue_submit_after_leaderboard_auth)
        begin_issue_submission.assert_called_once()

    def test_game_over_opens_publish_prompt_for_authenticated_player(self):
        game, speaker, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game.state.score = 120
        game.state.coins = 8

        game._open_game_over_dialog("Hit train")

        self.assertIs(game.active_menu, game.publish_confirm_menu)
        self.assertEqual(speaker.messages[-1], ("Game Over.", True))

    def test_game_over_opens_publish_prompt_for_remembered_leaderboard_username(self):
        game, speaker, _ = self.make_game()
        game._leaderboard_username = "runner01"
        game.settings["leaderboard_username"] = "runner01"
        game.state.score = 120
        game.state.coins = 8

        game._open_game_over_dialog("Hit train")

        self.assertIs(game.active_menu, game.publish_confirm_menu)
        self.assertEqual(speaker.messages[-1], ("Game Over.", True))

    def test_publish_prompt_delayed_announcement_includes_title(self):
        game, speaker, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game.state.score = 120
        game.state.coins = 8

        game._open_game_over_dialog("Hit train")
        game._update_pending_menu_announcement(0.5)

        self.assertEqual(speaker.messages[-1], ("Publish to Leaderboard?. Yes", True))

    def test_publish_latest_game_over_run_requests_auth_for_remembered_username(self):
        game, _, _ = self.make_game()
        game._leaderboard_username = "runner01"
        game.settings["leaderboard_username"] = "runner01"
        game.active_menu = game.publish_confirm_menu

        with patch(
            "subway_blind.game.prompt_for_credentials",
            return_value=CredentialPromptResult(username="runner01", password="secret"),
        ), patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            game._publish_latest_game_over_run()

        self.assertTrue(game._publish_after_leaderboard_auth)
        self.assertEqual(start_operation.call_args.args[0], "leaderboard_auth")
        self.assertIs(start_operation.call_args.kwargs["return_menu"], game.publish_confirm_menu)

    def test_leaderboard_auth_success_publishes_pending_game_over_run(self):
        game, _, _ = self.make_game()
        game._publish_after_leaderboard_auth = True

        with patch.object(game, "_publish_latest_game_over_run") as publish_latest_game_over_run:
            game._handle_leaderboard_success(
                "leaderboard_auth",
                {
                    "just_connected": False,
                    "username": "runner01",
                    "status": "existing",
                    "account_sync": {},
                },
            )

        self.assertFalse(game._publish_after_leaderboard_auth)
        publish_latest_game_over_run.assert_called_once()

    def test_options_menu_shows_logout_when_leaderboard_session_exists(self):
        game, _, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"

        game._refresh_options_menu_labels()

        labels = [item.label for item in game.options_menu.items]
        self.assertIn("Set User Name", labels[9])
        self.assertIn("Log Out", labels[10])
        self.assertEqual(game.options_menu.items[10].action, "opt_leaderboard_logout")

    def test_confirming_leaderboard_logout_clears_local_session(self):
        game, speaker, audio = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game._leaderboard_username = "runner01"
        game._refresh_options_menu_labels()
        game.active_menu = game.options_menu
        game.options_menu.index = game._update_option_index("opt_leaderboard_logout")

        result = game._handle_menu_action("opt_leaderboard_logout")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.leaderboard_logout_confirm_menu)
        self.assertEqual(game.leaderboard_logout_confirm_menu.index, 1)

        def fake_logout():
            game.leaderboard_client.auth_token = ""
            game.leaderboard_client.principal_username = ""

        with patch.object(game.leaderboard_client, "logout", side_effect=fake_logout):
            result = game._handle_menu_action("confirm_leaderboard_logout")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.options_menu)
        self.assertFalse(game.leaderboard_client.auth_token)
        self.assertEqual(game.settings["leaderboard_session_token"], "")
        self.assertEqual(game.settings["leaderboard_username"], "")
        self.assertEqual(game.options_menu.items[game._update_option_index("opt_leaderboard_account")].label, "Set User Name")
        self.assertEqual(speaker.messages[-1][0], "Leaderboard account signed out.")
        self.assertIn(("confirm", "ui", False), audio.played)

    def test_leaderboard_cached_results_open_immediately(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu
        game.leaderboard_client.auth_token = "token"
        game._leaderboard_entries = [
            {
                "rank": 1,
                "username": "runner01",
                "score": 900,
                "coins": 12,
                "play_time_seconds": 85,
            }
        ]
        game._leaderboard_total_players = 1
        game._leaderboard_cache_loaded_at = time.monotonic()

        with patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            game._open_leaderboard()

        self.assertIs(game.active_menu, game.leaderboard_menu)
        start_operation.assert_not_called()

    def test_leaderboard_uses_stale_cache_while_refreshing_in_background(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu
        game.leaderboard_client.auth_token = "token"
        game._leaderboard_entries = [
            {
                "rank": 1,
                "username": "runner01",
                "score": 900,
                "coins": 12,
                "play_time_seconds": 85,
            }
        ]
        game._leaderboard_total_players = 1
        game._leaderboard_cache_loaded_at = time.monotonic() - (LEADERBOARD_CACHE_TTL_SECONDS + 1.0)

        with patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            game._open_leaderboard()

        self.assertIs(game.active_menu, game.leaderboard_menu)
        start_operation.assert_called_once()
        self.assertEqual(start_operation.call_args.args[0], "leaderboard_refresh")
        self.assertFalse(start_operation.call_args.kwargs["show_status"])

    def test_leaderboard_menu_includes_filters_and_verification_labels(self):
        game, _, _ = self.make_game()
        game._leaderboard_period_filter = "season"
        game._leaderboard_difficulty_filter = "all"
        game._leaderboard_season = {
            "season_key": "2026-W14",
            "season_name": "Nightline Chase",
            "seconds_remaining": 93780,
            "reward_label": "Score Boosters",
            "reward_preview": "Rank 1 earns 5 Score Boosters. Rank 10 earns 1 Score Booster.",
        }
        game._leaderboard_entries = [
            {
                "rank": 1,
                "username": "runner01",
                "score": 900,
                "coins": 12,
                "play_time_seconds": 85,
                "difficulty": "hard",
                "verification_status": "suspicious",
            }
        ]
        game._leaderboard_total_players = 1

        game._refresh_leaderboard_menu()

        self.assertEqual(game.leaderboard_menu.items[0].label, "Season: Nightline Chase (2026-W14)")
        self.assertEqual(game.leaderboard_menu.items[1].label, "Season Ends In: 1 day 2 hours 3 minutes")
        self.assertIn("Score Boosters", game.leaderboard_menu.items[2].label)
        self.assertEqual(game.leaderboard_menu.items[3].label, "Difficulty: All Difficulties")
        self.assertIn("Suspicious", game.leaderboard_menu.items[4].label)
        self.assertIn("Hard", game.leaderboard_menu.items[4].label)

    def test_leaderboard_connect_does_not_speak_loaded_message(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.main_menu

        game._handle_leaderboard_success(
            "leaderboard_connect",
            {
                "just_connected": True,
                "period": "season",
                "difficulty": "all",
                "season": {
                    "season_key": "2026-W14",
                    "season_name": "Nightline Chase",
                    "seconds_remaining": 93780,
                    "reward_label": "Score Boosters",
                    "reward_preview": "Rank 1 earns 5 Score Boosters. Rank 10 earns 1 Score Booster.",
                },
                "entries": [],
                "total_players": 0,
            },
        )

        self.assertIs(game.active_menu, game.leaderboard_menu)
        self.assertFalse(any("leaderboard loaded" in text.lower() for text, _ in speaker.messages))

    def test_issue_connect_populates_issue_menu_and_plays_connect_sound(self):
        game, _, audio = self.make_game()
        game.active_menu = game.main_menu

        game._handle_leaderboard_success(
            "issue_connect",
            {
                "just_connected": True,
                "status": "investigating",
                "offset": 0,
                "total_reports": 1,
                "entries": [
                    {
                        "report_id": "a" * 32,
                        "reporter_username": "runner01",
                        "title": "Menu focus jumps unexpectedly",
                        "status": "investigating",
                        "created_at": "2026-04-01T12:34:56+00:00",
                    }
                ],
            },
        )

        self.assertIs(game.active_menu, game.issue_menu)
        self.assertIn(("connect", "ui", False), audio.played)
        self.assertEqual(game.issue_menu.items[0].label, "Report an Issue")
        self.assertEqual(
            game.issue_menu.items[2].label,
            "runner01: Menu focus jumps unexpectedly: Investigating: 2026-04-01 12:34:56",
        )

    def test_issue_submit_success_refreshes_menu_and_announces_remaining_count(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.issue_menu

        with patch.object(game, "_request_issue_refresh", return_value=True) as refresh_mock:
            game._handle_leaderboard_success(
                "issue_submit",
                {
                    "just_connected": True,
                    "report_id": "a" * 32,
                    "status": "investigating",
                    "submissions_remaining_today": 2,
                },
            )

        self.assertIs(game.active_menu, game.issue_menu)
        self.assertIn(("connect", "ui", False), audio.played)
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(
            speaker.messages[-1],
            ("Bug report submitted. Status: Investigating. 2 submissions remaining today.", True),
        )
        refresh_mock.assert_called_once()

    def test_issue_detail_menu_preserves_multiline_message_lines(self):
        game, _, _ = self.make_game()

        game._handle_leaderboard_success(
            "issue_detail",
            {
                "just_connected": False,
                "report_id": "a" * 32,
                "title": "Crash on startup",
                "status": "investigating",
                "created_at": "2026-04-01T12:34:56+00:00",
                "message": "Open the game.\nPress Enter.\nThe game closes.",
            },
        )

        self.assertIs(game.active_menu, game.issue_detail_menu)
        self.assertEqual(game.issue_detail_menu.items[0].label, "Title: Crash on startup")
        self.assertEqual(game.issue_detail_menu.items[3].label, "Message:")
        self.assertEqual(game.issue_detail_menu.items[4].label, "Open the game.")
        self.assertEqual(game.issue_detail_menu.items[5].label, "Press Enter.")
        self.assertEqual(game.issue_detail_menu.items[6].label, "The game closes.")

    def test_leaderboard_period_cycle_refreshes_without_status_screen(self):
        game, _, _ = self.make_game()
        game.active_menu = game.leaderboard_menu
        game._leaderboard_entries = [
            {
                "rank": 1,
                "username": "runner01",
                "score": 900,
                "coins": 12,
                "play_time_seconds": 85,
                "difficulty": "normal",
                "verification_status": "verified",
            }
        ]
        game._leaderboard_total_players = 1

        with patch.object(game, "_start_leaderboard_operation", return_value=True) as start_operation:
            game._cycle_leaderboard_period()

        self.assertIs(game.active_menu, game.leaderboard_menu)
        self.assertEqual(game._leaderboard_period_filter, "season")
        self.assertEqual(game.leaderboard_menu.items[0].label, "Season: Loading current week")
        self.assertEqual(start_operation.call_args.args[0], "leaderboard_refresh")
        self.assertFalse(start_operation.call_args.kwargs["show_status"])

    def test_build_leaderboard_submission_payload_includes_extended_run_details(self):
        game, _, _ = self.make_game()
        game._game_over_summary = {
            "score": 1450,
            "coins": 12,
            "play_time_seconds": 73,
            "death_reason": "Hit train",
            "game_version": APP_VERSION,
            "difficulty": "hard",
            "distance_meters": 1495,
            "clean_escapes": 6,
            "revives_used": 1,
            "powerup_usage": {"jetpack": 1, "hoverboard": 1},
        }

        payload = game._build_leaderboard_submission_payload()

        self.assertEqual(payload["difficulty"], "hard")
        self.assertEqual(payload["death_reason"], "Hit train")
        self.assertEqual(payload["distance_meters"], 1495)
        self.assertEqual(payload["clean_escapes"], 6)
        self.assertEqual(payload["revives_used"], 1)
        self.assertEqual(payload["powerup_usage"]["hoverboard"], 1)

    def test_leaderboard_run_detail_includes_extended_metadata(self):
        game, _, _ = self.make_game()
        game._leaderboard_selected_run = {
            "score": 1450,
            "coins": 12,
            "play_time_seconds": 73,
            "published_at": "2026-03-29T12:34:56+00:00",
            "difficulty": "hard",
            "distance_meters": 1495,
            "clean_escapes": 6,
            "revives_used": 1,
            "powerup_usage": {"jetpack": 1, "hoverboard": 1},
            "death_reason": "Hit train",
            "game_version": APP_VERSION,
            "verification_status": "suspicious",
            "verification_reasons": ["Distance exceeds the maximum travel range for the recorded play time."],
        }

        game._refresh_leaderboard_run_detail_menu()

        labels = [item.label for item in game.leaderboard_run_detail_menu.items]
        self.assertIn("Verification: Suspicious", labels)
        self.assertIn("Difficulty: Hard", labels)
        self.assertIn(f"Game Version: {APP_VERSION}", labels)
        self.assertTrue(any(label.startswith("Review Note: Distance exceeds") for label in labels))

    def test_main_menu_navigation_omits_item_description_when_disabled(self):
        game, speaker, _ = self.make_game()
        game.settings["main_menu_descriptions_enabled"] = False

        game.main_menu.open()
        game.main_menu.handle_key(pygame.K_DOWN)

        self.assertEqual(speaker.messages[0][0], f"Main Menu   Version: {APP_VERSION}. Start Game")
        self.assertEqual(speaker.messages[-1][0], "Events")

    def test_main_menu_exit_action_opens_desktop_confirmation(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu

        result = game._handle_menu_action("quit")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.exit_confirm_menu)
        self.assertEqual(game.exit_confirm_menu.title, "Return to Desktop?")
        self.assertEqual(game.exit_confirm_menu.index, 1)

    def test_main_menu_escape_opens_desktop_confirmation(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu

        result = game._handle_menu_action("close")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.exit_confirm_menu)
        self.assertEqual(game.exit_confirm_menu.index, 1)

    def test_exit_confirmation_no_returns_to_main_menu_exit_item(self):
        game, _, _ = self.make_game()
        game.active_menu = game.exit_confirm_menu

        result = game._handle_menu_action("cancel_exit")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(game.main_menu.index, 12)

    def test_exit_confirmation_yes_closes_game(self):
        game, _, _ = self.make_game()
        game.active_menu = game.exit_confirm_menu

        result = game._handle_menu_action("confirm_exit")

        self.assertFalse(result)

    def test_main_menu_exit_action_closes_immediately_when_confirmation_disabled(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu
        game.settings["confirm_exit_enabled"] = False

        result = game._handle_menu_action("quit")

        self.assertFalse(result)

    def test_main_menu_escape_closes_immediately_when_confirmation_disabled(self):
        game, _, _ = self.make_game()
        game.active_menu = game.main_menu
        game.settings["confirm_exit_enabled"] = False

        result = game._handle_menu_action("close")

        self.assertFalse(result)

    def test_options_menu_includes_output_device_entry(self):
        game, _, _ = self.make_game()
        labels = [item.label for item in game.options_menu.items]
        expected = [
            "SFX Volume: 90",
            "Music Volume: 60",
            "Check for Updates on Startup: On",
            "Output Device: System Default",
            "Menu Sound HRTF: On",
            "Speech: Off",
            "SAPI Settings",
            "Difficulty: Normal",
            "Main Menu Descriptions: On",
            "Set User Name",
            "Gameplay Announcements",
            "Controls",
            "Exit Confirmation: On",
            "Back",
        ]
        self.assertEqual(labels, expected)

    def test_gameplay_announcements_menu_lists_runtime_announcement_toggles(self):
        game, _, _ = self.make_game()
        labels = [item.label for item in game.announcements_menu.items]
        self.assertEqual(
            labels,
            ["Meters: Off", "Coin Counters: Off", "Quest Announcements: Off", "Pause on Focus Loss: On", "Back"],
        )

    def test_shop_menu_labels_include_coin_currency(self):
        game, _, _ = self.make_game()
        self.assertEqual(
            [item.label for item in game.shop_menu.items],
            [
                f"Buy Hoverboard   Cost: {SHOP_PRICES['hoverboard']} Coins   Owned: 3",
                f"Open Mystery Box   Cost: {SHOP_PRICES['mystery_box']} Coins",
                f"Buy Headstart   Cost: {SHOP_PRICES['headstart']} Coins   Owned: 2",
                f"Buy Score Booster   Cost: {SHOP_PRICES['score_booster']} Coins   Owned: 3",
                "Free Daily Gift   Available",
                "Item Upgrades   Maxed: 0/4",
                "Character Upgrades   Active: Jake",
                "Back",
            ],
        )

    def test_claim_daily_gift_updates_shop_and_events_labels(self):
        game, _, audio = self.make_game()
        game.active_menu = game.shop_menu

        result = game._handle_menu_action("claim_daily_gift")

        self.assertTrue(result)
        self.assertIn(("mystery_box_open", "ui", False), audio.played)
        self.assertEqual(game.shop_menu.items[4].label, "Free Daily Gift   Claimed Today")
        self.assertIn("Claimed Today", game.events_menu.items[6].label)

    def test_character_menu_lists_officially_added_characters(self):
        game, _, _ = self.make_game()

        game._refresh_character_menu_labels()

        labels = [item.label for item in game.character_menu.items[:-1]]
        self.assertEqual(
            [label.split("   ")[0] for label in labels],
            ["Jake", "Tricky", "Fresh", "Yutani", "Spike", "Dino", "Boombot"],
        )

    def test_achievements_menu_shows_progress_and_unlocks(self):
        game, speaker, _ = self.make_game()

        game.settings["achievement_progress"]["total_coins_collected"] = 1000
        game._announce_achievement_unlocks()
        game._refresh_achievements_menu_labels()

        self.assertIn("coin_collector", game.settings["achievements_unlocked"])
        self.assertEqual(game.achievements_menu.title, "Achievements   1/8")
        self.assertEqual(game.achievements_menu.items[0].label, "Coin Collector   Unlocked")
        self.assertTrue(any("Achievement unlocked: Coin Collector." == message for message, _ in speaker.messages))

    def test_commit_run_rewards_tracks_survivor_achievement(self):
        game, speaker, _ = self.make_game()
        game.state.running = True
        game.state.distance = 1500

        game._commit_run_rewards()

        self.assertIn("survivor", game.settings["achievements_unlocked"])
        self.assertTrue(any("Achievement unlocked: Survivor." == message for message, _ in speaker.messages))

    def test_how_to_play_opens_help_menu_instead_of_reading_one_long_message(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.main_menu

        result = game._handle_menu_action("howto")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.howto_menu)
        self.assertEqual(game.howto_menu.title, "How to Play")
        self.assertEqual(game.howto_menu.items[0].label, "Movement and Actions")
        self.assertNotIn(
            (
                "Controls: Left and right move lanes. Up jumps. Down rolls. Space uses a hoverboard.",
                True,
            ),
            speaker.messages,
        )

    def test_how_to_play_includes_new_meta_system_categories(self):
        game, _, _ = self.make_game()

        game._refresh_howto_menu_labels()

        labels = [item.label for item in game.howto_menu.items]
        self.assertIn("Events and Daily Rewards", labels)
        self.assertIn("Missions and Quests", labels)
        self.assertIn("Boards and Collections", labels)
        self.assertIn("Leaderboard and Publishing", labels)

    def test_whats_new_opens_line_by_line_dialog(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.main_menu

        result = game._handle_menu_action("whats_new")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.whats_new_menu)
        self.assertEqual(game.whats_new_menu.title, f"What's New   {APP_VERSION}")
        self.assertEqual(game.whats_new_menu.items[0].action, "copy_info_line")
        self.assertEqual(game.whats_new_menu.items[0].label, f"Version: {APP_VERSION}")
        self.assertEqual(game.whats_new_menu.items[-2].label, "Copy All")
        self.assertFalse(any("Update Summary" == message for message, _ in speaker.messages))

    def test_whats_new_lines_can_be_navigated_with_up_and_down(self):
        game, speaker, _ = self.make_game()
        game._handle_menu_action("whats_new")

        first_line = game.whats_new_menu.items[0].label
        second_line = game.whats_new_menu.items[1].label
        self.assertIn(first_line, speaker.messages[-1][0])

        game.whats_new_menu.handle_key(pygame.K_DOWN)

        self.assertEqual(game.whats_new_menu.index, 1)
        self.assertEqual(speaker.messages[-1][0], second_line)

    def test_escape_from_whats_new_returns_to_main_menu(self):
        game, _, _ = self.make_game()
        game._handle_menu_action("whats_new")

        result = game._handle_menu_action("close")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.main_menu)

    def test_how_to_play_topic_speaks_selected_help_item(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.howto_menu

        result = game._handle_menu_action("howto:movement")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.help_topic_menu)
        self.assertEqual(game.help_topic_menu.title, "Movement and Actions")
        self.assertEqual(game.help_topic_menu.items[0].action, "copy_info_line")
        self.assertTrue(game.help_topic_menu.items[0].label.startswith("Controls:"))
        self.assertEqual(game.help_topic_menu.items[-2].label, "Copy All")
        self.assertIn(game.help_topic_menu.items[0].label, speaker.messages[-1][0])

    def test_help_topic_back_returns_to_help_topic_list(self):
        game, _, _ = self.make_game()
        game.active_menu = game.howto_menu
        game._handle_menu_action("howto:warnings")

        result = game._handle_menu_action("back")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.howto_menu)

    def test_help_topic_lines_can_be_navigated_without_reading_full_topic(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.howto_menu
        game._handle_menu_action("howto:movement")

        self.assertGreater(len(game.help_topic_menu.items), 2)
        first_line = game.help_topic_menu.items[0].label
        second_line = game.help_topic_menu.items[1].label
        self.assertIn(first_line, speaker.messages[-1][0])

        game.help_topic_menu.handle_key(pygame.K_DOWN)

        self.assertEqual(game.help_topic_menu.index, 1)
        self.assertEqual(speaker.messages[-1][0], second_line)

    def test_escape_from_help_topic_returns_to_help_menu(self):
        game, _, _ = self.make_game()
        game.active_menu = game.howto_menu
        game._handle_menu_action("howto:warnings")

        result = game._handle_menu_action("close")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.howto_menu)

    def test_help_topic_segments_split_text_into_multiple_lines(self):
        segments = help_topic_segments(HOW_TO_TOPICS[0], "Use Left and Right.")

        self.assertGreater(len(segments), 1)

    def test_load_whats_new_content_uses_latest_changelog_entry(self):
        content = load_whats_new_content()

        self.assertEqual(content.title, f"What's New   {APP_VERSION}")
        self.assertIn("Update Summary", content.lines)
        self.assertNotIn("Press Enter to repeat the selected line.", content.lines)

    def test_help_topic_line_can_be_copied_to_clipboard(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.howto_menu
        game._handle_menu_action("howto:movement")

        with patch("subway_blind.game.copy_text_to_clipboard", return_value=True) as copy_mock:
            result = game._handle_menu_action("copy_info_line")

        self.assertTrue(result)
        copy_mock.assert_called_once_with(game.help_topic_menu.items[game.help_topic_menu.index].label)
        self.assertEqual(speaker.messages[-1], ("Selected line copied to clipboard.", True))

    def test_help_topic_copy_all_copies_title_and_lines(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.howto_menu
        game._handle_menu_action("howto:warnings")

        with patch("subway_blind.game.copy_text_to_clipboard", return_value=True) as copy_mock:
            result = game._handle_menu_action("copy_info_all")

        self.assertTrue(result)
        copied_text = copy_mock.call_args.args[0]
        self.assertTrue(copied_text.startswith("Hazards and Warnings\n\n"))
        self.assertIn("Listen for the announcer callouts and the train fly-by sound.", copied_text)
        self.assertEqual(speaker.messages[-1], ("Hazards and Warnings copied to clipboard.", True))

    def test_whats_new_copy_all_copies_title_and_lines(self):
        game, speaker, _ = self.make_game()
        game._handle_menu_action("whats_new")

        with patch("subway_blind.game.copy_text_to_clipboard", return_value=True) as copy_mock:
            result = game._handle_menu_action("copy_info_all")

        self.assertTrue(result)
        copied_text = copy_mock.call_args.args[0]
        self.assertTrue(copied_text.startswith(f"What's New   {APP_VERSION}\n\n"))
        self.assertIn(f"Version: {APP_VERSION}", copied_text)
        self.assertEqual(speaker.messages[-1], (f"What's New   {APP_VERSION} copied to clipboard.", True))

    def test_upgrade_version_marks_current_version_seen_without_auto_opening_help(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        settings["speech_enabled"] = False
        settings["last_seen_version"] = "1.1.1"
        with patch("subway_blind.game.Speaker.from_settings", return_value=DummySpeaker()), patch(
            "subway_blind.game.Audio",
            return_value=DummyAudio(settings),
        ):
            game = SubwayBlindGame(
                self.screen,
                pygame.time.Clock(),
                settings,
                updater=DummyUpdater(),
                packaged_build=False,
            )

        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(game.settings["last_seen_version"], APP_VERSION)

    def test_upgrade_help_does_not_reopen_when_version_already_seen(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        settings["speech_enabled"] = False
        settings["last_seen_version"] = APP_VERSION
        with patch("subway_blind.game.Speaker.from_settings", return_value=DummySpeaker()), patch(
            "subway_blind.game.Audio",
            return_value=DummyAudio(settings),
        ):
            game = SubwayBlindGame(
                self.screen,
                pygame.time.Clock(),
                settings,
                updater=DummyUpdater(),
                packaged_build=False,
            )

        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(game.settings["last_seen_version"], APP_VERSION)

    def test_game_starts_with_menu_music_request(self):
        game, _, audio = self.make_game()

        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(audio.music_started_tracks[-1], "menu")

    def test_startup_update_check_runs_when_setting_is_enabled(self):
        updater = DummyUpdater()
        with patch.object(SubwayBlindGame, "_show_startup_status", autospec=True) as startup_status:
            game, _, _ = self.make_game(updater=updater, packaged_build=True)

        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(updater.check_calls, 1)
        startup_status.assert_called_once_with(game, "Checking for updates.")

    def test_startup_update_check_opens_mandatory_update_menu_for_newer_release(self):
        updater = DummyUpdater()
        updater.check_results = [
            UpdateCheckResult(
                status="update_available",
                current_version=APP_VERSION,
                latest_version="0.2.0",
                release=make_release_info("0.2.0"),
                message="Version 0.2.0 is available.",
            )
        ]

        game, _, _ = self.make_game(updater=updater, packaged_build=True)

        self.assertIs(game.active_menu, game.update_menu)
        self.assertTrue(game.update_menu.title.startswith("Update Required"))

    def test_source_build_skips_startup_update_check(self):
        updater = DummyUpdater()
        with patch.object(SubwayBlindGame, "_show_startup_status", autospec=True) as startup_status:
            game, _, _ = self.make_game(updater=updater, packaged_build=False)

        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(updater.check_calls, 0)
        startup_status.assert_not_called()

    def test_manual_check_for_updates_opens_update_menu_when_update_exists(self):
        updater = DummyUpdater()
        updater.check_results = [
            UpdateCheckResult(
                status="no_releases",
                current_version=APP_VERSION,
                message="No published releases were found.",
            ),
            UpdateCheckResult(
                status="update_available",
                current_version=APP_VERSION,
                latest_version="0.2.0",
                release=make_release_info("0.2.0"),
                message="Version 0.2.0 is available.",
            ),
        ]
        game, _, _ = self.make_game(updater=updater, packaged_build=True)

        game._handle_menu_action("check_updates")

        self.assertIs(game.active_menu, game.update_menu)
        self.assertEqual(game._update_release_notes, "Important fixes.")

    def test_manual_check_for_updates_does_not_play_a_second_confirm_after_response(self):
        updater = DummyUpdater()
        updater.check_results = [
            UpdateCheckResult(
                status="no_releases",
                current_version=APP_VERSION,
                message="No published releases were found.",
            ),
            UpdateCheckResult(
                status="up_to_date",
                current_version=APP_VERSION,
                latest_version=APP_VERSION,
                release=make_release_info(APP_VERSION),
                message="You already have the latest version.",
            ),
        ]
        game, _, audio = self.make_game(updater=updater, packaged_build=True)
        game.active_menu = game.main_menu
        game.main_menu.index = 5

        game._handle_active_menu_key(pygame.K_RETURN)

        confirm_plays = [call for call in audio.played if call[0] == "confirm"]
        self.assertEqual(len(confirm_plays), 1)

    def test_mandatory_update_download_action_launches_update_and_requests_exit(self):
        updater = DummyUpdater()
        updater.check_results = [
            UpdateCheckResult(
                status="update_available",
                current_version=APP_VERSION,
                latest_version="0.2.0",
                release=make_release_info("0.2.0"),
                message="Version 0.2.0 is available.",
            )
        ]
        game, _, _ = self.make_game(updater=updater, packaged_build=True)

        keep_running = game._handle_menu_action("download_update")
        if game._update_install_thread is not None:
            game._update_install_thread.join(timeout=1.0)
        game._update_update_install_state()

        self.assertTrue(keep_running)
        self.assertEqual(len(updater.download_calls), 1)
        self.assertEqual(game.update_menu.items[0].action, "restart_after_update")

    def test_restart_after_update_uses_restart_script_and_requests_exit(self):
        updater = DummyUpdater()
        updater.check_results = [
            UpdateCheckResult(
                status="update_available",
                current_version=APP_VERSION,
                latest_version="0.2.0",
                release=make_release_info("0.2.0"),
                message="Version 0.2.0 is available.",
            )
        ]
        game, _, _ = self.make_game(updater=updater, packaged_build=True)
        if game._update_install_thread is not None:
            game._update_install_thread.join(timeout=1.0)
        game._update_install_result = updater.install_result
        game._update_restart_script_path = updater.install_result.restart_script_path
        game.update_menu.items[0].action = "restart_after_update"

        keep_running = game._handle_menu_action("restart_after_update")

        self.assertFalse(keep_running)
        self.assertEqual(updater.launch_restart_calls[-1], updater.install_result.restart_script_path)

    def test_source_build_manual_update_check_opens_non_mandatory_update_menu(self):
        updater = DummyUpdater()
        updater.check_results = [
            UpdateCheckResult(
                status="update_available",
                current_version=APP_VERSION,
                latest_version="0.2.0",
                release=make_release_info("0.2.0"),
                message="Version 0.2.0 is available.",
            )
        ]

        game, _, _ = self.make_game(updater=updater, packaged_build=False)

        game._handle_menu_action("check_updates")

        self.assertIs(game.active_menu, game.update_menu)
        self.assertEqual(game.update_menu.title, f"Update Available   {APP_VERSION} -> 0.2.0")
        self.assertEqual(game.update_menu.items[0].action, "open_release_page")
        self.assertEqual(game.update_menu.items[2].action, "back")

    def test_start_run_uses_profile_base_speed(self):
        game, _, audio = self.make_game()
        game.settings["difficulty"] = "hard"

        game.start_run()

        self.assertEqual(game.state.speed, SPEED_PROFILES["hard"].base_speed)
        self.assertEqual(audio.music_started_tracks[-1], "gameplay")

    def test_start_run_includes_permanent_mission_multiplier_bonus(self):
        game, _, _ = self.make_game()
        game.settings["mission_multiplier_bonus"] = 4

        with patch(
            "subway_blind.game.event_runtime_profile",
            return_value={
                "event": None,
                "featured_character_key": "",
                "featured_character_active": False,
                "featured_multiplier_bonus": 0,
                "super_box_bonus": 0.0,
                "word_bonus": 0.0,
                "box_bonus": 0.0,
                "jackpot_bonus": False,
            },
        ):
            game.start_run()

        self.assertEqual(game.state.multiplier, 5)

    def test_start_run_with_headstart_plays_intro_headstart_sounds(self):
        game, _, audio = self.make_game()
        game.settings["headstarts"] = 2
        game.selected_headstarts = 1

        game.start_run()

        self.assertIn(("intro_shake", HEADSTART_SHAKE_CHANNEL, True), audio.played)
        self.assertIn(("intro_spray", HEADSTART_SPRAY_CHANNEL, True), audio.played)
        self.assertGreater(game.player.headstart, 0.0)

    def test_start_run_without_headstart_does_not_play_headstart_intro_layers(self):
        game, _, audio = self.make_game()

        game.start_run()

        self.assertNotIn(("intro_shake", "intro_chase", False), audio.played)
        self.assertNotIn(("intro_spray", "intro_spray_once", False), audio.played)
        self.assertNotIn(("intro_shake", HEADSTART_SHAKE_CHANNEL, True), audio.played)
        self.assertNotIn(("intro_spray", HEADSTART_SPRAY_CHANNEL, True), audio.played)
        self.assertEqual(game.player.headstart, 0.0)

    def test_headstart_audio_stops_when_effect_expires(self):
        game, _, audio = self.make_game()
        game.settings["headstarts"] = 1
        game.selected_headstarts = 1

        game.start_run()
        game._update_game(headstart_duration_for_uses(1) + 0.1)

        self.assertIn(HEADSTART_SHAKE_CHANNEL, audio.stopped)
        self.assertIn(HEADSTART_SPRAY_CHANNEL, audio.stopped)
        self.assertEqual(game.player.headstart, 0.0)

    def test_start_action_opens_run_setup_menu(self):
        game, _, _ = self.make_game()

        game._handle_menu_action("start")

        self.assertIs(game.active_menu, game.loadout_menu)
        self.assertEqual(game.loadout_menu.title, "Run Setup")

    def test_learn_sounds_action_opens_sound_menu(self):
        game, _, _ = self.make_game()

        game._handle_menu_action("learn_sounds")

        self.assertIs(game.active_menu, game.learn_sounds_menu)
        self.assertEqual(game.learn_sounds_menu.title, "Learn Game Sounds")

    def test_enter_on_learn_sound_plays_preview_and_speaks_description(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.learn_sounds_menu
        game.learn_sounds_menu.index = 0
        game._refresh_learn_sound_description()

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIn(("coin", LEARN_SOUND_PREVIEW_CHANNEL, False), audio.played)
        self.assertTrue(speaker.messages[-1][0].startswith("Coin Pickup."))
        self.assertEqual(game._learn_sound_description, "Plays when you collect a coin on the track.")

    def test_learn_sound_loop_preview_stops_after_timeout(self):
        game, _, audio = self.make_game()
        game.active_menu = game.learn_sounds_menu
        game.learn_sounds_menu.index = next(
            index for index, item in enumerate(game.learn_sounds_menu.items) if item.action == "learn_sound:guard_loop"
        )

        game._handle_active_menu_key(pygame.K_RETURN)
        game._update_learn_sound_preview(LEARN_SOUND_LOOP_PREVIEW_DURATION + 0.1)

        self.assertIn(( "guard_loop", LEARN_SOUND_PREVIEW_CHANNEL, True), audio.played)
        self.assertIn(LEARN_SOUND_PREVIEW_CHANNEL, audio.stopped)

    def test_learn_sounds_back_stops_preview_and_returns_to_main_menu(self):
        game, _, audio = self.make_game()
        game._set_active_menu(game.learn_sounds_menu)
        game.learn_sounds_menu.index = next(
            index for index, item in enumerate(game.learn_sounds_menu.items) if item.action == "learn_sound:magnet_loop"
        )

        game._handle_active_menu_key(pygame.K_RETURN)
        result = game._handle_active_menu_key(pygame.K_ESCAPE)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.main_menu)
        self.assertIn(LEARN_SOUND_PREVIEW_CHANNEL, audio.stopped)

    def test_learn_sounds_menu_contains_only_active_gameplay_sound_entries(self):
        game, _, _ = self.make_game()

        actions = [item.action for item in game.learn_sounds_menu.items]

        self.assertEqual(actions[:-1], [f"learn_sound:{key}" for key in ACTIVE_GAMEPLAY_SOUND_KEYS])
        self.assertEqual(actions[-1], "back")
        self.assertNotIn("learn_sound:menuopen", actions)
        self.assertIn("learn_sound:announcer_jump_now", actions)
        self.assertIn("learn_sound:announcer_move_left_now", actions)

    def test_enter_on_announcer_learn_sound_plays_announcer_preview(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.learn_sounds_menu
        game.learn_sounds_menu.index = next(
            index for index, item in enumerate(game.learn_sounds_menu.items) if item.action == "learn_sound:announcer_move_right_now"
        )
        game._refresh_learn_sound_description()

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIn(("announcer_move_right_now", LEARN_SOUND_PREVIEW_CHANNEL, False), audio.played)
        self.assertTrue(speaker.messages[-1][0].startswith("Announcer Move Right Now."))

    def test_headstart_adds_speed_bonus_and_consumes_inventory(self):
        game, _, _ = self.make_game()
        game.selected_headstarts = 1
        starting_inventory = game.settings["headstarts"]

        game.start_run()
        game._update_game(0.5)

        self.assertEqual(game.settings["headstarts"], starting_inventory - 1)
        self.assertGreaterEqual(game.state.speed, SPEED_PROFILES["normal"].base_speed + HEADSTART_SPEED_BONUS)

    def test_end_run_banks_coins_and_plays_bank_sounds(self):
        game, _, audio = self.make_game()
        game.start_run()
        game.state.coins = 37
        game.settings["bank_coins"] = 12

        game.end_run(to_menu=True)

        self.assertEqual(game.settings["bank_coins"], 49)
        self.assertIn(("coin_gui", "ui", False), audio.played)
        self.assertIn(("gui_cash", "ui2", False), audio.played)
        self.assertEqual(audio.music_started_tracks[-1], "menu")

    def test_multiple_headstarts_extend_start_duration_and_consume_all_selected_charges(self):
        game, _, _ = self.make_game()
        game.settings["headstarts"] = 3
        game.selected_headstarts = 3

        game.start_run()

        self.assertEqual(game.settings["headstarts"], 0)
        self.assertEqual(game.player.headstart, headstart_duration_for_uses(3))

    def test_update_game_caps_speed_after_profile_limit(self):
        game, _, _ = self.make_game()
        game.start_run()
        game.state.time = 179.95

        game._update_game(1.0)

        self.assertAlmostEqual(game.state.speed, SPEED_PROFILES["normal"].max_speed)

    def test_update_game_updates_speaker_speed_factor(self):
        game, speaker, _ = self.make_game()
        game.start_run()
        game.state.time = 179.0

        game._update_game(1.0)

        self.assertTrue(speaker.speed_factors)
        self.assertGreater(speaker.speed_factors[-1], 0.95)

    def test_spawn_things_creates_pattern_coinline_and_support_in_safe_route(self):
        game, _, _ = self.make_game()
        game.start_run()
        game.state.next_spawn = 0.0
        game.state.next_coinline = 0.0
        game.state.next_support = 0.0

        with patch.object(game, "_choose_playable_pattern", return_value=(PATTERNS[4], 32.0)), patch.object(
            game.spawn_director,
            "base_spawn_distance",
            side_effect=[29.0, 34.0],
        ), patch.object(game.spawn_director, "choose_coin_lane", return_value=1), patch.object(
            game,
            "_choose_support_spawn_kind",
            return_value="key",
        ), patch.object(game.spawn_director, "support_lane", return_value=1):
            game._spawn_things(0.016)

        hazards = [obstacle for obstacle in game.obstacles if obstacle.kind in {"train", "low", "high"}]
        coins = [obstacle for obstacle in game.obstacles if obstacle.kind == "coin"]
        keys = [obstacle for obstacle in game.obstacles if obstacle.kind == "key"]

        self.assertEqual(len(hazards), 2)
        self.assertEqual({obstacle.lane for obstacle in hazards}, {-1, 1})
        self.assertEqual(len(coins), 6)
        self.assertTrue(all(obstacle.lane == 1 for obstacle in coins))
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0].lane, 1)

    def test_update_game_clamps_invalid_player_lane_back_onto_track(self):
        game, _, _ = self.make_game()
        game.player.lane = 4

        game._update_game(0.016)

        self.assertEqual(game.player.lane, 1)

    def test_spawn_things_delays_when_existing_hazard_is_too_close(self):
        game, _, _ = self.make_game()
        game.start_run()
        game.state.next_spawn = 0.0
        game.obstacles.append(Obstacle(kind="train", lane=0, z=10.0))

        game._spawn_things(0.016)

        self.assertAlmostEqual(game.state.next_spawn, 0.3)

    def test_adjust_selected_option_changes_sfx_with_right_arrow(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 0
        game.settings["sfx_volume"] = 0.4

        game._adjust_selected_option(1)

        self.assertEqual(game.settings["sfx_volume"], 0.41)
        self.assertEqual(game.options_menu.items[0].label, "SFX Volume: 41")
        self.assertEqual(audio.refreshed, 1)
        self.assertEqual(speaker.messages[-1][0], "SFX Volume: 41")
        self.assertIsNotNone(audio.play_calls[-1]["pan"])

    def test_adjust_selected_option_changes_music_with_left_arrow(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 1
        game.settings["music_volume"] = 0.6

        game._adjust_selected_option(-1)

        self.assertEqual(game.settings["music_volume"], 0.59)
        self.assertEqual(game.options_menu.items[1].label, "Music Volume: 59")
        self.assertEqual(audio.refreshed, 1)
        self.assertEqual(speaker.messages[-1][0], "Music Volume: 59")

    def test_adjust_selected_option_toggles_startup_update_checks(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 2
        game.settings["check_updates_on_startup"] = True

        game._adjust_selected_option(-1)

        self.assertFalse(game.settings["check_updates_on_startup"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Check for Updates on Startup: Off")

    def test_adjust_selected_option_cycles_output_device_in_place(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 3

        game._adjust_selected_option(1)

        self.assertEqual(game.settings["audio_output_device"], "External USB Headphones")
        self.assertEqual(game.options_menu.items[3].label, "Output Device: External USB Headphones")
        self.assertEqual(speaker.messages[-1][0], "Output device set to External USB Headphones.")

    def test_enter_does_nothing_in_options_menu(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 3

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.options_menu)
        self.assertEqual(game.settings["audio_output_device"], "")
        self.assertEqual(audio.played, [])
        self.assertEqual(speaker.messages, [])

    def test_adjust_selected_option_on_back_only_plays_edge_feedback(self):
        game, _, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 13

        game._adjust_selected_option(1)

        self.assertEqual(audio.played, [])
        self.assertIs(game.active_menu, game.options_menu)

    def test_enter_on_back_returns_to_main_menu_from_options(self):
        game, _, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 13

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(game.main_menu.index, 0)
        self.assertIn(("menuclose", "ui", False), audio.played)

    def test_controls_menu_defaults_to_keyboard_without_controller(self):
        game, _, _ = self.make_game()

        game._refresh_control_menus()

        self.assertEqual(
            [item.label for item in game.controls_menu.items],
            [
                "Active Input: Keyboard",
                "Binding Profile: Keyboard",
                "Customize Bindings",
                "Reset Keyboard",
                "Back",
            ],
        )

    def test_controls_menu_defaults_to_connected_controller_profile(self):
        game, _, _ = self.make_game()
        self.attach_controller(game, family=PLAYSTATION_FAMILY, name="Wireless Controller")
        game._selected_binding_device = "controller"

        game._refresh_control_menus()

        self.assertEqual(
            [item.label for item in game.controls_menu.items],
            [
                "Active Input: Keyboard",
                "Binding Profile: PlayStation Controller",
                "Customize Bindings",
                "Reset PlayStation Controller",
                "Back",
            ],
        )

    def test_options_controls_entry_opens_controls_menu(self):
        game, _, _ = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 11

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.controls_menu)
        self.assertEqual(game.controls_menu.items[1].label, "Binding Profile: Keyboard")

    def test_options_controls_entry_prefers_controller_profile_when_connected(self):
        game, _, _ = self.make_game()
        self.attach_controller(game, family=PLAYSTATION_FAMILY, name="Wireless Controller")
        game.active_menu = game.options_menu
        game.options_menu.index = 11

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.controls_menu)
        self.assertEqual(game.controls_menu.items[1].label, "Binding Profile: PlayStation Controller")

    def test_options_gameplay_announcements_entry_opens_submenu(self):
        game, _, _ = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 10

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.announcements_menu)
        self.assertEqual(game.announcements_menu.items[0].label, "Meters: Off")

    def test_options_logout_entry_opens_confirmation_on_enter(self):
        game, _, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game._leaderboard_username = "runner01"
        game._refresh_options_menu_labels()
        game.active_menu = game.options_menu
        game.options_menu.index = game._update_option_index("opt_leaderboard_logout")

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.leaderboard_logout_confirm_menu)
        self.assertEqual(game.leaderboard_logout_confirm_menu.index, 1)

    def test_gameplay_announcements_back_returns_to_options_entry(self):
        game, _, _ = self.make_game()
        game.active_menu = game.announcements_menu
        game.announcements_menu.index = game._update_announcements_index("back")

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.options_menu)
        self.assertEqual(game.options_menu.index, 10)

    def test_controls_menu_can_switch_binding_profile_like_options(self):
        game, speaker, _ = self.make_game()
        self.attach_controller(game, family=PLAYSTATION_FAMILY, name="Wireless Controller")
        game.active_menu = game.controls_menu
        game.controls_menu.index = 1
        game._selected_binding_device = "keyboard"
        game._build_controls_menu()

        game._handle_active_menu_key(pygame.K_RIGHT)

        self.assertEqual(game.controls_menu.items[1].label, "Binding Profile: PlayStation Controller")
        self.assertEqual(speaker.messages[-1][0], "Binding Profile: PlayStation Controller")

    def test_controls_menu_customize_uses_selected_controller_profile(self):
        game, _, _ = self.make_game()
        self.attach_controller(game, family=PLAYSTATION_FAMILY, name="Wireless Controller")
        game.active_menu = game.controls_menu
        game._selected_binding_device = "controller"
        game._build_controls_menu()
        game.controls_menu.index = 2

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.controller_bindings_menu)

    def test_keyboard_binding_capture_updates_menu_confirm(self):
        game, speaker, _ = self.make_game()
        game._build_keyboard_bindings_menu()
        game.active_menu = game.keyboard_bindings_menu

        game._begin_binding_capture("keyboard", "menu_confirm")
        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_f}))

        self.assertEqual(game.controls.keyboard_binding_for_action("menu_confirm"), pygame.K_f)
        self.assertIn(("Confirm set to F.", True), speaker.messages)

    def test_remapped_menu_up_uses_new_key_only(self):
        game, _, _ = self.make_game()
        game.controls.update_keyboard_binding("menu_up", pygame.K_j)
        game.active_menu = game.main_menu
        game.main_menu.index = 1

        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_UP}))
        self.assertEqual(game.main_menu.index, 1)

        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_j}))
        self.assertEqual(game.main_menu.index, 0)

    def test_remapped_menu_confirm_disables_enter(self):
        game, _, audio = self.make_game()
        game.controls.update_keyboard_binding("menu_confirm", pygame.K_f)
        game.active_menu = game.main_menu
        game.main_menu.index = 0

        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN}))
        self.assertIs(game.active_menu, game.main_menu)
        self.assertNotIn(("confirm", "ui", False), audio.played)

        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_f}))
        self.assertIs(game.active_menu, game.loadout_menu)

    def test_remapped_option_adjustment_disables_old_arrow(self):
        game, _, _ = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 0
        game.settings["sfx_volume"] = 0.4
        game.controls.update_keyboard_binding("option_increase", pygame.K_l)

        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RIGHT}))
        self.assertEqual(game.settings["sfx_volume"], 0.4)

        game._handle_keyboard_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_l}))
        self.assertEqual(game.settings["sfx_volume"], 0.41)

    def test_controller_binding_capture_updates_playstation_jump_label(self):
        game, speaker, _ = self.make_game()
        self.attach_controller(game, family=PLAYSTATION_FAMILY, name="Wireless Controller")
        game._build_controller_bindings_menu()
        game.active_menu = game.controller_bindings_menu

        game._begin_binding_capture("controller", "game_jump")
        game._handle_controller_event(
            pygame.event.Event(
                pygame.CONTROLLERBUTTONDOWN,
                {"instance_id": 41, "button": pygame.CONTROLLER_BUTTON_X},
            )
        )

        self.assertEqual(game.controls.controller_binding_for_action("game_jump", PLAYSTATION_FAMILY), "button:x")
        self.assertIn(("Jump set to Square.", True), speaker.messages)

    def test_controller_a_button_triggers_jump_in_gameplay(self):
        game, _, _ = self.make_game()
        self.attach_controller(game, family=XBOX_FAMILY, name="Xbox Wireless Controller")
        game.start_run()

        game._handle_controller_event(
            pygame.event.Event(
                pygame.CONTROLLERBUTTONDOWN,
                {"instance_id": 41, "button": pygame.CONTROLLER_BUTTON_A},
            )
        )

        self.assertGreater(game.player.vy, 0.0)

    def test_controller_left_stick_moves_player_left(self):
        game, _, _ = self.make_game()
        self.attach_controller(game, family=XBOX_FAMILY, name="Xbox Wireless Controller")
        game.start_run()

        game._handle_controller_event(
            pygame.event.Event(
                pygame.CONTROLLERAXISMOTION,
                {"instance_id": 41, "axis": pygame.CONTROLLER_AXIS_LEFTX, "value": -0.95},
            )
        )

        self.assertEqual(game.player.lane, -1)

    def test_menu_hint_uses_playstation_labels_after_controller_input(self):
        game, _, _ = self.make_game()
        self.attach_controller(game, family=PLAYSTATION_FAMILY, name="Wireless Controller")
        game.controls.last_input_source = "controller"

        hint_text = game._menu_navigation_hint()

        self.assertEqual(hint_text, "Use D-Pad Up/D-Pad Down, Cross to select, Circle to go back.")

    def test_adjust_selected_option_toggles_menu_sound_hrtf(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 4
        game.settings["menu_sound_hrtf"] = True

        game._adjust_selected_option(-1)

        self.assertFalse(game.settings["menu_sound_hrtf"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Menu Sound HRTF: Off")

    def test_adjust_selected_option_toggles_main_menu_descriptions_from_options(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 8

        game._adjust_selected_option(-1)

        self.assertFalse(game.settings["main_menu_descriptions_enabled"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Main Menu Descriptions: Off")

    def test_adjust_selected_option_toggles_exit_confirmation_from_options(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 12

        game._adjust_selected_option(-1)

        self.assertFalse(game.settings["confirm_exit_enabled"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Exit Confirmation: Off")

    def test_adjust_selected_option_sets_speech_state_from_direction(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 5
        game.settings["speech_enabled"] = True
        game.speaker.enabled = True

        game._adjust_selected_option(-1)

        self.assertFalse(game.settings["speech_enabled"])
        self.assertFalse(game.speaker.enabled)
        self.assertEqual(speaker.messages[-1][0], "Speech: Off")

    def test_adjust_selected_option_toggles_sapi_speech(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.sapi_menu
        game.sapi_menu.index = 0
        game.settings["speech_enabled"] = True
        game.settings["sapi_speech_enabled"] = False

        game._adjust_selected_option(1)

        self.assertTrue(game.settings["sapi_speech_enabled"])
        self.assertTrue(speaker.use_sapi)
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "SAPI Speech: On")

    def test_options_sapi_entry_opens_sapi_submenu(self):
        game, _, _ = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 6

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.sapi_menu)
        self.assertEqual(game.sapi_menu.title, "SAPI Settings")

    def test_sapi_submenu_back_returns_to_options(self):
        game, _, _ = self.make_game()
        game.active_menu = game.sapi_menu
        game.sapi_menu.index = 5

        result = game._handle_active_menu_key(pygame.K_RETURN)

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.options_menu)
        self.assertEqual(game.options_menu.index, 6)

    def test_adjust_selected_option_changes_sapi_volume(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.sapi_menu
        game.sapi_menu.index = 1
        game.settings["sapi_volume"] = 100

        game._adjust_selected_option(-1)

        self.assertEqual(game.settings["sapi_volume"], 99)
        self.assertEqual(speaker.sapi_volume, 99)
        self.assertEqual(game.sapi_menu.items[1].label, "SAPI Volume: 99")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(game.options_menu.items[6].label, "SAPI Settings")
        self.assertEqual(speaker.messages[-1][0], "SAPI Volume: 99")

    def test_adjust_selected_option_cycles_sapi_voice(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.sapi_menu
        game.sapi_menu.index = 2

        game._adjust_selected_option(1)

        self.assertEqual(game.settings["sapi_voice_id"], "voice-david")
        self.assertEqual(game.sapi_menu.items[2].label, "SAPI Voice: Microsoft David Desktop - English (United States)")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "SAPI Voice: Microsoft David Desktop - English (United States)")

    def test_adjust_selected_option_changes_sapi_rate(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.sapi_menu
        game.sapi_menu.index = 3
        game.settings["sapi_rate"] = 0

        game._adjust_selected_option(1)

        self.assertEqual(game.settings["sapi_rate"], 1)
        self.assertEqual(speaker.sapi_rate, 1)
        self.assertEqual(game.sapi_menu.items[3].label, "SAPI Rate: 1")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "SAPI Rate: 1")

    def test_adjust_selected_option_changes_sapi_pitch(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.sapi_menu
        game.sapi_menu.index = 4
        game.settings["sapi_pitch"] = 0

        game._adjust_selected_option(-1)

        self.assertEqual(game.settings["sapi_pitch"], -1)
        self.assertEqual(speaker.sapi_pitch, -1)
        self.assertEqual(game.sapi_menu.items[4].label, "SAPI Pitch: -1")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "SAPI Pitch: -1")

    def test_adjust_selected_option_cycles_difficulty_backward(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 7
        game.settings["difficulty"] = "normal"

        game._adjust_selected_option(-1)

        self.assertEqual(game.settings["difficulty"], "easy")
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Difficulty: Easy")

    def test_adjust_selected_option_toggles_meters(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.announcements_menu
        game.announcements_menu.index = 0

        game._adjust_selected_option(1)

        self.assertTrue(game.settings["meter_announcements_enabled"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Meters: On")

    def test_adjust_selected_option_toggles_coin_counters(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.announcements_menu
        game.announcements_menu.index = 1

        game._adjust_selected_option(1)

        self.assertTrue(game.settings["coin_counters_enabled"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Coin Counters: On")

    def test_adjust_selected_option_toggles_quest_changes(self):
        game, speaker, audio = self.make_game()
        game.active_menu = game.announcements_menu
        game.announcements_menu.index = 2

        game._adjust_selected_option(1)

        self.assertTrue(game.settings["quest_changes_enabled"])
        self.assertIn(("confirm", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Quest Announcements: On")

    def test_menu_repeat_moves_quickly_after_hold_delay(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.main_menu
        game.main_menu.index = 0

        game._prime_menu_repeat(pygame.K_DOWN)
        game._update_menu_repeat(MENU_REPEAT_INITIAL_DELAY + (MENU_REPEAT_INTERVAL * 2.1))

        self.assertEqual(game.main_menu.index, 3)
        self.assertEqual(
            speaker.messages[-1][0],
            "Me. Manage your active runner, hoverboard, upgrades, and collection bonuses.",
        )

    def test_menu_repeat_adjusts_option_values_while_holding_horizontal_arrow(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.options_menu
        game.options_menu.index = 0
        game.settings["sfx_volume"] = 0.4

        game._prime_menu_repeat(pygame.K_RIGHT)
        game._update_menu_repeat(MENU_REPEAT_INITIAL_DELAY + MENU_REPEAT_INTERVAL)

        self.assertEqual(game.settings["sfx_volume"], 0.42)
        self.assertEqual(game.options_menu.items[0].label, "SFX Volume: 42")
        self.assertEqual(speaker.messages[-1][0], "SFX Volume: 42")

    def test_pause_menu_close_resumes_run(self):
        game, speaker, audio = self.make_game()
        game.state.paused = True
        game.active_menu = game.pause_menu

        game._handle_menu_action("close")

        self.assertFalse(game.state.paused)
        self.assertIsNone(game.active_menu)
        self.assertIn(("menuclose", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "Resume")

    def test_pause_menu_return_to_main_requests_confirmation(self):
        game, _, _ = self.make_game()
        game.state.paused = True
        game.active_menu = game.pause_menu

        game._handle_menu_action("to_main")

        self.assertIs(game.active_menu, game.pause_confirm_menu)
        self.assertEqual(game.pause_confirm_menu.title, "Return to Main Menu?")

    def test_pause_confirmation_no_returns_to_pause_menu(self):
        game, _, _ = self.make_game()
        game.state.paused = True
        game.active_menu = game.pause_confirm_menu

        game._handle_menu_action("cancel_to_main")

        self.assertIs(game.active_menu, game.pause_menu)
        self.assertEqual(game.pause_menu.index, 1)

    def test_pause_confirmation_yes_returns_to_main_menu(self):
        game, _, audio = self.make_game()
        game.state.running = True
        game.state.paused = True
        game.active_menu = game.pause_confirm_menu

        game._handle_menu_action("confirm_to_main")

        self.assertIs(game.active_menu, game.main_menu)
        self.assertEqual(audio.music_started_tracks[-1], "menu")

    def test_pause_confirmation_yes_opens_publish_prompt_when_run_has_progress(self):
        game, speaker, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game.state.running = True
        game.state.paused = True
        game.state.score = 120
        game.state.coins = 8
        game.state.time = 42
        game.active_menu = game.pause_confirm_menu

        game._handle_menu_action("confirm_to_main")
        game._update_pending_menu_announcement(0.5)

        self.assertIs(game.active_menu, game.publish_confirm_menu)
        self.assertEqual(game._game_over_summary["score"], 120)
        self.assertEqual(game._game_over_summary["coins"], 8)
        self.assertEqual(speaker.messages[-1], ("Publish to Leaderboard?. Yes", True))

    def test_publish_prompt_no_from_pause_return_goes_to_main_menu(self):
        game, _, _ = self.make_game()
        game._publish_confirm_return_menu = game.main_menu
        game._publish_confirm_return_index = 0
        game.active_menu = game.publish_confirm_menu

        game._handle_menu_action("publish_confirm_no")

        self.assertIs(game.active_menu, game.main_menu)

    def test_publish_success_after_pause_return_goes_to_main_menu(self):
        game, _, _ = self.make_game()
        game._publish_confirm_return_menu = game.main_menu
        game._publish_confirm_return_index = 0

        game._handle_leaderboard_success(
            "leaderboard_publish",
            {
                "just_connected": False,
                "username": "runner01",
                "high_score": False,
            },
        )

        self.assertIs(game.active_menu, game.main_menu)

    def test_publish_success_with_personal_best_plays_high_score_feedback(self):
        game, speaker, audio = self.make_game()
        game._publish_confirm_return_menu = game.game_over_menu
        game._publish_confirm_return_index = 0

        game._handle_leaderboard_success(
            "leaderboard_publish",
            {
                "just_connected": True,
                "username": "runner01",
                "high_score": True,
                "board_rank": 7,
                "verification_status": "verified",
            },
        )

        self.assertIn(("connect", "ui", False), audio.played)
        self.assertIn(("high", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1], ("New personal best. Leaderboard rank 7.", True))

    def test_shop_purchase_spends_bank_coins_and_grants_hoverboard(self):
        game, speaker, _ = self.make_game()
        game.settings["bank_coins"] = SHOP_PRICES["hoverboard"]
        game.settings["hoverboards"] = 0
        game.active_menu = game.shop_menu

        game._purchase_shop_item("hoverboard")

        self.assertEqual(game.settings["bank_coins"], 0)
        self.assertEqual(game.settings["hoverboards"], 1)
        self.assertIn(("Hoverboard purchased.", True), speaker.messages)

    def test_shop_mystery_box_can_grant_multiple_hoverboards(self):
        game, speaker, _ = self.make_game()
        game.settings["hoverboards"] = 0

        with patch("subway_blind.game.shop_box_reward_amount", return_value=3):
            game._grant_shop_box_reward("hover")

        self.assertEqual(game.settings["hoverboards"], 3)
        self.assertIn(("Mystery box: 3 hoverboards.", False), speaker.messages)

    def test_unlock_character_spends_bank_coins_and_marks_character_unlocked(self):
        game, speaker, _ = self.make_game()
        game.settings["bank_coins"] = 2200

        game._unlock_character("tricky")

        self.assertEqual(game.settings["bank_coins"], 0)
        self.assertTrue(game.settings["character_progress"]["tricky"]["unlocked"])
        self.assertIn(("Tricky unlocked.", True), speaker.messages)

    def test_select_character_sets_active_character(self):
        game, speaker, _ = self.make_game()
        game.settings["character_progress"]["tricky"]["unlocked"] = True
        game._sync_character_progress()

        game._select_character("tricky")

        self.assertEqual(game.settings["selected_character"], "tricky")
        self.assertEqual(game.shop_menu.items[6].label, "Character Upgrades   Active: Tricky")
        self.assertIn(("Tricky selected.", True), speaker.messages)

    def test_select_board_updates_active_board_and_loadout_label(self):
        game, speaker, _ = self.make_game()
        game.settings["board_progress"]["bouncer"]["unlocked"] = True
        game._sync_character_progress()

        game._select_board("bouncer")

        self.assertEqual(game.settings["selected_board"], "bouncer")
        self.assertEqual(game.loadout_menu.items[0].label, "Board: Bouncer   Power: Double Jump")
        self.assertIn(("Bouncer selected.", True), speaker.messages)

    def test_upgrade_character_increases_level_and_updates_perk_summary(self):
        game, speaker, _ = self.make_game()
        game.settings["character_progress"]["fresh"]["unlocked"] = True
        game.settings["bank_coins"] = 1100
        game._sync_character_progress()

        game._upgrade_character("fresh")

        self.assertEqual(game.settings["character_progress"]["fresh"]["level"], 1)
        self.assertIn(("Fresh upgraded to level 1. Power duration +8%.", True), speaker.messages)

    def test_open_item_upgrades_menu_from_shop(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.shop_menu

        result = game._handle_menu_action("open_item_upgrades")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.item_upgrade_menu)
        self.assertEqual(game.item_upgrade_menu.title, "Item Upgrades   Maxed: 0/4")
        self.assertEqual(game.item_upgrade_menu.items[0].label, "Coin Magnet   Level 0/5   9s")
        self.assertIn((game._shop_coins_label(), False), speaker.messages)

    def test_purchase_item_upgrade_spends_bank_coins_and_increases_level(self):
        game, speaker, _ = self.make_game()
        upgrade_cost = next_item_upgrade_cost(game.settings, "magnet")
        game.settings["bank_coins"] = int(upgrade_cost or 0)
        game._refresh_item_upgrade_detail_menu_labels("magnet")

        game._purchase_item_upgrade("magnet")

        self.assertEqual(game.settings["bank_coins"], 0)
        self.assertEqual(game.settings["item_upgrades"]["magnet"], 1)
        self.assertIn(("Coin Magnet upgraded to level 1. Pickup duration 10s.", True), speaker.messages)
        self.assertEqual(game.shop_menu.items[5].label, "Item Upgrades   Maxed: 0/4")

    def test_purchase_item_upgrade_persists_after_reload(self):
        original_base_dir = config_module.BASE_DIR
        with tempfile.TemporaryDirectory() as temp_directory:
            config_module.BASE_DIR = Path(temp_directory)
            game, _, _ = self.make_game()
            game._persist_settings = lambda: config_module.save_settings(game.settings)
            upgrade_cost = next_item_upgrade_cost(game.settings, "magnet")
            game.settings["bank_coins"] = int(upgrade_cost or 0)

            game._purchase_item_upgrade("magnet")

            loaded = config_module.load_settings()
        config_module.BASE_DIR = original_base_dir

        self.assertEqual(loaded["bank_coins"], 0)
        self.assertEqual(loaded["item_upgrades"]["magnet"], 1)

    def test_persist_settings_writes_leaderboard_identity_without_recursion(self):
        game, _, _ = self.make_game()
        game._persist_settings = SubwayBlindGame._persist_settings.__get__(game, SubwayBlindGame)
        game.leaderboard_client.principal_username = "runner01"
        game.leaderboard_client.auth_token = "session-token-123"

        with patch("subway_blind.game.config_module.save_settings") as save_settings_mock:
            game._persist_settings()

        save_settings_mock.assert_called_once()
        saved_settings = save_settings_mock.call_args.args[0]
        self.assertEqual(saved_settings["leaderboard_username"], "runner01")
        self.assertEqual(saved_settings["leaderboard_session_token"], "session-token-123")

    def test_item_upgrade_max_level_blocks_purchase(self):
        game, speaker, _ = self.make_game()
        game.settings["item_upgrades"]["jetpack"] = 5

        game._purchase_item_upgrade("jetpack")

        self.assertIn(("Jetpack is already at max level.", True), speaker.messages)

    def test_item_upgrade_back_returns_to_shop_entry(self):
        game, _, _ = self.make_game()
        game.active_menu = game.item_upgrade_menu

        result = game._handle_menu_action("back")

        self.assertTrue(result)
        self.assertIs(game.active_menu, game.shop_menu)
        self.assertEqual(game.shop_menu.index, 5)

    def test_item_upgrade_extends_magnet_power_duration(self):
        game, _, _ = self.make_game()
        game.settings["item_upgrades"]["magnet"] = 3

        game._apply_power_reward("magnet", from_headstart=False)

        self.assertAlmostEqual(game.player.magnet, item_upgrade_duration(game.settings, "magnet"))

    def test_jake_bonus_banks_extra_run_coins(self):
        game, speaker, _ = self.make_game()
        game.settings["selected_character"] = "jake"
        game.settings["character_progress"]["jake"]["level"] = 2
        game._sync_character_progress()
        game.state.running = True
        game.state.coins = 100

        game._commit_run_rewards()

        self.assertEqual(game.settings["bank_coins"], 112)
        self.assertIn(("Jake bonus saved 12 extra coins.", False), speaker.messages)

    def test_tricky_bonus_extends_hoverboard_duration(self):
        game, _, _ = self.make_game()
        game.settings["selected_character"] = "tricky"
        game.settings["character_progress"]["tricky"] = {"unlocked": True, "level": 2}
        game._sync_character_progress()
        game.player.hoverboards = 1

        game._try_hoverboard()

        self.assertEqual(game.player.hover_active, HOVERBOARD_DURATION + 4.0)

    def test_fresh_bonus_extends_powerup_duration(self):
        game, _, _ = self.make_game()
        game.settings["selected_character"] = "fresh"
        game.settings["character_progress"]["fresh"] = {"unlocked": True, "level": 3}
        game._sync_character_progress()

        game._apply_power_reward("jetpack", from_headstart=False)

        self.assertAlmostEqual(game.player.jetpack, 6.5 * 1.24)

    def test_yutani_bonus_increases_starting_multiplier(self):
        game, _, _ = self.make_game()
        game.settings["selected_character"] = "yutani"
        game.settings["character_progress"]["yutani"] = {"unlocked": True, "level": 2}
        game._sync_character_progress()

        with patch(
            "subway_blind.game.event_runtime_profile",
            return_value={
                "event": None,
                "featured_character_key": "",
                "featured_character_active": False,
                "featured_multiplier_bonus": 0,
                "super_box_bonus": 0.0,
                "word_bonus": 0.0,
                "box_bonus": 0.0,
                "jackpot_bonus": False,
            },
        ):
            game.start_run()

        self.assertEqual(game.state.multiplier, 3)

    def test_boombot_bonus_extends_powerup_duration_more_than_fresh_level_one(self):
        game, _, _ = self.make_game()
        game.settings["selected_character"] = "boombot"
        game.settings["character_progress"]["boombot"] = {"unlocked": True, "level": 1}
        game._sync_character_progress()

        game._apply_power_reward("magnet", from_headstart=False)

        self.assertAlmostEqual(game.player.magnet, 9.0 * 1.1)

    def test_hoverboard_absorbs_hit(self):
        game, speaker, _ = self.make_game()
        game.player.hover_active = 5.0

        game._on_hit()

        self.assertEqual(game.player.hover_active, 0.0)
        self.assertEqual(game.player.stumbles, 0)
        self.assertEqual(speaker.messages[-1][0], "Hoverboard destroyed.")
        self.assertIn(("crash", "act", False), game.audio.played)

    def test_hoverboard_uses_original_duration_and_pauses_during_jetpack(self):
        game, _, _ = self.make_game()
        game.player.hoverboards = 1

        game._try_hoverboard()
        self.assertEqual(game.player.hover_active, HOVERBOARD_DURATION)

        game.player.jetpack = 4.0
        game._tick_powerups(1.0)

        self.assertEqual(game.player.hover_active, HOVERBOARD_DURATION)

    def test_hoverboard_limit_blocks_fifth_use_in_one_run(self):
        game, speaker, audio = self.make_game()
        game.player.hoverboards = HOVERBOARD_MAX_USES_PER_RUN + 1

        for _ in range(HOVERBOARD_MAX_USES_PER_RUN):
            game.player.hover_active = 0.0
            game._try_hoverboard()

        remaining_inventory = game.player.hoverboards
        game.player.hover_active = 0.0
        game._try_hoverboard()

        self.assertEqual(game.state.hoverboards_used, HOVERBOARD_MAX_USES_PER_RUN)
        self.assertEqual(game.player.hoverboards, remaining_inventory)
        self.assertEqual(game.player.hover_active, 0.0)
        self.assertIn(("menuedge", "ui", False), audio.played)
        self.assertEqual(
            speaker.messages[-1][0],
            f"Hoverboard limit reached. You can use {HOVERBOARD_MAX_USES_PER_RUN} per run.",
        )

    def test_bush_hit_uses_bush_stumble_sound(self):
        game, speaker, audio = self.make_game()

        game._on_hit("bush")

        self.assertIn(("stumble_bush", "act", False), audio.played)
        self.assertNotIn(("crash", "act2", False), audio.played)
        self.assertEqual(speaker.messages[-1][0], "You crashed. One chance left.")

    def test_train_hit_uses_train_stumble_sound_without_generic_crash_layer(self):
        game, _, audio = self.make_game()

        game._on_hit("train")

        self.assertIn(("stumble_side", "act", False), audio.played)
        self.assertNotIn(("crash", "act2", False), audio.played)

    def test_low_and_high_hits_use_standard_stumble_sound(self):
        for variant in ("low", "high"):
            game, _, audio = self.make_game()

            game._on_hit(variant)

            self.assertIn(("stumble", "act", False), audio.played)
            self.assertNotIn(("crash", "act2", False), audio.played)

    def test_first_stumble_starts_guard_loop_for_recovery_window(self):
        game, _, audio = self.make_game()
        game.state.running = True
        game._on_hit()

        game._tick_powerups(0.1)

        self.assertIn(("guard_loop", "loop_guard", True), audio.played)

    def test_guard_loop_stops_after_recovery_window_ends(self):
        game, _, audio = self.make_game()
        game.state.running = True
        game._on_hit()

        game._tick_powerups(1.5)

        self.assertIn("loop_guard", audio.stopped)

    def test_near_miss_triggers_swish_sound(self):
        game, _, audio = self.make_game()
        game.player.lane = 0
        game.player.y = 1.2
        game.obstacles = [Obstacle(kind="low", lane=0, z=1.0)]

        game._update_near_miss_audio()

        self.assertIn(("swish_mid", "near_0", False), audio.played)

    def test_second_hit_opens_game_over_dialog(self):
        game, speaker, audio = self.make_game()
        game.player.stumbles = 1
        game.state.score = 120
        game.state.coins = 8
        game.state.running = True
        game.settings["keys"] = 0
        game.active_menu = None

        game._on_hit()

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertEqual(audio.music_stopped, 0)
        self.assertEqual(audio.music_started_tracks[-1], "menu")
        self.assertEqual(game.settings["bank_coins"], 8)
        self.assertEqual(
            [item.label for item in game.game_over_menu.items],
            [
                "Score: 120",
                "Coins: 8",
                "Play Time: 00:00",
                "Death reason: Hit train",
                "Run again",
                "Main menu",
            ],
        )
        self.assertIn(("Run over. Score 120. Hit train.", True), speaker.messages)
        self.assertEqual(game.game_over_menu.index, 0)
        self.assertEqual(speaker.messages[-1], ("Game Over.", True))

    def test_second_hit_opens_revive_menu_when_keys_exist(self):
        game, speaker, _ = self.make_game()
        game.player.stumbles = 1
        game.settings["keys"] = 2
        game.active_menu = None

        game._on_hit()

        self.assertIs(game.active_menu, game.revive_menu)
        self.assertIn(("You can revive for 1 key.", True), speaker.messages)

    def test_second_hit_skips_revive_after_three_revives_used(self):
        game, speaker, _ = self.make_game()
        game.player.stumbles = 1
        game.state.revives_used = REVIVE_MAX_USES_PER_RUN
        game.settings["keys"] = 99
        game.state.score = 40
        game.state.coins = 3
        game.state.running = True

        game._on_hit()

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertIn(("Run over. Score 40. Hit train.", True), speaker.messages)

    def test_bush_death_reason_is_recorded_in_game_over_dialog(self):
        game, _, _ = self.make_game()
        game.player.stumbles = 1
        game.state.score = 40
        game.state.coins = 3
        game.state.running = True
        game.settings["keys"] = 0

        game._on_hit("bush")

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertEqual(game.game_over_menu.items[3].label, "Death reason: Hit bush")

    def test_revive_consumes_key_and_restores_run(self):
        game, _, _ = self.make_game()
        game.settings["keys"] = 2
        game.state.revives_used = 0
        game.active_menu = game.revive_menu
        game.state.paused = True
        game.player.stumbles = 2

        game._revive_run()

        self.assertEqual(game.settings["keys"], 1)
        self.assertEqual(game.state.revives_used, 1)
        self.assertFalse(game.state.paused)
        self.assertIsNone(game.active_menu)
        self.assertEqual(game.player.stumbles, 0)
        self.assertGreater(game.player.hover_active, 0)

    def test_revive_run_ends_run_when_revive_limit_is_reached(self):
        game, speaker, audio = self.make_game()
        game.settings["keys"] = 99
        game.state.revives_used = REVIVE_MAX_USES_PER_RUN
        game.active_menu = game.revive_menu
        game.state.paused = True
        game.state.score = 55
        game.state.coins = 4
        game.state.running = True
        game.player.stumbles = 2

        game._revive_run()

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertIn(("menuedge", "ui", False), audio.played)
        self.assertTrue(
            any(
                text == f"Revive limit reached. Only {REVIVE_MAX_USES_PER_RUN} revives work in one run."
                for text, _ in speaker.messages
            )
        )
        self.assertEqual(speaker.messages[-1][0], "Game Over.")

    def test_mystery_box_can_grant_new_inventory_rewards(self):
        game, _, _ = self.make_game()
        original_keys = game.settings["keys"]
        game._active_event_profile["jackpot_bonus"] = False

        with patch("subway_blind.game.pick_mystery_box_reward", return_value="key"):
            game._collect_box()

        self.assertEqual(game.settings["keys"], original_keys + 1)

    def test_collect_multiplier_pickup_uses_existing_powerup_audio(self):
        game, speaker, audio = self.make_game()

        game._collect_multiplier_pickup()

        self.assertGreater(game.player.mult2x, 0.0)
        self.assertIn(("powerup", "act", False), audio.played)
        self.assertIn(("2x multiplier.", False), speaker.messages)

    def test_collect_power_starts_magnet_loop_when_reward_is_magnet(self):
        game, speaker, audio = self.make_game()

        game._apply_power_reward("magnet", from_headstart=False)

        self.assertGreater(game.player.magnet, 0.0)
        self.assertIn(("magnet_loop", "loop_magnet", True), audio.played)
        self.assertIn(("Magnet.", False), speaker.messages)

    def test_collect_power_starts_jetpack_loop_when_reward_is_jetpack(self):
        game, speaker, audio = self.make_game()

        game._apply_power_reward("jetpack", from_headstart=False)

        self.assertGreater(game.player.jetpack, 0.0)
        self.assertEqual(game.player.y, 2.0)
        self.assertIn(("jetpack_loop", "loop_jetpack", True), audio.played)
        self.assertIn(("Jetpack.", False), speaker.messages)

    def test_collect_super_mysterizer_uses_existing_mystery_audio(self):
        game, speaker, audio = self.make_game()
        original_keys = game.settings["keys"]

        with patch("subway_blind.game.pick_super_mystery_box_reward", return_value="keys"), patch(
            "subway_blind.game.random.randint",
            return_value=2,
        ):
            game._collect_super_mysterizer()

        self.assertEqual(game.settings["keys"], original_keys + 2)
        self.assertIn(("mystery_box_open", "ui", False), audio.played)
        self.assertIn(("mystery_combo", "ui2", False), audio.played)
        self.assertTrue(any("Super Mysterizer" in message for message, _ in speaker.messages))

    def test_collect_pogo_stick_launches_player_with_existing_sounds(self):
        game, speaker, audio = self.make_game()

        game._collect_pogo_stick()

        self.assertGreater(game.player.pogo_active, 0.0)
        self.assertGreater(game.player.vy, 0.0)
        self.assertIn(("powerup", "act", False), audio.played)
        self.assertIn(("sneakers_jump", "act", False), audio.played)
        self.assertIn(("Pogo stick.", False), speaker.messages)

    def test_pogo_bounce_avoids_high_obstacle_collision(self):
        game, _, _ = self.make_game()
        game.player.pogo_active = 2.0
        game.player.y = 1.2
        game.obstacles = [Obstacle(kind="high", lane=0, z=1.0)]

        game._handle_obstacles()

        self.assertEqual(game.player.stumbles, 0)

    def test_mystery_box_announces_opening_before_reward(self):
        game, speaker, _ = self.make_game()
        game._active_event_profile["jackpot_bonus"] = False

        with patch("subway_blind.game.pick_mystery_box_reward", return_value="key"):
            game._collect_box()

        self.assertEqual(speaker.messages[0], ("Opening Mystery Box.", True))
        self.assertEqual(speaker.messages[1], ("Mystery box: key.", False))

    def test_collect_word_letter_completes_word_hunt_and_awards_bank_coins(self):
        game, speaker, _ = self.make_game()
        word = game._current_word()
        game.settings["word_hunt_day"] = date.today().isoformat()
        game.settings["word_hunt_letters"] = word[:-1]
        game.settings["word_hunt_completed_on"] = ""
        game.settings["word_hunt_streak"] = 0

        game._collect_word_letter(Obstacle(kind="word", lane=0, z=1.0, label=word[-1]))

        self.assertEqual(game.settings["bank_coins"], 300)
        self.assertTrue(any("Word Hunt complete." in message for message, _ in speaker.messages))

    def test_collect_word_letter_ignores_unexpected_letter(self):
        game, speaker, audio = self.make_game()
        word = game._current_word()
        game.settings["word_hunt_day"] = date.today().isoformat()
        game.settings["word_hunt_letters"] = word[:1]

        game._collect_word_letter(Obstacle(kind="word", lane=0, z=1.0, label="Z"))

        self.assertEqual(game.settings["word_hunt_letters"], word[:1])
        self.assertEqual(speaker.messages, [])
        self.assertEqual(audio.played, [])

    def test_collect_season_token_claims_reward(self):
        game, speaker, _ = self.make_game()
        game.settings["season_tokens"] = 4
        game.settings["season_reward_stage"] = 0

        game._collect_season_token()

        self.assertEqual(game.settings["season_reward_stage"], 1)
        self.assertEqual(game.settings["bank_coins"], 500)
        self.assertTrue(any("Season Hunt reward." in message for message, _ in speaker.messages))

    def test_record_mission_event_completes_set_and_increases_multiplier(self):
        game, speaker, _ = self.make_game()
        game.settings["quest_changes_enabled"] = True
        goals = game._mission_goals()
        for goal in goals[:-1]:
            game.settings["mission_metrics"][goal.metric] = goal.target
        final_goal = goals[-1]
        game.settings["mission_metrics"][final_goal.metric] = final_goal.target - 1
        game.state.running = True
        game.state.multiplier = 1

        game._record_mission_event(final_goal.metric)

        self.assertEqual(game.settings["mission_set"], 2)
        self.assertEqual(game.settings["mission_multiplier_bonus"], 1)
        self.assertEqual(game.state.multiplier, 2)
        self.assertTrue(any("Mission set complete." in message for message, _ in speaker.messages))

    def test_super_mystery_box_can_grant_jetpack_reward(self):
        game, speaker, _ = self.make_game()
        game.state.running = True

        with patch("subway_blind.game.pick_super_mystery_box_reward", return_value="jetpack"):
            game._open_super_mystery_box("Mission Set")

        self.assertGreater(game.player.jetpack, 0.0)
        self.assertIn(("Mission Set: Super Mystery Box. Jetpack.", True), speaker.messages)

    def test_tick_powerups_starts_loop_for_active_jetpack(self):
        game, _, audio = self.make_game()
        game.player.jetpack = 6.5

        game._tick_powerups(0.016)

        self.assertIn(("jetpack_loop", "loop_jetpack", True), audio.played)

    def test_lane_names_are_english(self):
        self.assertEqual(lane_name(-1), "Left lane")
        self.assertEqual(lane_name(0), "Center lane")
        self.assertEqual(lane_name(1), "Right lane")

    def test_coin_announcement_hotkey_works_during_headstart(self):
        game, speaker, _ = self.make_game()
        game.settings["coin_counters_enabled"] = True
        game.state.coins = 17
        game.player.headstart = 3.0

        game._handle_game_key(pygame.K_r)

        self.assertIn(("Coins collected: 17.", False), speaker.messages)

    def test_coin_announcement_hotkey_works_through_keyboard_translation(self):
        game, speaker, _ = self.make_game()
        game.settings["coin_counters_enabled"] = True
        game.state.coins = 23
        game.active_menu = None

        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r)
        game._handle_keyboard_event(event)

        self.assertIn(("Coins collected: 23.", False), speaker.messages)

    def test_play_time_hotkey_announces_elapsed_run_time(self):
        game, speaker, _ = self.make_game()
        game.state.time = 65.0

        game._handle_game_key(pygame.K_t)

        self.assertIn(("Play time: 01:05.", False), speaker.messages)

    def test_play_time_hotkey_works_through_keyboard_translation(self):
        game, speaker, _ = self.make_game()
        game.state.time = 3661.0
        game.active_menu = None

        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t)
        game._handle_keyboard_event(event)

        self.assertIn(("Play time: 01:01:01.", False), speaker.messages)

    def test_tracking_toggles_default_to_disabled(self):
        game, _, _ = self.make_game()

        self.assertFalse(game.settings["meter_announcements_enabled"])
        self.assertFalse(game.settings["coin_counters_enabled"])
        self.assertFalse(game.settings["quest_changes_enabled"])
        self.assertTrue(game.settings["pause_on_focus_loss_enabled"])

    def test_focus_loss_pauses_running_game_when_enabled(self):
        game, speaker, audio = self.make_game()
        game.state.running = True
        game.active_menu = None

        game._handle_window_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))

        self.assertTrue(game.state.paused)
        self.assertIs(game.active_menu, game.pause_menu)
        self.assertIn(("menuclose", "ui", False), audio.played)
        self.assertEqual(speaker.messages[-1], ("Paused. Resume", True))

    def test_focus_loss_does_not_pause_when_setting_disabled(self):
        game, _, audio = self.make_game()
        game.state.running = True
        game.active_menu = None
        game.settings["pause_on_focus_loss_enabled"] = False

        game._handle_window_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))

        self.assertFalse(game.state.paused)
        self.assertIsNone(game.active_menu)
        self.assertNotIn(("menuclose", "ui", False), audio.played)

    def test_focus_loss_toggle_updates_from_gameplay_announcements_menu(self):
        game, speaker, _ = self.make_game()
        game.active_menu = game.announcements_menu
        game.announcements_menu.index = game._update_announcements_index("opt_pause_on_focus_loss")

        game._adjust_selected_option(-1)

        self.assertFalse(game.settings["pause_on_focus_loss_enabled"])
        self.assertEqual(game.announcements_menu.items[3].label, "Pause on Focus Loss: Off")
        self.assertEqual(speaker.messages[-1], ("Pause on Focus Loss: Off", True))

    def test_run_loop_routes_focus_loss_events_to_pause_menu(self):
        game, _, _ = self.make_game()
        game.state.running = True
        game.active_menu = None
        focus_event_type = getattr(pygame, "WINDOWFOCUSLOST", pygame.ACTIVEEVENT)
        if focus_event_type == pygame.ACTIVEEVENT:
            focus_event = pygame.event.Event(
                pygame.ACTIVEEVENT,
                gain=0,
                state=getattr(pygame, "APPINPUTFOCUS", 0) or getattr(pygame, "APPACTIVE", 0),
            )
        else:
            focus_event = pygame.event.Event(focus_event_type)

        with patch("subway_blind.game.config_module.save_settings"), patch(
            "pygame.event.get",
            side_effect=([focus_event, pygame.event.Event(pygame.QUIT)], []),
        ):
            game.run()

        self.assertTrue(game.state.paused)
        self.assertIs(game.active_menu, game.pause_menu)

    def test_coin_hotkey_is_silent_when_coin_counters_disabled(self):
        game, speaker, _ = self.make_game()
        game.state.coins = 17

        game._handle_game_key(pygame.K_r)

        self.assertNotIn(("Coins collected: 17.", False), speaker.messages)

    def test_spawn_things_still_creates_coin_lines_when_coin_counters_disabled(self):
        game, _, _ = self.make_game()
        game.state.next_spawn = 999.0
        game.state.next_support = 999.0
        game.state.next_coinline = 0.0

        game._spawn_things(0.016)

        coins = [obstacle for obstacle in game.obstacles if obstacle.kind == "coin"]
        self.assertTrue(coins)

    def test_record_mission_event_advances_metrics_when_quest_changes_disabled(self):
        game, _, _ = self.make_game()

        game._record_mission_event("coins")

        self.assertEqual(game.settings["mission_metrics"]["coins"], 1)

    def test_record_run_metric_tracks_quest_progress_without_announcing_when_disabled(self):
        game, speaker, audio = self.make_game()
        quest = daily_quests()[0]
        game.settings["quest_state"]["daily_progress"][quest.key] = quest.target - 1

        game._record_run_metric(quest.metric)

        self.assertEqual(game.settings["quest_state"]["daily_progress"][quest.key], quest.target)
        self.assertNotIn(("mission_reward", "ui", False), audio.played)
        self.assertFalse(any("Quest ready:" in message for message, _ in speaker.messages))

    def test_mission_set_menu_marks_over_target_goal_as_completed(self):
        game, _, _ = self.make_game()
        goal = game._mission_goals()[0]
        game.settings["mission_metrics"][goal.metric] = goal.target + 21

        game._refresh_mission_set_menu_labels()

        self.assertIn("Completed", game.mission_set_menu.items[0].label)
        self.assertIn(f"{goal.target}/{goal.target}", game.mission_set_menu.items[0].label)

    def test_reset_daily_progress_action_clears_daily_progress_and_preserves_claimed_rewards(self):
        game, speaker, _ = self.make_game()
        daily_quest = daily_quests()[0]
        game.settings["quest_state"]["daily_progress"][daily_quest.key] = max(1, daily_quest.target - 1)
        game.settings["word_hunt_day"] = date.today().isoformat()
        game.settings["word_hunt_letters"] = game._current_word()[:1]
        game.settings["event_state"]["daily_high_score_total"] = 1400
        game.settings["event_state"]["coin_meter_coins"] = 26
        game._refresh_quest_menu_labels()
        game.active_menu = game.quests_menu

        result = game._handle_menu_action("reset_daily_progress")

        self.assertTrue(result)
        self.assertEqual(game.settings["quest_state"]["daily_progress"][daily_quest.key], 0)
        self.assertEqual(game.settings["word_hunt_letters"], "")
        self.assertEqual(game.settings["event_state"]["daily_high_score_total"], 0)
        self.assertEqual(game.settings["event_state"]["coin_meter_coins"], 0)
        self.assertEqual(speaker.messages[-1][0], "Today's progress was reset. Claimed rewards stayed claimed.")

    def test_reset_daily_progress_keeps_completed_word_hunt_reward_locked(self):
        game, speaker, _ = self.make_game()
        today_iso = date.today().isoformat()
        completed_word = game._current_word()
        game.settings["word_hunt_day"] = today_iso
        game.settings["word_hunt_letters"] = completed_word
        game.settings["word_hunt_completed_on"] = today_iso
        game._refresh_quest_menu_labels()
        game.active_menu = game.quests_menu

        game._handle_menu_action("reset_daily_progress")

        self.assertEqual(game.settings["word_hunt_letters"], completed_word)
        self.assertEqual(
            speaker.messages[-1][0],
            "Today's progress was reset. Word Hunt stayed complete because today's reward was already claimed.",
        )

    def test_meter_milestone_is_silent_when_meters_disabled(self):
        game, speaker, audio = self.make_game()
        game.state.distance = 249.0
        game.state.milestone = 0
        game.state.running = True
        game.speed_profile = SPEED_PROFILES["normal"]

        game._update_game(0.2)

        self.assertNotIn(("250 meters", False), speaker.messages)
        self.assertNotIn(("mission_reward", "ui", False), audio.played)

    def test_meter_milestone_speaks_when_meters_enabled(self):
        game, speaker, audio = self.make_game()
        game.settings["meter_announcements_enabled"] = True
        game.state.distance = 249.0
        game.state.milestone = 0
        game.state.running = True
        game.speed_profile = SPEED_PROFILES["normal"]

        game._update_game(0.2)

        self.assertIn(("250 meters", False), speaker.messages)
        self.assertIn(("mission_reward", "ui", False), audio.played)

    def test_jetpack_auto_collects_coins_while_airborne(self):
        game, _, _ = self.make_game()
        game.player.jetpack = 4.0
        game.obstacles = [Obstacle(kind="coin", lane=1, z=1.0, value=1)]

        game._handle_obstacles()

        self.assertEqual(game.state.coins, 1)
        self.assertLess(game.obstacles[0].z, -100)

    def test_support_pickups_do_not_emit_warning_sound(self):
        game, _, audio = self.make_game()
        game.obstacles = [Obstacle(kind="power", lane=0, z=5.0)]

        game._handle_obstacles()

        self.assertFalse(any(key == "warning" for key, _, _ in audio.played))

    def test_jetpack_disables_lane_change_actions(self):
        game, _, audio = self.make_game()
        game.player.jetpack = 4.0
        game.player.lane = 0

        game._handle_game_key(pygame.K_LEFT)

        self.assertEqual(game.player.lane, 0)
        self.assertNotIn(("dodge", "move", False), audio.played)

    def test_second_hit_summary_remains_last_spoken_before_game_over_dialog(self):
        game, speaker, audio = self.make_game()
        game.player.stumbles = 1
        game.state.score = 120
        game.state.coins = 8
        game.state.running = True
        game.settings["keys"] = 0
        game.active_menu = None

        game._on_hit()

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertEqual(audio.music_stopped, 0)
        self.assertEqual(audio.music_started_tracks[-1], "menu")
        self.assertEqual(speaker.messages[-1], ("Game Over.", True))

    def test_game_over_dialog_defers_score_announcement_until_delay_expires(self):
        game, speaker, _ = self.make_game()
        game.state.score = 120
        game.state.coins = 8

        game._open_game_over_dialog("Hit train")

        self.assertEqual(speaker.messages[-1], ("Game Over.", True))
        self.assertEqual(game.game_over_menu.index, 0)
        self.assertIsNotNone(game._pending_menu_announcement)

    def test_game_over_menu_run_again_starts_new_run(self):
        game, _, audio = self.make_game()
        game.state.score = 80
        game.state.coins = 6
        game._game_over_summary = {"score": 80, "coins": 6, "play_time_seconds": 42, "death_reason": "Hit train"}
        game._refresh_game_over_menu()
        game.active_menu = game.game_over_menu

        game._handle_menu_action("game_over_retry")

        self.assertIsNone(game.active_menu)
        self.assertTrue(game.state.running)
        self.assertGreaterEqual(audio.music_started, 1)

    def test_game_over_menu_main_menu_returns_to_main_menu(self):
        game, _, _ = self.make_game()
        game._game_over_summary = {"score": 80, "coins": 6, "play_time_seconds": 42, "death_reason": "Hit train"}
        game._refresh_game_over_menu()
        game.active_menu = game.game_over_menu

        game._handle_menu_action("game_over_main_menu")

        self.assertIs(game.active_menu, game.main_menu)

    def test_game_over_main_menu_reopens_publish_prompt_for_authenticated_player(self):
        game, speaker, _ = self.make_game()
        game.leaderboard_client.auth_token = "token"
        game.leaderboard_client.principal_username = "runner01"
        game._game_over_summary = {"score": 80, "coins": 6, "play_time_seconds": 42, "death_reason": "Hit train"}
        game._refresh_game_over_menu()
        game.active_menu = game.game_over_menu

        game._handle_menu_action("game_over_main_menu")
        game._update_pending_menu_announcement(0.01)

        self.assertIs(game.active_menu, game.publish_confirm_menu)
        self.assertEqual(game._publish_confirm_return_menu, game.main_menu)
        self.assertEqual(speaker.messages[-1], ("Publish to Leaderboard?. Yes", True))

    def test_game_over_detail_rows_are_read_only(self):
        game, speaker, _ = self.make_game()
        game._game_over_summary = {"score": 80, "coins": 6, "play_time_seconds": 42, "death_reason": "Hit train"}
        game._refresh_game_over_menu()
        game.active_menu = game.game_over_menu
        game.game_over_menu.index = 0

        game._handle_menu_action("game_over_info_score")

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertEqual(speaker.messages[-1], ("Score: 80", True))

    def test_revive_end_run_opens_game_over_dialog_with_generic_crash_reason(self):
        game, speaker, _ = self.make_game()
        game.state.score = 55
        game.state.coins = 4
        game.state.running = True
        game.active_menu = game.revive_menu

        game._handle_menu_action("end_run")

        self.assertIs(game.active_menu, game.game_over_menu)
        self.assertEqual(game.game_over_menu.items[3].label, "Death reason: Run ended after crash")
        self.assertIn(("Run over. Score 55. Run ended after crash.", True), speaker.messages)

    def test_draw_menu_keeps_hint_on_small_screens(self):
        game, _, _ = self.make_game()
        game.screen = pygame.display.set_mode((320, 240))

        game._draw_menu(game.main_menu)

        self.assertEqual(game.screen.get_size(), (320, 240))

    def test_handle_window_resize_enforces_minimum_window_size(self):
        game, _, _ = self.make_game()

        game._handle_window_event(pygame.event.Event(pygame.VIDEORESIZE, w=320, h=200))

        self.assertEqual(game.screen.get_size(), (640, 360))

    def test_window_size_changed_refreshes_screen_reference(self):
        game, _, _ = self.make_game()
        resized = pygame.display.set_mode((700, 420), pygame.RESIZABLE)

        game._handle_window_event(pygame.event.Event(pygame.WINDOWSIZECHANGED, x=700, y=420))

        self.assertIs(game.screen, resized)


if __name__ == "__main__":
    unittest.main()
