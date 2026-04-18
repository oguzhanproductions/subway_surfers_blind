from __future__ import annotations
from subway_blind.strings import sx as _sx
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
MENU_CONTEXT = _sx(71)
GAME_CONTEXT = _sx(388)
XBOX_FAMILY = _sx(389)
PLAYSTATION_FAMILY = _sx(390)
GENERIC_FAMILY = _sx(391)
CONTROLLER_FAMILIES = (XBOX_FAMILY, PLAYSTATION_FAMILY, GENERIC_FAMILY)
AXIS_CAPTURE_THRESHOLD = 0.7
AXIS_RELEASE_THRESHOLD = 0.45
UNASSIGNED_LABEL = _sx(392)
KEYBOARD_MODIFIER_MASK = pygame.KMOD_SHIFT | pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META
WINDOWS_LAYOUT_LABELS: dict[str, str] = {_sx(393): _sx(402), _sx(394): _sx(403), _sx(395): _sx(404), _sx(396): _sx(405), _sx(397): _sx(406), _sx(398): _sx(407), _sx(399): _sx(408), _sx(400): _sx(409), _sx(401): _sx(410)}
WINDOWS_LAYOUT_FALLBACK_LABELS: dict[str, str] = {_sx(411): _sx(418), _sx(412): _sx(419), _sx(413): _sx(420), _sx(414): _sx(421), _sx(415): _sx(422), _sx(416): _sx(423), _sx(417): _sx(424)}

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
ACTION_DEFINITIONS: tuple[InputActionDefinition, ...] = (InputActionDefinition(_sx(517), _sx(518), MENU_CONTEXT, pygame.K_UP, pygame.K_UP, _sx(519)), InputActionDefinition(_sx(520), _sx(521), MENU_CONTEXT, pygame.K_DOWN, pygame.K_DOWN, _sx(522)), InputActionDefinition(_sx(523), _sx(524), MENU_CONTEXT, pygame.K_RETURN, pygame.K_RETURN, _sx(525)), InputActionDefinition(_sx(526), _sx(489), MENU_CONTEXT, pygame.K_ESCAPE, pygame.K_ESCAPE, _sx(527)), InputActionDefinition(_sx(528), _sx(529), MENU_CONTEXT, pygame.K_LEFT, pygame.K_LEFT, _sx(530)), InputActionDefinition(_sx(531), _sx(532), MENU_CONTEXT, pygame.K_RIGHT, pygame.K_RIGHT, _sx(533)), InputActionDefinition(_sx(534), _sx(535), GAME_CONTEXT, pygame.K_LEFT, pygame.K_LEFT, _sx(536)), InputActionDefinition(_sx(537), _sx(538), GAME_CONTEXT, pygame.K_RIGHT, pygame.K_RIGHT, _sx(539)), InputActionDefinition(_sx(540), _sx(541), GAME_CONTEXT, pygame.K_UP, pygame.K_UP, _sx(525)), InputActionDefinition(_sx(542), _sx(543), GAME_CONTEXT, pygame.K_DOWN, pygame.K_DOWN, _sx(527)), InputActionDefinition(_sx(544), _sx(545), GAME_CONTEXT, pygame.K_SPACE, pygame.K_SPACE, _sx(546)), InputActionDefinition(_sx(547), _sx(548), GAME_CONTEXT, pygame.K_ESCAPE, pygame.K_ESCAPE, _sx(549)), InputActionDefinition(_sx(550), _sx(551), GAME_CONTEXT, pygame.K_m, pygame.K_m, _sx(552)))
ACTION_DEFINITIONS_BY_KEY = {definition.key: definition for definition in ACTION_DEFINITIONS}
ACTION_ORDER = tuple((definition.key for definition in ACTION_DEFINITIONS))
KEYBOARD_ACTION_ORDER = ACTION_ORDER
CONTROLLER_ACTION_ORDER = ACTION_ORDER
BUTTON_TOKEN_TO_CODE = {_sx(425): pygame.CONTROLLER_BUTTON_A, _sx(426): pygame.CONTROLLER_BUTTON_B, _sx(427): pygame.CONTROLLER_BUTTON_X, _sx(428): pygame.CONTROLLER_BUTTON_Y, _sx(429): pygame.CONTROLLER_BUTTON_BACK, _sx(430): pygame.CONTROLLER_BUTTON_START, _sx(431): pygame.CONTROLLER_BUTTON_GUIDE, _sx(432): pygame.CONTROLLER_BUTTON_LEFTSHOULDER, _sx(433): pygame.CONTROLLER_BUTTON_RIGHTSHOULDER, _sx(434): pygame.CONTROLLER_BUTTON_LEFTSTICK, _sx(435): pygame.CONTROLLER_BUTTON_RIGHTSTICK, _sx(436): pygame.CONTROLLER_BUTTON_DPAD_UP, _sx(437): pygame.CONTROLLER_BUTTON_DPAD_DOWN, _sx(438): pygame.CONTROLLER_BUTTON_DPAD_LEFT, _sx(439): pygame.CONTROLLER_BUTTON_DPAD_RIGHT}
BUTTON_CODE_TO_TOKEN = {code: token for token, code in BUTTON_TOKEN_TO_CODE.items()}
AXIS_TOKEN_TO_CODE = {_sx(440): pygame.CONTROLLER_AXIS_LEFTX, _sx(441): pygame.CONTROLLER_AXIS_LEFTY, _sx(442): pygame.CONTROLLER_AXIS_RIGHTX, _sx(443): pygame.CONTROLLER_AXIS_RIGHTY, _sx(444): pygame.CONTROLLER_AXIS_TRIGGERLEFT, _sx(445): pygame.CONTROLLER_AXIS_TRIGGERRIGHT}
AXIS_CODE_TO_TOKEN = {code: token for token, code in AXIS_TOKEN_TO_CODE.items()}
KEY_LABEL_OVERRIDES = {pygame.K_UP: _sx(446), pygame.K_DOWN: _sx(447), pygame.K_LEFT: _sx(448), pygame.K_RIGHT: _sx(449), pygame.K_RETURN: _sx(450), pygame.K_KP_ENTER: _sx(451), pygame.K_ESCAPE: _sx(452), pygame.K_SPACE: _sx(453), pygame.K_HOME: _sx(454), pygame.K_END: _sx(455), pygame.K_PAGEUP: _sx(456), pygame.K_PAGEDOWN: _sx(457), pygame.K_DELETE: _sx(458)}
XBOX_BUTTON_LABELS = {_sx(425): _sx(459), _sx(426): _sx(460), _sx(427): _sx(461), _sx(428): _sx(462), _sx(429): _sx(463), _sx(430): _sx(464), _sx(431): _sx(465), _sx(432): _sx(466), _sx(433): _sx(467), _sx(434): _sx(468), _sx(435): _sx(469), _sx(436): _sx(470), _sx(437): _sx(471), _sx(438): _sx(472), _sx(439): _sx(473)}
PLAYSTATION_BUTTON_LABELS = {_sx(425): _sx(474), _sx(426): _sx(475), _sx(427): _sx(476), _sx(428): _sx(477), _sx(429): _sx(478), _sx(430): _sx(479), _sx(431): _sx(480), _sx(432): _sx(481), _sx(433): _sx(482), _sx(434): _sx(483), _sx(435): _sx(484), _sx(436): _sx(470), _sx(437): _sx(471), _sx(438): _sx(472), _sx(439): _sx(473)}
GENERIC_BUTTON_LABELS = {_sx(425): _sx(485), _sx(426): _sx(486), _sx(427): _sx(487), _sx(428): _sx(488), _sx(429): _sx(489), _sx(430): _sx(490), _sx(431): _sx(491), _sx(432): _sx(492), _sx(433): _sx(493), _sx(434): _sx(468), _sx(435): _sx(469), _sx(436): _sx(470), _sx(437): _sx(471), _sx(438): _sx(472), _sx(439): _sx(473)}
AXIS_LABELS = {_sx(494): _sx(504), _sx(495): _sx(505), _sx(496): _sx(506), _sx(497): _sx(507), _sx(498): _sx(508), _sx(499): _sx(509), _sx(500): _sx(510), _sx(501): _sx(511), _sx(502): _sx(512), _sx(503): _sx(513)}

