"""The transcription pipeline: probe, extract audio, transcribe, write SRT."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import providers
from .config import RunConfig
from .errors import UserFacingError
from .media import (
    ensure_input,
    ensure_output,
    ensure_tool,
    extract_audio,
    format_bytes,
    probe_duration_seconds,
)
from .srt import Cue, normalize_srt_text, render_srt


def run(config: RunConfig) -> int:
    """Run the full pipeline for one input file. Returns a process exit code."""
    ensure_tool("ffmpeg")
    ensure_tool("ffprobe")
    ensure_input(config.input_path)
    ensure_output(config.output_path, force=config.force, dry_run=config.dry_run)

    provider = providers.build(config)
    _print_cost_estimate(config, provider)

    if not config.dry_run:
        provider.validate()

    with audio_workspace(config) as audio_path:
        extract_audio(
            config.input_path,
            audio_path,
            sample_rate=config.sample_rate,
            audio_bitrate=config.audio_bitrate,
            audio_format=config.audio_format,
        )
        upload_size = audio_path.stat().st_size
        print(f"Extracted audio: {audio_path} ({format_bytes(upload_size)})")

        max_upload_bytes = config.max_upload_mib * 1024 * 1024
        if upload_size > max_upload_bytes:
            raise UserFacingError(
                f"extracted audio is {format_bytes(upload_size)}, above the {config.max_upload_mib} MiB limit. "
                "Retry with a lower --audio-bitrate, or add chunking before using longer files."
            )

        if config.dry_run:
            print(f"Dry run: skipping the {provider.spec.label} API call.")
            return 0

        cues = provider.transcribe(audio_path, config.api_timeout_seconds)
        srt_text = render_srt(cues)
        if not srt_text:
            raise UserFacingError(f"{provider.spec.label} returned no subtitle text for this audio.")

        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(normalize_srt_text(srt_text), encoding="utf-8")
        _print_result(cues, config)

    return 0


def _print_result(cues: list[Cue], config: RunConfig) -> None:
    speakers = len({cue.speaker for cue in cues if cue.speaker is not None})
    detail = f"{len(cues)} cues"
    if speakers > 1:
        detail += f", {speakers} speakers"
    elif config.diarize:
        detail += ", single speaker"
    print(f"Wrote SRT: {config.output_path} ({detail})")


def _print_cost_estimate(config: RunConfig, provider: providers.TranscriptionProvider) -> None:
    duration_seconds = probe_duration_seconds(config.input_path)
    if duration_seconds is None:
        return
    minutes = duration_seconds / 60
    estimate = minutes * provider.spec.price_per_minute_usd
    print(f"Input duration: {minutes:.2f} minutes")
    print(f"Estimated {provider.model} transcription cost: ${estimate:.4f}")


@contextmanager
def audio_workspace(config: RunConfig) -> Iterator[Path]:
    """Yield the path for extracted audio, handling temp dirs and cleanup.

    - ``--work-dir`` uses that directory and leaves it in place.
    - ``--keep-audio`` writes into ``./.work`` and keeps the audio file.
    - Otherwise a private temporary directory is created and removed on exit.
    """
    cleanup_dir: tempfile.TemporaryDirectory[str] | None = None
    if config.work_dir:
        work_root = config.work_dir
    elif config.keep_audio:
        work_root = Path.cwd() / ".work"
    else:
        cleanup_dir = tempfile.TemporaryDirectory(prefix="subtitler-")
        work_root = Path(cleanup_dir.name)

    work_root.mkdir(parents=True, exist_ok=True)
    audio_path = work_root / f"{config.input_path.stem}.{config.audio_format}"
    try:
        yield audio_path
    finally:
        if config.keep_audio:
            print(f"Kept extracted audio: {audio_path}")
        elif cleanup_dir is not None:
            cleanup_dir.cleanup()
        elif audio_path.exists():
            audio_path.unlink()
