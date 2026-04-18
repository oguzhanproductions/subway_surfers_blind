from __future__ import annotations
import ctypes
import queue
import sys
import textwrap
from dataclasses import dataclass
from datetime import date
import random
import re
import threading
import time
from typing import Callable, Optional
import pygame
from subway_blind import config as config_module
from subway_blind.audio import Audio, Speaker, SAPI_RATE_MAX, SAPI_RATE_MIN, SAPI_PITCH_MAX, SAPI_PITCH_MIN, SAPI_VOICE_UNAVAILABLE_LABEL, SAPI_VOLUME_MAX, SAPI_VOLUME_MIN, SYSTEM_DEFAULT_OUTPUT_LABEL
from subway_blind.balance import SpeedProfile, speed_profile_for_difficulty
from subway_blind.boards import board_definition, board_definitions, board_unlocked, ensure_board_state, selected_board_definition
from subway_blind.characters import CharacterRuntimeBonuses, character_definition, character_definitions, character_level, character_perk_summary, character_runtime_bonuses, character_unlocked, ensure_character_progress_state, next_character_upgrade_cost, selected_character_definition
from subway_blind.config import resource_path
from subway_blind.collections import collection_bonus_summary, collection_definitions, collection_progress, collection_runtime_bonuses, completed_collection_keys, ensure_collection_state
from subway_blind.controls import ACTION_DEFINITIONS_BY_KEY, CONTROLLER_ACTION_ORDER, GAME_CONTEXT, KEYBOARD_ACTION_ORDER, MENU_CONTEXT, ControllerSupport, action_label, controller_binding_label, default_keyboard_bindings, family_label, keyboard_binding_label, keyboard_key_label
from subway_blind.events import can_claim_coin_meter_reward, can_claim_daily_high_score_reward, claim_coin_meter_reward, claim_daily_gift, claim_daily_high_score_reward, claim_login_calendar_reward, current_daily_event, daily_gift_available, ensure_event_state, event_runtime_profile, featured_character_key, login_calendar_available, login_calendar_next_day, next_coin_meter_threshold, next_daily_high_score_threshold, record_coin_meter_coins, record_daily_score, reset_daily_event_progress, tomorrow_daily_event
from subway_blind.leaderboard_client import LeaderboardClient, LeaderboardClientError
from subway_blind.item_upgrades import DEFAULT_ITEM_UPGRADE_KEY, ensure_item_upgrade_state, item_upgrade_definition, item_upgrade_definitions, item_upgrade_duration, item_upgrade_level, next_item_upgrade_cost
from subway_blind.features import clamp_headstart_uses, HEADSTART_SPEED_BONUS, headstart_duration_for_uses, HOVERBOARD_DURATION, HOVERBOARD_MAX_USES_PER_RUN, pick_headstart_end_reward, pick_mystery_box_reward, pick_shop_mystery_box_reward, revive_cost, REVIVE_MAX_USES_PER_RUN, SHOP_PRICES, shop_box_reward_amount, score_booster_bonus
from subway_blind.menu import Menu, MenuItem
from subway_blind.models import LANES, Obstacle, Player, RunState, lane_name, lane_to_pan, normalize_lane
from subway_blind.native_windows_credentials import CredentialPromptCancelled, NativeCredentialPromptError, prompt_for_credentials
from subway_blind.native_windows_issue_dialog import IssueDialogCancelled, NativeIssueDialogError, ISSUE_MESSAGE_LIMIT, ISSUE_TITLE_LIMIT, prompt_for_inline_issue_text
from subway_blind.progression import achievement_definitions, achievement_progress, active_word_for_settings, can_claim_season_reward, claim_season_reward, completed_mission_metrics, ensure_progression_state, mission_goals_for_set, newly_unlocked_achievements, next_season_reward_threshold, pick_super_mystery_box_reward, record_achievement_progress, register_season_token, register_word_letter, remaining_word_letters, reset_daily_word_hunt_progress, set_achievement_progress_max, update_word_hunt_streak, word_hunt_reward_for_streak
from subway_blind.quests import can_claim_meter_reward, claim_meter_reward, claim_quest, daily_quests, ensure_quest_state, next_meter_threshold, quest_claimed, quest_completed, quest_progress, quest_sneakers, record_quest_metric, reset_daily_quest_progress, seasonal_quests
from subway_blind.spawn import RoutePattern, SpawnDirector
from subway_blind.spatial_audio import SpatialThreatAudio
from subway_blind.updater import GitHubReleaseUpdater, UpdateCheckResult, UpdateInstallProgress, UpdateInstallResult, version_key
from subway_blind.version import APP_VERSION
from subway_blind.strings import ACTIVE_GAMEPLAY_SOUND_KEYS, DIFFICULTY_LABELS, HelpTopic, HOW_TO_TOPICS, ISSUE_STATUS_LABELS, ISSUE_STATUS_ORDER, LEADERBOARD_DIFFICULTY_FILTER_LABELS, LEADERBOARD_DIFFICULTY_FILTER_ORDER, LEADERBOARD_PERIOD_LABELS, LEADERBOARD_PERIOD_ORDER, LEADERBOARD_VERIFICATION_LABELS, LearnSoundEntry, LEARN_SOUND_LIBRARY, RUN_POWERUP_LABELS, SEASON_IMPRINT_TEXT, SPECIAL_ITEM_EFFECT_TEXT, SPECIAL_ITEM_LABELS, SPECIAL_ITEM_ORDER, TEXT, UPGRADE_HELP_TOPICS, sx as _sx
LEADERBOARD_CACHE_TTL_SECONDS = 45.0
GUARD_LOOP_DURATION = 1.35
POGO_STICK_DURATION = 5.5
MENU_REPEAT_INITIAL_DELAY = 0.34
MENU_REPEAT_INTERVAL = 0.075
LEARN_SOUND_PREVIEW_CHANNEL = _sx(640)
LEARN_SOUND_LOOP_PREVIEW_DURATION = 2.6
HEADSTART_SHAKE_CHANNEL = _sx(641)
HEADSTART_SPRAY_CHANNEL = _sx(642)
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 360
ISSUE_REPORT_PAGE_SIZE = 50
ISSUE_CACHE_TTL_SECONDS = 20.0
PRACTICE_BASE_SPEED = 16.0
PRACTICE_SCALING_MAX_SPEED = 23.0
PRACTICE_SCALING_CAP_SECONDS = 95.0
PRACTICE_TARGET_HAZARDS = 24
PRACTICE_TARGET_HAZARDS_MIN = 1
PRACTICE_TARGET_HAZARDS_MAX = 10000
PRACTICE_PROGRESS_STEP = 6
PRACTICE_HAZARD_KINDS = {_sx(643), _sx(644), _sx(97), _sx(645)}
EVENT_CHARACTER_OFFER_KEYS = (_sx(268), _sx(271), _sx(274), _sx(277), _sx(280), _sx(283))
EVENT_SHOP_KEY_COST = 18
EVENT_SHOP_HOVERBOARD_PACK_COST = 16
EVENT_SHOP_HEADSTART_COST = 20
EVENT_SHOP_SCORE_BOOSTER_COST = 24
EVENT_SHOP_SUPER_BOX_COST = 30
BINDING_CAPTURE_HOLD_SECONDS = 3.0
BINDING_CAPTURE_DING_PITCHES = {3: 1.0, 2: 1.15, 1: 1.3}

@dataclass(frozen=True)
class BindingCaptureRequest:
    device: str
    action_key: str

@dataclass
class KeyboardBindingHoldState:
    action_key: str
    binding_value: int | dict[str, object]
    required_keys: frozenset[int]
    remaining_seconds: float
    next_ding_mark: int

@dataclass(frozen=True)
class InfoDialogContent:
    title: str
    lines: tuple[str, ...]

@dataclass(frozen=True)
class LeaderboardOperationResult:
    token: int
    operation: str
    success: bool
    payload: object

def step_volume(value: float, direction: int) -> float:
    stepped = round(float(value) + 0.05 * direction, 2)
    return max(0.0, min(1.0, stepped))

def step_int(value: int, direction: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value) + direction))

def format_duration_seconds(duration: float) -> str:
    formatted = _sx(298).format(float(duration)).rstrip(_sx(297)).rstrip(_sx(292))
    return _sx(646).format(formatted)