def _normalize_locale_code(value: str) -> str:
    normalized = str(value or _sx(2)).strip()
    if not normalized:
        return _sx(2)
    normalized = normalized.split(_sx(292), 1)[0].split(_sx(585), 1)[0].replace(_sx(553), _sx(554))
    parts = [part for part in normalized.split(_sx(554)) if part]
    if not parts:
        return _sx(2)
    language = parts[0].lower()
    if len(parts) == 1:
        return language
    region = parts[1].upper()
    rest = parts[2:]
    return _sx(554).join([language, region, *rest])

def _localized_locale_label(locale_code: str) -> str:
    normalized = _normalize_locale_code(locale_code)
    if not normalized:
        return _sx(555)
    if BabelLocale is not None:
        try:
            locale_instance = BabelLocale.parse(normalized, sep=_sx(554))
            return str(locale_instance.get_display_name(locale_instance))
        except Exception:
            pass
    return normalized

def _windows_layout_label(layout_code: str, locale_code: str) -> str:
    normalized_layout = str(layout_code or _sx(2)).upper()
    if normalized_layout in WINDOWS_LAYOUT_LABELS:
        return WINDOWS_LAYOUT_LABELS[normalized_layout]
    language = _normalize_locale_code(locale_code).split(_sx(554), 1)[0]
    if language in WINDOWS_LAYOUT_FALLBACK_LABELS:
        return WINDOWS_LAYOUT_FALLBACK_LABELS[language]
    return _sx(514)

