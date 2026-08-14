"""Azure fast transcription provider (standard speech-to-text).

Plain fast transcription — no MAI ``enhancedMode`` — returns word-level
timestamps directly, so the SRT is time-synced in a single pass with no
alignment step. It also supports diarization, tagging each phrase with a speaker
id at no extra cost, which lets the SRT break cues at a change of speaker. Use it
for languages MAI doesn't cover, or whenever you want one-pass, in-sync,
speaker-aware subtitles.

Unlike MAI's short ISO codes, fast transcription expects region-qualified
BCP-47 locales (e.g. ``es-ES``, ``en-US``). For convenience, common bare codes
are mapped to a default region; omit ``--language`` to auto-detect.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..srt import Cue
from . import _azure_speech as az
from .base import ProviderSpec, TranscriptionProvider

if TYPE_CHECKING:
    from ..config import RunConfig

# A common subset of fast-transcription locales for --list-languages. Azure
# supports many more; pass any BCP-47 locale it accepts via --language.
COMMON_LOCALES: tuple[tuple[str, str], ...] = (
    ("ar-SA", "Arabic (Saudi Arabia)"),
    ("de-DE", "German (Germany)"),
    ("en-GB", "English (United Kingdom)"),
    ("en-US", "English (United States)"),
    ("es-ES", "Spanish (Spain)"),
    ("fr-FR", "French (France)"),
    ("hr-HR", "Croatian (Croatia)"),
    ("it-IT", "Italian (Italy)"),
    ("ja-JP", "Japanese (Japan)"),
    ("ko-KR", "Korean (Korea)"),
    ("nl-NL", "Dutch (Netherlands)"),
    ("pl-PL", "Polish (Poland)"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("ru-RU", "Russian (Russia)"),
    ("sr-RS", "Serbian (Cyrillic, Serbia)"),
    ("tr-TR", "Turkish (Türkiye)"),
    ("uk-UA", "Ukrainian (Ukraine)"),
    ("zh-CN", "Chinese (Mandarin, Simplified)"),
)

# Convenience mapping from bare ISO codes to a sensible default region locale.
# (en-US wins over en-GB because it appears later in COMMON_LOCALES.)
_SHORT_TO_LOCALE = {code.split("-")[0]: code for code, _ in COMMON_LOCALES}

SPEC = ProviderSpec(
    name="azure-fast",
    label="Azure fast transcription",
    default_model="fast-transcription",
    default_audio_format="mp3",
    default_max_upload_mib=500,
    # Standard-Audio tier, single pass: $0.36/hour = $0.006/minute.
    price_per_minute_usd=0.006,
    languages=COMMON_LOCALES,
    language_note=(
        "Fast transcription uses BCP-47 region codes like es-ES or en-US (this is a common "
        "subset; Azure supports more). Omit --language to auto-detect."
    ),
    supports_diarization=True,
)


class AzureFastProvider(TranscriptionProvider):
    spec = SPEC

    def __init__(
        self,
        *,
        endpoint: str | None,
        api_key: str | None,
        locale: str | None,
        max_speakers: int | None,
    ) -> None:
        super().__init__(SPEC.default_model)
        self.endpoint = endpoint
        self.api_key = api_key
        self.locale = locale
        self.max_speakers = max_speakers

    def validate(self) -> None:
        az.validate_credentials(self.endpoint, self.api_key)

    def transcribe(self, audio_path: Path, timeout_seconds: int) -> list[Cue]:
        definition = az.build_fast_definition(self.locale, self.max_speakers)
        payload = az.post_transcribe(self.endpoint, self.api_key, definition, audio_path, timeout_seconds)
        return az.transcription_to_cues(payload)


def build(config: RunConfig) -> AzureFastProvider:
    return AzureFastProvider(
        endpoint=config.azure_endpoint,
        api_key=os.environ.get("AZURE_SPEECH_API_KEY"),
        locale=resolve_locale(config.language),
        max_speakers=config.max_speakers if config.diarize else None,
    )


def resolve_locale(language: str | None) -> str | None:
    """Turn ``--language`` into a fast-transcription locale (or ``None`` to auto-detect)."""
    if not language:
        return None
    if "-" in language:
        return language  # already region-qualified, e.g. es-ES / en-US
    mapped = _SHORT_TO_LOCALE.get(language.lower())
    if mapped:
        print(f"note: mapping --language {language} to {mapped} for fast transcription.", file=sys.stderr)
        return mapped
    print(
        f"warning: fast transcription expects a region code (e.g. en-US, es-ES); "
        f"sending '{language}' as-is, which Azure may reject.",
        file=sys.stderr,
    )
    return language
