from __future__ import annotations
from subway_blind.strings import sx as _sx
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
import zipfile
from subway_blind.config import BASE_DIR
from subway_blind.version import APP_NAME, GITHUB_OWNER, GITHUB_REPOSITORY
GITHUB_API_VERSION = _sx(2156)
REQUEST_HEADERS = {_sx(2157): _sx(2160), _sx(2158): _sx(2161).format(APP_NAME), _sx(2159): GITHUB_API_VERSION}
VERSION_PATTERN = re.compile(_sx(2162))
DOWNLOAD_CHUNK_SIZE = 1024 * 256
SAFE_PATH_TOKEN_PATTERN = re.compile(_sx(2163))
MAX_RESTART_COPY_RETRIES = 180

@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    content_type: str
    size: int

@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    page_url: str
    published_at: str
    title: str
    notes: str
    assets: tuple[ReleaseAsset, ...]

@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    current_version: str
    latest_version: str | None = None
    release: ReleaseInfo | None = None
    message: str = _sx(2)

    @property
    def update_available(self) -> bool:
        return self.status == _sx(2177) and self.release is not None

@dataclass(frozen=True)
class UpdateInstallProgress:
    stage: str
    percent: float
    message: str

@dataclass(frozen=True)
class UpdateInstallResult:
    success: bool
    message: str
    restart_required: bool
    restart_script_path: str | None = None

def normalize_version(version: str) -> str:
    matched = VERSION_PATTERN.match(str(version or _sx(2)))
    if matched is None:
        return str(version or _sx(2)).strip()
    major = int(matched.group(_sx(2168)))
    minor = int(matched.group(_sx(2178)) or 0)
    patch = int(matched.group(_sx(2179)) or 0)
    return _sx(2164).format(major, minor, patch)

def version_key(version: str) -> tuple[int, int, int]:
    matched = VERSION_PATTERN.match(str(version or _sx(2)))
    if matched is None:
        return (0, 0, 0)
    return (int(matched.group(_sx(2168)) or 0), int(matched.group(_sx(2178)) or 0), int(matched.group(_sx(2179)) or 0))