def detect_keyboard_layout_info() -> KeyboardLayoutInfo:
    locale_code = _sx(2)
    layout_code = _sx(2)
    if os.name == _sx(85):
        try:
            user32 = ctypes.WinDLL(_sx(568), use_last_error=True)
            get_layout = user32.GetKeyboardLayout
            get_layout.argtypes = [ctypes.c_uint]
            get_layout.restype = ctypes.c_void_p
            get_layout_name = user32.GetKeyboardLayoutNameW
            get_layout_name.argtypes = [ctypes.c_wchar_p]
            get_layout_name.restype = ctypes.c_int
            layout_handle = int(get_layout(0) or 0)
            language_id = layout_handle & 65535
            locale_from_windows = locale.windows_locale.get(language_id, _sx(2))
            locale_code = _normalize_locale_code(locale_from_windows)
            layout_buffer = ctypes.create_unicode_buffer(9)
            if int(get_layout_name(layout_buffer)) != 0:
                layout_code = str(layout_buffer.value or _sx(2)).upper()
        except Exception:
            locale_code = _sx(2)
            layout_code = _sx(2)
    if not locale_code:
        locale_guess = locale.getlocale()[0] or _sx(2)
        locale_code = _normalize_locale_code(locale_guess)
    locale_label = _localized_locale_label(locale_code)
    layout_label = _windows_layout_label(layout_code, locale_code)
    signature = _sx(515).format(os.name, locale_code or _sx(578), layout_code or _sx(579))
    return KeyboardLayoutInfo(signature=signature, locale_code=locale_code, locale_label=locale_label, layout_code=layout_code, layout_label=layout_label)

def _char_supported_in_active_layout(character: str) -> bool:
    if len(character) != 1:
        return False
    if os.name != _sx(85):
        return character.isprintable()
    try:
        user32 = ctypes.WinDLL(_sx(568), use_last_error=True)
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

def sync_keyboard_layout_settings(settings: dict[str, Any]) -> bool:
    layout_info = detect_keyboard_layout_info()
    previous_signature = str(settings.get(_sx(356), _sx(2)) or _sx(2)).strip()
    changed = previous_signature != layout_info.signature
    settings[_sx(356)] = layout_info.signature
    settings[_sx(357)] = layout_info.locale_code
    settings[_sx(358)] = layout_info.locale_label
    settings[_sx(359)] = layout_info.layout_code
    settings[_sx(360)] = layout_info.layout_label
    return changed

def _normalize_keyboard_modifier_mask(mask: Any) -> int:
    try:
        normalized = int(mask)
    except Exception:
        return 0
    canonical = 0
    if normalized & pygame.KMOD_SHIFT:
        canonical |= pygame.KMOD_SHIFT
    if normalized & pygame.KMOD_CTRL:
        canonical |= pygame.KMOD_CTRL
    if normalized & pygame.KMOD_ALT:
        canonical |= pygame.KMOD_ALT
    if normalized & pygame.KMOD_META:
        canonical |= pygame.KMOD_META
    return canonical & int(KEYBOARD_MODIFIER_MASK)

