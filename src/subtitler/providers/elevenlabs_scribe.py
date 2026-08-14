"""ElevenLabs Scribe v2 transcription provider.

Scribe returns word-level timestamps *and* diarization from a single request, so
it needs no alignment pass and no second call — the same shape as
:mod:`.azure_fast`, but from a model that tops the independent Artificial
Analysis word-error-rate leaderboard.

The response is a flat list of tokens rather than phrases: each carries a
``type`` (``word``, ``spacing``, or ``audio_event``), a start/end in **seconds**,
and a ``speaker_id`` string when diarizing. This module keeps the words, drops
the spacing, and hands the rest to the shared cue grouper.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from ..errors import UserFacingError
from ..srt import Cue, group_words_into_cues
from .base import ProviderSpec, TranscriptionProvider
from ._http import build_multipart_body, extract_error_message

if TYPE_CHECKING:
    from ..config import RunConfig

SPEECH_TO_TEXT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL_ID = "scribe_v2"

# Scribe accepts up to 32 speakers.
MAX_SPEAKERS = 32

# A representative subset for --list-languages; Scribe covers 90+ languages and
# accepts any ISO-639-1 or ISO-639-3 code, so this list is a convenience, not a limit.
COMMON_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ar", "Arabic"),
    ("bg", "Bulgarian"),
    ("cs", "Czech"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("hi", "Hindi"),
    ("hr", "Croatian"),
    ("hu", "Hungarian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sr", "Serbian"),
    ("sv", "Swedish"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
    ("zh", "Chinese"),
)

SPEC = ProviderSpec(
    name="scribe",
    label="ElevenLabs Scribe v2",
    default_model=MODEL_ID,
    default_audio_format="mp3",
    # ElevenLabs accepts uploads up to 5 GB; this cap just keeps the pipeline's
    # size check meaningful for typical media.
    default_max_upload_mib=1000,
    # $0.22/hour.
    price_per_minute_usd=0.22 / 60,
    languages=COMMON_LANGUAGES,
    language_note=(
        "Scribe covers 90+ languages and accepts any ISO-639-1 or ISO-639-3 code "
        "(this is a common subset). Omit --language to auto-detect."
    ),
    supports_diarization=True,
)


class ElevenLabsScribeProvider(TranscriptionProvider):
    spec = SPEC

    def __init__(
        self,
        *,
        api_key: str | None,
        language: str | None,
        max_speakers: int | None,
        tag_audio_events: bool,
    ) -> None:
        super().__init__(MODEL_ID)
        self.api_key = api_key
        self.language = language
        self.max_speakers = max_speakers
        self.tag_audio_events = tag_audio_events

    def validate(self) -> None:
        if not self.api_key:
            raise UserFacingError("ELEVENLABS_API_KEY is not set. Export it, then rerun the same command.")

    def transcribe(self, audio_path: Path, timeout_seconds: int) -> list[Cue]:
        payload = self._post(audio_path, timeout_seconds)
        words = collect_words(payload)
        if not words:
            raise UserFacingError(
                "ElevenLabs Scribe returned no timed words (the audio may be silent or too short)."
            )
        # Scribe times every word individually; group them into readable cues
        # (falling back to the raw words if there are too few to group).
        return group_words_into_cues(words) or words

    def _post(self, audio_path: Path, timeout_seconds: int) -> dict[str, object]:
        fields: list[tuple[str, str]] = [
            ("model_id", MODEL_ID),
            ("timestamps_granularity", "word"),
            ("tag_audio_events", "true" if self.tag_audio_events else "false"),
            ("diarize", "true" if self.max_speakers is not None else "false"),
        ]
        if self.max_speakers is not None:
            fields.append(("num_speakers", str(min(MAX_SPEAKERS, max(1, self.max_speakers)))))
        if self.language:
            fields.append(("language_code", self.language))

        body, content_type = build_multipart_body(fields, "file", audio_path)
        request = urllib.request.Request(
            SPEECH_TO_TEXT_URL,
            data=body,
            headers={"xi-api-key": self.api_key or "", "Content-Type": content_type},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise UserFacingError(
                f"ElevenLabs API returned HTTP {exc.code}: {extract_error_message(body_text)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise UserFacingError(f"could not reach ElevenLabs API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise UserFacingError("ElevenLabs API returned a non-JSON response") from exc

        if not isinstance(payload, dict):
            raise UserFacingError("ElevenLabs API returned an unexpected (non-object) response")
        return payload


def collect_words(payload: dict[str, object]) -> list[Cue]:
    """Turn a Scribe response into word cues, in time order.

    Keeps ``word`` and ``audio_event`` tokens (an audio event is rendered text
    like "(laughter)", which belongs in subtitles) and drops ``spacing``, which
    carries no content. Times arrive in seconds and become milliseconds here.
    """
    tokens = payload.get("words")
    if not isinstance(tokens, list):
        return []

    speakers = _SpeakerNumbering()
    words: list[Cue] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        if token.get("type") not in (None, "word", "audio_event"):
            continue
        text = token.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        start = _seconds_to_ms(token.get("start"))
        end = _seconds_to_ms(token.get("end"))
        if start is None:
            continue
        words.append(Cue(start, end if end is not None and end > start else start, text.strip(), speakers.number(token)))

    return sorted(words, key=lambda word: word.start_ms)


class _SpeakerNumbering:
    """Map Scribe's ``speaker_id`` strings onto the integer ids cues use.

    Scribe labels speakers ``speaker_0``, ``speaker_1``, ... but the field is
    documented only as a string, so trailing digits are used when present and
    anything else is numbered by order of first appearance.
    """

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def number(self, token: dict[str, object]) -> int | None:
        raw = token.get("speaker_id")
        if not isinstance(raw, str) or not raw.strip():
            return None
        key = raw.strip()
        if key not in self._seen:
            digits = key.rsplit("_", 1)[-1]
            self._seen[key] = int(digits) if digits.isdigit() else len(self._seen)
        return self._seen[key]


def _seconds_to_ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value * 1000))


def build(config: RunConfig) -> ElevenLabsScribeProvider:
    return ElevenLabsScribeProvider(
        api_key=os.environ.get("ELEVENLABS_API_KEY"),
        language=config.language,
        max_speakers=config.max_speakers if config.diarize else None,
        tag_audio_events=config.tag_audio_events,
    )
