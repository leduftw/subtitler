"""Shared low-level client and response parsing for Azure Speech transcription.

Both the MAI provider and the hybrid provider hit the same
``/speechtotext/transcriptions:transcribe`` endpoint; only the ``definition``
JSON differs (MAI uses ``enhancedMode``; plain fast transcription does not).
This module owns the HTTP call and the JSON-to-cues parsing so those providers
stay focused on what they put in the request and do with the result.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from ..errors import UserFacingError
from ..srt import Cue, DEFAULT_WORD_DURATION_MS, group_words_into_cues
from ._http import build_multipart_body, extract_error_message

TRANSCRIPTIONS_PATH = "/speechtotext/transcriptions:transcribe"
API_VERSION = "2025-10-15"

# Azure ticks are 100-nanosecond units; 10,000 ticks make one millisecond.
TICKS_PER_MILLISECOND = 10_000

# Fallback cue length (ms) when a phrase reports no duration and is last.
FALLBACK_PHRASE_DURATION_MS = 5000

# Range Azure accepts for diarization's maxSpeakers.
MIN_SPEAKERS = 2
MAX_SPEAKERS = 35


def validate_credentials(endpoint: str | None, api_key: str | None) -> None:
    """Raise :class:`UserFacingError` if the Azure endpoint or key is missing."""
    if not endpoint:
        raise UserFacingError("AZURE_SPEECH_ENDPOINT is not set. Export it, or pass --azure-endpoint.")
    if not api_key:
        raise UserFacingError("AZURE_SPEECH_API_KEY is not set. Export it, then rerun the same command.")


def build_fast_definition(language: str | None, max_speakers: int | None = None) -> dict[str, object]:
    """Build the request ``definition`` for plain fast transcription (no MAI).

    Fast transcription returns word-level timestamps, which is what the hybrid
    provider aligns against. Pass ``None`` to auto-detect the language; if you do
    pass a locale it must be region-qualified (e.g. ``en-US``) — unlike MAI's
    short codes, fast transcription rejects bare ``en``.

    ``max_speakers`` enables diarization, tagging each returned phrase with a
    ``speaker`` id. Azure bills diarization at no extra cost on fast transcription
    and it requires mono audio, which is what the pipeline already extracts.
    """
    definition: dict[str, object] = {}
    if language:
        definition["locales"] = [language]
    if max_speakers is not None:
        capped = max(MIN_SPEAKERS, min(MAX_SPEAKERS, max_speakers))
        definition["diarization"] = {"enabled": True, "maxSpeakers": capped}
    return definition


def post_transcribe(
    endpoint: str | None,
    api_key: str | None,
    definition: dict[str, object],
    audio_path: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    """POST one audio file to the transcribe endpoint and return the parsed JSON."""
    fields = [("definition", json.dumps(definition, ensure_ascii=False))]
    body, content_type = build_multipart_body(fields, "audio", audio_path)
    url = (endpoint or "").rstrip("/") + TRANSCRIPTIONS_PATH + f"?api-version={API_VERSION}"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Ocp-Apim-Subscription-Key": api_key or "",
            "Content-Type": content_type,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise UserFacingError(
            f"Azure Speech API returned HTTP {exc.code}: {extract_error_message(body_text)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UserFacingError(f"could not reach Azure Speech API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UserFacingError("Azure Speech API returned a non-JSON response") from exc

    if not isinstance(payload, dict):
        raise UserFacingError("Azure Speech API returned an unexpected (non-object) response")
    return payload


# --- Response parsing --------------------------------------------------------


def transcription_to_cues(payload: dict[str, object]) -> list[Cue]:
    """Convert an Azure transcription response into subtitle cues."""
    cues = collect_cues(payload)
    if not cues:
        combined = _first_combined_phrase_text(payload)
        if not combined:
            raise UserFacingError("Azure Speech response did not include phrases or combined transcript text")
        cues = [Cue(0, FALLBACK_PHRASE_DURATION_MS, combined)]
    return cues


def combined_text(payload: dict[str, object]) -> str | None:
    """Return the full transcript text (the "what"), or ``None`` if absent.

    Prefers ``combinedPhrases`` (the provider's readability-optimized transcript)
    and falls back to joining individual phrase texts.
    """
    text = _first_combined_phrase_text(payload)
    if text:
        return text
    parts = [t for t in (_phrase_text(p) for p in _collect_phrases(payload)) if t]
    return " ".join(parts) if parts else None


def collect_words(payload: dict[str, object]) -> list[Cue]:
    """Return every word as a timed cue (the "when"), sorted by start time.

    Each word inherits its phrase's ``speaker`` when diarization was requested,
    which is how speaker identity reaches the hybrid provider's alignment step.
    """
    words: list[Cue] = []
    for phrase in _collect_phrases(payload):
        words.extend(_phrase_words(phrase))
    return sorted(words, key=lambda word: word.start_ms)


def collect_cues(payload: dict[str, object]) -> list[Cue]:
    """Build subtitle-sized cues from an Azure response (word- or phrase-level)."""
    phrases = _collect_phrases(payload)
    cues: list[Cue] = []
    for index, phrase in enumerate(phrases):
        word_cues = group_words_into_cues(_phrase_words(phrase))
        if word_cues:
            cues.extend(word_cues)
            continue

        text = _phrase_text(phrase)
        if not text:
            continue
        start_ms = _phrase_ms(phrase, "offsetMilliseconds", "offsetInTicks", "offset") or 0
        duration_ms = _phrase_ms(phrase, "durationMilliseconds", "durationInTicks", "duration")
        if duration_ms is None:
            next_start = None
            if index + 1 < len(phrases):
                next_start = _phrase_ms(phrases[index + 1], "offsetMilliseconds", "offsetInTicks", "offset")
            end_ms = next_start if next_start is not None and next_start > start_ms else start_ms + FALLBACK_PHRASE_DURATION_MS
        else:
            end_ms = start_ms + duration_ms
        cues.append(Cue(start_ms, end_ms, text, _phrase_speaker(phrase)))

    return sorted(cues, key=lambda cue: cue.start_ms)


def _phrase_words(phrase: dict[str, object]) -> list[Cue]:
    """Extract a phrase's word-level cues (ungrouped), or [] if none are present."""
    words_value = phrase.get("words")
    if not isinstance(words_value, list):
        return []

    speaker = _phrase_speaker(phrase)
    words: list[Cue] = []
    for word in words_value:
        if not isinstance(word, dict):
            continue
        text = _phrase_text(word)
        if not text:
            continue
        start_ms = _phrase_ms(word, "offsetMilliseconds", "offsetInTicks", "offset")
        if start_ms is None:
            continue
        duration_ms = _phrase_ms(word, "durationMilliseconds", "durationInTicks", "duration")
        end_ms = start_ms + (duration_ms if duration_ms is not None else DEFAULT_WORD_DURATION_MS)
        words.append(Cue(start_ms, end_ms, text, speaker))

    return words


def _phrase_speaker(phrase: dict[str, object]) -> int | None:
    """The phrase's diarization speaker id, or ``None`` when it wasn't diarized."""
    speaker = phrase.get("speaker")
    if isinstance(speaker, bool):  # bools are ints in Python; not a speaker id.
        return None
    if isinstance(speaker, int):
        return speaker
    if isinstance(speaker, str) and speaker.strip().isdigit():
        return int(speaker.strip())
    return None


def _collect_phrases(payload: dict[str, object]) -> list[dict[str, object]]:
    phrases: list[dict[str, object]] = []
    direct_phrases = payload.get("phrases")
    if isinstance(direct_phrases, list):
        phrases.extend(item for item in direct_phrases if isinstance(item, dict))

    phrases_by_channel = payload.get("phrasesByChannel")
    if isinstance(phrases_by_channel, list):
        for channel in phrases_by_channel:
            if not isinstance(channel, dict):
                continue
            channel_phrases = channel.get("phrases")
            if isinstance(channel_phrases, list):
                phrases.extend(item for item in channel_phrases if isinstance(item, dict))

    return sorted(phrases, key=lambda phrase: _phrase_ms(phrase, "offsetMilliseconds", "offsetInTicks", "offset") or 0)


def _first_combined_phrase_text(payload: dict[str, object]) -> str | None:
    combined_phrases = payload.get("combinedPhrases")
    if isinstance(combined_phrases, list):
        for phrase in combined_phrases:
            if isinstance(phrase, dict):
                text = _phrase_text(phrase)
                if text:
                    return text
    return None


def _phrase_text(phrase: dict[str, object]) -> str | None:
    for key in ("text", "displayText", "lexical"):
        value = phrase.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _phrase_ms(phrase: dict[str, object], milliseconds_key: str, ticks_key: str, fallback_key: str) -> int | None:
    value = phrase.get(milliseconds_key)
    if isinstance(value, int | float):
        return int(value)

    ticks = phrase.get(ticks_key)
    if isinstance(ticks, int | float):
        return int(ticks / TICKS_PER_MILLISECOND)

    fallback = phrase.get(fallback_key)
    if isinstance(fallback, int | float):
        return int(fallback)

    return None