def _normalize_keyboard_binding_value(value: Any, fallback: int | None) -> KeyboardBindingValue:
    if isinstance(value, int):
        return value
    if value is None:
        return None
    if isinstance(value, dict):
        key = value.get(_sx(569))
        modifiers = value.get(_sx(570))
        if isinstance(key, int):
            normalized: dict[str, object] = {_sx(569): key, _sx(570): _normalize_keyboard_modifier_mask(modifiers)}
            label = value.get(_sx(571))
            if isinstance(label, str) and label.strip():
                normalized[_sx(571)] = label.strip()
            return normalized
    return fallback

def _keyboard_binding_matches(binding: KeyboardBindingValue, key: int, modifiers: int) -> bool:
    if isinstance(binding, int):
        return binding == key
    if isinstance(binding, dict):
        binding_key = binding.get(_sx(569))
        binding_modifiers = _normalize_keyboard_modifier_mask(binding.get(_sx(570)))
        return isinstance(binding_key, int) and binding_key == key and (binding_modifiers == _normalize_keyboard_modifier_mask(modifiers))
    return False

def keyboard_binding_label(binding: KeyboardBindingValue) -> str:
    if binding is None:
        return UNASSIGNED_LABEL
    if isinstance(binding, int):
        return keyboard_key_label(binding)
    if isinstance(binding, dict):
        custom_label = binding.get(_sx(571))
        if isinstance(custom_label, str) and custom_label.strip():
            return custom_label.strip()
        key = binding.get(_sx(569))
        if not isinstance(key, int):
            return UNASSIGNED_LABEL
        modifiers = _normalize_keyboard_modifier_mask(binding.get(_sx(570)))
        parts: list[str] = []
        if modifiers & pygame.KMOD_CTRL:
            parts.append(_sx(580))
        if modifiers & pygame.KMOD_ALT:
            parts.append(_sx(581))
        if modifiers & pygame.KMOD_SHIFT:
            parts.append(_sx(582))
        if modifiers & pygame.KMOD_META:
            parts.append(_sx(583))
        parts.append(keyboard_key_label(key))
        return _sx(584).join(parts)
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
            family_bindings[action] = value if isinstance(value, str) and value or value is None else defaults[family][action]
        normalized[family] = family_bindings
    return normalized

def family_label(family: str) -> str:
    if family == XBOX_FAMILY:
        return _sx(557)
    if family == PLAYSTATION_FAMILY:
        return _sx(558)
    return _sx(516)

def controller_family_from_name(name: str) -> str:
    lowered = str(name or _sx(2)).casefold()
    if any((token in lowered for token in (_sx(389), _sx(586)))):
        return XBOX_FAMILY
    if any((token in lowered for token in (_sx(390), _sx(587), _sx(588), _sx(589), _sx(590), _sx(591)))):
        return PLAYSTATION_FAMILY
    return GENERIC_FAMILY

def keyboard_key_label(key: int | None) -> str:
    if key is None:
        return UNASSIGNED_LABEL
    if key in KEY_LABEL_OVERRIDES:
        return KEY_LABEL_OVERRIDES[key]
    key_name = pygame.key.name(key)
    if not key_name:
        return _sx(559).format(key)
    return key_name.replace(_sx(553), _sx(4)).title()

def controller_binding_label(binding: str | None, family: str) -> str:
    if not binding:
        return UNASSIGNED_LABEL
    binding_type, _, remainder = binding.partition(_sx(560))
    if binding_type == _sx(561):
        labels = GENERIC_BUTTON_LABELS
        if family == XBOX_FAMILY:
            labels = XBOX_BUTTON_LABELS
        elif family == PLAYSTATION_FAMILY:
            labels = PLAYSTATION_BUTTON_LABELS
        return labels.get(remainder, remainder.replace(_sx(553), _sx(4)).title())
    if binding_type == _sx(562):
        axis_label = remainder.replace(_sx(560), _sx(560))
        return AXIS_LABELS.get(axis_label, remainder.replace(_sx(560), _sx(4)).replace(_sx(553), _sx(4)).title())
    return binding.replace(_sx(560), _sx(4)).replace(_sx(553), _sx(4)).title()

def action_label(action_key: str) -> str:
    definition = ACTION_DEFINITIONS_BY_KEY.get(action_key)
    return definition.label if definition is not None else action_key

