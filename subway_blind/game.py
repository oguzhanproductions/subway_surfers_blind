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
from typing import Optional

import pygame

from subway_blind import config as config_module
from subway_blind.audio import (
    Audio,
    Speaker,
    SAPI_RATE_MAX,
    SAPI_RATE_MIN,
    SAPI_PITCH_MAX,
    SAPI_PITCH_MIN,
    SAPI_VOICE_UNAVAILABLE_LABEL,
    SAPI_VOLUME_MAX,
    SAPI_VOLUME_MIN,
    SYSTEM_DEFAULT_OUTPUT_LABEL,
)
from subway_blind.balance import SpeedProfile, speed_profile_for_difficulty
from subway_blind.boards import (
    board_definition,
    board_definitions,
    board_unlocked,
    ensure_board_state,
    selected_board_definition,
)
from subway_blind.characters import (
    CharacterRuntimeBonuses,
    character_definition,
    character_definitions,
    character_level,
    character_perk_summary,
    character_runtime_bonuses,
    character_unlocked,
    ensure_character_progress_state,
    next_character_upgrade_cost,
    selected_character_definition,
)
from subway_blind.config import resource_path
from subway_blind.collections import (
    collection_bonus_summary,
    collection_definitions,
    collection_progress,
    collection_runtime_bonuses,
    completed_collection_keys,
    ensure_collection_state,
)
from subway_blind.controls import (
    ACTION_DEFINITIONS_BY_KEY,
    CONTROLLER_ACTION_ORDER,
    GAME_CONTEXT,
    KEYBOARD_ACTION_ORDER,
    MENU_CONTEXT,
    ControllerSupport,
    action_label,
    controller_binding_label,
    family_label,
    keyboard_key_label,
)
from subway_blind.events import (
    can_claim_coin_meter_reward,
    can_claim_daily_high_score_reward,
    claim_coin_meter_reward,
    claim_daily_gift,
    claim_daily_high_score_reward,
    claim_login_calendar_reward,
    current_daily_event,
    daily_gift_available,
    ensure_event_state,
    event_runtime_profile,
    featured_character_key,
    login_calendar_available,
    login_calendar_next_day,
    next_coin_meter_threshold,
    next_daily_high_score_threshold,
    record_coin_meter_coins,
    record_daily_score,
    reset_daily_event_progress,
    tomorrow_daily_event,
)
from subway_blind.leaderboard_client import LeaderboardClient, LeaderboardClientError
from subway_blind.item_upgrades import (
    DEFAULT_ITEM_UPGRADE_KEY,
    ensure_item_upgrade_state,
    item_upgrade_definition,
    item_upgrade_definitions,
    item_upgrade_duration,
    item_upgrade_level,
    next_item_upgrade_cost,
)
from subway_blind.features import (
    clamp_headstart_uses,
    HEADSTART_SPEED_BONUS,
    headstart_duration_for_uses,
    HOVERBOARD_DURATION,
    HOVERBOARD_MAX_USES_PER_RUN,
    pick_headstart_end_reward,
    pick_mystery_box_reward,
    pick_shop_mystery_box_reward,
    revive_cost,
    REVIVE_MAX_USES_PER_RUN,
    SHOP_PRICES,
    shop_box_reward_amount,
    score_booster_bonus,
)
from subway_blind.menu import Menu, MenuItem
from subway_blind.models import LANES, Obstacle, Player, RunState, lane_name, lane_to_pan, normalize_lane
from subway_blind.native_windows_credentials import (
    CredentialPromptCancelled,
    NativeCredentialPromptError,
    prompt_for_credentials,
)
from subway_blind.progression import (
    achievement_definitions,
    achievement_progress,
    active_word_for_settings,
    can_claim_season_reward,
    claim_season_reward,
    completed_mission_metrics,
    ensure_progression_state,
    mission_goals_for_set,
    newly_unlocked_achievements,
    next_season_reward_threshold,
    pick_super_mystery_box_reward,
    record_achievement_progress,
    register_season_token,
    register_word_letter,
    remaining_word_letters,
    reset_daily_word_hunt_progress,
    set_achievement_progress_max,
    update_word_hunt_streak,
    word_hunt_reward_for_streak,
)
from subway_blind.quests import (
    can_claim_meter_reward,
    claim_meter_reward,
    claim_quest,
    daily_quests,
    ensure_quest_state,
    next_meter_threshold,
    quest_claimed,
    quest_completed,
    quest_progress,
    quest_sneakers,
    record_quest_metric,
    reset_daily_quest_progress,
    seasonal_quests,
)
from subway_blind.spawn import RoutePattern, SpawnDirector
from subway_blind.spatial_audio import SpatialThreatAudio
from subway_blind.updater import (
    GitHubReleaseUpdater,
    UpdateCheckResult,
    UpdateInstallProgress,
    UpdateInstallResult,
    version_key,
)
from subway_blind.version import APP_VERSION

DIFFICULTY_LABELS = {
    "easy": "Easy",
    "normal": "Normal",
    "hard": "Hard",
}
LEADERBOARD_PERIOD_LABELS = {
    "season": "Weekly Season",
}
LEADERBOARD_PERIOD_ORDER = tuple(LEADERBOARD_PERIOD_LABELS.keys())
LEADERBOARD_DIFFICULTY_FILTER_LABELS = {
    "all": "All Difficulties",
    "easy": "Easy Only",
    "normal": "Normal Only",
    "hard": "Hard Only",
    "unknown": "Unknown Difficulty",
}
LEADERBOARD_DIFFICULTY_FILTER_ORDER = ("all", "easy", "normal", "hard")
LEADERBOARD_VERIFICATION_LABELS = {
    "verified": "Verified",
    "suspicious": "Suspicious",
}
RUN_POWERUP_LABELS = {
    "magnet": "Magnet",
    "jetpack": "Jetpack",
    "mult2x": "Double Score",
    "sneakers": "Super Sneakers",
    "pogo": "Pogo Stick",
    "hoverboard": "Hoverboard",
}

GUARD_LOOP_DURATION = 1.35
POGO_STICK_DURATION = 5.5
MENU_REPEAT_INITIAL_DELAY = 0.34
MENU_REPEAT_INTERVAL = 0.075
LEARN_SOUND_PREVIEW_CHANNEL = "learn_sound_preview"
LEARN_SOUND_LOOP_PREVIEW_DURATION = 2.6
HEADSTART_SHAKE_CHANNEL = "intro_headstart_shake"
HEADSTART_SPRAY_CHANNEL = "intro_headstart_spray"
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 360


@dataclass(frozen=True)
class BindingCaptureRequest:
    device: str
    action_key: str


@dataclass(frozen=True)
class LearnSoundEntry:
    key: str
    label: str
    description: str
    loop: bool = False
    gain: float = 1.0


@dataclass(frozen=True)
class HelpTopic:
    key: str
    label: str
    description: str


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


LEADERBOARD_CACHE_TTL_SECONDS = 45.0


LEARN_SOUND_DETAILS: dict[str, LearnSoundEntry] = {
    "coin": LearnSoundEntry("coin", "Coin Pickup", "Plays when you collect a coin on the track."),
    "coin_gui": LearnSoundEntry("coin_gui", "Coin Bank", "Plays when coins are added to your saved total."),
    "jump": LearnSoundEntry("jump", "Jump", "Plays when you perform a normal jump."),
    "roll": LearnSoundEntry("roll", "Roll", "Plays when you duck under a high obstacle."),
    "dodge": LearnSoundEntry("dodge", "Lane Change", "Plays when you move left or right between lanes."),
    "announcer_jump_now": LearnSoundEntry("announcer_jump_now", "Announcer Jump Now", "Voice callout that tells you to jump immediately."),
    "announcer_roll_now": LearnSoundEntry("announcer_roll_now", "Announcer Roll Now", "Voice callout that tells you to roll immediately."),
    "announcer_move_left_now": LearnSoundEntry("announcer_move_left_now", "Announcer Move Left Now", "Voice callout that tells you to move left immediately."),
    "announcer_move_right_now": LearnSoundEntry("announcer_move_right_now", "Announcer Move Right Now", "Voice callout that tells you to move right immediately."),
    "landing": LearnSoundEntry("landing", "Landing", "Plays when you land after a normal jump."),
    "stumble": LearnSoundEntry("stumble", "Stumble", "Plays after a standard hit that still leaves one chance."),
    "stumble_side": LearnSoundEntry("stumble_side", "Side Stumble", "Plays after a side impact warning stumble."),
    "stumble_bush": LearnSoundEntry("stumble_bush", "Bush Stumble", "Plays when you hit a bush and survive the impact."),
    "crash": LearnSoundEntry("crash", "Crash", "Plays when a hoverboard absorbs a crash."),
    "death": LearnSoundEntry("death", "Death", "Main run over sound after the final hit."),
    "death_bodyfall": LearnSoundEntry("death_bodyfall", "Body Fall", "Body impact layer used during a full run loss."),
    "death_hitcam": LearnSoundEntry("death_hitcam", "Hit Camera", "Heavy hit layer used during the run over sequence."),
    "guard_catch": LearnSoundEntry("guard_catch", "Guard Catch", "Plays when the guard reaches you after a serious collision."),
    "guard_loop": LearnSoundEntry("guard_loop", "Guard Loop", "Short guard pressure loop after the first stumble.", loop=True, gain=0.72),
    "powerup": LearnSoundEntry("powerup", "Power Up", "Plays when you collect or activate a positive power item."),
    "powerdown": LearnSoundEntry("powerdown", "Power Down", "Plays when a temporary power effect expires."),
    "magnet_loop": LearnSoundEntry("magnet_loop", "Magnet Loop", "Looping sound while the coin magnet is active.", loop=True, gain=0.88),
    "jetpack_loop": LearnSoundEntry("jetpack_loop", "Jetpack Loop", "Looping sound while the jetpack is active.", loop=True, gain=0.88),
    "mystery_box": LearnSoundEntry("mystery_box", "Mystery Box", "Plays when a mystery box is collected or opened."),
    "mission_reward": LearnSoundEntry("mission_reward", "Mission Reward", "Reward chime for milestones, missions, and progress."),
    "train_pass": LearnSoundEntry("train_pass", "Train Pass", "Warning fly-by for a train moving through the scene."),
    "intro_start": LearnSoundEntry("intro_start", "Run Start", "Opening sound when a new run begins."),
    "intro_shake": LearnSoundEntry("intro_shake", "Headstart Shake", "Headstart launch shake effect."),
    "intro_spray": LearnSoundEntry("intro_spray", "Headstart Spray", "Headstart spray layer during the run intro."),
    "gui_cash": LearnSoundEntry("gui_cash", "Cash Reward", "Reward sound for large coin payouts."),
    "gui_close": LearnSoundEntry("gui_close", "Close Burst", "Sharp UI burst used before the revive choice."),
    "gui_tap": LearnSoundEntry("gui_tap", "Shop Tap", "Plays when a shop purchase is accepted."),
    "unlock": LearnSoundEntry("unlock", "Unlock", "Reward unlock sound for items and keys."),
    "left_foot": LearnSoundEntry("left_foot", "Left Footstep", "Regular left foot running step."),
    "right_foot": LearnSoundEntry("right_foot", "Right Footstep", "Regular right foot running step."),
    "sneakers_jump": LearnSoundEntry("sneakers_jump", "Super Sneakers Jump", "High jump launch used by super sneakers and pogo."),
    "sneakers_left": LearnSoundEntry("sneakers_left", "Super Sneakers Left Step", "Enhanced left footstep while super sneakers are active."),
    "sneakers_right": LearnSoundEntry("sneakers_right", "Super Sneakers Right Step", "Enhanced right footstep while super sneakers are active."),
    "slide_letters": LearnSoundEntry("slide_letters", "Letter Slide", "Plays when word hunt letters or intro tiles slide in."),
    "mystery_combo": LearnSoundEntry("mystery_combo", "Mystery Combo", "Bonus layer used for special mystery rewards."),
    "kick": LearnSoundEntry("kick", "Kick", "Impact layer used in the run over sequence."),
    "land_h": LearnSoundEntry("land_h", "Heavy Landing", "Heavy landing used after strong jumps or headstart endings."),
    "swish_short": LearnSoundEntry("swish_short", "Short Near Miss", "Short near-miss pass sound for a very quick close call."),
    "swish_mid": LearnSoundEntry("swish_mid", "Medium Near Miss", "Medium near-miss pass sound for a close call."),
    "swish_long": LearnSoundEntry("swish_long", "Long Near Miss", "Long near-miss pass sound for a sweeping close call."),
}
ACTIVE_GAMEPLAY_SOUND_KEYS: tuple[str, ...] = (
    "coin",
    "coin_gui",
    "jump",
    "roll",
    "dodge",
    "announcer_jump_now",
    "announcer_roll_now",
    "announcer_move_left_now",
    "announcer_move_right_now",
    "landing",
    "stumble",
    "stumble_side",
    "stumble_bush",
    "crash",
    "death",
    "death_bodyfall",
    "death_hitcam",
    "guard_catch",
    "guard_loop",
    "powerup",
    "powerdown",
    "magnet_loop",
    "jetpack_loop",
    "mystery_box",
    "mission_reward",
    "train_pass",
    "intro_start",
    "intro_shake",
    "intro_spray",
    "gui_cash",
    "gui_close",
    "gui_tap",
    "unlock",
    "left_foot",
    "right_foot",
    "sneakers_jump",
    "sneakers_left",
    "sneakers_right",
    "slide_letters",
    "mystery_combo",
    "kick",
    "land_h",
    "swish_short",
    "swish_mid",
    "swish_long",
)
LEARN_SOUND_LIBRARY: tuple[LearnSoundEntry, ...] = tuple(
    LEARN_SOUND_DETAILS[key] for key in ACTIVE_GAMEPLAY_SOUND_KEYS
)
HOW_TO_TOPICS: tuple[HelpTopic, ...] = (
    HelpTopic(
        "movement",
        "Movement and Actions",
        "Move left and right to change lanes. Jump over low barriers and bushes. Roll under high barriers. Press Space to activate your selected hoverboard. Open Start Game to review your active board, headstarts, and score boosters before a run.",
    ),
    HelpTopic(
        "warnings",
        "Hazards and Warnings",
        "Listen for the announcer callouts and the train fly-by sound. The callout focuses on the action needed for your current lane, such as jump, roll, move left, or move right. Near misses, collisions, hoverboard breaks, and guard pressure all have distinct audio layers.",
    ),
    HelpTopic(
        "powerups",
        "Power Ups and Boards",
        "Collect magnets, jetpacks, double score, super sneakers, and pogo sticks to survive longer and build bigger scores. Your selected board also changes hoverboard behavior. Different boards can add double jump, super jump, super speed, smooth drift, sideways zaps, or longer low rolls.",
    ),
    HelpTopic(
        "events",
        "Events and Daily Rewards",
        "Open Events from the main menu to review the current daily event, Daily High Score, Coin Meter, the mini mystery box daily gift, and the Daily Login Calendar. Daily events rotate through Super Mysterizer, Mega Jackpot, featured character bonuses, Super Mystery Box Mania, and Wordy Weekend.",
    ),
    HelpTopic(
        "quests",
        "Missions and Quests",
        "Open Missions from the main menu to review mission sets, quests, and achievements. Mission sets raise your permanent multiplier. Daily and seasonal quests award sneakers, and sneakers fill the quest meter for extra rewards. Word Hunt letters and Season Hunt tokens still appear during runs and remain part of progression.",
    ),
    HelpTopic(
        "collections",
        "Boards and Collections",
        "Open Me from the main menu to manage characters, boards, item upgrades, and collections. Collections complete when you unlock specific character or board sets. Finished collections grant passive bonuses such as stronger coin banking, longer hoverboards, longer power-up duration, or a higher starting multiplier.",
    ),
    HelpTopic(
        "economy",
        "Coins, Keys, and Shop",
        "Collect coins during runs and bank them when the run ends. Keys can revive you after a crash. Spend saved coins in Shop on hoverboards, headstarts, score boosters, mystery boxes, and upgrades. Shop also includes the free daily gift when it is available.",
    ),
    HelpTopic(
        "leaderboard",
        "Leaderboard and Publishing",
        "Open Leaderboard from the main menu after signing in through Options. The board tracks the current weekly season, shows the remaining time and active reward, lets you filter by difficulty, inspect player profiles, and publish finished runs with extended run details and verification status.",
    ),
    HelpTopic(
        "navigation",
        "Menu Navigation",
        "The main menu is organized into Start Game, Events, Missions, Me, Shop, Leaderboard, Options, How to Play, Learn Game Sounds, Check for Updates, and Exit. Use Up and Down to move, Enter to confirm, Escape to go back, and Left or Right when adjusting options.",
    ),
)
UPGRADE_HELP_TOPICS: dict[str, tuple[HelpTopic, ...]] = {
    "1.1.3": (
        HelpTopic(
            "update_1_1_3_audio",
            "Audio Routing Fixes",
            "Version 1.1.3 keeps reward and interface sounds out of the forced HRTF mono path while preserving mono menu feedback cues.",
        ),
        HelpTopic(
            "update_1_1_3_items",
            "Item Upgrades",
            "The Shop now includes an original-style Item Upgrades submenu for Coin Magnet, Jetpack, 2X Multiplier, and Super Sneakers, each with persistent upgrade levels and longer pickup durations.",
        ),
    ),
}
def step_volume(value: float, direction: int) -> float:
    stepped = round(float(value) + (0.01 * direction), 2)
    return max(0.0, min(1.0, stepped))


def step_int(value: int, direction: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value) + direction))


def format_duration_seconds(duration: float) -> str:
    formatted = f"{float(duration):.1f}".rstrip("0").rstrip(".")
    return f"{formatted}s"


