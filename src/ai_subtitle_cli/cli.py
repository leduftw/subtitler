"""Command-line entry point: argument parsing and top-level dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from . import providers, translate
from .config import (
    DEFAULT_API_TIMEOUT_SECONDS,
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_MAX_SPEAKERS,
    DEFAULT_SAMPLE_RATE,
    build_config,
)
from .errors import UserFacingError
from .pipeline import run


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.list_languages:
            providers.print_supported_languages(args.provider)
            return 0

        if args.emit_worksheet or args.apply_worksheet:
            return run_translation(args)

        config = build_config(args)
        return run(config)
    except UserFacingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def run_translation(args: argparse.Namespace) -> int:
    """Dispatch the two worksheet halves of the translation workflow."""
    if not args.input:
        raise UserFacingError("an input .srt file is required for --emit-worksheet/--apply-worksheet")
    subtitle_path = Path(args.input).expanduser().resolve()

    if args.emit_worksheet and args.apply_worksheet:
        raise UserFacingError("pass either --emit-worksheet or --apply-worksheet, not both.")

    if args.emit_worksheet:
        if not args.target_language:
            raise UserFacingError("--target-language is required with --emit-worksheet, e.g. --target-language en")
        return translate.emit_worksheet_file(
            subtitle_path,
            Path(args.emit_worksheet).expanduser().resolve(),
            args.language,
            args.target_language,
        )

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    elif args.target_language:
        # film.es.scribe.srt -> film.en.srt
        stem = subtitle_path.stem.split(".")[0]
        output_path = subtitle_path.parent / f"{stem}.{args.target_language}.srt"
    else:
        raise UserFacingError("pass --output, or --target-language so the output name can be derived.")

    return translate.apply_worksheet_file(
        subtitle_path,
        Path(args.apply_worksheet).expanduser().resolve(),
        output_path,
        args.force,
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ai-subtitle",
        description="Generate an SRT subtitle file from a video/audio file.",
        epilog=(
            "Language hints use short codes such as en=English, de=German, es=Spanish. "
            "Run `ai-subtitle --list-languages` for the provider-specific language/code list."
        ),
    )
    parser.add_argument("input", nargs="?", help="Input video or audio file.")
    parser.add_argument(
        "--provider",
        choices=providers.NAMES,
        default=providers.DEFAULT,
        help=f"Transcription provider. Default: {providers.DEFAULT}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output SRT path. Defaults to outputs/<input-stem>.<language-or-auto>.srt.",
    )
    parser.add_argument(
        "--language",
        help="Optional ISO language hint for transcription, e.g. en, de, es. Improves accuracy when known.",
    )
    parser.add_argument(
        "--list-languages",
        action="store_true",
        help="Print transcription language codes for the selected provider and exit.",
    )
    parser.add_argument(
        "--azure-model",
        default=providers.spec(providers.AZURE_MAI).default_model,
        help=(
            "MAI model used for the transcript pass of azure-hybrid. "
            f"Default: {providers.spec(providers.AZURE_MAI).default_model}."
        ),
    )
    parser.add_argument(
        "--azure-endpoint",
        help="Azure Speech endpoint. Defaults to AZURE_SPEECH_ENDPOINT.",
    )
    parser.add_argument(
        "--azure-transcribe-style",
        choices=("display", "verbatim"),
        default="display",
        help="Transcript style for azure-hybrid's MAI pass. Default: display.",
    )
    parser.add_argument(
        "--audio-format",
        choices=("auto", "m4a", "mp3"),
        default="auto",
        help="Extracted audio format. Default: auto (m4a for OpenAI, mp3 for the Azure providers).",
    )
    parser.add_argument(
        "--audio-bitrate",
        default=DEFAULT_AUDIO_BITRATE,
        help=f"Bitrate for extracted speech audio. Default: {DEFAULT_AUDIO_BITRATE}.",
    )
    parser.add_argument(
        "--sample-rate",
        default=DEFAULT_SAMPLE_RATE,
        help=f"Audio sample rate for extracted speech audio. Default: {DEFAULT_SAMPLE_RATE}.",
    )
    parser.add_argument(
        "--max-upload-mib",
        type=int,
        help=(
            "Maximum upload size accepted by the provider. Defaults to 25 MiB for OpenAI, "
            "500 MiB for azure-fast, 300 MiB for azure-hybrid."
        ),
    )
    parser.add_argument(
        "--diarize",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Identify who is speaking and start a new subtitle at each change of speaker. "
            "On by default for providers that support it (azure-fast, azure-hybrid); "
            "pass --no-diarize to turn it off."
        ),
    )
    parser.add_argument(
        "--max-speakers",
        type=int,
        default=DEFAULT_MAX_SPEAKERS,
        help=f"Upper bound on distinct speakers when diarizing (2-35). Default: {DEFAULT_MAX_SPEAKERS}.",
    )
    parser.add_argument(
        "--tag-audio-events",
        action="store_true",
        help="Scribe only: include non-speech events such as (laughter) in the subtitles.",
    )
    parser.add_argument(
        "--work-dir",
        help="Directory for temporary extracted audio. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--api-timeout-seconds",
        type=int,
        default=DEFAULT_API_TIMEOUT_SECONDS,
        help=f"Provider API request timeout. Default: {DEFAULT_API_TIMEOUT_SECONDS} seconds.",
    )
    translation = parser.add_argument_group(
        "translation",
        "Translate an existing .srt into another language. Pass the .srt as the input "
        "file: --emit-worksheet writes the lines out for a translator, --apply-worksheet "
        "reads them back and rebuilds the subtitles on the original timings.",
    )
    translation.add_argument(
        "--emit-worksheet",
        metavar="PATH",
        help="Write a translation worksheet for the input .srt to PATH, then exit.",
    )
    translation.add_argument(
        "--apply-worksheet",
        metavar="PATH",
        help="Rebuild subtitles from a translated worksheet at PATH, keeping the input .srt's timings.",
    )
    translation.add_argument(
        "--target-language",
        help="Language to translate into, e.g. en, de. Used in the worksheet header and the default output name.",
    )
    parser.add_argument("--keep-audio", action="store_true", help="Keep the extracted audio file after the run.")
    parser.add_argument("--force", action="store_true", help="Overwrite the output SRT if it already exists.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract audio and print the cost estimate, but skip the transcription provider's API call.",
    )
    return parser.parse_args(argv)