def reassign_keyboard_binding(bindings: dict[str, KeyboardBindingValue], action_key: str, binding: KeyboardBindingValue) -> dict[str, KeyboardBindingValue]:
    normalized = ensure_keyboard_bindings(bindings)
    definition = ACTION_DEFINITIONS_BY_KEY[action_key]
    for other_action, other_definition in ACTION_DEFINITIONS_BY_KEY.items():
        if other_action == action_key:
            continue
        if other_definition.context == definition.context and normalized.get(other_action) == binding:
            normalized[other_action] = None
    normalized[action_key] = binding
    return normalized

def reassign_controller_binding(bindings: dict[str, dict[str, str | None]], family: str, action_key: str, binding: str) -> dict[str, dict[str, str | None]]:
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
        self.last_input_source = _sx(563)
        self._axis_state: set[tuple[int, str]] = set()
        self.settings[_sx(354)] = ensure_keyboard_bindings(self.settings.get(_sx(354)))
        self.settings[_sx(355)] = ensure_controller_bindings(self.settings.get(_sx(355)))
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
            self.connected[instance_id] = ConnectedController(instance_id=instance_id, name=str(controller.name), family=controller_family_from_name(str(controller.name)), controller=controller)
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
        connected = ConnectedController(instance_id=instance_id, name=str(controller.name), family=controller_family_from_name(str(controller.name)), controller=controller)
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
                self.last_input_source = _sx(563)

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
        if self.last_input_source != _sx(565):
            return _sx(573)
        active = self.active_controller()
        return family_label(active.family) if active is not None else _sx(573)

    def current_controller_label(self) -> str:
        active = self.active_controller()
        if active is None:
            return _sx(574)
        return _sx(564).format(family_label(active.family), active.name)

    def controller_binding_for_action(self, action_key: str, family: str | None=None) -> str | None:
        selected_family = family or self.current_controller_family()
        return self.settings[_sx(355)].get(selected_family, {}).get(action_key)

    def keyboard_binding_for_action(self, action_key: str) -> KeyboardBindingValue:
        return self.settings[_sx(354)].get(action_key)

    def translate_keyboard_key(self, key: int, context: str, modifiers: int=0) -> int | None:
        self.last_input_source = _sx(563)
        for action_key in ACTION_ORDER:
            definition = ACTION_DEFINITIONS_BY_KEY[action_key]
            if definition.context != context:
                continue
            if _keyboard_binding_matches(self.settings[_sx(354)].get(action_key), key, modifiers):
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
        self.settings[_sx(354)] = reassign_keyboard_binding(self.settings[_sx(354)], action_key, binding)

    def update_controller_binding(self, family: str, action_key: str, binding: str) -> None:
        self.settings[_sx(355)] = reassign_controller_binding(self.settings[_sx(355)], family, action_key, binding)

    def reset_keyboard_bindings(self) -> None:
        self.settings[_sx(354)] = default_keyboard_bindings()

    def reset_controller_bindings(self, family: str) -> None:
        defaults = default_controller_bindings()
        self.settings[_sx(355)][family] = defaults[family]

    def _matches_for_binding(self, binding: str, instance_id: int, context: str, pressed: bool) -> list[tuple[int, bool]]:
        controller = self.connected.get(int(instance_id))
        if controller is None:
            return []
        self.active_controller_instance_id = controller.instance_id
        self.last_input_source = _sx(565)
        bindings = self.settings[_sx(355)].get(controller.family, {})
        translated: list[tuple[int, bool]] = []
        for action_key in ACTION_ORDER:
            definition = ACTION_DEFINITIONS_BY_KEY[action_key]
            if definition.context != context:
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
            binding = _sx(567).format(axis_token, direction)
            state_key = (instance_id, binding)
            value = float(event.value) * direction
            engaged = state_key in self._axis_state
            if value >= AXIS_CAPTURE_THRESHOLD and (not engaged):
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
        return _sx(566).format(token)

    def _axis_binding_from_event(self, event: pygame.event.Event) -> str | None:
        axis_token = AXIS_CODE_TO_TOKEN.get(int(event.axis))
        if axis_token is None:
            return None
        value = float(event.value)
        if abs(value) < AXIS_CAPTURE_THRESHOLD:
            return None
        direction = -1 if value < 0 else 1
        return _sx(567).format(axis_token, direction)
