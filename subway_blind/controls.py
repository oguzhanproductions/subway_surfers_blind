from __future__ import annotations

import copy
import ctypes
from dataclasses import dataclass
import locale
import os
from typing import Any

import pygame

try:
    from pygame._sdl2 import controller as sdl_controller
except Exception:
    sdl_controller = None

try:
    from babel import Locale as BabelLocale
except Exception:
    BabelLocale = None


MENU_CONTEXT = "menu"
GAME_CONTEXT = "game"
XBOX_FAMILY = "xbox"
PLAYSTATION_FAMILY = "playstation"
GENERIC_FAMILY = "generic"
CONTROLLER_FAMILIES = (XBOX_FAMILY, PLAYSTATION_FAMILY, GENERIC_FAMILY)
AXIS_CAPTURE_THRESHOLD = 0.7
AXIS_RELEASE_THRESHOLD = 0.45
UNASSIGNED_LABEL = "Unassigned"
KEYBOARD_MODIFIER_MASK = pygame.KMOD_SHIFT | pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META
BUFFER_JUMP_FIRST_KEY = -10001
BUFFER_JUMP_LAST_KEY = -10002
BUFFER_SHORTCUT_CANDIDATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("ö", "ç"),
    (";", "'"),
    ("ş", "i"),
    (",", "."),
    ("[", "]"),
    ("-", "="),
)
WINDOWS_LAYOUT_LABELS: dict[str, str] = {
    "00000409": "US QWERTY",
    "00000809": "UK QWERTY",
    "00000407": "German QWERTZ",
    "0000040C": "French AZERTY",
    "00000410": "Italian QWERTY",
    "0000040A": "Spanish QWERTY",
    "0000041F": "Turkish Q",
    "0001041F": "Turkish F",
    "00000419": "Russian JCUKEN",
}
WINDOWS_LAYOUT_FALLBACK_LABELS: dict[str, str] = {
    "tr": "Turkish",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "ru": "Russian",
}

@dataclass(frozen=True)
class InputActionDefinition:
    key: str
    label: str
    context: str
    target_key: int
    keyboard_default: int | None
    controller_default: str


@dataclass
class ConnectedController:
    instance_id: int
    name: str
    family: str
    controller: Any


@dataclass(frozen=True)
class KeyboardLayoutInfo:
    signature: str
    locale_code: str
    locale_label: str
    layout_code: str
    layout_label: str


KeyboardBindingValue = int | dict[str, object] | None


