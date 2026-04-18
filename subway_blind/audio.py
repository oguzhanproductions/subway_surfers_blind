from __future__ import annotations
from subway_blind.strings import sx as _sx
import audioop
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional
import wave
from xml.sax.saxutils import escape
import pygame
from subway_blind.config import resource_path
from subway_blind.hrtf_audio import OpenALHrtfEngine
FIXED_FOOTSTEP_PAN = {_sx(8): -0.18, _sx(9): -0.18, _sx(10): 0.18, _sx(11): 0.18}
CENTERED_PLAYER_KEYS = {_sx(12), _sx(13), _sx(14), _sx(15), _sx(16), _sx(17), _sx(18), _sx(19), _sx(20), _sx(21), _sx(22), _sx(23), _sx(24), _sx(25), _sx(26), _sx(27), _sx(28)}
KEY_CHANNEL_OVERRIDES = {_sx(12): _sx(29), _sx(13): _sx(29), _sx(14): _sx(30), _sx(15): _sx(31), _sx(16): _sx(32), _sx(17): _sx(32), _sx(18): _sx(33), _sx(19): _sx(34), _sx(20): _sx(35), _sx(21): _sx(36), _sx(22): _sx(37), _sx(23): _sx(37), _sx(24): _sx(37), _sx(25): _sx(38), _sx(26): _sx(39), _sx(28): _sx(40), _sx(27): _sx(41)}
CHANNEL_FALLBACK_OVERRIDES = {_sx(42): _sx(47), _sx(43): _sx(48), _sx(44): _sx(37), _sx(18): _sx(33), _sx(45): _sx(49), _sx(46): _sx(49)}
CHANNEL_POLYPHONY = {_sx(33): 12, _sx(31): 4, _sx(50): 4, _sx(29): 4, _sx(30): 4, _sx(32): 4, _sx(48): 8, _sx(34): 4, _sx(35): 4, _sx(36): 4, _sx(37): 4, _sx(38): 4, _sx(39): 4, _sx(40): 2, _sx(41): 2, _sx(49): 4}
FORCED_MONO_SOUND_KEYS = {_sx(51), _sx(52), _sx(53), _sx(54), _sx(55), _sx(56), _sx(57), _sx(58), _sx(59)}
ANNOUNCER_SOUND_FILES = {_sx(60): _sx(64), _sx(61): _sx(65), _sx(62): _sx(66), _sx(63): _sx(67)}
ANNOUNCER_SOUND_KEYS = frozenset(ANNOUNCER_SOUND_FILES)
SYSTEM_DEFAULT_OUTPUT_LABEL = _sx(5)
SAPI_VOICE_UNAVAILABLE_LABEL = _sx(6)
SAPI_VOICE_DEFAULT_LABEL = _sx(7)
SAPI_SPEAK_ASYNC = 1
SAPI_SPEAK_PURGE_BEFORE_SPEAK = 2
SAPI_SPEAK_IS_XML = 8
SAPI_RATE_MIN = -10
SAPI_RATE_MAX = 10
SAPI_PITCH_MIN = -10
SAPI_PITCH_MAX = 10
SAPI_VOLUME_MIN = 0
SAPI_VOLUME_MAX = 100
MUSIC_FILE_EXTENSIONS = (_sx(68), _sx(69), _sx(70))
MUSIC_TRACK_CANDIDATES = {_sx(71): (_sx(74), _sx(75), _sx(76), _sx(71)), _sx(72): (_sx(77), _sx(78), _sx(79), _sx(80), _sx(81))}
MUSIC_FADE_IN_SECONDS = 1.05
MUSIC_FADE_OUT_SECONDS = 0.75
MUSIC_DUCK_FADE_SECONDS = 1.05
MUSIC_DUCKED_LEVEL = 0.28

@dataclass(frozen=True)
class SapiVoiceChoice:
    voice_id: str
    name: str

def normalize_output_device_name(device_name: object) -> str | None:
    normalized = str(device_name or _sx(2)).strip()
    return normalized or None

def list_output_devices() -> list[str]:
    try:
        import pygame._sdl2.audio as sdl2_audio
    except Exception:
        return []
    try:
        names = sdl2_audio.get_audio_device_names(False)
    except Exception:
        return []
    devices: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = normalize_output_device_name(name)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        devices.append(normalized)
    return devices

def initialize_mixer_output(device_name: object) -> str | None:
    selected_device = normalize_output_device_name(device_name)
    if pygame.mixer.get_init() is not None:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
    if selected_device is not None:
        try:
            pygame.mixer.init(devicename=selected_device)
            return selected_device
        except pygame.error:
            pass
    try:
        pygame.mixer.init()
    except pygame.error:
        return None
    return None

