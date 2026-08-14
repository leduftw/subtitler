"""Transcription provider registry.

Each provider module exposes a ``SPEC`` (static metadata) and a ``build(config)``
factory. This package ties them together so the rest of the app can stay
provider-agnostic: ask for names, specs, or a ready-to-use provider instance.

A provider marked ``internal`` on its spec stays registered — its metadata and
request builders are still reachable — but is left out of :data:`NAMES`, so the
CLI never offers it as a ``--provider`` choice. That is how ``azure-mai`` remains
available as the text pass inside ``azure-hybrid`` without being something a user
can pick and get one 3,000-character subtitle from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import azure_fast, azure_hybrid, azure_mai, elevenlabs_scribe
from .base import ProviderSpec, TranscriptionProvider

if TYPE_CHECKING:
    from ..config import RunConfig

_MODULES = {module.SPEC.name: module for module in (elevenlabs_scribe, azure_fast, azure_hybrid, azure_mai)}
_SPECS = {name: module.SPEC for name, module in _MODULES.items()}

# Provider name constants and the user-selectable set, in display order.
AZURE_MAI = azure_mai.SPEC.name
AZURE_FAST = azure_fast.SPEC.name
AZURE_HYBRID = azure_hybrid.SPEC.name
SCRIBE = elevenlabs_scribe.SPEC.name
NAMES: tuple[str, ...] = tuple(name for name, provider_spec in _SPECS.items() if not provider_spec.internal)
DEFAULT = SCRIBE

__all__ = [
    "ProviderSpec",
    "TranscriptionProvider",
    "SCRIBE",
    "AZURE_MAI",
    "AZURE_FAST",
    "AZURE_HYBRID",
    "NAMES",
    "DEFAULT",
    "spec",
    "build",
    "print_supported_languages",
]


def spec(name: str) -> ProviderSpec:
    """Return the static metadata for a provider name."""
    return _SPECS[name]


def build(config: RunConfig) -> TranscriptionProvider:
    """Build the provider instance selected by ``config.provider``."""
    return _MODULES[config.provider].build(config)


def print_supported_languages(name: str) -> None:
    """Print the transcription language/code list for a provider."""
    provider_spec = spec(name)
    print(f"Supported transcription languages for {name}:")
    for code, language in provider_spec.languages:
        print(f"  {code:<2}  {language}")
    print()
    print("Use the code with --language, for example: --language en")
    if provider_spec.language_note:
        print(provider_spec.language_note)