ACTION_DEFINITIONS: tuple[InputActionDefinition, ...] = (
    InputActionDefinition("menu_up", "Menu Up", MENU_CONTEXT, pygame.K_UP, pygame.K_UP, "button:dpad_up"),
    InputActionDefinition("menu_down", "Menu Down", MENU_CONTEXT, pygame.K_DOWN, pygame.K_DOWN, "button:dpad_down"),
    InputActionDefinition("menu_confirm", "Confirm", MENU_CONTEXT, pygame.K_RETURN, pygame.K_RETURN, "button:a"),
    InputActionDefinition("menu_back", "Back", MENU_CONTEXT, pygame.K_ESCAPE, pygame.K_ESCAPE, "button:b"),
    InputActionDefinition(
        "menu_buffer_previous",
        "Buffer Previous Item",
        MENU_CONTEXT,
        pygame.K_PAGEUP,
        None,
        "button:leftshoulder",
    ),
    InputActionDefinition(
        "menu_buffer_next",
        "Buffer Next Item",
        MENU_CONTEXT,
        pygame.K_PAGEDOWN,
        None,
        "button:rightshoulder",
    ),
    InputActionDefinition(
        "menu_buffer_delete",
        "Delete Buffer Item",
        MENU_CONTEXT,
        pygame.K_DELETE,
        pygame.K_DELETE,
        "button:y",
    ),
    InputActionDefinition(
        "menu_buffer_home",
        "Buffer Jump To First",
        MENU_CONTEXT,
        BUFFER_JUMP_FIRST_KEY,
        None,
        "button:leftstick",
    ),
    InputActionDefinition(
        "menu_buffer_end",
        "Buffer Jump To Last",
        MENU_CONTEXT,
        BUFFER_JUMP_LAST_KEY,
        None,
        "button:rightstick",
    ),
    InputActionDefinition(
        "option_decrease",
        "Option Decrease",
        MENU_CONTEXT,
        pygame.K_LEFT,
        pygame.K_LEFT,
        "button:dpad_left",
    ),
    InputActionDefinition(
        "option_increase",
        "Option Increase",
        MENU_CONTEXT,
        pygame.K_RIGHT,
        pygame.K_RIGHT,
        "button:dpad_right",
    ),
    InputActionDefinition("game_move_left", "Move Left", GAME_CONTEXT, pygame.K_LEFT, pygame.K_LEFT, "axis:leftx:-1"),
    InputActionDefinition("game_move_right", "Move Right", GAME_CONTEXT, pygame.K_RIGHT, pygame.K_RIGHT, "axis:leftx:1"),
    InputActionDefinition("game_jump", "Jump", GAME_CONTEXT, pygame.K_UP, pygame.K_UP, "button:a"),
    InputActionDefinition("game_roll", "Roll", GAME_CONTEXT, pygame.K_DOWN, pygame.K_DOWN, "button:b"),
    InputActionDefinition("game_hoverboard", "Activate Hoverboard", GAME_CONTEXT, pygame.K_SPACE, pygame.K_SPACE, "button:x"),
    InputActionDefinition("game_pause", "Pause", GAME_CONTEXT, pygame.K_ESCAPE, pygame.K_ESCAPE, "button:start"),
    InputActionDefinition("game_toggle_speech", "Toggle Speech", GAME_CONTEXT, pygame.K_m, pygame.K_m, "button:y"),
)
ACTION_DEFINITIONS_BY_KEY = {definition.key: definition for definition in ACTION_DEFINITIONS}
ACTION_ORDER = tuple(definition.key for definition in ACTION_DEFINITIONS)
KEYBOARD_ACTION_ORDER = ACTION_ORDER
CONTROLLER_ACTION_ORDER = ACTION_ORDER

BUTTON_TOKEN_TO_CODE = {
    "a": pygame.CONTROLLER_BUTTON_A,
    "b": pygame.CONTROLLER_BUTTON_B,
    "x": pygame.CONTROLLER_BUTTON_X,
    "y": pygame.CONTROLLER_BUTTON_Y,
    "back": pygame.CONTROLLER_BUTTON_BACK,
    "start": pygame.CONTROLLER_BUTTON_START,
    "guide": pygame.CONTROLLER_BUTTON_GUIDE,
    "leftshoulder": pygame.CONTROLLER_BUTTON_LEFTSHOULDER,
    "rightshoulder": pygame.CONTROLLER_BUTTON_RIGHTSHOULDER,
    "leftstick": pygame.CONTROLLER_BUTTON_LEFTSTICK,
    "rightstick": pygame.CONTROLLER_BUTTON_RIGHTSTICK,
    "dpad_up": pygame.CONTROLLER_BUTTON_DPAD_UP,
    "dpad_down": pygame.CONTROLLER_BUTTON_DPAD_DOWN,
    "dpad_left": pygame.CONTROLLER_BUTTON_DPAD_LEFT,
    "dpad_right": pygame.CONTROLLER_BUTTON_DPAD_RIGHT,
}
BUTTON_CODE_TO_TOKEN = {code: token for token, code in BUTTON_TOKEN_TO_CODE.items()}
AXIS_TOKEN_TO_CODE = {
    "leftx": pygame.CONTROLLER_AXIS_LEFTX,
    "lefty": pygame.CONTROLLER_AXIS_LEFTY,
    "rightx": pygame.CONTROLLER_AXIS_RIGHTX,
    "righty": pygame.CONTROLLER_AXIS_RIGHTY,
    "triggerleft": pygame.CONTROLLER_AXIS_TRIGGERLEFT,
    "triggerright": pygame.CONTROLLER_AXIS_TRIGGERRIGHT,
}
AXIS_CODE_TO_TOKEN = {code: token for token, code in AXIS_TOKEN_TO_CODE.items()}