def format_play_time(total_seconds: float) -> str:
    total = max(0, int(round(float(total_seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def difficulty_display_label(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()
    return DIFFICULTY_LABELS.get(normalized, "Unknown")


def leaderboard_period_display_label(value: object) -> str:
    normalized = str(value or "season").strip().lower()
    return LEADERBOARD_PERIOD_LABELS.get(normalized, LEADERBOARD_PERIOD_LABELS["season"])


def leaderboard_difficulty_filter_display_label(value: object) -> str:
    normalized = str(value or "all").strip().lower()
    return LEADERBOARD_DIFFICULTY_FILTER_LABELS.get(normalized, LEADERBOARD_DIFFICULTY_FILTER_LABELS["all"])


def verification_display_label(value: object) -> str:
    normalized = str(value or "verified").strip().lower()
    return LEADERBOARD_VERIFICATION_LABELS.get(normalized, LEADERBOARD_VERIFICATION_LABELS["verified"])


def help_topic_segments(topic: HelpTopic, controls_summary: str) -> tuple[str, ...]:
    if topic.key == "movement":
        text = f"Controls: {controls_summary} {topic.description}"
    else:
        text = topic.description
    parts = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    return tuple(parts) if parts else (text.strip(),)


def load_whats_new_content() -> InfoDialogContent:
    fallback = InfoDialogContent(
        title=f"What's New   {APP_VERSION}",
        lines=("No update notes were provided for this version.",),
    )
    try:
        changelog_path = resource_path("CHANGELOG.txt")
        with open(changelog_path, "r", encoding="utf-8") as handle:
            lines = [line.rstrip() for line in handle]
    except Exception:
        return fallback

    entry_lines: list[str] = []
    found_date = False
    for line in lines:
        stripped = line.strip()
        if not found_date:
            if stripped.startswith("Date: "):
                found_date = True
            continue
        if stripped == "------------------------------------------------------------":
            break
        if stripped:
            entry_lines.append(stripped)

    if not entry_lines:
        return fallback
    return InfoDialogContent(title=f"What's New   {APP_VERSION}", lines=tuple(entry_lines))


def copy_text_to_clipboard(text: str) -> bool:
    normalized_text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if sys.platform == "win32" and _copy_text_to_clipboard_windows(normalized_text):
        return True
    return _copy_text_to_clipboard_pygame(normalized_text)


def _copy_text_to_clipboard_windows(text: str) -> bool:
    user32 = getattr(ctypes, "windll", None)
    if user32 is None:
        return False
    user32 = user32.user32
    kernel32 = ctypes.windll.kernel32
    window_handle = int(pygame.display.get_wm_info().get("window", 0) or 0)
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
        global_handle = kernel32.GlobalAlloc(0x0002, bytes_required)
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
    scrap = getattr(pygame, "scrap", None)
    if scrap is None or not pygame.display.get_init():
        return False
    try:
        scrap.init()
    except Exception:
        pass
    try:
        scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
    except Exception:
        return False
    return True


class SubwayBlindGame:
    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        settings: dict,
        updater: GitHubReleaseUpdater | None = None,
        packaged_build: bool | None = None,
    ):
        self.screen = screen
        self.clock = clock
        self.settings = settings
        self.speaker = Speaker.from_settings(settings)
        self.audio = Audio(settings)
        self.updater = updater or GitHubReleaseUpdater()
        self.packaged_build = bool(getattr(sys, "frozen", False)) if packaged_build is None else bool(packaged_build)
        self.font = pygame.font.SysFont("segoeui", 22)
        self.big = pygame.font.SysFont("segoeui", 38, bold=True)
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
        self.speed_profile: SpeedProfile = speed_profile_for_difficulty(str(self.settings["difficulty"]))
        self.spatial_audio = SpatialThreatAudio()
        self.spawn_director = SpawnDirector()
        self.selected_headstarts = 0
        self.selected_score_boosters = 0
        self._footstep_timer = 0.0
        self._left_foot_next = True
        self._run_rewards_committed = False
        self._near_miss_signatures: set[tuple[str, int]] = set()
        self._guard_loop_timer = 0.0
        self._menu_repeat_key: int | None = None
        self._menu_repeat_delay_remaining = 0.0
        self._learn_sound_entries_by_action = {
            f"learn_sound:{entry.key}": entry for entry in LEARN_SOUND_LIBRARY
        }
        self._learn_sound_description = "Press Enter to play the selected game sound."
        self._learn_sound_preview_timer = 0.0
        self._exit_requested = False
        self._latest_update_result: UpdateCheckResult | None = None
        self._update_status_message = "Check GitHub Releases for a newer version."
        self._update_release_notes = "No release notes were provided."
        self._update_progress_percent = 0.0
        self._update_progress_message = ""
        self._update_progress_stage = "idle"
        self._update_progress_announced_bucket = -1
        self._update_install_thread: threading.Thread | None = None
        self._update_install_result: UpdateInstallResult | None = None
        self._update_restart_script_path: str | None = None
        self._update_install_error = ""
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
        self._selected_binding_device = "controller" if self.controls.active_controller() is not None else "keyboard"
        self.leaderboard_client = LeaderboardClient()
        self._leaderboard_username = str(self.settings.get("leaderboard_username", "") or "").strip()
        self._restore_persisted_leaderboard_session()
        self._leaderboard_period_filter = "season"
        self._leaderboard_difficulty_filter = "all"
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
        self._meta_return_menu: Menu | None = None
        self._publish_confirm_return_menu: Menu | None = None
        self._publish_confirm_return_index = 0
        self._game_over_publish_state = "idle"
        self._active_run_stats = self._empty_run_stats()
        self._game_over_summary = self._empty_game_over_summary()
        self._last_death_reason = "Run ended."
        self._pending_menu_announcement: Optional[tuple[Menu, float, bool]] = None
        self._magnet_loop_active = False
        self._jetpack_loop_active = False

        self.pause_menu = Menu(
            self.speaker,
            self.audio,
            "Paused",
            [
                MenuItem("Resume", "resume"),
                MenuItem("Return to Main Menu", "to_main"),
            ],
        )
        self.pause_confirm_menu = Menu(
            self.speaker,
            self.audio,
            "Return to Main Menu?",
            [
                MenuItem("Yes", "confirm_to_main"),
                MenuItem("No", "cancel_to_main"),
            ],
        )
        self.leaderboard_logout_confirm_menu = Menu(
            self.speaker,
            self.audio,
            "Log Out of Leaderboard?",
            [
                MenuItem("Yes", "confirm_leaderboard_logout"),
                MenuItem("No", "cancel_leaderboard_logout"),
            ],
        )
        self.exit_confirm_menu = Menu(
            self.speaker,
            self.audio,
            "Return to Desktop?",
            [
                MenuItem("Yes", "confirm_exit"),
                MenuItem("No", "cancel_exit"),
            ],
        )
        self.revive_menu = Menu(
            self.speaker,
            self.audio,
            "Revive",
            [
                MenuItem(self._revive_option_label(), "revive"),
                MenuItem("End Run", "end_run"),
            ],
        )
        self.publish_confirm_menu = Menu(
            self.speaker,
            self.audio,
            "Publish to Leaderboard?",
            [
                MenuItem("Yes", "publish_confirm_yes"),
                MenuItem("No", "publish_confirm_no"),
            ],
        )
        self.game_over_menu = Menu(
            self.speaker,
            self.audio,
            "Game Over",
            [
                MenuItem("Score: 0", "game_over_info_score"),
                MenuItem("Coins: 0", "game_over_info_coins"),
                MenuItem("Play Time: 00:00", "game_over_info_time"),
                MenuItem("Death reason: Run ended.", "game_over_info_reason"),
                MenuItem("Run again", "game_over_retry"),
                MenuItem("Main menu", "game_over_main_menu"),
            ],
        )
        self.main_menu = Menu(
            self.speaker,
            self.audio,
            self._main_menu_title(),
            self._main_menu_items(),
            description_enabled=self._main_menu_descriptions_enabled,
        )
        self.loadout_menu = Menu(
            self.speaker,
            self.audio,
            "Run Setup",
            [
                MenuItem(self._loadout_board_label(), "loadout_board_info"),
                MenuItem(self._headstart_option_label(), "toggle_headstart"),
                MenuItem(self._score_booster_option_label(), "toggle_score_booster"),
                MenuItem("Begin Run", "begin_run"),
                MenuItem("Back", "back"),
            ],
        )
        self.events_menu = Menu(
            self.speaker,
            self.audio,
            "Events",
            [],
        )
        self.missions_hub_menu = Menu(
            self.speaker,
            self.audio,
            "Missions",
            [],
        )
        self.mission_set_menu = Menu(
            self.speaker,
            self.audio,
            "Mission Set",
            [],
        )
        self.quests_menu = Menu(
            self.speaker,
            self.audio,
            "Quests",
            [],
        )
        self.me_menu = Menu(
            self.speaker,
            self.audio,
            "Me",
            [],
        )
        self.options_menu = Menu(
            self.speaker,
            self.audio,
            "Options",
            self._build_options_menu_items(),
        )
        self.sapi_menu = Menu(
            self.speaker,
            self.audio,
            "SAPI Settings",
            [
                MenuItem(self._sapi_speech_option_label(), "opt_sapi"),
                MenuItem(self._sapi_volume_option_label(), "opt_sapi_volume"),
                MenuItem(self._sapi_voice_option_label(), "opt_sapi_voice"),
                MenuItem(self._sapi_rate_option_label(), "opt_sapi_rate"),
                MenuItem(self._sapi_pitch_option_label(), "opt_sapi_pitch"),
                MenuItem("Back", "back"),
            ],
        )
        self.announcements_menu = Menu(
            self.speaker,
            self.audio,
            "Gameplay Announcements",
            [
                MenuItem(self._meter_option_label(), "opt_meters"),
                MenuItem(self._coin_counter_option_label(), "opt_coin_counters"),
                MenuItem(self._quest_changes_option_label(), "opt_quest_changes"),
                MenuItem(self._pause_on_focus_loss_option_label(), "opt_pause_on_focus_loss"),
                MenuItem("Back", "back"),
            ],
        )
        self.controls_menu = Menu(
            self.speaker,
            self.audio,
            "Controls",
            [],
        )
        self.server_status_menu = Menu(
            self.speaker,
            self.audio,
            "Server",
            [
                MenuItem("Connecting to server...", "server_status_info"),
                MenuItem("Back", "back"),
            ],
        )
        self.leaderboard_menu = Menu(
            self.speaker,
            self.audio,
            "Leaderboard",
            [
                MenuItem("Connect to the server to load leaderboard entries.", "leaderboard_info"),
                MenuItem("Refresh", "leaderboard_refresh"),
                MenuItem("Back", "back"),
            ],
        )
        self.leaderboard_profile_menu = Menu(
            self.speaker,
            self.audio,
            "Player",
            [MenuItem("Back", "back")],
        )
        self.leaderboard_run_detail_menu = Menu(
            self.speaker,
            self.audio,
            "Published Run",
            [MenuItem("Back", "back")],
        )
        self.keyboard_bindings_menu = Menu(
            self.speaker,
            self.audio,
            "Keyboard Bindings",
            [],
        )
        self.controller_bindings_menu = Menu(
            self.speaker,
            self.audio,
            "Controller Bindings",
            [],
        )
        self.shop_menu = Menu(
            self.speaker,
            self.audio,
            self._shop_title(),
            [
                MenuItem(self._shop_hoverboard_label(), "buy_hoverboard"),
                MenuItem(self._shop_box_label(), "buy_box"),
                MenuItem(self._shop_headstart_label(), "buy_headstart"),
                MenuItem(self._shop_score_booster_label(), "buy_score_booster"),
                MenuItem(self._shop_daily_gift_label(), "claim_daily_gift"),
                MenuItem(self._shop_item_upgrade_label(), "open_item_upgrades"),
                MenuItem(self._shop_character_upgrade_label(), "open_character_upgrades"),
                MenuItem("Back", "back"),
            ],
        )
        self.item_upgrade_menu = Menu(
            self.speaker,
            self.audio,
            self._item_upgrade_menu_title(),
            [],
        )
        self.item_upgrade_detail_menu = Menu(
            self.speaker,
            self.audio,
            item_upgrade_definition(self._item_upgrade_detail_key).name,
            [],
        )
        self.character_menu = Menu(
            self.speaker,
            self.audio,
            self._character_menu_title(),
            [],
        )
        self.character_detail_menu = Menu(
            self.speaker,
            self.audio,
            selected_character_definition(self.settings).name,
            [],
        )
        self.board_menu = Menu(
            self.speaker,
            self.audio,
            self._board_menu_title(),
            [],
        )
        self.board_detail_menu = Menu(
            self.speaker,
            self.audio,
            selected_board_definition(self.settings).name,
            [],
        )
        self.collection_menu = Menu(
            self.speaker,
            self.audio,
            self._collection_menu_title(),
            [],
        )
        self.learn_sounds_menu = Menu(
            self.speaker,
            self.audio,
            "Learn Game Sounds",
            [MenuItem(entry.label, f"learn_sound:{entry.key}") for entry in LEARN_SOUND_LIBRARY] + [MenuItem("Back", "back")],
        )
        self.howto_menu = Menu(
            self.speaker,
            self.audio,
            "How to Play",
            [],
        )
        self._refresh_howto_menu_labels()
        self.help_topic_menu = Menu(
            self.speaker,
            self.audio,
            "Help",
            [MenuItem("Back", "back")],
        )
        self._selected_help_topic: HelpTopic | None = None
        self.whats_new_menu = Menu(
            self.speaker,
            self.audio,
            "What's New",
            [MenuItem("Back", "back")],
        )
        self._selected_info_dialog: InfoDialogContent | None = None
        self.achievements_menu = Menu(
            self.speaker,
            self.audio,
            self._achievements_menu_title(),
            [],
        )
        self.update_menu = Menu(
            self.speaker,
            self.audio,
            "Update Required",
            [
                MenuItem("Download and Install Update", "download_update"),
                MenuItem("Open Release Page", "open_release_page"),
                MenuItem("Quit Game", "quit"),
            ],
        )
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
        self._refresh_control_menus()

        self.active_menu: Optional[Menu] = self.main_menu
        if self.packaged_build and bool(self.settings.get("check_updates_on_startup", True)):
            self._show_startup_status("Checking for updates.")
            self._check_for_updates(announce_result=False, automatic=True)
        if self.active_menu == self.main_menu and not self.main_menu.opened:
            self.active_menu.open()
            self._sync_music_context()
        self._sync_character_progress()
        self._mark_current_version_seen()
        self._start_background_leaderboard_sync()

    def _sfx_option_label(self) -> str:
        return f"SFX Volume: {int(float(self.settings['sfx_volume']) * 100)}"

    def _main_menu_title(self) -> str:
        return f"Main Menu   Version: {APP_VERSION}"

    def _achievements_menu_title(self) -> str:
        unlocked = len(self.settings.get("achievements_unlocked", []))
        total = len(achievement_definitions())
        return f"Achievements   {unlocked}/{total}"

    def _howto_menu_title(self) -> str:
        return f"Updated Help   {APP_VERSION}" if self._showing_upgrade_help else "How to Play"

    def _shop_title(self) -> str:
        return "Shop"

    def _shop_coins_label(self) -> str:
        return f"Coins: {int(self.settings.get('bank_coins', 0))}"

    def _music_option_label(self) -> str:
        return f"Music Volume: {int(float(self.settings['music_volume']) * 100)}"

    def _updates_option_label(self) -> str:
        return (
            f"Check for Updates on Startup: "
            f"{'On' if self.settings['check_updates_on_startup'] else 'Off'}"
        )

    def _speech_option_label(self) -> str:
        return f"Speech: {'On' if self.settings['speech_enabled'] else 'Off'}"

    def _sapi_speech_option_label(self) -> str:
        return f"SAPI Speech: {'On' if self.settings['sapi_speech_enabled'] else 'Off'}"

    def _sapi_menu_entry_label(self) -> str:
        return "SAPI Settings"

    def _audio_output_option_label(self) -> str:
        return f"Output Device: {self.audio.output_device_display_name()}"

    def _menu_sound_hrtf_option_label(self) -> str:
        return f"Menu Sound HRTF: {'On' if self.settings['menu_sound_hrtf'] else 'Off'}"

    def _sapi_voice_option_label(self) -> str:
        voice_name = self.speaker.current_sapi_voice_display_name()
        return f"SAPI Voice: {voice_name}"

    def _sapi_rate_option_label(self) -> str:
        return f"SAPI Rate: {int(self.settings.get('sapi_rate', 0))}"

    def _sapi_pitch_option_label(self) -> str:
        return f"SAPI Pitch: {int(self.settings.get('sapi_pitch', 0))}"

    def _sapi_volume_option_label(self) -> str:
        return f"SAPI Volume: {int(self.settings.get('sapi_volume', 100))}"

    def _difficulty_option_label(self) -> str:
        difficulty = DIFFICULTY_LABELS.get(str(self.settings["difficulty"]), "Normal")
        return f"Difficulty: {difficulty}"

    def _meter_option_label(self) -> str:
        return f"Meters: {'On' if self._meters_enabled() else 'Off'}"

    def _coin_counter_option_label(self) -> str:
        return f"Coin Counters: {'On' if self._coin_counters_enabled() else 'Off'}"

    def _quest_changes_option_label(self) -> str:
        return f"Quest Announcements: {'On' if self._quest_changes_enabled() else 'Off'}"

    def _pause_on_focus_loss_option_label(self) -> str:
        return f"Pause on Focus Loss: {'On' if self._pause_on_focus_loss_enabled() else 'Off'}"

    def _main_menu_description_option_label(self) -> str:
        return f"Main Menu Descriptions: {'On' if self._main_menu_descriptions_enabled() else 'Off'}"

    def _leaderboard_account_option_label(self) -> str:
        if self._leaderboard_username:
            return f"Set User Name: {self._leaderboard_username}"
        return "Set User Name"

    def _leaderboard_logout_option_label(self) -> str:
        if self._leaderboard_username:
            return f"Log Out: {self._leaderboard_username}"
        return "Log Out"

    def _leaderboard_is_authenticated(self) -> bool:
        return self.leaderboard_client.is_authenticated()

    def _exit_confirmation_option_label(self) -> str:
        return f"Exit Confirmation: {'On' if self._exit_confirmation_enabled() else 'Off'}"

    def _headstart_option_label(self) -> str:
        owned = int(self.settings.get("headstarts", 0))
        return f"Headstart: {self.selected_headstarts}   Owned: {owned}"

    def _score_booster_option_label(self) -> str:
        owned = int(self.settings.get("score_boosters", 0))
        return f"Score Booster: {self.selected_score_boosters}   Owned: {owned}"

    def _revive_option_label(self) -> str:
        if int(self.state.revives_used) >= REVIVE_MAX_USES_PER_RUN:
            return f"Revive unavailable   Limit reached: {REVIVE_MAX_USES_PER_RUN} per run"
        cost = revive_cost(self.state.revives_used)
        owned = int(self.settings.get("keys", 0))
        return f"Use {cost} key{'s' if cost != 1 else ''} to revive   Owned: {owned}"

    def _shop_hoverboard_label(self) -> str:
        return (
            f"Buy Hoverboard   Cost: {SHOP_PRICES['hoverboard']} Coins   "
            f"Owned: {int(self.settings.get('hoverboards', 0))}"
        )

    def _shop_box_label(self) -> str:
        return f"Open Mystery Box   Cost: {SHOP_PRICES['mystery_box']} Coins"

    def _shop_headstart_label(self) -> str:
        return (
            f"Buy Headstart   Cost: {SHOP_PRICES['headstart']} Coins   "
            f"Owned: {int(self.settings.get('headstarts', 0))}"
        )

    def _shop_score_booster_label(self) -> str:
        return (
            f"Buy Score Booster   Cost: {SHOP_PRICES['score_booster']} Coins   "
            f"Owned: {int(self.settings.get('score_boosters', 0))}"
        )

    def _shop_item_upgrade_label(self) -> str:
        maxed = sum(
            1
            for definition in item_upgrade_definitions()
            if item_upgrade_level(self.settings, definition.key) >= definition.max_level
        )
        return f"Item Upgrades   Maxed: {maxed}/{len(item_upgrade_definitions())}"

    def _shop_character_upgrade_label(self) -> str:
        active_character = selected_character_definition(self.settings)
        return f"Character Upgrades   Active: {active_character.name}"

    def _shop_daily_gift_label(self) -> str:
        return "Free Daily Gift   Available" if daily_gift_available(self.settings) else "Free Daily Gift   Claimed Today"

    def _loadout_board_label(self) -> str:
        board = selected_board_definition(self.settings)
        return f"Board: {board.name}   Power: {board.power_label}"

    def _events_menu_title(self) -> str:
        event = current_daily_event()
        event_coins = int(self.settings.get("event_state", {}).get("event_coins", 0) or 0)
        return f"Events   {event.label}   Event Coins: {event_coins}"

    def _daily_event_info_label(self) -> str:
        event = current_daily_event()
        tomorrow = tomorrow_daily_event()
        featured_key = featured_character_key()
        if event.key == "featured_character_bonus":
            featured_name = character_definition(featured_key).name
            return f"Today: {event.label}   Featured Runner: {featured_name}   Tomorrow: {tomorrow.label}"
        return f"Today: {event.label}   Tomorrow: {tomorrow.label}"

    def _daily_high_score_status_label(self) -> str:
        total = int(self.settings.get("event_state", {}).get("daily_high_score_total", 0) or 0)
        next_threshold = next_daily_high_score_threshold(self.settings)
        if next_threshold is None:
            return f"Daily High Score: {total}   All rewards claimed"
        return f"Daily High Score: {total} of {next_threshold}"

    def _daily_high_score_action_label(self) -> str:
        if can_claim_daily_high_score_reward(self.settings):
            return "Claim Daily High Score Reward"
        next_threshold = next_daily_high_score_threshold(self.settings)
        if next_threshold is None:
            return "Daily High Score Rewards Complete"
        return f"Next Daily High Score Reward at {next_threshold}"

    def _coin_meter_status_label(self) -> str:
        coins = int(self.settings.get("event_state", {}).get("coin_meter_coins", 0) or 0)
        next_threshold = next_coin_meter_threshold(self.settings)
        if next_threshold is None:
            return f"Coin Meter: {coins}   All chests opened"
        return f"Coin Meter: {coins} of {next_threshold}"

    def _coin_meter_action_label(self) -> str:
        if can_claim_coin_meter_reward(self.settings):
            return "Open Coin Meter Chest"
        next_threshold = next_coin_meter_threshold(self.settings)
        if next_threshold is None:
            return "Coin Meter Complete"
        return f"Next Coin Meter Chest at {next_threshold}"

    def _login_calendar_status_label(self) -> str:
        next_day = login_calendar_next_day(self.settings)
        availability = "Available" if login_calendar_available(self.settings) else "Already claimed today"
        return f"Daily Login Calendar: Day {next_day} of 7   {availability}"

    def _login_calendar_action_label(self) -> str:
        if login_calendar_available(self.settings):
            return f"Claim Login Reward   Day {login_calendar_next_day(self.settings)}"
        return "Login Reward Claimed Today"

    def _word_hunt_status_label(self) -> str:
        active_word = active_word_for_settings(self.settings)
        collected = len(active_word) - len(self._remaining_word_letters())
        return f"Word Hunt: {active_word}   {collected}/{len(active_word)} letters"

    def _season_hunt_status_label(self) -> str:
        total = int(self.settings.get("season_tokens", 0) or 0)
        next_threshold = next_season_reward_threshold(self.settings)
        if next_threshold is None:
            return f"Season Hunt: {total} tokens   Track complete"
        return f"Season Hunt: {total} of {next_threshold} tokens"

    def _missions_hub_title(self) -> str:
        completed = len(completed_mission_metrics(self.settings))
        return f"Missions   Set {int(self.settings.get('mission_set', 1))}   {completed}/3"

    def _mission_set_menu_title(self) -> str:
        return f"Mission Set {int(self.settings.get('mission_set', 1))}"

    def _me_menu_title(self) -> str:
        return f"Me   {selected_character_definition(self.settings).name}   {selected_board_definition(self.settings).name}"

    def _board_menu_title(self) -> str:
        active_board = selected_board_definition(self.settings)
        return f"Boards   Active: {active_board.name}"

    def _board_list_item_label(self, key: str) -> str:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            return f"{definition.name}   Locked   Unlock: {definition.unlock_cost} Coins"
        status = "Active" if selected_board_definition(self.settings).key == definition.key else "Unlocked"
        return f"{definition.name}   {status}   {definition.power_label}"

    def _board_status_label(self, key: str) -> str:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            return f"Status: Locked   Unlock cost: {definition.unlock_cost} Coins"
        status = "Active" if selected_board_definition(self.settings).key == definition.key else "Unlocked"
        return f"Status: {status}"

    def _board_power_label(self, key: str) -> str:
        definition = board_definition(key)
        return f"Power: {definition.power_label}   {definition.description}"

    def _board_action_label(self, key: str) -> str:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            return f"Unlock Board   Cost: {definition.unlock_cost} Coins"
        if selected_board_definition(self.settings).key == definition.key:
            return "Board Active"
        return "Set as Active Board"

    def _collection_menu_title(self) -> str:
        completed = len(completed_collection_keys(self.settings))
        total = len(collection_definitions())
        return f"Collections   {completed}/{total}"

    def _collection_item_label(self, key: str) -> str:
        definition = next(item for item in collection_definitions() if item.key == key)
        owned, total = collection_progress(self.settings, definition)
        status = "Complete" if key in completed_collection_keys(self.settings) else "In Progress"
        return f"{definition.name}   {status}   {owned}/{total}   {collection_bonus_summary(definition)}"

    def _quest_menu_title(self) -> str:
        return f"Quests   Sneakers: {quest_sneakers(self.settings)}"

    def _quest_item_label(self, quest_key: str) -> str:
        quest = next(
            item for item in daily_quests() + seasonal_quests() if item.key == quest_key
        )
        progress = min(quest_progress(self.settings, quest), quest.target)
        status = "Claimed" if quest_claimed(self.settings, quest) else ("Ready" if quest_completed(self.settings, quest) else "Active")
        scope_label = "Daily" if quest.scope == "daily" else "Seasonal"
        return f"{scope_label}: {quest.label}   {progress}/{quest.target}   {status}   Sneakers {quest.sneaker_reward}"

    def _quest_meter_label(self) -> str:
        next_threshold = next_meter_threshold(self.settings)
        if next_threshold is None:
            return f"Sneaker Meter: {quest_sneakers(self.settings)}   Complete"
        return f"Sneaker Meter: {quest_sneakers(self.settings)} of {next_threshold}"

    def _quest_meter_action_label(self) -> str:
        if can_claim_meter_reward(self.settings):
            return "Claim Sneaker Meter Reward"
        next_threshold = next_meter_threshold(self.settings)
        if next_threshold is None:
            return "Sneaker Meter Complete"
        return f"Next Sneaker Meter Reward at {next_threshold}"

    def _mission_goal_item_label(self, goal) -> str:
        progress = int(self.settings.get("mission_metrics", {}).get(goal.metric, 0) or 0)
        visible_progress = min(progress, goal.target)
        status = "Completed" if progress >= goal.target else "Active"
        return f"{goal.label}   {visible_progress}/{goal.target}   {status}"

    def _daily_progress_reset_label(self) -> str:
        return "Reset Today's Progress   Keeps claimed rewards"

    def _item_upgrade_menu_title(self) -> str:
        maxed = sum(
            1
            for definition in item_upgrade_definitions()
            if item_upgrade_level(self.settings, definition.key) >= definition.max_level
        )
        return f"Item Upgrades   Maxed: {maxed}/{len(item_upgrade_definitions())}"

    def _item_upgrade_list_item_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        level = item_upgrade_level(self.settings, definition.key)
        duration = item_upgrade_duration(self.settings, definition.key)
        return f"{definition.name}   Level {level}/{definition.max_level}   {self._format_duration_seconds(duration)}"

    def _item_upgrade_status_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        level = item_upgrade_level(self.settings, definition.key)
        return f"Status: Level {level} of {definition.max_level}"

    def _item_upgrade_effect_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        current_duration = item_upgrade_duration(self.settings, definition.key)
        next_cost = next_item_upgrade_cost(self.settings, definition.key)
        if next_cost is None:
            return f"Effect: {definition.description} Pickup duration {self._format_duration_seconds(current_duration)}"
        next_level = item_upgrade_level(self.settings, definition.key) + 1
        next_duration = float(definition.durations[next_level])
        return (
            f"Effect: {definition.description} Current {self._format_duration_seconds(current_duration)}   "
            f"Next {self._format_duration_seconds(next_duration)}"
        )

    def _item_upgrade_action_label(self, key: str) -> str:
        definition = item_upgrade_definition(key)
        next_cost = next_item_upgrade_cost(self.settings, definition.key)
        if next_cost is None:
            return "Max Level Reached"
        next_level = item_upgrade_level(self.settings, definition.key) + 1
        return f"Upgrade to Level {next_level}   Cost: {next_cost} Coins"

    def _character_menu_title(self) -> str:
        active_character = selected_character_definition(self.settings)
        return f"Character Upgrades   Active: {active_character.name}"

    def _character_list_item_label(self, key: str) -> str:
        definition = character_definition(key)
        if not character_unlocked(self.settings, key):
            return f"{definition.name}   Locked   Unlock: {definition.unlock_cost} Coins"
        level = character_level(self.settings, key)
        active_status = "Active" if selected_character_definition(self.settings).key == key else "Unlocked"
        return (
            f"{definition.name}   {active_status}   Level {level}/{definition.max_level}   "
            f"{character_perk_summary(definition, level)}"
        )

    def _character_status_label(self, key: str) -> str:
        definition = character_definition(key)
        if not character_unlocked(self.settings, key):
            return f"Status: Locked   Unlock cost: {definition.unlock_cost} Coins"
        level = character_level(self.settings, key)
        active_status = "Active" if selected_character_definition(self.settings).key == key else "Unlocked"
        return f"Status: {active_status}   Level {level} of {definition.max_level}"

    def _character_perk_label(self, key: str) -> str:
        definition = character_definition(key)
        level = character_level(self.settings, key)
        return f"Perk: {character_perk_summary(definition, level)}"

    def _character_primary_action_label(self, key: str) -> str:
        definition = character_definition(key)
        if not character_unlocked(self.settings, key):
            return f"Unlock Character   Cost: {definition.unlock_cost} Coins"
        if selected_character_definition(self.settings).key == key:
            return "Character Active"
        return "Set as Active Character"

    def _character_upgrade_action_label(self, key: str) -> str:
        if not character_unlocked(self.settings, key):
            return "Unlock character first to upgrade"
        definition = character_definition(key)
        next_cost = next_character_upgrade_cost(self.settings, key)
        if next_cost is None:
            return "Max Level Reached"
        next_level = character_level(self.settings, key) + 1
        return f"Upgrade to Level {next_level}   Cost: {next_cost} Coins"

    def _refresh_options_menu_labels(self) -> None:
        selected_action = ""
        if self.options_menu.items:
            selected_action = self.options_menu.items[min(self.options_menu.index, len(self.options_menu.items) - 1)].action
        self.options_menu.items = self._build_options_menu_items()
        if selected_action:
            self.options_menu.index = self._update_option_index(selected_action)

    def _build_options_menu_items(self) -> list[MenuItem]:
        items = [
            MenuItem(self._sfx_option_label(), "opt_sfx"),
            MenuItem(self._music_option_label(), "opt_music"),
            MenuItem(self._updates_option_label(), "opt_updates"),
            MenuItem(self._audio_output_option_label(), "opt_output"),
            MenuItem(self._menu_sound_hrtf_option_label(), "opt_menu_hrtf"),
            MenuItem(self._speech_option_label(), "opt_speech"),
            MenuItem(self._sapi_menu_entry_label(), "opt_sapi_menu"),
            MenuItem(self._difficulty_option_label(), "opt_diff"),
            MenuItem(self._main_menu_description_option_label(), "opt_main_menu_descriptions"),
            MenuItem(self._leaderboard_account_option_label(), "opt_leaderboard_account"),
        ]
        if self._leaderboard_is_authenticated():
            items.append(MenuItem(self._leaderboard_logout_option_label(), "opt_leaderboard_logout"))
        items.extend(
            [
                MenuItem("Gameplay Announcements", "opt_gameplay_announcements"),
                MenuItem("Controls", "opt_controls"),
                MenuItem(self._exit_confirmation_option_label(), "opt_exit_confirmation"),
                MenuItem("Back", "back"),
            ]
        )
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
        self.loadout_menu.items[0].label = self._loadout_board_label()
        self.loadout_menu.items[1].label = self._headstart_option_label()
        self.loadout_menu.items[2].label = self._score_booster_option_label()

    def _refresh_revive_menu_label(self) -> None:
        self.revive_menu.items[0].label = self._revive_option_label()

    def _refresh_game_over_menu(self) -> None:
        summary = self._game_over_summary
        self.game_over_menu.items[0].label = f"Score: {int(summary['score'])}"
        self.game_over_menu.items[1].label = f"Coins: {int(summary['coins'])}"
        self.game_over_menu.items[2].label = f"Play Time: {format_play_time(summary['play_time_seconds'])}"
        self.game_over_menu.items[3].label = f"Death reason: {summary['death_reason']}"
        self.game_over_menu.items[4].label = "Run again"
        self.game_over_menu.items[5].label = "Main menu"

    @staticmethod
    def _empty_run_stats() -> dict[str, object]:
        return {
            "jumps": 0,
            "rolls": 0,
            "dodges": 0,
            "powerups": 0,
            "boxes": 0,
            "clean_escapes": 0,
            "powerup_usage": {key: 0 for key in RUN_POWERUP_LABELS},
        }

    def _empty_game_over_summary(self) -> dict[str, object]:
        return {
            "score": 0,
            "coins": 0,
            "play_time_seconds": 0,
            "death_reason": "Run ended.",
            "game_version": APP_VERSION,
            "difficulty": self._difficulty_key(),
            "distance_meters": 0,
            "clean_escapes": 0,
            "revives_used": 0,
            "powerup_usage": {},
        }

    def _record_run_metric(self, metric: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        current_value = int(self._active_run_stats.get(metric, 0) or 0)
        self._active_run_stats[metric] = current_value + int(amount)
        for quest in record_quest_metric(self.settings, metric, amount):
            if self._quest_changes_enabled():
                self.audio.play("mission_reward", channel="ui")
                self.speaker.speak(f"Quest ready: {quest.label}.", interrupt=False)

    def _record_run_powerup(self, powerup_key: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        usage = self._active_run_stats.get("powerup_usage")
        if not isinstance(usage, dict):
            usage = {key: 0 for key in RUN_POWERUP_LABELS}
            self._active_run_stats["powerup_usage"] = usage
        normalized_key = str(powerup_key or "").strip().lower()
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
            return "Power-ups: none"
        segments = [f"{RUN_POWERUP_LABELS[key]} {normalized_usage[key]}" for key in RUN_POWERUP_LABELS if key in normalized_usage]
        return "Power-ups: " + ", ".join(segments)

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
        self.item_upgrade_menu.items = [
            MenuItem(self._item_upgrade_list_item_label(definition.key), f"item_upgrade_open:{definition.key}")
            for definition in item_upgrade_definitions()
        ] + [MenuItem("Back", "back")]

    def _refresh_item_upgrade_detail_menu_labels(self, key: str) -> None:
        definition = item_upgrade_definition(key)
        self._item_upgrade_detail_key = definition.key
        next_cost = next_item_upgrade_cost(self.settings, definition.key)
        upgrade_action = (
            f"item_upgrade_purchase:{definition.key}"
            if next_cost is not None
            else f"item_upgrade_max_info:{definition.key}"
        )
        self.item_upgrade_detail_menu.title = definition.name
        self.item_upgrade_detail_menu.items = [
            MenuItem(self._item_upgrade_status_label(definition.key), f"item_upgrade_status_info:{definition.key}"),
            MenuItem(self._item_upgrade_effect_label(definition.key), f"item_upgrade_effect_info:{definition.key}"),
            MenuItem(self._item_upgrade_action_label(definition.key), upgrade_action),
            MenuItem("Back", "back"),
        ]

    def _refresh_character_menu_labels(self) -> None:
        self.character_menu.title = self._character_menu_title()
        self.character_menu.items = [
            MenuItem(self._character_list_item_label(definition.key), f"character_open:{definition.key}")
            for definition in character_definitions()
        ] + [MenuItem("Back", "back")]

    def _refresh_character_detail_menu_labels(self, key: str) -> None:
        definition = character_definition(key)
        self._character_detail_key = definition.key
        self.character_detail_menu.title = definition.name
        if not character_unlocked(self.settings, key):
            primary_action = f"character_unlock:{definition.key}"
        elif selected_character_definition(self.settings).key == definition.key:
            primary_action = f"character_active_info:{definition.key}"
        else:
            primary_action = f"character_select:{definition.key}"
        next_upgrade_cost = next_character_upgrade_cost(self.settings, key)
        if not character_unlocked(self.settings, key):
            upgrade_action = f"character_unlock_hint:{definition.key}"
        elif next_upgrade_cost is None:
            upgrade_action = f"character_max_info:{definition.key}"
        else:
            upgrade_action = f"character_upgrade:{definition.key}"
        self.character_detail_menu.items = [
            MenuItem(self._character_status_label(definition.key), f"character_status_info:{definition.key}"),
            MenuItem(self._character_perk_label(definition.key), f"character_perk_info:{definition.key}"),
            MenuItem(self._character_primary_action_label(definition.key), primary_action),
            MenuItem(self._character_upgrade_action_label(definition.key), upgrade_action),
            MenuItem("Back", "back"),
        ]

    def _refresh_board_menu_labels(self) -> None:
        self.board_menu.title = self._board_menu_title()
        self.board_menu.items = [
            MenuItem(self._board_list_item_label(definition.key), f"board_open:{definition.key}")
            for definition in board_definitions()
        ] + [MenuItem("Back", "back")]

    def _refresh_board_detail_menu_labels(self, key: str) -> None:
        definition = board_definition(key)
        self._board_detail_key = definition.key
        self.board_detail_menu.title = definition.name
        if not board_unlocked(self.settings, definition.key):
            primary_action = f"board_unlock:{definition.key}"
        elif selected_board_definition(self.settings).key == definition.key:
            primary_action = f"board_active_info:{definition.key}"
        else:
            primary_action = f"board_select:{definition.key}"
        self.board_detail_menu.items = [
            MenuItem(self._board_status_label(definition.key), f"board_status_info:{definition.key}"),
            MenuItem(self._board_power_label(definition.key), f"board_power_info:{definition.key}"),
            MenuItem(self._board_action_label(definition.key), primary_action),
            MenuItem("Back", "back"),
        ]

    def _refresh_collection_menu_labels(self) -> None:
        self.collection_menu.title = self._collection_menu_title()
        self.collection_menu.items = [
            MenuItem(self._collection_item_label(definition.key), f"collection_info:{definition.key}")
            for definition in collection_definitions()
        ] + [MenuItem("Back", "back")]

    def _refresh_events_menu_labels(self) -> None:
        ensure_event_state(self.settings)
        self.events_menu.title = self._events_menu_title()
        self.events_menu.items = [
            MenuItem(self._daily_event_info_label(), "event_info"),
            MenuItem(self._daily_high_score_status_label(), "event_info"),
            MenuItem(self._daily_high_score_action_label(), "claim_daily_high_score"),
            MenuItem(self._coin_meter_status_label(), "event_info"),
            MenuItem(self._coin_meter_action_label(), "claim_coin_meter"),
            MenuItem(f"Mini Mystery Box: {'Ready' if daily_gift_available(self.settings) else 'Claimed Today'}", "event_info"),
            MenuItem(self._shop_daily_gift_label(), "claim_daily_gift"),
            MenuItem(self._login_calendar_status_label(), "event_info"),
            MenuItem(self._login_calendar_action_label(), "claim_login_reward"),
            MenuItem(self._word_hunt_status_label(), "event_info"),
            MenuItem(self._season_hunt_status_label(), "event_info"),
            MenuItem("Back", "back"),
        ]

    def _refresh_missions_hub_menu_labels(self) -> None:
        ensure_quest_state(self.settings)
        self.missions_hub_menu.title = self._missions_hub_title()
        self.missions_hub_menu.items = [
            MenuItem(self._quest_menu_title(), "open_quests"),
            MenuItem(self._mission_status_text(), "open_mission_set"),
            MenuItem(self._achievements_menu_title(), "open_achievements"),
            MenuItem("Back", "back"),
        ]

    def _refresh_mission_set_menu_labels(self) -> None:
        ensure_progression_state(self.settings)
        self.mission_set_menu.title = self._mission_set_menu_title()
        items = [
            MenuItem(self._mission_goal_item_label(goal), "mission_info")
            for goal in self._mission_goals()
        ]
        items.append(MenuItem(f"Permanent Multiplier: x{1 + int(self.settings.get('mission_multiplier_bonus', 0))}", "mission_info"))
        items.append(MenuItem("Back", "back"))
        self.mission_set_menu.items = items

    def _refresh_quest_menu_labels(self) -> None:
        ensure_quest_state(self.settings)
        self.quests_menu.title = self._quest_menu_title()
        items = [
            MenuItem(self._quest_meter_label(), "quest_info"),
            MenuItem(self._quest_meter_action_label(), "claim_quest_meter"),
        ]
        for quest in daily_quests():
            action = f"claim_quest:{quest.key}" if quest_completed(self.settings, quest) and not quest_claimed(self.settings, quest) else "quest_info"
            items.append(MenuItem(self._quest_item_label(quest.key), action))
        for quest in seasonal_quests():
            action = f"claim_quest:{quest.key}" if quest_completed(self.settings, quest) and not quest_claimed(self.settings, quest) else "quest_info"
            items.append(MenuItem(self._quest_item_label(quest.key), action))
        items.append(MenuItem(self._daily_progress_reset_label(), "reset_daily_progress"))
        items.append(MenuItem("Back", "back"))
        self.quests_menu.items = items

    def _refresh_me_menu_labels(self) -> None:
        ensure_board_state(self.settings)
        ensure_collection_state(self.settings)
        self.me_menu.title = self._me_menu_title()
        completed = len(completed_collection_keys(self.settings))
        total = len(collection_definitions())
        self.me_menu.items = [
            MenuItem(self._character_menu_title(), "open_characters"),
            MenuItem(self._board_menu_title(), "open_boards"),
            MenuItem(self._item_upgrade_menu_title(), "open_item_upgrades"),
            MenuItem(f"Collections   {completed}/{total}", "open_collections"),
            MenuItem("Back", "back"),
        ]

    def _howto_topics(self) -> tuple[HelpTopic, ...]:
        if self._showing_upgrade_help:
            return UPGRADE_HELP_TOPICS.get(APP_VERSION, ()) + HOW_TO_TOPICS
        return HOW_TO_TOPICS

    def _refresh_howto_menu_labels(self) -> None:
        self.howto_menu.title = self._howto_menu_title()
        self.howto_menu.items = [MenuItem(topic.label, f"howto:{topic.key}") for topic in self._howto_topics()] + [
            MenuItem("Back", "back")
        ]

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
            self._play_menu_feedback("menuedge")
            return
        self._selected_help_topic = topic
        self.help_topic_menu.title = topic.label
        self.help_topic_menu.items = [
            MenuItem(segment, "copy_info_line") for segment in help_topic_segments(topic, self._gameplay_controls_summary())
        ] + [MenuItem("Copy All", "copy_info_all"), MenuItem("Back", "back")]
        self._set_active_menu(self.help_topic_menu)

    def _open_info_dialog(self, content: InfoDialogContent, menu: Menu) -> None:
        self._selected_info_dialog = content
        menu.title = content.title
        menu.items = [MenuItem(line, "copy_info_line") for line in content.lines] + [MenuItem("Copy All", "copy_info_all"), MenuItem("Back", "back")]
        self._set_active_menu(menu)

    def _copy_menu_text(self, text: str, success_message: str) -> bool:
        if not text:
            self._play_menu_feedback("menuedge")
            self.speaker.speak("Nothing available to copy.", interrupt=True)
            return True
        if copy_text_to_clipboard(text):
            self._play_menu_feedback("confirm")
            self.speaker.speak(success_message, interrupt=True)
            return True
        self._play_menu_feedback("menuedge")
        self.speaker.speak("Unable to copy text to the clipboard.", interrupt=True)
        return True

    def _selected_info_menu_lines(self, menu: Menu) -> tuple[str, ...]:
        if menu == self.help_topic_menu and self._selected_help_topic is not None:
            return help_topic_segments(self._selected_help_topic, self._gameplay_controls_summary())
        if menu == self.whats_new_menu and self._selected_info_dialog is not None:
            return self._selected_info_dialog.lines
        return ()

    def _selected_info_copy_all_text(self, menu: Menu) -> str:
        lines = self._selected_info_menu_lines(menu)
        if not lines:
            return ""
        return "\n".join((menu.title, "", *lines))

    @staticmethod
    def _selected_info_copy_all_message(menu: Menu) -> str:
        return f"{menu.title} copied to clipboard."

    def _mark_current_version_seen(self) -> None:
        seen_version = str(self.settings.get("last_seen_version", "") or "").strip()
        if not seen_version:
            self.settings["last_seen_version"] = APP_VERSION
            return
        if version_key(APP_VERSION) <= version_key(seen_version):
            self.settings["last_seen_version"] = APP_VERSION
            return
        self.settings["last_seen_version"] = APP_VERSION

    def _achievement_item_label(self, key: str) -> str:
        progress = achievement_progress(self.settings)
        unlocked = set(self.settings.get("achievements_unlocked", []))
        for achievement in achievement_definitions():
            if achievement.key != key:
                continue
            current = min(int(progress.get(achievement.metric, 0)), achievement.target)
            status = "Unlocked" if key in unlocked else f"{current}/{achievement.target}"
            return f"{achievement.label}   {status}"
        return key

    def _refresh_achievements_menu_labels(self) -> None:
        self.achievements_menu.title = self._achievements_menu_title()
        self.achievements_menu.items = [
            MenuItem(self._achievement_item_label(achievement.key), f"achievement:{achievement.key}")
            for achievement in achievement_definitions()
        ] + [MenuItem("Back", "back")]

    def _announce_achievement_unlocks(self) -> None:
        unlocks = newly_unlocked_achievements(self.settings)
        if not unlocks:
            return
        self.audio.play("unlock", channel="ui")
        for achievement in unlocks:
            self.speaker.speak(f"Achievement unlocked: {achievement.label}.", interrupt=False)
        self._refresh_achievements_menu_labels()

    def _record_achievement_metric(self, metric: str, amount: int = 1) -> None:
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
        self.settings["collections_completed"] = list(current_completed)
        self.audio.play("unlock", channel="ui")
        self.audio.play("mission_reward", channel="ui2")
        for key in new_keys:
            definition = next(item for item in collection_definitions() if item.key == key)
            self.speaker.speak(
                f"Collection complete: {definition.name}. {collection_bonus_summary(definition)}.",
                interrupt=False,
            )
        self._sync_character_progress()
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()

    def _build_controls_menu(self) -> None:
        self._sync_selected_binding_device()
        items = [
            MenuItem(f"Active Input: {self.controls.current_input_label()}", "announce_active_input"),
            MenuItem(f"Binding Profile: {self._selected_binding_profile_label()}", "select_binding_profile"),
            MenuItem("Customize Bindings", "open_selected_bindings"),
            MenuItem(f"Reset {self._selected_binding_profile_label()}", "reset_selected_bindings"),
        ]
        items.append(MenuItem("Back", "back"))
        self.controls_menu.items = items
        self.controls_menu.title = "Controls"

    def _sync_selected_binding_device(self) -> None:
        if self.controls.active_controller() is None:
            self._selected_binding_device = "keyboard"
            return
        if self._selected_binding_device not in {"keyboard", "controller"}:
            self._selected_binding_device = "controller"
            return
        if self.controls.last_input_source == "controller":
            self._selected_binding_device = "controller"

    def _selected_binding_profile_label(self) -> str:
        if self._selected_binding_device == "controller" and self.controls.active_controller() is not None:
            return family_label(self.controls.current_controller_family())
        return "Keyboard"

    def _cycle_selected_binding_device(self, direction: int) -> None:
        if direction not in (-1, 1):
            return
        available_devices = ["keyboard"]
        if self.controls.active_controller() is not None:
            available_devices.append("controller")
        if len(available_devices) == 1:
            self._play_menu_feedback("menuedge")
            return
        try:
            current_index = available_devices.index(self._selected_binding_device)
        except ValueError:
            current_index = 0
        self._selected_binding_device = available_devices[(current_index + direction) % len(available_devices)]
        self._play_menu_feedback("confirm")
        self._build_controls_menu()
        self.speaker.speak(self.controls_menu.items[1].label, interrupt=True)

    def _build_keyboard_bindings_menu(self) -> None:
        items = []
        for action_key in KEYBOARD_ACTION_ORDER:
            label = action_label(action_key)
            binding = keyboard_key_label(self.controls.keyboard_binding_for_action(action_key))
            items.append(MenuItem(f"{label}: {binding}", f"bind_keyboard:{action_key}"))
        items.append(MenuItem("Reset to Defaults", "reset_keyboard_bindings"))
        items.append(MenuItem("Back", "back"))
        self.keyboard_bindings_menu.items = items
        self.keyboard_bindings_menu.title = "Keyboard Bindings"

    def _build_controller_bindings_menu(self) -> None:
        family = self.controls.current_controller_family()
        items = []
        for action_key in CONTROLLER_ACTION_ORDER:
            label = action_label(action_key)
            binding = controller_binding_label(self.controls.controller_binding_for_action(action_key, family), family)
            items.append(MenuItem(f"{label}: {binding}", f"bind_controller:{action_key}"))
        items.append(MenuItem("Reset to Recommended", "reset_controller_bindings"))
        items.append(MenuItem("Back", "back"))
        self.controller_bindings_menu.items = items
        self.controller_bindings_menu.title = f"{family_label(family)} Bindings"

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
            self._learn_sound_description = "Return to the main menu."
            return
        self._learn_sound_description = entry.description

    def _stop_learn_sound_preview(self) -> None:
        self._learn_sound_preview_timer = 0.0
        self.audio.stop(LEARN_SOUND_PREVIEW_CHANNEL)

    def _start_headstart_audio(self) -> None:
        if self.player.headstart <= 0:
            return
        self.audio.play("intro_shake", loop=True, channel=HEADSTART_SHAKE_CHANNEL, gain=0.84)
        self.audio.play("intro_spray", loop=True, channel=HEADSTART_SPRAY_CHANNEL, gain=0.92)

    def _stop_headstart_audio(self) -> None:
        self.audio.stop(HEADSTART_SHAKE_CHANNEL)
        self.audio.stop(HEADSTART_SPRAY_CHANNEL)

    def _play_learn_sound_preview(self, entry: LearnSoundEntry) -> None:
        self._stop_learn_sound_preview()
        self._learn_sound_description = entry.description
        self.audio.play(
            entry.key,
            loop=entry.loop,
            channel=LEARN_SOUND_PREVIEW_CHANNEL,
            gain=entry.gain,
        )
        if entry.loop:
            self._learn_sound_preview_timer = LEARN_SOUND_LOOP_PREVIEW_DURATION
        self.speaker.speak(f"{entry.label}. {entry.description}", interrupt=True)

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
        self.audio.play(key, channel="ui")

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
        return bool(self.settings.get("meter_announcements_enabled", False))

    def _coin_counters_enabled(self) -> bool:
        return bool(self.settings.get("coin_counters_enabled", False))

    def _quest_changes_enabled(self) -> bool:
        return bool(self.settings.get("quest_changes_enabled", False))

    def _pause_on_focus_loss_enabled(self) -> bool:
        return bool(self.settings.get("pause_on_focus_loss_enabled", True))

    def _main_menu_descriptions_enabled(self) -> bool:
        return bool(self.settings.get("main_menu_descriptions_enabled", True))

    def _exit_confirmation_enabled(self) -> bool:
        return bool(self.settings.get("confirm_exit_enabled", True))

    def _main_menu_items(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Start Game",
                "start",
                "Set your loadout, then launch a new run when you are ready to hit the tracks.",
            ),
            MenuItem(
                "Events",
                "events",
                "Open the live event hub for Daily High Score, Coin Meter, the login calendar, and daily rewards.",
            ),
            MenuItem(
                "Missions",
                "missions_hub",
                "Review mission sets, quests, and achievement progress from a single progression hub.",
            ),
            MenuItem(
                "Me",
                "me",
                "Manage your active runner, hoverboard, upgrades, and collection bonuses.",
            ),
            MenuItem(
                "Shop",
                "shop",
                "Spend banked coins on hoverboards, boosters, boxes, and your free daily gift.",
            ),
            MenuItem(
                "Leaderboard",
                "leaderboard",
                "Connect to the online leaderboard, browse top players, and inspect published run history.",
            ),
            MenuItem(
                "What's New",
                "whats_new",
                "Hear the latest update notes, balance changes, and new features in this build.",
            ),
            MenuItem(
                "Options",
                "options",
                "Adjust audio, speech, controls, and accessibility settings before your next run.",
            ),
            MenuItem(
                "How to Play",
                "howto",
                "Browse movement, hazard, reward, and progression guidance one topic at a time.",
            ),
            MenuItem(
                "Learn Game Sounds",
                "learn_sounds",
                "Preview essential gameplay sounds so you can recognize danger, rewards, and powerups instantly.",
            ),
            MenuItem(
                "Check for Updates",
                "check_updates",
                "Search for a newer release and install it when an update is available.",
            ),
            MenuItem(
                "Exit",
                "quit",
                "Close the game and return to desktop.",
            ),
        ]

    def _selected_main_menu_description(self) -> str:
        if self.active_menu != self.main_menu or not self._main_menu_descriptions_enabled() or not self.main_menu.items:
            return ""
        return self.main_menu.items[self.main_menu.index].description.strip()

    def _refresh_update_menu(self, result: UpdateCheckResult) -> None:
        latest_version = result.latest_version or "Unknown"
        if self.packaged_build:
            self.update_menu.title = f"Update Required   {APP_VERSION} -> {latest_version}"
            self._update_status_message = (
                f"A newer version is available. Current version {APP_VERSION}. Latest version {latest_version}."
            )
        else:
            self.update_menu.title = f"Update Available   {APP_VERSION} -> {latest_version}"
            self._update_status_message = (
                f"A newer release is available. This source checkout reports version {APP_VERSION}. "
                f"Latest release {latest_version}."
            )
        self._update_release_notes = (
            result.release.notes.strip() if result.release is not None and result.release.notes.strip() else "No release notes were provided."
        )
        self._update_progress_percent = 0.0
        self._update_progress_message = ""
        self._update_progress_stage = "idle"
        self._update_progress_announced_bucket = -1
        self._update_install_thread = None
        self._update_install_result = None
        self._update_restart_script_path = None
        self._update_install_error = ""
        self._update_ready_announced = False
        has_zip_package = self.packaged_build and bool(result.release and self.updater.has_installable_package(result.release))
        self.update_menu.items[0].label = "Download and Install Update" if has_zip_package else "Open Release Page"
        self.update_menu.items[0].action = "download_update" if has_zip_package else "open_release_page"
        self.update_menu.items[1].label = "Open Release Page"
        self.update_menu.items[1].action = "open_release_page"
        self.update_menu.items[2].label = "Back" if not self.packaged_build else "Quit Game"
        self.update_menu.items[2].action = "back" if not self.packaged_build else "quit"

    def _menu_navigation_hint(self) -> str:
        up = keyboard_key_label(self.controls.keyboard_binding_for_action("menu_up"))
        down = keyboard_key_label(self.controls.keyboard_binding_for_action("menu_down"))
        confirm = keyboard_key_label(self.controls.keyboard_binding_for_action("menu_confirm"))
        back = keyboard_key_label(self.controls.keyboard_binding_for_action("menu_back"))
        if self.controls.last_input_source == "controller" and self.controls.active_controller() is not None:
            family = self.controls.current_controller_family()
            up = controller_binding_label(self.controls.controller_binding_for_action("menu_up", family), family)
            down = controller_binding_label(self.controls.controller_binding_for_action("menu_down", family), family)
            confirm = controller_binding_label(self.controls.controller_binding_for_action("menu_confirm", family), family)
            back = controller_binding_label(self.controls.controller_binding_for_action("menu_back", family), family)
        return f"Use {up}/{down}, {confirm} to select, {back} to go back."

    def _option_adjustment_hint(self) -> str:
        decrease = keyboard_key_label(self.controls.keyboard_binding_for_action("option_decrease"))
        increase = keyboard_key_label(self.controls.keyboard_binding_for_action("option_increase"))
        if self.controls.last_input_source == "controller" and self.controls.active_controller() is not None:
            family = self.controls.current_controller_family()
            decrease = controller_binding_label(self.controls.controller_binding_for_action("option_decrease", family), family)
            increase = controller_binding_label(self.controls.controller_binding_for_action("option_increase", family), family)
        return f"Adjust values with {decrease}/{increase}."

    def _gameplay_controls_summary(self) -> str:
        move_left = keyboard_key_label(self.controls.keyboard_binding_for_action("game_move_left"))
        move_right = keyboard_key_label(self.controls.keyboard_binding_for_action("game_move_right"))
        jump = keyboard_key_label(self.controls.keyboard_binding_for_action("game_jump"))
        roll = keyboard_key_label(self.controls.keyboard_binding_for_action("game_roll"))
        hoverboard = keyboard_key_label(self.controls.keyboard_binding_for_action("game_hoverboard"))
        pause = keyboard_key_label(self.controls.keyboard_binding_for_action("game_pause"))
        speech = keyboard_key_label(self.controls.keyboard_binding_for_action("game_toggle_speech"))
        if self.controls.last_input_source == "controller" and self.controls.active_controller() is not None:
            family = self.controls.current_controller_family()
            move_left = controller_binding_label(self.controls.controller_binding_for_action("game_move_left", family), family)
            move_right = controller_binding_label(self.controls.controller_binding_for_action("game_move_right", family), family)
            jump = controller_binding_label(self.controls.controller_binding_for_action("game_jump", family), family)
            roll = controller_binding_label(self.controls.controller_binding_for_action("game_roll", family), family)
            hoverboard = controller_binding_label(self.controls.controller_binding_for_action("game_hoverboard", family), family)
            pause = controller_binding_label(self.controls.controller_binding_for_action("game_pause", family), family)
            speech = controller_binding_label(self.controls.controller_binding_for_action("game_toggle_speech", family), family)
        return (
            f"Use {move_left} and {move_right} to change lanes. "
            f"Press {jump} to jump, {roll} to roll, {hoverboard} to activate a hoverboard, "
            f"{pause} to pause, and {speech} to toggle speech. "
            f"On keyboard, press R to hear coins and T to hear play time."
        )

    def _open_mandatory_update_menu(self, result: UpdateCheckResult) -> None:
        self._latest_update_result = result
        self._refresh_update_menu(result)
        self._set_active_menu(self.update_menu)
        self.speaker.speak(self._update_status_message, interrupt=True)

    def _show_startup_status(self, message: str) -> None:
        try:
            width, height = self.screen.get_size()
            self.screen.fill((10, 10, 15))
            title_surface = self.big.render("Subway Surfers Blind Edition", True, (240, 240, 240))
            message_surface = self.font.render(str(message or "").strip() or "Checking for updates.", True, (205, 205, 205))
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
                self.speaker.speak("Source builds cannot install updates automatically. Opening the release page.", interrupt=True)
            else:
                self._play_menu_feedback("menuedge")
                self.speaker.speak("Source builds cannot install updates automatically.", interrupt=True)
            return
        release = self._latest_update_result.release if self._latest_update_result is not None else None
        if release is None:
            self._play_menu_feedback("menuedge")
            self.speaker.speak("No release information is available.", interrupt=True)
            return
        if self._update_install_thread is not None and self._update_install_thread.is_alive():
            return

        self._update_progress_stage = "download"
        self._update_progress_percent = 0.0
        self._update_progress_message = "Starting update download."
        self._update_progress_announced_bucket = -1
        self._update_install_result = None
        self._update_restart_script_path = None
        self._update_install_error = ""
        self._update_ready_announced = False
        self.update_menu.items[0].label = "Installing Update..."
        self.update_menu.items[0].action = "install_busy"

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

        self._update_install_thread = threading.Thread(target=worker, name="update-install", daemon=True)
        self._update_install_thread.start()

    def _update_update_install_state(self) -> None:
        if self.active_menu != self.update_menu:
            return
        if self._update_progress_stage == "download":
            bucket = int(self._update_progress_percent // 10)
            if bucket > self._update_progress_announced_bucket and bucket < 10:
                self._update_progress_announced_bucket = bucket
                if bucket > 0:
                    self.speaker.speak(f"Download {bucket * 10} percent.", interrupt=False)
        if self._update_install_thread is None or self._update_install_thread.is_alive():
            return
        self._update_install_thread = None
        result = self._update_install_result
        if result is None:
            return
        self._update_status_message = result.message
        if not result.success:
            self.update_menu.items[0].label = "Download and Install Update"
            self.update_menu.items[0].action = "download_update"
            self._update_progress_stage = "error"
            self._play_menu_feedback("menuedge")
            self.speaker.speak(result.message, interrupt=True)
            self._update_install_result = None
            return
        self.update_menu.items[0].label = "Restart Game"
        self.update_menu.items[0].action = "restart_after_update"
        self.update_menu.items[1].label = "Open Release Page"
        self.update_menu.items[1].action = "open_release_page"
        self.update_menu.items[2].label = "Quit Game"
        self.update_menu.items[2].action = "quit"
        self._update_progress_stage = "ready"
        if not self._update_ready_announced:
            self._update_ready_announced = True
            self.speaker.speak(result.message, interrupt=True)

    def _check_for_updates(self, announce_result: bool, automatic: bool = False) -> None:
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
                self.speaker.speak(
                    f"{self._update_status_message} Open the release page to download the new build.",
                    interrupt=True,
                )
            return
        if result.release is not None:
            self._update_status_message = (
                f"Current version {APP_VERSION}. Latest release {result.release.version}. {result.message}"
            )
        else:
            self._update_status_message = result.message
        if announce_result:
            self.speaker.speak(self._update_status_message, interrupt=True)
            return
        if automatic and result.status == "error":
            return

    def _menu_uses_gameplay_music(self, menu: Menu | None) -> bool:
        return menu in {self.pause_menu, self.pause_confirm_menu, self.revive_menu}

    def _sync_music_context(self) -> None:
        if self._exit_requested:
            return
        if self.active_menu is None:
            if self.state.running:
                self.audio.music_start("gameplay")
            else:
                self.audio.music_stop()
            return
        if self.state.running and self._menu_uses_gameplay_music(self.active_menu):
            self.audio.music_start("gameplay")
            return
        self.audio.music_start("menu")

    def _difficulty_key(self) -> str:
        return str(self.settings.get("difficulty", "normal")).strip().lower()

    def _request_exit(self) -> None:
        if self._exit_requested:
            return
        self._exit_requested = True
        self._persist_settings()
        self.leaderboard_client.close()
        self.audio.music_stop()

    @staticmethod
    def _death_reason_for_variant(variant: str) -> str:
        return {
            "train": "Hit train",
            "low": "Hit low obstacle",
            "high": "Hit high obstacle",
            "bush": "Hit bush",
        }.get(variant, "Run ended after crash")

    def _open_game_over_dialog(self, death_reason: Optional[str] = None) -> None:
        summary_reason = death_reason or self._last_death_reason or "Run ended after crash"
        self._game_over_publish_state = "idle"
        self._update_game_over_summary(summary_reason)
        self._refresh_game_over_menu()
        if self._leaderboard_is_authenticated():
            self._open_publish_confirmation(return_menu=self.game_over_menu, start_index=0)
        else:
            self.active_menu = self.game_over_menu
            self.game_over_menu.opened = True
            self.game_over_menu.index = 0
            self._pending_menu_announcement = (self.game_over_menu, 0.45, False)
        self._sync_music_context()
        self.speaker.speak("Game Over.", interrupt=True)

    def _update_game_over_summary(self, reason: str) -> None:
        compact_powerup_usage = self._compact_powerup_usage(self._active_run_stats.get("powerup_usage"))
        self._game_over_summary = {
            "score": int(self.state.score),
            "coins": int(self.state.coins),
            "play_time_seconds": int(self.state.time),
            "death_reason": str(reason or "Run ended."),
            "game_version": APP_VERSION,
            "difficulty": self._difficulty_key(),
            "distance_meters": int(self.state.distance),
            "clean_escapes": int(self._active_run_stats.get("clean_escapes", 0) or 0),
            "revives_used": int(self.state.revives_used),
            "powerup_usage": compact_powerup_usage,
        }

    def _should_offer_publish_prompt(self) -> bool:
        if not self._leaderboard_is_authenticated():
            return False
        summary = self._game_over_summary
        return int(summary.get("score", 0) or 0) > 0 or int(summary.get("coins", 0) or 0) > 0

    def _open_publish_confirmation(self, return_menu: Menu, start_index: int = 0) -> None:
        self._publish_confirm_return_menu = return_menu
        self._publish_confirm_return_index = max(0, int(start_index))
        self.active_menu = self.publish_confirm_menu
        self.publish_confirm_menu.opened = True
        self.publish_confirm_menu.index = 0
        self._pending_menu_announcement = (self.publish_confirm_menu, 0.0, True)

    def _mission_goals(self):
        return mission_goals_for_set(int(self.settings.get("mission_set", 1)))

    def _mission_status_text(self) -> str:
        completed = len(completed_mission_metrics(self.settings))
        return f"Missions {completed}/3"

    def _current_word(self) -> str:
        return active_word_for_settings(self.settings)

    def _remaining_word_letters(self) -> str:
        return remaining_word_letters(self.settings)

    def _next_word_letter(self) -> str:
        remaining_letters = self._remaining_word_letters()
        return remaining_letters[:1]

    def _choose_support_spawn_kind(self) -> str:
        profile = self._active_event_profile
        kinds = ["power", "box", "key"]
        weights = [0.58, 0.18 + float(profile.get("box_bonus", 0.0) or 0.0), 0.08]
        active_word = any(obstacle.kind == "word" and obstacle.z > 0 for obstacle in self.obstacles)
        active_token = any(obstacle.kind == "season_token" and obstacle.z > 0 for obstacle in self.obstacles)
        active_multiplier = self.player.mult2x > 0 or any(
            obstacle.kind == "multiplier" and obstacle.z > 0 for obstacle in self.obstacles
        )
        active_super_box = any(obstacle.kind == "super_box" and obstacle.z > 0 for obstacle in self.obstacles)
        active_pogo = self.player.pogo_active > 0 or any(obstacle.kind == "pogo" and obstacle.z > 0 for obstacle in self.obstacles)
        if not active_multiplier:
            kinds.append("multiplier")
            weights.append(0.09)
        if not active_super_box:
            kinds.append("super_box")
            weights.append(0.06 + float(profile.get("super_box_bonus", 0.0) or 0.0))
        if not active_pogo:
            kinds.append("pogo")
            weights.append(0.09)
        if self._remaining_word_letters() and not active_word:
            kinds.append("word")
            weights.append(0.08 + float(profile.get("word_bonus", 0.0) or 0.0))
        if next_season_reward_threshold(self.settings) is not None and not active_token:
            kinds.append("season_token")
            weights.append(0.05)
        return random.choices(kinds, weights=weights, k=1)[0]

    def _complete_mission_set(self) -> None:
        self.settings["mission_set"] = int(self.settings.get("mission_set", 1)) + 1
        self.settings["mission_metrics"] = {
            "coins": 0,
            "jumps": 0,
            "rolls": 0,
            "dodges": 0,
            "powerups": 0,
            "boxes": 0,
        }
        if int(self.settings.get("mission_multiplier_bonus", 0)) < 29:
            self.settings["mission_multiplier_bonus"] = int(self.settings.get("mission_multiplier_bonus", 0)) + 1
            if self.state.running:
                self.state.multiplier += 1
            self.audio.play("mission_reward", channel="ui")
            self.audio.play("unlock", channel="ui2")
            self.speaker.speak(
                f"Mission set complete. Permanent multiplier is now x{1 + int(self.settings['mission_multiplier_bonus'])}.",
                interrupt=True,
            )
            return
        self.audio.play("mission_reward", channel="ui")
        self.speaker.speak("Mission set complete. Super Mystery Box.", interrupt=True)
        self._open_super_mystery_box("Mission Set")

    def _record_mission_event(self, metric: str, amount: int = 1) -> None:
        ensure_progression_state(self.settings)
        if self.state.running and amount > 0:
            self._record_run_metric(metric, amount)
        achievement_metric = {
            "jumps": "total_jumps",
            "rolls": "total_rolls",
            "dodges": "total_dodges",
        }.get(metric)
        if achievement_metric is not None:
            self._record_achievement_metric(achievement_metric, amount)
        metrics = self.settings.get("mission_metrics", {})
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
                    self.audio.play("mission_reward", channel="ui")
                    self.speaker.speak(f"Mission complete: {goal.label}.", interrupt=False)
        if len(completed_after) == len(goals) and len(completed_before) != len(goals):
            self._complete_mission_set()

    def _reset_daily_progress(self) -> None:
        today = date.today()
        reset_daily_quest_progress(self.settings, today)
        word_hunt_reset = reset_daily_word_hunt_progress(self.settings, today)
        word_hunt_completed_today = str(self.settings.get("word_hunt_completed_on", "") or "") == today.isoformat()
        reset_daily_event_progress(self.settings, today)
        self.audio.play("gui_tap", channel="ui")
        self._refresh_quest_menu_labels()
        self._refresh_events_menu_labels()
        self._persist_settings()
        if word_hunt_completed_today and not word_hunt_reset:
            self.speaker.speak(
                "Today's progress was reset. Word Hunt stayed complete because today's reward was already claimed.",
                interrupt=True,
            )
            return
        self.speaker.speak(
            "Today's progress was reset. Claimed rewards stayed claimed.",
            interrupt=True,
        )

    def _open_super_mystery_box(self, source: str) -> None:
        self._record_achievement_metric("total_boxes_opened", 1)
        reward = pick_super_mystery_box_reward()
        self.audio.play("mystery_box_open", channel="ui")
        self.audio.play("mystery_combo", channel="ui2")
        if reward == "coins":
            gain = random.randint(450, 1100)
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + gain
            self.audio.play("gui_cash", channel="ui3")
            self.speaker.speak(f"{source}: Super Mystery Box. {gain} coins saved.", interrupt=True)
            return
        if reward == "hoverboards":
            gain = random.randint(1, 2)
            self.settings["hoverboards"] = int(self.settings.get("hoverboards", 0)) + gain
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}: Super Mystery Box. {gain} hoverboard{'s' if gain != 1 else ''}.", interrupt=True)
            return
        if reward == "jetpack":
            self.audio.play("unlock", channel="ui3")
            self._apply_power_reward("jetpack", from_headstart=False)
            self.speaker.speak(f"{source}: Super Mystery Box. Jetpack.", interrupt=True)
            return
        if reward == "keys":
            gain = random.randint(1, 2)
            self.settings["keys"] = int(self.settings.get("keys", 0)) + gain
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}: Super Mystery Box. {gain} key{'s' if gain != 1 else ''}.", interrupt=True)
            return
        if reward == "headstarts":
            self.settings["headstarts"] = int(self.settings.get("headstarts", 0)) + 1
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}: Super Mystery Box. Headstart.", interrupt=True)
            return
        if reward == "score_boosters":
            self.settings["score_boosters"] = int(self.settings.get("score_boosters", 0)) + 1
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}: Super Mystery Box. Score Booster.", interrupt=True)
            return
        if reward == "jackpot":
            gain = random.randint(1500, 2600)
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + gain
            self.audio.play("gui_cash", channel="ui3")
            self.audio.play("unlock", channel="ui4")
            self.speaker.speak(f"{source}: Super Mystery Box jackpot. {gain} coins saved.", interrupt=True)
            return
        if int(self.settings.get("mission_multiplier_bonus", 0)) < 29:
            self.settings["mission_multiplier_bonus"] = int(self.settings.get("mission_multiplier_bonus", 0)) + 1
            if self.state.running:
                self.state.multiplier += 1
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(
                f"{source}: Super Mystery Box. Permanent multiplier x{1 + int(self.settings['mission_multiplier_bonus'])}.",
                interrupt=True,
            )
            return
        gain = random.randint(900, 1500)
        self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + gain
        self.audio.play("gui_cash", channel="ui3")
        self.speaker.speak(f"{source}: Super Mystery Box. {gain} coins saved.", interrupt=True)

    def _complete_word_hunt(self) -> None:
        streak = update_word_hunt_streak(self.settings)
        self._record_achievement_max("best_word_hunt_streak", streak)
        reward_kind, amount = word_hunt_reward_for_streak(streak)
        self.audio.play("mission_reward", channel="ui")
        if reward_kind == "coins":
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + amount
            self.audio.play("gui_cash", channel="ui2")
            self.speaker.speak(
                f"Word Hunt complete. Streak {streak}. {amount} coins saved.",
                interrupt=True,
            )
            return
        self.speaker.speak(f"Word Hunt complete. Streak {streak}. Super Mystery Box.", interrupt=True)
        self._open_super_mystery_box("Word Hunt")

    def _claim_season_reward(self) -> None:
        reward = claim_season_reward(self.settings)
        if reward is None:
            return
        self.audio.play("mission_reward", channel="ui")
        self.audio.play("unlock", channel="ui2")
        if reward == "coins":
            gain = 500
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + gain
            self.audio.play("gui_cash", channel="ui3")
            self.speaker.speak(f"Season Hunt reward. {gain} coins saved.", interrupt=True)
            return
        if reward == "key":
            self.settings["keys"] = int(self.settings.get("keys", 0)) + 1
            self.speaker.speak("Season Hunt reward. Key.", interrupt=True)
            return
        if reward == "headstart":
            self.settings["headstarts"] = int(self.settings.get("headstarts", 0)) + 1
            self.speaker.speak("Season Hunt reward. Headstart.", interrupt=True)
            return
        self.speaker.speak("Season Hunt reward. Super Mystery Box.", interrupt=True)
        self._open_super_mystery_box("Season Hunt")

    def _spend_bank_coins(self, cost: int) -> bool:
        current = int(self.settings.get("bank_coins", 0))
        if current < cost:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak("Not enough coins.", interrupt=True)
            return False
        self.settings["bank_coins"] = current - cost
        self.audio.play("gui_cash", channel="ui")
        return True

    def _persist_settings(self) -> None:
        self._sync_leaderboard_settings_from_client()
        config_module.save_settings(self.settings)

    def _sync_leaderboard_settings_from_client(self) -> None:
        self._leaderboard_username = str(self.leaderboard_client.principal_username or self._leaderboard_username or "").strip()
        self.settings["leaderboard_username"] = self._leaderboard_username
        self.settings["leaderboard_session_token"] = str(self.leaderboard_client.auth_token or "").strip()

    def _restore_persisted_leaderboard_session(self) -> None:
        persisted_username = str(self.settings.get("leaderboard_username", "") or "").strip()
        persisted_token = str(self.settings.get("leaderboard_session_token", "") or "").strip()
        self._leaderboard_username = persisted_username
        self.leaderboard_client.principal_username = persisted_username
        self.leaderboard_client.auth_token = persisted_token

    def _claimed_leaderboard_reward_ids(self) -> list[str]:
        return [
            str(reward_id).strip()
            for reward_id in list(self.settings.get("leaderboard_applied_reward_ids") or [])
            if str(reward_id).strip()
        ]

    def _remember_leaderboard_reward_ids(self, reward_ids: list[str]) -> None:
        remembered = self._claimed_leaderboard_reward_ids()
        for reward_id in reward_ids:
            normalized = str(reward_id).strip()
            if not normalized or normalized in remembered:
                continue
            remembered.append(normalized)
        self.settings["leaderboard_applied_reward_ids"] = remembered[-256:]

    def _format_leaderboard_season_remaining(self) -> str:
        season = self._leaderboard_season or {}
        remaining = max(0, int(season.get("seconds_remaining", 0) or 0))
        days = remaining // 86400
        hours = (remaining % 86400) // 3600
        minutes = (remaining % 3600) // 60
        return f"{days} day{'s' if days != 1 else ''} {hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"

    def _leaderboard_season_status_label(self) -> str:
        if not self._leaderboard_season:
            return "Season Ends In: Loading..."
        return f"Season Ends In: {self._format_leaderboard_season_remaining()}"

    def _leaderboard_reward_status_label(self) -> str:
        season = self._leaderboard_season or {}
        reward_label = str(season.get("reward_label") or "Reward").strip()
        reward_preview = str(season.get("reward_preview") or "Loading current season reward...").strip()
        return f"Season Reward: {reward_label}. {reward_preview}"

    def _leaderboard_season_identity_label(self) -> str:
        season = self._leaderboard_season or {}
        season_name = str(season.get("season_name") or "").strip()
        season_key = str(season.get("season_key") or "").strip()
        if season_name and season_key:
            return f"Season: {season_name} ({season_key})"
        if season_name:
            return f"Season: {season_name}"
        if season_key:
            return f"Season: {season_key}"
        return "Season: Loading current week"

    def _apply_leaderboard_account_sync(self, payload: dict[str, object], *, announce_rewards: bool) -> int:
        applied_reward_ids: list[str] = []
        username = str(payload.get("username") or self._leaderboard_username or "").strip()
        if username and username != self._leaderboard_username:
            self._leaderboard_username = username
            self.settings["leaderboard_username"] = username
            self._refresh_options_menu_labels()
        season = payload.get("season")
        if isinstance(season, dict):
            self._leaderboard_season = dict(season)
        known_ids = set(self._claimed_leaderboard_reward_ids())
        for reward_entry in list(payload.get("pending_rewards") or []):
            if not isinstance(reward_entry, dict):
                continue
            reward_id = str(reward_entry.get("id") or "").strip()
            if not reward_id or reward_id in known_ids:
                continue
            reward_kind = str(reward_entry.get("reward_kind") or "").strip().lower()
            reward_amount = max(1, int(reward_entry.get("reward_amount", 1) or 1))
            source = f"Season reward for rank {int(reward_entry.get('rank', 0) or 0)}"
            if self._apply_meta_reward({"kind": reward_kind, "amount": reward_amount}, source):
                applied_reward_ids.append(reward_id)
                known_ids.add(reward_id)
        if applied_reward_ids:
            self._remember_leaderboard_reward_ids(applied_reward_ids)
            self._persist_settings()
            if announce_rewards and len(applied_reward_ids) > 1:
                self.speaker.speak(f"{len(applied_reward_ids)} seasonal rewards were delivered.", interrupt=True)
        elif username:
            self._persist_settings()
        return len(applied_reward_ids)

    def _start_background_leaderboard_sync(self) -> None:
        if self._leaderboard_startup_sync_started or not self._leaderboard_is_authenticated():
            return
        self._leaderboard_startup_sync_started = True

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            sync_payload = self.leaderboard_client.sync_account(self._claimed_leaderboard_reward_ids())
            sync_payload["just_connected"] = just_connected
            return sync_payload

        self._start_leaderboard_operation(
            "leaderboard_startup_sync",
            "Leaderboard",
            "Checking seasonal rewards...",
            worker,
            return_menu=self.active_menu,
            show_status=False,
            reject_message=False,
        )

    def _sync_character_progress(self) -> None:
        ensure_character_progress_state(self.settings)
        ensure_board_state(self.settings)
        ensure_collection_state(self.settings)
        ensure_quest_state(self.settings)
        ensure_event_state(self.settings)
        self._collection_bonuses = collection_runtime_bonuses(self.settings)
        character_bonuses = character_runtime_bonuses(self.settings)
        self._active_character_bonuses = CharacterRuntimeBonuses(
            banked_coin_bonus_ratio=character_bonuses.banked_coin_bonus_ratio + self._collection_bonuses.banked_coin_bonus_ratio,
            hoverboard_duration_bonus=character_bonuses.hoverboard_duration_bonus + self._collection_bonuses.hoverboard_duration_bonus,
            power_duration_multiplier=character_bonuses.power_duration_multiplier * self._collection_bonuses.power_duration_multiplier,
            starting_multiplier_bonus=character_bonuses.starting_multiplier_bonus + self._collection_bonuses.starting_multiplier_bonus,
        )
        self._active_event_profile = event_runtime_profile(self.settings)

    def _powerup_duration(self, key: str) -> float:
        return self._character_adjusted_power_duration(item_upgrade_duration(self.settings, key))

    def _unlock_character(self, key: str) -> None:
        definition = character_definition(key)
        if character_unlocked(self.settings, definition.key):
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is already unlocked.", interrupt=True)
            return
        if not self._spend_bank_coins(definition.unlock_cost):
            return
        previous_completed = completed_collection_keys(self.settings)
        self.settings["character_progress"][definition.key]["unlocked"] = True
        self._sync_character_progress()
        self._refresh_shop_menu_labels()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()
        self._persist_settings()
        self.audio.play("unlock", channel="ui3")
        self.speaker.speak(f"{definition.name} unlocked.", interrupt=True)
        self.speaker.speak(self._shop_coins_label(), interrupt=False)
        self._announce_collection_unlocks(previous_completed)

    def _select_character(self, key: str) -> None:
        definition = character_definition(key)
        if not character_unlocked(self.settings, definition.key):
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is still locked.", interrupt=True)
            return
        if selected_character_definition(self.settings).key == definition.key:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is already active.", interrupt=True)
            return
        self.settings["selected_character"] = definition.key
        self._sync_character_progress()
        self._refresh_shop_menu_labels()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._refresh_events_menu_labels()
        self._refresh_me_menu_labels()
        self._persist_settings()
        self.audio.play("confirm", channel="ui")
        self.speaker.speak(f"{definition.name} selected.", interrupt=True)

    def _upgrade_character(self, key: str) -> None:
        definition = character_definition(key)
        if not character_unlocked(self.settings, definition.key):
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak("Unlock the character before upgrading.", interrupt=True)
            return
        upgrade_cost = next_character_upgrade_cost(self.settings, definition.key)
        if upgrade_cost is None:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is already at max level.", interrupt=True)
            return
        if not self._spend_bank_coins(upgrade_cost):
            return
        self.settings["character_progress"][definition.key]["level"] = character_level(self.settings, definition.key) + 1
        self._sync_character_progress()
        self._refresh_shop_menu_labels()
        self._refresh_character_menu_labels()
        self._refresh_character_detail_menu_labels(definition.key)
        self._persist_settings()
        upgraded_level = character_level(self.settings, definition.key)
        self.audio.play("unlock", channel="ui3")
        self.speaker.speak(
            f"{definition.name} upgraded to level {upgraded_level}. {character_perk_summary(definition, upgraded_level)}.",
            interrupt=True,
        )
        self.speaker.speak(self._shop_coins_label(), interrupt=False)

    def _purchase_item_upgrade(self, key: str) -> None:
        definition = item_upgrade_definition(key)
        upgrade_cost = next_item_upgrade_cost(self.settings, definition.key)
        if upgrade_cost is None:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is already at max level.", interrupt=True)
            return
        if not self._spend_bank_coins(upgrade_cost):
            return
        self.settings["item_upgrades"][definition.key] = item_upgrade_level(self.settings, definition.key) + 1
        self._refresh_shop_menu_labels()
        self._refresh_item_upgrade_menu_labels()
        self._refresh_item_upgrade_detail_menu_labels(definition.key)
        self._refresh_me_menu_labels()
        self._persist_settings()
        upgraded_level = item_upgrade_level(self.settings, definition.key)
        upgraded_duration = item_upgrade_duration(self.settings, definition.key)
        self.audio.play("unlock", channel="ui3")
        self.speaker.speak(
            f"{definition.name} upgraded to level {upgraded_level}. Pickup duration {self._format_duration_seconds(upgraded_duration)}.",
            interrupt=True,
        )
        self.speaker.speak(self._shop_coins_label(), interrupt=False)

    def _unlock_board(self, key: str) -> None:
        definition = board_definition(key)
        if board_unlocked(self.settings, definition.key):
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is already unlocked.", interrupt=True)
            return
        if not self._spend_bank_coins(definition.unlock_cost):
            return
        previous_completed = completed_collection_keys(self.settings)
        self.settings["board_progress"][definition.key]["unlocked"] = True
        self._sync_character_progress()
        self._refresh_board_menu_labels()
        self._refresh_board_detail_menu_labels(definition.key)
        self._refresh_collection_menu_labels()
        self._refresh_me_menu_labels()
        self._persist_settings()
        self.audio.play("unlock", channel="ui3")
        self.speaker.speak(f"{definition.name} unlocked.", interrupt=True)
        self.speaker.speak(self._shop_coins_label(), interrupt=False)
        self._announce_collection_unlocks(previous_completed)

    def _select_board(self, key: str) -> None:
        definition = board_definition(key)
        if not board_unlocked(self.settings, definition.key):
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is still locked.", interrupt=True)
            return
        if selected_board_definition(self.settings).key == definition.key:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{definition.name} is already active.", interrupt=True)
            return
        self.settings["selected_board"] = definition.key
        self._sync_character_progress()
        self._refresh_board_menu_labels()
        self._refresh_board_detail_menu_labels(definition.key)
        self._refresh_me_menu_labels()
        self._refresh_loadout_menu_labels()
        self._persist_settings()
        self.audio.play("confirm", channel="ui")
        self.speaker.speak(f"{definition.name} selected.", interrupt=True)

    def _apply_meta_reward(self, reward: dict[str, object] | None, source: str) -> bool:
        if reward is None:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(f"{source} is not ready yet.", interrupt=True)
            return False
        kind = str(reward.get("kind") or "").strip().lower()
        amount = max(1, int(reward.get("amount", 1) or 1))
        if kind == "coins":
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + amount
            self.audio.play("gui_cash", channel="ui3")
            self.speaker.speak(f"{source}. {amount} coins saved.", interrupt=True)
            return True
        if kind == "key":
            self.settings["keys"] = int(self.settings.get("keys", 0)) + amount
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}. {amount} key{'s' if amount != 1 else ''}.", interrupt=True)
            return True
        if kind == "headstart":
            self.settings["headstarts"] = int(self.settings.get("headstarts", 0)) + amount
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}. {amount} headstart{'s' if amount != 1 else ''}.", interrupt=True)
            return True
        if kind == "score_booster":
            self.settings["score_boosters"] = int(self.settings.get("score_boosters", 0)) + amount
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}. {amount} score booster{'s' if amount != 1 else ''}.", interrupt=True)
            return True
        if kind == "hoverboard":
            self.settings["hoverboards"] = int(self.settings.get("hoverboards", 0)) + amount
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"{source}. {amount} hoverboard{'s' if amount != 1 else ''}.", interrupt=True)
            return True
        if kind == "event_coins":
            self.settings["event_state"]["event_coins"] = int(self.settings["event_state"].get("event_coins", 0)) + amount
            self.audio.play("mission_reward", channel="ui3")
            self.speaker.speak(f"{source}. {amount} event coins.", interrupt=True)
            return True
        if kind == "super_box":
            self.speaker.speak(f"{source}. Super Mystery Box.", interrupt=True)
            self._open_super_mystery_box(source)
            return True
        self.audio.play("menuedge", channel="ui")
        self.speaker.speak(f"{source} reward is unavailable.", interrupt=True)
        return False

    def _purchase_shop_item(self, item: str) -> None:
        if item == "hoverboard":
            if not self._spend_bank_coins(SHOP_PRICES["hoverboard"]):
                return
            self.settings["hoverboards"] = int(self.settings.get("hoverboards", 0)) + 1
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak("Hoverboard purchased.", interrupt=True)
        elif item == "mystery_box":
            if not self._spend_bank_coins(SHOP_PRICES["mystery_box"]):
                return
            if self._active_event_profile.get("jackpot_bonus"):
                reward = random.choices(
                    ["coins", "hover", "key", "headstart", "score_booster", "jackpot", "nothing"],
                    weights=[45, 12, 12, 10, 8, 12, 1],
                    k=1,
                )[0]
            else:
                reward = pick_shop_mystery_box_reward()
            self._grant_shop_box_reward(reward)
        elif item == "headstart":
            if not self._spend_bank_coins(SHOP_PRICES["headstart"]):
                return
            self.settings["headstarts"] = int(self.settings.get("headstarts", 0)) + 1
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak("Headstart purchased.", interrupt=True)
        elif item == "score_booster":
            if not self._spend_bank_coins(SHOP_PRICES["score_booster"]):
                return
            self.settings["score_boosters"] = int(self.settings.get("score_boosters", 0)) + 1
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak("Score booster purchased.", interrupt=True)
        self._refresh_shop_menu_labels()
        self._persist_settings()
        self.speaker.speak(self._shop_coins_label(), interrupt=False)

    def _grant_shop_box_reward(self, reward: str) -> None:
        self.speaker.speak("Opening Mystery Box.", interrupt=True)
        self.audio.play("mystery_box_open", channel="player_box")
        if reward == "coins":
            gain = shop_box_reward_amount("coins")
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + gain
            self.audio.play("gui_cash", channel="ui3")
            self.speaker.speak(f"Mystery box: {gain} coins.", interrupt=False)
            return
        if reward == "hover":
            gain = shop_box_reward_amount("hover")
            self.settings["hoverboards"] = int(self.settings.get("hoverboards", 0)) + gain
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"Mystery box: {gain} hoverboard{'s' if gain != 1 else ''}.", interrupt=False)
            return
        if reward == "key":
            gain = shop_box_reward_amount("key")
            self.settings["keys"] = int(self.settings.get("keys", 0)) + gain
            self.audio.play("unlock", channel="ui3")
            self.speaker.speak(f"Mystery box: {gain} key{'s' if gain != 1 else ''}.", interrupt=False)
            return
        if reward == "headstart":
            gain = shop_box_reward_amount("headstart")
            self.settings["headstarts"] = int(self.settings.get("headstarts", 0)) + gain
            self.audio.play("mystery_combo", channel="ui3")
            self.speaker.speak(f"Mystery box: {gain} headstart{'s' if gain != 1 else ''}.", interrupt=False)
            return
        if reward == "score_booster":
            gain = shop_box_reward_amount("score_booster")
            self.settings["score_boosters"] = int(self.settings.get("score_boosters", 0)) + gain
            self.audio.play("mystery_combo", channel="ui3")
            self.speaker.speak(f"Mystery box: {gain} score booster{'s' if gain != 1 else ''}.", interrupt=False)
            return
        if reward == "jackpot":
            gain = shop_box_reward_amount("jackpot")
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + gain
            self.audio.play("gui_cash", channel="ui3")
            self.audio.play("unlock", channel="ui4")
            self.speaker.speak(f"Mystery box jackpot: {gain} coins.", interrupt=False)
            return
        self.speaker.speak("Mystery box: empty.", interrupt=False)

    def _commit_run_rewards(self) -> None:
        if self._run_rewards_committed or not self.state.running:
            return
        self._run_rewards_committed = True
        saved_coins = int(self.state.coins)
        character_bonus = int(saved_coins * self._active_character_bonuses.banked_coin_bonus_ratio)
        total_saved_coins = saved_coins + character_bonus
        self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + total_saved_coins
        self._record_achievement_max("best_distance", int(self.state.distance))
        if total_saved_coins > 0:
            self.audio.play("coin_gui", channel="ui")
            self.audio.play("gui_cash", channel="ui2")
        if character_bonus > 0:
            active_character = selected_character_definition(self.settings)
            self.speaker.speak(f"{active_character.name} bonus saved {character_bonus} extra coins.", interrupt=False)
        record_daily_score(self.settings, int(self.state.score))
        record_coin_meter_coins(self.settings, saved_coins)
        hoverboards_used = int(self._compact_powerup_usage(self._active_run_stats.get("powerup_usage")).get("hoverboard", 0) or 0)
        for quest in record_quest_metric(self.settings, "distance_meters", int(self.state.distance)):
            self.audio.play("mission_reward", channel="ui3")
            self.speaker.speak(f"Quest ready: {quest.label}.", interrupt=False)
        for quest in record_quest_metric(self.settings, "runs_completed", 1):
            self.audio.play("mission_reward", channel="ui3")
            self.speaker.speak(f"Quest ready: {quest.label}.", interrupt=False)
        if hoverboards_used > 0:
            for quest in record_quest_metric(self.settings, "hoverboards_used", hoverboards_used):
                self.audio.play("mission_reward", channel="ui3")
                self.speaker.speak(f"Quest ready: {quest.label}.", interrupt=False)
        self._refresh_events_menu_labels()
        self._refresh_quest_menu_labels()
        self._refresh_missions_hub_menu_labels()
        self._persist_settings()

    def _clear_menu_repeat(self) -> None:
        self._menu_repeat_key = None
        self._menu_repeat_delay_remaining = 0.0

    def _set_active_menu(self, menu: Optional[Menu], start_index: int = 0, play_sound: bool = True) -> None:
        self._clear_menu_repeat()
        self._stop_learn_sound_preview()
        self.active_menu = menu
        if menu is not None:
            menu.open(start_index=start_index, play_sound=play_sound)
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
            selected_action = self.controls_menu.items[self.controls_menu.index].action if self.controls_menu.items else ""
            return selected_action == "select_binding_profile"
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
        self._selected_binding_device = "controller"
        self._refresh_control_menus()
        self.speaker.speak(
            f"{family_label(family)} connected. Open Controls in Options to review bindings.",
            interrupt=True,
        )

    def _announce_controller_disconnected(self, name: str, family: str) -> None:
        self._selected_binding_device = "keyboard"
        self._refresh_control_menus()
        self.speaker.speak(f"{family_label(family)} disconnected. Keyboard controls remain available.", interrupt=True)

    def _cancel_binding_capture(self, announce: bool = True) -> None:
        if self._binding_capture is None:
            return
        self._binding_capture = None
        if announce:
            self.speaker.speak("Control reassignment cancelled.", interrupt=True)

    def _begin_binding_capture(self, device: str, action_key: str) -> None:
        self._binding_capture = BindingCaptureRequest(device=device, action_key=action_key)
        prompt = action_label(action_key)
        if device == "keyboard":
            self.speaker.speak(f"Press a key for {prompt}. Press Escape to cancel.", interrupt=True)
            return
        controller_name = family_label(self.controls.current_controller_family())
        self.speaker.speak(
            f"Press a button or stick direction on the {controller_name} for {prompt}. Press Escape to cancel.",
            interrupt=True,
        )

    def _complete_keyboard_binding_capture(self, key: int) -> None:
        if self._binding_capture is None:
            return
        action_key = self._binding_capture.action_key
        self.controls.update_keyboard_binding(action_key, key)
        self._binding_capture = None
        self._build_keyboard_bindings_menu()
        binding_label = keyboard_key_label(self.controls.keyboard_binding_for_action(action_key))
        self.speaker.speak(f"{action_label(action_key)} set to {binding_label}.", interrupt=True)

    def _complete_controller_binding_capture(self, binding: str) -> None:
        if self._binding_capture is None:
            return
        action_key = self._binding_capture.action_key
        family = self.controls.current_controller_family()
        self.controls.update_controller_binding(family, action_key, binding)
        self._binding_capture = None
        self._build_controller_bindings_menu()
        binding_label = controller_binding_label(self.controls.controller_binding_for_action(action_key, family), family)
        self.speaker.speak(f"{action_label(action_key)} set to {binding_label}.", interrupt=True)

    def _handle_keyboard_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if self._binding_capture is not None and self._binding_capture.device == "keyboard":
                if event.key == pygame.K_ESCAPE:
                    self._cancel_binding_capture()
                    return
                self._complete_keyboard_binding_capture(event.key)
                return
            translated_key = self.controls.translate_keyboard_key(event.key, self._input_context())
            if translated_key is None:
                return
            self._process_translated_keydown(translated_key)
            return
        if event.type == pygame.KEYUP:
            translated_key = self.controls.translate_keyboard_key(event.key, self._input_context())
            if translated_key is None:
                return
            self._process_translated_keyup(translated_key)

    def _handle_window_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.VIDEORESIZE:
            width = max(MIN_WINDOW_WIDTH, int(getattr(event, "w", MIN_WINDOW_WIDTH)))
            height = max(MIN_WINDOW_HEIGHT, int(getattr(event, "h", MIN_WINDOW_HEIGHT)))
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
        focus_lost_event = getattr(pygame, "WINDOWFOCUSLOST", None)
        minimized_event = getattr(pygame, "WINDOWMINIMIZED", None)
        if focus_lost_event is not None and event.type == focus_lost_event:
            return True
        if minimized_event is not None and event.type == minimized_event:
            return True
        if event.type != pygame.ACTIVEEVENT:
            return False
        gain = int(getattr(event, "gain", 1))
        state = int(getattr(event, "state", 0))
        focus_mask = (
            int(getattr(pygame, "APPINPUTFOCUS", 0))
            | int(getattr(pygame, "APPMOUSEFOCUS", 0))
            | int(getattr(pygame, "APPACTIVE", 0))
        )
        return gain == 0 and bool(state & focus_mask)

    def _pause_active_run(self) -> bool:
        if not self.state.running or self.state.paused or self.active_menu is not None:
            return False
        self.state.paused = True
        self._set_active_menu(self.pause_menu)
        self.audio.play("menuclose", channel="ui")
        return True

    def _pause_gameplay_for_focus_loss(self) -> None:
        if not self._pause_on_focus_loss_enabled():
            return
        self._pause_active_run()

    def _handle_controller_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.CONTROLLERDEVICEADDED:
            connected = self.controls.register_added_controller(getattr(event, "device_index", None))
            if connected is not None:
                self._announce_controller_connected(connected.name, connected.family)
            return
        if event.type == pygame.CONTROLLERDEVICEREMOVED:
            disconnected = self.controls.handle_device_removed(getattr(event, "instance_id", None))
            if disconnected is not None:
                self._announce_controller_disconnected(disconnected.name, disconnected.family)
            return
        if event.type == pygame.CONTROLLERDEVICEREMAPPED:
            self.controls.refresh_connected_controllers()
            self._refresh_control_menus()
            return
        if self._binding_capture is not None and self._binding_capture.device == "controller":
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
        self.state.coins += amount
        self._record_achievement_metric("total_coins_collected", amount)
        # Fatal collisions can commit rewards mid-frame; bank late coin pickups immediately.
        if self._run_rewards_committed:
            self.settings["bank_coins"] = int(self.settings.get("bank_coins", 0)) + amount

    def run(self) -> None:
        running = True
        while running:
            delta_time = self.clock.tick(60) / 1000.0
            self._update_pending_menu_announcement(delta_time)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._request_exit()
                elif event.type in (
                    pygame.VIDEORESIZE,
                    pygame.WINDOWSIZECHANGED,
                    getattr(pygame, "WINDOWFOCUSLOST", -1),
                    getattr(pygame, "WINDOWMINIMIZED", -1),
                    pygame.ACTIVEEVENT,
                ):
                    self._handle_window_event(event)
                elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
                    self._handle_keyboard_event(event)
                elif event.type in (
                    pygame.CONTROLLERDEVICEADDED,
                    pygame.CONTROLLERDEVICEREMOVED,
                    pygame.CONTROLLERDEVICEREMAPPED,
                    pygame.CONTROLLERBUTTONDOWN,
                    pygame.CONTROLLERBUTTONUP,
                    pygame.CONTROLLERAXISMOTION,
                ):
                    self._handle_controller_event(event)

            if not self._exit_requested and self.active_menu is not None:
                self._update_menu_repeat(delta_time)
                self._update_learn_sound_preview(delta_time)
                self._update_update_install_state()
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

    def _handle_active_menu_key(self, key: int) -> bool:
        if self.active_menu is None:
            return True
        if self._binding_capture is not None:
            if key == pygame.K_ESCAPE:
                self._cancel_binding_capture()
            else:
                self._play_menu_feedback("menuedge")
            return True
        if self.active_menu == self.options_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_selected_option(-1 if key == pygame.K_LEFT else 1)
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.options_menu.items[self.options_menu.index].action
                if selected_action in {
                    "back",
                    "opt_controls",
                    "opt_sapi_menu",
                    "opt_gameplay_announcements",
                    "opt_leaderboard_account",
                    "opt_leaderboard_logout",
                }:
                    return self._handle_menu_action(selected_action)
                return True
        if self.active_menu == self.sapi_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_selected_option(-1 if key == pygame.K_LEFT else 1)
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.sapi_menu.items[self.sapi_menu.index].action
                if selected_action == "back":
                    return self._handle_menu_action(selected_action)
                return True
        if self.active_menu == self.announcements_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_selected_option(-1 if key == pygame.K_LEFT else 1)
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.announcements_menu.items[self.announcements_menu.index].action
                if selected_action == "back":
                    return self._handle_menu_action(selected_action)
                return True
        if self.active_menu == self.controls_menu:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                selected_action = self.controls_menu.items[self.controls_menu.index].action
                if selected_action == "select_binding_profile":
                    self._cycle_selected_binding_device(-1 if key == pygame.K_LEFT else 1)
                else:
                    self._play_menu_feedback("menuedge")
                return True
        if self.active_menu == self.learn_sounds_menu:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                selected_action = self.learn_sounds_menu.items[self.learn_sounds_menu.index].action
                if selected_action == "back":
                    return self._handle_menu_action("back")
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
        if action == "close":
            if self.active_menu == self.revive_menu:
                self._finish_run_loss("Run ended after crash")
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
                self._set_active_menu(
                    self.exit_confirm_menu,
                    start_index=self._menu_index_for_action(self.exit_confirm_menu, "cancel_exit"),
                )
                return True
            if self.active_menu == self.controls_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index("opt_controls"))
                return True
            if self.active_menu == self.sapi_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index("opt_sapi_menu"))
                return True
            if self.active_menu == self.announcements_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(
                    self.options_menu,
                    start_index=self._update_option_index("opt_gameplay_announcements"),
                )
                return True
            if self.active_menu in {self.keyboard_bindings_menu, self.controller_bindings_menu}:
                self._build_controls_menu()
                self._set_active_menu(self.controls_menu)
                return True
            if self.active_menu == self.pause_menu:
                self.state.paused = False
                self._set_active_menu(None)
                self.audio.play("menuclose", channel="ui")
                self.speaker.speak("Resume", interrupt=True)
                return True
            if self.active_menu == self.pause_confirm_menu:
                self._set_active_menu(self.pause_menu, start_index=1)
                return True
            if self.active_menu == self.leaderboard_logout_confirm_menu:
                self._refresh_options_menu_labels()
                self._set_active_menu(
                    self.options_menu,
                    start_index=self._update_option_index("opt_leaderboard_logout"),
                )
                return True
            if self.active_menu == self.publish_confirm_menu:
                self._set_active_menu(self.game_over_menu)
                return True
            if self.active_menu == self.exit_confirm_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "quit"))
                return True
            if self.active_menu == self.help_topic_menu:
                self._set_active_menu(self.howto_menu)
                return True
            if self.active_menu == self.events_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "events"))
                return True
            if self.active_menu == self.missions_hub_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "missions_hub"))
                return True
            if self.active_menu in {self.mission_set_menu, self.quests_menu, self.achievements_menu}:
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu)
                return True
            if self.active_menu == self.me_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "me"))
                return True
            if self.active_menu == self.server_status_menu:
                self._cancel_leaderboard_operation()
                if self._leaderboard_return_menu is not None:
                    self._set_active_menu(self._leaderboard_return_menu)
                else:
                    self._set_active_menu(self.main_menu)
                return True
            if self.active_menu == self.leaderboard_menu:
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "leaderboard"))
                return True
            if self.active_menu == self.leaderboard_profile_menu:
                self._set_active_menu(self.leaderboard_menu)
                return True
            if self.active_menu == self.leaderboard_run_detail_menu:
                self._set_active_menu(self.leaderboard_profile_menu)
                return True
            if self.active_menu == self.item_upgrade_detail_menu:
                self._refresh_item_upgrade_menu_labels()
                self._set_active_menu(self.item_upgrade_menu)
                return True
            if self.active_menu == self.item_upgrade_menu:
                return_menu = self._meta_return_menu or self.shop_menu
                if return_menu == self.shop_menu:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, "open_item_upgrades"))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_item_upgrades"))
                return True
            if self.active_menu == self.character_detail_menu:
                self._refresh_character_menu_labels()
                self._set_active_menu(self.character_menu)
                return True
            if self.active_menu == self.character_menu:
                return_menu = self._meta_return_menu or self.shop_menu
                if return_menu == self.shop_menu:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, "open_character_upgrades"))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_characters"))
                return True
            if self.active_menu == self.board_detail_menu:
                self._refresh_board_menu_labels()
                self._set_active_menu(self.board_menu)
                return True
            if self.active_menu == self.board_menu:
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_boards"))
                return True
            if self.active_menu == self.collection_menu:
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_collections"))
                return True
            if self.active_menu == self.whats_new_menu:
                self._set_active_menu(self.main_menu)
                return True
            self._set_active_menu(self.main_menu)
            return True

        if self.active_menu == self.main_menu:
            if action == "start":
                self.selected_headstarts = 0
                self.selected_score_boosters = 0
                self._refresh_loadout_menu_labels()
                self._set_active_menu(self.loadout_menu)
                return True
            if action == "events":
                self._refresh_events_menu_labels()
                self._set_active_menu(self.events_menu)
                return True
            if action == "missions_hub":
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu)
                return True
            if action == "me":
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
            if action == "whats_new":
                self._open_info_dialog(load_whats_new_content(), self.whats_new_menu)
                return True
            if action == "shop":
                self._refresh_shop_menu_labels()
                self._set_active_menu(self.shop_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
            if action == "leaderboard":
                self._open_leaderboard()
                return True
            if action == "options":
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu)
                return True
            if action == "howto":
                self._showing_upgrade_help = False
                self._refresh_howto_menu_labels()
                self._set_active_menu(self.howto_menu)
                return True
            if action == "learn_sounds":
                self._set_active_menu(self.learn_sounds_menu)
                return True
            if action == "check_updates":
                self._check_for_updates(announce_result=True)
                return True
            if action == "quit":
                if not self._exit_confirmation_enabled():
                    return False
                self._set_active_menu(
                    self.exit_confirm_menu,
                    start_index=self._menu_index_for_action(self.exit_confirm_menu, "cancel_exit"),
                )
                return True

        if self.active_menu == self.loadout_menu:
            if action == "back":
                self._set_active_menu(self.main_menu)
                return True
            if action == "loadout_board_info":
                self.speaker.speak(self._loadout_board_label(), interrupt=True)
                return True
            if action == "toggle_headstart":
                owned = int(self.settings.get("headstarts", 0))
                if owned <= 0:
                    self.audio.play("menuedge", channel="ui")
                    self.speaker.speak("No headstarts available.", interrupt=True)
                    return True
                self.selected_headstarts = (self.selected_headstarts + 1) % (clamp_headstart_uses(owned) + 1)
                self.audio.play("confirm", channel="ui")
                self._refresh_loadout_menu_labels()
                self.speaker.speak(self.loadout_menu.items[1].label, interrupt=True)
                return True
            if action == "toggle_score_booster":
                owned = int(self.settings.get("score_boosters", 0))
                if owned <= 0:
                    self.audio.play("menuedge", channel="ui")
                    self.speaker.speak("No score boosters available.", interrupt=True)
                    return True
                self.selected_score_boosters = (self.selected_score_boosters + 1) % (min(3, owned) + 1)
                self.audio.play("confirm", channel="ui")
                self._refresh_loadout_menu_labels()
                self.speaker.speak(self.loadout_menu.items[2].label, interrupt=True)
                return True
            if action == "begin_run":
                self.start_run()
                return True

        if self.active_menu == self.events_menu:
            if action == "claim_daily_high_score":
                if self._apply_meta_reward(claim_daily_high_score_reward(self.settings), "Daily High Score reward"):
                    self.audio.play("mission_reward", channel="ui")
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == "claim_coin_meter":
                if self._apply_meta_reward(claim_coin_meter_reward(self.settings), "Coin Meter chest"):
                    self.audio.play("mission_reward", channel="ui")
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == "claim_daily_gift":
                reward = claim_daily_gift(self.settings)
                if reward is not None:
                    self.audio.play("mystery_box_open", channel="ui")
                if self._apply_meta_reward(reward, "Free Daily Gift"):
                    self._refresh_events_menu_labels()
                    self._refresh_shop_menu_labels()
                    self._persist_settings()
                return True
            if action == "claim_login_reward":
                if self._apply_meta_reward(claim_login_calendar_reward(self.settings), "Daily Login reward"):
                    self.audio.play("mission_reward", channel="ui")
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == "back":
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "events"))
                return True
            return True

        if self.active_menu == self.missions_hub_menu:
            if action == "open_quests":
                self._refresh_quest_menu_labels()
                self._set_active_menu(self.quests_menu)
                return True
            if action == "open_mission_set":
                self._refresh_mission_set_menu_labels()
                self._set_active_menu(self.mission_set_menu)
                return True
            if action == "open_achievements":
                self._refresh_achievements_menu_labels()
                self._set_active_menu(self.achievements_menu)
                return True
            if action == "back":
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "missions_hub"))
                return True
            return True

        if self.active_menu == self.mission_set_menu:
            if action == "back":
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu, start_index=self._menu_index_for_action(self.missions_hub_menu, "open_mission_set"))
                return True
            return True

        if self.active_menu == self.quests_menu:
            if action == "claim_quest_meter":
                if self._apply_meta_reward(claim_meter_reward(self.settings), "Sneaker Meter reward"):
                    self.audio.play("mission_reward", channel="ui")
                    self._refresh_quest_menu_labels()
                    self._persist_settings()
                return True
            if action.startswith("claim_quest:"):
                quest_key = action.split(":", 1)[1]
                quest = claim_quest(self.settings, quest_key)
                if quest is None:
                    self.audio.play("menuedge", channel="ui")
                    self.speaker.speak("That quest is not ready yet.", interrupt=True)
                    return True
                self.audio.play("mission_reward", channel="ui")
                self.audio.play("unlock", channel="ui2")
                self.speaker.speak(f"{quest.label}. {quest.sneaker_reward} sneakers added.", interrupt=True)
                self._refresh_quest_menu_labels()
                self._refresh_missions_hub_menu_labels()
                self._persist_settings()
                return True
            if action == "reset_daily_progress":
                self._reset_daily_progress()
                return True
            if action == "back":
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu, start_index=self._menu_index_for_action(self.missions_hub_menu, "open_quests"))
                return True
            return True

        if self.active_menu == self.me_menu:
            if action == "open_characters":
                self._meta_return_menu = self.me_menu
                self._refresh_character_menu_labels()
                self._set_active_menu(self.character_menu)
                return True
            if action == "open_boards":
                self._meta_return_menu = self.me_menu
                self._refresh_board_menu_labels()
                self._set_active_menu(self.board_menu)
                return True
            if action == "open_item_upgrades":
                self._meta_return_menu = self.me_menu
                self._refresh_item_upgrade_menu_labels()
                self._set_active_menu(self.item_upgrade_menu)
                return True
            if action == "open_collections":
                self._refresh_collection_menu_labels()
                self._set_active_menu(self.collection_menu)
                return True
            if action == "back":
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "me"))
                return True
            return True

        if self.active_menu == self.options_menu:
            if action == "opt_leaderboard_account":
                self._prompt_and_authenticate_leaderboard_account()
                return True
            if action == "opt_leaderboard_logout":
                self._set_active_menu(
                    self.leaderboard_logout_confirm_menu,
                    start_index=self._menu_index_for_action(
                        self.leaderboard_logout_confirm_menu,
                        "cancel_leaderboard_logout",
                    ),
                )
                return True
            if action == "opt_sapi_menu":
                self._refresh_sapi_menu_labels()
                self._set_active_menu(self.sapi_menu)
                return True
            if action == "opt_gameplay_announcements":
                self._refresh_announcements_menu_labels()
                self._set_active_menu(self.announcements_menu)
                return True
            if action == "opt_controls":
                self._selected_binding_device = "controller" if self.controls.active_controller() is not None else "keyboard"
                self._refresh_control_menus()
                self._set_active_menu(self.controls_menu)
                return True
            if action == "back":
                self.audio.play("menuclose", channel="ui")
                self._set_active_menu(self.main_menu)
                return True
            return True

        if self.active_menu == self.sapi_menu:
            if action == "back":
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index("opt_sapi_menu"))
                return True
            return True

        if self.active_menu == self.announcements_menu:
            if action == "back":
                self._refresh_options_menu_labels()
                self._set_active_menu(
                    self.options_menu,
                    start_index=self._update_option_index("opt_gameplay_announcements"),
                )
                return True
            return True

        if self.active_menu == self.controls_menu:
            if action == "announce_active_input":
                self.speaker.speak(
                    f"Current input is {self.controls.current_input_label()}. {self.controls.current_controller_label()}.",
                    interrupt=True,
                )
                return True
            if action == "select_binding_profile":
                self.speaker.speak(self.controls_menu.items[self.controls_menu.index].label, interrupt=True)
                return True
            if action == "open_selected_bindings":
                if self._selected_binding_device == "controller":
                    if self.controls.active_controller() is None:
                        self._play_menu_feedback("menuedge")
                        self.speaker.speak("No controller connected.", interrupt=True)
                        return True
                    self._build_controller_bindings_menu()
                    self._set_active_menu(self.controller_bindings_menu)
                    return True
                self._build_keyboard_bindings_menu()
                self._set_active_menu(self.keyboard_bindings_menu)
                return True
            if action == "reset_selected_bindings":
                if self._selected_binding_device == "controller":
                    if self.controls.active_controller() is None:
                        self._play_menu_feedback("menuedge")
                        self.speaker.speak("No controller connected.", interrupt=True)
                        return True
                    family = self.controls.current_controller_family()
                    self.controls.reset_controller_bindings(family)
                    self._build_controls_menu()
                    self._play_menu_feedback("confirm")
                    self.speaker.speak(f"{family_label(family)} bindings reset to recommended defaults.", interrupt=True)
                    return True
                self.controls.reset_keyboard_bindings()
                self._build_controls_menu()
                self._play_menu_feedback("confirm")
                self.speaker.speak("Keyboard bindings reset to defaults.", interrupt=True)
                return True
            if action == "back":
                self._refresh_options_menu_labels()
                self._set_active_menu(self.options_menu, start_index=self._update_option_index("opt_controls"))
                return True

        if self.active_menu == self.keyboard_bindings_menu:
            if action == "reset_keyboard_bindings":
                self.controls.reset_keyboard_bindings()
                self._build_keyboard_bindings_menu()
                self._play_menu_feedback("confirm")
                self.speaker.speak("Keyboard bindings reset to defaults.", interrupt=True)
                return True
            if action.startswith("bind_keyboard:"):
                self._begin_binding_capture("keyboard", action.split(":", 1)[1])
                return True
            if action == "back":
                self._build_controls_menu()
                self._set_active_menu(self.controls_menu, start_index=2)
                return True

        if self.active_menu == self.controller_bindings_menu:
            if action == "reset_controller_bindings":
                family = self.controls.current_controller_family()
                self.controls.reset_controller_bindings(family)
                self._build_controller_bindings_menu()
                self._play_menu_feedback("confirm")
                self.speaker.speak(f"{family_label(family)} bindings reset to recommended defaults.", interrupt=True)
                return True
            if action.startswith("bind_controller:"):
                if self.controls.active_controller() is None:
                    self._play_menu_feedback("menuedge")
                    self.speaker.speak("No controller connected.", interrupt=True)
                    return True
                self._begin_binding_capture("controller", action.split(":", 1)[1])
                return True
            if action == "back":
                self._build_controls_menu()
                self._set_active_menu(self.controls_menu, start_index=2)
                return True

        if self.active_menu == self.update_menu:
            if action == "back":
                self._set_active_menu(self.main_menu)
                return True
            if action == "download_update":
                self._begin_update_install()
                return True
            if action == "install_busy":
                return True
            if action == "restart_after_update":
                if self._update_restart_script_path and self.updater.launch_restart_script(self._update_restart_script_path):
                    self.speaker.speak("Restarting to apply the update.", interrupt=True)
                    return False
                self.speaker.speak("Update files are ready. Restart the game to finish applying them.", interrupt=True)
                return False
            if action == "open_release_page":
                release = self._latest_update_result.release if self._latest_update_result is not None else None
                opened = self.updater.open_release_page(release)
                if opened:
                    self.speaker.speak("Opening the release page.", interrupt=True)
                    return True
                self._play_menu_feedback("menuedge")
                self.speaker.speak("Unable to open the release page.", interrupt=True)
                return True
            if action == "quit":
                return False

        if self.active_menu == self.server_status_menu:
            if action == "back":
                self._cancel_leaderboard_operation()
                if self._leaderboard_return_menu is not None:
                    self._set_active_menu(self._leaderboard_return_menu)
                else:
                    self._set_active_menu(self.main_menu)
                return True
            self.speaker.speak(self.server_status_menu.items[0].label, interrupt=True)
            return True

        if self.active_menu == self.leaderboard_menu:
            if action == "back":
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "leaderboard"))
                return True
            if action == "leaderboard_cycle_period":
                self._cycle_leaderboard_period()
                return True
            if action == "leaderboard_cycle_difficulty":
                self._cycle_leaderboard_difficulty()
                return True
            if action == "leaderboard_refresh":
                self._open_leaderboard(force_refresh=True)
                return True
            if action.startswith("leaderboard_player:"):
                self._open_leaderboard_profile(action.split(":", 1)[1])
                return True
            if action == "leaderboard_info":
                self.speaker.speak(self.leaderboard_menu.items[self.leaderboard_menu.index].label, interrupt=True)
                return True

        if self.active_menu == self.leaderboard_profile_menu:
            if action == "back":
                self._set_active_menu(self.leaderboard_menu)
                return True
            if action.startswith("leaderboard_run:"):
                self._open_leaderboard_run_detail(action.split(":", 1)[1])
                return True
            self.speaker.speak(self.leaderboard_profile_menu.items[self.leaderboard_profile_menu.index].label, interrupt=True)
            return True

        if self.active_menu == self.leaderboard_run_detail_menu:
            if action == "back":
                self._set_active_menu(self.leaderboard_profile_menu)
                return True
            self.speaker.speak(self.leaderboard_run_detail_menu.items[self.leaderboard_run_detail_menu.index].label, interrupt=True)
            return True

        if self.active_menu == self.shop_menu:
            if action == "back":
                self._set_active_menu(self.main_menu)
                return True
            if action == "buy_hoverboard":
                self._purchase_shop_item("hoverboard")
                return True
            if action == "buy_box":
                self._purchase_shop_item("mystery_box")
                return True
            if action == "buy_headstart":
                self._purchase_shop_item("headstart")
                return True
            if action == "buy_score_booster":
                self._purchase_shop_item("score_booster")
                return True
            if action == "claim_daily_gift":
                reward = claim_daily_gift(self.settings)
                if reward is not None:
                    self.audio.play("mystery_box_open", channel="ui")
                if self._apply_meta_reward(reward, "Free Daily Gift"):
                    self._refresh_shop_menu_labels()
                    self._refresh_events_menu_labels()
                    self._persist_settings()
                return True
            if action == "open_item_upgrades":
                self._meta_return_menu = self.shop_menu
                self._refresh_item_upgrade_menu_labels()
                self._set_active_menu(self.item_upgrade_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True
            if action == "open_character_upgrades":
                self._meta_return_menu = self.shop_menu
                self._refresh_character_menu_labels()
                self._set_active_menu(self.character_menu)
                self.speaker.speak(self._shop_coins_label(), interrupt=False)
                return True

        if self.active_menu == self.item_upgrade_menu:
            if action == "back":
                if self._meta_return_menu in {None, self.shop_menu}:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, "open_item_upgrades"))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_item_upgrades"))
                return True
            if action.startswith("item_upgrade_open:"):
                self._refresh_item_upgrade_detail_menu_labels(action.split(":", 1)[1])
                self._set_active_menu(self.item_upgrade_detail_menu)
                return True

        if self.active_menu == self.item_upgrade_detail_menu:
            if action == "back":
                self._refresh_item_upgrade_menu_labels()
                upgrade_keys = [definition.key for definition in item_upgrade_definitions()]
                try:
                    start_index = upgrade_keys.index(self._item_upgrade_detail_key)
                except ValueError:
                    start_index = 0
                self._set_active_menu(self.item_upgrade_menu, start_index=start_index)
                return True
            if action.startswith("item_upgrade_status_info:"):
                definition = item_upgrade_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name}. {self._item_upgrade_status_label(definition.key)}.", interrupt=True)
                return True
            if action.startswith("item_upgrade_effect_info:"):
                definition = item_upgrade_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name}. {self._item_upgrade_effect_label(definition.key)}.", interrupt=True)
                return True
            if action.startswith("item_upgrade_purchase:"):
                self._purchase_item_upgrade(action.split(":", 1)[1])
                return True
            if action.startswith("item_upgrade_max_info:"):
                definition = item_upgrade_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name} is already at max level.", interrupt=True)
                return True

        if self.active_menu == self.character_menu:
            if action == "back":
                if self._meta_return_menu in {None, self.shop_menu}:
                    self._refresh_shop_menu_labels()
                    self._set_active_menu(self.shop_menu, start_index=self._menu_index_for_action(self.shop_menu, "open_character_upgrades"))
                    return True
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_characters"))
                return True
            if action.startswith("character_open:"):
                self._refresh_character_detail_menu_labels(action.split(":", 1)[1])
                self._set_active_menu(self.character_detail_menu)
                return True

        if self.active_menu == self.character_detail_menu:
            if action == "back":
                self._refresh_character_menu_labels()
                character_keys = [definition.key for definition in character_definitions()]
                try:
                    start_index = character_keys.index(self._character_detail_key)
                except ValueError:
                    start_index = 0
                self._set_active_menu(self.character_menu, start_index=start_index)
                return True
            if action.startswith("character_status_info:"):
                definition = character_definition(action.split(":", 1)[1])
                self.speaker.speak(
                    f"{definition.name}. {self._character_status_label(definition.key)}.",
                    interrupt=True,
                )
                return True
            if action.startswith("character_perk_info:"):
                definition = character_definition(action.split(":", 1)[1])
                self.speaker.speak(
                    f"{definition.name}. {definition.description} Current perk: {character_perk_summary(definition, character_level(self.settings, definition.key))}.",
                    interrupt=True,
                )
                return True
            if action.startswith("character_unlock:"):
                self._unlock_character(action.split(":", 1)[1])
                return True
            if action.startswith("character_select:"):
                self._select_character(action.split(":", 1)[1])
                return True
            if action.startswith("character_upgrade:"):
                self._upgrade_character(action.split(":", 1)[1])
                return True

        if self.active_menu == self.board_menu:
            if action == "back":
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_boards"))
                return True
            if action.startswith("board_open:"):
                self._refresh_board_detail_menu_labels(action.split(":", 1)[1])
                self._set_active_menu(self.board_detail_menu)
                return True

        if self.active_menu == self.board_detail_menu:
            if action == "back":
                self._refresh_board_menu_labels()
                board_keys = [definition.key for definition in board_definitions()]
                try:
                    start_index = board_keys.index(self._board_detail_key)
                except ValueError:
                    start_index = 0
                self._set_active_menu(self.board_menu, start_index=start_index)
                return True
            if action.startswith("board_status_info:"):
                definition = board_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name}. {self._board_status_label(definition.key)}.", interrupt=True)
                return True
            if action.startswith("board_power_info:"):
                definition = board_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name}. {self._board_power_label(definition.key)}.", interrupt=True)
                return True
            if action.startswith("board_unlock:"):
                self._unlock_board(action.split(":", 1)[1])
                return True
            if action.startswith("board_select:"):
                self._select_board(action.split(":", 1)[1])
                return True
            if action.startswith("board_active_info:"):
                definition = board_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name} is already the active board.", interrupt=True)
                return True

        if self.active_menu == self.collection_menu:
            if action == "back":
                self._refresh_me_menu_labels()
                self._set_active_menu(self.me_menu, start_index=self._menu_index_for_action(self.me_menu, "open_collections"))
                return True
            if action.startswith("collection_info:"):
                key = action.split(":", 1)[1]
                definition = next(item for item in collection_definitions() if item.key == key)
                owned, total = collection_progress(self.settings, definition)
                status = "complete" if key in completed_collection_keys(self.settings) else "in progress"
                self.speaker.speak(
                    f"{definition.name}. {definition.description} {owned} of {total}. Bonus: {collection_bonus_summary(definition)}. Status: {status}.",
                    interrupt=True,
                )
                return True
            if action.startswith("character_active_info:"):
                definition = character_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name} is already your active character.", interrupt=True)
                return True
            if action.startswith("character_unlock_hint:"):
                definition = character_definition(action.split(":", 1)[1])
                self.speaker.speak(f"Unlock {definition.name} before upgrading.", interrupt=True)
                return True
            if action.startswith("character_max_info:"):
                definition = character_definition(action.split(":", 1)[1])
                self.speaker.speak(f"{definition.name} is already at max level.", interrupt=True)
                return True

        if self.active_menu == self.achievements_menu:
            if action == "back":
                self._refresh_missions_hub_menu_labels()
                self._set_active_menu(self.missions_hub_menu, start_index=self._menu_index_for_action(self.missions_hub_menu, "open_achievements"))
                return True
            if action.startswith("achievement:"):
                achievement_key = action.split(":", 1)[1]
                for achievement in achievement_definitions():
                    if achievement.key == achievement_key:
                        self.speaker.speak(achievement.description, interrupt=True)
                        break
                return True

        if self.active_menu == self.learn_sounds_menu:
            if action == "back":
                self._set_active_menu(self.main_menu)
                return True

        if self.active_menu == self.howto_menu:
            if action == "back":
                self._showing_upgrade_help = False
                self._refresh_howto_menu_labels()
                self._set_active_menu(self.main_menu)
                return True
            if action.startswith("howto:"):
                self._open_help_topic(action.split(":", 1)[1])
                return True

        if self.active_menu == self.help_topic_menu:
            if action == "back":
                self._set_active_menu(self.howto_menu)
                return True
            if action == "copy_info_line":
                return self._copy_menu_text(
                    self.help_topic_menu.items[self.help_topic_menu.index].label,
                    "Selected line copied to clipboard.",
                )
            if action == "copy_info_all":
                return self._copy_menu_text(
                    self._selected_info_copy_all_text(self.help_topic_menu),
                    self._selected_info_copy_all_message(self.help_topic_menu),
                )
            return True

        if self.active_menu == self.whats_new_menu:
            if action == "back":
                self._set_active_menu(self.main_menu)
                return True
            if action == "copy_info_line":
                return self._copy_menu_text(
                    self.whats_new_menu.items[self.whats_new_menu.index].label,
                    "Selected line copied to clipboard.",
                )
            if action == "copy_info_all":
                return self._copy_menu_text(
                    self._selected_info_copy_all_text(self.whats_new_menu),
                    self._selected_info_copy_all_message(self.whats_new_menu),
                )
                return True

        if self.active_menu == self.pause_menu:
            if action == "resume":
                self.state.paused = False
                self._set_active_menu(None)
                self.speaker.speak("Resume", interrupt=True)
                return True
            if action == "to_main":
                self._set_active_menu(self.pause_confirm_menu)
                return True

        if self.active_menu == self.pause_confirm_menu:
            if action == "confirm_to_main":
                self.end_run(to_menu=True)
                return True
            if action == "cancel_to_main":
                self._set_active_menu(self.pause_menu, start_index=1)
                return True

        if self.active_menu == self.leaderboard_logout_confirm_menu:
            if action == "confirm_leaderboard_logout":
                self._logout_leaderboard_account()
                return True
            if action == "cancel_leaderboard_logout":
                self._refresh_options_menu_labels()
                self._set_active_menu(
                    self.options_menu,
                    start_index=self._update_option_index("opt_leaderboard_logout"),
                )
                return True

        if self.active_menu == self.publish_confirm_menu:
            if action == "publish_confirm_yes":
                self._publish_latest_game_over_run()
                return True
            if action == "publish_confirm_no":
                target_menu = self._publish_confirm_return_menu or self.game_over_menu
                self._set_active_menu(target_menu, start_index=self._publish_confirm_return_index)
                return True

        if self.active_menu == self.exit_confirm_menu:
            if action == "confirm_exit":
                return False
            if action == "cancel_exit":
                self._set_active_menu(self.main_menu, start_index=self._menu_index_for_action(self.main_menu, "quit"))
                return True

        if self.active_menu == self.revive_menu:
            if action == "revive":
                self._revive_run()
                return True
            if action in ("end_run", "close"):
                self._finish_run_loss("Run ended after crash")
                return True

        if self.active_menu == self.game_over_menu:
            if action == "game_over_retry":
                self.start_run()
                return True
            if action == "game_over_main_menu":
                if self._game_over_publish_state != "published" and self._should_offer_publish_prompt():
                    self._open_publish_confirmation(return_menu=self.main_menu, start_index=0)
                    return True
                self.active_menu = self.main_menu
                self.active_menu.open()
                return True
            if action.startswith("game_over_info_"):
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

    def _start_leaderboard_operation(
        self,
        operation: str,
        title: str,
        message: str,
        worker,
        *,
        return_menu: Menu | None = None,
        show_status: bool = True,
        reject_message: bool = True,
    ) -> bool:
        if self._leaderboard_active_operation is not None:
            if reject_message:
                self.audio.play("menuedge", channel="ui")
                self.speaker.speak("Please wait for the current server request to finish.", interrupt=True)
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
                self._leaderboard_operation_queue.put(
                    LeaderboardOperationResult(token=token, operation=operation, success=False, payload=exc)
                )
                return
            self._leaderboard_operation_queue.put(
                LeaderboardOperationResult(token=token, operation=operation, success=True, payload=result)
            )

        threading.Thread(target=runner, name=f"leaderboard-{operation}", daemon=True).start()
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
        if operation in {"leaderboard_connect", "leaderboard_refresh"}:
            data = dict(payload or {})
            if bool(data.get("just_connected")):
                self.audio.play("connect", channel="ui")
            selected_action = None
            if self.active_menu == self.leaderboard_menu and self.leaderboard_menu.items:
                selected_action = self.leaderboard_menu.items[self.leaderboard_menu.index].action
            self._leaderboard_period_filter = str(data.get("period") or self._leaderboard_period_filter or "season")
            self._leaderboard_difficulty_filter = str(data.get("difficulty") or self._leaderboard_difficulty_filter or "all")
            self._leaderboard_season = dict(data.get("season") or self._leaderboard_season or {})
            self._leaderboard_entries = list(data.get("entries") or [])
            self._leaderboard_total_players = int(data.get("total_players", len(self._leaderboard_entries)) or 0)
            self._leaderboard_cache_loaded_at = time.monotonic()
            self._refresh_leaderboard_menu()
            if selected_action:
                self.leaderboard_menu.index = self._menu_index_for_action(self.leaderboard_menu, selected_action)
            if operation == "leaderboard_connect":
                self._set_active_menu(self.leaderboard_menu, play_sound=False)
            return
        if operation == "leaderboard_profile":
            data = dict(payload or {})
            self._leaderboard_profile = data
            self._leaderboard_season = dict(data.get("season") or self._leaderboard_season or {})
            self._leaderboard_profile_history_count = int(data.get("history_total", 0) or 0)
            self._refresh_leaderboard_profile_menu()
            self._set_active_menu(self.leaderboard_profile_menu, play_sound=False)
            self.speaker.speak(f"{data.get('username', 'Player')} profile loaded.", interrupt=True)
            return
        if operation == "leaderboard_auth":
            data = dict(payload or {})
            if bool(data.get("just_connected")):
                self.audio.play("connect", channel="ui")
            self._leaderboard_username = str(data.get("username") or self._leaderboard_username or "").strip()
            self.settings["leaderboard_username"] = self._leaderboard_username
            account_sync = dict(data.get("account_sync") or {})
            if account_sync:
                self._apply_leaderboard_account_sync(account_sync, announce_rewards=True)
            self._refresh_options_menu_labels()
            self._persist_settings()
            self.speaker.speak(
                "Account created." if str(data.get("status")) == "created" else "Signed in.",
                interrupt=True,
            )
            if self._leaderboard_return_menu is not None:
                self._set_active_menu(self._leaderboard_return_menu, play_sound=False)
            return
        if operation == "leaderboard_publish":
            data = dict(payload or {})
            if bool(data.get("just_connected")):
                self.audio.play("connect", channel="ui")
            publish_username = str(data.get("username") or self._leaderboard_username or "").strip()
            if publish_username:
                self._leaderboard_username = publish_username
                self.settings["leaderboard_username"] = publish_username
                self._refresh_options_menu_labels()
                self._persist_settings()
            self._game_over_publish_state = "published"
            self._leaderboard_cache_loaded_at = 0.0
            self._refresh_game_over_menu()
            target_menu = self._publish_confirm_return_menu or self.game_over_menu
            self._set_active_menu(target_menu, start_index=self._publish_confirm_return_index, play_sound=False)
            if target_menu == self.game_over_menu:
                self.game_over_menu.index = 4
            suspicious_run = str(data.get("verification_status") or "verified") == "suspicious"
            if bool(data.get("high_score")):
                rank = data.get("board_rank")
                self.audio.play("high", channel="ui")
                if rank is not None:
                    message = f"New personal best. Leaderboard rank {rank}."
                else:
                    message = "New personal best."
                if suspicious_run:
                    message = f"{message} Run flagged as suspicious."
                self.speaker.speak(message, interrupt=True)
                return
            if suspicious_run:
                self.speaker.speak("Run published and flagged as suspicious.", interrupt=True)
            return
        if operation == "leaderboard_startup_sync":
            data = dict(payload or {})
            self._apply_leaderboard_account_sync(data, announce_rewards=True)
            self._refresh_leaderboard_menu()
            return

    def _handle_leaderboard_error(self, operation: str, error: object) -> None:
        if isinstance(error, LeaderboardClientError) and error.code == "reauth_required":
            self._leaderboard_username = ""
            self.settings["leaderboard_username"] = ""
            self.leaderboard_client.principal_username = ""
            self.leaderboard_client.auth_token = ""
            self._refresh_options_menu_labels()
            self._persist_settings()
        if operation == "leaderboard_startup_sync" and not (
            isinstance(error, LeaderboardClientError) and error.code == "reauth_required"
        ):
            return
        message = str(error)
        if operation == "leaderboard_refresh" and self._leaderboard_entries:
            self.audio.play("menuedge", channel="ui")
            self._refresh_leaderboard_menu()
            if self.active_menu != self.leaderboard_menu:
                self._set_active_menu(self.leaderboard_menu, play_sound=False)
            self.speaker.speak(f"{message} Showing the last downloaded leaderboard.", interrupt=True)
            return
        self.audio.play("menuedge", channel="ui")
        if self._leaderboard_return_menu is not None:
            self._set_active_menu(self._leaderboard_return_menu, play_sound=False)
        else:
            self._set_active_menu(self.main_menu, play_sound=False)
        self.speaker.speak(message, interrupt=True)

    def _open_leaderboard(self, force_refresh: bool = False) -> None:
        if not self._leaderboard_is_authenticated():
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak("Sign in from Options, Set User Name, before opening the leaderboard.", interrupt=True)
            return

        if self._leaderboard_entries and not force_refresh:
            self._refresh_leaderboard_menu()
            self._set_active_menu(self.leaderboard_menu)
            if not self._leaderboard_cache_is_fresh():
                self._request_leaderboard_refresh(
                    operation="leaderboard_refresh",
                    return_menu=self.leaderboard_menu,
                    show_status=False,
                )
            return
        self._request_leaderboard_refresh(
            operation="leaderboard_connect",
            return_menu=self.main_menu,
            show_status=not self._leaderboard_entries,
        )

    def _refresh_leaderboard_menu(self) -> None:
        total = max(self._leaderboard_total_players, len(self._leaderboard_entries))
        self.leaderboard_menu.title = f"Season Leaderboard   {len(self._leaderboard_entries)}/{total}"
        items = [
            MenuItem(
                self._leaderboard_season_identity_label(),
                "leaderboard_info",
            ),
            MenuItem(self._leaderboard_season_status_label(), "leaderboard_info"),
            MenuItem(self._leaderboard_reward_status_label(), "leaderboard_info"),
            MenuItem(self._leaderboard_difficulty_option_label(), "leaderboard_cycle_difficulty"),
        ]
        items.extend(
            MenuItem(self._leaderboard_entry_label(entry), f"leaderboard_player:{entry['username']}")
            for entry in self._leaderboard_entries
        )
        if not self._leaderboard_entries:
            items.append(MenuItem("No published runs were found for the current filters.", "leaderboard_info"))
        items.append(MenuItem("Refresh", "leaderboard_refresh"))
        items.append(MenuItem("Back", "back"))
        self.leaderboard_menu.items = items

    def _leaderboard_period_option_label(self) -> str:
        return f"Season: {leaderboard_period_display_label(self._leaderboard_period_filter)}"

    def _leaderboard_difficulty_option_label(self) -> str:
        return f"Difficulty: {leaderboard_difficulty_filter_display_label(self._leaderboard_difficulty_filter)}"

    def _leaderboard_entry_label(self, entry: dict[str, object]) -> str:
        segments = [
            f"{int(entry.get('rank', 0) or 0)}. {entry.get('username', 'Player')}",
            verification_display_label(entry.get("verification_status")),
        ]
        if self._leaderboard_difficulty_filter == "all":
            segments.append(difficulty_display_label(entry.get("difficulty")))
        segments.extend(
            [
                f"Score {int(entry.get('score', 0) or 0)}",
                f"Coins {int(entry.get('coins', 0) or 0)}",
                f"Time {format_play_time(entry.get('play_time_seconds', 0) or 0)}",
            ]
        )
        return "   ".join(segments)

    def _cycle_leaderboard_period(self) -> None:
        current_index = LEADERBOARD_PERIOD_ORDER.index(self._leaderboard_period_filter)
        self._leaderboard_period_filter = LEADERBOARD_PERIOD_ORDER[(current_index + 1) % len(LEADERBOARD_PERIOD_ORDER)]
        self._leaderboard_cache_loaded_at = 0.0
        self._refresh_leaderboard_menu()
        self._set_active_menu(self.leaderboard_menu, start_index=self._menu_index_for_action(self.leaderboard_menu, "leaderboard_cycle_period"))
        self._request_leaderboard_refresh("leaderboard_refresh", return_menu=self.leaderboard_menu, show_status=False)

    def _cycle_leaderboard_difficulty(self) -> None:
        current_index = LEADERBOARD_DIFFICULTY_FILTER_ORDER.index(self._leaderboard_difficulty_filter)
        self._leaderboard_difficulty_filter = LEADERBOARD_DIFFICULTY_FILTER_ORDER[
            (current_index + 1) % len(LEADERBOARD_DIFFICULTY_FILTER_ORDER)
        ]
        self._leaderboard_cache_loaded_at = 0.0
        self._refresh_leaderboard_menu()
        self._set_active_menu(
            self.leaderboard_menu,
            start_index=self._menu_index_for_action(self.leaderboard_menu, "leaderboard_cycle_difficulty"),
        )
        self._request_leaderboard_refresh("leaderboard_refresh", return_menu=self.leaderboard_menu, show_status=False)

    def _open_leaderboard_profile(self, username: str) -> None:
        def worker() -> dict[str, object]:
            self.leaderboard_client.connect()
            return self.leaderboard_client.fetch_profile(username=username, history_limit=50)

        self._start_leaderboard_operation(
            "leaderboard_profile",
            "Leaderboard",
            f"Loading {username}...",
            worker,
            return_menu=self.leaderboard_menu,
        )

    def _request_leaderboard_refresh(self, operation: str, return_menu: Menu, show_status: bool) -> bool:
        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            board = self.leaderboard_client.fetch_leaderboard(
                limit=100,
                period=self._leaderboard_period_filter,
                difficulty=self._leaderboard_difficulty_filter,
            )
            board["just_connected"] = just_connected
            return board

        return self._start_leaderboard_operation(
            operation,
            "Leaderboard",
            "Refreshing leaderboard..." if operation == "leaderboard_refresh" else "Connecting to server...",
            worker,
            return_menu=return_menu,
            show_status=show_status,
            reject_message=show_status,
        )

    def _leaderboard_cache_is_fresh(self) -> bool:
        if not self._leaderboard_entries or self._leaderboard_cache_loaded_at <= 0:
            return False
        return (time.monotonic() - self._leaderboard_cache_loaded_at) <= LEADERBOARD_CACHE_TTL_SECONDS

    def _refresh_leaderboard_profile_menu(self) -> None:
        profile = self._leaderboard_profile or {}
        summary = dict(profile.get("summary") or {})
        latest_run = dict(profile.get("latest_run") or {})
        best_run = dict(profile.get("best_run") or {})
        history = list(profile.get("history") or [])
        self.leaderboard_profile_menu.title = str(profile.get("username") or "Player")
        items = [
            MenuItem(
                f"Season Rank: {profile.get('board_rank') if profile.get('board_rank') is not None else 'Unranked'}",
                "leaderboard_profile_info",
            ),
            MenuItem(f"Published Runs: {int(summary.get('published_runs_total', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Active Days: {int(summary.get('active_days', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Recent Avg Score: {int(summary.get('recent_average_score', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Recent Avg Coins: {int(summary.get('recent_average_coins', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(
                f"Recent Avg Play Time: {format_play_time(summary.get('recent_average_play_time_seconds', 0) or 0)}",
                "leaderboard_profile_info",
            ),
            MenuItem(
                f"Recent Avg Distance: {int(summary.get('recent_average_distance_meters', 0) or 0)} meters",
                "leaderboard_profile_info",
            ),
            MenuItem(
                f"Best Score Improvement: +{int(summary.get('best_improvement_score', 0) or 0)}",
                "leaderboard_profile_info",
            ),
            MenuItem(f"Latest Score: {int(latest_run.get('score', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Latest Coins: {int(latest_run.get('coins', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Latest Play Time: {format_play_time(latest_run.get('play_time_seconds', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Latest Difficulty: {difficulty_display_label(latest_run.get('difficulty'))}", "leaderboard_profile_info"),
            MenuItem(f"Latest Status: {verification_display_label(latest_run.get('verification_status'))}", "leaderboard_profile_info"),
            MenuItem(f"Best Score: {int(best_run.get('score', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Best Coins: {int(best_run.get('coins', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Best Play Time: {format_play_time(best_run.get('play_time_seconds', 0) or 0)}", "leaderboard_profile_info"),
            MenuItem(f"Best Difficulty: {difficulty_display_label(best_run.get('difficulty'))}", "leaderboard_profile_info"),
            MenuItem(f"Best Status: {verification_display_label(best_run.get('verification_status'))}", "leaderboard_profile_info"),
        ]
        for history_entry in history:
            items.append(
                MenuItem(
                    self._leaderboard_history_label(history_entry),
                    f"leaderboard_run:{history_entry['submission_id']}",
                )
            )
        items.append(MenuItem("Back", "back"))
        self.leaderboard_profile_menu.items = items

    def _leaderboard_history_label(self, history_entry: dict[str, object]) -> str:
        published_at = str(history_entry.get("published_at") or "").replace("T", " ")[:19]
        return "   ".join(
            [
                published_at,
                difficulty_display_label(history_entry.get("difficulty")),
                verification_display_label(history_entry.get("verification_status")),
                f"Score {int(history_entry.get('score', 0) or 0)}",
                f"Coins {int(history_entry.get('coins', 0) or 0)}",
                f"Time {format_play_time(history_entry.get('play_time_seconds', 0) or 0)}",
            ]
        )

    def _open_leaderboard_run_detail(self, submission_id: str) -> None:
        profile = self._leaderboard_profile or {}
        for history_entry in list(profile.get("history") or []):
            if str(history_entry.get("submission_id") or "") != str(submission_id):
                continue
            self._leaderboard_selected_run = dict(history_entry)
            self._refresh_leaderboard_run_detail_menu()
            self._set_active_menu(self.leaderboard_run_detail_menu)
            return
        self.audio.play("menuedge", channel="ui")
        self.speaker.speak("Unable to open the selected run.", interrupt=True)

    def _refresh_leaderboard_run_detail_menu(self) -> None:
        run_data = self._leaderboard_selected_run or {}
        published_at = str(run_data.get("published_at") or "").replace("T", " ")[:19]
        verification_reasons = list(run_data.get("verification_reasons") or [])
        self.leaderboard_run_detail_menu.title = "Published Run"
        items = [
            MenuItem(f"Verification: {verification_display_label(run_data.get('verification_status'))}", "leaderboard_run_info"),
            MenuItem(f"Difficulty: {difficulty_display_label(run_data.get('difficulty'))}", "leaderboard_run_info"),
            MenuItem(f"Score: {int(run_data.get('score', 0) or 0)}", "leaderboard_run_info"),
            MenuItem(f"Coins: {int(run_data.get('coins', 0) or 0)}", "leaderboard_run_info"),
            MenuItem(f"Play Time: {format_play_time(run_data.get('play_time_seconds', 0) or 0)}", "leaderboard_run_info"),
            MenuItem(f"Distance: {int(run_data.get('distance_meters', 0) or 0)} meters", "leaderboard_run_info"),
            MenuItem(f"Clean Escapes: {int(run_data.get('clean_escapes', 0) or 0)}", "leaderboard_run_info"),
            MenuItem(f"Revives Used: {int(run_data.get('revives_used', 0) or 0)}", "leaderboard_run_info"),
            MenuItem(self._powerup_usage_label(run_data.get("powerup_usage")), "leaderboard_run_info"),
            MenuItem(f"Death Reason: {run_data.get('death_reason') or 'Run ended.'}", "leaderboard_run_info"),
            MenuItem(f"Game Version: {run_data.get('game_version') or 'unknown'}", "leaderboard_run_info"),
            MenuItem(f"Published At: {published_at}", "leaderboard_run_info"),
        ]
        for reason in verification_reasons:
            items.append(MenuItem(f"Review Note: {reason}", "leaderboard_run_info"))
        items.append(MenuItem("Back", "back"))
        self.leaderboard_run_detail_menu.items = items

    def _prompt_for_leaderboard_credentials(self) -> tuple[str, str] | None:
        try:
            result = prompt_for_credentials(
                caption="Subway Surfers Blind Leaderboard",
                message="Enter your user name and password. If the account does not exist yet, it will be created.",
                username_hint=self._leaderboard_username,
            )
        except CredentialPromptCancelled:
            return None
        except NativeCredentialPromptError as exc:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(str(exc), interrupt=True)
            return None
        username = result.username.strip()
        password = result.password
        if not username or not password:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak("User name and password are required.", interrupt=True)
            return None
        return username, password

    def _prompt_and_authenticate_leaderboard_account(self) -> None:
        credentials = self._prompt_for_leaderboard_credentials()
        if credentials is None:
            return
        username, password = credentials

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.login(username=username, password=password)
            result["account_sync"] = self.leaderboard_client.sync_account(self._claimed_leaderboard_reward_ids())
            result["just_connected"] = just_connected
            return result

        self._start_leaderboard_operation(
            "leaderboard_auth",
            "Leaderboard",
            "Connecting to server...",
            worker,
            return_menu=self.options_menu,
        )

    def _logout_leaderboard_account(self) -> None:
        self.leaderboard_client.logout()
        self._leaderboard_username = ""
        self.settings["leaderboard_username"] = ""
        self._leaderboard_entries = []
        self._leaderboard_total_players = 0
        self._leaderboard_profile = None
        self._leaderboard_selected_run = None
        self._leaderboard_profile_history_count = 0
        self._leaderboard_cache_loaded_at = 0.0
        self._refresh_options_menu_labels()
        self._persist_settings()
        self._set_active_menu(
            self.options_menu,
            start_index=self._update_option_index("opt_leaderboard_account"),
            play_sound=False,
        )
        self.audio.play("confirm", channel="ui")
        self.speaker.speak("Leaderboard account signed out.", interrupt=True)

    def _publish_latest_game_over_run(self) -> None:
        if not self._leaderboard_is_authenticated():
            self._set_active_menu(self.game_over_menu)
            return
        if self._game_over_publish_state in {"publishing", "published"}:
            return
        submission_payload = self._build_leaderboard_submission_payload()
        self._game_over_publish_state = "publishing"

        def worker() -> dict[str, object]:
            just_connected = self.leaderboard_client.connect()
            result = self.leaderboard_client.submit_score(**submission_payload)
            result["just_connected"] = just_connected
            result["username"] = self.leaderboard_client.principal_username
            return result

        self._start_leaderboard_operation(
            "leaderboard_publish",
            "Leaderboard",
            "Publishing your score...",
            worker,
            return_menu=self.game_over_menu,
        )

    def _build_leaderboard_submission_payload(self) -> dict[str, object]:
        summary = dict(self._game_over_summary)
        return {
            "score": int(summary.get("score", 0) or 0),
            "coins": int(summary.get("coins", 0) or 0),
            "play_time_seconds": int(summary.get("play_time_seconds", 0) or 0),
            "difficulty": str(summary.get("difficulty") or self._difficulty_key()),
            "death_reason": str(summary.get("death_reason") or "Run ended."),
            "distance_meters": int(summary.get("distance_meters", 0) or 0),
            "clean_escapes": int(summary.get("clean_escapes", 0) or 0),
            "revives_used": int(summary.get("revives_used", 0) or 0),
            "powerup_usage": dict(summary.get("powerup_usage") or {}),
        }

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
            self.speaker.speak(
                f"Output device set to {selected_label}.",
                interrupt=True,
            )
            return
        self.speaker.speak(
            f"Requested output device unavailable. Using {selected_label}.",
            interrupt=True,
        )

    def _apply_speaker_settings(self) -> None:
        self.speaker.apply_settings(self.settings)

    def _adjust_selected_option(self, direction: int) -> None:
        if self.active_menu not in {self.options_menu, self.sapi_menu, self.announcements_menu} or direction not in (-1, 1):
            return
        selected_action = self.active_menu.items[self.active_menu.index].action
        if selected_action == "back":
            return
        if selected_action == "opt_sfx":
            current = float(self.settings["sfx_volume"])
            updated = step_volume(current, direction)
            if updated == current:
                self._play_menu_feedback("menuedge")
                return
            self.settings["sfx_volume"] = updated
            self.audio.refresh_volumes()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index("opt_sfx")].label, interrupt=True)
            return
        if selected_action == "opt_music":
            current = float(self.settings["music_volume"])
            updated = step_volume(current, direction)
            if updated == current:
                self._play_menu_feedback("menuedge")
                return
            self.settings["music_volume"] = updated
            self.audio.refresh_volumes()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index("opt_music")].label, interrupt=True)
            return
        if selected_action == "opt_updates":
            self.settings["check_updates_on_startup"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index("opt_updates")].label, interrupt=True)
            return
        if selected_action == "opt_output":
            self._play_menu_feedback("confirm")
            self._cycle_output_device_in_options(direction)
            return
        if selected_action == "opt_menu_hrtf":
            self.settings["menu_sound_hrtf"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index("opt_menu_hrtf")].label, interrupt=True)
            return
        if selected_action == "opt_speech":
            self._play_menu_feedback("confirm")
            self.settings["speech_enabled"] = direction > 0
            self._refresh_options_menu_labels()
            label = self.options_menu.items[self._update_option_index("opt_speech")].label
            if self.settings["speech_enabled"]:
                self._apply_speaker_settings()
                self.speaker.speak(label, interrupt=True)
            else:
                self.speaker.speak(label, interrupt=True)
                self._apply_speaker_settings()
            return
        if selected_action == "opt_sapi":
            self.settings["sapi_speech_enabled"] = direction > 0
            self._apply_speaker_settings()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[0].label, interrupt=True)
            return
        if selected_action == "opt_sapi_volume":
            current = int(self.settings.get("sapi_volume", 100))
            updated = step_int(current, direction, SAPI_VOLUME_MIN, SAPI_VOLUME_MAX)
            if updated == current:
                self._play_menu_feedback("menuedge")
                return
            self.settings["sapi_volume"] = updated
            self._apply_speaker_settings()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[1].label, interrupt=True)
            return
        if selected_action == "opt_sapi_voice":
            selected_voice = self.speaker.cycle_sapi_voice(direction)
            if selected_voice == SAPI_VOICE_UNAVAILABLE_LABEL:
                self._play_menu_feedback("menuedge")
                self.speaker.speak("No SAPI voices available.", interrupt=True)
                return
            self.settings["sapi_voice_id"] = self.speaker.sapi_voice_id or ""
            self._apply_speaker_settings()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[2].label, interrupt=True)
            return
        if selected_action == "opt_sapi_rate":
            current = int(self.settings.get("sapi_rate", 0))
            updated = step_int(current, direction, SAPI_RATE_MIN, SAPI_RATE_MAX)
            if updated == current:
                self._play_menu_feedback("menuedge")
                return
            self.settings["sapi_rate"] = updated
            self._apply_speaker_settings()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[3].label, interrupt=True)
            return
        if selected_action == "opt_sapi_pitch":
            current = int(self.settings.get("sapi_pitch", 0))
            updated = step_int(current, direction, SAPI_PITCH_MIN, SAPI_PITCH_MAX)
            if updated == current:
                self._play_menu_feedback("menuedge")
                return
            self.settings["sapi_pitch"] = updated
            self._apply_speaker_settings()
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self._refresh_sapi_menu_labels()
            self.speaker.speak(self.sapi_menu.items[4].label, interrupt=True)
            return
        if selected_action == "opt_diff":
            order = ["easy", "normal", "hard"]
            current = str(self.settings["difficulty"])
            try:
                current_index = order.index(current)
            except ValueError:
                current_index = order.index("normal")
            self.settings["difficulty"] = order[(current_index + direction) % len(order)]
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(self.options_menu.items[self._update_option_index("opt_diff")].label, interrupt=True)
            return
        if selected_action == "opt_main_menu_descriptions":
            self.settings["main_menu_descriptions_enabled"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(
                self.options_menu.items[self._update_option_index("opt_main_menu_descriptions")].label,
                interrupt=True,
            )
            return
        if selected_action == "opt_exit_confirmation":
            self.settings["confirm_exit_enabled"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_options_menu_labels()
            self.speaker.speak(
                self.options_menu.items[self._update_option_index("opt_exit_confirmation")].label,
                interrupt=True,
            )
            return
        if selected_action == "opt_meters":
            self.settings["meter_announcements_enabled"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_announcements_menu_labels()
            self.speaker.speak(
                self.announcements_menu.items[self._update_announcements_index("opt_meters")].label,
                interrupt=True,
            )
            return
        if selected_action == "opt_coin_counters":
            self.settings["coin_counters_enabled"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_announcements_menu_labels()
            self.speaker.speak(
                self.announcements_menu.items[self._update_announcements_index("opt_coin_counters")].label,
                interrupt=True,
            )
            return
        if selected_action == "opt_quest_changes":
            self.settings["quest_changes_enabled"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_announcements_menu_labels()
            self.speaker.speak(
                self.announcements_menu.items[self._update_announcements_index("opt_quest_changes")].label,
                interrupt=True,
            )
            return
        if selected_action == "opt_pause_on_focus_loss":
            self.settings["pause_on_focus_loss_enabled"] = direction > 0
            self._play_menu_feedback("confirm")
            self._refresh_announcements_menu_labels()
            self.speaker.speak(
                self.announcements_menu.items[self._update_announcements_index("opt_pause_on_focus_loss")].label,
                interrupt=True,
            )
            return

    def start_run(self) -> None:
        ensure_progression_state(self.settings)
        self._sync_character_progress()
        self.state = RunState(running=True)
        self._set_active_menu(None)
        self.player = Player()
        self.player.hoverboards = int(self.settings.get("hoverboards", 0))
        self.obstacles = []
        self.speed_profile = speed_profile_for_difficulty(str(self.settings["difficulty"]))
        self.spatial_audio.reset()
        self.spawn_director.reset()
        self.state.multiplier = 1 + int(self.settings.get("mission_multiplier_bonus", 0)) + score_booster_bonus(
            self.selected_score_boosters
        ) + self._active_character_bonuses.starting_multiplier_bonus + int(self._active_event_profile.get("featured_multiplier_bonus", 0) or 0)
        self.state.speed = self.speed_profile.base_speed
        self._active_run_stats = self._empty_run_stats()
        self._footstep_timer = 0.0
        self._left_foot_next = True
        self._run_rewards_committed = False
        self._near_miss_signatures.clear()
        self._guard_loop_timer = 0.0
        self._last_death_reason = "Run ended."
        self._game_over_publish_state = "idle"
        self._game_over_summary = self._empty_game_over_summary()
        self._magnet_loop_active = False
        self._jetpack_loop_active = False
        self.player.board_extra_jump_available = False
        active_character = selected_character_definition(self.settings)
        active_board = selected_board_definition(self.settings)

        if self.selected_headstarts > 0:
            self.settings["headstarts"] = max(0, int(self.settings.get("headstarts", 0)) - self.selected_headstarts)
            self.player.headstart = headstart_duration_for_uses(self.selected_headstarts)
            self.player.y = 2.8
            self.player.vy = 0.0
            self._start_headstart_audio()
        if self.selected_score_boosters > 0:
            self.settings["score_boosters"] = max(
                0,
                int(self.settings.get("score_boosters", 0)) - self.selected_score_boosters,
            )
            self.audio.play("mission_reward", channel="boost")
            self.speaker.speak(
                f"Score booster active. Multiplier starts at x{self.state.multiplier}.",
                interrupt=False,
            )

        self.audio.play("slide_letters", channel="intro_ui")
        self.audio.play("intro_start", channel="ui")
        if self.selected_headstarts > 0:
            self.audio.play("intro_shake", channel="intro_chase")
            self.audio.play("intro_spray", channel="intro_spray_once")
        self.audio.music_start("gameplay")
        event = self._active_event_profile.get("event")
        event_message = ""
        if event is not None:
            event_label = str(getattr(event, "label", "") or "").strip()
            if self._active_event_profile.get("featured_character_active"):
                event_message = f" {event_label} active with bonus multiplier."
            elif event_label:
                event_message = f" {event_label} active."
        if self.selected_headstarts > 0:
            self.speaker.speak(
                f"Run started. {active_character.name} active. {active_board.name} board selected.{event_message} Headstart active for {self.selected_headstarts} charge{'s' if self.selected_headstarts != 1 else ''}.",
                interrupt=True,
            )
        else:
            self.speaker.speak(
                f"Run started. {active_character.name} active. {active_board.name} board selected.{event_message} Center lane.",
                interrupt=True,
            )

        self.selected_headstarts = 0
        self.selected_score_boosters = 0
        self._refresh_loadout_menu_labels()

    def end_run(self, to_menu: bool = True) -> None:
        self._commit_run_rewards()
        self.state.running = False
        self._stop_headstart_audio()
        self.audio.stop("loop_guard")
        self.audio.stop("loop_magnet")
        self.audio.stop("loop_jetpack")
        self._stop_spatial_audio()
        self.spatial_audio.reset()
        if to_menu:
            self._update_game_over_summary("Returned to main menu")
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
                self.speaker.speak(f"Coins collected: {self.state.coins}.", interrupt=False)
            return
        if key == pygame.K_t:
            self.speaker.speak(f"Play time: {format_play_time(self.state.time)}.", interrupt=False)
            return

        if self.state.paused or self.player.jetpack > 0 or self.player.headstart > 0:
            return

        self.player.lane = normalize_lane(self.player.lane)
        if key == pygame.K_LEFT:
            lane_step = 2 if self.player.hover_active > 0 and selected_board_definition(self.settings).power_key == "zap_sideways" else 1
            target_lane = normalize_lane(self.player.lane - lane_step)
            if target_lane != self.player.lane:
                move_count = abs(target_lane - self.player.lane)
                self.player.lane = target_lane
                self._record_mission_event("dodges", move_count)
                self.audio.play("dodge", pan=lane_to_pan(self.player.lane), channel="move")
                if self.settings.get("announce_lane", True):
                    self.speaker.speak(lane_name(self.player.lane), interrupt=False)
            else:
                self.audio.play("menuedge", channel="ui")
        elif key == pygame.K_RIGHT:
            lane_step = 2 if self.player.hover_active > 0 and selected_board_definition(self.settings).power_key == "zap_sideways" else 1
            target_lane = normalize_lane(self.player.lane + lane_step)
            if target_lane != self.player.lane:
                move_count = abs(target_lane - self.player.lane)
                self.player.lane = target_lane
                self._record_mission_event("dodges", move_count)
                self.audio.play("dodge", pan=lane_to_pan(self.player.lane), channel="move")
                if self.settings.get("announce_lane", True):
                    self.speaker.speak(lane_name(self.player.lane), interrupt=False)
            else:
                self.audio.play("menuedge", channel="ui")
        elif key == pygame.K_UP:
            self._try_jump()
        elif key == pygame.K_DOWN:
            self._try_roll()
        elif key == pygame.K_SPACE:
            self._try_hoverboard()
        elif key == pygame.K_m:
            self.settings["speech_enabled"] = not self.settings["speech_enabled"]
            if self.settings["speech_enabled"]:
                self._apply_speaker_settings()
                self.speaker.speak("Speech enabled", interrupt=True)
            else:
                self.speaker.speak("Speech disabled", interrupt=True)
                self._apply_speaker_settings()

    def _try_jump(self) -> None:
        board = selected_board_definition(self.settings)
        hover_power = board.power_key if self.player.hover_active > 0 else "standard"
        can_double_jump = (
            self.player.hover_active > 0
            and hover_power == "double_jump"
            and self.player.y > 0.01
            and self.player.board_extra_jump_available
            and self.player.jetpack <= 0
            and self.player.headstart <= 0
        )
        if self.player.rolling > 0:
            return
        if self.player.y > 0.01 and not can_double_jump:
            return
        base_jump = 13.0 if self.player.super_sneakers > 0 else 10.5
        if hover_power == "super_jump":
            base_jump += 2.4
        elif hover_power == "smooth_drift":
            base_jump += 1.1
        self.player.vy = base_jump
        self._record_mission_event("jumps")
        if self.player.hover_active > 0 and hover_power == "double_jump":
            if self.player.y <= 0.01:
                self.player.board_extra_jump_available = True
            else:
                self.player.board_extra_jump_available = False
        sound_key = "sneakers_jump" if self.player.super_sneakers > 0 else "jump"
        self.audio.play(sound_key, pan=lane_to_pan(self.player.lane), channel="act")

    def _try_roll(self) -> None:
        if self.player.y > 0.01:
            return
        board = selected_board_definition(self.settings)
        self.player.rolling = 1.05 if self.player.hover_active > 0 and board.power_key == "stay_low" else 0.7
        self._record_mission_event("rolls")
        self.audio.play("roll", pan=lane_to_pan(self.player.lane), channel="act")

    def _try_hoverboard(self) -> None:
        if self.player.hover_active > 0:
            return
        if int(self.state.hoverboards_used) >= HOVERBOARD_MAX_USES_PER_RUN:
            self.speaker.speak(
                f"Hoverboard limit reached. You can use {HOVERBOARD_MAX_USES_PER_RUN} per run.",
                interrupt=False,
            )
            self.audio.play("menuedge", channel="ui")
            return
        if self.player.hoverboards <= 0:
            self.speaker.speak("No hoverboards available.", interrupt=False)
            self.audio.play("menuedge", channel="ui")
            return
        self.player.hoverboards -= 1
        self.settings["hoverboards"] = max(0, int(self.settings.get("hoverboards", 0)) - 1)
        self.state.hoverboards_used += 1
        self.player.hover_active = HOVERBOARD_DURATION + self._active_character_bonuses.hoverboard_duration_bonus
        self.player.board_extra_jump_available = False
        self._record_run_powerup("hoverboard")
        self.audio.play("powerup", channel="act")
        board = selected_board_definition(self.settings)
        if board.power_key == "standard":
            self.speaker.speak(f"{board.name} hoverboard active.", interrupt=False)
        else:
            self.speaker.speak(f"{board.name} hoverboard active. {board.power_label}.", interrupt=False)

    def _update_game(self, delta_time: float) -> None:
        self.player.lane = normalize_lane(self.player.lane)
        self.state.time += delta_time
        base_speed = self.speed_profile.speed_for_elapsed(self.state.time)
        self.state.speed = base_speed + HEADSTART_SPEED_BONUS if self.player.headstart > 0 else base_speed
        active_board = selected_board_definition(self.settings)
        if self.player.hover_active > 0 and active_board.power_key == "super_speed":
            self.state.speed += 3.0
        speed_factor = self.speed_profile.progress(self.state.time)
        self.speaker.set_speed_factor(speed_factor)
        self.state.distance += self.state.speed * delta_time
        self.state.score += (self.state.speed * delta_time) * self._score_multiplier()

        if self.player.jetpack <= 0 and self.player.y <= 0.01 and self.player.rolling <= 0:
            self._footstep_timer -= delta_time
            if self._footstep_timer <= 0:
                self._footstep_timer = 0.33
                self._left_foot_next = not self._left_foot_next
                if self.player.super_sneakers > 0:
                    sound_key = "sneakers_left" if self._left_foot_next else "sneakers_right"
                else:
                    sound_key = "left_foot" if self._left_foot_next else "right_foot"
                if sound_key in self.audio.sounds:
                    self.audio.play(sound_key, pan=lane_to_pan(self.player.lane), channel="foot")
        else:
            self._footstep_timer = 0.0

        if self.player.jetpack <= 0 and self.player.headstart <= 0 and (self.player.y > 0 or self.player.vy != 0):
            gravity = 18.0 if self.player.hover_active > 0 and active_board.power_key == "smooth_drift" else 25.0
            self.player.vy -= gravity * delta_time
            self.player.y = max(0.0, self.player.y + self.player.vy * delta_time)
            if self.player.y <= 0.0 and self.player.vy < 0:
                self.player.y = 0.0
                self.player.vy = 0.0
                sound_key = "land_h" if self.player.super_sneakers > 0 or self.player.pogo_active > 0 else "landing"
                self.audio.play(sound_key, pan=lane_to_pan(self.player.lane), channel="act")

        if self.player.rolling > 0:
            self.player.rolling = max(0.0, self.player.rolling - delta_time)

        self._tick_powerups(delta_time)
        self._spawn_things(delta_time)

        for obstacle in self.obstacles:
            obstacle.z -= self.state.speed * delta_time

        self._update_near_miss_audio()

        if self.player.jetpack > 0 or self.player.headstart > 0:
            self._stop_spatial_audio()
            self.spatial_audio.reset()
        else:
            self.spatial_audio.update(delta_time, self.player.lane, self.state.speed, self.obstacles, self.audio, self.speaker)

        self._handle_obstacles()
        self.obstacles = [obstacle for obstacle in self.obstacles if obstacle.z > -5]

        milestone = int(self.state.distance // 250)
        if self._meters_enabled() and milestone > self.state.milestone:
            self.state.milestone = milestone
            self.audio.play("mission_reward", channel="ui")
            self.speaker.speak(f"{milestone * 250:.0f} meters", interrupt=False)

    def _score_multiplier(self) -> int:
        multiplier = self.state.multiplier
        if self.player.mult2x > 0:
            multiplier *= 2
        return multiplier

    def _tick_powerups(self, delta_time: float) -> None:
        def decay(attribute: str) -> None:
            current_value = getattr(self.player, attribute)
            if current_value > 0:
                setattr(self.player, attribute, max(0.0, current_value - delta_time))

        previous_headstart = self.player.headstart
        decay("headstart")
        if previous_headstart > 0 and self.player.headstart <= 0:
            self._stop_headstart_audio()
            self.player.y = 0.0
            self.player.vy = 0.0
            self.audio.play("land_h", channel="headstart_end")
            self.audio.play("powerup", channel="headstart_reward")
            self._apply_power_reward(pick_headstart_end_reward(), from_headstart=True)
        elif previous_headstart <= 0 and self.player.headstart > 0:
            self._start_headstart_audio()

        if self.player.headstart <= 0 and self.player.jetpack <= 0:
            decay("hover_active")
        if self.player.hover_active <= 0:
            self.player.board_extra_jump_available = False
        if self.player.jetpack <= 0 and self.player.headstart <= 0:
            decay("super_sneakers")

        previous_magnet = self.player.magnet
        if self.player.jetpack <= 0 and self.player.headstart <= 0:
            decay("magnet")
        if previous_magnet > 0 and self.player.magnet <= 0:
            self.audio.stop("loop_magnet")
            self._magnet_loop_active = False
            self.audio.play("powerdown", channel="act")
            self.speaker.speak("Magnet expired.", interrupt=False)
        elif self.player.magnet > 0 and not self._magnet_loop_active:
            self.audio.play("magnet_loop", loop=True, channel="loop_magnet")
            self._magnet_loop_active = True

        previous_jetpack = self.player.jetpack
        decay("jetpack")
        if previous_jetpack > 0 and self.player.jetpack <= 0:
            self.audio.stop("loop_jetpack")
            self._jetpack_loop_active = False
            self.audio.play("powerdown", channel="act")
            self.speaker.speak("Jetpack expired.", interrupt=False)
        elif self.player.jetpack > 0 and not self._jetpack_loop_active:
            self.audio.play("jetpack_loop", loop=True, channel="loop_jetpack")
            self._jetpack_loop_active = True

        previous_multiplier = self.player.mult2x
        if self.player.jetpack <= 0 and self.player.headstart <= 0:
            decay("mult2x")
        if previous_multiplier > 0 and self.player.mult2x <= 0:
            self.audio.play("powerdown", channel="act")
            self.speaker.speak("Score boost expired.", interrupt=False)

        previous_pogo = self.player.pogo_active
        decay("pogo_active")
        if previous_pogo > 0 and self.player.pogo_active <= 0:
            self.audio.play("powerdown", channel="act")
            self.speaker.speak("Pogo stick expired.", interrupt=False)
        elif self.player.pogo_active > 0:
            self._launch_pogo_bounce()

        self._guard_loop_timer = max(0.0, self._guard_loop_timer - delta_time)
        if self.state.running and not self.state.paused and self._guard_loop_timer > 0:
            self.audio.play("guard_loop", loop=True, channel="loop_guard", gain=0.72)
        else:
            self.audio.stop("loop_guard")

    def _spawn_things(self, delta_time: float) -> None:
        self.state.next_spawn -= delta_time
        self.state.next_coinline -= delta_time
        self.state.next_support -= delta_time
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
                    minimum_gap = 1.05 if difficulty == "easy" else 0.85
                    self.state.next_spawn = max(
                        minimum_gap,
                        self.spawn_director.next_encounter_gap(progress, difficulty=difficulty),
                    )

        if self.state.next_coinline <= 0:
            lane = self.spawn_director.choose_coin_lane(self.player.lane)
            self._spawn_coin_line(
                lane,
                start_distance=self.spawn_director.base_spawn_distance(
                    progress,
                    self.state.speed,
                    difficulty=difficulty,
                )
                - 7.5,
            )
            self.state.next_coinline = max(1.55, self.spawn_director.next_coin_gap(progress, difficulty=difficulty))

        if self.state.next_support <= 0:
            kind = self._choose_support_spawn_kind()
            lane = self.spawn_director.support_lane(self.player.lane)
            distance = self.spawn_director.base_spawn_distance(
                progress,
                self.state.speed,
                difficulty=difficulty,
            ) + 1.5
            self._spawn_support_collectible(kind, lane, distance)
            self.state.next_support = max(5.5, self.spawn_director.next_support_gap(progress, difficulty=difficulty))

    def _spawn_pattern(self, pattern: RoutePattern, base_distance: float) -> None:
        for entry in pattern.entries:
            self.obstacles.append(Obstacle(kind=entry.kind, lane=entry.lane, z=base_distance + entry.z_offset))

    def _choose_playable_pattern(self, progress: float, difficulty: str | None = None) -> Optional[tuple[RoutePattern, float]]:
        selected_difficulty = difficulty or self._difficulty_key()
        for pattern in self.spawn_director.candidate_patterns(progress, difficulty=selected_difficulty):
            distance = self.spawn_director.base_spawn_distance(progress, self.state.speed, difficulty=selected_difficulty)
            if not self.spawn_director.pattern_is_playable(
                pattern,
                distance,
                self.obstacles,
                current_lane=self.player.lane,
            ):
                continue
            self.spawn_director.accept_pattern(pattern)
            return pattern, distance
        return None

    def _spawn_coin_line(self, lane: int, start_distance: float) -> None:
        start_distance = max(18.0, start_distance)
        for index in range(6):
            self.obstacles.append(Obstacle(kind="coin", lane=lane, z=start_distance + index * 2.2, value=1))

    def _spawn_support_collectible(self, kind: str, lane: int, distance: float) -> None:
        if kind == "word":
            next_letter = self._next_word_letter()
            if next_letter:
                self.obstacles.append(Obstacle(kind="word", lane=lane, z=distance, label=next_letter))
                return
            kind = "power"
        if kind == "season_token":
            self.obstacles.append(Obstacle(kind="season_token", lane=lane, z=distance, label="S"))
            return
        if kind == "multiplier":
            self.obstacles.append(Obstacle(kind="multiplier", lane=lane, z=distance, label="2X"))
            return
        if kind == "super_box":
            self.obstacles.append(Obstacle(kind="super_box", lane=lane, z=distance, label="?"))
            return
        if kind == "pogo":
            self.obstacles.append(Obstacle(kind="pogo", lane=lane, z=distance, label="P"))
            return
        if kind == "power":
            obstacle_kind = "box" if random.random() < 0.22 else "power"
        else:
            obstacle_kind = kind
        self.obstacles.append(Obstacle(kind=obstacle_kind, lane=lane, z=distance))

    def _handle_obstacles(self) -> None:
        hit_distance = 2.1
        pickup_distance = 2.2

        for obstacle in self.obstacles:
            if obstacle.kind == "coin" and -0.5 < obstacle.z < pickup_distance:
                if self.player.jetpack > 0:
                    self._collect_coin(obstacle)
                    obstacle.z = -999
                elif self.player.headstart > 0:
                    obstacle.z = -999
                elif obstacle.lane == self.player.lane:
                    self._collect_coin(obstacle)
                    obstacle.z = -999
                elif self.player.magnet > 0 and abs(obstacle.lane - self.player.lane) <= 1:
                    self._collect_coin(obstacle)
                    obstacle.z = -999

            if obstacle.kind in ("power", "box", "key", "word", "season_token", "multiplier", "super_box", "pogo") and -0.8 < obstacle.z < 2.4:
                if self.player.jetpack > 0:
                    continue
                if self.player.headstart > 0:
                    obstacle.z = -999
                    continue
                if obstacle.lane == self.player.lane:
                    if obstacle.kind == "power":
                        self._collect_power()
                    elif obstacle.kind == "key":
                        self._collect_key()
                    elif obstacle.kind == "word":
                        self._collect_word_letter(obstacle)
                    elif obstacle.kind == "season_token":
                        self._collect_season_token()
                    elif obstacle.kind == "multiplier":
                        self._collect_multiplier_pickup()
                    elif obstacle.kind == "super_box":
                        self._collect_super_mysterizer()
                    elif obstacle.kind == "pogo":
                        self._collect_pogo_stick()
                    else:
                        self._collect_box()
                    obstacle.z = -999

            if obstacle.kind in ("train", "low", "high", "bush") and -0.8 < obstacle.z < hit_distance:
                if self.player.jetpack > 0 or self.player.headstart > 0 or obstacle.lane != self.player.lane:
                    continue
                if self.player.pogo_active > 0 and self.player.y > 1.0:
                    continue
                if obstacle.kind in ("low", "bush") and self.player.y > 0.6:
                    continue
                if obstacle.kind == "high" and self.player.rolling > 0:
                    continue
                self._on_hit(obstacle.kind)
                obstacle.z = -999

    def _collect_coin(self, obstacle: Obstacle) -> None:
        self._add_run_coins(1)
        self._record_mission_event("coins")
        self.audio.play("coin", pan=lane_to_pan(obstacle.lane), channel="coin")
        announce_every = int(self.settings.get("announce_coins_every", 10) or 0)
        if self._coin_counters_enabled() and announce_every and self.state.coins % announce_every == 0:
            self.speaker.speak(f"{self.state.coins} coins", interrupt=False)

    def _collect_power(self) -> None:
        self._record_mission_event("powerups")
        self.audio.play("powerup", channel="act")
        reward = random.choices(
            ["magnet", "jetpack", "mult2x", "sneakers"],
            weights=[0.35, 0.20, 0.30, 0.15],
            k=1,
        )[0]
        self._apply_power_reward(reward, from_headstart=False)

    def _collect_multiplier_pickup(self) -> None:
        self._record_mission_event("powerups")
        self._record_run_powerup("mult2x")
        self.audio.play("powerup", channel="act")
        self.player.mult2x = max(self.player.mult2x, self._powerup_duration("mult2x"))
        self.speaker.speak("2x multiplier.", interrupt=False)

    def _collect_super_mysterizer(self) -> None:
        self._record_mission_event("boxes")
        self._open_super_mystery_box("Super Mysterizer")

    def _launch_pogo_bounce(self) -> None:
        if self.player.pogo_active <= 0 or self.player.jetpack > 0 or self.player.headstart > 0:
            return
        if self.player.y > 0.01 or self.player.vy > 0.01:
            return
        self.player.rolling = 0.0
        self.player.vy = 14.6
        self.audio.play("sneakers_jump", channel="act")

    def _collect_pogo_stick(self) -> None:
        self._record_mission_event("powerups")
        self._record_run_powerup("pogo")
        self.audio.play("powerup", channel="act")
        self.player.pogo_active = max(self.player.pogo_active, POGO_STICK_DURATION)
        self._launch_pogo_bounce()
        self.speaker.speak("Pogo stick.", interrupt=False)

    def _pick_track_box_reward(self) -> str:
        if self._active_event_profile.get("jackpot_bonus"):
            return random.choices(
                ["coins", "hover", "mult", "key", "headstart", "score_booster", "nothing"],
                weights=[52, 16, 12, 8, 6, 4, 2],
                k=1,
            )[0]
        return pick_mystery_box_reward()

    def _collect_box(self) -> None:
        self._record_mission_event("boxes")
        self._record_achievement_metric("total_boxes_opened", 1)
        reward = self._pick_track_box_reward()
        self.speaker.speak("Opening Mystery Box.", interrupt=True)
        self.audio.play("mystery_box_open", channel="act")
        if reward == "coins":
            gain = random.randint(10, 40)
            self._add_run_coins(gain)
            self.speaker.speak(f"Mystery box: {gain} coins.", interrupt=False)
            self.audio.play("gui_cash", channel="ui")
        elif reward == "hover":
            self.settings["hoverboards"] = int(self.settings.get("hoverboards", 0)) + 1
            self.player.hoverboards += 1
            self.speaker.speak("Mystery box: hoverboard.", interrupt=False)
            self.audio.play("unlock", channel="ui")
        elif reward == "mult":
            self.state.multiplier = min(10, self.state.multiplier + 1)
            self.speaker.speak(f"Mystery box: multiplier {self.state.multiplier}.", interrupt=False)
            self.audio.play("mission_reward", channel="ui")
        elif reward == "key":
            self.settings["keys"] = int(self.settings.get("keys", 0)) + 1
            self.speaker.speak("Mystery box: key.", interrupt=False)
            self.audio.play("unlock", channel="ui")
        elif reward == "headstart":
            self.settings["headstarts"] = int(self.settings.get("headstarts", 0)) + 1
            self.speaker.speak("Mystery box: headstart.", interrupt=False)
            self.audio.play("mystery_combo", channel="ui")
        elif reward == "score_booster":
            self.settings["score_boosters"] = int(self.settings.get("score_boosters", 0)) + 1
            self.speaker.speak("Mystery box: score booster.", interrupt=False)
            self.audio.play("mystery_combo", channel="ui")
        else:
            self.speaker.speak("Mystery box: empty.", interrupt=False)

    def _collect_key(self) -> None:
        self.settings["keys"] = int(self.settings.get("keys", 0)) + 1
        self.audio.play("unlock", channel="ui")
        self.speaker.speak(f"Key collected. Total keys: {self.settings['keys']}.", interrupt=False)

    def _collect_word_letter(self, obstacle: Obstacle) -> None:
        expected_letter = self._next_word_letter()
        if not expected_letter or obstacle.label != expected_letter:
            return
        letter, completed = register_word_letter(self.settings)
        if not letter:
            return
        self.audio.play("slide_letters", channel="ui")
        if completed:
            self.speaker.speak(f"Letter {letter}.", interrupt=False)
            self._complete_word_hunt()
            return
        remaining_letters = len(self._remaining_word_letters())
        self.speaker.speak(f"Letter {letter}. {remaining_letters} letters left.", interrupt=False)

    def _collect_season_token(self) -> None:
        tokens, next_threshold = register_season_token(self.settings)
        self._record_achievement_metric("total_season_tokens", 1)
        self.audio.play("coin_gui", channel="ui")
        if can_claim_season_reward(self.settings):
            self.speaker.speak("Season token. Reward unlocked.", interrupt=False)
            self._claim_season_reward()
            return
        if next_threshold is None:
            self.speaker.speak(f"Season token. Total {tokens}.", interrupt=False)
            return
        self.speaker.speak(f"Season token. {tokens} of {next_threshold}.", interrupt=False)

    def _activate_magnet(self, duration: float) -> None:
        was_inactive = self.player.magnet <= 0
        self.player.magnet = max(self.player.magnet, float(duration))
        if was_inactive and self.player.jetpack <= 0 and self.player.headstart <= 0:
            self.audio.play("magnet_loop", loop=True, channel="loop_magnet")

    def _activate_jetpack(self, duration: float) -> None:
        was_inactive = self.player.jetpack <= 0
        self.player.jetpack = max(self.player.jetpack, float(duration))
        self.player.y = 2.0
        self.player.vy = 0.0
        if was_inactive:
            self.audio.play("jetpack_loop", loop=True, channel="loop_jetpack")

    def _character_adjusted_power_duration(self, duration: float) -> float:
        return float(duration) * self._active_character_bonuses.power_duration_multiplier

    def _apply_power_reward(self, reward: str, from_headstart: bool) -> None:
        if reward == "magnet":
            self._record_run_powerup("magnet")
            self._activate_magnet(self._powerup_duration("magnet"))
            message = "Headstart reward: magnet." if from_headstart else "Magnet."
            self.speaker.speak(message, interrupt=False)
            return
        if reward == "jetpack":
            self._record_run_powerup("jetpack")
            self._activate_jetpack(self._powerup_duration("jetpack"))
            self.speaker.speak("Jetpack.", interrupt=False)
            return
        if reward == "mult2x":
            self._record_run_powerup("mult2x")
            self.player.mult2x = max(self.player.mult2x, self._powerup_duration("mult2x"))
            message = "Headstart reward: double score." if from_headstart else "Double score."
            self.speaker.speak(message, interrupt=False)
            return
        if reward == "sneakers":
            self._record_run_powerup("sneakers")
            self.player.super_sneakers = self._powerup_duration("sneakers")
            message = "Headstart reward: super sneakers." if from_headstart else "Super sneakers."
            self.speaker.speak(message, interrupt=False)

    def _queue_revive_or_finish(self) -> None:
        if int(self.state.revives_used) >= REVIVE_MAX_USES_PER_RUN:
            self._finish_run_loss()
            return
        cost = revive_cost(self.state.revives_used)
        if int(self.settings.get("keys", 0)) < cost:
            self._finish_run_loss()
            return
        self.state.paused = True
        self.audio.play("guard_catch", channel="act2")
        self.audio.play("gui_close", channel="ui")
        self._refresh_revive_menu_label()
        self._set_active_menu(self.revive_menu)
        self.speaker.speak(
            f"You can revive for {cost} key{'s' if cost != 1 else ''}.",
            interrupt=True,
        )

    def _revive_run(self) -> None:
        if int(self.state.revives_used) >= REVIVE_MAX_USES_PER_RUN:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak(
                f"Revive limit reached. Only {REVIVE_MAX_USES_PER_RUN} revives work in one run.",
                interrupt=True,
            )
            self._finish_run_loss("Run ended after crash")
            return
        cost = revive_cost(self.state.revives_used)
        owned = int(self.settings.get("keys", 0))
        if owned < cost:
            self.audio.play("menuedge", channel="ui")
            self.speaker.speak("Not enough keys.", interrupt=True)
            return
        self.settings["keys"] = owned - cost
        self.state.revives_used += 1
        self.state.paused = False
        self.player.stumbles = 0
        self.player.rolling = 0.0
        self.player.y = 0.0
        self.player.vy = 0.0
        self.player.hover_active = max(self.player.hover_active, 3.5)
        self._guard_loop_timer = 0.0
        self._set_active_menu(None)
        self.audio.play("unlock", channel="ui")
        self.audio.play("powerup", channel="act")
        self.speaker.speak("Revived. Temporary shield active.", interrupt=True)

    def _finish_run_loss(self, death_reason: Optional[str] = None) -> None:
        self.state.paused = False
        self._stop_spatial_audio()
        self.audio.play("kick", channel="player_kick")
        self.audio.play("death_hitcam", channel="player_death_cam")
        self.audio.play("death_bodyfall", channel="player_death_fall")
        self.audio.play("death", channel="act")
        self.audio.play("guard_catch", channel="act2")
        summary_reason = death_reason or self._last_death_reason or "Run ended after crash"
        self.speaker.speak(f"Run over. Score {int(self.state.score)}. {summary_reason}.", interrupt=True)
        self._commit_run_rewards()
        self.audio.stop("loop_guard")
        self.audio.stop("loop_magnet")
        self.audio.stop("loop_jetpack")
        self._stop_spatial_audio()
        self.spatial_audio.reset()
        self._open_game_over_dialog(summary_reason)

    def _stop_spatial_audio(self) -> None:
        for lane in LANES:
            self.audio.stop(f"spatial_{lane}")

    @staticmethod
    def _stumble_sound_for_variant(variant: str) -> str:
        return {
            "train": "stumble_side",
            "bush": "stumble_bush",
            "low": "stumble",
            "high": "stumble",
        }.get(variant, "stumble")

    def _on_hit(self, variant: str = "train") -> None:
        if self.player.hover_active > 0:
            self.player.hover_active = 0.0
            self.audio.play("crash", channel="act")
            self.audio.play("powerdown", channel="act2")
            self.speaker.speak("Hoverboard destroyed.", interrupt=True)
            return

        self._last_death_reason = self._death_reason_for_variant(variant)
        self.player.stumbles += 1
        if self.player.stumbles >= 2:
            self._guard_loop_timer = 0.0
            self._queue_revive_or_finish()
            return

        self._guard_loop_timer = GUARD_LOOP_DURATION
        self.audio.play(self._stumble_sound_for_variant(variant), channel="act")
        self.speaker.speak("You crashed. One chance left.", interrupt=True)

    def _update_near_miss_audio(self) -> None:
        active_signatures: set[tuple[str, int]] = set()
        for obstacle in self.obstacles:
            if obstacle.kind not in {"train", "low", "high", "bush"}:
                continue
            if not (-0.2 <= obstacle.z <= 2.1):
                continue
            lane_delta = abs(obstacle.lane - self.player.lane)
            if lane_delta > 1:
                continue
            if lane_delta == 0:
                if obstacle.kind in {"low", "bush"} and self.player.y > 0.6:
                    pass
                elif obstacle.kind == "high" and self.player.rolling > 0:
                    pass
                else:
                    continue
            signature = (obstacle.kind, id(obstacle))
            active_signatures.add(signature)
            if signature in self._near_miss_signatures:
                continue
            if obstacle.kind == "train":
                sound_key = "swish_long"
            elif lane_delta == 0:
                sound_key = "swish_mid"
            else:
                sound_key = "swish_short"
            self._record_run_metric("clean_escapes")
            self.audio.play(sound_key, channel=f"near_{obstacle.lane}")
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
        start_index = max(0, min(menu.index - (visible_rows // 2), max_start_index))
        visible_items = menu.items[start_index : start_index + visible_rows]
        y_position = list_top
        if menu in {
            self.shop_menu,
            self.me_menu,
            self.character_menu,
            self.character_detail_menu,
            self.board_menu,
            self.board_detail_menu,
            self.item_upgrade_menu,
            self.item_upgrade_detail_menu,
            self.collection_menu,
        }:
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
            top_more = self.font.render("...", True, (160, 160, 160))
            self.screen.blit(top_more, (40, list_top - 28))
        if start_index + len(visible_items) < len(menu.items):
            bottom_more = self.font.render("...", True, (160, 160, 160))
            self.screen.blit(bottom_more, (40, y_position - 8))

        hint_text = self._menu_navigation_hint()
        if menu == self.learn_sounds_menu:
            description_lines = textwrap.wrap(self._learn_sound_description, width=62)[:3]
            description_top = min(height - 132, y_position + 18)
            prompt_surface = self.font.render("Select a sound to hear its gameplay cue.", True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, description_top))
            for line_index, line in enumerate(description_lines):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, description_top + 32 + (line_index * 26)))
            hint_text = self._menu_navigation_hint()
        elif menu == self.update_menu:
            description_lines = textwrap.wrap(self._update_status_message, width=62)[:2]
            release_note_lines = textwrap.wrap(self._update_release_notes, width=62)[:5]
            description_top = min(height - 176, y_position + 14)
            prompt_surface = self.font.render("Update required before you can continue.", True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, description_top))
            for line_index, line in enumerate(description_lines):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, description_top + 32 + (line_index * 26)))
            if self._update_progress_stage in {"download", "extract", "ready", "error"}:
                progress_surface = self.font.render(
                    f"Status: {self._update_progress_message or self._update_status_message}",
                    True,
                    (190, 210, 190) if self._update_progress_stage == "ready" else (180, 180, 180),
                )
                self.screen.blit(progress_surface, (40, description_top + 88))
                percent_surface = self.font.render(
                    f"Progress: {int(self._update_progress_percent)}%",
                    True,
                    (220, 220, 120),
                )
                self.screen.blit(percent_surface, (40, description_top + 116))
                notes_top = description_top + 150
            else:
                notes_top = description_top + 88
            notes_label_surface = self.font.render("Release Notes:", True, (205, 205, 205))
            self.screen.blit(notes_label_surface, (40, notes_top))
            for line_index, line in enumerate(release_note_lines):
                line_surface = self.font.render(line, True, (180, 180, 180))
                self.screen.blit(line_surface, (40, notes_top + 28 + (line_index * 24)))
            hint_text = self._menu_navigation_hint()
        elif menu == self.help_topic_menu and self._selected_help_topic is not None:
            prompt_surface = self.font.render("Use Up and Down to select a line. Press Enter to copy it. Copy All is at the end.", True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, max(height - 100, y_position + 18)))
            hint_text = self._menu_navigation_hint()
        elif menu == self.whats_new_menu and self._selected_info_dialog is not None:
            prompt_surface = self.font.render("Use Up and Down to select a line. Press Enter to copy it. Copy All is at the end.", True, (205, 205, 205))
            self.screen.blit(prompt_surface, (40, max(height - 100, y_position + 18)))
            hint_text = self._menu_navigation_hint()
        elif menu == self.main_menu:
            selected_description = self._selected_main_menu_description()
            if selected_description:
                description_lines = textwrap.wrap(selected_description, width=62)[:3]
                description_top = min(height - 132, y_position + 18)
                prompt_surface = self.font.render("Selected item", True, (205, 205, 205))
                self.screen.blit(prompt_surface, (40, description_top))
                for line_index, line in enumerate(description_lines):
                    line_surface = self.font.render(line, True, (180, 180, 180))
                    self.screen.blit(line_surface, (40, description_top + 32 + (line_index * 26)))
        elif menu in {self.options_menu, self.sapi_menu, self.announcements_menu}:
            hint_text = f"{self._menu_navigation_hint()} {self._option_adjustment_hint()}"
        elif menu in {self.keyboard_bindings_menu, self.controller_bindings_menu} and self._binding_capture is not None:
            capture_prompt = (
                f"Press a key for {action_label(self._binding_capture.action_key)}. Escape cancels."
                if self._binding_capture.device == "keyboard"
                else f"Press a controller input for {action_label(self._binding_capture.action_key)}. Escape cancels."
            )
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
            if obstacle.kind == "coin":
                color = (240, 200, 40)
                size = max(8, size // 2)
            elif obstacle.kind == "power":
                color = (60, 200, 220)
            elif obstacle.kind == "box":
                color = (160, 100, 220)
            elif obstacle.kind == "key":
                color = (80, 220, 255)
                size = max(10, size // 2)
            elif obstacle.kind == "word":
                color = (250, 235, 90)
                size = max(12, size // 2)
            elif obstacle.kind == "season_token":
                color = (255, 145, 60)
                size = max(12, size // 2)
            elif obstacle.kind == "multiplier":
                color = (255, 210, 70)
                size = max(14, size // 2)
            elif obstacle.kind == "super_box":
                color = (245, 120, 255)
                size = max(14, size // 2)
            elif obstacle.kind == "pogo":
                color = (110, 235, 210)
                size = max(14, size // 2)
            elif obstacle.kind == "high":
                color = (220, 120, 60)
            elif obstacle.kind == "low":
                color = (60, 220, 120)
            elif obstacle.kind == "bush":
                color = (40, 160, 60)
            elif obstacle.kind == "train":
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

        hud_parts = [
            f"Score: {int(self.state.score)}",
            f"Multiplier: x{self._score_multiplier()}",
            f"Speed: {self.state.speed:.1f}",
            f"Boards: {self.player.hoverboards}",
            f"Keys: {int(self.settings.get('keys', 0))}",
        ]
        if self._coin_counters_enabled():
            hud_parts.insert(0, f"Coins: {self.state.coins}")
        hud = "   ".join(hud_parts)
        if self.player.hover_active > 0:
            hud += "   [Hoverboard]"
        if self.player.headstart > 0:
            hud += "   [Headstart]"
        if self.player.magnet > 0:
            hud += "   [Magnet]"
        if self.player.jetpack > 0:
            hud += "   [Jetpack]"
        if self.player.mult2x > 0:
            hud += "   [2x]"
        if self.player.super_sneakers > 0:
            hud += "   [Super Sneakers]"
        hud_surface = self.font.render(hud, True, (230, 230, 230))
        self.screen.blit(hud_surface, (15, 10))

        if self._quest_changes_enabled():
            next_threshold = next_season_reward_threshold(self.settings)
            word = self._current_word()
            found_letters = str(self.settings.get("word_hunt_letters", ""))
            season_progress = (
                f"{int(self.settings.get('season_tokens', 0))}/{next_threshold}"
                if next_threshold is not None
                else f"{int(self.settings.get('season_tokens', 0))}/done"
            )
            meta_hud = (
                f"{self._mission_status_text()}   "
                f"Word Hunt: {found_letters or '-'} / {word}   "
                f"Season Hunt: {season_progress}"
            )
            meta_surface = self.font.render(meta_hud, True, (205, 205, 205))
            self.screen.blit(meta_surface, (15, 36))

        if self.state.paused:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            self.screen.blit(overlay, (0, 0))
