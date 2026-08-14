"""SRT subtitle construction: timestamps, line wrapping, and cue grouping.

A :class:`Cue` is one subtitle: when it shows, what it says, and — when the
provider diarized the audio — who said it. Providers return cues rather than
formatted text so SRT rendering stays in one place and speaker handling works
the same way for every provider.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

# Limits used when grouping individual words into readable subtitle cues.
MAX_SUBTITLE_CHARS = 84
MAX_SUBTITLE_DURATION_MS = 6_000
MAX_WORD_GAP_MS = 900

# Width at which a cue's text is wrapped onto multiple lines.
WRAP_WIDTH = 42

# Fallback cue length (ms) for a single word that has no duration.
DEFAULT_WORD_DURATION_MS = 250

# Minimum length (ms) of a cue built from grouped words.
MIN_CUE_DURATION_MS = 500

# Marks a cue that starts a new speaker's turn — the standard subtitle
# convention for dialogue, and understood by every player.
SPEAKER_CHANGE_PREFIX = "- "


@dataclass(frozen=True, slots=True)
class Cue:
    """A subtitle cue.

    ``text`` may contain explicit newlines, in which case those line breaks are
    preserved verbatim instead of being re-wrapped. ``speaker`` is the provider's
    speaker id (diarization), or ``None`` when the provider didn't identify one.
    """

    start_ms: int
    end_ms: int
    text: str
    speaker: int | None = None


def format_srt_timestamp(milliseconds: int) -> str:
    """Format a millisecond offset as an ``HH:MM:SS,mmm`` SRT timestamp."""
    milliseconds = max(0, milliseconds)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def wrap_subtitle_text(text: str) -> list[str]:
    """Wrap cue text to ``WRAP_WIDTH`` columns, never returning an empty list."""
    return textwrap.wrap(text, width=WRAP_WIDTH, break_long_words=False, break_on_hyphens=False) or [text]


def normalize_srt_text(text: str) -> str:
    """Normalize line endings and guarantee a single trailing newline."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def has_multiple_speakers(cues: list[Cue]) -> bool:
    """True when the cues name two or more distinct speakers."""
    return len({cue.speaker for cue in cues if cue.speaker is not None}) >= 2


def render_srt(cues: list[Cue]) -> str:
    """Render cues as SRT text. Returns an empty string when there are no cues.

    When the cues identify two or more speakers, every cue that starts a new
    speaker's turn is prefixed with ``- ``. A lone speaker (or no speaker data at
    all) renders unprefixed, so diarizing a single-voice recording costs nothing
    in readability.
    """
    mark_speakers = has_multiple_speakers(cues)
    previous_speaker: int | None = None
    blocks: list[str] = []

    for index, cue in enumerate(cues):
        starts_turn = mark_speakers and (index == 0 or cue.speaker != previous_speaker)
        previous_speaker = cue.speaker
        lines = _cue_lines(cue, SPEAKER_CHANGE_PREFIX if starts_turn else "")
        if not lines:
            continue
        blocks.append(
            "\n".join(
                [
                    str(len(blocks) + 1),
                    f"{format_srt_timestamp(cue.start_ms)} --> {format_srt_timestamp(cue.end_ms)}",
                    *lines,
                ]
            )
        )

    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _cue_lines(cue: Cue, prefix: str) -> list[str]:
    """Lay out one cue's text, honoring any line breaks it already carries."""
    text = prefix + cue.text.strip()
    if not text.strip():
        return []
    if "\n" in text:
        return [line.rstrip() for line in text.split("\n") if line.strip()]
    return wrap_subtitle_text(text)


# Tolerant of both ``,``/``.`` decimal separators and 1-3 digit hours.
_TIMESTAMP_LINE = re.compile(
    r"(\d{1,3}):([0-5]?\d):([0-5]?\d)[,.](\d{1,3})\s*-->\s*(\d{1,3}):([0-5]?\d):([0-5]?\d)[,.](\d{1,3})"
)


def parse_srt(text: str) -> list[Cue]:
    """Parse SRT text into cues, preserving each cue's existing line breaks.

    Reading an SRT back is how :mod:`.translate` works on a subtitle file the
    tool produced earlier, without re-running (and re-paying for) transcription.
    Speaker ids don't survive the round trip — SRT has no field for them — so
    parsed cues carry the ``- `` turn markers in their text instead.
    """
    cues: list[Cue] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return cues

    for block in re.split(r"\n\s*\n+", normalized):
        lines = [line for line in block.split("\n") if line.strip()]
        for index, line in enumerate(lines):
            match = _TIMESTAMP_LINE.search(line)
            if not match:
                continue
            body = "\n".join(lines[index + 1 :]).strip()
            if body:
                cues.append(Cue(_match_ms(match, 0), _match_ms(match, 4), body))
            break

    return cues


def _match_ms(match: re.Match[str], group_offset: int) -> int:
    hours, minutes, seconds, fraction = (match.group(group_offset + i) for i in range(1, 5))
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        # "5" means 500ms, "05" means 50ms — pad right, don't zero-fill left.
        + int(fraction.ljust(3, "0"))
    )


def group_words_into_cues(words: list[Cue]) -> list[Cue]:
    """Group word-level cues into subtitle-sized cues.

    A change of speaker always starts a new cue, so one subtitle never blends two
    voices together — the failure that turns an interruption into a single
    nonsensical line.

    Returns an empty list when there are fewer than two words, signalling the
    caller to fall back to a coarser (phrase-level) cue instead.
    """
    if len(words) < 2:
        return []

    cues: list[Cue] = []
    current: list[Cue] = []
    for word in words:
        if current and _should_start_new_cue(current, word):
            cues.append(_merge_words(current))
            current = []
        current.append(word)

    if current:
        cues.append(_merge_words(current))
    return cues


def _should_start_new_cue(current: list[Cue], word: Cue) -> bool:
    current_start = current[0].start_ms
    current_end = current[-1].end_ms
    gap_ms = word.start_ms - current_end
    duration_ms = word.end_ms - current_start
    text = " ".join([item.text for item in current] + [word.text])
    return (
        word.speaker != current[-1].speaker
        or gap_ms > MAX_WORD_GAP_MS
        or duration_ms > MAX_SUBTITLE_DURATION_MS
        or len(text) > MAX_SUBTITLE_CHARS
    )


def _merge_words(words: list[Cue]) -> Cue:
    start_ms = words[0].start_ms
    end_ms = max(words[-1].end_ms, start_ms + MIN_CUE_DURATION_MS)
    text = " ".join(word.text for word in words)
    return Cue(start_ms, end_ms, text, words[0].speaker)
