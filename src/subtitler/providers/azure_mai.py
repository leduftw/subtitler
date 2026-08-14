"""Azure MAI transcription provider.

``mai-transcribe-1.5`` is exposed through Azure Speech's LLM Speech REST API via
``enhancedMode``. It returns an accurate, readability-optimized transcript but
only coarse, segment-level timestamps (no word-level timing), and Azure does not
support diarization in enhanced mode — so this provider can tell you *what* was
said, but never *when* precisely or *by whom*. For well-synced, speaker-aware
subtitles, see :mod:`.azure_hybrid` (MAI's wording) or :mod:`.azure_fast`.
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

# Languages MAI-Transcribe-1.5 supports as locale hints (ISO 639-1 codes), 43 in
# total per the model card. (The REST API doc table currently omits `zh`.)
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ar", "Arabic"),
    ("as", "Assamese"),
    ("bg", "Bulgarian"),
    ("bn", "Bengali"),
    ("ca", "Catalan"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("et", "Estonian"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("gu", "Gujarati"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("kn", "Kannada"),
    ("ko", "Korean"),
    ("lt", "Lithuanian"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("nb", "Norwegian Bokmål"),
    ("nl", "Dutch"),
    ("or", "Odia"),
    ("pa", "Punjabi"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("sv", "Swedish"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
    ("zh", "Chinese"),
)

SPEC = ProviderSpec(
    name="azure-mai",
    label="Azure MAI",
    default_model="mai-transcribe-1.5",
    default_audio_format="mp3",
    default_max_upload_mib=300,
    # $0.36/hour (Standard-Audio tier in LLM Speech enhanced mode) = $0.006/minute.
    price_per_minute_usd=0.006,
    languages=SUPPORTED_LANGUAGES,
    language_note="Note: a --language not listed above is omitted so Azure can auto-detect the spoken language.",
    # Not offered as a --provider choice: MAI's timing is too coarse to make
    # subtitles from on its own (a three-minute clip comes back as one cue). It
    # earns its place only as the text pass inside azure-hybrid.
    internal=True,
)


def build_definition(model: str, language: str | None, transcribe_style: str) -> dict[str, object]:
    """Build the MAI ``enhancedMode`` request ``definition``."""
    enhanced_mode: dict[str, object] = {
        "enabled": True,
        "task": "transcribe",
        "model": model,
    }
    if transcribe_style == "verbatim":
        enhanced_mode["transcribeStyle"] = "verbatim"

    definition: dict[str, object] = {"enhancedMode": enhanced_mode}
    if language:
        definition["locales"] = [language]
    return definition


class AzureMaiProvider(TranscriptionProvider):
    spec = SPEC

    def __init__(
        self,
        *,
        model: str,
        endpoint: str | None,
        api_key: str | None,
        language: str | None,
        transcribe_style: str,
    ) -> None:
        super().__init__(model)
        self.endpoint = endpoint
        self.api_key = api_key
        self.language = language
        self.transcribe_style = transcribe_style

    def validate(self) -> None:
        az.validate_credentials(self.endpoint, self.api_key)

    def transcribe(self, audio_path: Path, timeout_seconds: int) -> list[Cue]:
        definition = build_definition(self.model, self.language, self.transcribe_style)
        payload = az.post_transcribe(self.endpoint, self.api_key, definition, audio_path, timeout_seconds)
        return az.transcription_to_cues(payload)


def build(config: RunConfig) -> AzureMaiProvider:
    return AzureMaiProvider(
        model=config.azure_model,
        endpoint=config.azure_endpoint,
        api_key=os.environ.get("AZURE_SPEECH_API_KEY"),
        language=request_language(config.language),
        transcribe_style=config.azure_transcribe_style,
    )


def request_language(language: str | None) -> str | None:
    """Return ``language`` if MAI supports it, else warn and fall back to auto-detect."""
    if not language:
        return None
    code = language.lower()
    if code in {item[0] for item in SUPPORTED_LANGUAGES}:
        return code
    print(
        f"warning: --language {language} is not listed for Azure MAI; omitting locales so Azure can auto-detect.",
        file=sys.stderr,
    )
    return None
