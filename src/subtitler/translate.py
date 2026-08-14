"""Translate finished subtitle cues into another language.

No speech provider offers translation *and* word-level timing *and* speakers in
one call — Azure's LLM Speech ``translate`` task explicitly drops both word
offsets and diarization, and ElevenLabs Scribe doesn't translate at all. So
translation is a second stage over cues that are already correctly timed: only
the text changes, and the timing and speaker data carry straight over.

The hard part is *context*. Cues are split for reading speed, not for meaning, so
a sentence routinely spans three of them:

```text
y gracias por venir a esta reunión que,
como ya saben, hemos aplazado
tres veces.
```

Translating those lines independently produces nonsense. But translating the
merged paragraph produces text that can't be mapped back — a translation shares
no words with its source, so nothing can re-align it to the original cues
(unlike :mod:`.align`, which relies on both sides being the same language).

The worksheet format resolves that: cues are grouped into speaker turns so a
translator can read whole sentences, while each line keeps a number so the
result can be reassembled onto the original timings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import UserFacingError
from .srt import Cue, format_srt_timestamp, normalize_srt_text, parse_srt, render_srt

WORKSHEET_VERSION = "v1"

_LINE = re.compile(r"^\s*(\d+)\s*\|(.*)$")
_TURN = re.compile(r"^\s*\[([^\]]+)\]")

_INSTRUCTIONS = """\
# subtitler worksheet {version}
# source: {source}    target: {target}
#
# HOW TO TRANSLATE THIS FILE
#
# Each [SPEAKER] block is one continuous utterance. Its lines are subtitle cues,
# split for reading speed, so sentences run across several lines and a single
# line is often a fragment that means nothing on its own.
#
#   1. Read the whole block first and work out the complete sentences.
#   2. Translate the block as a whole into {target}.
#   3. Redistribute your translation across the SAME numbered lines, breaking at
#      natural phrase boundaries.
#
# Rules:
#   - Keep every line number, exactly once, in order. Do not merge, split, drop,
#     add, or renumber lines.
#   - Keep the "N|" prefix. Everything after it is the text to replace.
#   - A line may end mid-sentence. That is expected — do not "complete" it.
#   - Keep any leading "- " (it marks a change of speaker).
#   - Leave [SPEAKER] and timestamp headers untouched; they are context for you.
"""


@dataclass(frozen=True)
class Turn:
    """A run of consecutive cues from one speaker, with their 1-based numbers."""

    speaker: int | None
    numbers: list[int]
    cues: list[Cue]


def group_into_turns(cues: list[Cue]) -> list[Turn]:
    """Group consecutive cues by speaker, preserving each cue's 1-based number.

    Cues parsed back from an SRT have no speaker field, so the ``- `` turn marker
    is used as the boundary signal instead.
    """
    turns: list[Turn] = []
    for index, cue in enumerate(cues, start=1):
        starts_turn = cue.text.lstrip().startswith("- ")
        same_speaker = (
            turns
            and not starts_turn
            and (cue.speaker == turns[-1].speaker if cue.speaker is not None else True)
        )
        if same_speaker:
            turns[-1].numbers.append(index)
            turns[-1].cues.append(cue)
        else:
            turns.append(Turn(cue.speaker, [index], [cue]))
    return turns


def speaker_label(turn: Turn, fallback_index: int) -> str:
    """A short human label for a turn: A, B, C… by speaker id where known."""
    if turn.speaker is None:
        return "?"
    return chr(ord("A") + turn.speaker % 26)


def emit_worksheet(cues: list[Cue], source_language: str, target_language: str) -> str:
    """Render cues as a translation worksheet."""
    if not cues:
        raise UserFacingError("there are no cues to translate.")

    parts = [_INSTRUCTIONS.format(version=WORKSHEET_VERSION, source=source_language, target=target_language)]
    for position, turn in enumerate(group_into_turns(cues)):
        parts.append(f"\n[{speaker_label(turn, position)}] {format_srt_timestamp(turn.cues[0].start_ms)}")
        for number, cue in zip(turn.numbers, turn.cues):
            parts.append(f"{number}| " + " ".join(cue.text.split()))
    return "\n".join(parts) + "\n"


def apply_worksheet(worksheet: str, cues: list[Cue]) -> list[Cue]:
    """Rebuild cues from a translated worksheet, keeping the original timings.

    Raises :class:`UserFacingError` when the worksheet doesn't line up with the
    cues — a missing or duplicated number would silently shift every later
    subtitle onto the wrong timestamp, so it's checked rather than guessed at.
    """
    translated: dict[int, str] = {}
    for raw in worksheet.split("\n"):
        if raw.lstrip().startswith("#") or _TURN.match(raw):
            continue
        match = _LINE.match(raw)
        if not match:
            continue
        number = int(match.group(1))
        if number in translated:
            raise UserFacingError(f"worksheet line {number} appears more than once.")
        translated[number] = match.group(2).strip()

    expected = set(range(1, len(cues) + 1))
    missing = sorted(expected - translated.keys())
    extra = sorted(translated.keys() - expected)
    if missing:
        raise UserFacingError(
            f"worksheet is missing {len(missing)} of {len(cues)} lines "
            f"(first missing: {missing[0]}). Every numbered line must be kept."
        )
    if extra:
        raise UserFacingError(f"worksheet has unexpected line numbers: {extra[:5]}")

    rebuilt: list[Cue] = []
    for index, cue in enumerate(cues, start=1):
        text = translated[index]
        if not text:
            continue  # A line translated to nothing simply drops out.
        rebuilt.append(Cue(cue.start_ms, cue.end_ms, text, cue.speaker))

    if not rebuilt:
        raise UserFacingError("the translated worksheet contained no text.")
    return rebuilt


# --- File-level entry points used by the CLI -----------------------------------


def read_subtitle_cues(path: Path) -> list[Cue]:
    """Load an existing SRT file as cues."""
    if not path.is_file():
        raise UserFacingError(f"subtitle file not found: {path}")
    cues = parse_srt(path.read_text(encoding="utf-8"))
    if not cues:
        raise UserFacingError(f"no subtitle cues found in {path} (is it an .srt file?)")
    return cues


def emit_worksheet_file(
    subtitle_path: Path,
    worksheet_path: Path,
    source_language: str | None,
    target_language: str,
) -> int:
    """Write a translation worksheet for ``subtitle_path``. Returns an exit code."""
    cues = read_subtitle_cues(subtitle_path)
    worksheet = emit_worksheet(cues, source_language or "auto", target_language)
    worksheet_path.parent.mkdir(parents=True, exist_ok=True)
    worksheet_path.write_text(worksheet, encoding="utf-8")
    turns = len(group_into_turns(cues))
    print(f"Wrote worksheet: {worksheet_path} ({len(cues)} lines in {turns} speaker turns)")
    print(f"Translate the numbered lines into {target_language}, then rerun with --apply-worksheet.")
    return 0


def apply_worksheet_file(
    subtitle_path: Path,
    worksheet_path: Path,
    output_path: Path,
    force: bool,
) -> int:
    """Rebuild a translated SRT from a worksheet. Returns an exit code."""
    if output_path.exists() and not force:
        raise UserFacingError(f"{output_path} already exists. Pass --force to overwrite.")
    if not worksheet_path.is_file():
        raise UserFacingError(f"worksheet not found: {worksheet_path}")

    cues = read_subtitle_cues(subtitle_path)
    translated = apply_worksheet(worksheet_path.read_text(encoding="utf-8"), cues)

    srt = render_srt(translated)
    if not srt:
        raise UserFacingError("the translated worksheet produced no subtitles.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(normalize_srt_text(srt), encoding="utf-8")
    print(f"Wrote SRT: {output_path} ({len(translated)} cues, timings unchanged)")
    return 0