KEY_LABEL_OVERRIDES = {
    pygame.K_UP: "Up Arrow",
    pygame.K_DOWN: "Down Arrow",
    pygame.K_LEFT: "Left Arrow",
    pygame.K_RIGHT: "Right Arrow",
    pygame.K_RETURN: "Enter",
    pygame.K_KP_ENTER: "Numpad Enter",
    pygame.K_ESCAPE: "Escape",
    pygame.K_SPACE: "Space",
    pygame.K_HOME: "Home",
    pygame.K_END: "End",
    pygame.K_PAGEUP: "Page Up",
    pygame.K_PAGEDOWN: "Page Down",
    pygame.K_DELETE: "Delete",
}
XBOX_BUTTON_LABELS = {
    "a": "A",
    "b": "B",
    "x": "X",
    "y": "Y",
    "back": "View",
    "start": "Menu",
    "guide": "Xbox Button",
    "leftshoulder": "LB",
    "rightshoulder": "RB",
    "leftstick": "Left Stick Press",
    "rightstick": "Right Stick Press",
    "dpad_up": "D-Pad Up",
    "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left",
    "dpad_right": "D-Pad Right",
}
PLAYSTATION_BUTTON_LABELS = {
    "a": "Cross",
    "b": "Circle",
    "x": "Square",
    "y": "Triangle",
    "back": "Create",
    "start": "Options",
    "guide": "PS Button",
    "leftshoulder": "L1",
    "rightshoulder": "R1",
    "leftstick": "L3",
    "rightstick": "R3",
    "dpad_up": "D-Pad Up",
    "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left",
    "dpad_right": "D-Pad Right",
}
GENERIC_BUTTON_LABELS = {
    "a": "South Button",
    "b": "East Button",
    "x": "West Button",
    "y": "North Button",
    "back": "Back",
    "start": "Start",
    "guide": "Guide",
    "leftshoulder": "Left Shoulder",
    "rightshoulder": "Right Shoulder",
    "leftstick": "Left Stick Press",
    "rightstick": "Right Stick Press",
    "dpad_up": "D-Pad Up",
    "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left",
    "dpad_right": "D-Pad Right",
}
AXIS_LABELS = {
    "leftx:-1": "Left Stick Left",
    "leftx:1": "Left Stick Right",
    "lefty:-1": "Left Stick Up",
    "lefty:1": "Left Stick Down",
    "rightx:-1": "Right Stick Left",
    "rightx:1": "Right Stick Right",
    "righty:-1": "Right Stick Up",
    "righty:1": "Right Stick Down",
    "triggerleft:1": "Left Trigger",
    "triggerright:1": "Right Trigger",
}


