from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

_TRANSLATION_SEPARATOR = " [=] "
_PLACEHOLDER_PATTERN = re.compile(r"%t?[1-9]")


@dataclass(frozen=True)
class _CompiledPattern:
    regex: re.Pattern[str]
    replacement: str
    parameter_order: tuple[int, ...]
    translated_parameters: frozenset[int]


class _LanguagePack:

    def __init__(self, name: str, exact_entries: dict[str, str], pattern_entries: tuple[_CompiledPattern, ...]):
        self.name = name
        self.exact_entries = exact_entries
        self.pattern_entries = pattern_entries


@dataclass(frozen=True)
class _LanguageSource:
    key: str
    display_name: str
    lng_path: Path | None
    version: str
    author: str


@dataclass(frozen=True)
class LanguageEntry:
    key: str
    name: str
    version: str
    author: str


_ACTIVE_PACK = _LanguagePack("english", {}, ())


def _resource_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _langs_dir() -> Path:
    return _resource_base_dir() / "langs"


def _normalize_language_key(value: object) -> str:
    normalized = str(value or "english").strip().lower()
    return normalized or "english"


def _default_display_name(language_key: str) -> str:
    normalized = _normalize_language_key(language_key)
    return normalized.replace("_", " ").replace("-", " ").title()


def _safe_manifest_text(value: object) -> str:
    return str(value or "").strip()


def _load_manifest(manifest_path: Path) -> dict[str, object] | None:
    try:
        raw = manifest_path.read_text(encoding="utf-8-sig")
        decoded = json.loads(raw)
    except Exception:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def _find_language_file_in_directory(directory: Path, preferred_name: str | None) -> Path | None:
    if preferred_name:
        preferred_path = directory / preferred_name
        if preferred_path.exists() and preferred_path.is_file():
            return preferred_path
    lng_files = sorted(path for path in directory.glob("*.lng") if path.is_file())
    if not lng_files:
        return None
    return lng_files[0]


