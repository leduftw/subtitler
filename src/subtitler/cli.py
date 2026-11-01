"""Command-line entry point: argument parsing and top-level dispatch."""

from __future__ import annotations

import argparse
import itertools
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from . import __version__, providers, translate, update
from .config import (
    DEFAULT_API_TIMEOUT_SECONDS,
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_MAX_SPEAKERS,
    DEFAULT_SAMPLE_RATE,
    build_config,
)
from .errors import UsageError, UserFacingError
from .pipeline import run

# The repo's GitHub description as a sentence: subtitler's help and its repo describe it in the same words.
DESCRIPTION = "Subtitles for any video, in any language."

# What a bare `subtitler` adds after its help: the one thing it needs.
MISSING_INPUT = "To make subtitles, pass a video or audio file: subtitler <file>"

# The first word of a command line, when it's one of these, is a command and not
# a file. Writing ./help reaches a file with that name.
COMMANDS = ("help", "version", "update", "upgrade")


class ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message: str | None, file=None) -> None:
        # Python's FORCE_COLOR and PYTHON_COLORS can color a pipe or outrank
        # NO_COLOR; here colors only ever reach a terminal.
        file = file or sys.stderr
        if message and (
            not file.isatty()
            or os.environ.get("NO_COLOR")
            or os.environ.get("TERM") == "dumb"
        ):
            message = re.sub(r"\x1b\[[0-9;]*m", "", message)
        super()._print_message(message, file)


def no_color_requested(parser: ArgumentParser, options: list[str]) -> bool:
    """Recognize the global flag, including argparse's unambiguous abbreviations."""
    for option in options:
        if option == "--no-color":
            return True
        if parser.allow_abbrev and option.startswith("--"):
            matches = [
                name
                for name in parser._option_string_actions
                if name.startswith(option)
            ]
            if matches == ["--no-color"]:
                return True
    return False


def command_words(parser: ArgumentParser, argv: list[str]) -> list[str]:
    """The command this command line starts with, if any; --no-color may come first."""
    words = list(
        itertools.dropwhile(lambda word: no_color_requested(parser, [word]), argv)
    )
    return words if words and words[0] in COMMANDS else []


def keep_printing() -> None:
    """Don't let a character the output can't show fail a run that has done its work.

    On Windows a pipe can only hold the local code page, and a subtitle's file
    name or a word in the guide can be outside it.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def main(argv: Iterable[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    keep_printing()
    # --no-color decides how the help looks, and -h prints the help the moment
    # argparse reaches it, so the flag is read before parsing.
    options = argv[: argv.index("--")] if "--" in argv else argv
    parser = build_parser()
    color = not no_color_requested(parser, options)
    # On Python before 3.14 this attribute is harmless and help stays plain.
    parser.color = color
    if not argv:
        # A bare `subtitler` has nothing to subtitle, so it shows how instead.
        parser.print_help()
        print(f"\n{MISSING_INPUT}")
        return 0

    words = command_words(parser, argv)
    if words:
        return run_command(parser, build_command_parser(color), words)

    args = parser.parse_args(argv)
    try:
        if args.translation_guide:
            print(translate.translation_guide(), end="")
            return 0

        if args.list_languages:
            providers.print_supported_languages(args.provider)
            return 0

        if args.emit_worksheet or args.apply_worksheet:
            return run_translation(args)

        config = build_config(args)
        return run(config)
    except UsageError as exc:
        parser.error(str(exc))
    except (UserFacingError, OSError, UnicodeError) as exc:
        print(f"subtitler: {exc}", file=sys.stderr)
        return 1


def run_command(
    parser: ArgumentParser, commands: ArgumentParser, words: list[str]
) -> int:
    """Run help, version or update, each with a parser of its own."""
    args = commands.parse_args(words)
    if args.command == "help":
        if not args.topic:
            parser.print_help()
            return 0
        # argparse prints that command's help and exits.
        commands.parse_args([args.topic, "--help"])
    if args.command == "version":
        print(f"subtitler {__version__}")
        return 0
    try:
        return update.run()
    except (UserFacingError, OSError) as exc:
        print(f"subtitler: {exc}", file=sys.stderr)
        return 1


def run_translation(args: argparse.Namespace) -> int:
    """Dispatch the two worksheet halves of the translation workflow."""
    if not args.input:
        raise UsageError(
            "an input .srt file is required for --emit-worksheet/--apply-worksheet"
        )
    subtitle_path = Path(args.input).expanduser().resolve()

    if args.emit_worksheet and args.apply_worksheet:
        raise UsageError("pass either --emit-worksheet or --apply-worksheet, not both.")

    if args.emit_worksheet:
        if not args.target_language:
            raise UsageError(
                "--target-language is required with --emit-worksheet, e.g. --target-language en"
            )
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
        raise UsageError(
            "pass --output, or --target-language so the output name can be derived."
        )

    return translate.apply_worksheet_file(
        subtitle_path,
        Path(args.apply_worksheet).expanduser().resolve(),
        output_path,
        args.force,
    )


def parser_style(color: bool) -> dict[str, bool]:
    # argparse colors its help and suggests fixes for typos from Python 3.14 on;
    # older versions print plain text without suggestions.
    if sys.version_info >= (3, 14):
        return {"color": color, "suggest_on_error": True}
    return {}


def build_command_parser(color: bool = True) -> ArgumentParser:
    """The parser behind COMMANDS, used only when a command line starts with one."""
    parser = ArgumentParser(prog="subtitler", add_help=False, **parser_style(color))
    commands = parser.add_subparsers(dest="command", required=True)
    show_help = commands.add_parser(
        "help", description="Show the help, or the help of one command."
    )
    show_help.add_argument("topic", nargs="?", choices=COMMANDS, metavar="command")
    show_version = commands.add_parser(
        "version", description="Show the version and exit."
    )
    updater = commands.add_parser(
        "update",
        aliases=["upgrade"],
        description=(
            "Update subtitler to the latest release, the same way it was installed."
        ),
    )
    for command in (show_help, show_version, updater):
        command.add_argument(
            "--no-color",
            action="store_true",
            help="Print without colors, like NO_COLOR=1.",
        )
    return parser


def build_parser(color: bool = True) -> ArgumentParser:
    parser = ArgumentParser(
        prog="subtitler",
        description=DESCRIPTION,
        epilog=(
            "Language hints use short codes such as en=English, de=German, es=Spanish. "
            "Run `subtitler --list-languages` for the provider-specific language/code list."
        ),
        **parser_style(color),
    )
    parser.add_argument_group(
        "commands",
        "subtitler help [command] and subtitler version work like --help and --version, "
        "and subtitler update (or upgrade) moves to the latest release. To read a file "
        "with one of these names, write ./help.",
    )
    parser.add_argument("input", nargs="?", help="Input video or audio file.")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"subtitler {__version__}",
        help="Show the version and exit.",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Print without colors, like NO_COLOR=1."
    )
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
        help="Extracted audio format. Default: auto (the selected provider's preferred format).",
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
        help="Maximum upload size in MiB. Defaults to the selected provider's upload limit.",
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
        "reads them back and rebuilds the subtitles on the original timings. An agent "
        "doing the translating should read --translation-guide first.",
    )
    translation.add_argument(
        "--translation-guide",
        action="store_true",
        help="Print the instructions for translating subtitles well, then exit.",
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
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the extracted audio file after the run.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output SRT if it already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract audio and print the cost estimate, but skip the transcription provider's API call.",
    )
    return parser
