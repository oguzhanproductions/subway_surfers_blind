from __future__ import annotations

import audioop
import hashlib
import os
import shutil
import tempfile
import uuid
import wave
from pathlib import Path

from subway_blind.config import BASE_DIR, resource_path


class OpenALHrtfEngine:
    def __init__(self, sfx_volume: float, output_device_name: str | None = None):
        self.available = False
        self._al = None
        self._device = None
        self._context = None
        self._buffers: dict[str, object] = {}
        self._buffer_paths: dict[str, str] = {}
        self._sources: dict[str, object] = {}
        self._channel_keys: dict[str, str] = {}
        self._listener_gain = max(0.0, min(1.0, float(sfx_volume)))
        self._output_device_name = str(output_device_name or "").strip()
        try:
            import pyopenalsoft as openal
        except Exception:
            return
        self._al = openal
        try:
            self._configure_openal_soft()
            self._al.init()
            self._device = self._al.Device(self._output_device_name)
            self._context = self._al.Context(self._device)
            self._al.Listener.reset()
            self._al.Listener.set_position(0.0, 0.0, 0.0)
            self._al.Listener.set_velocity(0.0, 0.0, 0.0)
            self._al.Listener.set_orientation(0.0, 0.0, -1.0, 0.0, 1.0, 0.0)
            self.available = True
        except Exception:
            self.available = False

    def _configure_openal_soft(self) -> None:
        config_root = BASE_DIR / "data" / "openal"
        config_root.mkdir(parents=True, exist_ok=True)
        config_path = config_root / "alsoft.ini"
        config_path.write_text(
            "[general]\n"
            "stereo-mode = headphones\n"
            "hrtf = true\n"
            "sources = 128\n"
            "slots = 16\n",
            encoding="utf-8",
        )
        os.environ["ALSOFT_CONF"] = str(config_path)

    @staticmethod
    def _buffer_cache_key(key: str, spatialize: bool) -> str:
        return f"{key}::{'spatial' if spatialize else 'direct'}"

    def register_sound(self, key: str, path: str, spatialize: bool = False) -> str | None:
        if not self.available or self._al is None:
            return None
        source_path = Path(path)
        if not source_path.exists():
            return None
        buffer_key = self._buffer_cache_key(key, spatialize)
        prepared_path = self._prepare_openal_path(source_path, spatialize=spatialize)
        if self._buffer_paths.get(buffer_key) == prepared_path and buffer_key in self._buffers:
            return buffer_key
        try:
            audio_data = self._al.AudioData(prepared_path)
            buffer = self._al.Buffer(audio_data)
        except Exception:
            if prepared_path != str(source_path):
                self._discard_cached_asset(Path(prepared_path))
                try:
                    prepared_path = self._prepare_openal_path(source_path, refresh=True, spatialize=spatialize)
                    audio_data = self._al.AudioData(prepared_path)
                    buffer = self._al.Buffer(audio_data)
                except Exception:
                    return None
            else:
                return None
        self._buffers[buffer_key] = buffer
        self._buffer_paths[buffer_key] = prepared_path
        return buffer_key

    def _prepare_openal_path(self, source: Path, refresh: bool = False, spatialize: bool = False) -> str:
        if source.suffix.lower() == ".wav":
            return self._prepare_wav_path(source, refresh=refresh, spatialize=spatialize)
        if self._is_ascii_safe_path(source):
            return str(source)
        return self._stage_original_asset(source, refresh=refresh)

    def _prepare_wav_path(self, source: Path, refresh: bool = False, spatialize: bool = False) -> str:
        requires_ascii_cache = not self._is_ascii_safe_path(source)
        try:
            with wave.open(str(source), "rb") as reader:
                channels = reader.getnchannels()
                sample_width = reader.getsampwidth()
                frame_rate = reader.getframerate()
                frames = reader.readframes(reader.getnframes())
        except Exception:
            if requires_ascii_cache:
                return self._stage_original_asset(source, refresh=refresh)
            return str(source)

        if not spatialize:
            if requires_ascii_cache:
                return self._stage_original_asset(source, refresh=refresh)
            return str(source)

        if channels == 1 and not requires_ascii_cache:
            return str(source)

        fingerprint = self._source_fingerprint(source)
        cache_suffix = ".wav"
        stem_suffix = "_mono" if channels != 1 else ""
        cache_path = self._openal_cache_root() / f"{self._ascii_file_stem(source.stem)}_{fingerprint}{stem_suffix}{cache_suffix}"
        if not refresh and self._is_valid_cached_wav(cache_path, expected_channels=1):
            return str(cache_path)

        try:
            if channels == 1:
                self._copy_file_atomically(source, cache_path)
            else:
                mono_frames = self._downmix_to_mono(frames, channels, sample_width)
                self._write_wav_atomically(
                    cache_path,
                    channels=1,
                    sample_width=sample_width,
                    frame_rate=frame_rate,
                    frames=mono_frames,
                )
            return str(cache_path)
        except Exception:
            return str(source)

    def _downmix_to_mono(self, frames: bytes, channels: int, sample_width: int) -> bytes:
        if channels <= 1:
            return frames
        if channels == 2:
            return audioop.tomono(frames, sample_width, 0.5, 0.5)

        frame_step = sample_width * channels
        mono_chunks: list[bytes] = []
        for offset in range(0, len(frames), frame_step):
            frame = frames[offset : offset + frame_step]
            if len(frame) < frame_step:
                break
            mono = audioop.tomono(frame[: sample_width * 2], sample_width, 0.5, 0.5)
            mono_chunks.append(mono)
        return b"".join(mono_chunks)

    def _openal_cache_root(self) -> Path:
        preferred_root = BASE_DIR / "data" / "openal_cache"
        candidates = [preferred_root]

        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        candidates.append(program_data / "VireonInteractive" / "SubwaySurfersBlindEdition" / "openal_cache")

        temp_root = Path(tempfile.gettempdir())
        candidates.append(temp_root / "VireonInteractive" / "SubwaySurfersBlindEdition" / "openal_cache")

        for candidate in candidates:
            if not self._is_ascii_safe_path(candidate):
                continue
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
            return candidate
        preferred_root.mkdir(parents=True, exist_ok=True)
        return preferred_root

    def _stage_original_asset(self, source: Path, refresh: bool = False) -> str:
        cache_path = self._openal_cache_root() / f"{self._ascii_file_stem(source.stem)}_{self._source_fingerprint(source)}{source.suffix.lower()}"
        if not refresh and self._is_usable_cached_asset(cache_path):
            return str(cache_path)
        try:
            self._copy_file_atomically(source, cache_path)
            return str(cache_path)
        except Exception:
            return str(source)

    def _source_fingerprint(self, source: Path) -> str:
        stats = source.stat()
        try:
            resolved_source = source.resolve()
        except Exception:
            resolved_source = source
        return hashlib.sha1(
            f"{resolved_source}::{stats.st_mtime_ns}::{stats.st_size}".encode("utf-8")
        ).hexdigest()[:16]

    def _is_ascii_safe_path(self, path: Path) -> bool:
        try:
            value = str(path.resolve(strict=False))
        except Exception:
            value = str(path)
        return value.isascii()

    def _ascii_file_stem(self, value: str) -> str:
        sanitized = "".join(character if character.isascii() and character.isalnum() else "_" for character in value)
        return sanitized.strip("_") or "sound"

    def _is_usable_cached_asset(self, path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except Exception:
            return False

    def _is_valid_cached_wav(self, path: Path, expected_channels: int) -> bool:
        if not self._is_usable_cached_asset(path):
            return False
        try:
            with wave.open(str(path), "rb") as reader:
                return reader.getnchannels() == expected_channels and reader.getnframes() >= 0
        except Exception:
            return False

    def _copy_file_atomically(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(f"{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temp_path)
            os.replace(temp_path, destination)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def _write_wav_atomically(
        self,
        destination: Path,
        channels: int,
        sample_width: int,
        frame_rate: int,
        frames: bytes,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(f"{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with wave.open(str(temp_path), "wb") as writer:
                writer.setnchannels(channels)
                writer.setsampwidth(sample_width)
                writer.setframerate(frame_rate)
                writer.writeframes(frames)
            os.replace(temp_path, destination)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def _discard_cached_asset(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            return

    def set_listener_gain(self, sfx_volume: float) -> None:
        self._listener_gain = max(0.0, min(1.0, float(sfx_volume)))

    def _stop_source(self, source) -> None:
        try:
            source.stop()
        except Exception:
            return

    def update_source(
        self,
        channel: str,
        x: float,
        y: float,
        z: float,
        gain: float,
        pitch: float = 1.0,
        relative: bool = False,
        velocity_x: float = 0.0,
        velocity_y: float = 0.0,
        velocity_z: float = 0.0,
    ) -> bool:
        if not self.available:
            return False
        source = self._sources.get(channel)
        if source is None or not getattr(source, "playing", False):
            return False
        source.relative = relative
        source.gain = max(0.0, min(1.2, self._listener_gain * float(gain)))
        source.pitch = max(0.5, min(1.5, float(pitch)))
        source.set_position(float(x), float(y), float(z))
        source.set_velocity(float(velocity_x), float(velocity_y), float(velocity_z))
        return True

    def play_sound(
        self,
        key: str,
        path: str,
        channel: str,
        x: float,
        y: float,
        z: float,
        gain: float,
        pitch: float = 1.0,
        loop: bool = False,
        relative: bool = False,
        velocity_x: float = 0.0,
        velocity_y: float = 0.0,
        velocity_z: float = 0.0,
        spatialize: bool = False,
    ) -> bool:
        if not self.available or self._al is None:
            return False
        buffer_key = self.register_sound(key, path, spatialize=spatialize)
        if buffer_key is None:
            return False
        buffer = self._buffers.get(buffer_key)
        if buffer is None:
            return False
        source = self._sources.get(channel)
        if source is None:
            source = self._al.Source()
            source.reference_distance = 1.5
            source.rolloff_factor = 1.0
            source.max_distance = 48.0
            self._sources[channel] = source
        current_key = self._channel_keys.get(channel)
        if current_key != key:
            self._stop_source(source)
            source.set_buffer(buffer)
            self._channel_keys[channel] = key
        elif not loop:
            self._stop_source(source)
        source.relative = relative
        source.looping = loop
        source.gain = max(0.0, min(1.2, self._listener_gain * float(gain)))
        source.pitch = max(0.5, min(1.5, float(pitch)))
        source.set_position(float(x), float(y), float(z))
        source.set_velocity(float(velocity_x), float(velocity_y), float(velocity_z))
        if loop and source.playing:
            return True
        source.play()
        return True

    def stop(self, channel: str) -> None:
        source = self._sources.get(channel)
        if source is None:
            return
        self._stop_source(source)
        self._channel_keys.pop(channel, None)

    def is_channel_playing(self, channel: str) -> bool:
        if not self.available:
            return False
        source = self._sources.get(channel)
        if source is None:
            return False
        try:
            return bool(source.playing)
        except Exception:
            return False

    def shutdown(self) -> None:
        for source in self._sources.values():
            self._stop_source(source)
        self._sources.clear()
        self._channel_keys.clear()
        self._buffers.clear()
        self._buffer_paths.clear()
        self._context = None
        self._device = None
        if self._al is None:
            return
        quit_openal = getattr(self._al, "quit", None)
        if callable(quit_openal):
            try:
                quit_openal()
            except Exception:
                return
