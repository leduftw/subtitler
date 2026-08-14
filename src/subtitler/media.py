"""Local media handling via ffmpeg/ffprobe and filesystem preconditions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import UserFacingError


def ensure_tool(name: str) -> None:
    """Raise if a required command-line tool is not on PATH."""
    if shutil.which(name) is None:
        raise UserFacingError(f"{name} is required but was not found on PATH")


def ensure_input(path: Path) -> None:
    """Raise if the input path is missing or is not a regular file."""
    if not path.exists():
        raise UserFacingError(f"input file does not exist: {path}")
    if not path.is_file():
        raise UserFacingError(f"input path is not a file: {path}")


def ensure_output(path: Path, *, force: bool, dry_run: bool) -> None:
    """Raise if the output already exists and would be overwritten."""
    if path.exists() and not force and not dry_run:
        raise UserFacingError(f"output already exists: {path} (use --force to overwrite)")


def probe_duration_seconds(path: Path) -> float | None:
    """Return the media duration in seconds, or ``None`` if ffprobe can't tell."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def extract_audio(
    input_path: Path,
    audio_path: Path,
    *,
    sample_rate: str,
    audio_bitrate: str,
    audio_format: str,
) -> None:
    """Extract the first audio track as a compact mono speech file via ffmpeg."""
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_format == "m4a":
        codec_args = ["-c:a", "aac", "-b:a", audio_bitrate]
    elif audio_format == "mp3":
        codec_args = ["-c:a", "libmp3lame", "-b:a", audio_bitrate]
    else:
        raise UserFacingError(f"unsupported audio format: {audio_format}")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        sample_rate,
        *codec_args,
        str(audio_path),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "ffmpeg failed without stderr output"
        raise UserFacingError(f"could not extract audio: {stderr}")


def format_bytes(size: int) -> str:
    """Format a byte count as a human-readable MiB string."""
    mib = size / (1024 * 1024)
    return f"{mib:.2f} MiB"