class Speaker:

    def __init__(self, enabled: bool=True, use_sapi: bool=False, sapi_voice_id: str | None=None, sapi_rate: int=0, sapi_pitch: int=0, sapi_volume: int=100):
        self.enabled = bool(enabled)
        self.use_sapi = bool(use_sapi)
        self.sapi_voice_id = self._normalize_voice_id(sapi_voice_id)
        self.sapi_rate = self._normalize_sapi_rate(sapi_rate)
        self.sapi_pitch = self._normalize_sapi_pitch(sapi_pitch)
        self.sapi_volume = self._normalize_sapi_volume(sapi_volume)
        self._driver = None
        self._sapi_voice = None
        self._sapi_voice_name = SAPI_VOICE_DEFAULT_LABEL
        self._speed_factor = 0.0
        self._sapi_voice_choices_cache: list[SapiVoiceChoice] | None = None
        self._initialize_backend()

    @classmethod
    def from_settings(cls, settings: dict) -> _sx(73):
        return cls(enabled=bool(settings.get(_sx(117), True)), use_sapi=bool(settings.get(_sx(118), False)), sapi_voice_id=settings.get(_sx(119)), sapi_rate=settings.get(_sx(120), 0), sapi_pitch=settings.get(_sx(121), 0), sapi_volume=settings.get(_sx(122), 100))

    @staticmethod
    def _normalize_voice_id(voice_id: object) -> str | None:
        normalized = str(voice_id or _sx(2)).strip()
        return normalized or None

    @staticmethod
    def _normalize_sapi_rate(value: object) -> int:
        try:
            normalized = int(round(float(value)))
        except (TypeError, ValueError):
            normalized = 0
        return max(SAPI_RATE_MIN, min(SAPI_RATE_MAX, normalized))

    @staticmethod
    def _normalize_sapi_pitch(value: object) -> int:
        try:
            normalized = int(round(float(value)))
        except (TypeError, ValueError):
            normalized = 0
        return max(SAPI_PITCH_MIN, min(SAPI_PITCH_MAX, normalized))

    @staticmethod
    def _normalize_sapi_volume(value: object) -> int:
        try:
            normalized = int(round(float(value)))
        except (TypeError, ValueError):
            normalized = 100
        return max(SAPI_VOLUME_MIN, min(SAPI_VOLUME_MAX, normalized))

    def apply_settings(self, settings: dict) -> None:
        enabled = bool(settings.get(_sx(117), True))
        use_sapi = bool(settings.get(_sx(118), False))
        sapi_voice_id = self._normalize_voice_id(settings.get(_sx(119)))
        sapi_rate = self._normalize_sapi_rate(settings.get(_sx(120), 0))
        sapi_pitch = self._normalize_sapi_pitch(settings.get(_sx(121), 0))
        sapi_volume = self._normalize_sapi_volume(settings.get(_sx(122), 100))
        if enabled == self.enabled and use_sapi == self.use_sapi and (sapi_voice_id == self.sapi_voice_id) and (sapi_rate == self.sapi_rate) and (sapi_pitch == self.sapi_pitch) and (sapi_volume == self.sapi_volume):
            return
        should_reinitialize = enabled != self.enabled or use_sapi != self.use_sapi or (enabled and use_sapi and (sapi_voice_id != self.sapi_voice_id))
        self.enabled = enabled
        self.use_sapi = use_sapi
        self.sapi_voice_id = sapi_voice_id
        self.sapi_rate = sapi_rate
        self.sapi_pitch = sapi_pitch
        self.sapi_volume = sapi_volume
        if should_reinitialize:
            self._initialize_backend()
            return
        self._apply_sapi_rate()
        self._apply_sapi_volume()

    def _initialize_backend(self) -> None:
        self._driver = None
        self._sapi_voice = None
        self._sapi_voice_name = self.current_sapi_voice_display_name()
        if not self.enabled:
            return
        if self.use_sapi and self._initialize_sapi():
            self._apply_sapi_rate()
            self._apply_sapi_volume()
            return
        self._initialize_accessible_output()

    def _initialize_accessible_output(self) -> None:
        try:
            from accessible_output2.outputs.auto import Auto
            self._driver = Auto()
            self._apply_rate_to_supported_outputs()
        except Exception:
            self._driver = None

    def _initialize_sapi(self) -> bool:
        if os.name != _sx(85):
            return False
        try:
            from win32com.client import Dispatch
        except Exception:
            return False
        try:
            sapi_voice = Dispatch(_sx(123))
            for voice_choice in self.sapi_voice_choices():
                if voice_choice.voice_id != self.sapi_voice_id:
                    continue
                for index in range(sapi_voice.GetVoices().Count):
                    token = sapi_voice.GetVoices().Item(index)
                    token_id = self._normalize_voice_id(getattr(token, _sx(185), None))
                    if token_id != voice_choice.voice_id:
                        continue
                    sapi_voice.Voice = token
                    break
                break
            current_token = getattr(sapi_voice, _sx(124), None)
            current_voice_id = self._normalize_voice_id(getattr(current_token, _sx(185), None))
            if current_voice_id is not None:
                self.sapi_voice_id = current_voice_id
            try:
                self._sapi_voice_name = current_token.GetDescription()
            except Exception:
                self._sapi_voice_name = self.current_sapi_voice_display_name()
            self._sapi_voice = sapi_voice
            return True
        except Exception:
            self._sapi_voice = None
            return False

    def speak(self, text: str, interrupt: bool=True) -> None:
        if not self.enabled:
            return
        if self._sapi_voice is not None:
            flags = SAPI_SPEAK_ASYNC
            if interrupt:
                flags |= SAPI_SPEAK_PURGE_BEFORE_SPEAK
            message = str(text)
            if self.sapi_pitch != 0:
                flags |= SAPI_SPEAK_IS_XML
                message = _sx(125).format(self.sapi_pitch, escape(message))
            try:
                self._sapi_voice.Speak(message, flags)
            except Exception:
                return
            return
        if self._driver is None:
            try:
                print(text)
            except Exception:
                return
            return
        try:
            self._driver.speak(text, interrupt=interrupt)
        except TypeError:
            try:
                self._driver.speak(text, interrupt)
            except Exception:
                return
        except Exception:
            return

    def set_speed_factor(self, speed_factor: float) -> None:
        normalized = max(0.0, min(1.0, float(speed_factor)))
        if abs(normalized - self._speed_factor) < 0.04:
            return
        self._speed_factor = normalized
        self._apply_sapi_rate()
        self._apply_rate_to_supported_outputs()

    def sapi_available(self) -> bool:
        return len(self.sapi_voice_choices()) > 0

    def sapi_voice_choices(self) -> list[SapiVoiceChoice]:
        if self._sapi_voice_choices_cache is not None:
            return list(self._sapi_voice_choices_cache)
        choices: list[SapiVoiceChoice] = []
        if os.name == _sx(85):
            try:
                from win32com.client import Dispatch
                token_collection = Dispatch(_sx(123)).GetVoices()
                for index in range(token_collection.Count):
                    token = token_collection.Item(index)
                    voice_id = self._normalize_voice_id(getattr(token, _sx(185), None))
                    if voice_id is None:
                        continue
                    try:
                        name = str(token.GetDescription()).strip() or voice_id
                    except Exception:
                        name = voice_id
                    choices.append(SapiVoiceChoice(voice_id=voice_id, name=name))
            except Exception:
                choices = []
        self._sapi_voice_choices_cache = choices
        return list(self._sapi_voice_choices_cache)

    def current_sapi_voice_display_name(self) -> str:
        if self._sapi_voice is not None:
            return self._sapi_voice_name
        choices = self.sapi_voice_choices()
        if not choices:
            return SAPI_VOICE_UNAVAILABLE_LABEL
        if self.sapi_voice_id is None:
            return choices[0].name
        for choice in choices:
            if choice.voice_id == self.sapi_voice_id:
                return choice.name
        return choices[0].name

    def cycle_sapi_voice(self, direction: int) -> str:
        choices = self.sapi_voice_choices()
        if not choices:
            return SAPI_VOICE_UNAVAILABLE_LABEL
        normalized_direction = -1 if direction < 0 else 1
        current_voice_id = self.sapi_voice_id
        try:
            current_index = next((index for index, choice in enumerate(choices) if choice.voice_id == current_voice_id))
        except StopIteration:
            current_index = 0
        selected = choices[(current_index + normalized_direction) % len(choices)]
        self.sapi_voice_id = selected.voice_id
        self._sapi_voice_name = selected.name
        if self._sapi_voice is not None:
            self._initialize_backend()
        return selected.name

    def _apply_sapi_rate(self) -> None:
        if self._sapi_voice is None:
            return
        dynamic_rate_offset = int(round(-1 + self._speed_factor * 5.0))
        target_rate = self.sapi_rate + dynamic_rate_offset
        try:
            self._sapi_voice.Rate = max(SAPI_RATE_MIN, min(SAPI_RATE_MAX, target_rate))
        except Exception:
            return

    def _apply_sapi_volume(self) -> None:
        if self._sapi_voice is None:
            return
        try:
            self._sapi_voice.Volume = self.sapi_volume
        except Exception:
            return

    def stop(self) -> None:
        if self._sapi_voice is not None:
            try:
                self._sapi_voice.Speak(_sx(2), SAPI_SPEAK_ASYNC | SAPI_SPEAK_PURGE_BEFORE_SPEAK)
            except Exception:
                pass

    def _apply_rate_to_supported_outputs(self) -> None:
        if self._driver is None:
            return
        outputs = getattr(self._driver, _sx(86), [])
        for output in outputs:
            has_rate = getattr(output, _sx(126), None)
            set_rate = getattr(output, _sx(127), None)
            min_rate = getattr(output, _sx(128), None)
            max_rate = getattr(output, _sx(129), None)
            if not callable(has_rate) or not callable(set_rate) or (not callable(min_rate)) or (not callable(max_rate)):
                continue
            try:
                if not has_rate():
                    continue
                minimum = float(min_rate())
                maximum = float(max_rate())
                target = minimum + (maximum - minimum) * (0.42 + self._speed_factor * 0.4)
                set_rate(target)
            except Exception:
                continue