class GitHubReleaseUpdater:

    def __init__(self, owner: str=GITHUB_OWNER, repository: str=GITHUB_REPOSITORY, timeout_seconds: float=4.0):
        self.owner = owner
        self.repository = repository
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.latest_release_url = _sx(2166).format(owner, repository)
        self.releases_page_url = _sx(2167).format(owner, repository)

    def check_for_updates(self, current_version: str) -> UpdateCheckResult:
        normalized_current = normalize_version(current_version)
        request = urllib.request.Request(self.latest_release_url, headers=REQUEST_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode(_sx(386)))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return UpdateCheckResult(status=_sx(2212), current_version=normalized_current, message=_sx(2213))
            return UpdateCheckResult(status=_sx(1007), current_version=normalized_current, message=_sx(2200).format(error.code))
        except Exception:
            return UpdateCheckResult(status=_sx(1007), current_version=normalized_current, message=_sx(2201))
        release = self._parse_release(payload)
        if release is None:
            return UpdateCheckResult(status=_sx(1007), current_version=normalized_current, message=_sx(2192))
        if version_key(release.version) > version_key(normalized_current):
            return UpdateCheckResult(status=_sx(2177), current_version=normalized_current, latest_version=release.version, release=release, message=_sx(2193).format(release.version))
        return UpdateCheckResult(status=_sx(2180), current_version=normalized_current, latest_version=release.version, release=release, message=_sx(2181))

    def has_installable_package(self, release: ReleaseInfo) -> bool:
        return self._preferred_zip_asset(release) is not None

    def download_and_install(self, release: ReleaseInfo, progress_callback=None) -> UpdateInstallResult:
        asset = self._preferred_zip_asset(release)
        if asset is None:
            return UpdateInstallResult(success=False, message=_sx(2194), restart_required=False)
        cache_directory = self._update_cache_directory()
        cache_directory.mkdir(parents=True, exist_ok=True)
        archive_path = cache_directory / asset.name
        install_directory = self._install_directory()
        install_directory.mkdir(parents=True, exist_ok=True)
        staging_directory = self._create_staging_directory(cache_directory, release.version)
        progress = progress_callback or (lambda _progress: None)
        progress(UpdateInstallProgress(_sx(761), 0.0, _sx(762)))
        request = urllib.request.Request(asset.download_url, headers=REQUEST_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout_seconds, 20.0)) as response:
                total_size = int(response.headers.get(_sx(2215), _sx(297)) or 0)
                written = 0
                with archive_path.open(_sx(1920)) as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        written += len(chunk)
                        percent = 0.0 if total_size <= 0 else min(100.0, written / total_size * 100.0)
                        progress(UpdateInstallProgress(_sx(761), percent, _sx(2217).format(int(percent))))
        except Exception:
            return UpdateInstallResult(success=False, message=_sx(2204), restart_required=False)
        progress(UpdateInstallProgress(_sx(1849), 0.0, _sx(2182)))
        try:
            self._extract_release_archive(archive_path, staging_directory, progress)
        except Exception:
            return UpdateInstallResult(success=False, message=_sx(2205), restart_required=False)
        restart_script_path = self._create_restart_script(staging_directory, install_directory, archive_path)
        self._delete_file_if_exists(archive_path)
        progress(UpdateInstallProgress(_sx(769), 100.0, _sx(2183)))
        return UpdateInstallResult(success=True, message=_sx(2183), restart_required=True, restart_script_path=restart_script_path)

    def launch_restart_script(self, restart_script_path: str | None) -> bool:
        if not restart_script_path:
            return False
        try:
            subprocess.Popen([_sx(2195), _sx(2196), restart_script_path], creationflags=getattr(subprocess, _sx(2206), 0))
            return True
        except Exception:
            return False

    def open_release_page(self, release: ReleaseInfo | None=None) -> bool:
        target_url = release.page_url if release is not None else self.releases_page_url
        try:
            return bool(webbrowser.open(target_url))
        except Exception:
            return False

    def _parse_release(self, payload: dict) -> ReleaseInfo | None:
        tag_name = normalize_version(str(payload.get(_sx(2207)) or payload.get(_sx(2208)) or _sx(2)))
        if not tag_name:
            return None
        assets: list[ReleaseAsset] = []
        for asset_payload in payload.get(_sx(87), []):
            download_url = str(asset_payload.get(_sx(2218)) or _sx(2)).strip()
            name = str(asset_payload.get(_sx(2208)) or _sx(2)).strip()
            if not download_url or not name:
                continue
            assets.append(ReleaseAsset(name=name, download_url=download_url, content_type=str(asset_payload.get(_sx(2223)) or _sx(2)).strip(), size=int(asset_payload.get(_sx(2220)) or 0)))
        return ReleaseInfo(version=tag_name, page_url=str(payload.get(_sx(2221)) or self.releases_page_url).strip(), published_at=str(payload.get(_sx(1872)) or _sx(2)).strip(), title=str(payload.get(_sx(2208)) or tag_name).strip(), notes=str(payload.get(_sx(2222)) or _sx(2)).strip(), assets=tuple(assets))

    def _preferred_zip_asset(self, release: ReleaseInfo) -> ReleaseAsset | None:
        zip_assets = [asset for asset in release.assets if Path(asset.name).suffix.lower() == _sx(2197)]
        if not zip_assets:
            return None
        zip_assets.sort(key=lambda asset: asset.name.lower())
        return zip_assets[0]

    def _extract_release_archive(self, archive_path: Path, staging_directory: Path, progress_callback) -> None:
        with zipfile.ZipFile(archive_path, _sx(385)) as archive:
            file_infos = [info for info in archive.infolist() if not info.is_dir()]
            root_prefix = self._common_archive_root(file_infos)
            total_entries = max(1, len(file_infos))
            for entry_index, info in enumerate(file_infos, start=1):
                relative_path = self._normalized_member_path(info.filename, root_prefix)
                if relative_path is None:
                    continue
                target_path = staging_directory.joinpath(*relative_path.parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, _sx(385)) as source_handle, target_path.open(_sx(1920)) as destination_handle:
                    shutil.copyfileobj(source_handle, destination_handle)
                percent = min(100.0, entry_index / total_entries * 100.0)
                progress_callback(UpdateInstallProgress(_sx(1849), percent, _sx(2209).format(int(percent))))

    def _common_archive_root(self, file_infos: list[zipfile.ZipInfo]) -> str | None:
        if not file_infos:
            return None
        first_parts = PurePosixPath(file_infos[0].filename).parts
        if not first_parts:
            return None
        candidate = first_parts[0]
        for info in file_infos[1:]:
            parts = PurePosixPath(info.filename).parts
            if not parts or parts[0] != candidate:
                return None
        return candidate

    def _normalized_member_path(self, member_name: str, root_prefix: str | None) -> Path | None:
        member_path = PurePosixPath(member_name)
        parts = member_path.parts
        if root_prefix is not None and parts and (parts[0] == root_prefix):
            parts = parts[1:]
        sanitized_parts = [part for part in parts if part not in {_sx(2), _sx(292), _sx(2210)}]
        if not sanitized_parts:
            return None
        return Path(*sanitized_parts)

    def _install_directory(self) -> Path:
        if getattr(sys, _sx(362), False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent

    def _update_cache_directory(self) -> Path:
        return BASE_DIR / _sx(2173)

    def _create_staging_directory(self, cache_directory: Path, version: str) -> Path:
        safe_version = SAFE_PATH_TOKEN_PATTERN.sub(_sx(553), normalize_version(version) or _sx(2174)).strip(_sx(2184)) or _sx(2174)
        return Path(tempfile.mkdtemp(prefix=_sx(2198).format(safe_version), dir=cache_directory))

    def _delete_file_if_exists(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            return

    def _create_restart_script(self, staging_directory: Path, install_directory: Path, archive_path: Path) -> str:
        script_directory = Path(tempfile.mkdtemp(prefix=_sx(2199)))
        script_path = script_directory / _sx(2175)
        launch_path = Path(sys.executable).resolve() if getattr(sys, _sx(362), False) else install_directory / _sx(2185)
        script_path.write_text(_sx(2176).format(staging_directory, install_directory, archive_path, MAX_RESTART_COPY_RETRIES, launch_path), encoding=_sx(386))
        return str(script_path)
