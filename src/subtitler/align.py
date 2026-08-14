"""Align a transcript's wording onto externally-provided word timings.

This is the "merge" step behind the hybrid provider: it takes an accurate
transcript (the *what*) and a separately-timed word sequence (the *when*) and
returns word cues that carry the transcript's wording at the timed sequence's
timestamps.

When the timed sequence is diarized, each word also carries a speaker id, and
that identity is transferred alongside the timing — so a transcript with no
speaker information of its own (MAI doesn't diarize) still ends up with per-word
speakers, which is what lets the SRT split cues at an interruption.

The two sequences rarely tokenize identically — the accurate transcript may
reformat numbers, drop disfluencies, or punctuate differently. We diff the two
word sequences (:class:`difflib.SequenceMatcher`) and:

- copy timings straight across for matching words,
- spread a timed span proportionally across a differing run of words,
- interpolate timings for transcript words with no timed counterpart, and
- ignore timed words the transcript dropped.

Everything here is pure and standard-library only (no ML alignment model).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .srt import Cue

_WORD_CHARS = re.compile(r"\w+", re.UNICODE)

# What we know about one transcript token while aligning: its span and speaker.
_Span = tuple[int, int, int | None]


def align_text_to_words(transcript: str, timed_words: list[Cue]) -> list[Cue]:
    """Return ``(start_ms, end_ms, word)`` cues for ``transcript``'s words.

    ``timed_words`` supplies the timing (and speaker) reference. The returned
    cues follow the transcript's wording and order, are sorted, and never
    overlap.
    """
    raw_tokens = transcript.split()
    if not raw_tokens or not timed_words:
        return []

    transcript_keys = [_normalize(token) for token in raw_tokens]
    timed_keys = [_normalize(word.text) for word in timed_words]

    # spans[i] is the (start, end, speaker) for transcript token i, or None until filled.
    spans: list[_Span | None] = [None] * len(raw_tokens)

    matcher = SequenceMatcher(a=transcript_keys, b=timed_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                word = timed_words[j1 + offset]
                spans[i1 + offset] = (word.start_ms, word.end_ms, word.speaker)
        elif tag == "replace":
            _spread_span(spans, timed_words, i1, i2, j1, j2)
        # "delete": transcript words with no timed match -> interpolated later.
        # "insert": timed words the transcript dropped -> ignored.

    _interpolate_gaps(spans, timed_words)
    _enforce_monotonic(spans)

    return [Cue(span[0], span[1], raw_tokens[i], span[2]) for i, span in enumerate(spans) if span is not None]


def _normalize(token: str) -> str:
    """Lowercased alphanumeric core of a token; ``""`` for pure punctuation."""
    return "".join(_WORD_CHARS.findall(token.lower()))


def _spread_span(
    spans: list[_Span | None],
    timed_words: list[Cue],
    i1: int,
    i2: int,
    j1: int,
    j2: int,
) -> None:
    """Distribute the timed span [j1, j2) evenly across transcript tokens [i1, i2)."""
    span_start = timed_words[j1].start_ms
    span_end = max(timed_words[j2 - 1].end_ms, span_start)
    speaker = _dominant_speaker(timed_words[j1:j2])
    count = i2 - i1
    step = (span_end - span_start) / count
    for offset in range(count):
        start = int(span_start + step * offset)
        end = span_end if offset == count - 1 else int(span_start + step * (offset + 1))
        spans[i1 + offset] = (start, max(end, start), speaker)


def _dominant_speaker(words: list[Cue]) -> int | None:
    """The speaker holding the most words in ``words`` (ties go to the earliest)."""
    counts: dict[int | None, int] = {}
    for word in words:
        counts[word.speaker] = counts.get(word.speaker, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda speaker: counts[speaker])


def _interpolate_gaps(spans: list[_Span | None], timed_words: list[Cue]) -> None:
    """Fill runs of unmatched transcript words by spreading the surrounding gap.

    An unmatched run is attributed to whichever neighbouring speaker it abuts —
    the preceding one where there is one, otherwise the following one.
    """
    audio_start = timed_words[0].start_ms
    audio_end = max(timed_words[-1].end_ms, audio_start)
    total = len(spans)

    index = 0
    while index < total:
        if spans[index] is not None:
            index += 1
            continue

        run_end = index
        while run_end < total and spans[run_end] is None:
            run_end += 1

        before = spans[index - 1] if index > 0 else None
        after = spans[run_end] if run_end < total else None
        left = before[1] if before is not None else audio_start
        right = after[0] if after is not None else audio_end
        right = max(right, left)
        speaker = before[2] if before is not None else (after[2] if after is not None else None)

        count = run_end - index
        step = (right - left) / count
        for offset in range(count):
            start = int(left + step * offset)
            end = right if offset == count - 1 else int(left + step * (offset + 1))
            spans[index + offset] = (start, max(end, start), speaker)
        index = run_end


def _enforce_monotonic(spans: list[_Span | None]) -> None:
    """Clamp cues so they are non-decreasing and never overlap."""
    previous_end: int | None = None
    for i, span in enumerate(spans):
        if span is None:
            continue
        start, end, speaker = span
        if previous_end is not None and start < previous_end:
            start = previous_end
        end = max(end, start)
        spans[i] = (start, end, speaker)
        previous_end = end