class Audio:

    def __init__(self, settings: dict):
        self.settings = settings
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.sound_paths: dict[str, str] = {}
        self.sound_channel_counts: dict[str, int | None] = {}
        self.channels: dict[str, pygame.mixer.Channel] = {}
        self._next_channel_index = 0
        self._output_device_name = normalize_output_device_name(settings.get(_sx(1)))
        self._mixer_ready = pygame.mixer.get_init() is not None
        self._music_catalog: dict[str, str] = {}
        self._music_current_track: str | None = None
        self._music_pending_track: str | None = None
        self._music_fade_level = 0.0
        self._music_transition: str | None = None
        self._music_ducking_level = 1.0
        self._music_ducking_target = 1.0
        self._pitched_sounds: dict[tuple[str, int], pygame.mixer.Sound] = {}
        self._channel_polyphony_index: dict[str, int] = {}
        self.hrtf = OpenALHrtfEngine(settings.get(_sx(130), 1.0), self._output_device_name)
        self._load()

    def _load_sound(self, key: str, path: str) -> None:
        if not os.path.exists(path):
            return
        playback_path = self._resolve_playback_path(key, path)
        self.sound_paths[key] = playback_path
        self.sound_channel_counts[key] = self._read_sound_channel_count(playback_path)
        try:
            self.hrtf.register_sound(key, playback_path)
        except Exception:
            pass
        if not self._mixer_ready:
            return
        try:
            sound = pygame.mixer.Sound(playback_path)
        except Exception:
            return
        sound.set_volume(float(self.settings[_sx(130)]))
        self.sounds[key] = sound

    def _resolve_playback_path(self, key: str, path: str) -> str:
        if key not in FORCED_MONO_SOUND_KEYS:
            return path
        try:
            prepared_path = self.hrtf._prepare_openal_path(Path(path), spatialize=True)
        except Exception:
            return path
        if self._read_sound_channel_count(prepared_path) != 1:
            return path
        return prepared_path

    @staticmethod
    def _read_sound_channel_count(path: str) -> int | None:
        if not path.lower().endswith(_sx(69)):
            return None
        try:
            with wave.open(path, _sx(189)) as reader:
                channels = int(reader.getnchannels())
        except Exception:
            return None
        return channels if channels > 0 else None

    def _pick_menu_sound(self, base_name: str) -> str:
        for extension in (_sx(68), _sx(69)):
            candidate = resource_path(_sx(87), _sx(71), _sx(131).format(base_name, extension))
            if os.path.exists(candidate):
                return candidate
        return resource_path(_sx(87), _sx(71), _sx(88).format(base_name))

    def _pick_sfx_sound(self, base_name: str) -> str:
        for extension in (_sx(68), _sx(69), _sx(70)):
            candidate = resource_path(_sx(87), _sx(89), _sx(131).format(base_name, extension))
            if os.path.exists(candidate):
                return candidate
        return resource_path(_sx(87), _sx(89), _sx(88).format(base_name))

    def _load(self) -> None:
        sfx_path = lambda name: resource_path(_sx(87), _sx(89), name)
        announcer_path = lambda name: resource_path(_sx(87), _sx(132), name)
        self._load_sound(_sx(18), sfx_path(_sx(133)))
        self._load_sound(_sx(90), sfx_path(_sx(134)))
        self._load_sound(_sx(12), sfx_path(_sx(135)))
        self._load_sound(_sx(14), sfx_path(_sx(136)))
        self._load_sound(_sx(15), sfx_path(_sx(137)))
        self._load_sound(_sx(16), sfx_path(_sx(138)))
        self._load_sound(_sx(22), sfx_path(_sx(139)))
        self._load_sound(_sx(25), sfx_path(_sx(140)))
        self._load_sound(_sx(26), sfx_path(_sx(141)))
        self._load_sound(_sx(91), sfx_path(_sx(142)))
        self._load_sound(_sx(92), sfx_path(_sx(143)))
        self._load_sound(_sx(28), sfx_path(_sx(144)))
        self._load_sound(_sx(93), sfx_path(_sx(145)))
        self._load_sound(_sx(19), sfx_path(_sx(146)))
        self._load_sound(_sx(20), sfx_path(_sx(147)))
        self._load_sound(_sx(94), sfx_path(_sx(148)))
        self._load_sound(_sx(95), sfx_path(_sx(149)))
        self._load_sound(_sx(96), self._pick_sfx_sound(_sx(96)))
        self._load_sound(_sx(97), self._pick_sfx_sound(_sx(97)))
        self._load_sound(_sx(21), sfx_path(_sx(150)))
        self._load_sound(_sx(98), sfx_path(_sx(151)))
        self._load_sound(_sx(99), sfx_path(_sx(152)))
        self._load_sound(_sx(100), sfx_path(_sx(153)))
        self._load_sound(_sx(101), sfx_path(_sx(154)))
        self._load_sound(_sx(102), sfx_path(_sx(155)))
        self._load_sound(_sx(103), sfx_path(_sx(156)))
        self._load_sound(_sx(104), sfx_path(_sx(157)))
        self._load_sound(_sx(105), sfx_path(_sx(158)))
        self._load_sound(_sx(106), sfx_path(_sx(159)))
        self._load_sound(_sx(107), sfx_path(_sx(160)))
        self._load_sound(_sx(108), sfx_path(_sx(161)))
        self._load_sound(_sx(8), sfx_path(_sx(162)))
        self._load_sound(_sx(10), sfx_path(_sx(163)))
        self._load_sound(_sx(13), sfx_path(_sx(164)))
        self._load_sound(_sx(9), sfx_path(_sx(165)))
        self._load_sound(_sx(11), sfx_path(_sx(166)))
        self._load_sound(_sx(109), sfx_path(_sx(167)))
        self._load_sound(_sx(110), sfx_path(_sx(168)))
        self._load_sound(_sx(23), sfx_path(_sx(169)))
        self._load_sound(_sx(24), sfx_path(_sx(170)))
        self._load_sound(_sx(27), sfx_path(_sx(171)))
        self._load_sound(_sx(17), sfx_path(_sx(172)))
        self._load_sound(_sx(111), sfx_path(_sx(173)))
        self._load_sound(_sx(112), sfx_path(_sx(174)))
        self._load_sound(_sx(113), sfx_path(_sx(175)))
        self._load_sound(_sx(51), self._pick_menu_sound(_sx(51)))
        self._load_sound(_sx(52), self._pick_menu_sound(_sx(52)))
        self._load_sound(_sx(53), self._pick_menu_sound(_sx(53)))
        self._load_sound(_sx(54), self._pick_menu_sound(_sx(54)))
        self._load_sound(_sx(55), self._pick_menu_sound(_sx(55)))
        self._load_sound(_sx(56), self._pick_menu_sound(_sx(56)))
        self._load_sound(_sx(57), resource_path(_sx(87), _sx(71), _sx(176)))
        self._load_sound(_sx(58), resource_path(_sx(87), _sx(71), _sx(177)))
        self._load_sound(_sx(59), resource_path(_sx(87), _sx(71), _sx(178)))
        for key, filename in ANNOUNCER_SOUND_FILES.items():
            self._load_sound(key, announcer_path(filename))
        self._music_catalog = self._discover_music_catalog()

    def refresh_volumes(self) -> None:
        if not self._mixer_ready:
            self.hrtf.set_listener_gain(float(self.settings[_sx(130)]))
            return
        sound_volume = float(self.settings[_sx(130)])
        for sound in self.sounds.values():
            try:
                sound.set_volume(sound_volume)
            except Exception:
                continue
        self._apply_music_volume()
        self.hrtf.set_listener_gain(sound_volume)

    def output_device_choices(self) -> list[str | None]:
        devices = [None]
        current_device = normalize_output_device_name(self.settings.get(_sx(1)))
        for device in list_output_devices():
            devices.append(device)
        if current_device is not None and current_device not in devices:
            devices.append(current_device)
        return devices

    def current_output_device_name(self) -> str | None:
        return normalize_output_device_name(self.settings.get(_sx(1)))

    def output_device_display_name(self) -> str:
        return self.current_output_device_name() or SYSTEM_DEFAULT_OUTPUT_LABEL

    def cycle_output_device(self) -> tuple[str | None, str | None]:
        devices = self.output_device_choices()
        current_device = self.current_output_device_name()
        try:
            current_index = devices.index(current_device)
        except ValueError:
            current_index = 0
        requested_device = devices[(current_index + 1) % len(devices)]
        applied_device = self.apply_output_device(requested_device)
        return (requested_device, applied_device)

    def apply_output_device(self, device_name: str | None) -> str | None:
        requested_device = normalize_output_device_name(device_name)
        resume_music_track = self._music_pending_track or self._music_current_track
        self.shutdown()
        applied_device = initialize_mixer_output(requested_device)
        self._output_device_name = applied_device
        self.settings[_sx(1)] = applied_device or _sx(2)
        self._mixer_ready = pygame.mixer.get_init() is not None
        self.hrtf = OpenALHrtfEngine(self.settings.get(_sx(130), 1.0), applied_device)
        self.sounds.clear()
        self.sound_paths.clear()
        self.sound_channel_counts.clear()
        self.channels.clear()
        self._next_channel_index = 0
        self._channel_polyphony_index.clear()
        self._load()
        self.refresh_volumes()
        if resume_music_track is not None:
            self.music_start(resume_music_track)
        return applied_device

    def shutdown(self) -> None:
        if self._mixer_ready:
            for channel in self.channels.values():
                try:
                    channel.stop()
                except Exception:
                    continue
            self._stop_music_immediately()
        self.channels.clear()
        self._next_channel_index = 0
        self._channel_polyphony_index.clear()
        self.hrtf.shutdown()

    def has_sound(self, key: str) -> bool:
        return key in self.sound_paths or key in self.sounds

    def _get_channel(self, name: str) -> Optional[pygame.mixer.Channel]:
        if not self._mixer_ready:
            return None
        existing = self.channels.get(name)
        if existing is not None:
            return existing
        index = self._next_channel_index
        self._next_channel_index += 1
        try:
            pygame.mixer.set_num_channels(max(16, self._next_channel_index + 1))
            channel = pygame.mixer.Channel(index)
        except Exception:
            return None
        self.channels[name] = channel
        return channel

    def play(self, key: str, pan: Optional[float]=None, loop: bool=False, channel: Optional[str]=None, gain: float=1.0, pitch: float=1.0) -> None:
        gain = max(0.0, min(1.5, float(gain)))
        pitch = max(0.5, min(2.0, float(pitch)))
        normalized_pan = self._normalize_pan_for_key(key, pan)
        sound_path = self.sound_paths.get(key)
        requested_channel = channel or _sx(114).format(key)
        target_channel = self._normalize_channel_for_key(key, requested_channel)
        playback_channel = self._resolve_playback_channel(target_channel, loop)
        if self._should_use_non_spatial_hrtf(key, target_channel) and sound_path is not None:
            x, y, z, profile_pitch, relative = self._hrtf_profile(key, playback_channel, normalized_pan)
            played = self.hrtf.play_sound(key=key, path=sound_path, channel=playback_channel, x=x, y=y, z=z, gain=gain, pitch=profile_pitch * pitch, loop=loop, relative=relative, spatialize=False)
            if played:
                return
        if not self._mixer_ready:
            return
        sound = self.sounds.get(key)
        if sound is None:
            return
        if abs(pitch - 1.0) >= 0.01:
            sound = self._get_pitched_sound(key, sound, pitch)
        output_channel = self._get_channel(playback_channel)
        if output_channel is None:
            return
        base_volume = float(self.settings[_sx(130)]) * gain
        if normalized_pan is None:
            output_channel.set_volume(max(0.0, min(1.0, base_volume)))
        else:
            clamped_pan = max(-1.0, min(1.0, float(normalized_pan)))
            left = max(0.0, min(1.0, 1.0 - max(0.0, clamped_pan)))
            right = max(0.0, min(1.0, 1.0 + min(0.0, clamped_pan)))
            output_channel.set_volume(max(0.0, min(1.0, left * base_volume)), max(0.0, min(1.0, right * base_volume)))
        try:
            output_channel.play(sound, loops=-1 if loop else 0)
        except Exception:
            return

    def stop(self, channel: str) -> None:
        self.hrtf.stop(channel)
        output_channel = self.channels.get(channel)
        if output_channel is None:
            return
        try:
            output_channel.stop()
        except Exception:
            return

    def play_spatial(self, key: str, channel: str, x: float, y: float, z: float, gain: float, pitch: float=1.0, fallback_pan: Optional[float]=None, velocity_x: float=0.0, velocity_y: float=0.0, velocity_z: float=0.0) -> None:
        sound_path = self.sound_paths.get(key)
        played = False
        if sound_path is not None:
            played = self.hrtf.play_sound(key=key, path=sound_path, channel=channel, x=x, y=y, z=z, gain=gain, pitch=pitch, velocity_x=velocity_x, velocity_y=velocity_y, velocity_z=velocity_z, spatialize=True)
        if played:
            return
        self.play(key, pan=fallback_pan, channel=channel, gain=gain)

    def update_spatial(self, channel: str, x: float, y: float, z: float, gain: float, pitch: float=1.0, fallback_pan: Optional[float]=None, velocity_x: float=0.0, velocity_y: float=0.0, velocity_z: float=0.0) -> None:
        if self.hrtf.update_source(channel=channel, x=x, y=y, z=z, gain=gain, pitch=pitch, velocity_x=velocity_x, velocity_y=velocity_y, velocity_z=velocity_z):
            return
        output_channel = self.channels.get(channel)
        if output_channel is None:
            return
        base_volume = float(self.settings[_sx(130)]) * max(0.0, min(1.5, float(gain)))
        if fallback_pan is None:
            output_channel.set_volume(max(0.0, min(1.0, base_volume)))
            return
        clamped_pan = max(-1.0, min(1.0, float(fallback_pan)))
        left = max(0.0, min(1.0, 1.0 - max(0.0, clamped_pan)))
        right = max(0.0, min(1.0, 1.0 + min(0.0, clamped_pan)))
        output_channel.set_volume(max(0.0, min(1.0, left * base_volume)), max(0.0, min(1.0, right * base_volume)))

    def _hrtf_profile(self, key: str, channel: str, pan: Optional[float]) -> tuple[float, float, float, float, bool]:
        clamped_pan = 0.0 if pan is None else max(-1.0, min(1.0, float(pan)))
        x = clamped_pan * 1.95
        y = 0.0
        z = -1.55
        pitch = 1.0
        relative = False
        if channel.startswith(_sx(180)) or channel.startswith(_sx(181)) or channel.startswith(_sx(182)):
            x = clamped_pan * 0.6
            z = -0.9
            relative = True
        elif channel.startswith(_sx(42)) or channel.startswith(_sx(43)) or channel.startswith(_sx(190)) or channel.startswith(_sx(18)):
            z = -1.8
        elif channel.startswith(_sx(194)) or key in {_sx(93), _sx(28)}:
            z = 0.7
            x = clamped_pan * 1.2
        elif channel.startswith(_sx(197)) or key == _sx(95):
            z = -1.0
            y = 0.35
        elif channel.startswith(_sx(198)) or key == _sx(94):
            z = -1.2
            y = 0.1
        if key == _sx(101):
            z = -5.4
            x = clamped_pan * 2.6
            y = -0.08
            pitch = 0.9
        elif key in {_sx(191), _sx(51), _sx(52), _sx(53), _sx(54), _sx(55), _sx(56), _sx(57), _sx(58), _sx(59)}:
            z = -0.8
            relative = True
        elif key in ANNOUNCER_SOUND_KEYS:
            x = 0.0
            y = 0.0
            z = -0.9
            relative = True
        elif key in {_sx(8), _sx(10), _sx(9), _sx(11)}:
            x = clamped_pan * 1.4
            y = -0.2
            z = -0.95
            relative = True
        elif key in CENTERED_PLAYER_KEYS:
            x = 0.0
            y = 0.0
            z = -1.05
            relative = True
        return (x, y, z, pitch, relative)

    def _get_pitched_sound(self, key: str, sound: pygame.mixer.Sound, pitch: float) -> pygame.mixer.Sound:
        pitch_key = round(pitch * 100)
        cache_key = (key, pitch_key)
        cached = self._pitched_sounds.get(cache_key)
        if cached is not None:
            return cached
        mixer_info = pygame.mixer.get_init()
        if mixer_info is None:
            return sound
        freq, size, channels = mixer_info
        width = abs(size) // 8
        raw = sound.get_raw()
        try:
            inrate = int(freq * pitch)
            converted, _ = audioop.ratecv(raw, width, channels, inrate, freq, None)
            pitched = pygame.mixer.Sound(buffer=converted)
            pitched.set_volume(sound.get_volume())
            self._pitched_sounds[cache_key] = pitched
            return pitched
        except Exception:
            return sound

    def _should_use_non_spatial_hrtf(self, key: str, channel: str) -> bool:
        if not self.hrtf.available:
            return False
        if self.sound_channel_counts.get(key) != 1:
            return False
        if channel.startswith(_sx(180)) and (not bool(self.settings.get(_sx(195), True))):
            return False
        return True

    @staticmethod
    def _normalize_pan_for_key(key: str, pan: Optional[float]) -> Optional[float]:
        fixed_pan = FIXED_FOOTSTEP_PAN.get(key)
        if fixed_pan is not None:
            return fixed_pan
        if key in CENTERED_PLAYER_KEYS:
            return 0.0
        return pan

    @staticmethod
    def _normalize_channel_for_key(key: str, channel: str) -> str:
        if key in FIXED_FOOTSTEP_PAN:
            return _sx(50)
        if key in KEY_CHANNEL_OVERRIDES:
            return KEY_CHANNEL_OVERRIDES[key]
        return CHANNEL_FALLBACK_OVERRIDES.get(channel, channel)

    def _resolve_playback_channel(self, channel: str, loop: bool) -> str:
        if loop:
            return channel
        polyphony = CHANNEL_POLYPHONY.get(channel, 1)
        if polyphony <= 1:
            return channel
        index_map = getattr(self, _sx(115), None)
        if index_map is None:
            index_map = {}
            self._channel_polyphony_index = index_map
        next_index = index_map.get(channel, 0)
        for offset in range(polyphony):
            slot_index = (next_index + offset) % polyphony
            candidate_channel = _sx(82).format(channel, slot_index)
            if not self._is_channel_active(candidate_channel):
                index_map[channel] = (slot_index + 1) % polyphony
                return candidate_channel
        fallback_channel = _sx(82).format(channel, next_index)
        index_map[channel] = (next_index + 1) % polyphony
        return fallback_channel

    def _is_channel_active(self, channel: str) -> bool:
        output_channel = self.channels.get(channel)
        if output_channel is not None:
            try:
                if bool(output_channel.get_busy()):
                    return True
            except Exception:
                pass
        try:
            return bool(self.hrtf.is_channel_playing(channel))
        except Exception:
            return False

    def _discover_music_catalog(self) -> dict[str, str]:
        catalog: dict[str, str] = {}
        for track_key, base_names in MUSIC_TRACK_CANDIDATES.items():
            resolved = self._resolve_music_track_path(base_names)
            if resolved is not None:
                catalog[track_key] = resolved
        return catalog

    def _resolve_music_track_path(self, base_names: tuple[str, ...]) -> str | None:
        for base_name in base_names:
            for extension in MUSIC_FILE_EXTENSIONS:
                candidate = resource_path(_sx(87), _sx(192), _sx(131).format(base_name, extension))
                if os.path.exists(candidate):
                    return candidate
        return None

    def _target_music_volume(self) -> float:
        return max(0.0, min(1.0, float(self.settings.get(_sx(196), 0.0))))

    def _apply_music_volume(self) -> None:
        if not self._mixer_ready:
            return
        try:
            pygame.mixer.music.set_volume(self._target_music_volume() * self._music_fade_level * self._music_ducking_level)
        except Exception:
            return

    def _stop_music_immediately(self) -> None:
        if self._mixer_ready:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self._music_current_track = None
        self._music_pending_track = None
        self._music_fade_level = 0.0
        self._music_transition = None

    def set_music_ducking(self, enabled: bool, level: float=MUSIC_DUCKED_LEVEL) -> None:
        target = max(0.0, min(1.0, float(level if enabled else 1.0)))
        self._music_ducking_target = target
        if abs(self._music_ducking_level - target) < 0.001:
            self._music_ducking_level = target
        self._apply_music_volume()

    def _play_music_track(self, track_key: str) -> bool:
        if not self._mixer_ready:
            return False
        track_path = self._music_catalog.get(track_key)
        if track_path is None:
            self._stop_music_immediately()
            return False
        try:
            pygame.mixer.music.load(track_path)
            pygame.mixer.music.play(-1)
        except Exception:
            self._stop_music_immediately()
            return False
        self._music_current_track = track_key
        self._music_pending_track = None
        self._music_fade_level = 0.0
        self._music_transition = _sx(83)
        self._apply_music_volume()
        return True

    def _begin_music_fade_out(self, next_track: str | None=None) -> None:
        if not self._mixer_ready:
            self._stop_music_immediately()
            return
        if self._music_current_track is None:
            if next_track is not None:
                self._play_music_track(next_track)
            else:
                self._stop_music_immediately()
            return
        self._music_pending_track = next_track
        self._music_transition = _sx(84)
        if self._music_fade_level <= 0.0:
            self._music_fade_level = 1.0
        self._apply_music_volume()

    def music_start(self, track_key: str=_sx(72)) -> None:
        normalized_track = _sx(71) if str(track_key).strip().lower() == _sx(71) else _sx(72)
        if self._music_current_track == normalized_track and self._music_pending_track is None:
            if self._music_transition == _sx(84):
                self._music_transition = _sx(83)
            elif self._music_transition is None and self._music_fade_level < 1.0:
                self._music_transition = _sx(83)
            self._apply_music_volume()
            return
        if self._music_current_track is None:
            self._play_music_track(normalized_track)
            return
        self._begin_music_fade_out(normalized_track)

    def music_stop(self, immediate: bool=False) -> None:
        if immediate:
            self._stop_music_immediately()
            return
        self._begin_music_fade_out(None)

    def music_is_idle(self) -> bool:
        return self._music_current_track is None and self._music_pending_track is None and (self._music_transition is None)

    def update(self, delta_time: float) -> None:
        if not self._mixer_ready:
            return
        if not hasattr(self, _sx(183)):
            self._music_ducking_level = 1.0
        if not hasattr(self, _sx(184)):
            self._music_ducking_target = 1.0
        duck_step = float(delta_time) / MUSIC_DUCK_FADE_SECONDS if MUSIC_DUCK_FADE_SECONDS > 0 else 1.0
        if self._music_ducking_level < self._music_ducking_target:
            self._music_ducking_level = min(self._music_ducking_target, self._music_ducking_level + duck_step)
            self._apply_music_volume()
        elif self._music_ducking_level > self._music_ducking_target:
            self._music_ducking_level = max(self._music_ducking_target, self._music_ducking_level - duck_step)
            self._apply_music_volume()
        if self._music_transition is None:
            return
        if self._music_transition == _sx(83):
            self._music_fade_level = min(1.0, self._music_fade_level + float(delta_time) / MUSIC_FADE_IN_SECONDS)
            self._apply_music_volume()
            if self._music_fade_level >= 1.0:
                self._music_transition = None
            return
        if self._music_transition != _sx(84):
            return
        self._music_fade_level = max(0.0, self._music_fade_level - float(delta_time) / MUSIC_FADE_OUT_SECONDS)
        self._apply_music_volume()
        if self._music_fade_level > 0.0:
            return
        next_track = self._music_pending_track
        self._stop_music_immediately()
        if next_track is not None:
            self._play_music_track(next_track)
