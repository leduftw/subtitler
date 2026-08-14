"""Run configuration: the resolved settings for a single transcription run."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import providers
from .errors import UserFacingError

# Generic defaults that don't depend on the chosen provider.
DEFAULT_AUDIO_BITRATE = "48k"
DEFAULT_SAMPLE_RATE = "16000"
DEFAULT_API_TIMEOUT_SECONDS = 1800

# Upper bound on distinct speakers for diarization. Generous enough for panels
# and interviews; Azure accepts 2-35.
DEFAULT_MAX_SPEAKERS = 8


@dataclass(frozen=True)
class RunConfig:
    input_path: Path
    output_path: Path
    provider: str
    language: str | None
    azure_model: str
    azure_endpoint: str | None
    azure_transcribe_style: str
    audio_format: str
    audio_bitrate: str
    sample_rate: str
    max_upload_mib: int
    diarize: bool
    max_speakers: int
    tag_audio_events: bool
    keep_audio: bool
    force: bool
    dry_run: bool
    work_dir: Path | None
    api_timeout_seconds: int


def build_config(args: argparse.Namespace) -> RunConfig:
    """Resolve parsed CLI arguments into a fully materialized :class:`RunConfig`."""
    if not args.input:
        raise UserFacingError("input file is required unless --list-languages is used")

    provider_spec = providers.spec(args.provider)
    input_path = Path(args.input).expanduser().resolve()

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        language_suffix = args.language or "auto"
        output_path = Path.cwd() / "outputs" / f"{input_path.stem}.{language_suffix}.srt"

    # Provider-specific defaults fill in for the "auto"/unset sentinels.
    audio_format = args.audio_format if args.audio_format != "auto" else provider_spec.default_audio_format
    max_upload_mib = args.max_upload_mib if args.max_upload_mib is not None else provider_spec.default_max_upload_mib

    return RunConfig(
        input_path=input_path,
        output_path=output_path,
        provider=args.provider,
        language=args.language,
        azure_model=args.azure_model,
        azure_endpoint=args.azure_endpoint or os.environ.get("AZURE_SPEECH_ENDPOINT"),
        azure_transcribe_style=args.azure_transcribe_style,
        audio_format=audio_format,
        audio_bitrate=args.audio_bitrate,
        sample_rate=args.sample_rate,
        max_upload_mib=max_upload_mib,
        diarize=resolve_diarize(args.diarize, provider_spec),
        max_speakers=args.max_speakers,
        tag_audio_events=args.tag_audio_events,
        keep_audio=args.keep_audio,
        force=args.force,
        dry_run=args.dry_run,
        work_dir=Path(args.work_dir).expanduser().resolve() if args.work_dir else None,
        api_timeout_seconds=args.api_timeout_seconds,
    )


def resolve_diarize(requested: bool | None, provider_spec: providers.ProviderSpec) -> bool:
    """Decide whether to diarize this run.

    Unset (``None``) means "on where the provider supports it" — diarization is
    free on Azure and a single-speaker recording still renders unlabelled, so
    there's nothing to lose by default. Asking for it explicitly on a provider
    that can't do it is worth a warning rather than a hard error.
    """
    if requested is False:
        return False
    if provider_spec.supports_diarization:
        return True
    if requested is True:
        print(
            f"warning: --diarize is not supported by {provider_spec.name}; continuing without speaker labels. "
            "Use --provider azure-fast or azure-hybrid for speaker-aware subtitles.",
            file=sys.stderr,
        )
    return False
