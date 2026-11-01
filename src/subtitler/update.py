"""``subtitler update``: moves to the latest release through whatever installed it.

The channel comes from where subtitler really is, after following links:
Homebrew's ``bin/subtitler`` is only a link into its ``Cellar``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .errors import UserFacingError

PACKAGE = "leduftw-subtitler"
LATEST_RELEASE = "https://github.com/leduftw/subtitler/releases/latest"
INSTALLER_SH = f"{LATEST_RELEASE}/download/subtitler-installer.sh"
INSTALLER_PS1 = f"{LATEST_RELEASE}/download/subtitler-installer.ps1"
# Where a version's WinGet manifest appears once Microsoft has accepted it.
WINGET_MANIFESTS = "https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/l/leduftw/subtitler"
PYPI_RELEASES = f"https://pypi.org/pypi/{PACKAGE}"
USER_AGENT = f"subtitler/{__version__}"
TIMEOUT_SECONDS = 10

# How subtitler was installed. `folder` matters only to the installer.
HOMEBREW = "Homebrew"
WINGET = "WinGet"
UV = "uv"
PIPX = "pipx"
PIP = "pip"
INSTALLER = "the installer"
CLONE = "a clone"


@dataclass(frozen=True)
class Plan:
    """The command that updates subtitler through its channel."""

    manager: str
    command: list[str]
    # SUBTITLER_INSTALL_DIR for the installer, so it replaces this copy.
    install_dir: Path | None = None
    # Windows can't replace a running program, so subtitler starts this and exits.
    detach: bool = False


def channel_of(path: Path, frozen: bool, environment: Path) -> str:
    """Tell the channel from subtitler's resolved path.

    ``path`` is the standalone program when ``frozen``, and otherwise this module
    inside the Python ``environment`` running it. uv and pipx each leave a file
    of their own at the top of the environment they create for a tool.
    """
    text = path.as_posix().replace("\\", "/")
    if frozen:
        if "/Cellar/subtitler/" in text:
            return HOMEBREW
        if "/microsoft/winget/" in text.lower():
            return WINGET
        return INSTALLER
    if (environment / "uv-receipt.toml").is_file():
        return UV
    if (environment / "pipx_metadata.json").is_file():
        return PIPX
    if "/site-packages/" in text or "/dist-packages/" in text:
        return PIP
    return CLONE


def plan(channel: str, folder: Path, windows: bool) -> Plan | None:
    """What updates subtitler on this channel; nothing for a clone."""
    if channel == HOMEBREW:
        return Plan(channel, ["brew", "upgrade", "leduftw/tap/subtitler"])
    if channel == WINGET:
        return Plan(
            channel, ["winget", "upgrade", "--id", "leduftw.subtitler"], detach=True
        )
    if channel == UV:
        return Plan(channel, ["uv", "tool", "upgrade", PACKAGE], detach=windows)
    if channel == PIPX:
        return Plan(channel, ["pipx", "upgrade", PACKAGE], detach=windows)
    if channel == PIP:
        command = [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
        return Plan(channel, command, detach=windows)
    if channel == CLONE:
        return None
    if windows:
        command = ["powershell", "-NoProfile", "-Command", f"irm {INSTALLER_PS1} | iex"]
        return Plan(channel, command, install_dir=folder, detach=True)
    # Download first, so a failed download fails the update instead of piping
    # nothing into `sh`, which would succeed.
    script = f"script=$(curl -fsSL {INSTALLER_SH}) && printf '%s\\n' \"$script\" | sh"
    return Plan(channel, ["sh", "-c", script], install_dir=folder)


def parse_version(text: str) -> tuple[int, ...] | None:
    """A version as three numbers, so 1.10.0 is newer than 1.9.0."""
    parts = text.split(".")
    if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def version_from_url(url: str) -> str | None:
    """The version that GitHub's ``releases/latest`` redirect ends at."""
    _, marker, version = url.partition("/releases/tag/v")
    return version if marker and parse_version(version) else None


def latest_version() -> str:
    request = urllib.request.Request(
        LATEST_RELEASE, headers={"User-Agent": USER_AGENT}, method="HEAD"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            landed = response.geturl()
    except (urllib.error.URLError, TimeoutError) as error:
        raise UserFacingError(f"can't check the latest release: {error}") from error
    version = version_from_url(landed)
    if version is None:
        raise UserFacingError(
            "can't check the latest release: GitHub lists no release of subtitler"
        )
    return version


def published(url: str, where: str) -> bool:
    """Whether a package host has this file yet."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            return True
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return False
        raise UserFacingError(f"can't check {where}: {error}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise UserFacingError(f"can't check {where}: {error}") from error


def not_there_yet(channel: str, latest: str) -> str | None:
    """Why this channel can't deliver ``latest`` yet, if it can't."""
    if channel == WINGET:
        url = f"{WINGET_MANIFESTS}/{latest}/leduftw.subtitler.yaml"
        if not published(url, f"WinGet for {latest}"):
            return (
                f"subtitler {latest} is out, but not on WinGet yet: Microsoft reviews "
                "each new version first, which can take a few days."
            )
    if channel in (UV, PIPX, PIP):
        url = f"{PYPI_RELEASES}/{latest}/json"
        if not published(url, f"PyPI for {latest}"):
            return (
                f"subtitler {latest} is out, but not on PyPI yet: it usually arrives "
                "within minutes of the release."
            )
    return None


def update_environment(chosen: Plan, version: str) -> dict[str, str]:
    environment = dict(os.environ)
    if chosen.install_dir is not None:
        environment["SUBTITLER_INSTALL_DIR"] = str(chosen.install_dir)
        # An old installation pin must not undo the version check before this.
        environment["SUBTITLER_VERSION"] = version
    return environment


def carry_out(chosen: Plan, version: str) -> None:
    environment = update_environment(chosen, version)
    program = chosen.command[0]
    try:
        if chosen.detach:
            subprocess.Popen(chosen.command, env=environment)
            print(
                f"{chosen.manager} finishes the update in this window once subtitler has exited."
            )
            return
        result = subprocess.run(chosen.command, env=environment, check=False)
    except OSError as error:
        raise UserFacingError(f"can't run {program}: {error}") from error
    if result.returncode != 0:
        raise UserFacingError(
            f"{chosen.manager} didn't finish the update (exit code {result.returncode})"
        )


def run() -> int:
    frozen = bool(getattr(sys, "frozen", False))
    location = Path(sys.executable if frozen else __file__).resolve()
    channel = channel_of(location, frozen, Path(sys.prefix))
    chosen = plan(channel, location.parent, os.name == "nt")
    if chosen is None:
        raise UserFacingError(
            f"this subtitler runs from a clone ({location.parent}); "
            "update it with `git pull`"
        )

    latest = latest_version()
    current, newest = parse_version(__version__), parse_version(latest)
    if newest == current:
        print(f"subtitler {__version__} is the latest version.")
        return 0
    if newest < current:
        print(f"subtitler {__version__} is newer than the latest release, {latest}.")
        return 0

    reason = not_there_yet(channel, latest)
    if reason:
        print(reason)
        return 0

    print(f"Updating subtitler {__version__} to {latest} with {chosen.manager}.")
    carry_out(chosen, latest)
    return 0
