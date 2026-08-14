"""The transcription provider contract.

A provider knows how to turn an extracted audio file into subtitle cues. Static
metadata (defaults, pricing, supported languages) lives on :class:`ProviderSpec`
so the CLI can read it before a provider instance is built — for ``--list-languages``
and for resolving provider-specific argument defaults.

Providers return cues rather than SRT text so that rendering, line wrapping, and
speaker labelling happen once, in :mod:`..srt`, for every provider alike.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ..srt import Cue


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of a transcription provider."""

    name: str
    label: str
    default_model: str
    default_audio_format: str
    default_max_upload_mib: int
    price_per_minute_usd: float
    languages: tuple[tuple[str, str], ...]
    language_note: str | None = None
    # Whether this provider can label who is speaking (``--diarize``).
    supports_diarization: bool = False
    # An internal building block rather than a ``--provider`` choice. Registered
    # so its spec and definitions stay reachable, but hidden from the CLI because
    # its output isn't good enough to hand a user directly.
    internal: bool = False


class TranscriptionProvider(ABC):
    """Turns an extracted audio file into subtitle cues."""

    spec: ClassVar[ProviderSpec]

    def __init__(self, model: str) -> None:
        # The concrete model id used for this run (shown in the cost estimate).
        self.model = model

    @abstractmethod
    def validate(self) -> None:
        """Raise :class:`UserFacingError` if required credentials are missing.

        Called only for real runs; skipped on ``--dry-run``.
        """

    @abstractmethod
    def transcribe(self, audio_path: Path, timeout_seconds: int) -> list[Cue]:
        """Upload ``audio_path`` and return its subtitle cues, in time order."""