def _normalize_locale_code(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    normalized = normalized.split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    parts = [part for part in normalized.split("-") if part]
    if not parts:
        return ""
    language = parts[0].lower()
    if len(parts) == 1:
        return language
    region = parts[1].upper()
    rest = parts[2:]
    return "-".join([language, region, *rest])


def _localized_locale_label(locale_code: str) -> str:
    normalized = _normalize_locale_code(locale_code)
    if not normalized:
        return "Unknown Locale"
    if BabelLocale is not None:
        try:
            locale_instance = BabelLocale.parse(normalized, sep="-")
            return str(locale_instance.get_display_name(locale_instance))
        except Exception:
            pass
    return normalized


def _windows_layout_label(layout_code: str, locale_code: str) -> str:
    normalized_layout = str(layout_code or "").upper()
    if normalized_layout in WINDOWS_LAYOUT_LABELS:
        return WINDOWS_LAYOUT_LABELS[normalized_layout]
    language = _normalize_locale_code(locale_code).split("-", 1)[0]
    if language in WINDOWS_LAYOUT_FALLBACK_LABELS:
        return WINDOWS_LAYOUT_FALLBACK_LABELS[language]
    return "Standard Keyboard"


def detect_keyboard_layout_info() -> KeyboardLayoutInfo:
    locale_code = ""
    layout_code = ""
    if os.name == "nt":
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            get_layout = user32.GetKeyboardLayout
            get_layout.argtypes = [ctypes.c_uint]
            get_layout.restype = ctypes.c_void_p
            get_layout_name = user32.GetKeyboardLayoutNameW
            get_layout_name.argtypes = [ctypes.c_wchar_p]
            get_layout_name.restype = ctypes.c_int
            layout_handle = int(get_layout(0) or 0)
            language_id = layout_handle & 0xFFFF
            locale_from_windows = locale.windows_locale.get(language_id, "")
            locale_code = _normalize_locale_code(locale_from_windows)
            layout_buffer = ctypes.create_unicode_buffer(9)
            if int(get_layout_name(layout_buffer)) != 0:
                layout_code = str(layout_buffer.value or "").upper()
        except Exception:
            locale_code = ""
            layout_code = ""
    if not locale_code:
        locale_guess = locale.getlocale()[0] or ""
        locale_code = _normalize_locale_code(locale_guess)
    locale_label = _localized_locale_label(locale_code)
    layout_label = _windows_layout_label(layout_code, locale_code)
    signature = f"{os.name}|{locale_code or 'unknown'}|{layout_code or 'default'}"
    return KeyboardLayoutInfo(
        signature=signature,
        locale_code=locale_code,
        locale_label=locale_label,
        layout_code=layout_code,
        layout_label=layout_label,
    )


def _char_supported_in_active_layout(character: str) -> bool:
    if len(character) != 1:
        return False
    if os.name != "nt":
        return character.isprintable()
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_layout = user32.GetKeyboardLayout
        get_layout.argtypes = [ctypes.c_uint]
        get_layout.restype = ctypes.c_void_p
        vk_scan = user32.VkKeyScanExW
        vk_scan.argtypes = [ctypes.c_wchar, ctypes.c_void_p]
        vk_scan.restype = ctypes.c_short
        layout = get_layout(0)
        if layout is None:
            return character.isprintable()
        return int(vk_scan(character, layout)) != -1
    except Exception:
        return character.isprintable()


def detect_buffer_shortcut_chars() -> dict[str, str]:
    for previous_char, next_char in BUFFER_SHORTCUT_CANDIDATE_PAIRS:
        if _char_supported_in_active_layout(previous_char) and _char_supported_in_active_layout(next_char):
            return {"previous": previous_char, "next": next_char}
    return {"previous": ";", "next": "'"}


def ensure_buffer_shortcut_chars(raw_chars: Any) -> dict[str, str]:
    detected = detect_buffer_shortcut_chars()
    if not isinstance(raw_chars, dict):
        return detected
    previous = str(raw_chars.get("previous", "") or "").strip()[:1]
    next_char = str(raw_chars.get("next", "") or "").strip()[:1]
    if not previous or not next_char or previous == next_char:
        return detected
    if not _char_supported_in_active_layout(previous) or not _char_supported_in_active_layout(next_char):
        return detected
    return {"previous": previous, "next": next_char}


def sync_keyboard_layout_settings(settings: dict[str, Any]) -> bool:
    layout_info = detect_keyboard_layout_info()
    previous_signature = str(settings.get("keyboard_layout_signature", "") or "").strip()
    changed = previous_signature != layout_info.signature
    settings["keyboard_layout_signature"] = layout_info.signature
    settings["keyboard_layout_locale"] = layout_info.locale_code
    settings["keyboard_layout_locale_label"] = layout_info.locale_label
    settings["keyboard_layout_code"] = layout_info.layout_code
    settings["keyboard_layout_name"] = layout_info.layout_label
    if changed:
        settings["buffer_shortcut_chars"] = detect_buffer_shortcut_chars()
    return changed


def _normalize_keyboard_modifier_mask(mask: Any) -> int:
    try:
        normalized = int(mask)
    except Exception:
        return 0
    return normalized & int(KEYBOARD_MODIFIER_MASK)


def _normalize_keyboard_binding_value(value: Any, fallback: int | None) -> KeyboardBindingValue:
    if isinstance(value, int):
        return value
    if value is None:
        return None
    if isinstance(value, dict):
        key = value.get("key")
        modifiers = value.get("modifiers")
        if isinstance(key, int):
            normalized: dict[str, object] = {"key": key, "modifiers": _normalize_keyboard_modifier_mask(modifiers)}
            label = value.get("label")
            if isinstance(label, str) and label.strip():
                normalized["label"] = label.strip()
            return normalized
    return fallback


def _keyboard_binding_matches(binding: KeyboardBindingValue, key: int, modifiers: int) -> bool:
    if isinstance(binding, int):
        return binding == key
    if isinstance(binding, dict):
        binding_key = binding.get("key")
        binding_modifiers = _normalize_keyboard_modifier_mask(binding.get("modifiers"))
        return isinstance(binding_key, int) and binding_key == key and binding_modifiers == _normalize_keyboard_modifier_mask(modifiers)
    return False


def keyboard_binding_label(binding: KeyboardBindingValue) -> str:
    if binding is None:
        return UNASSIGNED_LABEL
    if isinstance(binding, int):
        return keyboard_key_label(binding)
    if isinstance(binding, dict):
        custom_label = binding.get("label")
        if isinstance(custom_label, str) and custom_label.strip():
            return custom_label.strip()
        key = binding.get("key")
        if not isinstance(key, int):
            return UNASSIGNED_LABEL
        modifiers = _normalize_keyboard_modifier_mask(binding.get("modifiers"))
        parts: list[str] = []
        if modifiers & pygame.KMOD_CTRL:
            parts.append("Ctrl")
        if modifiers & pygame.KMOD_ALT:
            parts.append("Alt")
        if modifiers & pygame.KMOD_SHIFT:
            parts.append("Shift")
        if modifiers & pygame.KMOD_META:
            parts.append("Meta")
        parts.append(keyboard_key_label(key))
        return " + ".join(parts)
    return UNASSIGNED_LABEL


def default_keyboard_bindings() -> dict[str, KeyboardBindingValue]:
    return {definition.key: definition.keyboard_default for definition in ACTION_DEFINITIONS}


def default_controller_bindings() -> dict[str, dict[str, str]]:
    template = {definition.key: definition.controller_default for definition in ACTION_DEFINITIONS}
    return {family: copy.deepcopy(template) for family in CONTROLLER_FAMILIES}


def ensure_keyboard_bindings(raw_bindings: Any) -> dict[str, KeyboardBindingValue]:
    defaults = default_keyboard_bindings()
    if not isinstance(raw_bindings, dict):
        return defaults
    normalized: dict[str, KeyboardBindingValue] = {}
    for action in ACTION_ORDER:
        value = raw_bindings.get(action, defaults[action])
        normalized[action] = _normalize_keyboard_binding_value(value, defaults[action])
    legacy_buffer_keys = {
        "menu_buffer_previous": pygame.K_PAGEUP,
        "menu_buffer_next": pygame.K_PAGEDOWN,
        "menu_buffer_home": pygame.K_HOME,
        "menu_buffer_end": pygame.K_END,
    }
    for action, legacy_key in legacy_buffer_keys.items():
        if normalized.get(action) == legacy_key:
            normalized[action] = defaults[action]
    return normalized


def ensure_controller_bindings(raw_bindings: Any) -> dict[str, dict[str, str | None]]:
    defaults = default_controller_bindings()
    if not isinstance(raw_bindings, dict):
        return defaults
    normalized: dict[str, dict[str, str | None]] = {}
    for family in CONTROLLER_FAMILIES:
        family_raw = raw_bindings.get(family, {})
        family_bindings: dict[str, str | None] = {}
        for action in ACTION_ORDER:
            value = family_raw.get(action, defaults[family][action]) if isinstance(family_raw, dict) else defaults[family][action]
            family_bindings[action] = value if (isinstance(value, str) and value) or value is None else defaults[family][action]
        normalized[family] = family_bindings
    return normalized


def family_label(family: str) -> str:
    if family == XBOX_FAMILY:
        return "Xbox Controller"
    if family == PLAYSTATION_FAMILY:
        return "PlayStation Controller"
    return "Generic Controller"


def controller_family_from_name(name: str) -> str:
    lowered = str(name or "").casefold()
    if any(token in lowered for token in ("xbox", "xinput")):
        return XBOX_FAMILY
    if any(token in lowered for token in ("playstation", "dualshock", "dualsense", "wireless controller", "ps4", "ps5")):
        return PLAYSTATION_FAMILY
    return GENERIC_FAMILY


def keyboard_key_label(key: int | None) -> str:
    if key is None:
        return UNASSIGNED_LABEL
    if key in KEY_LABEL_OVERRIDES:
        return KEY_LABEL_OVERRIDES[key]
    key_name = pygame.key.name(key)
    if not key_name:
        return f"Key {key}"
    return key_name.replace("_", " ").title()


def controller_binding_label(binding: str | None, family: str) -> str:
    if not binding:
        return UNASSIGNED_LABEL
    binding_type, _, remainder = binding.partition(":")
    if binding_type == "button":
        labels = GENERIC_BUTTON_LABELS
        if family == XBOX_FAMILY:
            labels = XBOX_BUTTON_LABELS
        elif family == PLAYSTATION_FAMILY:
            labels = PLAYSTATION_BUTTON_LABELS
        return labels.get(remainder, remainder.replace("_", " ").title())
    if binding_type == "axis":
        axis_label = remainder.replace(":", ":")
        return AXIS_LABELS.get(axis_label, remainder.replace(":", " ").replace("_", " ").title())
    return binding.replace(":", " ").replace("_", " ").title()


def action_label(action_key: str) -> str:
    definition = ACTION_DEFINITIONS_BY_KEY.get(action_key)
    return definition.label if definition is not None else action_key


def reassign_keyboard_binding(
    bindings: dict[str, KeyboardBindingValue],
    action_key: str,
    binding: KeyboardBindingValue,
) -> dict[str, KeyboardBindingValue]:
    normalized = ensure_keyboard_bindings(bindings)
    definition = ACTION_DEFINITIONS_BY_KEY[action_key]
    for other_action, other_definition in ACTION_DEFINITIONS_BY_KEY.items():
        if other_action == action_key:
            continue
        if other_definition.context == definition.context and normalized.get(other_action) == binding:
            normalized[other_action] = None
    normalized[action_key] = binding
    return normalized


def reassign_controller_binding(
    bindings: dict[str, dict[str, str | None]],
    family: str,
    action_key: str,
    binding: str,
) -> dict[str, dict[str, str | None]]:
    normalized = ensure_controller_bindings(bindings)
    family_bindings = normalized[family]
    definition = ACTION_DEFINITIONS_BY_KEY[action_key]
    for other_action, other_definition in ACTION_DEFINITIONS_BY_KEY.items():
        if other_action == action_key:
            continue
        if other_definition.context == definition.context and family_bindings.get(other_action) == binding:
            family_bindings[other_action] = None
    family_bindings[action_key] = binding
    return normalized


class ControllerSupport:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.available = sdl_controller is not None
        self.connected: dict[int, ConnectedController] = {}
        self.active_controller_instance_id: int | None = None
        self.last_input_source = "keyboard"
        self._axis_state: set[tuple[int, str]] = set()
        self.settings["keyboard_bindings"] = ensure_keyboard_bindings(self.settings.get("keyboard_bindings"))
        self.settings["controller_bindings"] = ensure_controller_bindings(self.settings.get("controller_bindings"))
        if not self.available:
            return
        try:
            pygame.joystick.init()
            sdl_controller.init()
        except Exception:
            self.available = False
            return
        self.refresh_connected_controllers()

    def refresh_connected_controllers(self) -> None:
        if not self.available:
            self.connected.clear()
            self.active_controller_instance_id = None
            return
        current_ids: set[int] = set()
        for index in range(pygame.joystick.get_count()):
            if not sdl_controller.is_controller(index):
                continue
            try:
                controller = sdl_controller.Controller(index)
                if not controller.get_init():
                    controller.init()
            except Exception:
                continue
            instance_id = int(controller.id)
            current_ids.add(instance_id)
            if instance_id in self.connected:
                continue
            self.connected[instance_id] = ConnectedController(
                instance_id=instance_id,
                name=str(controller.name),
                family=controller_family_from_name(str(controller.name)),
                controller=controller,
            )
        removed_ids = [instance_id for instance_id in self.connected if instance_id not in current_ids]
        for instance_id in removed_ids:
            self.remove_controller(instance_id)
        if self.active_controller_instance_id not in self.connected:
            self.active_controller_instance_id = next(iter(self.connected), None)

    def register_added_controller(self, device_index: int | None) -> ConnectedController | None:
        if not self.available or device_index is None or device_index < 0:
            return None
        try:
            if not sdl_controller.is_controller(device_index):
                return None
            controller = sdl_controller.Controller(device_index)
            if not controller.get_init():
                controller.init()
        except Exception:
            return None
        instance_id = int(controller.id)
        connected = ConnectedController(
            instance_id=instance_id,
            name=str(controller.name),
            family=controller_family_from_name(str(controller.name)),
            controller=controller,
        )
        self.connected[instance_id] = connected
        if self.active_controller_instance_id is None:
            self.active_controller_instance_id = instance_id
        return connected

    def remove_controller(self, instance_id: int | None) -> None:
        if instance_id is None:
            return
        connected = self.connected.pop(int(instance_id), None)
        if connected is not None:
            try:
                connected.controller.quit()
            except Exception:
                pass
        self._axis_state = {entry for entry in self._axis_state if entry[0] != instance_id}
        if self.active_controller_instance_id == instance_id:
            self.active_controller_instance_id = next(iter(self.connected), None)
            if self.active_controller_instance_id is None:
                self.last_input_source = "keyboard"

    def handle_device_removed(self, instance_id: int | None) -> ConnectedController | None:
        connected = self.connected.get(int(instance_id)) if instance_id is not None else None
        self.remove_controller(instance_id)
        return connected

    def active_controller(self) -> ConnectedController | None:
        if self.active_controller_instance_id in self.connected:
            return self.connected[self.active_controller_instance_id]
        if not self.connected:
            return None
        self.active_controller_instance_id = next(iter(self.connected))
        return self.connected[self.active_controller_instance_id]

    def current_controller_family(self) -> str:
        active = self.active_controller()
        return active.family if active is not None else GENERIC_FAMILY

    def current_input_label(self) -> str:
        if self.last_input_source != "controller":
            return "Keyboard"
        active = self.active_controller()
        return family_label(active.family) if active is not None else "Keyboard"

    def current_controller_label(self) -> str:
        active = self.active_controller()
        if active is None:
            return "No controller connected"
        return f"{family_label(active.family)}: {active.name}"

    def controller_binding_for_action(self, action_key: str, family: str | None = None) -> str | None:
        selected_family = family or self.current_controller_family()
        return self.settings["controller_bindings"].get(selected_family, {}).get(action_key)

    def keyboard_binding_for_action(self, action_key: str) -> KeyboardBindingValue:
        return self.settings["keyboard_bindings"].get(action_key)

    def translate_keyboard_key(self, key: int, context: str, modifiers: int = 0) -> int | None:
        self.last_input_source = "keyboard"
        for action_key in ACTION_ORDER:
            definition = ACTION_DEFINITIONS_BY_KEY[action_key]
            if definition.context != context and not (context == GAME_CONTEXT and action_key.startswith("menu_buffer_")):
                continue
            if _keyboard_binding_matches(self.settings["keyboard_bindings"].get(action_key), key, modifiers):
                return definition.target_key
        if context == GAME_CONTEXT and key in (pygame.K_r, pygame.K_t):
            return key
        if context == MENU_CONTEXT and key in (pygame.K_HOME, pygame.K_END):
            return key
        return None

    def translate_controller_event(self, event: pygame.event.Event, context: str) -> list[tuple[int, bool]]:
        if not self.available:
            return []
        if event.type == pygame.CONTROLLERBUTTONDOWN:
            binding = self._button_binding_from_event(event)
            if binding is None:
                return []
            return self._matches_for_binding(binding, event.instance_id, context, True)
        if event.type == pygame.CONTROLLERBUTTONUP:
            binding = self._button_binding_from_event(event)
            if binding is None:
                return []
            return self._matches_for_binding(binding, event.instance_id, context, False)
        if event.type == pygame.CONTROLLERAXISMOTION:
            return self._translate_axis_event(event, context)
        return []

    def capture_controller_binding(self, event: pygame.event.Event) -> str | None:
        if not self.available:
            return None
        if event.type == pygame.CONTROLLERBUTTONDOWN:
            return self._button_binding_from_event(event)
        if event.type == pygame.CONTROLLERAXISMOTION:
            axis_binding = self._axis_binding_from_event(event)
            if axis_binding is not None:
                self._axis_state.add((int(event.instance_id), axis_binding))
            return axis_binding
        return None

    def update_keyboard_binding(self, action_key: str, binding: KeyboardBindingValue) -> None:
        self.settings["keyboard_bindings"] = reassign_keyboard_binding(self.settings["keyboard_bindings"], action_key, binding)

    def update_controller_binding(self, family: str, action_key: str, binding: str) -> None:
        self.settings["controller_bindings"] = reassign_controller_binding(
            self.settings["controller_bindings"],
            family,
            action_key,
            binding,
        )

    def reset_keyboard_bindings(self) -> None:
        self.settings["keyboard_bindings"] = default_keyboard_bindings()

    def reset_controller_bindings(self, family: str) -> None:
        defaults = default_controller_bindings()
        self.settings["controller_bindings"][family] = defaults[family]

    def _matches_for_binding(
        self,
        binding: str,
        instance_id: int,
        context: str,
        pressed: bool,
    ) -> list[tuple[int, bool]]:
        controller = self.connected.get(int(instance_id))
        if controller is None:
            return []
        self.active_controller_instance_id = controller.instance_id
        self.last_input_source = "controller"
        bindings = self.settings["controller_bindings"].get(controller.family, {})
        translated: list[tuple[int, bool]] = []
        for action_key in ACTION_ORDER:
            definition = ACTION_DEFINITIONS_BY_KEY[action_key]
            if definition.context != context and not (context == GAME_CONTEXT and action_key.startswith("menu_buffer_")):
                continue
            if bindings.get(action_key) == binding:
                translated.append((definition.target_key, pressed))
        return translated

    def _translate_axis_event(self, event: pygame.event.Event, context: str) -> list[tuple[int, bool]]:
        axis_token = AXIS_CODE_TO_TOKEN.get(int(event.axis))
        if axis_token is None:
            return []
        instance_id = int(event.instance_id)
        transitions: list[tuple[int, bool]] = []
        for direction in (-1, 1):
            binding = f"axis:{axis_token}:{direction}"
            state_key = (instance_id, binding)
            value = float(event.value) * direction
            engaged = state_key in self._axis_state
            if value >= AXIS_CAPTURE_THRESHOLD and not engaged:
                self._axis_state.add(state_key)
                transitions.extend(self._matches_for_binding(binding, instance_id, context, True))
                continue
            if value <= AXIS_RELEASE_THRESHOLD and engaged:
                self._axis_state.discard(state_key)
                transitions.extend(self._matches_for_binding(binding, instance_id, context, False))
        return transitions

    def _button_binding_from_event(self, event: pygame.event.Event) -> str | None:
        token = BUTTON_CODE_TO_TOKEN.get(int(event.button))
        if token is None:
            return None
        return f"button:{token}"

    def _axis_binding_from_event(self, event: pygame.event.Event) -> str | None:
        axis_token = AXIS_CODE_TO_TOKEN.get(int(event.axis))
        if axis_token is None:
            return None
        value = float(event.value)
        if abs(value) < AXIS_CAPTURE_THRESHOLD:
            return None
        direction = -1 if value < 0 else 1
        return f"axis:{axis_token}:{direction}"

