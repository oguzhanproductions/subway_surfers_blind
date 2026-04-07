from __future__ import annotations

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

GITHUB_API_VERSION = "2022-11-28"
REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"{APP_NAME} Updater",
    "X-GitHub-Api-Version": GITHUB_API_VERSION,
}
VERSION_PATTERN = re.compile(r"^\s*v?(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?:[-+].*)?\s*$")
DOWNLOAD_CHUNK_SIZE = 1024 * 256
SAFE_PATH_TOKEN_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
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
    message: str = ""

    @property
    def update_available(self) -> bool:
        return self.status == "update_available" and self.release is not None


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
    matched = VERSION_PATTERN.match(str(version or ""))
    if matched is None:
        return str(version or "").strip()
    major = int(matched.group("major"))
    minor = int(matched.group("minor") or 0)
    patch = int(matched.group("patch") or 0)
    return f"{major}.{minor}.{patch}"


def version_key(version: str) -> tuple[int, int, int]:
    matched = VERSION_PATTERN.match(str(version or ""))
    if matched is None:
        return 0, 0, 0
    return (
        int(matched.group("major") or 0),
        int(matched.group("minor") or 0),
        int(matched.group("patch") or 0),
    )


class GitHubReleaseUpdater:
    def __init__(
        self,
        owner: str = GITHUB_OWNER,
        repository: str = GITHUB_REPOSITORY,
        timeout_seconds: float = 4.0,
    ):
        self.owner = owner
        self.repository = repository
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.latest_release_url = f"https://api.github.com/repos/{owner}/{repository}/releases/latest"
        self.releases_page_url = f"https://github.com/{owner}/{repository}/releases"

    def check_for_updates(self, current_version: str) -> UpdateCheckResult:
        normalized_current = normalize_version(current_version)
        request = urllib.request.Request(self.latest_release_url, headers=REQUEST_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return UpdateCheckResult(
                    status="no_releases",
                    current_version=normalized_current,
                    message="No published releases were found.",
                )
            return UpdateCheckResult(
                status="error",
                current_version=normalized_current,
                message=f"Update check failed with HTTP {error.code}.",
            )
        except Exception:
            return UpdateCheckResult(
                status="error",
                current_version=normalized_current,
                message="Unable to contact GitHub Releases.",
            )

        release = self._parse_release(payload)
        if release is None:
            return UpdateCheckResult(
                status="error",
                current_version=normalized_current,
                message="The latest release data was invalid.",
            )

        if version_key(release.version) > version_key(normalized_current):
            return UpdateCheckResult(
                status="update_available",
                current_version=normalized_current,
                latest_version=release.version,
                release=release,
                message=f"Version {release.version} is available.",
            )
        return UpdateCheckResult(
            status="up_to_date",
            current_version=normalized_current,
            latest_version=release.version,
            release=release,
            message="You already have the latest version.",
        )

    def has_installable_package(self, release: ReleaseInfo) -> bool:
        return self._preferred_zip_asset(release) is not None

    def download_and_install(
        self,
        release: ReleaseInfo,
        progress_callback=None,
    ) -> UpdateInstallResult:
        asset = self._preferred_zip_asset(release)
        if asset is None:
            return UpdateInstallResult(
                success=False,
                message="No ZIP update package was found in the latest release.",
                restart_required=False,
            )

        cache_directory = self._update_cache_directory()
        cache_directory.mkdir(parents=True, exist_ok=True)
        archive_path = cache_directory / asset.name
        install_directory = self._install_directory()
        install_directory.mkdir(parents=True, exist_ok=True)
        staging_directory = self._create_staging_directory(cache_directory, release.version)

        progress = progress_callback or (lambda _progress: None)
        progress(UpdateInstallProgress("download", 0.0, "Starting update download."))

        request = urllib.request.Request(asset.download_url, headers=REQUEST_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout_seconds, 20.0)) as response:
                total_size = int(response.headers.get("Content-Length", "0") or 0)
                written = 0
                with archive_path.open("wb") as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        written += len(chunk)
                        percent = 0.0 if total_size <= 0 else min(100.0, (written / total_size) * 100.0)
                        progress(UpdateInstallProgress("download", percent, f"Downloading update package. {int(percent)} percent."))
        except Exception:
            return UpdateInstallResult(
                success=False,
                message="Unable to download the update package.",
                restart_required=False,
            )

        progress(UpdateInstallProgress("extract", 0.0, "Extracting update package."))
        try:
            self._extract_release_archive(archive_path, staging_directory, progress)
        except Exception:
            return UpdateInstallResult(
                success=False,
                message="Unable to extract the update package.",
                restart_required=False,
            )

        restart_script_path = self._create_restart_script(staging_directory, install_directory, archive_path)
        self._delete_file_if_exists(archive_path)

        progress(UpdateInstallProgress("ready", 100.0, "Update installed. Restart the game to finish applying it."))
        return UpdateInstallResult(
            success=True,
            message="Update installed. Restart the game to finish applying it.",
            restart_required=True,
            restart_script_path=restart_script_path,
        )

    def launch_restart_script(self, restart_script_path: str | None) -> bool:
        if not restart_script_path:
            return False
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", restart_script_path],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            return False

    def open_release_page(self, release: ReleaseInfo | None = None) -> bool:
        target_url = release.page_url if release is not None else self.releases_page_url
        try:
            return bool(webbrowser.open(target_url))
        except Exception:
            return False

    def _parse_release(self, payload: dict) -> ReleaseInfo | None:
        tag_name = normalize_version(str(payload.get("tag_name") or payload.get("name") or ""))
        if not tag_name:
            return None
        assets: list[ReleaseAsset] = []
        for asset_payload in payload.get("assets", []):
            download_url = str(asset_payload.get("browser_download_url") or "").strip()
            name = str(asset_payload.get("name") or "").strip()
            if not download_url or not name:
                continue
            assets.append(
                ReleaseAsset(
                    name=name,
                    download_url=download_url,
                    content_type=str(asset_payload.get("content_type") or "").strip(),
                    size=int(asset_payload.get("size") or 0),
                )
            )
        return ReleaseInfo(
            version=tag_name,
            page_url=str(payload.get("html_url") or self.releases_page_url).strip(),
            published_at=str(payload.get("published_at") or "").strip(),
            title=str(payload.get("name") or tag_name).strip(),
            notes=str(payload.get("body") or "").strip(),
            assets=tuple(assets),
        )

    def _preferred_zip_asset(self, release: ReleaseInfo) -> ReleaseAsset | None:
        zip_assets = [asset for asset in release.assets if Path(asset.name).suffix.lower() == ".zip"]
        if not zip_assets:
            return None
        zip_assets.sort(key=lambda asset: asset.name.lower())
        return zip_assets[0]

    def _extract_release_archive(self, archive_path: Path, staging_directory: Path, progress_callback) -> None:
        with zipfile.ZipFile(archive_path, "r") as archive:
            file_infos = [info for info in archive.infolist() if not info.is_dir()]
            root_prefix = self._common_archive_root(file_infos)
            total_entries = max(1, len(file_infos))
            for entry_index, info in enumerate(file_infos, start=1):
                relative_path = self._normalized_member_path(info.filename, root_prefix)
                if relative_path is None:
                    continue
                target_path = staging_directory.joinpath(*relative_path.parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_handle, target_path.open("wb") as destination_handle:
                    shutil.copyfileobj(source_handle, destination_handle)
                percent = min(100.0, (entry_index / total_entries) * 100.0)
                progress_callback(
                    UpdateInstallProgress(
                        "extract",
                        percent,
                        f"Extracting update package. {int(percent)} percent.",
                    )
                )

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
        if root_prefix is not None and parts and parts[0] == root_prefix:
            parts = parts[1:]
        sanitized_parts = [part for part in parts if part not in {"", ".", ".."}]
        if not sanitized_parts:
            return None
        return Path(*sanitized_parts)

    def _install_directory(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent

    def _update_cache_directory(self) -> Path:
        return BASE_DIR / "updates"

    def _create_staging_directory(self, cache_directory: Path, version: str) -> Path:
        safe_version = SAFE_PATH_TOKEN_PATTERN.sub("_", normalize_version(version) or "latest").strip("._") or "latest"
        return Path(tempfile.mkdtemp(prefix=f"release_{safe_version}_", dir=cache_directory))

    def _delete_file_if_exists(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            return

    def _create_restart_script(self, staging_directory: Path, install_directory: Path, archive_path: Path) -> str:
        script_directory = Path(tempfile.mkdtemp(prefix="subway_blind_update_"))
        script_path = script_directory / "apply_update.cmd"
        launch_path = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else install_directory / "main.py"
        script_path.write_text(
            "@echo off\n"
            "setlocal\n"
            f"set STAGE={staging_directory}\n"
            f"set TARGET={install_directory}\n"
            f"set ARCHIVE={archive_path}\n"
            "set RETRIES=0\n"
            f"set MAX_RETRIES={MAX_RESTART_COPY_RETRIES}\n"
            ":retry\n"
            "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
            "$ErrorActionPreference = 'Stop'; "
            "Copy-Item -LiteralPath '%STAGE%\\*' -Destination '%TARGET%' -Recurse -Force\" >nul 2>nul\n"
            "if errorlevel 1 (\n"
            "  set /a RETRIES=%RETRIES%+1\n"
            "  if %RETRIES% GEQ %MAX_RETRIES% exit /b 1\n"
            "  timeout /t 1 /nobreak >nul\n"
            "  goto retry\n"
            ")\n"
            "rmdir /S /Q \"%STAGE%\" >nul 2>nul\n"
            "del /Q \"%ARCHIVE%\" >nul 2>nul\n"
            f"start \"\" \"{launch_path}\"\n"
            "exit /b 0\n",
            encoding="utf-8",
        )
        return str(script_path)
