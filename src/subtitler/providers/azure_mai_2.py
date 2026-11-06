"""Azure MAI-Transcribe-2 with native word timing and speaker diarization.

Unlike MAI-Transcribe-1.5, this model can produce subtitle-ready words in one
request. Missing word timing is an error: a phrase-sized fallback could hide
lost dialogue or produce subtitles spanning an entire recording.
"""

from __future__ import annotations

import math
import os
import sys
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

from ..errors import UsageError, UserFacingError
from ..srt import Cue, group_words_into_cues
from . import _azure_speech as az
from .base import ProviderSpec, TranscriptionProvider

if TYPE_CHECKING:
    from ..config import RunConfig

MODEL_ID = "MAI-Transcribe-2"

# Complete language list from Azure's MAI-Transcribe documentation. Serbian and
# Croatian are not supported; silently dropping their hints changes the output.
# https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("af", "Afrikaans"),
    ("ar", "Arabic"),
    ("as", "Assamese"),
    ("az", "Azerbaijani"),
    ("bg", "Bulgarian"),
    ("bn", "Bengali"),
    ("bs", "Bosnian"),
    ("ca", "Catalan"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("et", "Estonian"),
    ("fa", "Persian"),
    ("fi", "Finnish"),
    ("fil", "Filipino"),
    ("fr", "French"),
    ("gl", "Galician"),
    ("gu", "Gujarati"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("hy", "Armenian"),
    ("id", "Indonesian"),
    ("is", "Icelandic"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("kk", "Kazakh"),
    ("kn", "Kannada"),
    ("ko", "Korean"),
    ("lt", "Lithuanian"),
    ("lv", "Latvian"),
    ("mk", "Macedonian"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("ms", "Malay"),
    ("nb", "Norwegian Bokmål"),
    ("ne", "Nepali"),
    ("nl", "Dutch"),
    ("or", "Odia"),
    ("pa", "Punjabi (Gurmukhi script)"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("sv", "Swedish"),
    ("sw", "Swahili"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("ur", "Urdu"),
    ("vi", "Vietnamese"),
    ("yue", "Cantonese"),
    ("zh", "Chinese (simplified)"),
)

SPEC = ProviderSpec(
    name="azure-mai-2",
    label="Azure MAI-Transcribe-2",
    default_model=MODEL_ID,
    default_audio_format="mp3",
    # The 2025-10-15 REST reference gives 250 MB; 238 MiB stays below that
    # limit even when MB means decimal bytes.
    default_max_upload_mib=238,
    # Standard rate, $0.36/hour; introductory discounts may lower the bill.
    price_per_minute_usd=0.36 / 60,
    languages=SUPPORTED_LANGUAGES,
    language_note=(
        "MAI-Transcribe-2 supports these 60 language codes. Unsupported hints "
        "are rejected; omit --language to auto-detect."
    ),
    supports_diarization=True,
)


def request_language(language: str | None) -> str | None:
    """Validate an explicit language instead of silently changing recognition."""
    if not language:
        return None
    code = language.strip().lower()
    if code not in {item[0] for item in SUPPORTED_LANGUAGES}:
        raise UsageError(
            f"--language {language} is not supported by azure-mai-2. "
            "Use --provider azure-mai-2 --list-languages for supported codes, "
            "or choose --provider scribe for broader language coverage."
        )
    return code


def build_definition(
    language: str | None, transcribe_style: str, max_speakers: int | None
) -> dict[str, object]:
    """Request the model's native word timing, with optional speaker labels."""
    styles = {"display": "clean", "verbatim": "verbatim"}
    if transcribe_style not in styles:
        raise UsageError(f"unsupported Azure transcription style: {transcribe_style}")
    definition = az.build_fast_definition(request_language(language))
    if max_speakers is not None:
        # Live MAI-2 rejects maxSpeakers even though plain Azure fast supports it.
        definition["diarization"] = {"enabled": True}
    definition["enhancedMode"] = {
        "enabled": True,
        "model": MODEL_ID,
        "modelOptions": {
            "timestamps": "word",
            "transcribeStyle": styles[transcribe_style],
        },
    }
    return definition


class AzureMai2Provider(TranscriptionProvider):
    spec = SPEC

    def __init__(
        self,
        *,
        endpoint: str | None,
        api_key: str | None,
        language: str | None,
        transcribe_style: str,
        max_speakers: int | None,
    ) -> None:
        super().__init__(MODEL_ID)
        self.endpoint = endpoint
        self.api_key = api_key
        self.language = request_language(language)
        self.transcribe_style = transcribe_style
        self.max_speakers = max_speakers

    def validate(self) -> None:
        az.validate_credentials(self.endpoint, self.api_key)

    def transcribe(self, audio_path: Path, timeout_seconds: int) -> list[Cue]:
        definition = build_definition(
            self.language, self.transcribe_style, self.max_speakers
        )
        try:
            payload = az.post_transcribe(
                self.endpoint, self.api_key, definition, audio_path, timeout_seconds
            )
        except UserFacingError as exc:
            cause = exc.__cause__
            if (
                self.max_speakers is not None
                and isinstance(cause, urllib.error.HTTPError)
                and cause.code in (408, 500, 503)
            ):
                raise UserFacingError(
                    f"{exc}. MAI-Transcribe-2 preview can fail on long recordings "
                    "with diarization. Retry with --no-diarize for subtitles without "
                    "speaker labels, or use --provider scribe to keep speaker labels."
                ) from exc
            raise
        return transcription_to_cues(payload)


def transcription_to_cues(payload: dict[str, object]) -> list[Cue]:
    """Require native timing for every phrase before using the shared parser."""
    phrases = payload.get("phrases")
    if not isinstance(phrases, list):
        raise _missing_timing()
    for phrase in phrases:
        if not isinstance(phrase, dict):
            raise _missing_timing()
        words = phrase.get("words")
        if not isinstance(words, list) or not words:
            # Empty non-speech phrases do not contain dialogue to lose.
            if not phrase.get("text"):
                continue
            raise _missing_timing()
        for word in words:
            if not isinstance(word, dict) or not isinstance(word.get("text"), str):
                raise _missing_timing()
            if not word["text"].strip():
                continue
            for key in ("offsetMilliseconds", "durationMilliseconds"):
                value = word.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int | float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise _missing_timing()
    words = az.collect_words(payload)
    if not words:
        if az.combined_text(payload):
            raise _missing_timing()
        # Silent audio comes back as an empty transcript, not as a timing fault.
        raise UserFacingError(
            "MAI-Transcribe-2 returned no speech for this audio "
            "(it may be silent or too short)."
        )
    return group_words_into_cues(words) or words


def _missing_timing() -> UserFacingError:
    return UserFacingError(
        "MAI-Transcribe-2 returned missing or invalid native word timestamps. "
        "It cannot produce accurately timed subtitles from this response. "
        "Try --provider scribe or --provider azure-fast."
    )


def build(config: RunConfig) -> AzureMai2Provider:
    from ..config import DEFAULT_MAX_SPEAKERS

    if config.diarize and config.max_speakers != DEFAULT_MAX_SPEAKERS:
        print(
            "warning: --max-speakers is not supported by azure-mai-2; "
            "Azure detects the number of speakers automatically.",
            file=sys.stderr,
        )
    return AzureMai2Provider(
        endpoint=config.azure_endpoint,
        api_key=os.environ.get("AZURE_SPEECH_API_KEY"),
        language=config.language,
        transcribe_style=config.azure_transcribe_style,
        max_speakers=config.max_speakers if config.diarize else None,
    )