def format_play_time(total_seconds: float) -> str:
    total = max(0, int(round(float(total_seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return _sx(648).format(hours, minutes, seconds)
    return _sx(647).format(minutes, seconds)

def difficulty_display_label(value: object) -> str:
    normalized = str(value or _sx(578)).strip().lower()
    return DIFFICULTY_LABELS.get(normalized, TEXT[_sx(578)])

def leaderboard_period_display_label(value: object) -> str:
    normalized = str(value or _sx(659)).strip().lower()
    return LEADERBOARD_PERIOD_LABELS.get(normalized, LEADERBOARD_PERIOD_LABELS[_sx(659)])

def leaderboard_difficulty_filter_display_label(value: object) -> str:
    normalized = str(value or _sx(660)).strip().lower()
    return LEADERBOARD_DIFFICULTY_FILTER_LABELS.get(normalized, LEADERBOARD_DIFFICULTY_FILTER_LABELS[_sx(660)])

def issue_status_display_label(value: object) -> str:
    normalized = str(value or _sx(660)).strip().lower()
    return ISSUE_STATUS_LABELS.get(normalized, ISSUE_STATUS_LABELS[_sx(660)])

def verification_display_label(value: object) -> str:
    normalized = str(value or _sx(786)).strip().lower()
    return LEADERBOARD_VERIFICATION_LABELS.get(normalized, LEADERBOARD_VERIFICATION_LABELS[_sx(786)])

def help_topic_segments(topic: HelpTopic, controls_summary: str) -> tuple[str, ...]:
    if topic.key == _sx(649):
        text = _sx(650).format(controls_summary, topic.description)
    else:
        text = topic.description
    parts = [segment.strip() for segment in re.split(_sx(1164), text) if segment.strip()]
    return tuple(parts) if parts else (text.strip(),)

def load_whats_new_content() -> InfoDialogContent:
    fallback = InfoDialogContent(title=_sx(788).format(TEXT[_sx(1782)], APP_VERSION), lines=(TEXT[_sx(1576)],))
    try:
        changelog_path = resource_path(_sx(789))
        with open(changelog_path, _sx(385), encoding=_sx(386)) as handle:
            lines = [line.rstrip() for line in handle]
    except Exception:
        return fallback
    entry_lines: list[str] = []
    found_date = False
    for line in lines:
        stripped = line.strip()
        if not found_date:
            if stripped.startswith(_sx(1165)):
                found_date = True
            continue
        if stripped == _sx(790):
            break
        if stripped:
            entry_lines.append(stripped)
    if not entry_lines:
        return fallback
    return InfoDialogContent(title=_sx(788).format(TEXT[_sx(1782)], APP_VERSION), lines=tuple(entry_lines))

def copy_text_to_clipboard(text: str) -> bool:
    normalized_text = str(text).replace(_sx(1166), _sx(652)).replace(_sx(651), _sx(652))
    if sys.platform == _sx(791) and _copy_text_to_clipboard_windows(normalized_text):
        return True
    return _copy_text_to_clipboard_pygame(normalized_text)

def _copy_text_to_clipboard_windows(text: str) -> bool:
    user32 = getattr(ctypes, _sx(653), None)
    if user32 is None:
        return False
    user32 = user32.user32
    kernel32 = ctypes.windll.kernel32
    window_handle = int(pygame.display.get_wm_info().get(_sx(1167), 0) or 0)
    clipboard_handle = ctypes.c_void_p(window_handle) if window_handle else None
    for _ in range(8):
        if user32.OpenClipboard(clipboard_handle):
            break
        time.sleep(0.01)
    else:
        return False
    global_handle = None
    try:
        if not user32.EmptyClipboard():
            return False
        buffer = ctypes.create_unicode_buffer(text)
        bytes_required = ctypes.sizeof(buffer)
        global_handle = kernel32.GlobalAlloc(2, bytes_required)
        if not global_handle:
            return False
        locked_memory = kernel32.GlobalLock(global_handle)
        if not locked_memory:
            kernel32.GlobalFree(global_handle)
            global_handle = None
            return False
        try:
            ctypes.memmove(locked_memory, ctypes.addressof(buffer), bytes_required)
        finally:
            kernel32.GlobalUnlock(global_handle)
        if not user32.SetClipboardData(13, global_handle):
            kernel32.GlobalFree(global_handle)
            global_handle = None
            return False
        global_handle = None
        return True
    finally:
        user32.CloseClipboard()
        if global_handle:
            kernel32.GlobalFree(global_handle)

def _copy_text_to_clipboard_pygame(text: str) -> bool:
    scrap = getattr(pygame, _sx(654), None)
    if scrap is None or not pygame.display.get_init():
        return False
    try:
        scrap.init()
    except Exception:
        pass
    try:
        scrap.put(pygame.SCRAP_TEXT, text.encode(_sx(386)))
    except Exception:
        return False
    return True

class SubwayBlindGame:

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock, settings: dict, updater: GitHubReleaseUpdater | None=None, packaged_build: bool | None=None):
        self.screen = screen
        self.clock = clock
        self.settings = settings
        self.speaker = Speaker.from_settings(settings)
        self.audio = Audio(settings)
        self.updater = updater or GitHubReleaseUpdater()
        self.packaged_build = bool(getattr(sys, _sx(362), False)) if packaged_build is None else bool(packaged_build)
        self.font = pygame.font.SysFont(_sx(792), 22)
        self.big = pygame.font.SysFont(_sx(792), 38, bold=True)
        ensure_progression_state(self.settings)
        ensure_character_progress_state(self.settings)
        ensure_board_state(self.settings)
        ensure_item_upgrade_state(self.settings)
        ensure_collection_state(self.settings)
        ensure_quest_state(self.settings)
        ensure_event_state(self.settings)
        self.state = RunState()
        self.player = Player()
        self.obstacles: list[Obstacle] = []
        self.speed_profile: SpeedProfile = speed_profile_for_difficulty(str(self.settings[_sx(318)]))
        self.spatial_audio = SpatialThreatAudio()
        self.spawn_director = SpawnDirector()
        self.selected_headstarts = 0
        self.selected_score_boosters = 0
        self._footstep_timer = 0.0
        self._left_foot_next = True
        self._run_rewards_committed = False
        self._near_miss_signatures: set[tuple[str, int]] = set()
        self._guard_loop_timer = 0.0
        self._coin_pitch_index = 0
        self._coin_pitch_timer = 0.0
        self._coin_streak = 0
        self._menu_repeat_key: int | None = None
        self._menu_repeat_delay_remaining = 0.0
        self._learn_sound_entries_by_action = {_sx(793).format(entry.key): entry for entry in LEARN_SOUND_LIBRARY}
        self._learn_sound_description = _sx(655)
        self._learn_sound_preview_timer = 0.0
        self._exit_requested = False
        self._latest_update_result: UpdateCheckResult | None = None
        self._update_status_message = _sx(656)
        self._update_release_notes = _sx(657)
        self._update_progress_percent = 0.0
        self._update_progress_message = _sx(2)
        self._update_progress_stage = _sx(658)
        self._update_progress_announced_bucket = -1
        self._update_install_thread: threading.Thread | None = None
        self._update_install_result: UpdateInstallResult | None = None
        self._update_restart_script_path: str | None = None
        self._update_install_error = _sx(2)
        self._update_ready_announced = False
        self._showing_upgrade_help = False
        self._active_character_bonuses = CharacterRuntimeBonuses()
        self._collection_bonuses = collection_runtime_bonuses(self.settings)
        self._active_event_profile = event_runtime_profile(self.settings)
        self._character_detail_key = selected_character_definition(self.settings).key
        self._board_detail_key = selected_board_definition(self.settings).key
        self._item_upgrade_detail_key = DEFAULT_ITEM_UPGRADE_KEY
        self.controls = ControllerSupport(settings)
        self._binding_capture: BindingCaptureRequest | None = None
        self._keyboard_binding_hold: KeyboardBindingHoldState | None = None
        self._pressed_keys: set[int] = set()
        self._selected_binding_device = _sx(565) if self.controls.active_controller() is not None else _sx(563)
        self.leaderboard_client = LeaderboardClient()
        self._leaderboard_username = str(self.settings.get(_sx(330), _sx(2)) or _sx(2)).strip()
        self._restore_persisted_leaderboard_session()
        self._server_special_items: dict[str, int] = {}
        self._server_special_item_loadout: dict[str, bool] = {key: False for key in SPECIAL_ITEM_ORDER}
        self._server_wheel_status: dict[str, object] = {}
        self._season_imprint_bonus_key = _sx(2)
        self._special_toggle_item_key = _sx(2)
        self._active_special_run_items: set[str] = set()
        self._special_effect_timers: dict[str, float] = {}
        self._special_run_used_flags: set[str] = set()
        self._consumed_special_items_this_run: set[str] = set()
        self._pending_consumed_special_items: list[str] = []
        self._pending_overclock_keys = 0
        self._box_high_tier_meter = 0
        self._coin_streak_grace_timer = 0.0
        self._leaderboard_period_filter = _sx(659)
        self._leaderboard_difficulty_filter = _sx(660)
        self._leaderboard_season: dict[str, object] = {}
        self._leaderboard_entries: list[dict[str, object]] = []
        self._leaderboard_total_players = 0
        self._leaderboard_profile: dict[str, object] | None = None
        self._leaderboard_selected_run: dict[str, object] | None = None
        self._leaderboard_profile_history_count = 0
        self._leaderboard_cache_loaded_at = 0.0
        self._leaderboard_operation_queue: queue.Queue[LeaderboardOperationResult] = queue.Queue()
        self._leaderboard_operation_token = 0
        self._leaderboard_active_operation: str | None = None
        self._leaderboard_return_menu: Menu | None = None
        self._leaderboard_startup_sync_started = False
        self._issue_status_filter = _sx(660)
        self._issue_entries: list[dict[str, object]] = []
        self._issue_total_reports = 0
        self._issue_offset = 0
        self._issue_cache_loaded_at = 0.0
        self._selected_issue_report: dict[str, object] | None = None
        self._selected_issue_detail_content: InfoDialogContent | None = None
        self._issue_draft_title = _sx(2)
        self._issue_draft_message = _sx(2)
        self._meta_return_menu: Menu | None = None
        self._options_return_menu: Menu | None = None
        self._publish_confirm_return_menu: Menu | None = None
        self._publish_confirm_return_index = 0
        self._publish_after_leaderboard_auth = False
        self._issue_submit_after_leaderboard_auth = False
        self._pending_purchase_handler: Callable[[], None] | None = None
        self._pending_purchase_return_menu: Menu | None = None
        self._pending_purchase_return_index = 0
        self._pending_wheel_spin_reward: dict[str, object] | None = None
        self._pending_wheel_spin_reward_delay = 0.0
        self._game_over_publish_state = _sx(658)
        self._active_run_stats = self._empty_run_stats()
        self._game_over_summary = self._empty_game_over_summary()
        self._last_death_reason = _sx(661)
        self._practice_mode_active = False
        self._practice_speed_scaling_active = False
        self._pending_practice_setup = False
        self._practice_hazards_cleared = 0
        self._practice_hazard_target = self._practice_hazard_target_setting()
        self._practice_next_progress_announcement = PRACTICE_PROGRESS_STEP
        self._pending_menu_announcement: Optional[tuple[Menu, float, bool]] = None
        self._menu_last_indices: dict[int, int] = {}
        self._magnet_loop_active = False
        self._jetpack_loop_active = False
        self.pause_menu = Menu(self.speaker, self.audio, _sx(794), [MenuItem(_sx(1577), _sx(1420)), MenuItem(_sx(1578), _sx(1422)), MenuItem(_sx(479), _sx(1421))])
        self.pause_confirm_menu = Menu(self.speaker, self.audio, _sx(795), [MenuItem(TEXT[_sx(1783)], _sx(1423)), MenuItem(TEXT[_sx(1784)], _sx(1424))])
        self.leaderboard_logout_confirm_menu = Menu(self.speaker, self.audio, _sx(796), [MenuItem(TEXT[_sx(1783)], _sx(1425)), MenuItem(TEXT[_sx(1784)], _sx(1426))])
        self.exit_confirm_menu = Menu(self.speaker, self.audio, _sx(797), [MenuItem(TEXT[_sx(1783)], _sx(1431)), MenuItem(TEXT[_sx(1784)], _sx(1432))])
        self.revive_menu = Menu(self.speaker, self.audio, _sx(798), [MenuItem(self._revive_option_label(), _sx(1433)), MenuItem(_sx(1579), _sx(1580))])
        self.publish_confirm_menu = Menu(self.speaker, self.audio, _sx(799), [MenuItem(TEXT[_sx(1783)], _sx(1427)), MenuItem(TEXT[_sx(1784)], _sx(1428))])
        self.purchase_confirm_menu = Menu(self.speaker, self.audio, _sx(800), [MenuItem(TEXT[_sx(1783)], _sx(1429)), MenuItem(TEXT[_sx(1784)], _sx(1430))])
        self.game_over_menu = Menu(self.speaker, self.audio, _sx(801), [MenuItem(_sx(1581), _sx(1582)), MenuItem(_sx(1583), _sx(1584)), MenuItem(_sx(1585), _sx(1586)), MenuItem(_sx(1587), _sx(1588)), MenuItem(_sx(751), _sx(964)), MenuItem(_sx(752), _sx(965))])
        self.main_menu = Menu(self.speaker, self.audio, self._main_menu_title(), self._main_menu_items(), description_enabled=self._main_menu_descriptions_enabled)
        self.loadout_menu = Menu(self.speaker, self.audio, _sx(802), [])
        self.events_menu = Menu(self.speaker, self.audio, _sx(803), [])
        self.wheel_menu = Menu(self.speaker, self.audio, _sx(703), [])
        self.event_shop_menu = Menu(self.speaker, self.audio, _sx(804), [])
        self.missions_hub_menu = Menu(self.speaker, self.audio, _sx(805), [])
        self.mission_set_menu = Menu(self.speaker, self.audio, _sx(806), [])
        self.quests_menu = Menu(self.speaker, self.audio, _sx(807), [])
        self.me_menu = Menu(self.speaker, self.audio, _sx(808), [])
        self.options_menu = Menu(self.speaker, self.audio, _sx(479), self._build_options_menu_items())
        self.sapi_menu = Menu(self.speaker, self.audio, _sx(671), [MenuItem(self._sapi_speech_option_label(), _sx(1121)), MenuItem(self._sapi_volume_option_label(), _sx(1122)), MenuItem(self._sapi_voice_option_label(), _sx(1123)), MenuItem(self._sapi_rate_option_label(), _sx(1124)), MenuItem(self._sapi_pitch_option_label(), _sx(1125)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.announcements_menu = Menu(self.speaker, self.audio, _sx(809), [MenuItem(self._meter_option_label(), _sx(1130)), MenuItem(self._coin_counter_option_label(), _sx(1131)), MenuItem(self._quest_changes_option_label(), _sx(1132)), MenuItem(self._pause_on_focus_loss_option_label(), _sx(1133)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.controls_menu = Menu(self.speaker, self.audio, _sx(754), [])
        self.server_status_menu = Menu(self.speaker, self.audio, _sx(810), [MenuItem(_sx(1086), _sx(1589)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.leaderboard_menu = Menu(self.speaker, self.audio, _sx(811), [MenuItem(_sx(1590), _sx(1390)), MenuItem(_sx(1452), _sx(1083)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.leaderboard_profile_menu = Menu(self.speaker, self.audio, _sx(812), [MenuItem(TEXT[_sx(429)], _sx(429))])
        self.leaderboard_run_detail_menu = Menu(self.speaker, self.audio, _sx(777), [MenuItem(TEXT[_sx(429)], _sx(429))])
        self.issue_menu = Menu(self.speaker, self.audio, _sx(813), [MenuItem(_sx(1489), _sx(1073)), MenuItem(_sx(1591), _sx(1392)), MenuItem(_sx(1592), _sx(1593)), MenuItem(_sx(1594), _sx(1595)), MenuItem(_sx(1596), _sx(1101)), MenuItem(_sx(1597), _sx(1102)), MenuItem(_sx(1452), _sx(1100)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.issue_detail_menu = Menu(self.speaker, self.audio, _sx(814), [MenuItem(TEXT[_sx(429)], _sx(429))])
        self.issue_compose_menu = Menu(self.speaker, self.audio, _sx(813), [MenuItem(_sx(1090), _sx(1108)), MenuItem(_sx(1093), _sx(1109)), MenuItem(_sx(1490), _sx(1394)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.keyboard_bindings_menu = Menu(self.speaker, self.audio, _sx(815), [])
        self.controller_bindings_menu = Menu(self.speaker, self.audio, _sx(816), [])
        self.shop_menu = Menu(self.speaker, self.audio, self._shop_title(), [MenuItem(self._shop_hoverboard_label(), _sx(1397)), MenuItem(self._shop_box_label(), _sx(1398)), MenuItem(self._shop_headstart_label(), _sx(1399)), MenuItem(self._shop_score_booster_label(), _sx(1400)), MenuItem(self._shop_daily_gift_label(), _sx(1219)), MenuItem(self._shop_item_upgrade_label(), _sx(1245)), MenuItem(self._shop_character_upgrade_label(), _sx(1401)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.item_upgrade_menu = Menu(self.speaker, self.audio, self._item_upgrade_menu_title(), [])
        self.item_upgrade_detail_menu = Menu(self.speaker, self.audio, item_upgrade_definition(self._item_upgrade_detail_key).name, [])
        self.character_menu = Menu(self.speaker, self.audio, self._character_menu_title(), [])
        self.character_detail_menu = Menu(self.speaker, self.audio, selected_character_definition(self.settings).name, [])
        self.board_menu = Menu(self.speaker, self.audio, self._board_menu_title(), [])
        self.board_detail_menu = Menu(self.speaker, self.audio, selected_board_definition(self.settings).name, [])
        self.collection_menu = Menu(self.speaker, self.audio, self._collection_menu_title(), [])
        self.learn_sounds_menu = Menu(self.speaker, self.audio, _sx(817), [MenuItem(entry.label, _sx(793).format(entry.key)) for entry in LEARN_SOUND_LIBRARY] + [MenuItem(TEXT[_sx(429)], _sx(429))])
        self.howto_menu = Menu(self.speaker, self.audio, _sx(818), [])
        self._refresh_howto_menu_labels()
        self.help_topic_menu = Menu(self.speaker, self.audio, _sx(819), [MenuItem(TEXT[_sx(429)], _sx(429))])
        self._selected_help_topic: HelpTopic | None = None
        self.whats_new_menu = Menu(self.speaker, self.audio, _sx(820), [MenuItem(TEXT[_sx(429)], _sx(429))])
        self._selected_info_dialog: InfoDialogContent | None = None
        self.achievements_menu = Menu(self.speaker, self.audio, self._achievements_menu_title(), [])
        self.update_menu = Menu(self.speaker, self.audio, _sx(821), [MenuItem(_sx(994), _sx(995)), MenuItem(_sx(756), _sx(757)), MenuItem(_sx(767), _sx(768))])
        self._refresh_item_upgrade_menu_labels()
        self._refresh_item_upgrade_detail_menu_labels(self._item_upgrade_detail_key)
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(self._character_detail_key)
        self._refresh_board_menu_labels()
        self._refresh_board_detail_menu_labels(self._board_detail_key)
        self._refresh_collection_menu_labels()
        self._refresh_events_menu_labels()
        self._refresh_missions_hub_menu_labels()
        self._refresh_mission_set_menu_labels()
        self._refresh_quest_menu_labels()
        self._refresh_me_menu_labels()
        self._refresh_issue_menu()
        self._refresh_control_menus()
        self._refresh_game_over_menu()
        self.active_menu: Optional[Menu] = self.main_menu
        if self.packaged_build and bool(self.settings.get(_sx(316), True)):
            self._show_startup_status(_sx(1169))
            self._check_for_updates(announce_result=False, automatic=True)
        if self.active_menu == self.main_menu and (not self.main_menu.opened):
            self.active_menu.open()
            self._sync_music_context()
        self._sync_character_progress()
        self._mark_current_version_seen()
        self._start_background_leaderboard_sync()

    def _sfx_option_label(self) -> str:
        return _sx(662).format(int(float(self.settings[_sx(130)]) * 100))

    def _main_menu_title(self) -> str:
        return _sx(663).format(APP_VERSION)

    def _achievements_menu_title(self) -> str:
        unlocked = len(self.settings.get(_sx(350), []))
        total = len(achievement_definitions())
        return _sx(664).format(unlocked, total)

    def _howto_menu_title(self) -> str:
        return _sx(826).format(APP_VERSION) if self._showing_upgrade_help else _sx(818)

    def _shop_title(self) -> str:
        return _sx(665)

    def _shop_coins_label(self) -> str:
        return _sx(666).format(int(self.settings.get(_sx(333), 0)))

    def _shop_max_purchasable(self, item_key: str) -> int:
        coins = int(self.settings.get(_sx(333), 0))
        cost = int(SHOP_PRICES.get(item_key, 0))
        if cost <= 0:
            return 0
        return max(0, coins // cost)

    def _music_option_label(self) -> str:
        return _sx(667).format(int(float(self.settings[_sx(196)]) * 100))

    def _updates_option_label(self) -> str:
        return _sx(668).format(_sx(1598) if self.settings[_sx(316)] else _sx(1599))

    def _speech_option_label(self) -> str:
        return _sx(669).format(_sx(1598) if self.settings[_sx(117)] else _sx(1599))

    def _sapi_speech_option_label(self) -> str:
        return _sx(670).format(_sx(1598) if self.settings[_sx(118)] else _sx(1599))

    def _sapi_menu_entry_label(self) -> str:
        return _sx(671)

    def _audio_output_option_label(self) -> str:
        return _sx(672).format(self.audio.output_device_display_name())

    def _menu_sound_hrtf_option_label(self) -> str:
        return _sx(673).format(_sx(1598) if self.settings[_sx(195)] else _sx(1599))

    def _menu_wrap_option_label(self) -> str:
        return _sx(674).format(_sx(1598) if self.settings.get(_sx(315), False) else _sx(1599))

    def _sapi_voice_option_label(self) -> str:
        voice_name = self.speaker.current_sapi_voice_display_name()
        return _sx(675).format(voice_name)

    def _sapi_rate_option_label(self) -> str:
        return _sx(676).format(int(self.settings.get(_sx(120), 0)))

    def _sapi_pitch_option_label(self) -> str:
        return _sx(677).format(int(self.settings.get(_sx(121), 0)))

    def _sapi_volume_option_label(self) -> str:
        return _sx(678).format(int(self.settings.get(_sx(122), 100)))

    def _difficulty_option_label(self) -> str:
        difficulty = DIFFICULTY_LABELS.get(str(self.settings[_sx(318)]), _sx(839))
        return _sx(679).format(difficulty)

    def _meter_option_label(self) -> str:
        return _sx(680).format(_sx(1598) if self._meters_enabled() else _sx(1599))

    def _coin_counter_option_label(self) -> str:
        return _sx(681).format(_sx(1598) if self._coin_counters_enabled() else _sx(1599))

    def _quest_changes_option_label(self) -> str:
        return _sx(682).format(_sx(1598) if self._quest_changes_enabled() else _sx(1599))

    def _pause_on_focus_loss_option_label(self) -> str:
        return _sx(683).format(_sx(1598) if self._pause_on_focus_loss_enabled() else _sx(1599))

    def _main_menu_description_option_label(self) -> str:
        return _sx(684).format(_sx(1598) if self._main_menu_descriptions_enabled() else _sx(1599))

    def _leaderboard_account_option_label(self) -> str:
        if self._leaderboard_username:
            return _sx(846).format(self._leaderboard_username)
        return _sx(685)

    def _leaderboard_logout_option_label(self) -> str:
        if self._leaderboard_username:
            return _sx(847).format(self._leaderboard_username)
        return _sx(686)

    def _leaderboard_is_authenticated(self) -> bool:
        return self.leaderboard_client.is_authenticated()

    def _leaderboard_has_publish_identity(self) -> bool:
        if self._leaderboard_is_authenticated():
            return True
        return bool(str(self._leaderboard_username or _sx(2)).strip())

    def _exit_confirmation_option_label(self) -> str:
        return _sx(687).format(_sx(1598) if self._exit_confirmation_enabled() else _sx(1599))

    def _purchase_confirmation_option_label(self) -> str:
        return _sx(688).format(_sx(1598) if self._purchase_confirmation_enabled() else _sx(1599))

    def _headstart_option_label(self) -> str:
        owned = int(self.settings.get(_sx(336), 0))
        return _sx(689).format(self.selected_headstarts, owned)

    def _score_booster_option_label(self) -> str:
        owned = int(self.settings.get(_sx(337), 0))
        return _sx(690).format(self.selected_score_boosters, owned)

    def _revive_option_label(self) -> str:
        if int(self.state.revives_used) >= REVIVE_MAX_USES_PER_RUN:
            return _sx(853).format(REVIVE_MAX_USES_PER_RUN)
        cost = revive_cost(self.state.revives_used)
        owned = int(self.settings.get(_sx(334), 0))
        return _sx(691).format(cost, _sx(294) if cost != 1 else _sx(2), owned)

    def _shop_hoverboard_label(self) -> str:
        max_buy = self._shop_max_purchasable(_sx(594))
        return _sx(692).format(SHOP_PRICES[_sx(594)], int(self.settings.get(_sx(335), 0)), max_buy)

    def _shop_box_label(self) -> str:
        max_buy = self._shop_max_purchasable(_sx(21))
        return _sx(693).format(SHOP_PRICES[_sx(21)], max_buy)

    def _shop_headstart_label(self) -> str:
        max_buy = self._shop_max_purchasable(_sx(595))
        return _sx(694).format(SHOP_PRICES[_sx(595)], int(self.settings.get(_sx(336), 0)), max_buy)

    def _shop_score_booster_label(self) -> str:
        max_buy = self._shop_max_purchasable(_sx(596))
        return _sx(695).format(SHOP_PRICES[_sx(596)], int(self.settings.get(_sx(337), 0)), max_buy)

    def _shop_item_upgrade_label(self) -> str:
        maxed = sum((1 for definition in item_upgrade_definitions() if item_upgrade_level(self.settings, definition.key) >= definition.max_level))
        return _sx(696).format(maxed, len(item_upgrade_definitions()))

    def _shop_character_upgrade_label(self) -> str:
        active_character = selected_character_definition(self.settings)
        return _sx(697).format(active_character.name)

    def _shop_daily_gift_label(self) -> str:
        return _sx(866) if daily_gift_available(self.settings) else _sx(867)

    def _loadout_board_label(self) -> str:
        board = selected_board_definition(self.settings)
        return _sx(698).format(board.name, board.power_label)

    def _loadout_title(self) -> str:
        return _sx(870) if self._pending_practice_setup else _sx(802)

    @staticmethod
    def _special_item_label(item_key: str) -> str:
        return SPECIAL_ITEM_LABELS.get(str(item_key or _sx(2)).strip().lower(), _sx(871))

    def _special_item_owned_count(self, item_key: str) -> int:
        return max(0, int(self._server_special_items.get(item_key, 0) or 0))

    def _special_item_enabled(self, item_key: str) -> bool:
        if self._special_item_owned_count(item_key) <= 0:
            return False
        return bool(self._server_special_item_loadout.get(item_key, False))

    def _special_item_loadout_label(self, item_key: str) -> str:
        return _sx(699).format(self._special_item_label(item_key), _sx(1598) if self._special_item_enabled(item_key) else _sx(1599), self._special_item_owned_count(item_key))

    def _wheel_status_label(self) -> str:
        spins_remaining = int(self._server_wheel_status.get(_sx(1600), 0) or 0)
        max_spins = int(self._server_wheel_status.get(_sx(1601), 2) or 2)
        return _sx(700).format(spins_remaining, max_spins)

    def _season_imprint_status_label(self) -> str:
        bonus_key = str(self._season_imprint_bonus_key or _sx(2)).strip().lower()
        if not bonus_key:
            return _sx(874)
        description = SEASON_IMPRINT_TEXT.get(bonus_key, _sx(875))
        return _sx(701).format(bonus_key.replace(_sx(553), _sx(4)).title(), description)

    def _wheel_spin_action_label(self) -> str:
        if not self._leaderboard_is_authenticated():
            return _sx(878)
        spins_remaining = int(self._server_wheel_status.get(_sx(1600), 0) or 0)
        if spins_remaining <= 0:
            return _sx(879)
        return _sx(702)

    def _refresh_wheel_menu_labels(self) -> None:
        items = [MenuItem(self._wheel_status_label(), _sx(1175)), MenuItem(self._season_imprint_status_label(), _sx(1175)), MenuItem(self._wheel_spin_action_label(), _sx(1176))]
        for item_key in SPECIAL_ITEM_ORDER:
            owned = self._special_item_owned_count(item_key)
            if owned <= 0:
                continue
            items.append(MenuItem(self._special_item_loadout_label(item_key), _sx(1602).format(item_key)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.wheel_menu.title = _sx(703)
        self.wheel_menu.items = items

    def _practice_speed_scaling_option_label(self) -> str:
        return _sx(704).format(_sx(1598) if self._practice_speed_scaling_enabled() else _sx(1599))

    def _practice_hazard_target_option_label(self) -> str:
        return _sx(705).format(self._practice_hazard_target_setting())

    def _build_loadout_menu_items(self) -> list[MenuItem]:
        if self._pending_practice_setup:
            return [MenuItem(self._practice_hazard_target_option_label(), _sx(1110)), MenuItem(self._practice_speed_scaling_option_label(), _sx(1378)), MenuItem(_sx(1603), _sx(1379)), MenuItem(TEXT[_sx(429)], _sx(429))]
        items = [MenuItem(self._loadout_board_label(), _sx(1177)), MenuItem(self._headstart_option_label(), _sx(1178)), MenuItem(self._score_booster_option_label(), _sx(1179))]
        if self._leaderboard_is_authenticated():
            for item_key in SPECIAL_ITEM_ORDER:
                if self._special_item_owned_count(item_key) <= 0:
                    continue
                items.append(MenuItem(self._special_item_loadout_label(item_key), _sx(1785).format(item_key)))
        items.extend([MenuItem(_sx(1604), _sx(1379)), MenuItem(TEXT[_sx(429)], _sx(429))])
        return items

    def _events_menu_title(self) -> str:
        event = current_daily_event()
        event_coins = int(self.settings.get(_sx(352), {}).get(_sx(597), 0) or 0)
        return _sx(706).format(event.label, event_coins)

    def _event_shop_title(self) -> str:
        return _sx(707).format(self._event_coin_balance())

    def _event_coin_balance(self) -> int:
        return int(self.settings.get(_sx(352), {}).get(_sx(597), 0) or 0)

    def _event_shop_character_offer_key(self) -> str | None:
        event_candidates = [definition for definition in character_definitions() if definition.key in EVENT_CHARACTER_OFFER_KEYS and (not character_unlocked(self.settings, definition.key))]
        if event_candidates:
            return event_candidates[date.today().toordinal() % len(event_candidates)].key
        featured_key = featured_character_key()
        if not character_unlocked(self.settings, featured_key):
            return featured_key
        locked = [definition for definition in character_definitions() if not character_unlocked(self.settings, definition.key)]
        if not locked:
            return None
        return locked[date.today().toordinal() % len(locked)].key

    def _event_shop_board_offer_key(self) -> str | None:
        seasonal_rotation = [definition for definition in board_definitions() if definition.unlock_cost > 0]
        if not seasonal_rotation:
            return None
        seasonal_key = seasonal_rotation[date.today().toordinal() % len(seasonal_rotation)].key
        if not board_unlocked(self.settings, seasonal_key):
            return seasonal_key
        locked = [definition for definition in seasonal_rotation if not board_unlocked(self.settings, definition.key)]
        if not locked:
            return None
        return locked[date.today().toordinal() % len(locked)].key

    def _event_shop_character_offer_cost(self, key: str) -> int:
        return max(20, int(round(character_definition(key).unlock_cost / 130)))

    def _event_shop_board_offer_cost(self, key: str) -> int:
        return max(18, int(round(board_definition(key).unlock_cost / 120)))

    def _event_shop_character_label(self) -> str:
        key = self._event_shop_character_offer_key()
        if key is None:
            return _sx(885)
        definition = character_definition(key)
        cost = self._event_shop_character_offer_cost(key)
        status = _sx(886) if character_unlocked(self.settings, key) else _sx(887).format(cost)
        return _sx(708).format(definition.name, status)

    def _event_shop_board_label(self) -> str:
        key = self._event_shop_board_offer_key()
        if key is None:
            return _sx(889)
        definition = board_definition(key)
        cost = self._event_shop_board_offer_cost(key)
        status = _sx(886) if board_unlocked(self.settings, key) else _sx(887).format(cost)
        return _sx(709).format(definition.name, status)

    def _event_shop_key_label(self) -> str:
        return _sx(710).format(EVENT_SHOP_KEY_COST, int(self.settings.get(_sx(334), 0)))

    def _event_shop_hoverboard_label(self) -> str:
        return _sx(711).format(EVENT_SHOP_HOVERBOARD_PACK_COST, int(self.settings.get(_sx(335), 0)))

    def _event_shop_headstart_label(self) -> str:
        return _sx(712).format(EVENT_SHOP_HEADSTART_COST, int(self.settings.get(_sx(336), 0)))

    def _event_shop_score_booster_label(self) -> str:
        return _sx(713).format(EVENT_SHOP_SCORE_BOOSTER_COST, int(self.settings.get(_sx(337), 0)))

    def _event_shop_super_box_label(self) -> str:
        return _sx(714).format(EVENT_SHOP_SUPER_BOX_COST)

    def _daily_event_info_label(self) -> str:
        event = current_daily_event()
        tomorrow = tomorrow_daily_event()
        featured_key = featured_character_key()
        if event.key == _sx(624):
            featured_name = character_definition(featured_key).name
            return _sx(896).format(event.label, featured_name, tomorrow.label)
        return _sx(715).format(event.label, tomorrow.label)

    def _daily_high_score_status_label(self) -> str:
        total = int(self.settings.get(_sx(352), {}).get(_sx(600), 0) or 0)
        next_threshold = next_daily_high_score_threshold(self.settings)
        if next_threshold is None:
            return _sx(899).format(total)
        return _sx(716).format(total, next_threshold)

    def _daily_high_score_action_label(self) -> str:
        if can_claim_daily_high_score_reward(self.settings):
            return _sx(902)
        next_threshold = next_daily_high_score_threshold(self.settings)
        if next_threshold is None:
            return _sx(903)
        return _sx(717).format(next_threshold)

    def _coin_meter_status_label(self) -> str:
        coins = int(self.settings.get(_sx(352), {}).get(_sx(603), 0) or 0)
        next_threshold = next_coin_meter_threshold(self.settings)
        if next_threshold is None:
            return _sx(905).format(coins)
        return _sx(718).format(coins, next_threshold)

    def _coin_meter_action_label(self) -> str:
        if can_claim_coin_meter_reward(self.settings):
            return _sx(907)
        next_threshold = next_coin_meter_threshold(self.settings)
        if next_threshold is None:
            return _sx(908)
        return _sx(719).format(next_threshold)

    def _login_calendar_status_label(self) -> str:
        next_day = login_calendar_next_day(self.settings)
        availability = _sx(910) if login_calendar_available(self.settings) else _sx(911)
        return _sx(720).format(next_day, availability)

    def _login_calendar_action_label(self) -> str:
        if login_calendar_available(self.settings):
            return _sx(914).format(login_calendar_next_day(self.settings))
        return _sx(721)

    def _word_hunt_status_label(self) -> str:
        active_word = active_word_for_settings(self.settings)
        collected = len(active_word) - len(self._remaining_word_letters())
        return _sx(722).format(active_word, collected, len(active_word))

    def _season_hunt_status_label(self) -> str:
        total = int(self.settings.get(_sx(347), 0) or 0)
        next_threshold = next_season_reward_threshold(self.settings)
        if next_threshold is None:
            return _sx(917).format(total)
        return _sx(723).format(total, next_threshold)

    def _missions_hub_title(self) -> str:
        completed = len(completed_mission_metrics(self.settings))
        return _sx(724).format(int(self.settings.get(_sx(339), 1)), completed)

    def _mission_set_menu_title(self) -> str:
        return _sx(725).format(int(self.settings.get(_sx(339), 1)))

    def _me_menu_title(self) -> str:
        return _sx(726).format(selected_character_definition(self.settings).name, selected_board_definition(self.settings).name)

    def _board_menu_title(self) -> str:
        active_board = selected_board_definition(self.settings)
        return _sx(727).format(active_board.name)

    def _board_list_item_label(self, key: str) -> str:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            return _sx(925).format(definition.name, definition.unlock_cost)
        status = _sx(926) if selected_board_definition(self.settings).key == definition.key else _sx(927)
        return _sx(728).format(definition.name, status, definition.power_label)

    def _board_status_label(self, key: str) -> str:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            return _sx(928).format(definition.unlock_cost)
        status = _sx(926) if selected_board_definition(self.settings).key == definition.key else _sx(927)
        return _sx(729).format(status)

    def _board_power_label(self, key: str) -> str:
        definition = board_definition(key)
        return _sx(730).format(definition.power_label, definition.description)

    def _board_action_label(self, key: str) -> str:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            return _sx(931).format(definition.unlock_cost)
        if selected_board_definition(self.settings).key == definition.key:
            return _sx(932)
        return _sx(731)

    def _collection_menu_title(self) -> str:
        completed = len(completed_collection_keys(self.settings))
        total = len(collection_definitions())
        return _sx(732).format(completed, total)

    def _collection_item_label(self, key: str) -> str:
        definition = next((item for item in collection_definitions() if item.key == key))
        owned, total = collection_progress(self.settings, definition)
        status = _sx(934) if key in completed_collection_keys(self.settings) else _sx(935)
        return _sx(733).format(definition.name, status, owned, total, collection_bonus_summary(definition))

    def _quest_menu_title(self) -> str:
        return _sx(734).format(quest_sneakers(self.settings))

    def _quest_item_label(self, quest_key: str) -> str:
        quest = next((item for item in daily_quests() + seasonal_quests() if item.key == quest_key))
        progress = min(quest_progress(self.settings, quest), quest.target)
        status = _sx(937) if quest_claimed(self.settings, quest) else _sx(1189) if quest_completed(self.settings, quest) else _sx(926)
        scope_label = _sx(938) if quest.scope == _sx(1190) else _sx(939)
        return _sx(735).format(scope_label, quest.label, progress, quest.target, status, quest.sneaker_reward)

    def _quest_meter_label(self) -> str:
        next_threshold = next_meter_threshold(self.settings)
        if next_threshold is None:
            return _sx(941).format(quest_sneakers(self.settings))
        return _sx(736).format(quest_sneakers(self.settings), next_threshold)

    def _quest_meter_action_label(self) -> str:
        if can_claim_meter_reward(self.settings):
            return _sx(943)
        next_threshold = next_meter_threshold(self.settings)
        if next_threshold is None:
            return _sx(944)
        return _sx(737).format(next_threshold)

    def _mission_goal_item_label(self, goal) -> str:
        progress = int(self.settings.get(_sx(341), {}).get(goal.metric, 0) or 0)
        visible_progress = min(progress, goal.target)
        status = _sx(946) if progress >= goal.target else _sx(926)
        return _sx(738).format(goal.label, visible_progress, goal.target, status)

    def _daily_progress_reset_label(self) -> str:
        return _sx(739)

    def _item_upgrade_menu_title(self) -> str:
        maxed = sum((1 for definition in item_upgrade_definitions() if item_upgrade_level(self.settings, definition.key) >= definition.max_level))
        return _sx(696).format(maxed, len(item_upgrade_definitions()))

    def _item_upgrade_list_item_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        level = item_upgrade_level(self.settings, definition.key)
        duration = item_upgrade_duration(self.settings, definition.key)
        return _sx(740).format(definition.name, level, definition.max_level, self._format_duration_seconds(duration))

    def _item_upgrade_status_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        level = item_upgrade_level(self.settings, definition.key)
        return _sx(741).format(level, definition.max_level)

    def _item_upgrade_effect_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        current_duration = item_upgrade_duration(self.settings, definition.key)
        next_cost = next_item_upgrade_cost(self.settings, definition.key)
        if next_cost is None:
            return _sx(949).format(definition.description, self._format_duration_seconds(current_duration))
        next_level = item_upgrade_level(self.settings, definition.key) + 1
        next_duration = float(definition.durations[next_level])
        return _sx(742).format(definition.description, self._format_duration_seconds(current_duration), self._format_duration_seconds(next_duration))

    def _item_upgrade_action_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        next_cost = next_item_upgrade_cost(self.settings, definition.key)
        if next_cost is None:
            return _sx(953)
        next_level = item_upgrade_level(self.settings, definition.key) + 1
        return _sx(743).format(next_level, next_cost)

    def _character_menu_title(self) -> str:
        active_character = selected_character_definition(self.settings)
        return _sx(697).format(active_character.name)

    def _character_list_item_label(self, key: str) -> str:
        definition = character_definition(key)
        if not character_unlocked(self.settings, key):
            return _sx(925).format(definition.name, definition.unlock_cost)
        level = character_level(self.settings, key)
        active_status = _sx(926) if selected_character_definition(self.settings).key == key else _sx(927)
        return _sx(744).format(definition.name, active_status, level, definition.max_level, character_perk_summary(definition, level))

    def _character_status_label(self, key: str) -> str:
        definition = character_definition(key)
        if not character_unlocked(self.settings, key):
            return _sx(928).format(definition.unlock_cost)
        level = character_level(self.settings, key)
        active_status = _sx(926) if selected_character_definition(self.settings).key == key else _sx(927)
        return _sx(745).format(active_status, level, definition.max_level)

    def _character_perk_label(self, key: str) -> str:
        definition = character_definition(key)
        level = character_level(self.settings, key)
        return _sx(746).format(character_perk_summary(definition, level))

    def _character_primary_action_label(self, key: str) -> str:
        definition = character_definition(key)
        if not character_unlocked(self.settings, key):
            return _sx(958).format(definition.unlock_cost)
        if selected_character_definition(self.settings).key == key:
            return _sx(959)
        return _sx(747)

    def _character_upgrade_action_label(self, key: str) -> str:
        if not character_unlocked(self.settings, key):
            return _sx(960)
        definition = character_definition(key)
        next_cost = next_character_upgrade_cost(self.settings, key)
        if next_cost is None:
            return _sx(953)
        next_level = character_level(self.settings, key) + 1
        return _sx(743).format(next_level, next_cost)

    def _refresh_options_menu_labels(self) -> None:
        selected_action = _sx(2)
        if self.options_menu.items:
            selected_action = self.options_menu.items[min(self.options_menu.index, len(self.options_menu.items) - 1)].action
        self.options_menu.items = self._build_options_menu_items()
        if selected_action:
            self.options_menu.index = self._update_option_index(selected_action)

    def _build_options_menu_items(self) -> list[MenuItem]:
        items = [MenuItem(self._sfx_option_label(), _sx(1114)), MenuItem(self._music_option_label(), _sx(1115)), MenuItem(self._updates_option_label(), _sx(1116)), MenuItem(self._audio_output_option_label(), _sx(1117)), MenuItem(self._menu_sound_hrtf_option_label(), _sx(1118)), MenuItem(self._menu_wrap_option_label(), _sx(1119)), MenuItem(self._speech_option_label(), _sx(1120)), MenuItem(self._sapi_menu_entry_label(), _sx(1194)), MenuItem(self._difficulty_option_label(), _sx(1126)), MenuItem(self._main_menu_description_option_label(), _sx(1127)), MenuItem(self._leaderboard_account_option_label(), _sx(1195))]
        if self._leaderboard_is_authenticated():
            items.append(MenuItem(self._leaderboard_logout_option_label(), _sx(1382)))
        items.extend([MenuItem(_sx(809), _sx(1383)), MenuItem(_sx(754), _sx(1384)), MenuItem(self._purchase_confirmation_option_label(), _sx(1129)), MenuItem(self._exit_confirmation_option_label(), _sx(1128)), MenuItem(TEXT[_sx(429)], _sx(429))])
        return items

    def _refresh_announcements_menu_labels(self) -> None:
        self.announcements_menu.items[0].label = self._meter_option_label()
        self.announcements_menu.items[1].label = self._coin_counter_option_label()
        self.announcements_menu.items[2].label = self._quest_changes_option_label()
        self.announcements_menu.items[3].label = self._pause_on_focus_loss_option_label()

    def _refresh_sapi_menu_labels(self) -> None:
        self.sapi_menu.items[0].label = self._sapi_speech_option_label()
        self.sapi_menu.items[1].label = self._sapi_volume_option_label()
        self.sapi_menu.items[2].label = self._sapi_voice_option_label()
        self.sapi_menu.items[3].label = self._sapi_rate_option_label()
        self.sapi_menu.items[4].label = self._sapi_pitch_option_label()

    def _refresh_loadout_menu_labels(self) -> None:
        selected_action = _sx(2)
        if self.loadout_menu.items:
            selected_action = self.loadout_menu.items[min(self.loadout_menu.index, len(self.loadout_menu.items) - 1)].action
        self.loadout_menu.title = self._loadout_title()
        self.loadout_menu.items = self._build_loadout_menu_items()
        if selected_action:
            self.loadout_menu.index = self._menu_index_for_action(self.loadout_menu, selected_action)

    def _refresh_revive_menu_label(self) -> None:
        self.revive_menu.items[0].label = self._revive_option_label()

    def _refresh_game_over_menu(self) -> None:
        summary = self._game_over_summary
        self.game_over_menu.items[0].label = _sx(748).format(int(summary[_sx(968)]))
        self.game_over_menu.items[1].label = _sx(666).format(int(summary[_sx(363)]))
        self.game_over_menu.items[2].label = _sx(749).format(format_play_time(summary[_sx(969)]))
        self.game_over_menu.items[3].label = _sx(750).format(summary[_sx(970)])
        run_again_index = self._menu_index_for_action(self.game_over_menu, _sx(964))
        main_menu_index = self._menu_index_for_action(self.game_over_menu, _sx(965))
        self.game_over_menu.items[run_again_index].label = _sx(751)
        self.game_over_menu.items[main_menu_index].label = _sx(752)

    @staticmethod
    def _empty_run_stats() -> dict[str, object]:
        return {_sx(364): 0, _sx(365): 0, _sx(366): 0, _sx(367): 0, _sx(368): 0, _sx(966): 0, _sx(967): {key: 0 for key in RUN_POWERUP_LABELS}}

    def _empty_game_over_summary(self) -> dict[str, object]:
        return {_sx(968): 0, _sx(363): 0, _sx(969): 0, _sx(970): _sx(661), _sx(971): APP_VERSION, _sx(318): self._difficulty_key(), _sx(972): 0, _sx(966): 0, _sx(973): 0, _sx(967): {}}

    def _record_run_metric(self, metric: str, amount: int=1) -> None:
        if amount <= 0:
            return
        current_value = int(self._active_run_stats.get(metric, 0) or 0)
        self._active_run_stats[metric] = current_value + int(amount)
        if self._practice_mode_active:
            return
        for quest in record_quest_metric(self.settings, metric, amount):
            if self._quest_changes_enabled():
                self.audio.play(_sx(100), channel=_sx(180))
                self.speaker.speak(_sx(1358).format(quest.label), interrupt=False)

    def _record_run_powerup(self, powerup_key: str, amount: int=1) -> None:
        if amount <= 0:
            return
        usage = self._active_run_stats.get(_sx(967))
        if not isinstance(usage, dict):
            usage = {key: 0 for key in RUN_POWERUP_LABELS}
            self._active_run_stats[_sx(967)] = usage
        normalized_key = str(powerup_key or _sx(2)).strip().lower()
        if normalized_key not in RUN_POWERUP_LABELS:
            return
        usage[normalized_key] = int(usage.get(normalized_key, 0) or 0) + int(amount)

    @staticmethod
    def _compact_powerup_usage(powerup_usage: object) -> dict[str, int]:
        if not isinstance(powerup_usage, dict):
            return {}
        compact: dict[str, int] = {}
        for key in RUN_POWERUP_LABELS:
            amount = int(powerup_usage.get(key, 0) or 0)
            if amount > 0:
                compact[key] = amount
        return compact

    def _powerup_usage_label(self, powerup_usage: object) -> str:
        normalized_usage = self._compact_powerup_usage(powerup_usage)
        if not normalized_usage:
            return _sx(974)
        segments = [_sx(3).format(RUN_POWERUP_LABELS[key], normalized_usage[key]) for key in RUN_POWERUP_LABELS if key in normalized_usage]
        return _sx(975) + _sx(996).join(segments)

    def _refresh_shop_menu_labels(self) -> None:
        self.shop_menu.title = self._shop_title()
        self.shop_menu.items[0].label = self._shop_hoverboard_label()
        self.shop_menu.items[1].label = self._shop_box_label()
        self.shop_menu.items[2].label = self._shop_headstart_label()
        self.shop_menu.items[3].label = self._shop_score_booster_label()
        self.shop_menu.items[4].label = self._shop_daily_gift_label()
        self.shop_menu.items[5].label = self._shop_item_upgrade_label()
        self.shop_menu.items[6].label = self._shop_character_upgrade_label()

    def _refresh_item_upgrade_menu_labels(self) -> None:
        self.item_upgrade_menu.title = self._item_upgrade_menu_title()
        self.item_upgrade_menu.items = [MenuItem(self._item_upgrade_list_item_label(definition.key), _sx(1605).format(definition.key)) for definition in item_upgrade_definitions()] + [MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_item_upgrade_detail_menu_labels(self, key: str) -> None:
        definition = item_upgrade_definition(key)
        self._item_upgrade_detail_key = definition.key
        next_cost = next_item_upgrade_cost(self.settings, definition.key)
        upgrade_action = _sx(976).format(definition.key) if next_cost is not None else _sx(977).format(definition.key)
        self.item_upgrade_detail_menu.title = definition.name
        self.item_upgrade_detail_menu.items = [MenuItem(self._item_upgrade_status_label(definition.key), _sx(1198).format(definition.key)), MenuItem(self._item_upgrade_effect_label(definition.key), _sx(1199).format(definition.key)), MenuItem(self._item_upgrade_action_label(definition.key), upgrade_action), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_character_menu_labels(self) -> None:
        self.character_menu.title = self._character_menu_title()
        self.character_menu.items = [MenuItem(self._character_list_item_label(definition.key), _sx(1606).format(definition.key)) for definition in character_definitions()] + [MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_character_detail_menu_labels(self, key: str) -> None:
        definition = character_definition(key)
        self._character_detail_key = definition.key
        self.character_detail_menu.title = definition.name
        if not character_unlocked(self.settings, key):
            primary_action = _sx(978).format(definition.key)
        elif selected_character_definition(self.settings).key == definition.key:
            primary_action = _sx(1201).format(definition.key)
        else:
            primary_action = _sx(1202).format(definition.key)
        next_upgrade_cost = next_character_upgrade_cost(self.settings, key)
        if not character_unlocked(self.settings, key):
            upgrade_action = _sx(979).format(definition.key)
        elif next_upgrade_cost is None:
            upgrade_action = _sx(1204).format(definition.key)
        else:
            upgrade_action = _sx(1205).format(definition.key)
        self.character_detail_menu.items = [MenuItem(self._character_status_label(definition.key), _sx(1206).format(definition.key)), MenuItem(self._character_perk_label(definition.key), _sx(1207).format(definition.key)), MenuItem(self._character_primary_action_label(definition.key), primary_action), MenuItem(self._character_upgrade_action_label(definition.key), upgrade_action), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_board_menu_labels(self) -> None:
        self.board_menu.title = self._board_menu_title()
        self.board_menu.items = [MenuItem(self._board_list_item_label(definition.key), _sx(1607).format(definition.key)) for definition in board_definitions()] + [MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_board_detail_menu_labels(self, key: str) -> None:
        definition = board_definition(key)
        self._board_detail_key = definition.key
        self.board_detail_menu.title = definition.name
        if not board_unlocked(self.settings, definition.key):
            primary_action = _sx(980).format(definition.key)
        elif selected_board_definition(self.settings).key == definition.key:
            primary_action = _sx(1209).format(definition.key)
        else:
            primary_action = _sx(1210).format(definition.key)
        self.board_detail_menu.items = [MenuItem(self._board_status_label(definition.key), _sx(1211).format(definition.key)), MenuItem(self._board_power_label(definition.key), _sx(1212).format(definition.key)), MenuItem(self._board_action_label(definition.key), primary_action), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_collection_menu_labels(self) -> None:
        self.collection_menu.title = self._collection_menu_title()
        self.collection_menu.items = [MenuItem(self._collection_item_label(definition.key), _sx(1608).format(definition.key)) for definition in collection_definitions()] + [MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_events_menu_labels(self) -> None:
        ensure_event_state(self.settings)
        self.events_menu.title = self._events_menu_title()
        self.events_menu.items = [MenuItem(self._daily_event_info_label(), _sx(1213)), MenuItem(_sx(1214), _sx(1215)), MenuItem(self._daily_high_score_status_label(), _sx(1213)), MenuItem(self._daily_high_score_action_label(), _sx(1216)), MenuItem(self._coin_meter_status_label(), _sx(1213)), MenuItem(self._coin_meter_action_label(), _sx(1217)), MenuItem(_sx(1218).format(_sx(1189) if daily_gift_available(self.settings) else _sx(1852)), _sx(1213)), MenuItem(self._shop_daily_gift_label(), _sx(1219)), MenuItem(self._login_calendar_status_label(), _sx(1213)), MenuItem(self._login_calendar_action_label(), _sx(1220)), MenuItem(self._word_hunt_status_label(), _sx(1213)), MenuItem(self._season_hunt_status_label(), _sx(1213)), MenuItem(TEXT[_sx(429)], _sx(429))]
        self._refresh_event_shop_menu_labels()

    def _refresh_event_shop_menu_labels(self) -> None:
        self.event_shop_menu.title = self._event_shop_title()
        self.event_shop_menu.items = [MenuItem(self._event_shop_character_label(), _sx(1221)), MenuItem(self._event_shop_board_label(), _sx(1222)), MenuItem(self._event_shop_key_label(), _sx(1223)), MenuItem(self._event_shop_hoverboard_label(), _sx(1224)), MenuItem(self._event_shop_headstart_label(), _sx(1225)), MenuItem(self._event_shop_score_booster_label(), _sx(1226)), MenuItem(self._event_shop_super_box_label(), _sx(1227)), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _spend_event_coins(self, cost: int) -> bool:
        ensure_event_state(self.settings)
        safe_cost = max(1, int(cost))
        current = self._event_coin_balance()
        if current < safe_cost:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1228).format(safe_cost, current), interrupt=True)
            return False
        self.settings[_sx(352)][_sx(597)] = current - safe_cost
        self.audio.play(_sx(105), channel=_sx(180))
        return True

    def _buy_event_shop_character(self) -> None:
        offer_key = self._event_shop_character_offer_key()
        if offer_key is None:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1229), interrupt=True)
            return
        definition = character_definition(offer_key)
        if character_unlocked(self.settings, offer_key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1230).format(definition.name), interrupt=True)
            return
        cost = self._event_shop_character_offer_cost(offer_key)
        if not self._spend_event_coins(cost):
            return
        previous_completed = completed_collection_keys(self.settings)
        self.settings[_sx(240)][definition.key][_sx(239)] = True
        self._sync_character_progress()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()
        self._refresh_shop_menu_labels()
        self._refresh_events_menu_labels()
        self._persist_settings()
        self.audio.play(_sx(108), channel=_sx(1231))
        self.speaker.speak(_sx(981).format(definition.name), interrupt=True)
        self._announce_collection_unlocks(previous_completed)

    def _buy_event_shop_board(self) -> None:
        offer_key = self._event_shop_board_offer_key()
        if offer_key is None:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1233), interrupt=True)
            return
        definition = board_definition(offer_key)
        if board_unlocked(self.settings, offer_key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1230).format(definition.name), interrupt=True)
            return
        cost = self._event_shop_board_offer_cost(offer_key)
        if not self._spend_event_coins(cost):
            return
        previous_completed = completed_collection_keys(self.settings)
        self.settings[_sx(202)][definition.key][_sx(239)] = True
        self._sync_character_progress()
        self._refresh_board_menu_labels()
        self._refresh_board_detail_menu_labels(definition.key)
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()
        self._refresh_events_menu_labels()
        self._persist_settings()
        self.audio.play(_sx(108), channel=_sx(1231))
        self.speaker.speak(_sx(981).format(definition.name), interrupt=True)
        self._announce_collection_unlocks(previous_completed)

    def _buy_event_shop_reward(self, cost: int, reward: dict[str, object], source: str) -> None:
        if not self._spend_event_coins(cost):
            return
        if self._apply_meta_reward(reward, source):
            self._refresh_events_menu_labels()
            self._refresh_shop_menu_labels()
            self._persist_settings()

    def _refresh_missions_hub_menu_labels(self) -> None:
        ensure_quest_state(self.settings)
        self.missions_hub_menu.title = self._missions_hub_title()
        self.missions_hub_menu.items = [MenuItem(self._quest_menu_title(), _sx(1234)), MenuItem(self._mission_status_text(), _sx(1235)), MenuItem(self._achievements_menu_title(), _sx(1236)), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _refresh_mission_set_menu_labels(self) -> None:
        ensure_progression_state(self.settings)
        self.mission_set_menu.title = self._mission_set_menu_title()
        items = [MenuItem(self._mission_goal_item_label(goal), _sx(1237)) for goal in self._mission_goals()]
        items.append(MenuItem(_sx(1238).format(1 + int(self.settings.get(_sx(340), 0))), _sx(1237)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.mission_set_menu.items = items

    def _refresh_quest_menu_labels(self) -> None:
        ensure_quest_state(self.settings)
        self.quests_menu.title = self._quest_menu_title()
        items = [MenuItem(self._quest_meter_label(), _sx(1239)), MenuItem(self._quest_meter_action_label(), _sx(1240))]
        for quest in daily_quests():
            action = _sx(1241).format(quest.key) if quest_completed(self.settings, quest) and (not quest_claimed(self.settings, quest)) else _sx(1239)
            items.append(MenuItem(self._quest_item_label(quest.key), action))
        for quest in seasonal_quests():
            action = _sx(1241).format(quest.key) if quest_completed(self.settings, quest) and (not quest_claimed(self.settings, quest)) else _sx(1239)
            items.append(MenuItem(self._quest_item_label(quest.key), action))
        items.append(MenuItem(self._daily_progress_reset_label(), _sx(1242)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.quests_menu.items = items

    def _refresh_me_menu_labels(self) -> None:
        ensure_board_state(self.settings)
        ensure_collection_state(self.settings)
        self.me_menu.title = self._me_menu_title()
        completed = len(completed_collection_keys(self.settings))
        total = len(collection_definitions())
        self.me_menu.items = [MenuItem(self._character_menu_title(), _sx(1243)), MenuItem(self._board_menu_title(), _sx(1244)), MenuItem(self._item_upgrade_menu_title(), _sx(1245)), MenuItem(_sx(732).format(completed, total), _sx(1246)), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _howto_topics(self) -> tuple[HelpTopic, ...]:
        if self._showing_upgrade_help:
            return UPGRADE_HELP_TOPICS.get(APP_VERSION, ()) + HOW_TO_TOPICS
        return HOW_TO_TOPICS

    def _refresh_howto_menu_labels(self) -> None:
        self.howto_menu.title = self._howto_menu_title()
        self.howto_menu.items = [MenuItem(topic.label, _sx(1615).format(topic.key)) for topic in self._howto_topics()] + [MenuItem(TEXT[_sx(429)], _sx(429))]

    def _help_topic_for_key(self, key: str) -> HelpTopic | None:
        for topic in UPGRADE_HELP_TOPICS.get(APP_VERSION, ()):
            if topic.key == key:
                return topic
        for topic in HOW_TO_TOPICS:
            if topic.key == key:
                return topic
        return None

    @staticmethod
    def _format_duration_seconds(duration: float) -> str:
        return format_duration_seconds(duration)

    @staticmethod
    def _menu_index_for_action(menu: Menu, action: str) -> int:
        for index, item in enumerate(menu.items):
            if item.action == action:
                return index
        return 0

    def _open_help_topic(self, key: str) -> None:
        topic = self._help_topic_for_key(key)
        if topic is None:
            self._play_menu_feedback(_sx(52))
            return
        self._selected_help_topic = topic
        self.help_topic_menu.title = topic.label
        self.help_topic_menu.items = [MenuItem(segment, _sx(1395)) for segment in help_topic_segments(topic, self._gameplay_controls_summary())] + [MenuItem(_sx(1616), _sx(1396)), MenuItem(TEXT[_sx(429)], _sx(429))]
        self._set_active_menu(self.help_topic_menu)

    def _open_info_dialog(self, content: InfoDialogContent, menu: Menu) -> None:
        self._selected_info_dialog = content
        menu.title = content.title
        menu.items = [MenuItem(line, _sx(1395)) for line in content.lines] + [MenuItem(_sx(1616), _sx(1396)), MenuItem(TEXT[_sx(429)], _sx(429))]
        self._set_active_menu(menu)

    def _copy_menu_text(self, text: str, success_message: str) -> bool:
        if not text:
            self._play_menu_feedback(_sx(52))
            self.speaker.speak(_sx(1247), interrupt=True)
            return True
        if copy_text_to_clipboard(text):
            self._play_menu_feedback(_sx(56))
            self.speaker.speak(success_message, interrupt=True)
            return True
        self._play_menu_feedback(_sx(52))
        self.speaker.speak(_sx(982), interrupt=True)
        return True

    def _selected_info_menu_lines(self, menu: Menu) -> tuple[str, ...]:
        if menu == self.help_topic_menu and self._selected_help_topic is not None:
            return help_topic_segments(self._selected_help_topic, self._gameplay_controls_summary())
        if menu == self.whats_new_menu and self._selected_info_dialog is not None:
            return self._selected_info_dialog.lines
        if menu == self.issue_detail_menu and self._selected_issue_detail_content is not None:
            return self._selected_issue_detail_content.lines
        return ()

    def _selected_info_copy_all_text(self, menu: Menu) -> str:
        lines = self._selected_info_menu_lines(menu)
        if not lines:
            return _sx(2)
        return _sx(652).join((menu.title, _sx(2), *lines))

    @staticmethod
    def _selected_info_copy_all_message(menu: Menu) -> str:
        return _sx(753).format(menu.title)

    def _mark_current_version_seen(self) -> None:
        seen_version = str(self.settings.get(_sx(317), _sx(2)) or _sx(2)).strip()
        if not seen_version:
            self.settings[_sx(317)] = APP_VERSION
            return
        if version_key(APP_VERSION) <= version_key(seen_version):
            self.settings[_sx(317)] = APP_VERSION
            return
        self.settings[_sx(317)] = APP_VERSION

    def _achievement_item_label(self, key: str) -> str:
        progress = achievement_progress(self.settings)
        unlocked = set(self.settings.get(_sx(350), []))
        for achievement in achievement_definitions():
            if achievement.key != key:
                continue
            current = min(int(progress.get(achievement.metric, 0)), achievement.target)
            status = _sx(927) if key in unlocked else _sx(1248).format(current, achievement.target)
            return _sx(788).format(achievement.label, status)
        return key

    def _refresh_achievements_menu_labels(self) -> None:
        self.achievements_menu.title = self._achievements_menu_title()
        self.achievements_menu.items = [MenuItem(self._achievement_item_label(achievement.key), _sx(1617).format(achievement.key)) for achievement in achievement_definitions()] + [MenuItem(TEXT[_sx(429)], _sx(429))]

    def _announce_achievement_unlocks(self) -> None:
        unlocks = newly_unlocked_achievements(self.settings)
        if not unlocks:
            return
        self.audio.play(_sx(108), channel=_sx(180))
        for achievement in unlocks:
            self.speaker.speak(_sx(1249).format(achievement.label), interrupt=False)
        self._refresh_achievements_menu_labels()

    def _record_achievement_metric(self, metric: str, amount: int=1) -> None:
        record_achievement_progress(self.settings, metric, amount)
        self._announce_achievement_unlocks()

    def _record_achievement_max(self, metric: str, value: int) -> None:
        set_achievement_progress_max(self.settings, metric, value)
        self._announce_achievement_unlocks()

    def _announce_collection_unlocks(self, previous_completed: tuple[str, ...]) -> None:
        current_completed = completed_collection_keys(self.settings)
        new_keys = [key for key in current_completed if key not in previous_completed]
        if not new_keys:
            return
        self.settings[_sx(300)] = list(current_completed)
        self.audio.play(_sx(108), channel=_sx(180))
        self.audio.play(_sx(100), channel=_sx(1250))
        for key in new_keys:
            definition = next((item for item in collection_definitions() if item.key == key))
            self.speaker.speak(_sx(1251).format(definition.name, collection_bonus_summary(definition)), interrupt=False)
        self._sync_character_progress()
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()

    def _build_controls_menu(self) -> None:
        self._sync_selected_binding_device()
        items = [MenuItem(_sx(1252).format(self.controls.current_input_label()), _sx(1253)), MenuItem(_sx(1254).format(self._selected_binding_profile_label()), _sx(984)), MenuItem(_sx(1255), _sx(1256)), MenuItem(_sx(1257).format(self._selected_binding_profile_label()), _sx(1258))]
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.controls_menu.items = items
        self.controls_menu.title = _sx(754)

    def _sync_selected_binding_device(self) -> None:
        if self.controls.active_controller() is None:
            self._selected_binding_device = _sx(563)
            return
        if self._selected_binding_device not in {_sx(563), _sx(565)}:
            self._selected_binding_device = _sx(565)
            return
        if self.controls.last_input_source == _sx(565):
            self._selected_binding_device = _sx(565)

    def _selected_binding_profile_label(self) -> str:
        if self._selected_binding_device == _sx(565) and self.controls.active_controller() is not None:
            return family_label(self.controls.current_controller_family())
        return _sx(573)

    def _cycle_selected_binding_device(self, direction: int) -> None:
        if direction not in (-1, 1):
            return
        available_devices = [_sx(563)]
        if self.controls.active_controller() is not None:
            available_devices.append(_sx(565))
        if len(available_devices) == 1:
            self._play_menu_feedback(_sx(52))
            return
        try:
            current_index = available_devices.index(self._selected_binding_device)
        except ValueError:
            current_index = 0
        self._selected_binding_device = available_devices[(current_index + direction) % len(available_devices)]
        self._play_menu_feedback(_sx(56))
        self._build_controls_menu()
        profile_index = self._menu_index_for_action(self.controls_menu, _sx(984))
        self.speaker.speak(self.controls_menu.items[profile_index].label, interrupt=True)

    def _build_keyboard_bindings_menu(self) -> None:
        items = []
        for action_key in KEYBOARD_ACTION_ORDER:
            label = action_label(action_key)
            bound_key = self.controls.keyboard_binding_for_action(action_key)
            binding = keyboard_binding_label(bound_key)
            items.append(MenuItem(_sx(564).format(label, binding), _sx(1623).format(action_key)))
        items.append(MenuItem(_sx(1259), _sx(1260)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.keyboard_bindings_menu.items = items
        keyboard_layout_name = str(self.settings.get(_sx(360), _sx(2)) or _sx(2)).strip()
        self.keyboard_bindings_menu.title = _sx(985).format(keyboard_layout_name) if keyboard_layout_name else _sx(815)

    def _build_controller_bindings_menu(self) -> None:
        family = self.controls.current_controller_family()
        items = []
        for action_key in CONTROLLER_ACTION_ORDER:
            label = action_label(action_key)
            binding = controller_binding_label(self.controls.controller_binding_for_action(action_key, family), family)
            items.append(MenuItem(_sx(564).format(label, binding), _sx(1624).format(action_key)))
        items.append(MenuItem(_sx(1263), _sx(1264)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.controller_bindings_menu.items = items
        self.controller_bindings_menu.title = _sx(755).format(family_label(family))

    def _refresh_control_menus(self) -> None:
        self._build_controls_menu()
        self._build_keyboard_bindings_menu()
        self._build_controller_bindings_menu()

    def _current_learn_sound_entry(self) -> LearnSoundEntry | None:
        if self.active_menu != self.learn_sounds_menu:
            return None
        if self.learn_sounds_menu.index >= len(LEARN_SOUND_LIBRARY):
            return None
        return LEARN_SOUND_LIBRARY[self.learn_sounds_menu.index]

    def _refresh_learn_sound_description(self) -> None:
        entry = self._current_learn_sound_entry()
        if entry is None:
            self._learn_sound_description = _sx(987)
            return
        self._learn_sound_description = entry.description

    def _stop_learn_sound_preview(self) -> None:
        self._learn_sound_preview_timer = 0.0
        self.audio.stop(LEARN_SOUND_PREVIEW_CHANNEL)

    def _start_headstart_audio(self) -> None:
        if self.player.headstart <= 0:
            return
        self.audio.play(_sx(103), loop=True, channel=HEADSTART_SHAKE_CHANNEL, gain=0.84)
        self.audio.play(_sx(104), loop=True, channel=HEADSTART_SPRAY_CHANNEL, gain=0.92)

    def _stop_headstart_audio(self) -> None:
        self.audio.stop(HEADSTART_SHAKE_CHANNEL)
        self.audio.stop(HEADSTART_SPRAY_CHANNEL)

    def _play_learn_sound_preview(self, entry: LearnSoundEntry) -> None:
        self._stop_learn_sound_preview()
        self._learn_sound_description = entry.description
        self.audio.play(entry.key, loop=entry.loop, channel=LEARN_SOUND_PREVIEW_CHANNEL, gain=entry.gain)
        if entry.loop:
            self._learn_sound_preview_timer = LEARN_SOUND_LOOP_PREVIEW_DURATION
        self.speaker.speak(_sx(988).format(entry.label, entry.description), interrupt=True)

    def _update_learn_sound_preview(self, delta_time: float) -> None:
        if self._learn_sound_preview_timer <= 0:
            return
        self._learn_sound_preview_timer = max(0.0, self._learn_sound_preview_timer - delta_time)
        if self._learn_sound_preview_timer <= 0:
            self.audio.stop(LEARN_SOUND_PREVIEW_CHANNEL)

    def _play_menu_feedback(self, key: str) -> None:
        if self.active_menu is not None:
            self.active_menu.play_feedback(key)
            return
        self.audio.play(key, channel=_sx(180))

    def _update_option_index(self, action: str) -> int:
        for index, item in enumerate(self.options_menu.items):
            if item.action == action:
                return index
        return 0

    def _update_announcements_index(self, action: str) -> int:
        for index, item in enumerate(self.announcements_menu.items):
            if item.action == action:
                return index
        return 0

    def _meters_enabled(self) -> bool:
        return bool(self.settings.get(_sx(321), False))

    def _coin_counters_enabled(self) -> bool:
        return bool(self.settings.get(_sx(322), False))

    def _quest_changes_enabled(self) -> bool:
        return bool(self.settings.get(_sx(323), False))

    def _pause_on_focus_loss_enabled(self) -> bool:
        return bool(self.settings.get(_sx(324), True))

    def _practice_speed_scaling_enabled(self) -> bool:
        return bool(self.settings.get(_sx(325), False))

    def _practice_hazard_target_setting(self) -> int:
        try:
            target_value = int(self.settings.get(_sx(326), PRACTICE_TARGET_HAZARDS))
        except (TypeError, ValueError):
            target_value = PRACTICE_TARGET_HAZARDS
        return max(PRACTICE_TARGET_HAZARDS_MIN, min(PRACTICE_TARGET_HAZARDS_MAX, target_value))

    def _main_menu_descriptions_enabled(self) -> bool:
        return bool(self.settings.get(_sx(327), True))

    def _exit_confirmation_enabled(self) -> bool:
        return bool(self.settings.get(_sx(328), True))

    def _purchase_confirmation_enabled(self) -> bool:
        return bool(self.settings.get(_sx(329), True))

    def _main_menu_items(self) -> list[MenuItem]:
        return [MenuItem(_sx(1265), _sx(430), _sx(1266)), MenuItem(_sx(1267), _sx(1268), _sx(1269)), MenuItem(_sx(803), _sx(1270), _sx(1271)), MenuItem(_sx(805), _sx(1272), _sx(1273)), MenuItem(_sx(808), _sx(1274), _sx(1275)), MenuItem(_sx(665), _sx(1276), _sx(1277)), MenuItem(_sx(811), _sx(1278), _sx(1279)), MenuItem(_sx(703), _sx(99), _sx(1280)), MenuItem(_sx(813), _sx(1281), _sx(1282)), MenuItem(_sx(820), _sx(1283), _sx(1284)), MenuItem(_sx(479), _sx(1285), _sx(1286)), MenuItem(_sx(818), _sx(1287), _sx(1288)), MenuItem(_sx(817), _sx(1289), _sx(1290)), MenuItem(_sx(1291), _sx(1292), _sx(1293)), MenuItem(_sx(1294), _sx(768), _sx(1295))]

    def _selected_main_menu_description(self) -> str:
        if self.active_menu != self.main_menu or not self._main_menu_descriptions_enabled() or (not self.main_menu.items):
            return _sx(2)
        return self.main_menu.items[self.main_menu.index].description.strip()

    def _refresh_update_menu(self, result: UpdateCheckResult) -> None:
        latest_version = result.latest_version or _sx(989)
        if self.packaged_build:
            self.update_menu.title = _sx(990).format(APP_VERSION, latest_version)
            self._update_status_message = _sx(991).format(APP_VERSION, latest_version)
        else:
            self.update_menu.title = _sx(992).format(APP_VERSION, latest_version)
            self._update_status_message = _sx(993).format(APP_VERSION, latest_version)
        self._update_release_notes = result.release.notes.strip() if result.release is not None and result.release.notes.strip() else _sx(657)
        self._update_progress_percent = 0.0
        self._update_progress_message = _sx(2)
        self._update_progress_stage = _sx(658)
        self._update_progress_announced_bucket = -1
        self._update_install_thread = None
        self._update_install_result = None
        self._update_restart_script_path = None
        self._update_install_error = _sx(2)
        self._update_ready_announced = False
        has_zip_package = self.packaged_build and bool(result.release and self.updater.has_installable_package(result.release))
        self.update_menu.items[0].label = _sx(994) if has_zip_package else _sx(756)
        self.update_menu.items[0].action = _sx(995) if has_zip_package else _sx(757)
        self.update_menu.items[1].label = _sx(756)
        self.update_menu.items[1].action = _sx(757)
        self.update_menu.items[2].label = _sx(489) if not self.packaged_build else _sx(767)
        self.update_menu.items[2].action = _sx(429) if not self.packaged_build else _sx(768)

    def _menu_navigation_hint(self) -> str:
        up = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(517)))
        down = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(520)))
        confirm = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(523)))
        back = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(526)))
        if self.controls.last_input_source == _sx(565) and self.controls.active_controller() is not None:
            family = self.controls.current_controller_family()
            up = controller_binding_label(self.controls.controller_binding_for_action(_sx(517), family), family)
            down = controller_binding_label(self.controls.controller_binding_for_action(_sx(520), family), family)
            confirm = controller_binding_label(self.controls.controller_binding_for_action(_sx(523), family), family)
            back = controller_binding_label(self.controls.controller_binding_for_action(_sx(526), family), family)
        return _sx(758).format(up, down, confirm, back)

    def _option_adjustment_hint(self) -> str:
        decrease = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(528)))
        increase = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(531)))
        if self.controls.last_input_source == _sx(565) and self.controls.active_controller() is not None:
            family = self.controls.current_controller_family()
            decrease = controller_binding_label(self.controls.controller_binding_for_action(_sx(528), family), family)
            increase = controller_binding_label(self.controls.controller_binding_for_action(_sx(531), family), family)
        return _sx(759).format(decrease, increase)

    def _gameplay_controls_summary(self) -> str:
        move_left = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(534)))
        move_right = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(537)))
        jump = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(540)))
        roll = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(542)))
        hoverboard = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(544)))
        pause = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(547)))
        speech = keyboard_binding_label(self.controls.keyboard_binding_for_action(_sx(550)))
        if self.controls.last_input_source == _sx(565) and self.controls.active_controller() is not None:
            family = self.controls.current_controller_family()
            move_left = controller_binding_label(self.controls.controller_binding_for_action(_sx(534), family), family)
            move_right = controller_binding_label(self.controls.controller_binding_for_action(_sx(537), family), family)
            jump = controller_binding_label(self.controls.controller_binding_for_action(_sx(540), family), family)
            roll = controller_binding_label(self.controls.controller_binding_for_action(_sx(542), family), family)
            hoverboard = controller_binding_label(self.controls.controller_binding_for_action(_sx(544), family), family)
            pause = controller_binding_label(self.controls.controller_binding_for_action(_sx(547), family), family)
            speech = controller_binding_label(self.controls.controller_binding_for_action(_sx(550), family), family)
        return _sx(760).format(move_left, move_right, jump, roll, hoverboard, pause, speech)

    def _open_mandatory_update_menu(self, result: UpdateCheckResult) -> None:
        self._latest_update_result = result
        self._refresh_update_menu(result)
        self._set_active_menu(self.update_menu)
        self.speaker.speak(self._update_status_message, interrupt=True)

    def _show_startup_status(self, message: str) -> None:
        try:
            width, height = self.screen.get_size()
            self.screen.fill((10, 10, 15))
            title_surface = self.big.render(_sx(1303), True, (240, 240, 240))
            message_surface = self.font.render(str(message or _sx(2)).strip() or _sx(1169), True, (205, 205, 205))
            title_rect = title_surface.get_rect(center=(width // 2, max(72, height // 2 - 30)))
            message_rect = message_surface.get_rect(center=(width // 2, min(height - 48, height // 2 + 18)))
            self.screen.blit(title_surface, title_rect)
            self.screen.blit(message_surface, message_rect)
            pygame.display.flip()
            pygame.event.pump()
        except pygame.error:
            return

    def _begin_update_install(self) -> None:
        if not self.packaged_build:
            release = self._latest_update_result.release if self._latest_update_result is not None else None
            opened = self.updater.open_release_page(release)
            if opened:
                self.speaker.speak(_sx(1625), interrupt=True)
            else:
                self._play_menu_feedback(_sx(52))
                self.speaker.speak(_sx(1626), interrupt=True)
            return
        release = self._latest_update_result.release if self._latest_update_result is not None else None
        if release is None:
            self._play_menu_feedback(_sx(52))
            self.speaker.speak(_sx(1304), interrupt=True)
            return
        if self._update_install_thread is not None and self._update_install_thread.is_alive():
            return
        self._update_progress_stage = _sx(761)
        self._update_progress_percent = 0.0
        self._update_progress_message = _sx(762)
        self._update_progress_announced_bucket = -1
        self._update_install_result = None
        self._update_restart_script_path = None
        self._update_install_error = _sx(2)
        self._update_ready_announced = False
        self.update_menu.items[0].label = _sx(763)
        self.update_menu.items[0].action = _sx(764)

        def progress_callback(progress: UpdateInstallProgress) -> None:
            self._update_progress_stage = progress.stage
            self._update_progress_percent = max(0.0, min(100.0, float(progress.percent)))
            self._update_progress_message = progress.message

        def worker() -> None:
            result = self.updater.download_and_install(release, progress_callback=progress_callback)
            self._update_install_result = result
            self._update_restart_script_path = result.restart_script_path
            if not result.success:
                self._update_install_error = result.message
        self._update_install_thread = threading.Thread(target=worker, name=_sx(1305), daemon=True)
        self._update_install_thread.start()

    def _update_update_install_state(self) -> None:
        if self.active_menu != self.update_menu:
            return
        if self._update_progress_stage == _sx(761):
            bucket = int(self._update_progress_percent // 10)
            if bucket > self._update_progress_announced_bucket and bucket < 10:
                self._update_progress_announced_bucket = bucket
                if bucket > 0:
                    self.speaker.speak(_sx(1786).format(bucket * 10), interrupt=False)
        if self._update_install_thread is None or self._update_install_thread.is_alive():
            return
        self._update_install_thread = None
        result = self._update_install_result
        if result is None:
            return
        self._update_status_message = result.message
        if not result.success:
            self.update_menu.items[0].label = _sx(994)
            self.update_menu.items[0].action = _sx(995)
            self._update_progress_stage = _sx(1007)
            self._play_menu_feedback(_sx(52))
            self.speaker.speak(result.message, interrupt=True)
            self._update_install_result = None
            return
        self.update_menu.items[0].label = _sx(765)
        self.update_menu.items[0].action = _sx(766)
        self.update_menu.items[1].label = _sx(756)
        self.update_menu.items[1].action = _sx(757)
        self.update_menu.items[2].label = _sx(767)
        self.update_menu.items[2].action = _sx(768)
        self._update_progress_stage = _sx(769)
        if not self._update_ready_announced:
            self._update_ready_announced = True
            self.speaker.speak(result.message, interrupt=True)

    def _check_for_updates(self, announce_result: bool, automatic: bool=False) -> None:
        result = self.updater.check_for_updates(APP_VERSION)
        self._latest_update_result = result
        if result.update_available:
            self._refresh_update_menu(result)
            if self.packaged_build or not automatic:
                self._set_active_menu(self.update_menu)
            if self.packaged_build:
                self.speaker.speak(self._update_status_message, interrupt=True)
                return
            if announce_result:
                self.speaker.speak(_sx(1627).format(self._update_status_message), interrupt=True)
            return
        if result.release is not None:
            self._update_status_message = _sx(1008).format(APP_VERSION, result.release.version, result.message)
        else:
            self._update_status_message = result.message
        if announce_result:
            self.speaker.speak(self._update_status_message, interrupt=True)
            return
        if automatic and result.status == _sx(1007):
            return

    def _menu_uses_gameplay_music(self, menu: Menu | None) -> bool:
        return menu in {self.pause_menu, self.pause_confirm_menu, self.revive_menu}

    def _sync_music_context(self) -> None:
        if self._exit_requested:
            return
        self.audio.set_music_ducking(False)
        if self.active_menu is None:
            if self.state.running:
                self.audio.music_start(_sx(72))
            else:
                self.audio.music_stop()
            return
        if self.state.running and self._menu_uses_gameplay_music(self.active_menu):
            self.audio.music_start(_sx(72))
            return
        self.audio.music_start(_sx(71))

    def _difficulty_key(self) -> str:
        return str(self.settings.get(_sx(318), _sx(200))).strip().lower()

    def _request_exit(self) -> None:
        if self._exit_requested:
            return
        self._exit_requested = True
        self._persist_settings()
        self.leaderboard_client.close()
        self.audio.music_stop()

    @staticmethod
    def _death_reason_for_variant(variant: str) -> str:
        return {_sx(643): _sx(1628), _sx(644): _sx(1629), _sx(97): _sx(1630), _sx(645): _sx(1631)}.get(variant, _sx(1009))

    def _open_game_over_dialog(self, death_reason: Optional[str]=None) -> None:
        summary_reason = death_reason or self._last_death_reason or _sx(1009)
        self._game_over_publish_state = _sx(658)
        self._update_game_over_summary(summary_reason)
        self._refresh_game_over_menu()
        if self._should_offer_publish_prompt():
            self._open_publish_confirmation(return_menu=self.game_over_menu, start_index=0)
        else:
            self.active_menu = self.game_over_menu
            self.game_over_menu.opened = True
            self.game_over_menu.index = 0
            self._pending_menu_announcement = (self.game_over_menu, 0.45, False)
        self._sync_music_context()
        self.speaker.speak(_sx(1010), interrupt=True)

    def _update_game_over_summary(self, reason: str) -> None:
        compact_powerup_usage = self._compact_powerup_usage(self._active_run_stats.get(_sx(967)))
        self._game_over_summary = {_sx(968): int(self.state.score), _sx(363): int(self.state.coins), _sx(969): int(self.state.time), _sx(970): str(reason or _sx(661)), _sx(971): APP_VERSION, _sx(318): self._difficulty_key(), _sx(972): int(self.state.distance), _sx(966): int(self._active_run_stats.get(_sx(966), 0) or 0), _sx(973): int(self.state.revives_used), _sx(967): compact_powerup_usage}

    def _should_offer_publish_prompt(self) -> bool:
        if self._practice_mode_active:
            return False
        if not self._leaderboard_has_publish_identity():
            return False
        summary = self._game_over_summary
        return int(summary.get(_sx(968), 0) or 0) > 0 or int(summary.get(_sx(363), 0) or 0) > 0

    def _open_publish_confirmation(self, return_menu: Menu, start_index: int=0) -> None:
        self._publish_confirm_return_menu = return_menu
        self._publish_confirm_return_index = max(0, int(start_index))
        self.active_menu = self.publish_confirm_menu
        self.publish_confirm_menu.opened = True
        self.publish_confirm_menu.index = 0
        self._pending_menu_announcement = (self.publish_confirm_menu, 0.0, True)

    def _run_or_confirm_purchase(self, purchase_handler: Callable[[], None], return_menu: Menu | None=None, return_index: int | None=None) -> None:
        if not self._purchase_confirmation_enabled():
            purchase_handler()
            return
        source_menu = return_menu or self.active_menu
        if source_menu is not None and source_menu.items:
            source_index = min(source_menu.index, len(source_menu.items) - 1)
        else:
            source_index = 0
        self._pending_purchase_handler = purchase_handler
        self._pending_purchase_return_menu = source_menu
        self._pending_purchase_return_index = max(0, source_index if return_index is None else int(return_index))
        self._set_active_menu(self.purchase_confirm_menu, start_index=0)

    def _resolve_pending_purchase(self, accepted: bool) -> None:
        purchase_handler = self._pending_purchase_handler
        return_menu = self._pending_purchase_return_menu
        return_index = self._pending_purchase_return_index
        self._pending_purchase_handler = None
        self._pending_purchase_return_menu = None
        self._pending_purchase_return_index = 0
        if accepted and purchase_handler is not None:
            purchase_handler()
        if self.active_menu == self.purchase_confirm_menu and return_menu is not None:
            self._set_active_menu(return_menu, start_index=return_index)

    def _mission_goals(self):
        return mission_goals_for_set(int(self.settings.get(_sx(339), 1)))

    def _mission_status_text(self) -> str:
        completed = len(completed_mission_metrics(self.settings))
        return _sx(770).format(completed)

    def _current_word(self) -> str:
        return active_word_for_settings(self.settings)

    def _remaining_word_letters(self) -> str:
        return remaining_word_letters(self.settings)

    def _next_word_letter(self) -> str:
        remaining_letters = self._remaining_word_letters()
        return remaining_letters[:1]

    def _choose_support_spawn_kind(self) -> str:
        profile = self._active_event_profile
        kinds = [_sx(1012), _sx(1013), _sx(569)]
        weights = [0.58, 0.18 + float(profile.get(_sx(616), 0.0) or 0.0), 0.08]
        active_word = any((obstacle.kind == _sx(1138) and obstacle.z > 0 for obstacle in self.obstacles))
        active_token = any((obstacle.kind == _sx(1139) and obstacle.z > 0 for obstacle in self.obstacles))
        active_multiplier = self.player.mult2x > 0 or any((obstacle.kind == _sx(1140) and obstacle.z > 0 for obstacle in self.obstacles))
        active_super_box = any((obstacle.kind == _sx(598) and obstacle.z > 0 for obstacle in self.obstacles))
        active_pogo = self.player.pogo_active > 0 or any((obstacle.kind == _sx(1141) and obstacle.z > 0 for obstacle in self.obstacles))
        if not active_multiplier:
            kinds.append(_sx(1140))
            weights.append(0.09)
        if not active_super_box:
            kinds.append(_sx(598))
            weights.append(0.06 + float(profile.get(_sx(614), 0.0) or 0.0))
        if not active_pogo:
            kinds.append(_sx(1141))
            weights.append(0.09)
        if self._remaining_word_letters() and (not active_word):
            kinds.append(_sx(1138))
            weights.append(0.08 + float(profile.get(_sx(615), 0.0) or 0.0))
        if next_season_reward_threshold(self.settings) is not None and (not active_token):
            kinds.append(_sx(1139))
            weights.append(0.05)
        return random.choices(kinds, weights=weights, k=1)[0]

    def _complete_mission_set(self) -> None:
        self.settings[_sx(339)] = int(self.settings.get(_sx(339), 1)) + 1
        self.settings[_sx(341)] = {_sx(363): 0, _sx(364): 0, _sx(365): 0, _sx(366): 0, _sx(367): 0, _sx(368): 0}
        if int(self.settings.get(_sx(340), 0)) < 29:
            self.settings[_sx(340)] = int(self.settings.get(_sx(340), 0)) + 1
            if self.state.running:
                self.state.multiplier += 1
            self.audio.play(_sx(100), channel=_sx(180))
            self.audio.play(_sx(108), channel=_sx(1250))
            self.speaker.speak(_sx(1307).format(1 + int(self.settings[_sx(340)])), interrupt=True)
            return
        self.audio.play(_sx(100), channel=_sx(180))
        self.speaker.speak(_sx(1014), interrupt=True)
        self._open_super_mystery_box(_sx(806))

    def _record_mission_event(self, metric: str, amount: int=1) -> None:
        ensure_progression_state(self.settings)
        if self.state.running and amount > 0:
            self._record_run_metric(metric, amount)
        if self._practice_mode_active:
            return
        achievement_metric = {_sx(364): _sx(370), _sx(365): _sx(371), _sx(366): _sx(372)}.get(metric)
        if achievement_metric is not None:
            self._record_achievement_metric(achievement_metric, amount)
        metrics = self.settings.get(_sx(341), {})
        if metric not in metrics or amount <= 0:
            return
        goals = self._mission_goals()
        completed_before = completed_mission_metrics(self.settings)
        metrics[metric] = int(metrics.get(metric, 0)) + amount
        completed_after = completed_mission_metrics(self.settings)
        newly_completed = completed_after - completed_before
        if self._quest_changes_enabled():
            for goal in goals:
                if goal.metric in newly_completed:
                    self.audio.play(_sx(100), channel=_sx(180))
                    self.speaker.speak(_sx(1788).format(goal.label), interrupt=False)
        if len(completed_after) == len(goals) and len(completed_before) != len(goals):
            self._complete_mission_set()

    def _reset_daily_progress(self) -> None:
        today = date.today()
        reset_daily_quest_progress(self.settings, today)
        word_hunt_reset = reset_daily_word_hunt_progress(self.settings, today)
        word_hunt_completed_today = str(self.settings.get(_sx(345), _sx(2)) or _sx(2)) == today.isoformat()
        reset_daily_event_progress(self.settings, today)
        self.audio.play(_sx(107), channel=_sx(180))
        self._refresh_quest_menu_labels()
        self._refresh_events_menu_labels()
        self._persist_settings()
        if word_hunt_completed_today and (not word_hunt_reset):
            self.speaker.speak(_sx(1308), interrupt=True)
            return
        self.speaker.speak(_sx(1015), interrupt=True)

    def _open_super_mystery_box(self, source: str) -> None:
        self._record_achievement_metric(_sx(373), 1)
        if self._special_active(_sx(1016)):
            self._box_high_tier_meter += 1
            jackpot_chance = min(0.35, 0.06 * self._box_high_tier_meter)
            if self._season_imprint_matches(_sx(1309)):
                jackpot_chance = min(0.45, jackpot_chance + 0.06)
            if random.random() < jackpot_chance:
                self._box_high_tier_meter = 0
                reward = random.choice([_sx(639), _sx(334), _sx(335)])
            else:
                reward = pick_super_mystery_box_reward()
        else:
            reward = pick_super_mystery_box_reward()
        self.audio.play(_sx(98), channel=_sx(180))
        self.audio.play(_sx(110), channel=_sx(1250))
        if reward == _sx(363):
            gain = random.randint(450, 1100)
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
            self.audio.play(_sx(105), channel=_sx(1231))
            self.speaker.speak(_sx(1018).format(source, gain), interrupt=True)
            return
        if reward == _sx(335):
            gain = random.randint(1, 2)
            self.settings[_sx(335)] = int(self.settings.get(_sx(335), 0)) + gain
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1310).format(source, gain, _sx(294) if gain != 1 else _sx(2)), interrupt=True)
            return
        if reward == _sx(1017):
            self.audio.play(_sx(108), channel=_sx(1231))
            if self.state.running:
                self._apply_power_reward(_sx(1017), from_headstart=False)
                self.speaker.speak(_sx(1634).format(source), interrupt=True)
                return
            gain = random.randint(450, 1100)
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
            self.audio.play(_sx(105), channel=_sx(1231))
            self.speaker.speak(_sx(1018).format(source, gain), interrupt=True)
            return
        if reward == _sx(334):
            gain = random.randint(1, 2)
            self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + gain
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1311).format(source, gain, _sx(294) if gain != 1 else _sx(2)), interrupt=True)
            return
        if reward == _sx(336):
            self.settings[_sx(336)] = int(self.settings.get(_sx(336), 0)) + 1
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1312).format(source), interrupt=True)
            return
        if reward == _sx(337):
            self.settings[_sx(337)] = int(self.settings.get(_sx(337), 0)) + 1
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1313).format(source), interrupt=True)
            return
        if reward == _sx(639):
            gain = random.randint(1500, 2600)
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
            self.audio.play(_sx(105), channel=_sx(1231))
            self.audio.play(_sx(108), channel=_sx(1637))
            self.speaker.speak(_sx(1314).format(source, gain), interrupt=True)
            return
        if int(self.settings.get(_sx(340), 0)) < 29:
            self.settings[_sx(340)] = int(self.settings.get(_sx(340), 0)) + 1
            if self.state.running:
                self.state.multiplier += 1
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1315).format(source, 1 + int(self.settings[_sx(340)])), interrupt=True)
            return
        gain = random.randint(900, 1500)
        self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
        self.audio.play(_sx(105), channel=_sx(1231))
        self.speaker.speak(_sx(1018).format(source, gain), interrupt=True)

    def _complete_word_hunt(self) -> None:
        streak = update_word_hunt_streak(self.settings)
        self._record_achievement_max(_sx(375), streak)
        reward_kind, amount = word_hunt_reward_for_streak(streak)
        self.audio.play(_sx(100), channel=_sx(180))
        if reward_kind == _sx(363):
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + amount
            self.audio.play(_sx(105), channel=_sx(1250))
            self.speaker.speak(_sx(1318).format(streak, amount), interrupt=True)
            return
        self.speaker.speak(_sx(1019).format(streak), interrupt=True)
        self._open_super_mystery_box(_sx(1020))

    def _claim_season_reward(self) -> None:
        reward = claim_season_reward(self.settings)
        if reward is None:
            return
        self.audio.play(_sx(100), channel=_sx(180))
        self.audio.play(_sx(108), channel=_sx(1250))
        if reward == _sx(363):
            gain = 500
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
            self.audio.play(_sx(105), channel=_sx(1231))
            self.speaker.speak(_sx(1321).format(gain), interrupt=True)
            return
        if reward == _sx(569):
            self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + 1
            self.speaker.speak(_sx(1322), interrupt=True)
            return
        if reward == _sx(595):
            self.settings[_sx(336)] = int(self.settings.get(_sx(336), 0)) + 1
            self.speaker.speak(_sx(1323), interrupt=True)
            return
        self.speaker.speak(_sx(1021), interrupt=True)
        self._open_super_mystery_box(_sx(1022))

    def _spend_bank_coins(self, cost: int) -> bool:
        current = int(self.settings.get(_sx(333), 0))
        if current < cost:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1324), interrupt=True)
            return False
        self.settings[_sx(333)] = current - cost
        self.audio.play(_sx(105), channel=_sx(180))
        return True

    def _persist_settings(self) -> None:
        self._sync_leaderboard_settings_from_client()
        config_module.save_settings(self.settings)

    def _sync_leaderboard_settings_from_client(self) -> None:
        self._leaderboard_username = str(self.leaderboard_client.principal_username or self._leaderboard_username or _sx(2)).strip()
        self.settings[_sx(330)] = self._leaderboard_username
        self.settings[_sx(331)] = str(self.leaderboard_client.auth_token or _sx(2)).strip()

    def _restore_persisted_leaderboard_session(self) -> None:
        persisted_username = str(self.settings.get(_sx(330), _sx(2)) or _sx(2)).strip()
        persisted_token = str(self.settings.get(_sx(331), _sx(2)) or _sx(2)).strip()
        self._leaderboard_username = persisted_username
        self.leaderboard_client.principal_username = persisted_username
        self.leaderboard_client.auth_token = persisted_token

    def _claimed_leaderboard_reward_ids(self) -> list[str]:
        return [str(reward_id).strip() for reward_id in list(self.settings.get(_sx(332)) or []) if str(reward_id).strip()]

    def _remember_leaderboard_reward_ids(self, reward_ids: list[str]) -> None:
        remembered = self._claimed_leaderboard_reward_ids()
        for reward_id in reward_ids:
            normalized = str(reward_id).strip()
            if not normalized or normalized in remembered:
                continue
            remembered.append(normalized)
        self.settings[_sx(332)] = remembered[-256:]

    def _format_leaderboard_season_remaining(self) -> str:
        season = self._leaderboard_season or {}
        remaining = max(0, int(season.get(_sx(1790), 0) or 0))
        days = remaining // 86400
        hours = remaining % 86400 // 3600
        minutes = remaining % 3600 // 60
        return _sx(771).format(days, _sx(294) if days != 1 else _sx(2), hours, _sx(294) if hours != 1 else _sx(2), minutes, _sx(294) if minutes != 1 else _sx(2))

    def _leaderboard_season_status_label(self) -> str:
        if not self._leaderboard_season:
            return _sx(1026)
        return _sx(772).format(self._format_leaderboard_season_remaining())

    def _leaderboard_reward_status_label(self) -> str:
        season = self._leaderboard_season or {}
        reward_label = str(season.get(_sx(1856)) or _sx(1791)).strip()
        reward_preview = str(season.get(_sx(1857)) or _sx(1792)).strip()
        return _sx(773).format(reward_label, reward_preview)

    def _leaderboard_season_identity_label(self) -> str:
        season = self._leaderboard_season or {}
        season_name = str(season.get(_sx(1858)) or _sx(2)).strip()
        season_key = str(season.get(_sx(1859)) or _sx(2)).strip()
        if season_name and season_key:
            return _sx(1030).format(season_name, season_key)
        if season_name:
            return _sx(776).format(season_name)
        if season_key:
            return _sx(776).format(season_key)
        return _sx(774)

    def _apply_leaderboard_account_sync(self, payload: dict[str, object], *, announce_rewards: bool) -> int:
        applied_reward_ids: list[str] = []
        username = str(payload.get(_sx(1502)) or self._leaderboard_username or _sx(2)).strip()
        if username and username != self._leaderboard_username:
            self._leaderboard_username = username
            self.settings[_sx(330)] = username
            self._refresh_options_menu_labels()
        season = payload.get(_sx(659))
        if isinstance(season, dict):
            self._leaderboard_season = dict(season)
        self._apply_special_sync_payload(payload)
        known_ids = set(self._claimed_leaderboard_reward_ids())
        for reward_entry in list(payload.get(_sx(1641)) or []):
            if not isinstance(reward_entry, dict):
                continue
            reward_id = str(reward_entry.get(_sx(1870)) or _sx(2)).strip()
            if not reward_id or reward_id in known_ids:
                continue
            reward_kind = str(reward_entry.get(_sx(1889)) or _sx(2)).strip().lower()
            reward_amount = max(1, int(reward_entry.get(_sx(1860), 1) or 1))
            source = _sx(1031).format(int(reward_entry.get(_sx(1871), 0) or 0))
            if self._apply_meta_reward({_sx(592): reward_kind, _sx(593): reward_amount}, source):
                applied_reward_ids.append(reward_id)
                known_ids.add(reward_id)
        if applied_reward_ids:
            self._remember_leaderboard_reward_ids(applied_reward_ids)
            self._persist_settings()
            if announce_rewards and len(applied_reward_ids) > 1:
                self.speaker.speak(_sx(1642).format(len(applied_reward_ids)), interrupt=True)
        elif username:
            self._persist_settings()
        return len(applied_reward_ids)

    def _apply_special_sync_payload(self, payload: dict[str, object]) -> None:
        items_payload = payload.get(_sx(1032))
        loadout_payload = payload.get(_sx(1033))
        wheel_payload = payload.get(_sx(1034))
        season_imprint_bonus = str(payload.get(_sx(1877)) or _sx(2)).strip().lower()
        normalized_items: dict[str, int] = {}
        if isinstance(items_payload, dict):
            for item_key in SPECIAL_ITEM_ORDER:
                amount = int(items_payload.get(item_key, 0) or 0)
                if amount > 0:
                    normalized_items[item_key] = amount
        normalized_loadout: dict[str, bool] = {}
        for item_key in SPECIAL_ITEM_ORDER:
            if item_key not in normalized_items:
                normalized_loadout[item_key] = False
                continue
            enabled = bool(loadout_payload.get(item_key, False)) if isinstance(loadout_payload, dict) else False
            normalized_loadout[item_key] = enabled
        self._server_special_items = normalized_items
        self._server_special_item_loadout = normalized_loadout
        self._server_wheel_status = dict(wheel_payload) if isinstance(wheel_payload, dict) else {}
        if season_imprint_bonus in SEASON_IMPRINT_TEXT:
            self._season_imprint_bonus_key = season_imprint_bonus
        elif not self._season_imprint_bonus_key:
            self._season_imprint_bonus_key = _sx(2)
        self._refresh_wheel_menu_labels()
        self._refresh_loadout_menu_labels()

    def _clear_server_special_state(self) -> None:
        self._server_special_items = {}
        self._server_special_item_loadout = {key: False for key in SPECIAL_ITEM_ORDER}
        self._server_wheel_status = {}
        self._season_imprint_bonus_key = _sx(2)
        self._active_special_run_items.clear()
        self._special_effect_timers.clear()
        self._special_run_used_flags.clear()
        self._consumed_special_items_this_run.clear()
        self._pending_consumed_special_items = []
        self._pending_overclock_keys = 0
        self._box_high_tier_meter = 0
        self._coin_streak_grace_timer = 0.0
        self._refresh_wheel_menu_labels()
        self._refresh_loadout_menu_labels()

    def _start_background_leaderboard_sync(self) -> None:
        if self._leaderboard_startup_sync_started or not self._leaderboard_is_authenticated():
            return
        self._leaderboard_startup_sync_started = True

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            sync_payload = self.leaderboard_client.sync_account(self._claimed_leaderboard_reward_ids())
            sync_payload[_sx(1327)] = just_connected
            return sync_payload
        self._start_leaderboard_operation(_sx(1035), _sx(811), _sx(1036), worker, return_menu=self.active_menu, show_status=False, reject_message=False)

    def _sync_character_progress(self) -> None:
        ensure_character_progress_state(self.settings)
        ensure_board_state(self.settings)
        ensure_collection_state(self.settings)
        ensure_quest_state(self.settings)
        ensure_event_state(self.settings)
        self._collection_bonuses = collection_runtime_bonuses(self.settings)
        character_bonuses = character_runtime_bonuses(self.settings)
        self._active_character_bonuses = CharacterRuntimeBonuses(banked_coin_bonus_ratio=character_bonuses.banked_coin_bonus_ratio + self._collection_bonuses.banked_coin_bonus_ratio, hoverboard_duration_bonus=character_bonuses.hoverboard_duration_bonus + self._collection_bonuses.hoverboard_duration_bonus, power_duration_multiplier=character_bonuses.power_duration_multiplier * self._collection_bonuses.power_duration_multiplier, starting_multiplier_bonus=character_bonuses.starting_multiplier_bonus + self._collection_bonuses.starting_multiplier_bonus)
        self._active_event_profile = event_runtime_profile(self.settings)

    def _powerup_duration(self, key: str) -> float:
        return self._character_adjusted_power_duration(item_upgrade_duration(self.settings, key))

    def _special_active(self, item_key: str) -> bool:
        return item_key in self._active_special_run_items

    def _season_imprint_active(self) -> bool:
        return self._special_active(_sx(1328)) and bool(self._season_imprint_bonus_key)

    def _season_imprint_matches(self, bonus_key: str) -> bool:
        matched = self._season_imprint_active() and self._season_imprint_bonus_key == bonus_key
        if matched:
            self._mark_special_item_consumed(_sx(1328))
        return matched

    def _special_timer(self, timer_key: str) -> float:
        return float(self._special_effect_timers.get(timer_key, 0.0) or 0.0)

    def _set_special_timer(self, timer_key: str, duration: float) -> None:
        self._special_effect_timers[timer_key] = max(0.0, float(duration))

    def _extend_special_timer(self, timer_key: str, duration: float) -> None:
        self._set_special_timer(timer_key, max(self._special_timer(timer_key), float(duration)))

    def _special_duration_scale(self) -> float:
        if self._season_imprint_matches(_sx(1037)):
            return 1.2
        return 1.0

    def _mark_special_item_consumed(self, item_key: str) -> None:
        normalized_key = str(item_key or _sx(2)).strip().lower()
        if normalized_key not in SPECIAL_ITEM_ORDER:
            return
        if normalized_key not in self._active_special_run_items:
            return
        if normalized_key in self._consumed_special_items_this_run:
            return
        self._consumed_special_items_this_run.add(normalized_key)

    def _queue_consumed_special_items_sync(self) -> None:
        if not self._consumed_special_items_this_run:
            return
        for item_key in sorted(self._consumed_special_items_this_run):
            self._pending_consumed_special_items.append(item_key)
        self._consumed_special_items_this_run.clear()
        if not self._leaderboard_is_authenticated():
            return
        if self._leaderboard_active_operation is not None:
            return
        pending_items = [str(item_key).strip() for item_key in self._pending_consumed_special_items if str(item_key).strip()]
        if not pending_items:
            return
        pending_items = list(dict.fromkeys(pending_items))[:64]

        def worker() -> dict[str, object]:
            self.leaderboard_client.connect()
            payload = self.leaderboard_client.sync_account(self._claimed_leaderboard_reward_ids(), consumed_special_item_keys=pending_items)
            payload[_sx(1329)] = list(pending_items)
            return payload
        self._start_leaderboard_operation(_sx(1038), _sx(1039), _sx(1040), worker, return_menu=self.active_menu, show_status=False, reject_message=False)

    def _flush_consumed_special_items(self, consumed_keys: list[str]) -> None:
        consumed_set = {str(item_key).strip().lower() for item_key in consumed_keys if str(item_key).strip()}
        if not consumed_set:
            return
        self._pending_consumed_special_items = [item_key for item_key in self._pending_consumed_special_items if str(item_key).strip().lower() not in consumed_set]

    def _unlock_character(self, key: str) -> None:
        definition = character_definition(key)
        if character_unlocked(self.settings, definition.key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1230).format(definition.name), interrupt=True)
            return
        if not self._spend_bank_coins(definition.unlock_cost):
            return
        previous_completed = completed_collection_keys(self.settings)
        self.settings[_sx(240)][definition.key][_sx(239)] = True
        self._sync_character_progress()
        self._refresh_shop_menu_labels()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()
        self._persist_settings()
        self.audio.play(_sx(108), channel=_sx(1231))
        self.speaker.speak(_sx(1041).format(definition.name), interrupt=True)
        self.speaker.speak(self._shop_coins_label(), interrupt=False)
        self._announce_collection_unlocks(previous_completed)

    def _select_character(self, key: str) -> None:
        definition = character_definition(key)
        if not character_unlocked(self.settings, definition.key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1331).format(definition.name), interrupt=True)
            return
        if selected_character_definition(self.settings).key == definition.key:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1332).format(definition.name), interrupt=True)
            return
        self.settings[_sx(241)] = definition.key
        self._sync_character_progress()
        self._refresh_shop_menu_labels()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._refresh_events_menu_labels()
        self._refresh_me_menu_labels()
        self._persist_settings()
        self.audio.play(_sx(56), channel=_sx(180))
        self.speaker.speak(_sx(1042).format(definition.name), interrupt=True)

    def _upgrade_character(self, key: str) -> None:
        definition = character_definition(key)
        if not character_unlocked(self.settings, definition.key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1334), interrupt=True)
            return
        upgrade_cost = next_character_upgrade_cost(self.settings, definition.key)
        if upgrade_cost is None:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1335).format(definition.name), interrupt=True)
            return
        if not self._spend_bank_coins(upgrade_cost):
            return
        self.settings[_sx(240)][definition.key][_sx(289)] = character_level(self.settings, definition.key) + 1
        self._sync_character_progress()
        self._refresh_shop_menu_labels()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._persist_settings()
        upgraded_level = character_level(self.settings, definition.key)
        self.audio.play(_sx(108), channel=_sx(1231))
        self.speaker.speak(_sx(1043).format(definition.name, upgraded_level, character_perk_summary(definition, upgraded_level)), interrupt=True)
        self.speaker.speak(self._shop_coins_label(), interrupt=False)

    def _purchase_item_upgrade(self, key: str) -> None:
        definition = item_upgrade_definition(key)
        upgrade_cost = next_item_upgrade_cost(self.settings, definition.key)
        if upgrade_cost is None:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1335).format(definition.name), interrupt=True)
            return
        if not self._spend_bank_coins(upgrade_cost):
            return
        self.settings[_sx(338)][definition.key] = item_upgrade_level(self.settings, definition.key) + 1
        self._refresh_shop_menu_labels()
        self._refresh_item_upgrade_menu_labels()
        self._refresh_item_upgrade_detail_menu_labels(definition.key)
        self._refresh_me_menu_labels()
        self._persist_settings()
        upgraded_level = item_upgrade_level(self.settings, definition.key)
        upgraded_duration = item_upgrade_duration(self.settings, definition.key)
        self.audio.play(_sx(108), channel=_sx(1231))
        self.speaker.speak(_sx(1044).format(definition.name, upgraded_level, self._format_duration_seconds(upgraded_duration)), interrupt=True)
        self.speaker.speak(self._shop_coins_label(), interrupt=False)

    def _unlock_board(self, key: str) -> None:
        definition = board_definition(key)
        if board_unlocked(self.settings, definition.key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1230).format(definition.name), interrupt=True)
            return
        if not self._spend_bank_coins(definition.unlock_cost):
            return
        previous_completed = completed_collection_keys(self.settings)
        self.settings[_sx(202)][definition.key][_sx(239)] = True
        self._sync_character_progress()
        self._refresh_board_menu_labels()
        self._refresh_board_detail_menu_labels(definition.key)
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()
        self._persist_settings()
        self.audio.play(_sx(108), channel=_sx(1231))
        self.speaker.speak(_sx(1041).format(definition.name), interrupt=True)
        self.speaker.speak(self._shop_coins_label(), interrupt=False)
        self._announce_collection_unlocks(previous_completed)

    def _select_board(self, key: str) -> None:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1331).format(definition.name), interrupt=True)
            return
        if selected_board_definition(self.settings).key == definition.key:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1332).format(definition.name), interrupt=True)
            return
        self.settings[_sx(203)] = definition.key
        self._sync_character_progress()
        self._refresh_board_menu_labels()
        self._refresh_board_detail_menu_labels(definition.key)
        self._refresh_me_menu_labels()
        self._refresh_loadout_menu_labels()
        self._persist_settings()
        self.audio.play(_sx(56), channel=_sx(180))
        self.speaker.speak(_sx(1042).format(definition.name), interrupt=True)

    def _apply_meta_reward(self, reward: dict[str, object] | None, source: str) -> bool:
        if reward is None:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1338).format(source), interrupt=True)
            return False
        kind = str(reward.get(_sx(592)) or _sx(2)).strip().lower()
        amount = max(1, int(reward.get(_sx(593), 1) or 1))
        if kind == _sx(363):
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + amount
            self.audio.play(_sx(105), channel=_sx(1231))
            self.speaker.speak(_sx(1339).format(source, amount), interrupt=True)
            return True
        if kind == _sx(569):
            self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + amount
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1340).format(source, amount, _sx(294) if amount != 1 else _sx(2)), interrupt=True)
            return True
        if kind == _sx(595):
            self.settings[_sx(336)] = int(self.settings.get(_sx(336), 0)) + amount
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1341).format(source, amount, _sx(294) if amount != 1 else _sx(2)), interrupt=True)
            return True
        if kind == _sx(596):
            self.settings[_sx(337)] = int(self.settings.get(_sx(337), 0)) + amount
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1342).format(source, amount, _sx(294) if amount != 1 else _sx(2)), interrupt=True)
            return True
        if kind == _sx(594):
            self.settings[_sx(335)] = int(self.settings.get(_sx(335), 0)) + amount
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1343).format(source, amount, _sx(294) if amount != 1 else _sx(2)), interrupt=True)
            return True
        if kind == _sx(597):
            self.settings[_sx(352)][_sx(597)] = int(self.settings[_sx(352)].get(_sx(597), 0)) + amount
            self.audio.play(_sx(100), channel=_sx(1231))
            self.speaker.speak(_sx(1344).format(source, amount), interrupt=True)
            return True
        if kind == _sx(598):
            self.speaker.speak(_sx(1345).format(source), interrupt=True)
            self._open_super_mystery_box(source)
            return True
        self.audio.play(_sx(52), channel=_sx(180))
        self.speaker.speak(_sx(1045).format(source), interrupt=True)
        return False

    def _purchase_shop_item(self, item: str) -> None:
        if item == _sx(594):
            if not self._spend_bank_coins(SHOP_PRICES[_sx(594)]):
                return
            self.settings[_sx(335)] = int(self.settings.get(_sx(335), 0)) + 1
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1347), interrupt=True)
        elif item == _sx(21):
            if not self._spend_bank_coins(SHOP_PRICES[_sx(21)]):
                return
            if self._active_event_profile.get(_sx(617)) or self._special_active(_sx(1016)):
                self._box_high_tier_meter += 1
                jackpot_weight = 12
                if self._special_active(_sx(1016)):
                    jackpot_weight += min(20, self._box_high_tier_meter * 3)
                    if self._season_imprint_matches(_sx(1309)):
                        jackpot_weight += 8
                reward = random.choices([_sx(363), _sx(636), _sx(569), _sx(595), _sx(596), _sx(639), _sx(638)], weights=[45, 12, 12, 10, 8, jackpot_weight, 1], k=1)[0]
                if reward == _sx(639):
                    self._box_high_tier_meter = 0
                    if self._special_active(_sx(1016)):
                        self._mark_special_item_consumed(_sx(1016))
            else:
                reward = pick_shop_mystery_box_reward()
            self._grant_shop_box_reward(reward)
        elif item == _sx(595):
            if not self._spend_bank_coins(SHOP_PRICES[_sx(595)]):
                return
            self.settings[_sx(336)] = int(self.settings.get(_sx(336), 0)) + 1
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1794), interrupt=True)
        elif item == _sx(596):
            if not self._spend_bank_coins(SHOP_PRICES[_sx(596)]):
                return
            self.settings[_sx(337)] = int(self.settings.get(_sx(337), 0)) + 1
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1861), interrupt=True)
        self._refresh_shop_menu_labels()
        self._persist_settings()
        self.speaker.speak(self._shop_coins_label(), interrupt=False)

    def _grant_shop_box_reward(self, reward: str) -> None:
        self.speaker.speak(_sx(1046), interrupt=True)
        self.audio.play(_sx(98), channel=_sx(36))
        if reward == _sx(363):
            gain = shop_box_reward_amount(_sx(363))
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
            self.audio.play(_sx(105), channel=_sx(1231))
            self.speaker.speak(_sx(1348).format(gain), interrupt=False)
            return
        if reward == _sx(636):
            gain = shop_box_reward_amount(_sx(636))
            self.settings[_sx(335)] = int(self.settings.get(_sx(335), 0)) + gain
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1349).format(gain, _sx(294) if gain != 1 else _sx(2)), interrupt=False)
            return
        if reward == _sx(569):
            gain = shop_box_reward_amount(_sx(569))
            self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + gain
            self.audio.play(_sx(108), channel=_sx(1231))
            self.speaker.speak(_sx(1350).format(gain, _sx(294) if gain != 1 else _sx(2)), interrupt=False)
            return
        if reward == _sx(595):
            gain = shop_box_reward_amount(_sx(595))
            self.settings[_sx(336)] = int(self.settings.get(_sx(336), 0)) + gain
            self.audio.play(_sx(110), channel=_sx(1231))
            self.speaker.speak(_sx(1351).format(gain, _sx(294) if gain != 1 else _sx(2)), interrupt=False)
            return
        if reward == _sx(596):
            gain = shop_box_reward_amount(_sx(596))
            self.settings[_sx(337)] = int(self.settings.get(_sx(337), 0)) + gain
            self.audio.play(_sx(110), channel=_sx(1231))
            self.speaker.speak(_sx(1352).format(gain, _sx(294) if gain != 1 else _sx(2)), interrupt=False)
            return
        if reward == _sx(639):
            gain = shop_box_reward_amount(_sx(639))
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + gain
            self.audio.play(_sx(105), channel=_sx(1231))
            self.audio.play(_sx(108), channel=_sx(1637))
            self.speaker.speak(_sx(1353).format(gain), interrupt=False)
            return
        self.speaker.speak(_sx(1047), interrupt=False)

    def _commit_run_rewards(self) -> None:
        if self._run_rewards_committed or not self.state.running:
            return
        self._run_rewards_committed = True
        if self._practice_mode_active:
            return
        saved_coins = int(self.state.coins)
        character_bonus = int(saved_coins * self._active_character_bonuses.banked_coin_bonus_ratio)
        vault_seal_bonus = 0
        if self._special_active(_sx(1354)) and saved_coins > 0:
            ratio = 0.1 if self._season_imprint_matches(_sx(1037)) else 0.07
            vault_seal_bonus = max(1, int(saved_coins * ratio))
            self._mark_special_item_consumed(_sx(1354))
        total_saved_coins = saved_coins + character_bonus + vault_seal_bonus
        self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + total_saved_coins
        if self._pending_overclock_keys > 0:
            self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + int(self._pending_overclock_keys)
        self._record_achievement_max(_sx(374), int(self.state.distance))
        if total_saved_coins > 0:
            self.audio.play(_sx(90), channel=_sx(180))
            self.audio.play(_sx(105), channel=_sx(1250))
        if character_bonus > 0:
            active_character = selected_character_definition(self.settings)
            self.speaker.speak(_sx(1355).format(active_character.name, character_bonus), interrupt=False)
        if vault_seal_bonus > 0:
            self.speaker.speak(_sx(1356).format(vault_seal_bonus), interrupt=False)
        if self._pending_overclock_keys > 0:
            self.speaker.speak(_sx(1357).format(int(self._pending_overclock_keys)), interrupt=False)
        record_daily_score(self.settings, int(self.state.score))
        record_coin_meter_coins(self.settings, saved_coins)
        hoverboards_used = int(self._compact_powerup_usage(self._active_run_stats.get(_sx(967))).get(_sx(594), 0) or 0)
        for quest in record_quest_metric(self.settings, _sx(972), int(self.state.distance)):
            self.audio.play(_sx(100), channel=_sx(1231))
            self.speaker.speak(_sx(1358).format(quest.label), interrupt=False)
        for quest in record_quest_metric(self.settings, _sx(1048), 1):
            self.audio.play(_sx(100), channel=_sx(1231))
            self.speaker.speak(_sx(1358).format(quest.label), interrupt=False)
        if hoverboards_used > 0:
            for quest in record_quest_metric(self.settings, _sx(1359), hoverboards_used):
                self.audio.play(_sx(100), channel=_sx(1231))
                self.speaker.speak(_sx(1358).format(quest.label), interrupt=False)
        self._refresh_events_menu_labels()
        self._refresh_quest_menu_labels()
        self._refresh_missions_hub_menu_labels()
        self._persist_settings()
        self._queue_consumed_special_items_sync()

    def _clear_menu_repeat(self) -> None:
        self._menu_repeat_key = None
        self._menu_repeat_delay_remaining = 0.0

    def _reset_input_after_native_modal(self) -> None:
        self._clear_menu_repeat()
        try:
            pygame.event.pump()
            pygame.key.set_mods(0)
        except Exception:
            pass
        event_types = [pygame.KEYDOWN, pygame.KEYUP, pygame.ACTIVEEVENT]
        for event_name in (_sx(1049), _sx(1050), _sx(1051), _sx(1052), _sx(1053)):
            event_type = getattr(pygame, event_name, None)
            if event_type is not None:
                event_types.append(event_type)
        for event_type in event_types:
            try:
                pygame.event.clear(event_type)
            except Exception:
                continue

    def _set_active_menu(self, menu: Optional[Menu], start_index: int | None=None, play_sound: bool=True) -> None:
        self._clear_menu_repeat()
        self._stop_learn_sound_preview()
        if self.active_menu is not None:
            self._menu_last_indices[id(self.active_menu)] = int(self.active_menu.index)
        self.active_menu = menu
        if menu is not None:
            if start_index is None:
                remembered_index = self._menu_last_indices.get(id(menu))
                target_index = int(remembered_index) if remembered_index is not None else 0
            else:
                target_index = int(start_index)
            menu.open(start_index=target_index, play_sound=play_sound)
            self._menu_last_indices[id(menu)] = int(menu.index)
            if menu == self.learn_sounds_menu:
                self._refresh_learn_sound_description()
        self._sync_music_context()

    def _menu_key_supports_repeat(self, key: int) -> bool:
        if self.active_menu is None:
            return False
        if key in (pygame.K_UP, pygame.K_DOWN, pygame.K_w, pygame.K_s):
            return True
        if self.active_menu in {self.options_menu, self.sapi_menu, self.announcements_menu} and key in (pygame.K_LEFT, pygame.K_RIGHT):
            return True
        if self.active_menu == self.controls_menu and key in (pygame.K_LEFT, pygame.K_RIGHT):
            selected_action = self.controls_menu.items[self.controls_menu.index].action if self.controls_menu.items else _sx(2)
            return selected_action == _sx(984)
        return False

    def _prime_menu_repeat(self, key: int) -> None:
        if self._menu_key_supports_repeat(key):
            self._menu_repeat_key = key
            self._menu_repeat_delay_remaining = MENU_REPEAT_INITIAL_DELAY
            return
        if self._menu_repeat_key == key:
            self._clear_menu_repeat()

    def _release_menu_repeat(self, key: int) -> None:
        if self._menu_repeat_key == key:
            self._clear_menu_repeat()

    def _update_menu_repeat(self, delta_time: float) -> None:
        if self._menu_repeat_key is None or self.active_menu is None:
            return
        if not self._menu_key_supports_repeat(self._menu_repeat_key):
            self._clear_menu_repeat()
            return
        self._menu_repeat_delay_remaining -= delta_time
        while self._menu_repeat_delay_remaining <= 0:
            self._handle_active_menu_key(self._menu_repeat_key)
            if self._menu_repeat_key is None or self.active_menu is None:
                return
            self._menu_repeat_delay_remaining += MENU_REPEAT_INTERVAL

    def _input_context(self) -> str:
        return MENU_CONTEXT if self.active_menu is not None else GAME_CONTEXT

    def _process_translated_keydown(self, key: int) -> bool:
        if self._exit_requested:
            return True
        if self.active_menu is not None:
            if self._pending_menu_announcement is not None and self.active_menu == self.game_over_menu:
                return True
            keep_running = self._handle_active_menu_key(key)
            if keep_running:
                self._prime_menu_repeat(key)
                return True
            self._request_exit()
            return False
        self._handle_game_key(key)
        return True

    def _process_translated_keyup(self, key: int) -> None:
        self._release_menu_repeat(key)

    def _announce_controller_connected(self, name: str, family: str) -> None:
        self._selected_binding_device = _sx(565)
        self._refresh_control_menus()
        self.speaker.speak(_sx(1054).format(family_label(family)), interrupt=True)

    def _announce_controller_disconnected(self, name: str, family: str) -> None:
        self._selected_binding_device = _sx(563)
        self._refresh_control_menus()
        self.speaker.speak(_sx(1055).format(family_label(family)), interrupt=True)

    def _cancel_binding_capture(self, announce: bool=True) -> None:
        if self._binding_capture is None:
            return
        self._keyboard_binding_hold = None
        self._binding_capture = None
        if announce:
            self.speaker.speak(_sx(1362), interrupt=True)

    def _begin_binding_capture(self, device: str, action_key: str) -> None:
        self._binding_capture = BindingCaptureRequest(device=device, action_key=action_key)
        self._keyboard_binding_hold = None
        prompt = action_label(action_key)
        if device == _sx(563):
            self.speaker.speak(_sx(1363).format(prompt), interrupt=True)
            return
        controller_name = family_label(self.controls.current_controller_family())
        self.speaker.speak(_sx(1056).format(controller_name, prompt), interrupt=True)

    @staticmethod
    def _is_modifier_key(key: int) -> bool:
        return key in {pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LALT, pygame.K_RALT, pygame.K_LMETA, pygame.K_RMETA}

    def _modifier_mask_from_keys(self, keys: set[int]) -> int:
        mask = 0
        if pygame.K_LSHIFT in keys or pygame.K_RSHIFT in keys:
            mask |= pygame.KMOD_SHIFT
        if pygame.K_LCTRL in keys or pygame.K_RCTRL in keys:
            mask |= pygame.KMOD_CTRL
        if pygame.K_LALT in keys or pygame.K_RALT in keys:
            mask |= pygame.KMOD_ALT
        if pygame.K_LMETA in keys or pygame.K_RMETA in keys:
            mask |= pygame.KMOD_META
        return mask

    def _keyboard_binding_value_from_pressed_keys(self, key_event: pygame.event.Event) -> tuple[int | dict[str, object] | None, frozenset[int], str]:
        non_modifier_keys = [key for key in self._pressed_keys if not self._is_modifier_key(key)]
        if len(non_modifier_keys) != 1:
            return (None, frozenset(), _sx(2))
        primary_key = int(non_modifier_keys[0])
        modifier_mask = self._modifier_mask_from_keys(self._pressed_keys)
        raw_char = str(getattr(key_event, _sx(1661), _sx(2)) or _sx(2))
        char_label = raw_char if len(raw_char) == 1 and raw_char.isprintable() and (not raw_char.isspace()) else _sx(2)
        label = char_label or keyboard_key_label(primary_key)
        if modifier_mask & pygame.KMOD_CTRL:
            label = _sx(1057).format(label)
        if modifier_mask & pygame.KMOD_ALT:
            label = _sx(1058).format(label)
        if modifier_mask & pygame.KMOD_SHIFT:
            label = _sx(1059).format(label)
        if modifier_mask & pygame.KMOD_META:
            label = _sx(1060).format(label)
        if modifier_mask == 0 and (not char_label):
            return (primary_key, frozenset(self._pressed_keys), label)
        return ({_sx(569): primary_key, _sx(570): int(modifier_mask), _sx(571): label}, frozenset(self._pressed_keys), label)

    def _start_keyboard_binding_hold_capture(self, key_event: pygame.event.Event) -> None:
        if self._binding_capture is None:
            return
        binding_value, required_keys, label = self._keyboard_binding_value_from_pressed_keys(key_event)
        if binding_value is None:
            if len([key for key in self._pressed_keys if not self._is_modifier_key(key)]) > 1:
                self._play_menu_feedback(_sx(52))
                self.speaker.speak(_sx(1662), interrupt=True)
            return
        self._keyboard_binding_hold = KeyboardBindingHoldState(action_key=self._binding_capture.action_key, binding_value=binding_value, required_keys=required_keys, remaining_seconds=BINDING_CAPTURE_HOLD_SECONDS, next_ding_mark=2)
        self.audio.play(_sx(57), channel=_sx(180), pitch=BINDING_CAPTURE_DING_PITCHES[3])
        self.speaker.speak(_sx(1061).format(label), interrupt=True)

    def _fail_keyboard_binding_hold(self) -> None:
        self._keyboard_binding_hold = None
        self.audio.play(_sx(59), channel=_sx(180))
        self.speaker.speak(_sx(1062), interrupt=True)

    def _complete_keyboard_binding_capture(self) -> None:
        if self._binding_capture is None or self._keyboard_binding_hold is None:
            return
        action_key = self._binding_capture.action_key
        self.controls.update_keyboard_binding(action_key, self._keyboard_binding_hold.binding_value)
        binding_label = keyboard_binding_label(self.controls.keyboard_binding_for_action(action_key))
        self._keyboard_binding_hold = None
        self._binding_capture = None
        self._build_keyboard_bindings_menu()
        self.audio.play(_sx(58), channel=_sx(180))
        self.speaker.speak(_sx(1063).format(action_label(action_key), binding_label), interrupt=True)

    def _update_keyboard_binding_hold(self, delta_time: float) -> None:
        hold_state = self._keyboard_binding_hold
        if hold_state is None:
            return
        if not hold_state.required_keys.issubset(self._pressed_keys):
            self._fail_keyboard_binding_hold()
            return
        hold_state.remaining_seconds = max(0.0, hold_state.remaining_seconds - float(delta_time))
        while hold_state.next_ding_mark >= 1 and hold_state.remaining_seconds <= float(hold_state.next_ding_mark):
            pitch = BINDING_CAPTURE_DING_PITCHES.get(hold_state.next_ding_mark, 1.0)
            self.audio.play(_sx(57), channel=_sx(180), pitch=pitch)
            hold_state.next_ding_mark -= 1
        if hold_state.remaining_seconds > 0:
            return
        self._complete_keyboard_binding_capture()

    def _complete_controller_binding_capture(self, binding: str) -> None:
        if self._binding_capture is None:
            return
        action_key = self._binding_capture.action_key
        family = self.controls.current_controller_family()
        self.controls.update_controller_binding(family, action_key, binding)
        self._binding_capture = None
        self._build_controller_bindings_menu()
        binding_label = controller_binding_label(self.controls.controller_binding_for_action(action_key, family), family)
        self.speaker.speak(_sx(1063).format(action_label(action_key), binding_label), interrupt=True)

    def _handle_keyboard_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            self._pressed_keys.add(int(event.key))
            if self._binding_capture is not None and self._binding_capture.device == _sx(563):
                if event.key == pygame.K_ESCAPE:
                    self._cancel_binding_capture()
                    return
                if self._keyboard_binding_hold is None:
                    self._start_keyboard_binding_hold_capture(event)
                    return
                if frozenset(self._pressed_keys) != self._keyboard_binding_hold.required_keys:
                    self._fail_keyboard_binding_hold()
                return
            translated_key = self.controls.translate_keyboard_key(event.key, self._input_context(), int(getattr(event, _sx(1795), pygame.key.get_mods())))
            if translated_key is None:
                return
            self._process_translated_keydown(translated_key)
            return
        if event.type == pygame.KEYUP:
            self._pressed_keys.discard(int(event.key))
            if self._binding_capture is not None and self._binding_capture.device == _sx(563):
                if self._keyboard_binding_hold is not None:
                    self._fail_keyboard_binding_hold()
                return
            translated_key = self.controls.translate_keyboard_key(event.key, self._input_context(), int(getattr(event, _sx(1795), pygame.key.get_mods())))
            if translated_key is None:
                return
            self._process_translated_keyup(translated_key)

    def _handle_window_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.VIDEORESIZE:
            width = max(MIN_WINDOW_WIDTH, int(getattr(event, _sx(382), MIN_WINDOW_WIDTH)))
            height = max(MIN_WINDOW_HEIGHT, int(getattr(event, _sx(1796), MIN_WINDOW_HEIGHT)))
            self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
            return
        if event.type == pygame.WINDOWSIZECHANGED:
            surface = pygame.display.get_surface()
            if surface is not None:
                self.screen = surface
            return
        if self._is_window_focus_loss_event(event):
            self._pause_gameplay_for_focus_loss()

    def _is_window_focus_loss_event(self, event: pygame.event.Event) -> bool:
        focus_lost_event = getattr(pygame, _sx(1050), None)
        minimized_event = getattr(pygame, _sx(1052), None)
        if focus_lost_event is not None and event.type == focus_lost_event:
            return True
        if minimized_event is not None and event.type == minimized_event:
            return True
        if event.type != pygame.ACTIVEEVENT:
            return False
        gain = int(getattr(event, _sx(1374), 1))
        state = int(getattr(event, _sx(1375), 0))
        focus_mask = int(getattr(pygame, _sx(1797), 0)) | int(getattr(pygame, _sx(1798), 0)) | int(getattr(pygame, _sx(1663), 0))
        return gain == 0 and bool(state & focus_mask)

    def _pause_active_run(self) -> bool:
        if not self.state.running or self.state.paused or self.active_menu is not None:
            return False
        self.state.paused = True
        self._set_active_menu(self.pause_menu)
        self.audio.play(_sx(55), channel=_sx(180))
        return True

    def _pause_gameplay_for_focus_loss(self) -> None:
        if not self._pause_on_focus_loss_enabled():
            return
        self._pause_active_run()

    def _handle_controller_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.CONTROLLERDEVICEADDED:
            connected = self.controls.register_added_controller(getattr(event, _sx(1664), None))
            if connected is not None:
                self._announce_controller_connected(connected.name, connected.family)
            return
        if event.type == pygame.CONTROLLERDEVICEREMOVED:
            disconnected = self.controls.handle_device_removed(getattr(event, _sx(1665), None))
            if disconnected is not None:
                self._announce_controller_disconnected(disconnected.name, disconnected.family)
            return
        if event.type == pygame.CONTROLLERDEVICEREMAPPED:
            self.controls.refresh_connected_controllers()
            self._refresh_control_menus()
            return
        if self._binding_capture is not None and self._binding_capture.device == _sx(565):
            binding = self.controls.capture_controller_binding(event)
            if binding is not None:
                self._complete_controller_binding_capture(binding)
            return
        for translated_key, pressed in self.controls.translate_controller_event(event, self._input_context()):
            if pressed:
                self._process_translated_keydown(translated_key)
            else:
                self._process_translated_keyup(translated_key)

    def _add_run_coins(self, amount: int) -> None:
        if amount <= 0:
            return
        if self._practice_mode_active:
            return
        adjusted_amount = int(amount)
        if self._season_imprint_matches(_sx(1064)):
            adjusted_amount += max(1, int(round(adjusted_amount * 0.1)))
        self.state.coins += adjusted_amount
        self._record_achievement_metric(_sx(369), adjusted_amount)
        if self._run_rewards_committed:
            self.settings[_sx(333)] = int(self.settings.get(_sx(333), 0)) + adjusted_amount

    def run(self) -> None:
        running = True
        while running:
            delta_time = self.clock.tick(60) / 1000.0
            self._update_pending_menu_announcement(delta_time)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._request_exit()
                elif event.type in (pygame.VIDEORESIZE, pygame.WINDOWSIZECHANGED, getattr(pygame, _sx(1050), -1), getattr(pygame, _sx(1052), -1), pygame.ACTIVEEVENT):
                    self._handle_window_event(event)
                elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
                    self._handle_keyboard_event(event)
                elif event.type in (pygame.CONTROLLERDEVICEADDED, pygame.CONTROLLERDEVICEREMOVED, pygame.CONTROLLERDEVICEREMAPPED, pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP, pygame.CONTROLLERAXISMOTION):
                    self._handle_controller_event(event)
            if not self._exit_requested and self.active_menu is not None:
                self._update_menu_repeat(delta_time)
                self._update_learn_sound_preview(delta_time)
                self._update_update_install_state()
                self._update_keyboard_binding_hold(delta_time)
                self._update_pending_wheel_spin_reward(delta_time)
            if not self._exit_requested:
                self._update_leaderboard_operation_state()
            if not self._exit_requested and self.active_menu is None:
                if not self.state.paused:
                    self._update_game(delta_time)
            self.audio.update(delta_time)
            if self.active_menu is None:
                self._draw_game()
            else:
                self._draw_menu(self.active_menu)
            pygame.display.flip()
            if self._exit_requested and self.audio.music_is_idle():
                running = False
        config_module.save_settings(self.settings)

    def _update_pending_menu_announcement(self, delta_time: float) -> None:
        if self._pending_menu_announcement is None:
            return
        menu, remaining, announce_opening = self._pending_menu_announcement
        remaining = max(0.0, remaining - float(delta_time))
        if remaining > 0:
            self._pending_menu_announcement = (menu, remaining, announce_opening)
            return
        self._pending_menu_announcement = None
        if self.active_menu is not menu:
            return
        if announce_opening:
            self.speaker.speak(menu._opening_announcement(), interrupt=True)
            return
        menu._announce_current()

    def _update_pending_wheel_spin_reward(self, delta_time: float) -> None:
        if self._pending_wheel_spin_reward is None:
            return
        self._pending_wheel_spin_reward_delay = max(0.0, float(self._pending_wheel_spin_reward_delay) - float(delta_time))
        if self._pending_wheel_spin_reward_delay > 0:
            return
        reward_data = dict(self._pending_wheel_spin_reward)
        self._pending_wheel_spin_reward = None
        self._pending_wheel_spin_reward_delay = 0.0
        sync_payload = reward_data.get(_sx(1065))
        if isinstance(sync_payload, dict):
            self._apply_special_sync_payload(sync_payload)
            self._refresh_wheel_menu_labels()
        amount = max(1, int(reward_data.get(_sx(593), 1) or 1))
        item_label = str(reward_data.get(_sx(1439)) or _sx(871)).strip() or _sx(871)
        self.audio.play(_sx(98), channel=_sx(180))
        self.audio.play(_sx(108), channel=_sx(1250))
        self.speaker.speak(_sx(1066).format(amount, item_label, _sx(2) if amount == 1 else _sx(294)), interrupt=True)

    def _handle_active_menu_key(self, key: int) -> bool:
        if self.active_menu is None:
            return True
        if self._binding_capture is not None:
            if key == pygame.K_ESCAPE:
                self._cancel_binding_capture()
            else:
                self._play_menu_feedback(_sx(52))
            return True
        if self.active_menu == self.options_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_selected_option(-1 if key == pygame.K_LEFT else 1)
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.options_menu.items[self.options_menu.index].action
                if selected_action in {_sx(429), _sx(1384), _sx(1194), _sx(1383), _sx(1195), _sx(1382)}:
                    return self._handle_menu_action(selected_action)
                return True
        if self.active_menu == self.sapi_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_selected_option(-1 if key == pygame.K_LEFT else 1)
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.sapi_menu.items[self.sapi_menu.index].action
                if selected_action == _sx(429):
                    return self._handle_menu_action(selected_action)
                return True
        if self.active_menu == self.announcements_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_selected_option(-1 if key == pygame.K_LEFT else 1)
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.announcements_menu.items[self.announcements_menu.index].action
                if selected_action == _sx(429):
                    return self._handle_menu_action(selected_action)
                return True
        if self.active_menu == self.controls_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                selected_action = self.controls_menu.items[self.controls_menu.index].action
                if selected_action == _sx(984):
                    self._cycle_selected_binding_device(-1 if key == pygame.K_LEFT else 1)
                else:
                    self._play_menu_feedback(_sx(52))
                return True
        if self.active_menu == self.learn_sounds_menu:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.learn_sounds_menu.items[self.learn_sounds_menu.index].action
                if selected_action == _sx(429):
                    return self._handle_menu_action(_sx(429))
                entry = self._learn_sound_entries_by_action.get(selected_action)
                if entry is not None:
                    self._play_learn_sound_preview(entry)
                return True
            previous_index = self.learn_sounds_menu.index
            action = self.learn_sounds_menu.handle_key(key)
            if self.learn_sounds_menu.index != previous_index:
                self._refresh_learn_sound_description()
            if action:
                return self._handle_menu_action(action)
            return True
        action = self.active_menu.handle_key(key)
        if action:
            return self._handle_menu_action(action)
        return True

    def _handle_menu_action(self, action: str) -> bool:
        if action == _sx(1067):
            if self.active_menu == self.revive_menu:
                self._finish_run_loss(_sx(1009))
                return True
            if self.active_menu == self.game_over_menu:
                self.active_menu.index = 0
                self.speaker.speak(self.active_menu.items[0].label, interrupt=True)
                return True
            if self.active_menu == self.update_menu:
                return False
            if self.active_menu == self.main_menu:
                if not self._exit_confirmation_enabled():
                    return False
                self._set_active_menu(self.exit_confirm_menu, start_index=self._menu_index_for_action(self.exit_confirm_menu, _sx(1432)))
                return True
            if self.active_menu == self.controls_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1384)))
                return True
            if self.active_menu == self.options_menu:
                return_menu = self._options_return_menu or self.main_menu
                start_index = self._menu_index_for_action(self.pause_menu, _sx(1421)) if return_menu == self.pause_menu else None
                self._set_active_menu(return_menu, start_index=start_index)
                return True
            if self.active_menu == self.sapi_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1194)))
                return True
            if self.active_menu == self.announcements_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1383)))
                return True
            if self.active_menu in {self.keyboard_bindings_menu, self.controller_bindings_menu}:
                self._build_controls_menu()
                self._set_active_menu(self.controls_menu)
                return True
            if self.active_menu == self.pause_menu:
                self.state.paused = False
                self._set_active_menu(None)
                self.audio.play(_sx(55), channel=_sx(180))
                self.speaker.speak(_sx(1577), interrupt=True)
                return True
            if self.active_menu == self.pause_confirm_menu:
                self._set_active_menu(self.pause_menu, start_index=self._menu_index_for_action(self.pause_menu, _sx(1422)))
                return True
            if self.active_menu == self.leaderboard_logout_confirm_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1382)))
                return True
            if self.active_menu == self.publish_confirm_menu:
                self._set_active_menu(self.game_over_menu)
                return True
            if self.active_menu == self.purchase_confirm_menu:
                self._resolve_pending_purchase(accepted=False)
                return True
            if self.active_menu == self.exit_confirm_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(768)))
                return True
            if self.active_menu == self.help_topic_menu:
                self._set_active_menu(self.howto_menu)
                return True
            if self.active_menu == self.events_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1270)))
                return True
            if self.active_menu == self.wheel_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(99)))
                return True
            if self.active_menu == self.event_shop_menu:
                self._refresh_events_menu_labels()
                self._set_active_menu(self.events_menu, start_index=self._menu_index_for_action(self.events_menu, _sx(1215)))
                return True
            if self.active_menu == self.missions_hub_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1272)))
                return True
            if self.active_menu in {self.mission_set_menu, self.quests_menu, self.achievements_menu}:
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu)
                return True
            if self.active_menu == self.me_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1274)))
                return True
            if self.active_menu == self.server_status_menu:
                self._cancel_leaderboard_operation()
                if self._leaderboard_return_menu is not None:
                    self._set_active_menu(self._leaderboard_return_menu)
                else:
                    self._set_active_menu(self.main_menu)
                return True
            if self.active_menu == self.leaderboard_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1278)))
                return True
            if self.active_menu == self.leaderboard_profile_menu:
                self._set_active_menu(self.leaderboard_menu)
                return True
            if self.active_menu == self.leaderboard_run_detail_menu:
                self._set_active_menu(self.leaderboard_profile_menu)
                return True
            if self.active_menu == self.issue_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1281)))
                return True
            if self.active_menu == self.issue_compose_menu:
                self._refresh_issue_menu()
                self._set_active_menu(self.issue_menu, start_index=self._menu_index_for_action(self.issue_menu, _sx(1073)))
                return True
            if self.active_menu == self.issue_detail_menu:
                self._set_active_menu(self.issue_menu)
                return True
            if self.active_menu == self.item_upgrade_detail_menu:
                self._refresh_item_upgrade_menu_labels()
                self._set_active_menu(self.item_upgrade_menu)
                return True
            if self.active_menu == self.item_upgrade_menu:
                return_menu = self._meta_return_menu or self.shop_menu
                if return_menu == self.shop_menu:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, _sx(1245)))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1245)))
                return True
            if self.active_menu == self.character_detail_menu:
                self._refresh_character_menu_labels()
                self._set_active_menu(self.character_menu)
                return True
            if self.active_menu == self.character_menu:
                return_menu = self._meta_return_menu or self.shop_menu
                if return_menu == self.shop_menu:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, _sx(1401)))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1243)))
                return True
            if self.active_menu == self.board_detail_menu:
                self._refresh_board_menu_labels()
                self._set_active_menu(self.board_menu)
                return True
            if self.active_menu == self.board_menu:
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1244)))
                return True
            if self.active_menu == self.collection_menu:
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1246)))
                return True
            if self.active_menu == self.whats_new_menu:
                self._set_active_menu(self.main_menu)
                return True
            self._set_active_menu(self.main_menu)
            return True
        if self.active_menu == self.main_menu:
            if action == _sx(430):
                self._pending_practice_setup = False
                self.selected_headstarts = 0
                self.selected_score_boosters = 0
                self._refresh_loadout_menu_labels()
                self._set_active_menu(self.loadout_menu)
                return True
            if action == _sx(1268):
                self._pending_practice_setup = True
                self.selected_headstarts = 0
                self.selected_score_boosters = 0
                self._refresh_loadout_menu_labels()
                self._set_active_menu(self.loadout_menu)
                return True
            if action == _sx(1270):
                self._refresh_events_menu_labels()
                self._set_active_menu(self.events_menu)
                return True
            if action == _sx(1272):
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu)
                return True
            if action == _sx(1274):
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
            if action == _sx(1283):
                self._open_info_dialog(load_whats_new_content(), self.whats_new_menu)
                return True
            if action == _sx(1276):
                self._refresh_shop_menu_labels()
                self._set_active_menu(self.shop_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
            if action == _sx(1278):
                self._open_leaderboard()
                return True
            if action == _sx(99):
                self._open_wheel_menu()
                return True
            if action == _sx(1281):
                self._open_issue_reports()
                return True
            if action == _sx(1285):
                self._options_return_menu = self.main_menu
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu)
                return True
            if action == _sx(1287):
                self._showing_upgrade_help = False
                self._refresh_howto_menu_labels()
                self._set_active_menu(self.howto_menu)
                return True
            if action == _sx(1289):
                self._set_active_menu(self.learn_sounds_menu)
                return True
            if action == _sx(1292):
                self._check_for_updates(announce_result=True)
                return True
            if action == _sx(768):
                if not self._exit_confirmation_enabled():
                    return False
                self._set_active_menu(self.exit_confirm_menu, start_index=self._menu_index_for_action(self.exit_confirm_menu, _sx(1432)))
                return True
        if self.active_menu == self.loadout_menu:
            if action == _sx(429):
                self._pending_practice_setup = False
                self._refresh_loadout_menu_labels()
                self._set_active_menu(self.main_menu)
                return True
            if action == _sx(1177):
                self.speaker.speak(self._loadout_board_label(), interrupt=True)
                return True
            if action == _sx(1178):
                owned = int(self.settings.get(_sx(336), 0))
                if owned <= 0:
                    self.audio.play(_sx(52), channel=_sx(180))
                    self.speaker.speak(_sx(1799), interrupt=True)
                    return True
                self.selected_headstarts = (self.selected_headstarts + 1) % (clamp_headstart_uses(owned) + 1)
                self.audio.play(_sx(56), channel=_sx(180))
                self._refresh_loadout_menu_labels()
                self.speaker.speak(self.loadout_menu.items[self._menu_index_for_action(self.loadout_menu, _sx(1178))].label, interrupt=True)
                return True
            if action == _sx(1179):
                owned = int(self.settings.get(_sx(337), 0))
                if owned <= 0:
                    self.audio.play(_sx(52), channel=_sx(180))
                    self.speaker.speak(_sx(1800), interrupt=True)
                    return True
                self.selected_score_boosters = (self.selected_score_boosters + 1) % (min(3, owned) + 1)
                self.audio.play(_sx(56), channel=_sx(180))
                self._refresh_loadout_menu_labels()
                self.speaker.speak(self.loadout_menu.items[self._menu_index_for_action(self.loadout_menu, _sx(1179))].label, interrupt=True)
                return True
            if action.startswith(_sx(1377)):
                item_key = action.split(_sx(560), 1)[1]
                self._toggle_special_item_loadout(item_key)
                return True
            if action == _sx(1110):
                self._edit_practice_hazard_target()
                return True
            if action == _sx(1378):
                self.settings[_sx(325)] = not self._practice_speed_scaling_enabled()
                self.audio.play(_sx(56), channel=_sx(180))
                self._refresh_loadout_menu_labels()
                self.speaker.speak(self.loadout_menu.items[self._menu_index_for_action(self.loadout_menu, _sx(1378))].label, interrupt=True)
                return True
            if action == _sx(1379):
                self.start_run(practice_mode=self._pending_practice_setup)
                return True
        if self.active_menu == self.events_menu:
            if action == _sx(1213):
                if self.events_menu.items:
                    item = self.events_menu.items[min(self.events_menu.index, len(self.events_menu.items) - 1)]
                    self.speaker.speak(item.label, interrupt=True)
                return True
            if action == _sx(1215):
                self._refresh_event_shop_menu_labels()
                self._set_active_menu(self.event_shop_menu)
                return True
            if action == _sx(1216):
                if self._apply_meta_reward(claim_daily_high_score_reward(self.settings), _sx(1666)):
                    self.audio.play(_sx(100), channel=_sx(180))
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == _sx(1217):
                if self._apply_meta_reward(claim_coin_meter_reward(self.settings), _sx(1667)):
                    self.audio.play(_sx(100), channel=_sx(180))
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == _sx(1219):
                reward = claim_daily_gift(self.settings)
                if reward is not None:
                    self.audio.play(_sx(98), channel=_sx(180))
                if self._apply_meta_reward(reward, _sx(1668)):
                    self._refresh_events_menu_labels()
                    self._refresh_shop_menu_labels()
                    self._persist_settings()
                return True
            if action == _sx(1220):
                if self._apply_meta_reward(claim_login_calendar_reward(self.settings), _sx(1669)):
                    self.audio.play(_sx(100), channel=_sx(180))
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == _sx(429):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1270)))
                return True
            return True
        if self.active_menu == self.wheel_menu:
            if action == _sx(1175):
                if self.wheel_menu.items:
                    item = self.wheel_menu.items[min(self.wheel_menu.index, len(self.wheel_menu.items) - 1)]
                    self.speaker.speak(item.label, interrupt=True)
                return True
            if action == _sx(1176):
                self._request_weekly_wheel_spin()
                return True
            if action.startswith(_sx(1380)):
                item_key = action.split(_sx(560), 1)[1]
                effect = SPECIAL_ITEM_EFFECT_TEXT.get(item_key, _sx(1670))
                self.speaker.speak(_sx(988).format(self._special_item_label(item_key), effect), interrupt=True)
                return True
            if action == _sx(429):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(99)))
                return True
            return True
        if self.active_menu == self.event_shop_menu:
            if action == _sx(1221):
                self._run_or_confirm_purchase(self._buy_event_shop_character, return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1221)))
                return True
            if action == _sx(1222):
                self._run_or_confirm_purchase(self._buy_event_shop_board, return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1222)))
                return True
            if action == _sx(1223):
                self._run_or_confirm_purchase(lambda: self._buy_event_shop_reward(EVENT_SHOP_KEY_COST, {_sx(592): _sx(569), _sx(593): 1}, _sx(804)), return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1223)))
                return True
            if action == _sx(1224):
                self._run_or_confirm_purchase(lambda: self._buy_event_shop_reward(EVENT_SHOP_HOVERBOARD_PACK_COST, {_sx(592): _sx(594), _sx(593): 2}, _sx(804)), return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1224)))
                return True
            if action == _sx(1225):
                self._run_or_confirm_purchase(lambda: self._buy_event_shop_reward(EVENT_SHOP_HEADSTART_COST, {_sx(592): _sx(595), _sx(593): 1}, _sx(804)), return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1225)))
                return True
            if action == _sx(1226):
                self._run_or_confirm_purchase(lambda: self._buy_event_shop_reward(EVENT_SHOP_SCORE_BOOSTER_COST, {_sx(592): _sx(596), _sx(593): 1}, _sx(804)), return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1226)))
                return True
            if action == _sx(1227):
                self._run_or_confirm_purchase(lambda: self._buy_event_shop_reward(EVENT_SHOP_SUPER_BOX_COST, {_sx(592): _sx(598), _sx(593): 1}, _sx(804)), return_menu=self.event_shop_menu, return_index=self._menu_index_for_action(self.event_shop_menu, _sx(1227)))
                return True
            if action == _sx(429):
                self._refresh_events_menu_labels()
                self._set_active_menu(self.events_menu, start_index=self._menu_index_for_action(self.events_menu, _sx(1215)))
                return True
            return True
        if self.active_menu == self.missions_hub_menu:
            if action == _sx(1234):
                self._refresh_quest_menu_labels()
                self._set_active_menu(self.quests_menu)
                return True
            if action == _sx(1235):
                self._refresh_mission_set_menu_labels()
                self._set_active_menu(self.mission_set_menu)
                return True
            if action == _sx(1236):
                self._refresh_achievements_menu_labels()
                self._set_active_menu(self.achievements_menu)
                return True
            if action == _sx(429):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1272)))
                return True
            return True
        if self.active_menu == self.mission_set_menu:
            if action == _sx(429):
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu, start_index=self._menu_index_for_action(self.missions_hub_menu, _sx(1235)))
                return True
            return True
        if self.active_menu == self.quests_menu:
            if action == _sx(1240):
                if self._apply_meta_reward(claim_meter_reward(self.settings), _sx(1671)):
                    self.audio.play(_sx(100), channel=_sx(180))
                    self._refresh_quest_menu_labels()
                    self._persist_settings()
                return True
            if action.startswith(_sx(1381)):
                quest_key = action.split(_sx(560), 1)[1]
                quest = claim_quest(self.settings, quest_key)
                if quest is None:
                    self.audio.play(_sx(52), channel=_sx(180))
                    self.speaker.speak(_sx(1801), interrupt=True)
                    return True
                self.audio.play(_sx(100), channel=_sx(180))
                self.audio.play(_sx(108), channel=_sx(1250))
                self.speaker.speak(_sx(1672).format(quest.label, quest.sneaker_reward), interrupt=True)
                self._refresh_quest_menu_labels()
                self._refresh_missions_hub_menu_labels()
                self._persist_settings()
                return True
            if action == _sx(1242):
                self._reset_daily_progress()
                return True
            if action == _sx(429):
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu, start_index=self._menu_index_for_action(self.missions_hub_menu, _sx(1234)))
                return True
            return True
        if self.active_menu == self.me_menu:
            if action == _sx(1243):
                self._meta_return_menu = self.me_menu
                self._refresh_character_menu_labels()
                self._set_active_menu(self.character_menu)
                return True
            if action == _sx(1244):
                self._meta_return_menu = self.me_menu
                self._refresh_board_menu_labels()
                self._set_active_menu(self.board_menu)
                return True
            if action == _sx(1245):
                self._meta_return_menu = self.me_menu
                self._refresh_item_upgrade_menu_labels()
                self._set_active_menu(self.item_upgrade_menu)
                return True
            if action == _sx(1246):
                self._refresh_collection_menu_labels()
                self._set_active_menu(self.collection_menu)
                return True
            if action == _sx(429):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1274)))
                return True
            return True
        if self.active_menu == self.options_menu:
            if action == _sx(1195):
                self._prompt_and_authenticate_leaderboard_account()
                return True
            if action == _sx(1382):
                self._set_active_menu(self.leaderboard_logout_confirm_menu, start_index=self._menu_index_for_action(self.leaderboard_logout_confirm_menu, _sx(1426)))
                return True
            if action == _sx(1194):
                self._refresh_sapi_menu_labels()
                self._set_active_menu(self.sapi_menu)
                return True
            if action == _sx(1383):
                self._refresh_announcements_menu_labels()
                self._set_active_menu(self.announcements_menu)
                return True
            if action == _sx(1384):
                self._selected_binding_device = _sx(565) if self.controls.active_controller() is not None else _sx(563)
                self._refresh_control_menus()
                self._set_active_menu(self.controls_menu)
                return True
            if action == _sx(429):
                self.audio.play(_sx(55), channel=_sx(180))
                return_menu = self._options_return_menu or self.main_menu
                start_index = self._menu_index_for_action(self.pause_menu, _sx(1421)) if return_menu == self.pause_menu else None
                self._set_active_menu(return_menu, start_index=start_index)
                return True
            return True
        if self.active_menu == self.sapi_menu:
            if action == _sx(429):
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1194)))
                return True
            return True
        if self.active_menu == self.announcements_menu:
            if action == _sx(429):
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1383)))
                return True
            return True
        if self.active_menu == self.controls_menu:
            if action == _sx(1253):
                self.speaker.speak(_sx(1673).format(self.controls.current_input_label(), self.controls.current_controller_label()), interrupt=True)
                return True
            if action == _sx(984):
                self.speaker.speak(self.controls_menu.items[self.controls_menu.index].label, interrupt=True)
                return True
            if action == _sx(1256):
                if self._selected_binding_device == _sx(565):
                    if self.controls.active_controller() is None:
                        self._play_menu_feedback(_sx(52))
                        self.speaker.speak(_sx(1805), interrupt=True)
                        return True
                    self._build_controller_bindings_menu()
                    self._set_active_menu(self.controller_bindings_menu)
                    return True
                self._build_keyboard_bindings_menu()
                self._set_active_menu(self.keyboard_bindings_menu)
                return True
            if action == _sx(1258):
                if self._selected_binding_device == _sx(565):
                    if self.controls.active_controller() is None:
                        self._play_menu_feedback(_sx(52))
                        self.speaker.speak(_sx(1805), interrupt=True)
                        return True
                    family = self.controls.current_controller_family()
                    self.controls.reset_controller_bindings(family)
                    self._build_controls_menu()
                    self._play_menu_feedback(_sx(56))
                    self.speaker.speak(_sx(1675).format(family_label(family)), interrupt=True)
                    return True
                self.controls.reset_keyboard_bindings()
                self._build_controls_menu()
                self._play_menu_feedback(_sx(56))
                self.speaker.speak(_sx(1674), interrupt=True)
                return True
            if action == _sx(429):
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1384)))
                return True
        if self.active_menu == self.keyboard_bindings_menu:
            if action == _sx(1260):
                self.controls.reset_keyboard_bindings()
                self._build_keyboard_bindings_menu()
                self._play_menu_feedback(_sx(56))
                self.speaker.speak(_sx(1674), interrupt=True)
                return True
            if action.startswith(_sx(1385)):
                self._begin_binding_capture(_sx(563), action.split(_sx(560), 1)[1])
                return True
            if action == _sx(429):
                self._build_controls_menu()
                self._set_active_menu(self.controls_menu, start_index=2)
                return True
        if self.active_menu == self.controller_bindings_menu:
            if action == _sx(1264):
                family = self.controls.current_controller_family()
                self.controls.reset_controller_bindings(family)
                self._build_controller_bindings_menu()
                self._play_menu_feedback(_sx(56))
                self.speaker.speak(_sx(1675).format(family_label(family)), interrupt=True)
                return True
            if action.startswith(_sx(1386)):
                if self.controls.active_controller() is None:
                    self._play_menu_feedback(_sx(52))
                    self.speaker.speak(_sx(1805), interrupt=True)
                    return True
                self._begin_binding_capture(_sx(565), action.split(_sx(560), 1)[1])
                return True
            if action == _sx(429):
                self._build_controls_menu()
                self._set_active_menu(self.controls_menu, start_index=2)
                return True
        if self.active_menu == self.update_menu:
            if action == _sx(429):
                self._set_active_menu(self.main_menu)
                return True
            if action == _sx(995):
                self._begin_update_install()
                return True
            if action == _sx(764):
                return True
            if action == _sx(766):
                if self._update_restart_script_path and self.updater.launch_restart_script(self._update_restart_script_path):
                    self.speaker.speak(_sx(1806), interrupt=True)
                    return False
                self.speaker.speak(_sx(1676), interrupt=True)
                return False
            if action == _sx(757):
                release = self._latest_update_result.release if self._latest_update_result is not None else None
                opened = self.updater.open_release_page(release)
                if opened:
                    self.speaker.speak(_sx(1807), interrupt=True)
                    return True
                self._play_menu_feedback(_sx(52))
                self.speaker.speak(_sx(1677), interrupt=True)
                return True
            if action == _sx(768):
                return False
        if self.active_menu == self.server_status_menu:
            if action == _sx(429):
                self._cancel_leaderboard_operation()
                if self._leaderboard_return_menu is not None:
                    self._set_active_menu(self._leaderboard_return_menu)
                else:
                    self._set_active_menu(self.main_menu)
                return True
            self.speaker.speak(self.server_status_menu.items[0].label, interrupt=True)
            return True
        if self.active_menu == self.leaderboard_menu:
            if action == _sx(429):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1278)))
                return True
            if action == _sx(1387):
                self._cycle_leaderboard_period()
                return True
            if action == _sx(1388):
                self._cycle_leaderboard_difficulty()
                return True
            if action == _sx(1083):
                self._open_leaderboard(force_refresh=True)
                return True
            if action.startswith(_sx(1389)):
                self._open_leaderboard_profile(action.split(_sx(560), 1)[1])
                return True
            if action == _sx(1390):
                self.speaker.speak(self.leaderboard_menu.items[self.leaderboard_menu.index].label, interrupt=True)
                return True
        if self.active_menu == self.leaderboard_profile_menu:
            if action == _sx(429):
                self._set_active_menu(self.leaderboard_menu)
                return True
            if action.startswith(_sx(1391)):
                self._open_leaderboard_run_detail(action.split(_sx(560), 1)[1])
                return True
            self.speaker.speak(self.leaderboard_profile_menu.items[self.leaderboard_profile_menu.index].label, interrupt=True)
            return True
        if self.active_menu == self.leaderboard_run_detail_menu:
            if action == _sx(429):
                self._set_active_menu(self.leaderboard_profile_menu)
                return True
            self.speaker.speak(self.leaderboard_run_detail_menu.items[self.leaderboard_run_detail_menu.index].label, interrupt=True)
            return True
        if self.active_menu == self.issue_menu:
            if action == _sx(429):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(1281)))
                return True
            if action == _sx(1073):
                self._begin_issue_submission()
                return True
            if action == _sx(1392):
                self._cycle_issue_status_filter()
                return True
            if action == _sx(1101):
                self._change_issue_page(-1)
                return True
            if action == _sx(1102):
                self._change_issue_page(1)
                return True
            if action == _sx(1100):
                self._open_issue_reports(force_refresh=True)
                return True
            if action.startswith(_sx(1393)):
                self._open_issue_report_detail(action.split(_sx(560), 1)[1])
                return True
            self.speaker.speak(self.issue_menu.items[self.issue_menu.index].label, interrupt=True)
            return True
        if self.active_menu == self.issue_compose_menu:
            if action == _sx(429):
                self._refresh_issue_menu()
                self._set_active_menu(self.issue_menu, start_index=self._menu_index_for_action(self.issue_menu, _sx(1073)))
                return True
            if action == _sx(1108):
                self._edit_issue_draft_field(_sx(1106))
                return True
            if action == _sx(1109):
                self._edit_issue_draft_field(_sx(1495))
                return True
            if action == _sx(1394):
                self._submit_issue_draft()
                return True
            self.speaker.speak(self.issue_compose_menu.items[self.issue_compose_menu.index].label, interrupt=True)
            return True
        if self.active_menu == self.issue_detail_menu:
            if action == _sx(429):
                self._set_active_menu(self.issue_menu)
                return True
            if action == _sx(1395):
                return self._copy_menu_text(self.issue_detail_menu.items[self.issue_detail_menu.index].label, _sx(1678))
            if action == _sx(1396):
                return self._copy_menu_text(self._selected_info_copy_all_text(self.issue_detail_menu), self._selected_info_copy_all_message(self.issue_detail_menu))
            self.speaker.speak(self.issue_detail_menu.items[self.issue_detail_menu.index].label, interrupt=True)
            return True
        if self.active_menu == self.shop_menu:
            if action == _sx(429):
                self._set_active_menu(self.main_menu)
                return True
            if action == _sx(1397):
                self._run_or_confirm_purchase(lambda: self._purchase_shop_item(_sx(594)), return_menu=self.shop_menu, return_index=self._menu_index_for_action(self.shop_menu, _sx(1397)))
                return True
            if action == _sx(1398):
                self._run_or_confirm_purchase(lambda: self._purchase_shop_item(_sx(21)), return_menu=self.shop_menu, return_index=self._menu_index_for_action(self.shop_menu, _sx(1398)))
                return True
            if action == _sx(1399):
                self._run_or_confirm_purchase(lambda: self._purchase_shop_item(_sx(595)), return_menu=self.shop_menu, return_index=self._menu_index_for_action(self.shop_menu, _sx(1399)))
                return True
            if action == _sx(1400):
                self._run_or_confirm_purchase(lambda: self._purchase_shop_item(_sx(596)), return_menu=self.shop_menu, return_index=self._menu_index_for_action(self.shop_menu, _sx(1400)))
                return True
            if action == _sx(1219):
                reward = claim_daily_gift(self.settings)
                if reward is not None:
                    self.audio.play(_sx(98), channel=_sx(180))
                if self._apply_meta_reward(reward, _sx(1668)):
                    self._refresh_shop_menu_labels()
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == _sx(1245):
                self._meta_return_menu = self.shop_menu
                self._refresh_item_upgrade_menu_labels()
                self._set_active_menu(self.item_upgrade_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
            if action == _sx(1401):
                self._meta_return_menu = self.shop_menu
                self._refresh_character_menu_labels()
                self._set_active_menu(self.character_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
        if self.active_menu == self.item_upgrade_menu:
            if action == _sx(429):
                if self._meta_return_menu in {None, self.shop_menu}:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, _sx(1245)))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1245)))
                return True
            if action.startswith(_sx(1402)):
                self._refresh_item_upgrade_detail_menu_labels(action.split(_sx(560), 1)[1])
                self._set_active_menu(self.item_upgrade_detail_menu)
                return True
        if self.active_menu == self.item_upgrade_detail_menu:
            if action == _sx(429):
                self._refresh_item_upgrade_menu_labels()
                upgrade_keys = [definition.key for definition in item_upgrade_definitions()]
                try:
                    start_index = upgrade_keys.index(self._item_upgrade_detail_key)
                except ValueError:
                    start_index = 0
                self._set_active_menu(self.item_upgrade_menu, start_index=start_index)
                return True
            if action.startswith(_sx(1403)):
                definition = item_upgrade_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1679).format(definition.name, self._item_upgrade_status_label(definition.key)), interrupt=True)
                return True
            if action.startswith(_sx(1404)):
                definition = item_upgrade_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1679).format(definition.name, self._item_upgrade_effect_label(definition.key)), interrupt=True)
                return True
            if action.startswith(_sx(1196)):
                key = action.split(_sx(560), 1)[1]
                self._run_or_confirm_purchase(lambda key=key: self._purchase_item_upgrade(key), return_menu=self.item_upgrade_detail_menu, return_index=self.item_upgrade_detail_menu.index)
                return True
            if action.startswith(_sx(1197)):
                definition = item_upgrade_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1335).format(definition.name), interrupt=True)
                return True
        if self.active_menu == self.character_menu:
            if action == _sx(429):
                if self._meta_return_menu in {None, self.shop_menu}:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, _sx(1401)))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1243)))
                return True
            if action.startswith(_sx(1405)):
                self._refresh_character_detail_menu_labels(action.split(_sx(560), 1)[1])
                self._set_active_menu(self.character_detail_menu)
                return True
        if self.active_menu == self.character_detail_menu:
            if action == _sx(429):
                self._refresh_character_menu_labels()
                character_keys = [definition.key for definition in character_definitions()]
                try:
                    start_index = character_keys.index(self._character_detail_key)
                except ValueError:
                    start_index = 0
                self._set_active_menu(self.character_menu, start_index=start_index)
                return True
            if action.startswith(_sx(1406)):
                definition = character_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1679).format(definition.name, self._character_status_label(definition.key)), interrupt=True)
                return True
            if action.startswith(_sx(1407)):
                definition = character_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1680).format(definition.name, definition.description, character_perk_summary(definition, character_level(self.settings, definition.key))), interrupt=True)
                return True
            if action.startswith(_sx(1200)):
                key = action.split(_sx(560), 1)[1]
                self._run_or_confirm_purchase(lambda key=key: self._unlock_character(key), return_menu=self.character_detail_menu, return_index=self.character_detail_menu.index)
                return True
            if action.startswith(_sx(1408)):
                self._select_character(action.split(_sx(560), 1)[1])
                return True
            if action.startswith(_sx(1409)):
                key = action.split(_sx(560), 1)[1]
                self._run_or_confirm_purchase(lambda key=key: self._upgrade_character(key), return_menu=self.character_detail_menu, return_index=self.character_detail_menu.index)
                return True
        if self.active_menu == self.board_menu:
            if action == _sx(429):
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1244)))
                return True
            if action.startswith(_sx(1410)):
                self._refresh_board_detail_menu_labels(action.split(_sx(560), 1)[1])
                self._set_active_menu(self.board_detail_menu)
                return True
        if self.active_menu == self.board_detail_menu:
            if action == _sx(429):
                self._refresh_board_menu_labels()
                board_keys = [definition.key for definition in board_definitions()]
                try:
                    start_index = board_keys.index(self._board_detail_key)
                except ValueError:
                    start_index = 0
                self._set_active_menu(self.board_menu, start_index=start_index)
                return True
            if action.startswith(_sx(1411)):
                definition = board_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1679).format(definition.name, self._board_status_label(definition.key)), interrupt=True)
                return True
            if action.startswith(_sx(1412)):
                definition = board_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1679).format(definition.name, self._board_power_label(definition.key)), interrupt=True)
                return True
            if action.startswith(_sx(1208)):
                key = action.split(_sx(560), 1)[1]
                self._run_or_confirm_purchase(lambda key=key: self._unlock_board(key), return_menu=self.board_detail_menu, return_index=self.board_detail_menu.index)
                return True
            if action.startswith(_sx(1413)):
                self._select_board(action.split(_sx(560), 1)[1])
                return True
            if action.startswith(_sx(1414)):
                definition = board_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1681).format(definition.name), interrupt=True)
                return True
        if self.active_menu == self.collection_menu:
            if action == _sx(429):
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, _sx(1246)))
                return True
            if action.startswith(_sx(1415)):
                key = action.split(_sx(560), 1)[1]
                definition = next((item for item in collection_definitions() if item.key == key))
                owned, total = collection_progress(self.settings, definition)
                status = _sx(1682) if key in completed_collection_keys(self.settings) else _sx(1683)
                self.speaker.speak(_sx(1684).format(definition.name, definition.description, owned, total, collection_bonus_summary(definition), status), interrupt=True)
                return True
            if action.startswith(_sx(1416)):
                definition = character_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1685).format(definition.name), interrupt=True)
                return True
            if action.startswith(_sx(1203)):
                definition = character_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1686).format(definition.name), interrupt=True)
                return True
            if action.startswith(_sx(1417)):
                definition = character_definition(action.split(_sx(560), 1)[1])
                self.speaker.speak(_sx(1335).format(definition.name), interrupt=True)
                return True
        if self.active_menu == self.achievements_menu:
            if action == _sx(429):
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu, start_index=self._menu_index_for_action(self.missions_hub_menu, _sx(1236)))
                return True
            if action.startswith(_sx(1418)):
                achievement_key = action.split(_sx(560), 1)[1]
                for achievement in achievement_definitions():
                    if achievement.key == achievement_key:
                        self.speaker.speak(achievement.description, interrupt=True)
                        break
                return True
        if self.active_menu == self.learn_sounds_menu:
            if action == _sx(429):
                self._set_active_menu(self.main_menu)
                return True
        if self.active_menu == self.howto_menu:
            if action == _sx(429):
                self._showing_upgrade_help = False
                self._refresh_howto_menu_labels()
                self._set_active_menu(self.main_menu)
                return True
            if action.startswith(_sx(1419)):
                self._open_help_topic(action.split(_sx(560), 1)[1])
                return True
        if self.active_menu == self.help_topic_menu:
            if action == _sx(429):
                self._set_active_menu(self.howto_menu)
                return True
            if action == _sx(1395):
                return self._copy_menu_text(self.help_topic_menu.items[self.help_topic_menu.index].label, _sx(1678))
            if action == _sx(1396):
                return self._copy_menu_text(self._selected_info_copy_all_text(self.help_topic_menu), self._selected_info_copy_all_message(self.help_topic_menu))
            return True
        if self.active_menu == self.whats_new_menu:
            if action == _sx(429):
                self._set_active_menu(self.main_menu)
                return True
            if action == _sx(1395):
                return self._copy_menu_text(self.whats_new_menu.items[self.whats_new_menu.index].label, _sx(1678))
            if action == _sx(1396):
                return self._copy_menu_text(self._selected_info_copy_all_text(self.whats_new_menu), self._selected_info_copy_all_message(self.whats_new_menu))
                return True
        if self.active_menu == self.pause_menu:
            if action == _sx(1420):
                self.state.paused = False
                self._set_active_menu(None)
                self.speaker.speak(_sx(1577), interrupt=True)
                return True
            if action == _sx(1421):
                self._options_return_menu = self.pause_menu
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu)
                return True
            if action == _sx(1422):
                self._set_active_menu(self.pause_confirm_menu)
                return True
        if self.active_menu == self.pause_confirm_menu:
            if action == _sx(1423):
                self.end_run(to_menu=True)
                return True
            if action == _sx(1424):
                self._set_active_menu(self.pause_menu, start_index=self._menu_index_for_action(self.pause_menu, _sx(1422)))
                return True
        if self.active_menu == self.leaderboard_logout_confirm_menu:
            if action == _sx(1425):
                self._logout_leaderboard_account()
                return True
            if action == _sx(1426):
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1382)))
                return True
        if self.active_menu == self.publish_confirm_menu:
            if action == _sx(1427):
                self._publish_latest_game_over_run()
                return True
            if action == _sx(1428):
                target_menu = self._publish_confirm_return_menu or self.game_over_menu
                self._set_active_menu(target_menu, start_index=self._publish_confirm_return_index)
                return True
        if self.active_menu == self.purchase_confirm_menu:
            if action == _sx(1429):
                self._resolve_pending_purchase(accepted=True)
                return True
            if action == _sx(1430):
                self._resolve_pending_purchase(accepted=False)
                return True
        if self.active_menu == self.exit_confirm_menu:
            if action == _sx(1431):
                return False
            if action == _sx(1432):
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, _sx(768)))
                return True
        if self.active_menu == self.revive_menu:
            if action == _sx(1433):
                self._revive_run()
                return True
            if action in (_sx(1580), _sx(1067)):
                self._finish_run_loss(_sx(1009))
                return True
        if self.active_menu == self.game_over_menu:
            if action == _sx(964):
                self.start_run(practice_mode=self._practice_mode_active)
                return True
            if action == _sx(965):
                if self._game_over_publish_state != _sx(1071) and self._should_offer_publish_prompt():
                    self._open_publish_confirmation(return_menu=self.main_menu, start_index=0)
                    return True
                self.active_menu = self.main_menu
                self.active_menu.open()
                return True
            if action.startswith(_sx(1434)):
                current_item = self.active_menu.items[self.active_menu.index]
                self.speaker.speak(current_item.label, interrupt=True)
                return True
        return True

    def _set_server_status(self, title: str, message: str) -> None:
        self.server_status_menu.title = title
        self.server_status_menu.items[0].label = message

    def _cancel_leaderboard_operation(self) -> None:
        self._leaderboard_active_operation = None
        self._leaderboard_operation_token += 1

    def _start_leaderboard_operation(self, operation: str, title: str, message: str, worker, *, return_menu: Menu | None=None, show_status: bool=True, reject_message: bool=True) -> bool:
        if self._leaderboard_active_operation is not None:
            if reject_message:
                self.audio.play(_sx(52), channel=_sx(180))
                self.speaker.speak(_sx(1687), interrupt=True)
            return False
        self._leaderboard_active_operation = operation
        self._leaderboard_operation_token += 1
        token = self._leaderboard_operation_token
        self._leaderboard_return_menu = return_menu or self.active_menu
        if show_status:
            self._set_server_status(title, message)
            self._set_active_menu(self.server_status_menu, play_sound=False)

        def runner() -> None:
            try:
                result = worker()
            except Exception as exc:
                self._leaderboard_operation_queue.put(LeaderboardOperationResult(token=token, operation=operation, success=False, payload=exc))
                return
            self._leaderboard_operation_queue.put(LeaderboardOperationResult(token=token, operation=operation, success=True, payload=result))
        threading.Thread(target=runner, name=_sx(1815).format(operation), daemon=True).start()
        return True

    def _update_leaderboard_operation_state(self) -> None:
        while True:
            try:
                result = self._leaderboard_operation_queue.get_nowait()
            except queue.Empty:
                return
            if result.token != self._leaderboard_operation_token:
                continue
            self._leaderboard_active_operation = None
            if not result.success:
                self._handle_leaderboard_error(result.operation, result.payload)
                continue
            self._handle_leaderboard_success(result.operation, result.payload)

    def _handle_leaderboard_success(self, operation: str, payload: object) -> None:
        if operation in {_sx(1435), _sx(1083)}:
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            selected_action = None
            if self.active_menu == self.leaderboard_menu and self.leaderboard_menu.items:
                selected_action = self.leaderboard_menu.items[self.leaderboard_menu.index].action
            self._leaderboard_period_filter = str(data.get(_sx(1816)) or self._leaderboard_period_filter or _sx(659))
            self._leaderboard_difficulty_filter = str(data.get(_sx(318)) or self._leaderboard_difficulty_filter or _sx(660))
            self._leaderboard_season = dict(data.get(_sx(659)) or self._leaderboard_season or {})
            self._leaderboard_entries = list(data.get(_sx(1817)) or [])
            self._leaderboard_total_players = int(data.get(_sx(1818), len(self._leaderboard_entries)) or 0)
            self._leaderboard_cache_loaded_at = time.monotonic()
            self._refresh_leaderboard_menu()
            if selected_action:
                self.leaderboard_menu.index = self._menu_index_for_action(self.leaderboard_menu, selected_action)
            if operation == _sx(1435):
                self._set_active_menu(self.leaderboard_menu, play_sound=False)
            return
        if operation == _sx(1068):
            data = dict(payload or {})
            self._leaderboard_profile = data
            self._leaderboard_season = dict(data.get(_sx(659)) or self._leaderboard_season or {})
            self._leaderboard_profile_history_count = int(data.get(_sx(1819), 0) or 0)
            self._refresh_leaderboard_profile_menu()
            self._set_active_menu(self.leaderboard_profile_menu, play_sound=False)
            self.speaker.speak(_sx(1436).format(data.get(_sx(1502), _sx(812))), interrupt=True)
            return
        if operation == _sx(1069):
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            self._leaderboard_username = str(data.get(_sx(1502)) or self._leaderboard_username or _sx(2)).strip()
            self.settings[_sx(330)] = self._leaderboard_username
            account_sync = dict(data.get(_sx(1487)) or {})
            if account_sync:
                self._apply_leaderboard_account_sync(account_sync, announce_rewards=True)
            self._refresh_options_menu_labels()
            self._persist_settings()
            self.speaker.speak(_sx(1689) if str(data.get(_sx(1823))) == _sx(1820) else _sx(1690), interrupt=True)
            if self._publish_after_leaderboard_auth:
                self._publish_after_leaderboard_auth = False
                self._publish_latest_game_over_run()
                return
            if self._issue_submit_after_leaderboard_auth:
                self._issue_submit_after_leaderboard_auth = False
                self._begin_issue_submission()
                return
            if self._leaderboard_return_menu is not None:
                self._set_active_menu(self._leaderboard_return_menu, play_sound=False)
            return
        if operation == _sx(1070):
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            publish_username = str(data.get(_sx(1502)) or self._leaderboard_username or _sx(2)).strip()
            if publish_username:
                self._leaderboard_username = publish_username
                self.settings[_sx(330)] = publish_username
                self._refresh_options_menu_labels()
                self._persist_settings()
            self._game_over_publish_state = _sx(1071)
            self._leaderboard_cache_loaded_at = 0.0
            self._refresh_game_over_menu()
            target_menu = self._publish_confirm_return_menu or self.game_over_menu
            self._set_active_menu(target_menu, start_index=self._publish_confirm_return_index, play_sound=False)
            if target_menu == self.game_over_menu:
                self.game_over_menu.index = self._menu_index_for_action(self.game_over_menu, _sx(964))
            suspicious_run = str(data.get(_sx(1704)) or _sx(786)) == _sx(1437)
            if bool(data.get(_sx(1691))):
                rank = data.get(_sx(1692))
                self.audio.play(_sx(97), channel=_sx(180))
                if rank is not None:
                    message = _sx(1693).format(rank)
                else:
                    message = _sx(1694)
                if suspicious_run:
                    message = _sx(1695).format(message)
                self.speaker.speak(message, interrupt=True)
                return
            if suspicious_run:
                self.speaker.speak(_sx(1696), interrupt=True)
            return
        if operation in {_sx(1099), _sx(1100)}:
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            selected_action = None
            if self.active_menu == self.issue_menu and self.issue_menu.items:
                selected_action = self.issue_menu.items[self.issue_menu.index].action
            self._issue_status_filter = str(data.get(_sx(1823)) or self._issue_status_filter or _sx(660))
            self._issue_entries = list(data.get(_sx(1817)) or [])
            self._issue_total_reports = int(data.get(_sx(1824), len(self._issue_entries)) or 0)
            self._issue_offset = int(data.get(_sx(1825), self._issue_offset) or 0)
            self._issue_cache_loaded_at = time.monotonic()
            self._refresh_issue_menu()
            if selected_action:
                self.issue_menu.index = self._menu_index_for_action(self.issue_menu, selected_action)
            if operation == _sx(1099):
                self._set_active_menu(self.issue_menu, play_sound=False)
            return
        if operation == _sx(1072):
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            self._set_issue_detail_content(data)
            self._set_active_menu(self.issue_detail_menu, play_sound=False)
            return
        if operation == _sx(1073):
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            self._issue_status_filter = _sx(1074)
            self._issue_offset = 0
            self._issue_cache_loaded_at = 0.0
            self._issue_draft_title = _sx(2)
            self._issue_draft_message = _sx(2)
            self._refresh_issue_menu()
            self._set_active_menu(self.issue_menu, start_index=self._menu_index_for_action(self.issue_menu, _sx(1073)), play_sound=False)
            submissions_remaining = int(data.get(_sx(1826), 0) or 0)
            self.audio.play(_sx(56), channel=_sx(180))
            self.speaker.speak(_sx(1438).format(submissions_remaining), interrupt=True)
            self._request_issue_refresh(_sx(1100), return_menu=self.issue_menu, show_status=False)
            return
        if operation == _sx(1035):
            data = dict(payload or {})
            self._apply_leaderboard_account_sync(data, announce_rewards=True)
            self._refresh_leaderboard_menu()
            return
        if operation == _sx(1075):
            data = dict(payload or {})
            if bool(data.get(_sx(1327))):
                self.audio.play(_sx(96), channel=_sx(180))
            self._apply_leaderboard_account_sync(data, announce_rewards=True)
            self._refresh_leaderboard_menu()
            self._refresh_wheel_menu_labels()
            if self.active_menu == self.wheel_menu:
                self._set_active_menu(self.wheel_menu, play_sound=False)
            return
        if operation == _sx(99):
            data = dict(payload or {})
            reward = dict(data.get(_sx(1827)) or {})
            item_key = str(reward.get(_sx(1890)) or _sx(2)).strip().lower()
            item_label = self._special_item_label(item_key) if item_key else _sx(871)
            amount = max(1, int(reward.get(_sx(593), 1) or 1))
            self._set_active_menu(self.wheel_menu, play_sound=False)
            self.audio.play(_sx(99), channel=_sx(99))
            spin_delay = 0.0
            spin_sound = self.audio.sounds.get(_sx(99))
            if spin_sound is not None:
                spin_delay = max(0.0, float(spin_sound.get_length()))
            self._pending_wheel_spin_reward = {_sx(593): amount, _sx(1439): item_label, _sx(1065): data}
            self._pending_wheel_spin_reward_delay = spin_delay
            return
        if operation == _sx(1038):
            data = dict(payload or {})
            self._apply_leaderboard_account_sync(data, announce_rewards=False)
            consumed_keys = list(data.get(_sx(1329)) or [])
            self._flush_consumed_special_items(consumed_keys)
            self._refresh_wheel_menu_labels()
            self._refresh_loadout_menu_labels()
            return
        if operation == _sx(1076):
            data = dict(payload or {})
            self._apply_special_sync_payload(data)
            toggled_key = str(data.get(_sx(1890)) or self._special_toggle_item_key or _sx(2)).strip().lower()
            self._special_toggle_item_key = _sx(2)
            if toggled_key:
                state_text = _sx(1598) if bool(data.get(_sx(1863), False)) else _sx(1599)
                self.audio.play(_sx(56), channel=_sx(180))
                self.speaker.speak(_sx(1699).format(self._special_item_label(toggled_key), state_text), interrupt=True)
            if self._leaderboard_return_menu == self.loadout_menu:
                self._refresh_loadout_menu_labels()
                self._set_active_menu(self.loadout_menu, start_index=self._menu_index_for_action(self.loadout_menu, _sx(1785).format(toggled_key) if toggled_key else _sx(1379)), play_sound=False)
            return

    def _handle_leaderboard_error(self, operation: str, error: object) -> None:
        if operation == _sx(1069):
            self._publish_after_leaderboard_auth = False
            self._issue_submit_after_leaderboard_auth = False
        if isinstance(error, LeaderboardClientError) and error.code == _sx(1440):
            self._leaderboard_username = _sx(2)
            self.settings[_sx(330)] = _sx(2)
            self.leaderboard_client.principal_username = _sx(2)
            self.leaderboard_client.auth_token = _sx(2)
            self._clear_server_special_state()
            self._refresh_options_menu_labels()
            self._persist_settings()
        if operation == _sx(1038):
            return
        if operation == _sx(1035) and (not (isinstance(error, LeaderboardClientError) and error.code == _sx(1440))):
            return
        message = self._leaderboard_error_message(operation, error)
        if operation == _sx(1083) and self._leaderboard_entries:
            self.audio.play(_sx(52), channel=_sx(180))
            self._refresh_leaderboard_menu()
            if self.active_menu != self.leaderboard_menu:
                self._set_active_menu(self.leaderboard_menu, play_sound=False)
            self.speaker.speak(_sx(1441).format(message), interrupt=True)
            return
        if operation == _sx(1100) and (self._issue_entries or self._issue_total_reports == 0):
            self.audio.play(_sx(52), channel=_sx(180))
            self._refresh_issue_menu()
            if self.active_menu != self.issue_menu:
                self._set_active_menu(self.issue_menu, play_sound=False)
            self.speaker.speak(_sx(1442).format(message), interrupt=True)
            return
        self.audio.play(_sx(52), channel=_sx(180))
        if self._leaderboard_return_menu is not None:
            self._set_active_menu(self._leaderboard_return_menu, play_sound=False)
        else:
            self._set_active_menu(self.main_menu, play_sound=False)
        self.speaker.speak(message, interrupt=True)

    @staticmethod
    def _leaderboard_error_message(operation: str, error: object) -> str:
        if operation.startswith(_sx(1443)) and isinstance(error, LeaderboardClientError) and (error.code == _sx(1444)):
            return _sx(1077)
        return str(error)

    def _open_wheel_menu(self) -> None:
        if not self._leaderboard_is_authenticated():
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1445), interrupt=True)
            return
        self._refresh_wheel_menu_labels()
        self._set_active_menu(self.wheel_menu)
        self._request_wheel_sync(show_status=False)

    def _request_wheel_sync(self, *, show_status: bool) -> None:

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            payload = self.leaderboard_client.sync_account(self._claimed_leaderboard_reward_ids())
            payload[_sx(1327)] = just_connected
            return payload
        self._start_leaderboard_operation(_sx(1075), _sx(703), _sx(1078), worker, return_menu=self.wheel_menu, show_status=show_status, reject_message=False)

    def _request_weekly_wheel_spin(self) -> None:
        if not self._leaderboard_is_authenticated():
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1446), interrupt=True)
            return
        spins_remaining = int(self._server_wheel_status.get(_sx(1600), 0) or 0)
        if spins_remaining <= 0:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1447), interrupt=True)
            return

        def worker() -> dict[str, object]:
            self.leaderboard_client.connect()
            return self.leaderboard_client.spin_weekly_wheel()
        self._start_leaderboard_operation(_sx(99), _sx(703), _sx(1079), worker, return_menu=self.wheel_menu, show_status=True, reject_message=True)

    def _toggle_special_item_loadout(self, item_key: str) -> None:
        normalized_key = str(item_key or _sx(2)).strip().lower()
        if normalized_key not in SPECIAL_ITEM_ORDER:
            self.audio.play(_sx(52), channel=_sx(180))
            return
        if not self._leaderboard_is_authenticated():
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1446), interrupt=True)
            return
        if self._special_item_owned_count(normalized_key) <= 0:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1448), interrupt=True)
            return
        next_enabled = not self._special_item_enabled(normalized_key)

        def worker() -> dict[str, object]:
            self.leaderboard_client.connect()
            return self.leaderboard_client.set_special_item_loadout(normalized_key, next_enabled)
        if self._start_leaderboard_operation(_sx(1076), _sx(1039), _sx(1080).format(self._special_item_label(normalized_key)), worker, return_menu=self.loadout_menu, show_status=True, reject_message=True):
            self._special_toggle_item_key = normalized_key

    def _open_leaderboard(self, force_refresh: bool=False) -> None:
        if not self._leaderboard_is_authenticated():
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1451), interrupt=True)
            return
        if self._leaderboard_entries and (not force_refresh):
            self._refresh_leaderboard_menu()
            self._set_active_menu(self.leaderboard_menu)
            if not self._leaderboard_cache_is_fresh():
                self._request_leaderboard_refresh(operation=_sx(1083), return_menu=self.leaderboard_menu, show_status=False)
            return
        self._request_leaderboard_refresh(operation=_sx(1435), return_menu=self.main_menu, show_status=not self._leaderboard_entries)

    def _refresh_leaderboard_menu(self) -> None:
        total = max(self._leaderboard_total_players, len(self._leaderboard_entries))
        self.leaderboard_menu.title = _sx(775).format(len(self._leaderboard_entries), total)
        items = [MenuItem(self._leaderboard_season_identity_label(), _sx(1390)), MenuItem(self._leaderboard_season_status_label(), _sx(1390)), MenuItem(self._leaderboard_reward_status_label(), _sx(1390)), MenuItem(self._leaderboard_difficulty_option_label(), _sx(1388))]
        items.extend((MenuItem(self._leaderboard_entry_label(entry), _sx(1702).format(entry[_sx(1502)])) for entry in self._leaderboard_entries))
        if not self._leaderboard_entries:
            items.append(MenuItem(_sx(1703), _sx(1390)))
        items.append(MenuItem(_sx(1452), _sx(1083)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.leaderboard_menu.items = items

    def _leaderboard_period_option_label(self) -> str:
        return _sx(776).format(leaderboard_period_display_label(self._leaderboard_period_filter))

    def _leaderboard_difficulty_option_label(self) -> str:
        return _sx(679).format(leaderboard_difficulty_filter_display_label(self._leaderboard_difficulty_filter))

    def _leaderboard_entry_label(self, entry: dict[str, object]) -> str:
        segments = [_sx(988).format(int(entry.get(_sx(1871), 0) or 0), entry.get(_sx(1502), _sx(812))), verification_display_label(entry.get(_sx(1704)))]
        if self._leaderboard_difficulty_filter == _sx(660):
            segments.append(difficulty_display_label(entry.get(_sx(318))))
        segments.extend([_sx(1453).format(int(entry.get(_sx(968), 0) or 0)), _sx(1454).format(int(entry.get(_sx(363), 0) or 0)), _sx(1455).format(format_play_time(entry.get(_sx(969), 0) or 0))])
        return _sx(877).join(segments)

    def _cycle_leaderboard_period(self) -> None:
        current_index = LEADERBOARD_PERIOD_ORDER.index(self._leaderboard_period_filter)
        self._leaderboard_period_filter = LEADERBOARD_PERIOD_ORDER[(current_index + 1) % len(LEADERBOARD_PERIOD_ORDER)]
        self._leaderboard_cache_loaded_at = 0.0
        self._refresh_leaderboard_menu()
        self._set_active_menu(self.leaderboard_menu, start_index=self._menu_index_for_action(self.leaderboard_menu, _sx(1387)))
        self._request_leaderboard_refresh(_sx(1083), return_menu=self.leaderboard_menu, show_status=False)

    def _cycle_leaderboard_difficulty(self) -> None:
        current_index = LEADERBOARD_DIFFICULTY_FILTER_ORDER.index(self._leaderboard_difficulty_filter)
        self._leaderboard_difficulty_filter = LEADERBOARD_DIFFICULTY_FILTER_ORDER[(current_index + 1) % len(LEADERBOARD_DIFFICULTY_FILTER_ORDER)]
        self._leaderboard_cache_loaded_at = 0.0
        self._refresh_leaderboard_menu()
        self._set_active_menu(self.leaderboard_menu, start_index=self._menu_index_for_action(self.leaderboard_menu, _sx(1388)))
        self._request_leaderboard_refresh(_sx(1083), return_menu=self.leaderboard_menu, show_status=False)

    def _open_leaderboard_profile(self, username: str) -> None:

        def worker() -> dict[str, object]:
            self.leaderboard_client.connect()
            return self.leaderboard_client.fetch_profile(username=username, history_limit=50)
        self._start_leaderboard_operation(_sx(1068), _sx(811), _sx(1084).format(username), worker, return_menu=self.leaderboard_menu)

    def _request_leaderboard_refresh(self, operation: str, return_menu: Menu, show_status: bool) -> bool:

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            board = self.leaderboard_client.fetch_leaderboard(limit=100, period=self._leaderboard_period_filter, difficulty=self._leaderboard_difficulty_filter)
            board[_sx(1327)] = just_connected
            return board
        return self._start_leaderboard_operation(operation, _sx(811), _sx(1457) if operation == _sx(1083) else _sx(1086), worker, return_menu=return_menu, show_status=show_status, reject_message=show_status)

    def _leaderboard_cache_is_fresh(self) -> bool:
        if not self._leaderboard_entries or self._leaderboard_cache_loaded_at <= 0:
            return False
        return time.monotonic() - self._leaderboard_cache_loaded_at <= LEADERBOARD_CACHE_TTL_SECONDS

    def _refresh_leaderboard_profile_menu(self) -> None:
        profile = self._leaderboard_profile or {}
        summary = dict(profile.get(_sx(1708)) or {})
        latest_run = dict(profile.get(_sx(1709)) or {})
        best_run = dict(profile.get(_sx(1710)) or {})
        history = list(profile.get(_sx(1711)) or [])
        self.leaderboard_profile_menu.title = str(profile.get(_sx(1502)) or _sx(812))
        items = [MenuItem(_sx(1458).format(profile.get(_sx(1692)) if profile.get(_sx(1692)) is not None else _sx(1864)), _sx(1459)), MenuItem(_sx(1460).format(int(summary.get(_sx(1878), 0) or 0)), _sx(1459)), MenuItem(_sx(1461).format(int(summary.get(_sx(1879), 0) or 0)), _sx(1459)), MenuItem(_sx(1462).format(int(summary.get(_sx(1880), 0) or 0)), _sx(1459)), MenuItem(_sx(1463).format(int(summary.get(_sx(1881), 0) or 0)), _sx(1459)), MenuItem(_sx(1464).format(format_play_time(summary.get(_sx(1882), 0) or 0)), _sx(1459)), MenuItem(_sx(1465).format(int(summary.get(_sx(1883), 0) or 0)), _sx(1459)), MenuItem(_sx(1466).format(int(summary.get(_sx(1884), 0) or 0)), _sx(1459)), MenuItem(_sx(1467).format(int(latest_run.get(_sx(968), 0) or 0)), _sx(1459)), MenuItem(_sx(1468).format(int(latest_run.get(_sx(363), 0) or 0)), _sx(1459)), MenuItem(_sx(1469).format(format_play_time(latest_run.get(_sx(969), 0) or 0)), _sx(1459)), MenuItem(_sx(1470).format(difficulty_display_label(latest_run.get(_sx(318)))), _sx(1459)), MenuItem(_sx(1471).format(verification_display_label(latest_run.get(_sx(1704)))), _sx(1459)), MenuItem(_sx(1472).format(int(best_run.get(_sx(968), 0) or 0)), _sx(1459)), MenuItem(_sx(1473).format(int(best_run.get(_sx(363), 0) or 0)), _sx(1459)), MenuItem(_sx(1474).format(format_play_time(best_run.get(_sx(969), 0) or 0)), _sx(1459)), MenuItem(_sx(1475).format(difficulty_display_label(best_run.get(_sx(318)))), _sx(1459)), MenuItem(_sx(1476).format(verification_display_label(best_run.get(_sx(1704)))), _sx(1459))]
        for history_entry in history:
            items.append(MenuItem(self._leaderboard_history_label(history_entry), _sx(1731).format(history_entry[_sx(1865)])))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.leaderboard_profile_menu.items = items

    def _leaderboard_history_label(self, history_entry: dict[str, object]) -> str:
        published_at = str(history_entry.get(_sx(1872)) or _sx(2)).replace(_sx(1477), _sx(4))[:19]
        return _sx(877).join([published_at, difficulty_display_label(history_entry.get(_sx(318))), verification_display_label(history_entry.get(_sx(1704))), _sx(1453).format(int(history_entry.get(_sx(968), 0) or 0)), _sx(1454).format(int(history_entry.get(_sx(363), 0) or 0)), _sx(1455).format(format_play_time(history_entry.get(_sx(969), 0) or 0))])

    def _open_leaderboard_run_detail(self, submission_id: str) -> None:
        profile = self._leaderboard_profile or {}
        for history_entry in list(profile.get(_sx(1711)) or []):
            if str(history_entry.get(_sx(1865)) or _sx(2)) != str(submission_id):
                continue
            self._leaderboard_selected_run = dict(history_entry)
            self._refresh_leaderboard_run_detail_menu()
            self._set_active_menu(self.leaderboard_run_detail_menu)
            return
        self.audio.play(_sx(52), channel=_sx(180))
        self.speaker.speak(_sx(1085), interrupt=True)

    def _refresh_leaderboard_run_detail_menu(self) -> None:
        run_data = self._leaderboard_selected_run or {}
        published_at = str(run_data.get(_sx(1872)) or _sx(2)).replace(_sx(1477), _sx(4))[:19]
        verification_reasons = list(run_data.get(_sx(1732)) or [])
        self.leaderboard_run_detail_menu.title = _sx(777)
        items = [MenuItem(_sx(1478).format(verification_display_label(run_data.get(_sx(1704)))), _sx(1479)), MenuItem(_sx(679).format(difficulty_display_label(run_data.get(_sx(318)))), _sx(1479)), MenuItem(_sx(748).format(int(run_data.get(_sx(968), 0) or 0)), _sx(1479)), MenuItem(_sx(666).format(int(run_data.get(_sx(363), 0) or 0)), _sx(1479)), MenuItem(_sx(749).format(format_play_time(run_data.get(_sx(969), 0) or 0)), _sx(1479)), MenuItem(_sx(1480).format(int(run_data.get(_sx(972), 0) or 0)), _sx(1479)), MenuItem(_sx(1481).format(int(run_data.get(_sx(966), 0) or 0)), _sx(1479)), MenuItem(_sx(1482).format(int(run_data.get(_sx(973), 0) or 0)), _sx(1479)), MenuItem(self._powerup_usage_label(run_data.get(_sx(967))), _sx(1479)), MenuItem(_sx(1483).format(run_data.get(_sx(970)) or _sx(661)), _sx(1479)), MenuItem(_sx(1484).format(run_data.get(_sx(971)) or _sx(578)), _sx(1479)), MenuItem(_sx(1485).format(published_at), _sx(1479))]
        for reason in verification_reasons:
            items.append(MenuItem(_sx(1740).format(reason), _sx(1479)))
        items.append(MenuItem(TEXT[_sx(429)], _sx(429)))
        self.leaderboard_run_detail_menu.items = items

    def _prompt_for_leaderboard_credentials(self) -> tuple[str, str] | None:
        try:
            result = prompt_for_credentials(caption=_sx(1741), message=_sx(1742), username_hint=self._leaderboard_username)
        except CredentialPromptCancelled:
            self._reset_input_after_native_modal()
            return None
        except NativeCredentialPromptError as exc:
            self._reset_input_after_native_modal()
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(str(exc), interrupt=True)
            return None
        self._reset_input_after_native_modal()
        username = result.username.strip()
        password = result.password
        if not username or not password:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1486), interrupt=True)
            return None
        return (username, password)

    def _prompt_and_authenticate_leaderboard_account(self, *, return_menu: Menu | None=None, publish_after_auth: bool=False, submit_issue_after_auth: bool=False) -> None:
        self._publish_after_leaderboard_auth = False
        self._issue_submit_after_leaderboard_auth = False
        credentials = self._prompt_for_leaderboard_credentials()
        if credentials is None:
            return
        username, password = credentials
        self._publish_after_leaderboard_auth = bool(publish_after_auth)
        self._issue_submit_after_leaderboard_auth = bool(submit_issue_after_auth)

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.login(username=username, password=password)
            result[_sx(1487)] = self.leaderboard_client.sync_account(self._claimed_leaderboard_reward_ids())
            result[_sx(1327)] = just_connected
            return result
        self._start_leaderboard_operation(_sx(1069), _sx(811), _sx(1086), worker, return_menu=return_menu or self.options_menu)

    def _logout_leaderboard_account(self) -> None:
        self.leaderboard_client.logout()
        self._leaderboard_username = _sx(2)
        self.settings[_sx(330)] = _sx(2)
        self._clear_server_special_state()
        self._leaderboard_entries = []
        self._leaderboard_total_players = 0
        self._leaderboard_profile = None
        self._leaderboard_selected_run = None
        self._leaderboard_profile_history_count = 0
        self._leaderboard_cache_loaded_at = 0.0
        self._refresh_options_menu_labels()
        self._persist_settings()
        self._set_active_menu(self.options_menu, start_index=self._update_option_index(_sx(1195)), play_sound=False)
        self.audio.play(_sx(56), channel=_sx(180))
        self.speaker.speak(_sx(1087), interrupt=True)

    def _issue_filter_option_label(self) -> str:
        return _sx(729).format(issue_status_display_label(self._issue_status_filter))

    def _issue_total_pages(self) -> int:
        total_reports = max(0, int(self._issue_total_reports))
        return max(1, (total_reports + ISSUE_REPORT_PAGE_SIZE - 1) // ISSUE_REPORT_PAGE_SIZE)

    def _issue_current_page(self) -> int:
        return max(0, int(self._issue_offset)) // ISSUE_REPORT_PAGE_SIZE + 1

    def _issue_page_info_label(self) -> str:
        return _sx(778).format(self._issue_current_page(), self._issue_total_pages())

    def _issue_report_summary_label(self, entry: dict[str, object]) -> str:
        created_at = str(entry.get(_sx(1873)) or _sx(2)).replace(_sx(1477), _sx(4))[:19]
        username = str(entry.get(_sx(1874)) or entry.get(_sx(1502)) or entry.get(_sx(1875)) or _sx(1089)).strip() or _sx(1089)
        return _sx(779).format(username, str(entry.get(_sx(1106)) or _sx(1829)), issue_status_display_label(entry.get(_sx(1823))), created_at or _sx(1743))

    def _issue_draft_title_label(self) -> str:
        title = _sx(4).join(self._issue_draft_title.strip().split())
        if not title:
            return _sx(1090)
        preview = title if len(title) <= 72 else _sx(1091).format(title[:69].rstrip())
        return _sx(780).format(preview)

    def _issue_draft_message_label(self) -> str:
        normalized_message = self._issue_draft_message.replace(_sx(1166), _sx(652)).replace(_sx(651), _sx(652))
        if not normalized_message.strip():
            return _sx(1093)
        first_line = next((line.strip() for line in normalized_message.split(_sx(652)) if line.strip()), _sx(2))
        if not first_line:
            first_line = _sx(1094)
        preview = first_line if len(first_line) <= 56 else _sx(1091).format(first_line[:53].rstrip())
        line_count = len(normalized_message.split(_sx(652)))
        return _sx(781).format(preview, len(normalized_message), ISSUE_MESSAGE_LIMIT, line_count)

    def _issue_draft_preview_lines(self) -> tuple[str, ...]:
        normalized_message = self._issue_draft_message.replace(_sx(1166), _sx(652)).replace(_sx(651), _sx(652))
        if not normalized_message:
            return (_sx(1488),)
        lines: list[str] = []
        for raw_line in normalized_message.split(_sx(652))[:5]:
            wrapped = textwrap.wrap(raw_line if raw_line else _sx(4), width=62) or [_sx(4)]
            lines.extend(wrapped[:2])
            if len(lines) >= 5:
                break
        return tuple(lines[:5]) or (_sx(1488),)

    def _issue_cache_is_fresh(self) -> bool:
        if self._issue_cache_loaded_at <= 0:
            return False
        if self._issue_entries:
            return time.monotonic() - self._issue_cache_loaded_at <= ISSUE_CACHE_TTL_SECONDS
        return self._issue_total_reports == 0 and time.monotonic() - self._issue_cache_loaded_at <= ISSUE_CACHE_TTL_SECONDS

    def _refresh_issue_menu(self) -> None:
        total = max(self._issue_total_reports, len(self._issue_entries))
        self.issue_menu.title = _sx(782).format(len(self._issue_entries), total)
        items = [MenuItem(_sx(1489), _sx(1073)), MenuItem(self._issue_filter_option_label(), _sx(1392))]
        if self._issue_entries:
            items.extend((MenuItem(self._issue_report_summary_label(entry), _sx(1830).format(entry[_sx(1885)])) for entry in self._issue_entries))
        else:
            items.append(MenuItem(_sx(1744), _sx(1593)))
        items.extend([MenuItem(self._issue_page_info_label(), _sx(1595)), MenuItem(_sx(1596), _sx(1101)), MenuItem(_sx(1597), _sx(1102)), MenuItem(_sx(1452), _sx(1100)), MenuItem(TEXT[_sx(429)], _sx(429))])
        self.issue_menu.items = items
        self.issue_menu.index = min(self.issue_menu.index, len(self.issue_menu.items) - 1)

    def _refresh_issue_compose_menu(self) -> None:
        self.issue_compose_menu.title = _sx(783)
        self.issue_compose_menu.items = [MenuItem(self._issue_draft_title_label(), _sx(1108)), MenuItem(self._issue_draft_message_label(), _sx(1109)), MenuItem(_sx(1490), _sx(1394)), MenuItem(TEXT[_sx(429)], _sx(429))]
        self.issue_compose_menu.index = min(self.issue_compose_menu.index, len(self.issue_compose_menu.items) - 1)

    def _open_issue_compose_menu(self) -> None:
        self._refresh_issue_compose_menu()
        self._set_active_menu(self.issue_compose_menu)

    def _open_issue_reports(self, force_refresh: bool=False) -> None:
        if (self._issue_entries or self._issue_total_reports == 0) and self._issue_cache_loaded_at > 0 and (not force_refresh):
            self._refresh_issue_menu()
            self._set_active_menu(self.issue_menu)
            if not self._issue_cache_is_fresh():
                self._request_issue_refresh(_sx(1100), return_menu=self.issue_menu, show_status=False)
            return
        self._request_issue_refresh(_sx(1099), return_menu=self.main_menu, show_status=self._issue_cache_loaded_at <= 0)

    def _request_issue_refresh(self, operation: str, return_menu: Menu, show_status: bool) -> bool:
        issue_offset = self._issue_offset
        issue_filter = self._issue_status_filter

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.fetch_issue_reports(offset=issue_offset, limit=ISSUE_REPORT_PAGE_SIZE, status=issue_filter)
            result[_sx(1327)] = just_connected
            return result
        return self._start_leaderboard_operation(operation, _sx(810), _sx(1491) if operation != _sx(1073) else _sx(1111), worker, return_menu=return_menu, show_status=show_status)

    def _cycle_issue_status_filter(self) -> None:
        current_index = ISSUE_STATUS_ORDER.index(self._issue_status_filter)
        self._issue_status_filter = ISSUE_STATUS_ORDER[(current_index + 1) % len(ISSUE_STATUS_ORDER)]
        self._issue_offset = 0
        self._issue_cache_loaded_at = 0.0
        self._refresh_issue_menu()
        self._set_active_menu(self.issue_menu, start_index=self._menu_index_for_action(self.issue_menu, _sx(1392)))
        self._request_issue_refresh(_sx(1100), return_menu=self.issue_menu, show_status=False)

    def _change_issue_page(self, direction: int) -> None:
        if direction not in (-1, 1):
            return
        current_page = self._issue_current_page()
        total_pages = self._issue_total_pages()
        next_page = current_page + direction
        if next_page < 1 or next_page > total_pages:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1492), interrupt=True)
            return
        self._issue_offset = (next_page - 1) * ISSUE_REPORT_PAGE_SIZE
        self._issue_cache_loaded_at = 0.0
        self._refresh_issue_menu()
        target_action = _sx(1101) if direction < 0 else _sx(1102)
        self._set_active_menu(self.issue_menu, start_index=self._menu_index_for_action(self.issue_menu, target_action))
        self._request_issue_refresh(_sx(1100), return_menu=self.issue_menu, show_status=False)

    def _open_issue_report_detail(self, report_id: str) -> None:
        selected_id = str(report_id or _sx(2)).strip()

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.fetch_issue_report_detail(selected_id)
            result[_sx(1327)] = just_connected
            return result
        self._start_leaderboard_operation(_sx(1072), _sx(810), _sx(1103), worker, return_menu=self.issue_menu)

    def _set_issue_detail_content(self, report: dict[str, object]) -> None:
        self._selected_issue_report = dict(report)
        message_lines = str(report.get(_sx(1495)) or _sx(2)).replace(_sx(1166), _sx(652)).replace(_sx(651), _sx(652)).split(_sx(652))
        created_at = str(report.get(_sx(1873)) or _sx(2)).replace(_sx(1477), _sx(4))[:19]
        lines = [_sx(780).format(str(report.get(_sx(1106)) or _sx(1829))), _sx(729).format(issue_status_display_label(report.get(_sx(1823)))), _sx(1104).format(created_at or _sx(1743)), _sx(1105), *[line if line else _sx(4) for line in message_lines]]
        content = InfoDialogContent(title=_sx(814), lines=tuple(lines))
        self._selected_issue_detail_content = content
        self.issue_detail_menu.title = content.title
        self.issue_detail_menu.items = [MenuItem(line, _sx(1395)) for line in content.lines] + [MenuItem(_sx(1616), _sx(1396)), MenuItem(TEXT[_sx(429)], _sx(429))]

    def _begin_issue_submission(self) -> None:
        if not self._leaderboard_is_authenticated():
            if self._leaderboard_has_publish_identity():
                self._prompt_and_authenticate_leaderboard_account(return_menu=self.issue_menu, publish_after_auth=False, submit_issue_after_auth=True)
                return
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1494), interrupt=True)
            return
        self._open_issue_compose_menu()

    def _edit_issue_draft_field(self, field_name: str) -> None:
        field_key = str(field_name or _sx(2)).strip().lower()
        if field_key == _sx(1106):
            current_value = self._issue_draft_title
            caption = _sx(1107)
            multiline = False
            text_limit = ISSUE_TITLE_LIMIT
        elif field_key == _sx(1495):
            current_value = self._issue_draft_message
            caption = _sx(1496)
            multiline = True
            text_limit = ISSUE_MESSAGE_LIMIT
        else:
            return
        try:
            result = prompt_for_inline_issue_text(caption=caption, text_hint=current_value, multiline=multiline, text_limit=text_limit)
        except IssueDialogCancelled:
            self._reset_input_after_native_modal()
            self.audio.play(_sx(55), channel=_sx(180))
            self.speaker.speak(_sx(1745), interrupt=True)
            return
        except NativeIssueDialogError as exc:
            self._reset_input_after_native_modal()
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(str(exc), interrupt=True)
            return
        self._reset_input_after_native_modal()
        if field_key == _sx(1106):
            self._issue_draft_title = result
            target_action = _sx(1108)
        else:
            self._issue_draft_message = result
            target_action = _sx(1109)
        self.audio.play(_sx(56), channel=_sx(180))
        self._refresh_issue_compose_menu()
        self.issue_compose_menu.index = self._menu_index_for_action(self.issue_compose_menu, target_action)
        self.speaker.speak(self.issue_compose_menu.items[self.issue_compose_menu.index].label, interrupt=True)

    def _edit_practice_hazard_target(self) -> None:
        current_target = self._practice_hazard_target_setting()
        try:
            result = prompt_for_inline_issue_text(caption=_sx(1746), text_hint=str(current_target), multiline=False, text_limit=5, numeric_only=True)
        except IssueDialogCancelled:
            self._reset_input_after_native_modal()
            self.audio.play(_sx(55), channel=_sx(180))
            self.speaker.speak(_sx(1745), interrupt=True)
            return
        except NativeIssueDialogError as exc:
            self._reset_input_after_native_modal()
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(str(exc), interrupt=True)
            return
        self._reset_input_after_native_modal()
        normalized_value = str(result or _sx(2)).strip()
        if not normalized_value.isdigit():
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1497), interrupt=True)
            return
        target_value = int(normalized_value)
        if target_value < PRACTICE_TARGET_HAZARDS_MIN or target_value > PRACTICE_TARGET_HAZARDS_MAX:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1498), interrupt=True)
            return
        self.settings[_sx(326)] = target_value
        self.audio.play(_sx(56), channel=_sx(180))
        self._refresh_loadout_menu_labels()
        self.loadout_menu.index = self._menu_index_for_action(self.loadout_menu, _sx(1110))
        self.speaker.speak(self.loadout_menu.items[self.loadout_menu.index].label, interrupt=True)

    def _submit_issue_draft(self) -> None:
        normalized_title = _sx(4).join(self._issue_draft_title.strip().split())
        normalized_message = self._issue_draft_message.replace(_sx(1166), _sx(652)).replace(_sx(651), _sx(652))
        if not normalized_title:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1499), interrupt=True)
            self.issue_compose_menu.index = self._menu_index_for_action(self.issue_compose_menu, _sx(1108))
            return
        if not normalized_message.strip():
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1500), interrupt=True)
            self.issue_compose_menu.index = self._menu_index_for_action(self.issue_compose_menu, _sx(1109))
            return

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.submit_issue_report(title=normalized_title, message=normalized_message)
            result[_sx(1327)] = just_connected
            return result
        self._start_leaderboard_operation(_sx(1073), _sx(810), _sx(1111), worker, return_menu=self.issue_compose_menu)

    def _publish_latest_game_over_run(self) -> None:
        if self._practice_mode_active:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1501), interrupt=True)
            self._set_active_menu(self.game_over_menu)
            return
        if not self._leaderboard_is_authenticated():
            if self._leaderboard_has_publish_identity():
                self._prompt_and_authenticate_leaderboard_account(return_menu=self.publish_confirm_menu, publish_after_auth=True)
                return
            self._set_active_menu(self.game_over_menu)
            return
        if self._game_over_publish_state in {_sx(784), _sx(1071)}:
            return
        submission_payload = self._build_leaderboard_submission_payload()
        self._game_over_publish_state = _sx(784)

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.submit_score(**submission_payload)
            result[_sx(1327)] = just_connected
            result[_sx(1502)] = self.leaderboard_client.principal_username
            return result
        self._start_leaderboard_operation(_sx(1070), _sx(811), _sx(1112), worker, return_menu=self.game_over_menu)

    def _build_leaderboard_submission_payload(self) -> dict[str, object]:
        summary = dict(self._game_over_summary)
        return {_sx(968): int(summary.get(_sx(968), 0) or 0), _sx(363): int(summary.get(_sx(363), 0) or 0), _sx(969): int(summary.get(_sx(969), 0) or 0), _sx(318): str(summary.get(_sx(318)) or self._difficulty_key()), _sx(970): str(summary.get(_sx(970)) or _sx(661)), _sx(972): int(summary.get(_sx(972), 0) or 0), _sx(966): int(summary.get(_sx(966), 0) or 0), _sx(973): int(summary.get(_sx(973), 0) or 0), _sx(967): dict(summary.get(_sx(967)) or {})}

    def _cycle_output_device_in_options(self, direction: int) -> None:
        devices = self.audio.output_device_choices()
        current_device = self.audio.current_output_device_name()
        try:
            current_index = devices.index(current_device)
        except ValueError:
            current_index = 0
        requested_device = devices[(current_index + direction) % len(devices)]
        applied_device = self.audio.apply_output_device(requested_device)
        self._refresh_options_menu_labels()
        selected_label = applied_device or SYSTEM_DEFAULT_OUTPUT_LABEL
        if requested_device == applied_device:
            self.speaker.speak(_sx(1503).format(selected_label), interrupt=True)
            return
        self.speaker.speak(_sx(1113).format(selected_label), interrupt=True)

    def _apply_speaker_settings(self) -> None:
        self.speaker.apply_settings(self.settings)

    def _adjust_selected_option(self, direction: int) -> None:
        if self.active_menu not in {self.options_menu, self.sapi_menu, self.announcements_menu} or direction not in (-1, 1):
            return
        selected_action = self.active_menu.items[self.active_menu.index].action
        if selected_action == _sx(429):
            return
        if selected_action == _sx(1114):
            current = float(self.settings[_sx(130)])
            updated = step_volume(current, direction)
            if updated == current:
                self._play_menu_feedback(_sx(52))
                return
            self.settings[_sx(130)] = updated
            self.audio.refresh_volumes()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1114))].label, interrupt=True)
            return
        if selected_action == _sx(1115):
            current = float(self.settings[_sx(196)])
            updated = step_volume(current, direction)
            if updated == current:
                self._play_menu_feedback(_sx(52))
                return
            self.settings[_sx(196)] = updated
            self.audio.refresh_volumes()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1115))].label, interrupt=True)
            return
        if selected_action == _sx(1116):
            self.settings[_sx(316)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1116))].label, interrupt=True)
            return
        if selected_action == _sx(1117):
            self._play_menu_feedback(_sx(56))
            self._cycle_output_device_in_options(direction)
            return
        if selected_action == _sx(1118):
            self.settings[_sx(195)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1118))].label, interrupt=True)
            return
        if selected_action == _sx(1119):
            self.settings[_sx(315)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1119))].label, interrupt=True)
            return
        if selected_action == _sx(1120):
            self._play_menu_feedback(_sx(56))
            self.settings[_sx(117)] = direction > 0
            self._refresh_options_menu_labels()
            label = self.options_menu.items[self._update_option_index(_sx(1120))].label
            if self.settings[_sx(117)]:
                self._apply_speaker_settings()
                self.speaker.speak(label, interrupt=True)
            else:
                self.speaker.speak(label, interrupt=True)
                self._apply_speaker_settings()
            return
        if selected_action == _sx(1121):
            self.settings[_sx(118)] = direction > 0
            self._apply_speaker_settings()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[0].label, interrupt=True)
            return
        if selected_action == _sx(1122):
            current = int(self.settings.get(_sx(122), 100))
            updated = step_int(current, direction, SAPI_VOLUME_MIN, SAPI_VOLUME_MAX)
            if updated == current:
                self._play_menu_feedback(_sx(52))
                return
            self.settings[_sx(122)] = updated
            self._apply_speaker_settings()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[1].label, interrupt=True)
            return
        if selected_action == _sx(1123):
            selected_voice = self.speaker.cycle_sapi_voice(direction)
            if selected_voice == SAPI_VOICE_UNAVAILABLE_LABEL:
                self._play_menu_feedback(_sx(52))
                self.speaker.speak(_sx(1748), interrupt=True)
                return
            self.settings[_sx(119)] = self.speaker.sapi_voice_id or _sx(2)
            self._apply_speaker_settings()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[2].label, interrupt=True)
            return
        if selected_action == _sx(1124):
            current = int(self.settings.get(_sx(120), 0))
            updated = step_int(current, direction, SAPI_RATE_MIN, SAPI_RATE_MAX)
            if updated == current:
                self._play_menu_feedback(_sx(52))
                return
            self.settings[_sx(120)] = updated
            self._apply_speaker_settings()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[3].label, interrupt=True)
            return
        if selected_action == _sx(1125):
            current = int(self.settings.get(_sx(121), 0))
            updated = step_int(current, direction, SAPI_PITCH_MIN, SAPI_PITCH_MAX)
            if updated == current:
                self._play_menu_feedback(_sx(52))
                return
            self.settings[_sx(121)] = updated
            self._apply_speaker_settings()
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[4].label, interrupt=True)
            return
        if selected_action == _sx(1126):
            order = [_sx(199), _sx(200), _sx(201)]
            current = str(self.settings[_sx(318)])
            try:
                current_index = order.index(current)
            except ValueError:
                current_index = order.index(_sx(200))
            self.settings[_sx(318)] = order[(current_index + direction) % len(order)]
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1126))].label, interrupt=True)
            return
        if selected_action == _sx(1127):
            self.settings[_sx(327)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1127))].label, interrupt=True)
            return
        if selected_action == _sx(1128):
            self.settings[_sx(328)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1128))].label, interrupt=True)
            return
        if selected_action == _sx(1129):
            self.settings[_sx(329)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index(_sx(1129))].label, interrupt=True)
            return
        if selected_action == _sx(1130):
            self.settings[_sx(321)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_announcements_menu_labels()
            self.speaker.speak(self.announcements_menu.items[self._update_announcements_index(_sx(1130))].label, interrupt=True)
            return
        if selected_action == _sx(1131):
            self.settings[_sx(322)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_announcements_menu_labels()
            self.speaker.speak(self.announcements_menu.items[self._update_announcements_index(_sx(1131))].label, interrupt=True)
            return
        if selected_action == _sx(1132):
            self.settings[_sx(323)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_announcements_menu_labels()
            self.speaker.speak(self.announcements_menu.items[self._update_announcements_index(_sx(1132))].label, interrupt=True)
            return
        if selected_action == _sx(1133):
            self.settings[_sx(324)] = direction > 0
            self._play_menu_feedback(_sx(56))
            self._refresh_announcements_menu_labels()
            self.speaker.speak(self.announcements_menu.items[self._update_announcements_index(_sx(1133))].label, interrupt=True)
            return

    def start_run(self, practice_mode: bool=False) -> None:
        ensure_progression_state(self.settings)
        self._sync_character_progress()
        self._practice_mode_active = bool(practice_mode)
        practice_speed_scaling_enabled = self._practice_speed_scaling_enabled() if self._practice_mode_active else False
        self._practice_speed_scaling_active = practice_speed_scaling_enabled
        self._practice_hazards_cleared = 0
        self._practice_hazard_target = self._practice_hazard_target_setting() if self._practice_mode_active else PRACTICE_TARGET_HAZARDS
        self._practice_next_progress_announcement = PRACTICE_PROGRESS_STEP
        self.state = RunState(running=True)
        self._set_active_menu(None)
        self.player = Player()
        self.player.hoverboards = int(self.settings.get(_sx(335), 0))
        self.obstacles = []
        if self._practice_mode_active:
            self.speed_profile = SpeedProfile(base_speed=PRACTICE_BASE_SPEED, max_speed=PRACTICE_SCALING_MAX_SPEED if practice_speed_scaling_enabled else PRACTICE_BASE_SPEED, cap_seconds=PRACTICE_SCALING_CAP_SECONDS if practice_speed_scaling_enabled else 1.0, spawn_gap_start=1.28, spawn_gap_end=1.0 if practice_speed_scaling_enabled else 1.28)
        else:
            self.speed_profile = speed_profile_for_difficulty(str(self.settings[_sx(318)]))
        self.spatial_audio.reset()
        self.spawn_director.reset()
        if self._practice_mode_active:
            self.state.multiplier = 1
        else:
            self.state.multiplier = 1 + int(self.settings.get(_sx(340), 0)) + score_booster_bonus(self.selected_score_boosters) + self._active_character_bonuses.starting_multiplier_bonus + int(self._active_event_profile.get(_sx(613), 0) or 0)
        self.state.speed = self.speed_profile.base_speed
        self._active_run_stats = self._empty_run_stats()
        self._footstep_timer = 0.0
        self._left_foot_next = True
        self._run_rewards_committed = False
        self._near_miss_signatures.clear()
        self._guard_loop_timer = 0.0
        self._coin_pitch_index = 0
        self._coin_pitch_timer = 0.0
        self._coin_streak = 0
        self._last_death_reason = _sx(661)
        self._game_over_publish_state = _sx(658)
        self._game_over_summary = self._empty_game_over_summary()
        self._magnet_loop_active = False
        self._jetpack_loop_active = False
        self._special_effect_timers = {}
        self._special_run_used_flags = set()
        self._consumed_special_items_this_run = set()
        self._pending_overclock_keys = 0
        self._box_high_tier_meter = 0
        self._coin_streak_grace_timer = 0.0
        if self._leaderboard_is_authenticated():
            self._active_special_run_items = {item_key for item_key in SPECIAL_ITEM_ORDER if self._special_item_enabled(item_key)}
        else:
            self._active_special_run_items = set()
        self.player.board_extra_jump_available = False
        active_character = selected_character_definition(self.settings)
        active_board = selected_board_definition(self.settings)
        if not self._practice_mode_active and self.selected_headstarts > 0:
            self.settings[_sx(336)] = max(0, int(self.settings.get(_sx(336), 0)) - self.selected_headstarts)
            self.player.headstart = headstart_duration_for_uses(self.selected_headstarts)
            self.player.y = 2.8
            self.player.vy = 0.0
            self._start_headstart_audio()
        if not self._practice_mode_active and self.selected_score_boosters > 0:
            self.settings[_sx(337)] = max(0, int(self.settings.get(_sx(337), 0)) - self.selected_score_boosters)
            self.audio.play(_sx(100), channel=_sx(182))
            self.speaker.speak(_sx(1505).format(self.state.multiplier), interrupt=False)
        self.audio.play(_sx(109), channel=_sx(1506))
        self.audio.play(_sx(102), channel=_sx(180))
        if self.selected_headstarts > 0:
            self.audio.play(_sx(103), channel=_sx(1750))
            self.audio.play(_sx(104), channel=_sx(1751))
        self.audio.music_start(_sx(72))
        event = self._active_event_profile.get(_sx(610))
        event_message = _sx(2)
        if not self._practice_mode_active and event is not None:
            event_label = str(getattr(event, _sx(571), _sx(2)) or _sx(2)).strip()
            if self._active_event_profile.get(_sx(612)):
                event_message = _sx(1507).format(event_label)
            elif event_label:
                event_message = _sx(1753).format(event_label)
        if self._practice_mode_active:
            speed_behavior = _sx(1508) if practice_speed_scaling_enabled else _sx(1509)
            self.speaker.speak(_sx(1510).format(speed_behavior, self._practice_hazard_target), interrupt=True)
        elif self.selected_headstarts > 0:
            self.speaker.speak(_sx(1757).format(active_character.name, active_board.name, event_message, self.selected_headstarts, _sx(294) if self.selected_headstarts != 1 else _sx(2)), interrupt=True)
        else:
            self.speaker.speak(_sx(1758).format(active_character.name, active_board.name, event_message), interrupt=True)
        self.selected_headstarts = 0
        self.selected_score_boosters = 0
        self._pending_practice_setup = False
        self._refresh_loadout_menu_labels()

    def end_run(self, to_menu: bool=True) -> None:
        self._commit_run_rewards()
        self.state.running = False
        self._stop_headstart_audio()
        self.audio.stop(_sx(194))
        self.audio.stop(_sx(198))
        self.audio.stop(_sx(197))
        self._stop_spatial_audio()
        self.spatial_audio.reset()
        if to_menu:
            self._update_game_over_summary(_sx(1511))
            if self._should_offer_publish_prompt():
                self._open_publish_confirmation(return_menu=self.main_menu, start_index=0)
                self._sync_music_context()
                return
            self._set_active_menu(self.main_menu)
            return
        self._set_active_menu(None)

    def _handle_game_key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            self._pause_active_run()
            return
        if key == pygame.K_r:
            if self._coin_counters_enabled():
                self.speaker.speak(_sx(1759).format(self.state.coins), interrupt=False)
            return
        if key == pygame.K_t:
            self.speaker.speak(_sx(1512).format(format_play_time(self.state.time)), interrupt=False)
            return
        if self.state.paused or self.player.jetpack > 0 or self.player.headstart > 0:
            return
        self.player.lane = normalize_lane(self.player.lane)
        if key == pygame.K_LEFT:
            lane_step = 2 if self.player.hover_active > 0 and selected_board_definition(self.settings).power_key == _sx(231) else 1
            target_lane = normalize_lane(self.player.lane - lane_step)
            if target_lane != self.player.lane:
                move_count = abs(target_lane - self.player.lane)
                self.player.lane = target_lane
                if self._special_active(_sx(1761)):
                    window = self._special_timer(_sx(1839))
                    charges = int(self._special_effect_timers.get(_sx(1866), 0) or 0)
                    if window > 0 and charges > 0:
                        extra_lane = normalize_lane(self.player.lane - 1)
                        if extra_lane != self.player.lane:
                            self.player.lane = extra_lane
                            move_count += 1
                            self._special_effect_timers[_sx(1866)] = max(0, charges - 1)
                            self._mark_special_item_consumed(_sx(1761))
                    else:
                        self._set_special_timer(_sx(1839), 1.2)
                        self._special_effect_timers[_sx(1866)] = 2
                if self._special_active(_sx(1556)):
                    self._set_special_timer(_sx(1556), 8.0 * self._special_duration_scale())
                self._record_mission_event(_sx(366), move_count)
                self.audio.play(_sx(15), pan=lane_to_pan(self.player.lane), channel=_sx(42))
                if self.settings.get(_sx(319), True):
                    self.speaker.speak(lane_name(self.player.lane), interrupt=False)
            else:
                self.audio.play(_sx(52), channel=_sx(180))
        elif key == pygame.K_RIGHT:
            lane_step = 2 if self.player.hover_active > 0 and selected_board_definition(self.settings).power_key == _sx(231) else 1
            target_lane = normalize_lane(self.player.lane + lane_step)
            if target_lane != self.player.lane:
                move_count = abs(target_lane - self.player.lane)
                self.player.lane = target_lane
                if self._special_active(_sx(1761)):
                    window = self._special_timer(_sx(1839))
                    charges = int(self._special_effect_timers.get(_sx(1866), 0) or 0)
                    if window > 0 and charges > 0:
                        extra_lane = normalize_lane(self.player.lane + 1)
                        if extra_lane != self.player.lane:
                            self.player.lane = extra_lane
                            move_count += 1
                            self._special_effect_timers[_sx(1866)] = max(0, charges - 1)
                            self._mark_special_item_consumed(_sx(1761))
                    else:
                        self._set_special_timer(_sx(1839), 1.2)
                        self._special_effect_timers[_sx(1866)] = 2
                if self._special_active(_sx(1556)):
                    self._set_special_timer(_sx(1556), 8.0 * self._special_duration_scale())
                self._record_mission_event(_sx(366), move_count)
                self.audio.play(_sx(15), pan=lane_to_pan(self.player.lane), channel=_sx(42))
                if self.settings.get(_sx(319), True):
                    self.speaker.speak(lane_name(self.player.lane), interrupt=False)
            else:
                self.audio.play(_sx(52), channel=_sx(180))
        elif key == pygame.K_UP:
            self._try_jump()
        elif key == pygame.K_DOWN:
            self._try_roll()
        elif key == pygame.K_SPACE:
            self._try_hoverboard()
        elif key == pygame.K_m:
            self.settings[_sx(117)] = not self.settings[_sx(117)]
            if self.settings[_sx(117)]:
                self._apply_speaker_settings()
                self.speaker.speak(_sx(1891), interrupt=True)
            else:
                self.speaker.speak(_sx(1892), interrupt=True)
                self._apply_speaker_settings()

    def _try_jump(self) -> None:
        board = selected_board_definition(self.settings)
        hover_power = board.power_key if self.player.hover_active > 0 else _sx(206)
        can_double_jump = self.player.hover_active > 0 and hover_power == _sx(211) and (self.player.y > 0.01) and self.player.board_extra_jump_available and (self.player.jetpack <= 0) and (self.player.headstart <= 0)
        if self.player.rolling > 0:
            return
        if self.player.y > 0.01 and (not can_double_jump):
            return
        base_jump = 13.0 if self.player.super_sneakers > 0 else 10.5
        if hover_power == _sx(216):
            base_jump += 2.4
        elif hover_power == _sx(226):
            base_jump += 1.1
        self.player.vy = base_jump
        self._record_mission_event(_sx(364))
        if self.player.hover_active > 0 and hover_power == _sx(211):
            if self.player.y <= 0.01:
                self.player.board_extra_jump_available = True
            else:
                self.player.board_extra_jump_available = False
        sound_key = _sx(13) if self.player.super_sneakers > 0 else _sx(12)
        self.audio.play(sound_key, pan=lane_to_pan(self.player.lane), channel=_sx(43))

    def _try_roll(self) -> None:
        if self.player.y > 0.01:
            return
        board = selected_board_definition(self.settings)
        roll_duration = 1.05 if self.player.hover_active > 0 and board.power_key == _sx(236) else 0.7
        if self._special_active(_sx(1513)) and self.player.super_sneakers > 0:
            roll_duration *= 0.65
            self._mark_special_item_consumed(_sx(1513))
        self.player.rolling = roll_duration
        self._record_mission_event(_sx(365))
        self.audio.play(_sx(14), pan=lane_to_pan(self.player.lane), channel=_sx(43))

    def _try_hoverboard(self) -> None:
        if self._practice_mode_active:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1514), interrupt=False)
            return
        if self.player.hover_active > 0:
            return
        if int(self.state.hoverboards_used) >= HOVERBOARD_MAX_USES_PER_RUN:
            self.speaker.speak(_sx(1515).format(HOVERBOARD_MAX_USES_PER_RUN), interrupt=False)
            self.audio.play(_sx(52), channel=_sx(180))
            return
        if self.player.hoverboards <= 0:
            self.speaker.speak(_sx(1516), interrupt=False)
            self.audio.play(_sx(52), channel=_sx(180))
            return
        self.player.hoverboards -= 1
        self.settings[_sx(335)] = max(0, int(self.settings.get(_sx(335), 0)) - 1)
        self.state.hoverboards_used += 1
        self.player.hover_active = HOVERBOARD_DURATION + self._active_character_bonuses.hoverboard_duration_bonus
        self.player.board_extra_jump_available = False
        self._record_run_powerup(_sx(594))
        self.audio.play(_sx(19), channel=_sx(43))
        board = selected_board_definition(self.settings)
        if board.power_key == _sx(206):
            self.speaker.speak(_sx(1517).format(board.name), interrupt=False)
        else:
            self.speaker.speak(_sx(1518).format(board.name, board.power_label), interrupt=False)

    def _update_game(self, delta_time: float) -> None:
        self.player.lane = normalize_lane(self.player.lane)
        self.state.time += delta_time
        if self._practice_mode_active and (not self._practice_speed_scaling_active):
            base_speed = self.speed_profile.base_speed
        else:
            base_speed = self.speed_profile.speed_for_elapsed(self.state.time)
        self.state.speed = base_speed + HEADSTART_SPEED_BONUS if self.player.headstart > 0 else base_speed
        active_board = selected_board_definition(self.settings)
        if self.player.hover_active > 0 and active_board.power_key == _sx(221):
            self.state.speed += 3.0
        speed_factor = 0.0 if self._practice_mode_active and (not self._practice_speed_scaling_active) else self.speed_profile.progress(self.state.time)
        self.speaker.set_speed_factor(speed_factor)
        self.state.distance += self.state.speed * delta_time
        if not self._practice_mode_active:
            self.state.score += self.state.speed * delta_time * self._score_multiplier()
        if self.player.jetpack <= 0 and self.player.y <= 0.01 and (self.player.rolling <= 0):
            self._footstep_timer -= delta_time
            if self._footstep_timer <= 0:
                self._footstep_timer = 0.33
                self._left_foot_next = not self._left_foot_next
                if self.player.super_sneakers > 0:
                    sound_key = _sx(9) if self._left_foot_next else _sx(11)
                else:
                    sound_key = _sx(8) if self._left_foot_next else _sx(10)
                if sound_key in self.audio.sounds:
                    self.audio.play(sound_key, pan=lane_to_pan(self.player.lane), channel=_sx(190))
        else:
            self._footstep_timer = 0.0
        if self.player.jetpack <= 0 and self.player.headstart <= 0 and (self.player.y > 0 or self.player.vy != 0):
            gravity = 18.0 if self.player.hover_active > 0 and active_board.power_key == _sx(226) else 25.0
            self.player.vy -= gravity * delta_time
            self.player.y = max(0.0, self.player.y + self.player.vy * delta_time)
            if self.player.y <= 0.0 and self.player.vy < 0:
                self.player.y = 0.0
                self.player.vy = 0.0
                sound_key = _sx(17) if self.player.super_sneakers > 0 or self.player.pogo_active > 0 else _sx(16)
                self.audio.play(sound_key, pan=lane_to_pan(self.player.lane), channel=_sx(43))
        if self.player.rolling > 0:
            self.player.rolling = max(0.0, self.player.rolling - delta_time)
        self._tick_powerups(delta_time)
        self._spawn_things(delta_time)
        if self._coin_pitch_timer > 0:
            self._coin_pitch_timer = max(0.0, self._coin_pitch_timer - delta_time)
            if self._coin_pitch_timer <= 0:
                if self._special_active(_sx(1766)):
                    grace = 0.85
                    if self._season_imprint_matches(_sx(1840)):
                        grace += 0.25
                    self._coin_streak_grace_timer = max(self._coin_streak_grace_timer, grace)
                    self._mark_special_item_consumed(_sx(1766))
                else:
                    self._coin_pitch_index = 0
                    self._coin_streak = 0
        if self._coin_streak_grace_timer > 0:
            self._coin_streak_grace_timer = max(0.0, self._coin_streak_grace_timer - delta_time)
            if self._coin_streak_grace_timer <= 0:
                self._coin_pitch_index = 0
                self._coin_streak = 0
        for obstacle in self.obstacles:
            obstacle.z -= self.state.speed * delta_time
        self._update_near_miss_audio()
        if self.player.jetpack > 0 or self.player.headstart > 0:
            self._stop_spatial_audio()
            self.spatial_audio.reset()
        else:
            self.spatial_audio.update(delta_time, self.player.lane, self.state.speed, self.obstacles, self.audio, self.speaker)
        self._handle_obstacles()
        self._update_practice_lane_progress()
        self.obstacles = [obstacle for obstacle in self.obstacles if obstacle.z > -5]
        milestone = int(self.state.distance // 250)
        if self._meters_enabled() and milestone > self.state.milestone:
            self.state.milestone = milestone
            self.audio.play(_sx(100), channel=_sx(180))
            self.speaker.speak(_sx(1519).format(milestone * 250), interrupt=False)

    def _score_multiplier(self) -> int:
        multiplier = self.state.multiplier
        if self.player.mult2x > 0:
            multiplier *= 2
        return multiplier

    def _update_practice_lane_progress(self) -> None:
        if not self._practice_mode_active or not self.state.running:
            return
        cleared = 0
        for obstacle in self.obstacles:
            if obstacle.kind not in PRACTICE_HAZARD_KINDS:
                continue
            if -900 < obstacle.z <= -5:
                cleared += 1
        if cleared <= 0:
            return
        self._practice_hazards_cleared += cleared
        if self._practice_hazards_cleared >= self._practice_hazard_target:
            self._complete_practice_lane_run()
            return
        if self._practice_hazards_cleared >= self._practice_next_progress_announcement:
            remaining = max(0, self._practice_hazard_target - self._practice_hazards_cleared)
            self.speaker.speak(_sx(1520).format(self._practice_hazards_cleared, self._practice_hazard_target, remaining), interrupt=False)
            self._practice_next_progress_announcement += PRACTICE_PROGRESS_STEP

    def _complete_practice_lane_run(self) -> None:
        if not self.state.running:
            return
        for quest in record_quest_metric(self.settings, _sx(1134), 1):
            if self._quest_changes_enabled():
                self.audio.play(_sx(100), channel=_sx(1231))
                self.speaker.speak(_sx(1358).format(quest.label), interrupt=False)
        self._refresh_quest_menu_labels()
        self._refresh_missions_hub_menu_labels()
        self.state.paused = False
        self._stop_spatial_audio()
        self.audio.play(_sx(100), channel=_sx(180))
        self.audio.play(_sx(108), channel=_sx(1250))
        self.speaker.speak(_sx(1135).format(self._practice_hazard_target), interrupt=True)
        self._commit_run_rewards()
        self.audio.stop(_sx(194))
        self.audio.stop(_sx(198))
        self.audio.stop(_sx(197))
        self._stop_spatial_audio()
        self.spatial_audio.reset()
        self._open_game_over_dialog(_sx(1136).format(self._practice_hazard_target))

    def _tick_powerups(self, delta_time: float) -> None:

        def decay(attribute: str) -> None:
            current_value = getattr(self.player, attribute)
            if current_value > 0:
                setattr(self.player, attribute, max(0.0, current_value - delta_time))
        for timer_key in list(self._special_effect_timers.keys()):
            current = float(self._special_effect_timers.get(timer_key, 0.0) or 0.0)
            if current <= 0:
                self._special_effect_timers[timer_key] = 0.0
                continue
            self._special_effect_timers[timer_key] = max(0.0, current - delta_time)
        previous_headstart = self.player.headstart
        decay(_sx(595))
        if previous_headstart > 0 and self.player.headstart <= 0:
            self._stop_headstart_audio()
            self.player.y = 0.0
            self.player.vy = 0.0
            self.audio.play(_sx(17), channel=_sx(45))
            self.audio.play(_sx(19), channel=_sx(46))
            self._apply_power_reward(pick_headstart_end_reward(), from_headstart=True)
        elif previous_headstart <= 0 and self.player.headstart > 0:
            self._start_headstart_audio()
        if self.player.headstart <= 0 and self.player.jetpack <= 0:
            decay(_sx(1524))
        if self.player.hover_active <= 0:
            self.player.board_extra_jump_available = False
        previous_sneakers = self.player.super_sneakers
        if self.player.jetpack <= 0 and self.player.headstart <= 0:
            decay(_sx(1525))
        sneakers_expired = previous_sneakers > 0 and self.player.super_sneakers <= 0
        previous_magnet = self.player.magnet
        if self.player.jetpack <= 0 and self.player.headstart <= 0:
            decay(_sx(633))
        magnet_expired = previous_magnet > 0 and self.player.magnet <= 0
        if previous_magnet > 0 and self.player.magnet <= 0:
            self.audio.stop(_sx(198))
            self._magnet_loop_active = False
            if self._special_active(_sx(1526)):
                self._set_special_timer(_sx(1526), 3.0 * self._special_duration_scale())
                self._mark_special_item_consumed(_sx(1526))
            self.audio.play(_sx(20), channel=_sx(43))
            self.speaker.speak(_sx(1527), interrupt=False)
        elif self.player.magnet > 0 and (not self._magnet_loop_active):
            self.audio.play(_sx(94), loop=True, channel=_sx(198))
            self._magnet_loop_active = True
        previous_jetpack = self.player.jetpack
        decay(_sx(1017))
        jetpack_expired = previous_jetpack > 0 and self.player.jetpack <= 0
        if previous_jetpack > 0 and self.player.jetpack <= 0:
            self.audio.stop(_sx(197))
            self._jetpack_loop_active = False
            if self._special_active(_sx(1528)):
                self._set_special_timer(_sx(1769), 2.0 * self._special_duration_scale())
                self._mark_special_item_consumed(_sx(1528))
            self.audio.play(_sx(20), channel=_sx(43))
            self.speaker.speak(_sx(1529), interrupt=False)
        elif self.player.jetpack > 0 and (not self._jetpack_loop_active):
            self.audio.play(_sx(95), loop=True, channel=_sx(197))
            self._jetpack_loop_active = True
        previous_multiplier = self.player.mult2x
        if self.player.jetpack <= 0 and self.player.headstart <= 0:
            decay(_sx(634))
        mult_expired = previous_multiplier > 0 and self.player.mult2x <= 0
        if previous_multiplier > 0 and self.player.mult2x <= 0:
            self.audio.play(_sx(20), channel=_sx(43))
            self.speaker.speak(_sx(1530), interrupt=False)
        previous_pogo = self.player.pogo_active
        decay(_sx(1137))
        pogo_expired = previous_pogo > 0 and self.player.pogo_active <= 0
        if previous_pogo > 0 and self.player.pogo_active <= 0:
            self.audio.play(_sx(20), channel=_sx(43))
            self.speaker.speak(_sx(1531), interrupt=False)
        elif self.player.pogo_active > 0:
            self._launch_pogo_bounce()
        if self._special_active(_sx(1532)) and _sx(1533) not in self._special_run_used_flags:
            if any((magnet_expired, mult_expired, sneakers_expired, pogo_expired, jetpack_expired)):
                remaining_chain = max(float(self.player.magnet), float(self.player.mult2x), float(self.player.super_sneakers), float(self.player.pogo_active), float(self.player.jetpack))
                if remaining_chain <= 0:
                    restore_duration = 1.8 * self._special_duration_scale()
                    if magnet_expired:
                        self._activate_magnet(restore_duration)
                    elif jetpack_expired:
                        self._activate_jetpack(restore_duration)
                    elif mult_expired:
                        self.player.mult2x = max(self.player.mult2x, restore_duration)
                    elif sneakers_expired:
                        self.player.super_sneakers = max(self.player.super_sneakers, restore_duration)
                    elif pogo_expired:
                        self.player.pogo_active = max(self.player.pogo_active, restore_duration)
                    self._special_run_used_flags.add(_sx(1533))
                    self._mark_special_item_consumed(_sx(1532))
                    self.audio.play(_sx(19), channel=_sx(44))
                    self.speaker.speak(_sx(1842), interrupt=False)
        self._guard_loop_timer = max(0.0, self._guard_loop_timer - delta_time)
        if self.state.running and (not self.state.paused) and (self._guard_loop_timer > 0):
            self.audio.play(_sx(93), loop=True, channel=_sx(194), gain=0.72)
        else:
            self.audio.stop(_sx(194))

    def _spawn_things(self, delta_time: float) -> None:
        self.state.next_spawn -= delta_time
        self.state.next_coinline -= delta_time
        self.state.next_support -= delta_time
        if self._practice_mode_active:
            progress = self.speed_profile.progress(self.state.time) if self._practice_speed_scaling_active else 0.0
            difficulty = _sx(199)
        else:
            progress = self.speed_profile.progress(self.state.time)
            difficulty = self._difficulty_key()
        if self.state.next_spawn <= 0:
            if self.spawn_director.should_delay_spawn(self.obstacles):
                self.state.next_spawn = 0.3
            else:
                pattern = self._choose_playable_pattern(progress, difficulty)
                if pattern is None:
                    self.state.next_spawn = 0.35
                else:
                    chosen_pattern, distance = pattern
                    self._spawn_pattern(chosen_pattern, distance)
                    minimum_gap = 1.05 if difficulty == _sx(199) else 0.85
                    spawn_gap_scale = 1.0
                    if self._special_timer(_sx(1562)) > 0:
                        spawn_gap_scale *= 1.22
                    if self._season_imprint_matches(_sx(1776)):
                        spawn_gap_scale *= 1.08
                    self.state.next_spawn = max(minimum_gap, self.spawn_director.next_encounter_gap(progress, difficulty=difficulty)) * spawn_gap_scale
        if not self._practice_mode_active and self.state.next_coinline <= 0:
            lane = self.spawn_director.choose_coin_lane(self.player.lane)
            self._spawn_coin_line(lane, start_distance=self.spawn_director.base_spawn_distance(progress, self.state.speed, difficulty=difficulty) - 7.5)
            self.state.next_coinline = max(1.55, self.spawn_director.next_coin_gap(progress, difficulty=difficulty))
        if not self._practice_mode_active and self.state.next_support <= 0:
            kind = self._choose_support_spawn_kind()
            lane = self.spawn_director.support_lane(self.player.lane)
            distance = self.spawn_director.base_spawn_distance(progress, self.state.speed, difficulty=difficulty) + 1.5
            self._spawn_support_collectible(kind, lane, distance)
            self.state.next_support = max(5.5, self.spawn_director.next_support_gap(progress, difficulty=difficulty))

    def _spawn_pattern(self, pattern: RoutePattern, base_distance: float) -> None:
        for entry in pattern.entries:
            if self._practice_mode_active and entry.kind not in PRACTICE_HAZARD_KINDS:
                continue
            self.obstacles.append(Obstacle(kind=entry.kind, lane=entry.lane, z=base_distance + entry.z_offset))

    def _choose_playable_pattern(self, progress: float, difficulty: str | None=None) -> Optional[tuple[RoutePattern, float]]:
        selected_difficulty = difficulty or self._difficulty_key()
        for pattern in self.spawn_director.candidate_patterns(progress, difficulty=selected_difficulty):
            distance = self.spawn_director.base_spawn_distance(progress, self.state.speed, difficulty=selected_difficulty)
            if not self.spawn_director.pattern_is_playable(pattern, distance, self.obstacles, current_lane=self.player.lane):
                continue
            self.spawn_director.accept_pattern(pattern)
            return (pattern, distance)
        return None

    def _spawn_coin_line(self, lane: int, start_distance: float) -> None:
        start_distance = max(18.0, start_distance)
        for index in range(6):
            self.obstacles.append(Obstacle(kind=_sx(18), lane=lane, z=start_distance + index * 2.2, value=1))

    def _spawn_support_collectible(self, kind: str, lane: int, distance: float) -> None:
        if kind == _sx(1138):
            next_letter = self._next_word_letter()
            if next_letter:
                self.obstacles.append(Obstacle(kind=_sx(1138), lane=lane, z=distance, label=next_letter))
                return
            kind = _sx(1012)
        if kind == _sx(1139):
            self.obstacles.append(Obstacle(kind=_sx(1139), lane=lane, z=distance, label=_sx(1843)))
            return
        if kind == _sx(1140):
            self.obstacles.append(Obstacle(kind=_sx(1140), lane=lane, z=distance, label=_sx(1844)))
            return
        if kind == _sx(598):
            self.obstacles.append(Obstacle(kind=_sx(598), lane=lane, z=distance, label=_sx(1845)))
            return
        if kind == _sx(1141):
            self.obstacles.append(Obstacle(kind=_sx(1141), lane=lane, z=distance, label=_sx(1846)))
            return
        if kind == _sx(1012):
            obstacle_kind = _sx(1013) if random.random() < 0.22 else _sx(1012)
        else:
            obstacle_kind = kind
        self.obstacles.append(Obstacle(kind=obstacle_kind, lane=lane, z=distance))

    def _handle_obstacles(self) -> None:
        hit_distance = 2.1
        pickup_distance = 2.2
        for obstacle in self.obstacles:
            if obstacle.kind == _sx(18) and -0.5 < obstacle.z < pickup_distance:
                if self.player.jetpack > 0:
                    self._collect_coin(obstacle)
                    obstacle.z = -999
                elif self.player.headstart > 0:
                    obstacle.z = -999
                elif obstacle.lane == self.player.lane:
                    self._collect_coin(obstacle)
                    obstacle.z = -999
                elif (self.player.magnet > 0 or (self._special_timer(_sx(1526)) > 0 and abs(obstacle.lane - self.player.lane) <= 1 and (random.random() < 0.45))) and abs(obstacle.lane - self.player.lane) <= 1:
                    self._collect_coin(obstacle)
                    obstacle.z = -999
            if obstacle.kind in (_sx(1012), _sx(1013), _sx(569), _sx(1138), _sx(1139), _sx(1140), _sx(598), _sx(1141)) and -0.8 < obstacle.z < 2.4:
                if self.player.jetpack > 0:
                    continue
                if self.player.headstart > 0:
                    obstacle.z = -999
                    continue
                if obstacle.lane == self.player.lane:
                    if obstacle.kind == _sx(1012):
                        self._collect_power()
                    elif obstacle.kind == _sx(569):
                        self._collect_key()
                    elif obstacle.kind == _sx(1138):
                        self._collect_word_letter(obstacle)
                    elif obstacle.kind == _sx(1139):
                        self._collect_season_token()
                    elif obstacle.kind == _sx(1140):
                        self._collect_multiplier_pickup()
                    elif obstacle.kind == _sx(598):
                        self._collect_super_mysterizer()
                    elif obstacle.kind == _sx(1141):
                        self._collect_pogo_stick()
                    else:
                        self._collect_box()
                    obstacle.z = -999
            if obstacle.kind in (_sx(643), _sx(644), _sx(97), _sx(645)) and -0.8 < obstacle.z < hit_distance:
                if self.player.jetpack > 0 or self.player.headstart > 0 or obstacle.lane != self.player.lane:
                    continue
                if self.player.pogo_active > 0 and self.player.y > 1.0:
                    continue
                if obstacle.kind in (_sx(644), _sx(645)) and self.player.y > 0.6:
                    continue
                if obstacle.kind == _sx(97) and self.player.rolling > 0:
                    continue
                if self._special_timer(_sx(1769)) > 0:
                    continue
                self._on_hit(obstacle.kind)
                obstacle.z = -999

    def _collect_coin(self, obstacle: Obstacle) -> None:
        self._add_run_coins(1)
        self._record_mission_event(_sx(363))
        self._coin_streak += 1
        if self._coin_streak % 7 == 0:
            self._coin_pitch_index = min(self._coin_pitch_index + 1, 12)
        pitch = 1.0 + self._coin_pitch_index * 0.08
        self._coin_pitch_timer = 3.0
        self._coin_streak_grace_timer = 0.0
        self.audio.play(_sx(18), pan=lane_to_pan(obstacle.lane), channel=_sx(18), pitch=pitch)
        announce_every = int(self.settings.get(_sx(320), 10) or 0)
        if self._coin_counters_enabled() and announce_every and (self.state.coins % announce_every == 0):
            self.speaker.speak(_sx(1534).format(self.state.coins), interrupt=False)

    def _collect_power(self) -> None:
        self._record_mission_event(_sx(367))
        self.audio.play(_sx(19), channel=_sx(43))
        reward = random.choices([_sx(633), _sx(1017), _sx(634), _sx(635)], weights=[0.35, 0.2, 0.3, 0.15], k=1)[0]
        self._apply_power_reward(reward, from_headstart=False)

    def _collect_multiplier_pickup(self) -> None:
        self._record_mission_event(_sx(367))
        self._record_run_powerup(_sx(634))
        self.audio.play(_sx(19), channel=_sx(43))
        self.player.mult2x = max(self.player.mult2x, self._powerup_duration(_sx(634)))
        self.speaker.speak(_sx(1142), interrupt=False)

    def _collect_super_mysterizer(self) -> None:
        self._record_mission_event(_sx(368))
        self._open_super_mystery_box(_sx(619))

    def _launch_pogo_bounce(self) -> None:
        if self.player.pogo_active <= 0 or self.player.jetpack > 0 or self.player.headstart > 0:
            return
        if self.player.y > 0.01 or self.player.vy > 0.01:
            return
        self.player.rolling = 0.0
        self.player.vy = 14.6
        self.audio.play(_sx(13), channel=_sx(43))

    def _collect_pogo_stick(self) -> None:
        self._record_mission_event(_sx(367))
        self._record_run_powerup(_sx(1141))
        self.audio.play(_sx(19), channel=_sx(43))
        self.player.pogo_active = max(self.player.pogo_active, POGO_STICK_DURATION)
        self._launch_pogo_bounce()
        self.speaker.speak(_sx(1143), interrupt=False)

    def _pick_track_box_reward(self) -> str:
        if self._special_active(_sx(1016)):
            self._box_high_tier_meter += 1
            bonus = min(0.5, 0.08 * self._box_high_tier_meter)
            if self._season_imprint_matches(_sx(1309)):
                bonus = min(0.6, bonus + 0.07)
            if random.random() < bonus:
                self._box_high_tier_meter = 0
                self._mark_special_item_consumed(_sx(1016))
                return random.choice([_sx(636), _sx(569), _sx(595), _sx(596)])
        if self._active_event_profile.get(_sx(617)):
            return random.choices([_sx(363), _sx(636), _sx(637), _sx(569), _sx(595), _sx(596), _sx(638)], weights=[52, 16, 12, 8, 6, 4, 2], k=1)[0]
        return pick_mystery_box_reward()

    def _collect_box(self) -> None:
        self._record_mission_event(_sx(368))
        self._record_achievement_metric(_sx(373), 1)
        reward = self._pick_track_box_reward()
        self.speaker.speak(_sx(1046), interrupt=True)
        self.audio.play(_sx(98), channel=_sx(43))
        if reward == _sx(363):
            gain = random.randint(10, 40)
            self._add_run_coins(gain)
            self.speaker.speak(_sx(1348).format(gain), interrupt=False)
            self.audio.play(_sx(105), channel=_sx(180))
        elif reward == _sx(636):
            self.settings[_sx(335)] = int(self.settings.get(_sx(335), 0)) + 1
            self.player.hoverboards += 1
            self.speaker.speak(_sx(1771), interrupt=False)
            self.audio.play(_sx(108), channel=_sx(180))
        elif reward == _sx(637):
            self.state.multiplier = min(10, self.state.multiplier + 1)
            self.speaker.speak(_sx(1847).format(self.state.multiplier), interrupt=False)
            self.audio.play(_sx(100), channel=_sx(180))
        elif reward == _sx(569):
            self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + 1
            self.speaker.speak(_sx(1868), interrupt=False)
            self.audio.play(_sx(108), channel=_sx(180))
        elif reward == _sx(595):
            self.settings[_sx(336)] = int(self.settings.get(_sx(336), 0)) + 1
            self.speaker.speak(_sx(1876), interrupt=False)
            self.audio.play(_sx(110), channel=_sx(180))
        elif reward == _sx(596):
            self.settings[_sx(337)] = int(self.settings.get(_sx(337), 0)) + 1
            self.speaker.speak(_sx(1886), interrupt=False)
            self.audio.play(_sx(110), channel=_sx(180))
        else:
            self.speaker.speak(_sx(1047), interrupt=False)

    def _collect_key(self) -> None:
        self.settings[_sx(334)] = int(self.settings.get(_sx(334), 0)) + 1
        if self._special_active(_sx(1144)):
            chance = 0.35 + (0.1 if self._season_imprint_matches(_sx(1309)) else 0.0)
            if random.random() < chance:
                self._pending_overclock_keys += 1
                self._mark_special_item_consumed(_sx(1144))
        self.audio.play(_sx(108), channel=_sx(180))
        self.speaker.speak(_sx(1145).format(self.settings[_sx(334)]), interrupt=False)

    def _collect_word_letter(self, obstacle: Obstacle) -> None:
        expected_letter = self._next_word_letter()
        if not expected_letter or obstacle.label != expected_letter:
            return
        letter, completed = register_word_letter(self.settings)
        if not letter:
            return
        self.audio.play(_sx(109), channel=_sx(180))
        if completed:
            self.speaker.speak(_sx(1536).format(letter), interrupt=False)
            self._complete_word_hunt()
            return
        remaining_letters = len(self._remaining_word_letters())
        self.speaker.speak(_sx(1146).format(letter, remaining_letters), interrupt=False)

    def _collect_season_token(self) -> None:
        tokens, next_threshold = register_season_token(self.settings)
        self._record_achievement_metric(_sx(376), 1)
        self.audio.play(_sx(90), channel=_sx(180))
        if can_claim_season_reward(self.settings):
            self.speaker.speak(_sx(1539), interrupt=False)
            self._claim_season_reward()
            return
        if next_threshold is None:
            self.speaker.speak(_sx(1540).format(tokens), interrupt=False)
            return
        self.speaker.speak(_sx(1147).format(tokens, next_threshold), interrupt=False)

    def _activate_magnet(self, duration: float) -> None:
        was_inactive = self.player.magnet <= 0
        self.player.magnet = max(self.player.magnet, float(duration))
        if was_inactive and self.player.jetpack <= 0 and (self.player.headstart <= 0):
            self.audio.play(_sx(94), loop=True, channel=_sx(198))
            self._magnet_loop_active = True

    def _activate_jetpack(self, duration: float) -> None:
        was_inactive = self.player.jetpack <= 0
        self.player.jetpack = max(self.player.jetpack, float(duration))
        self.player.y = 2.0
        self.player.vy = 0.0
        if was_inactive and self.state.running and (not self.state.paused):
            self.audio.play(_sx(95), loop=True, channel=_sx(197))
            self._jetpack_loop_active = True

    def _character_adjusted_power_duration(self, duration: float) -> float:
        return float(duration) * self._active_character_bonuses.power_duration_multiplier

    def _apply_power_reward(self, reward: str, from_headstart: bool) -> None:
        if reward == _sx(633):
            self._record_run_powerup(_sx(633))
            self._activate_magnet(self._powerup_duration(_sx(633)))
            message = _sx(1542) if from_headstart else _sx(1543)
            self.speaker.speak(message, interrupt=False)
            return
        if reward == _sx(1017):
            self._record_run_powerup(_sx(1017))
            self._activate_jetpack(self._powerup_duration(_sx(1017)))
            self.speaker.speak(_sx(1544), interrupt=False)
            return
        if reward == _sx(634):
            self._record_run_powerup(_sx(634))
            self.player.mult2x = max(self.player.mult2x, self._powerup_duration(_sx(634)))
            message = _sx(1545) if from_headstart else _sx(1546)
            self.speaker.speak(message, interrupt=False)
            return
        if reward == _sx(635):
            self._record_run_powerup(_sx(635))
            self.player.super_sneakers = self._powerup_duration(_sx(635))
            message = _sx(1547) if from_headstart else _sx(1548)
            self.speaker.speak(message, interrupt=False)

    def _queue_revive_or_finish(self) -> None:
        if self._practice_mode_active:
            self._finish_run_loss()
            return
        if int(self.state.revives_used) >= REVIVE_MAX_USES_PER_RUN:
            self._finish_run_loss()
            return
        cost = revive_cost(self.state.revives_used)
        if int(self.settings.get(_sx(334), 0)) < cost:
            self._finish_run_loss()
            return
        self.state.paused = True
        self.audio.play(_sx(28), channel=_sx(44))
        self.audio.play(_sx(106), channel=_sx(180))
        self._refresh_revive_menu_label()
        self._set_active_menu(self.revive_menu)
        self.speaker.speak(_sx(1148).format(cost, _sx(294) if cost != 1 else _sx(2)), interrupt=True)

    def _revive_run(self) -> None:
        if int(self.state.revives_used) >= REVIVE_MAX_USES_PER_RUN:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1550).format(REVIVE_MAX_USES_PER_RUN), interrupt=True)
            self._finish_run_loss(_sx(1009))
            return
        cost = revive_cost(self.state.revives_used)
        owned = int(self.settings.get(_sx(334), 0))
        if owned < cost:
            self.audio.play(_sx(52), channel=_sx(180))
            self.speaker.speak(_sx(1551), interrupt=True)
            return
        self.settings[_sx(334)] = owned - cost
        self.state.revives_used += 1
        self.state.paused = False
        self.player.stumbles = 0
        self.player.rolling = 0.0
        self.player.y = 0.0
        self.player.vy = 0.0
        self.player.hover_active = max(self.player.hover_active, 3.5)
        self._guard_loop_timer = 0.0
        self._set_active_menu(None)
        self.audio.play(_sx(108), channel=_sx(180))
        self.audio.play(_sx(19), channel=_sx(43))
        self.speaker.speak(_sx(1149), interrupt=True)

    def _finish_run_loss(self, death_reason: Optional[str]=None) -> None:
        self.state.paused = False
        self._stop_spatial_audio()
        self.audio.play(_sx(27), channel=_sx(41))
        self.audio.play(_sx(92), channel=_sx(1552))
        self.audio.play(_sx(91), channel=_sx(1553))
        self.audio.play(_sx(26), channel=_sx(43))
        self.audio.play(_sx(28), channel=_sx(44))
        summary_reason = death_reason or self._last_death_reason or _sx(1009)
        self.speaker.speak(_sx(1150).format(int(self.state.score), summary_reason), interrupt=True)
        self._commit_run_rewards()
        self.audio.stop(_sx(194))
        self.audio.stop(_sx(198))
        self.audio.stop(_sx(197))
        self._stop_spatial_audio()
        self.spatial_audio.reset()
        self._open_game_over_dialog(summary_reason)

    def _stop_spatial_audio(self) -> None:
        for lane in LANES:
            self.audio.stop(_sx(1555).format(lane))

    @staticmethod
    def _stumble_sound_for_variant(variant: str) -> str:
        return {_sx(643): _sx(23), _sx(645): _sx(24), _sx(644): _sx(22), _sx(97): _sx(22)}.get(variant, _sx(22))

    def _on_hit(self, variant: str=_sx(643)) -> None:
        if self._special_timer(_sx(1556)) > 0:
            self._set_special_timer(_sx(1556), 0.0)
            self._mark_special_item_consumed(_sx(1556))
            self.audio.play(_sx(112), channel=_sx(43))
            self.speaker.speak(_sx(1557), interrupt=False)
            return
        if self.player.hover_active > 0:
            self.player.hover_active = 0.0
            self.audio.play(_sx(25), channel=_sx(43))
            self.audio.play(_sx(20), channel=_sx(44))
            self.speaker.speak(_sx(1558), interrupt=True)
            return
        self._last_death_reason = self._death_reason_for_variant(variant)
        if self._special_active(_sx(1559)) and _sx(1560) not in self._special_run_used_flags:
            self._special_run_used_flags.add(_sx(1560))
            self._mark_special_item_consumed(_sx(1559))
            self.player.stumbles = max(0, self.player.stumbles)
            self.audio.play(_sx(22), channel=_sx(43))
            self.speaker.speak(_sx(1561), interrupt=True)
            return
        self.player.stumbles += 1
        if self.player.stumbles >= 2:
            self._guard_loop_timer = 0.0
            self._queue_revive_or_finish()
            return
        self._guard_loop_timer = GUARD_LOOP_DURATION
        self.audio.play(self._stumble_sound_for_variant(variant), channel=_sx(43))
        self.speaker.speak(_sx(1151), interrupt=True)

    def _update_near_miss_audio(self) -> None:
        active_signatures: set[tuple[str, int]] = set()
        for obstacle in self.obstacles:
            if obstacle.kind not in {_sx(643), _sx(644), _sx(97), _sx(645)}:
                continue
            if not -0.2 <= obstacle.z <= 2.1:
                continue
            lane_delta = abs(obstacle.lane - self.player.lane)
            if lane_delta > 1:
                continue
            if lane_delta == 0:
                if obstacle.kind in {_sx(644), _sx(645)} and self.player.y > 0.6:
                    pass
                elif obstacle.kind == _sx(97) and self.player.rolling > 0:
                    pass
                else:
                    continue
            signature = (obstacle.kind, id(obstacle))
            active_signatures.add(signature)
            if signature in self._near_miss_signatures:
                continue
            if obstacle.kind == _sx(643):
                sound_key = _sx(113)
            elif lane_delta == 0:
                sound_key = _sx(112)
            else:
                sound_key = _sx(111)
            self._record_run_metric(_sx(966))
            if self._special_active(_sx(1562)):
                crowd_duration = 4.0 * self._special_duration_scale()
                if self._season_imprint_matches(_sx(1776)):
                    crowd_duration += 1.0
                self._extend_special_timer(_sx(1562), crowd_duration)
                self._mark_special_item_consumed(_sx(1562))
            if self._special_active(_sx(1563)):
                gain = 1
                if self._season_imprint_matches(_sx(1777)):
                    gain = 2
                self.settings[_sx(352)][_sx(597)] = int(self.settings[_sx(352)].get(_sx(597), 0)) + gain
                self._mark_special_item_consumed(_sx(1563))
            self.audio.play(sound_key, channel=_sx(1778).format(obstacle.lane))
        self._near_miss_signatures = active_signatures

    def _draw_menu(self, menu: Menu) -> None:
        width, height = self.screen.get_size()
        self.screen.fill((10, 10, 15))
        title_surface = self.big.render(menu.title, True, (240, 240, 240))
        self.screen.blit(title_surface, (40, 32))
        list_top = 110
        row_height = 38
        visible_rows = 9 if menu == self.learn_sounds_menu else 10
        max_start_index = max(0, len(menu.items) - visible_rows)
        start_index = max(0, min(menu.index - visible_rows // 2, max_start_index))
        visible_items = menu.items[start_index:start_index + visible_rows]
        y_position = list_top
        if menu in {self.shop_menu, self.me_menu, self.character_menu, self.character_detail_menu, self.board_menu, self.board_detail_menu, self.item_upgrade_menu, self.item_upgrade_detail_menu, self.collection_menu}:
            coins_surface = self.font.render(self._shop_coins_label(), True, (220, 220, 220))
            self.screen.blit(coins_surface, (70, y_position))
            y_position += 40
        for relative_index, item in enumerate(visible_items):
            actual_index = start_index + relative_index
            color = (255, 255, 0) if actual_index == menu.index else (220, 220, 220)
            label_surface = self.font.render(item.label, True, color)
            self.screen.blit(label_surface, (70, y_position))
            y_position += row_height
        if start_index > 0:
            top_more = self.font.render(_sx(1450), True, (160, 160, 160))
            self.screen.blit(top_more, (40, list_top - 28))
        if start_index + len(visible_items) < len(menu.items):
            bottom_more = self.font.render(_sx(1450), True, (160, 160, 160))
            self.screen.blit(bottom_more, (40, y_position - 8))
        hint_text = self._menu_navigation_hint()
        if menu == self.learn_sounds_menu:
            description_lines = textwrap.wrap(self._learn_sound_description, width=62)[:3]
            description_top = min(height - 132, y_position + 18)
            prompt_surface = self.font.render(_sx(1564), True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, description_top))
            for line_index, line in enumerate(description_lines):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, description_top + 32 + line_index * 26))
            hint_text = self._menu_navigation_hint()
        elif menu == self.update_menu:
            description_lines = textwrap.wrap(self._update_status_message, width=62)[:2]
            release_note_lines = textwrap.wrap(self._update_release_notes, width=62)[:5]
            description_top = min(height - 176, y_position + 14)
            prompt_surface = self.font.render(_sx(1779), True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, description_top))
            for line_index, line in enumerate(description_lines):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, description_top + 32 + line_index * 26))
            if self._update_progress_stage in {_sx(761), _sx(1849), _sx(769), _sx(1007)}:
                progress_surface = self.font.render(_sx(729).format(self._update_progress_message or self._update_status_message), True, (190, 210, 190) if self._update_progress_stage == _sx(769) else (180, 180, 180))
                self.screen.blit(progress_surface, (40, description_top + 88))
                percent_surface = self.font.render(_sx(1850).format(int(self._update_progress_percent)), True, (220, 220, 120))
                self.screen.blit(percent_surface, (40, description_top + 116))
                notes_top = description_top + 150
            else:
                notes_top = description_top + 88
            notes_label_surface = self.font.render(_sx(1780), True, (205, 205, 205))
            self.screen.blit(notes_label_surface, (40, notes_top))
            for line_index, line in enumerate(release_note_lines):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, notes_top + 28 + line_index * 24))
            hint_text = self._menu_navigation_hint()
        elif menu == self.help_topic_menu and self._selected_help_topic is not None:
            prompt_surface = self.font.render(_sx(1851), True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, max(height - 100, y_position + 18)))
            hint_text = self._menu_navigation_hint()
        elif menu == self.whats_new_menu and self._selected_info_dialog is not None:
            prompt_surface = self.font.render(_sx(1851), True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, max(height - 100, y_position + 18)))
            hint_text = self._menu_navigation_hint()
        elif menu == self.main_menu:
            selected_description = self._selected_main_menu_description()
            if selected_description:
                description_lines = textwrap.wrap(selected_description, width=62)[:3]
                description_top = min(height - 132, y_position + 18)
                prompt_surface = self.font.render(_sx(1887), True, (205, 205, 205))
                self.screen.blit(prompt_surface, (40, description_top))
                for line_index, line in enumerate(description_lines):
                    line_surface = self.font.render(line, True, (180, 180, 180))
                    self.screen.blit(line_surface, (40, description_top + 32 + line_index * 26))
        elif menu == self.issue_compose_menu:
            description_top = min(height - 180, y_position + 18)
            prompt_surface = self.font.render(_sx(1888), True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, description_top))
            for line_index, line in enumerate(self._issue_draft_preview_lines()):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, description_top + 32 + line_index * 26))
        elif menu in {self.options_menu, self.sapi_menu, self.announcements_menu}:
            hint_text = _sx(3).format(self._menu_navigation_hint(), self._option_adjustment_hint())
        elif menu in {self.keyboard_bindings_menu, self.controller_bindings_menu} and self._binding_capture is not None:
            if self._binding_capture.device == _sx(563):
                if self._keyboard_binding_hold is None:
                    capture_prompt = _sx(1894).format(action_label(self._binding_capture.action_key))
                else:
                    remaining = max(0.0, self._keyboard_binding_hold.remaining_seconds)
                    capture_prompt = _sx(1895).format(remaining, action_label(self._binding_capture.action_key))
            else:
                capture_prompt = _sx(1893).format(action_label(self._binding_capture.action_key))
            prompt_surface = self.font.render(capture_prompt, True, (255, 220, 120))
            self.screen.blit(prompt_surface, (40, max(height - 80, y_position + 18)))
        hint_surface = self.font.render(hint_text, True, (180, 180, 180))
        hint_rect = hint_surface.get_rect(left=40, bottom=max(40, height - 20))
        self.screen.blit(hint_surface, hint_rect)

    def _draw_game(self) -> None:
        width, height = self.screen.get_size()
        self.screen.fill((5, 5, 10))
        lane_width = width // 3
        for index in range(3):
            x = index * lane_width
            pygame.draw.rect(self.screen, (18, 18, 28), (x + 2, 0, lane_width - 4, height))
            pygame.draw.line(self.screen, (40, 40, 60), (x, 0), (x, height), 2)
        for obstacle in self.obstacles:
            if obstacle.z > 60 or obstacle.z < -1:
                continue
            size = max(10, int(1400 / (obstacle.z + 15)))
            lane_index = obstacle.lane + 1
            center_x = lane_index * lane_width + lane_width // 2
            center_y = int(height - 80 - (60 - obstacle.z) * 6)
            color = (200, 80, 80)
            if obstacle.kind == _sx(18):
                color = (240, 200, 40)
                size = max(8, size // 2)
            elif obstacle.kind == _sx(1012):
                color = (60, 200, 220)
            elif obstacle.kind == _sx(1013):
                color = (160, 100, 220)
            elif obstacle.kind == _sx(569):
                color = (80, 220, 255)
                size = max(10, size // 2)
            elif obstacle.kind == _sx(1138):
                color = (250, 235, 90)
                size = max(12, size // 2)
            elif obstacle.kind == _sx(1139):
                color = (255, 145, 60)
                size = max(12, size // 2)
            elif obstacle.kind == _sx(1140):
                color = (255, 210, 70)
                size = max(14, size // 2)
            elif obstacle.kind == _sx(598):
                color = (245, 120, 255)
                size = max(14, size // 2)
            elif obstacle.kind == _sx(1141):
                color = (110, 235, 210)
                size = max(14, size // 2)
            elif obstacle.kind == _sx(97):
                color = (220, 120, 60)
            elif obstacle.kind == _sx(644):
                color = (60, 220, 120)
            elif obstacle.kind == _sx(645):
                color = (40, 160, 60)
            elif obstacle.kind == _sx(643):
                color = (180, 180, 180)
            pygame.draw.rect(self.screen, color, (center_x - size // 2, center_y - size // 2, size, size))
            if obstacle.label:
                glyph_surface = self.font.render(obstacle.label, True, (20, 20, 20))
                glyph_rect = glyph_surface.get_rect(center=(center_x, center_y))
                self.screen.blit(glyph_surface, glyph_rect)
        player_x = (self.player.lane + 1) * lane_width + lane_width // 2
        player_y = height - 120 - int(self.player.y * 40)
        player_height = 50 if self.player.rolling <= 0 else 28
        pygame.draw.rect(self.screen, (80, 160, 255), (player_x - 18, player_y - player_height, 36, player_height))
        hud_parts = [_sx(748).format(int(self.state.score)), _sx(1152).format(self._score_multiplier()), _sx(1153).format(self.state.speed), _sx(1154).format(self.player.hoverboards), _sx(1155).format(int(self.settings.get(_sx(334), 0)))]
        if self._coin_counters_enabled():
            hud_parts.insert(0, _sx(666).format(self.state.coins))
        hud = _sx(877).join(hud_parts)
        if self.player.hover_active > 0:
            hud += _sx(1156)
        if self.player.headstart > 0:
            hud += _sx(1157)
        if self.player.magnet > 0:
            hud += _sx(1158)
        if self.player.jetpack > 0:
            hud += _sx(1159)
        if self.player.mult2x > 0:
            hud += _sx(1160)
        if self.player.super_sneakers > 0:
            hud += _sx(1161)
        if self._practice_mode_active:
            remaining_hazards = max(0, self._practice_hazard_target - self._practice_hazards_cleared)
            hud += _sx(1162).format(self._practice_hazards_cleared, self._practice_hazard_target, remaining_hazards)
        hud_surface = self.font.render(hud, True, (230, 230, 230))
        self.screen.blit(hud_surface, (15, 10))
        if self._quest_changes_enabled():
            next_threshold = next_season_reward_threshold(self.settings)
            word = self._current_word()
            found_letters = str(self.settings.get(_sx(343), _sx(2)))
            season_progress = _sx(1248).format(int(self.settings.get(_sx(347), 0)), next_threshold) if next_threshold is not None else _sx(1572).format(int(self.settings.get(_sx(347), 0)))
            meta_hud = _sx(1163).format(self._mission_status_text(), found_letters or _sx(554), word, season_progress)
            meta_surface = self.font.render(meta_hud, True, (205, 205, 205))
            self.screen.blit(meta_surface, (15, 36))
        if self.state.paused:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            self.screen.blit(overlay, (0, 0))