def _discover_language_sources() -> dict[str, _LanguageSource]:
    sources: dict[str, _LanguageSource] = {
        "english": _LanguageSource(
            key="english",
            display_name="English",
            lng_path=None,
            version="",
            author="",
        )
    }
    langs_path = _langs_dir()
    if not langs_path.exists() or not langs_path.is_dir():
        return sources
    for item in sorted((path for path in langs_path.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
        manifest_path = item / "manifest.json"
        manifest = _load_manifest(manifest_path)
        language_key = _normalize_language_key(manifest.get("id") if manifest is not None else item.name)
        language_file_name = (
            _safe_manifest_text(manifest.get("language_file")) if manifest is not None else ""
        ) or (
            _safe_manifest_text(manifest.get("lng_file")) if manifest is not None else ""
        )
        lng_path = _find_language_file_in_directory(item, language_file_name or None)
        if language_key == "english" or lng_path is None:
            continue
        display_name = (
            _safe_manifest_text(manifest.get("name")) if manifest is not None else ""
        ) or _default_display_name(language_key)
        version = _safe_manifest_text(manifest.get("version")) if manifest is not None else ""
        author = _safe_manifest_text(manifest.get("author")) if manifest is not None else ""
        sources[language_key] = _LanguageSource(
            key=language_key,
            display_name=display_name,
            lng_path=lng_path,
            version=version,
            author=author,
        )
    for item in sorted(langs_path.glob("*.lng"), key=lambda path: path.name.casefold()):
        language_key = _normalize_language_key(item.stem)
        if language_key in {"", "english"} or language_key in sources:
            continue
        sources[language_key] = _LanguageSource(
            key=language_key,
            display_name=_default_display_name(language_key),
            lng_path=item,
            version="",
            author="",
        )
    return sources


def available_languages() -> list[str]:
    sources = _discover_language_sources()
    discovered = sorted(
        (key for key in sources.keys() if key != "english"),
        key=lambda key: (sources[key].display_name.casefold(), key),
    )
    return ["english", *discovered]


def available_language_entries() -> list[LanguageEntry]:
    sources = _discover_language_sources()
    ordered_keys = available_languages()
    entries: list[LanguageEntry] = []
    for key in ordered_keys:
        source = sources.get(key)
        if source is None:
            entries.append(LanguageEntry(key=key, name=_default_display_name(key), version="", author=""))
            continue
        entries.append(
            LanguageEntry(
                key=source.key,
                name=source.display_name,
                version=source.version,
                author=source.author,
            )
        )
    return entries


def language_display_name(language_name: str) -> str:
    normalized = _normalize_language_key(language_name)
    source = _discover_language_sources().get(normalized)
    if source is not None:
        return source.display_name
    return _default_display_name(normalized)


def current_language() -> str:
    return _ACTIVE_PACK.name


def set_language(language_name: str | None) -> str:
    normalized = _normalize_language_key(language_name)
    if normalized == "english":
        _set_active_pack(_LanguagePack("english", {}, ()))
        return "english"
    source = _discover_language_sources().get(normalized)
    if source is None or source.lng_path is None:
        _set_active_pack(_LanguagePack("english", {}, ()))
        return "english"
    try:
        contents = source.lng_path.read_text(encoding="utf-8")
    except Exception:
        _set_active_pack(_LanguagePack("english", {}, ()))
        return "english"
    exact_entries, pattern_entries = _parse_language_file(contents)
    _set_active_pack(_LanguagePack(normalized, exact_entries, pattern_entries))
    return normalized


def translate_text(value: object) -> str:
    return _translate_text(str(value), depth=0)


def _translate_text(source: str, depth: int) -> str:
    if not source:
        return source
    if depth >= 4:
        return source
    active_pack = _ACTIVE_PACK
    if active_pack.name == "english":
        return source
    exact_match = active_pack.exact_entries.get(source.casefold())
    if exact_match is not None:
        return exact_match
    for pattern in active_pack.pattern_entries:
        match = pattern.regex.fullmatch(source)
        if match is None:
            continue
        parameters: dict[int, str] = {}
        for parameter_index in pattern.parameter_order:
            group_value = str(match.group(f"p{parameter_index}") or "")
            if parameter_index in pattern.translated_parameters:
                group_value = _translate_text(group_value, depth + 1)
            else:
                translated_group = _translate_text(group_value, depth + 1)
                if translated_group:
                    group_value = translated_group
            parameters[parameter_index] = group_value
        translated = pattern.replacement
        for parameter_index in pattern.parameter_order:
            translated = translated.replace(f"%{parameter_index}", parameters.get(parameter_index, ""))
        return translated
    return source


def _set_active_pack(pack: _LanguagePack) -> None:
    global _ACTIVE_PACK
    _ACTIVE_PACK = pack


def _parse_language_file(contents: str) -> tuple[dict[str, str], tuple[_CompiledPattern, ...]]:
    exact_entries: dict[str, str] = {}
    compiled_patterns: list[_CompiledPattern] = []
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if _TRANSLATION_SEPARATOR not in line:
            continue
        left, right = line.split(_TRANSLATION_SEPARATOR, 1)
        key = left.strip()
        replacement = right.strip()
        if not key:
            continue
        placeholder_matches = list(_PLACEHOLDER_PATTERN.finditer(key))
        if not placeholder_matches:
            exact_entries[key.casefold()] = replacement
            continue
        compiled_pattern = _compile_pattern(key, replacement)
        if compiled_pattern is not None:
            compiled_patterns.append(compiled_pattern)
    compiled_patterns.sort(key=_pattern_sort_key)
    return exact_entries, tuple(compiled_patterns)


def _pattern_sort_key(item: _CompiledPattern) -> tuple[int, int]:
    placeholder_count = len(item.parameter_order)
    literal_length = len(item.regex.pattern)
    return (-placeholder_count, -literal_length)


def _compile_pattern(key: str, replacement: str) -> _CompiledPattern | None:
    parameter_order: list[int] = []
    translated_parameters: set[int] = set()
    pattern_parts: list[str] = []
    cursor = 0
    for token in _PLACEHOLDER_PATTERN.finditer(key):
        start, end = token.span()
        pattern_parts.append(re.escape(key[cursor:start]))
        raw_token = token.group(0)
        is_translated_parameter = raw_token.startswith("%t")
        parameter_index = int(raw_token[-1])
        if parameter_index not in parameter_order:
            parameter_order.append(parameter_index)
        if is_translated_parameter:
            translated_parameters.add(parameter_index)
        pattern_parts.append(f"(?P<p{parameter_index}>.+?)")
        cursor = end
    pattern_parts.append(re.escape(key[cursor:]))
    try:
        compiled_regex = re.compile("".join(pattern_parts), re.IGNORECASE | re.DOTALL)
    except re.error:
        return None
    return _CompiledPattern(regex=compiled_regex, replacement=replacement, parameter_order=tuple(parameter_order), translated_parameters=frozenset(translated_parameters))
