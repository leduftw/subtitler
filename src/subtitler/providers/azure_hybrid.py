"""Azure hybrid provider: MAI transcript timed by fast transcription.

MAI gives an accurate transcript but no word-level timing; Azure's plain fast
transcription gives word-level timing but a less polished transcript. This
provider runs both on the same audio and merges them (:func:`align_text_to_words`)
so the SRT carries MAI's wording at fast transcription's timestamps — which is
what makes subtitles appear as each line is actually spoken.

Cost is two transcription passes over the same audio (see :data:`SPEC`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..align import align_text_to_words
from ..errors import UserFacingError
from ..srt import Cue, group_words_into_cues
from . import _azure_speech as az
from . import azure_mai
from .base import ProviderSpec, TranscriptionProvider

if TYPE_CHECKING:
    from ..config import RunConfig

SPEC = ProviderSpec(
    name="azure-hybrid",
    label="Azure MAI + fast alignment",
    default_model="mai-transcribe-1.5",
    default_audio_format="mp3",
    default_max_upload_mib=300,
    # Two passes over the same audio (MAI + fast transcription), each ~$0.006/minute.
    price_per_minute_usd=0.012,
    languages=azure_mai.SUPPORTED_LANGUAGES,
    language_note="Note: runs MAI for text and fast transcription for word timings, then aligns the two.",
    supports_diarization=True,
)


class AzureHybridProvider(TranscriptionProvider):
    spec = SPEC

    def __init__(
        self,
        *,
        model: str,
        endpoint: str | None,
        api_key: str | None,
        language: str | None,
        transcribe_style: str,
        max_speakers: int | None,
    ) -> None:
        super().__init__(model)
        self.endpoint = endpoint
        self.api_key = api_key
        self.language = language
        self.transcribe_style = transcribe_style
        self.max_speakers = max_speakers

    def validate(self) -> None:
        az.validate_credentials(self.endpoint, self.api_key)

    def transcribe(self, audio_path: Path, timeout_seconds: int) -> list[Cue]:
        # 1. MAI: the accurate transcript (the "what").
        mai_definition = azure_mai.build_definition(self.model, self.language, self.transcribe_style)
        mai_payload = az.post_transcribe(self.endpoint, self.api_key, mai_definition, audio_path, timeout_seconds)
        transcript = az.combined_text(mai_payload)
        if not transcript:
            raise UserFacingError("Azure MAI returned no transcript text to align.")

        # 2. Fast transcription: word-level timings (the "when") and, when diarizing,
        # the speakers (the "who") — MAI supports neither. Fast transcription needs
        # region-qualified locales (e.g. en-US), not MAI's short codes, and its
        # transcript is only a timing skeleton (MAI supplies the words), so we let it
        # auto-detect the language to stay robust across inputs.
        fast_definition = az.build_fast_definition(None, self.max_speakers)
        fast_payload = az.post_transcribe(self.endpoint, self.api_key, fast_definition, audio_path, timeout_seconds)
        timed_words = az.collect_words(fast_payload)
        if not timed_words:
            raise UserFacingError(
                "Azure fast transcription returned no word timings to align against "
                "(the audio may be silent or too short)."
            )

        # 3. Merge: MAI's wording at fast transcription's timestamps and speakers.
        word_cues = align_text_to_words(transcript, timed_words)
        cues = group_words_into_cues(word_cues) or word_cues
        if not cues:
            raise UserFacingError("Aligning the MAI transcript to word timings produced no cues.")
        return cues


def build(config: RunConfig) -> AzureHybridProvider:
    return AzureHybridProvider(
        model=config.azure_model,
        endpoint=config.azure_endpoint,
        api_key=os.environ.get("AZURE_SPEECH_API_KEY"),
        language=azure_mai.request_language(config.language),
        transcribe_style=config.azure_transcribe_style,
        max_speakers=config.max_speakers if config.diarize else None,
    )
