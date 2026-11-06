"""Tests for native MAI-Transcribe-2 timing and the Azure request contract."""

from __future__ import annotations

import contextlib
import copy
import io
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitler.errors import UsageError, UserFacingError
from subtitler.providers import azure_mai_2 as mai
from subtitler.srt import Cue


def provider(*, max_speakers: int | None = 8) -> mai.AzureMai2Provider:
    return mai.AzureMai2Provider(
        endpoint="https://speech.example.com",
        api_key="test-key",
        language="en",
        transcribe_style="verbatim",
        max_speakers=max_speakers,
    )


class Mai2DefinitionTest(unittest.TestCase):
    def test_native_word_timestamps_and_verbatim_are_explicit(self) -> None:
        self.assertEqual(
            mai.build_definition("EN", "verbatim", 8),
            {
                "locales": ["en"],
                "diarization": {"enabled": True},
                "enhancedMode": {
                    "enabled": True,
                    "model": "MAI-Transcribe-2",
                    "modelOptions": {
                        "timestamps": "word",
                        "transcribeStyle": "verbatim",
                    },
                },
            },
        )

    def test_display_requests_clean_word_timing_without_diarization(self) -> None:
        definition = mai.build_definition(None, "display", None)
        self.assertNotIn("locales", definition)
        self.assertNotIn("diarization", definition)
        self.assertEqual(
            definition["enhancedMode"]["modelOptions"],
            {"timestamps": "word", "transcribeStyle": "clean"},
        )

    def test_diarization_never_sends_unsupported_max_speakers(self) -> None:
        for count in (1, 8, 35):
            with self.subTest(count=count):
                self.assertEqual(
                    mai.build_definition("en", "verbatim", count)["diarization"],
                    {"enabled": True},
                )

    def test_unsupported_language_is_rejected_before_upload(self) -> None:
        for language in ("sr", "sr-RS", "hr", "unknown"):
            with (
                self.subTest(language=language),
                self.assertRaisesRegex(UsageError, "not supported.*azure-mai-2"),
            ):
                mai.build_definition(language, "verbatim", None)
        self.assertEqual(len(mai.SUPPORTED_LANGUAGES), 60)
        self.assertEqual(len(dict(mai.SUPPORTED_LANGUAGES)), 60)
        self.assertEqual(mai.request_language("FIL"), "fil")


class Mai2ResponseTest(unittest.TestCase):
    # Azure's documented TranscribeResult has word offsets/durations in
    # milliseconds; the phrase owns its speaker id.
    PAYLOAD: ClassVar[dict] = {
        "durationMilliseconds": 3500,
        "combinedPhrases": [{"text": "Hello there. Welcome back."}],
        "phrases": [
            {
                "text": "Hello there.",
                "offsetMilliseconds": 1000,
                "durationMilliseconds": 900,
                "speaker": 0,
                "words": [
                    {
                        "text": "Hello",
                        "offsetMilliseconds": 1000,
                        "durationMilliseconds": 400,
                    },
                    {
                        "text": "there.",
                        "offsetMilliseconds": 1450,
                        "durationMilliseconds": 450,
                    },
                ],
            },
            {
                "text": "Welcome back.",
                "offsetMilliseconds": 2000,
                "durationMilliseconds": 900,
                "speaker": 1,
                "words": [
                    {
                        "text": "Welcome",
                        "offsetMilliseconds": 2000,
                        "durationMilliseconds": 400,
                    },
                    {
                        "text": "back.",
                        "offsetMilliseconds": 2450,
                        "durationMilliseconds": 450,
                    },
                ],
            },
        ],
    }

    def test_groups_native_words_without_crossing_speakers(self) -> None:
        self.assertEqual(
            mai.transcription_to_cues(self.PAYLOAD),
            [Cue(1000, 1900, "Hello there.", 0), Cue(2000, 2900, "Welcome back.", 1)],
        )

    def test_preserves_timing_for_a_single_word(self) -> None:
        self.assertEqual(
            mai.transcription_to_cues(
                {
                    "phrases": [
                        {
                            "words": [
                                {
                                    "text": "Hi.",
                                    "offsetMilliseconds": 1500,
                                    "durationMilliseconds": 200,
                                }
                            ]
                        }
                    ]
                }
            ),
            [Cue(1500, 1700, "Hi.")],
        )

    def test_missing_word_timing_does_not_fall_back_to_one_giant_cue(self) -> None:
        payload = {
            "durationMilliseconds": 180_000,
            "combinedPhrases": [{"text": "A whole recording without word timing."}],
            "phrases": [
                {
                    "text": "A whole recording without word timing.",
                    "offsetMilliseconds": 0,
                    "durationMilliseconds": 180_000,
                }
            ],
        }
        with self.assertRaisesRegex(UserFacingError, "native word timestamps"):
            mai.transcription_to_cues(payload)

    def test_missing_timing_in_a_later_phrase_does_not_drop_dialogue(self) -> None:
        payload = copy.deepcopy(self.PAYLOAD)
        payload["phrases"][1].pop("words")
        with self.assertRaisesRegex(UserFacingError, "native word timestamps"):
            mai.transcription_to_cues(payload)

    def test_missing_or_invalid_word_duration_is_not_invented(self) -> None:
        for value in (None, "250", True, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                payload = copy.deepcopy(self.PAYLOAD)
                payload["phrases"][0]["words"][0]["durationMilliseconds"] = value
                with self.assertRaisesRegex(UserFacingError, "native word timestamps"):
                    mai.transcription_to_cues(payload)

    def test_missing_offset_is_not_inferred_from_the_phrase(self) -> None:
        payload = copy.deepcopy(self.PAYLOAD)
        payload["phrases"][0]["words"][0].pop("offsetMilliseconds")
        with self.assertRaisesRegex(UserFacingError, "native word timestamps"):
            mai.transcription_to_cues(payload)

    def test_malformed_response_reports_no_timing(self) -> None:
        for payload in (
            {},
            {"phrases": "invalid"},
            {"combinedPhrases": [{"text": "Untimed words."}], "phrases": []},
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaisesRegex(UserFacingError, "native word timestamps"),
            ):
                mai.transcription_to_cues(payload)

    def test_silent_audio_reports_no_speech_rather_than_bad_timing(self) -> None:
        # The live service answers eight seconds of silence with this shape.
        payload = {
            "durationMilliseconds": 8000,
            "combinedPhrases": [{"text": ""}],
            "phrases": [],
        }
        with self.assertRaisesRegex(UserFacingError, "no speech") as caught:
            mai.transcription_to_cues(payload)
        self.assertNotIn("timestamps", str(caught.exception))


class Mai2ProviderTest(unittest.TestCase):
    def test_uploads_once_through_the_shared_client(self) -> None:
        with mock.patch.object(
            mai.az, "post_transcribe", return_value=Mai2ResponseTest.PAYLOAD
        ) as post:
            cues = provider().transcribe(Path("audio.mp3"), 1800)
        self.assertEqual([cue.speaker for cue in cues], [0, 1])
        post.assert_called_once_with(
            "https://speech.example.com",
            "test-key",
            mai.build_definition("en", "verbatim", 8),
            Path("audio.mp3"),
            1800,
        )

    def test_preview_failure_keeps_error_and_offers_explicit_alternatives(self) -> None:
        for status in (408, 500, 503):
            with self.subTest(status=status):
                error = UserFacingError(
                    f"Azure Speech API returned HTTP {status}: service failed"
                )
                error.__cause__ = urllib.error.HTTPError(
                    "https://speech.example.com", status, "service failed", {}, None
                )
                self.addCleanup(error.__cause__.close)
                with (
                    mock.patch.object(
                        mai.az, "post_transcribe", side_effect=error
                    ) as post,
                    self.assertRaisesRegex(
                        UserFacingError,
                        f"HTTP {status}.*--no-diarize.*--provider scribe",
                    ),
                ):
                    provider().transcribe(Path("audio.mp3"), 1800)
                post.assert_called_once()

    def test_non_diarized_failure_does_not_blame_diarization(self) -> None:
        error = UserFacingError("Azure Speech API returned HTTP 503: service failed")
        error.__cause__ = urllib.error.HTTPError(
            "https://speech.example.com", 503, "service failed", {}, None
        )
        self.addCleanup(error.__cause__.close)
        with (
            mock.patch.object(mai.az, "post_transcribe", side_effect=error),
            self.assertRaises(UserFacingError) as caught,
        ):
            provider(max_speakers=None).transcribe(Path("audio.mp3"), 1800)
        self.assertIs(caught.exception, error)

    def test_credentials_use_the_existing_azure_validation(self) -> None:
        with mock.patch.object(mai.az, "validate_credentials") as validate:
            provider().validate()
        validate.assert_called_once_with("https://speech.example.com", "test-key")

    def test_config_uses_fixed_mai2_model_and_honors_no_diarize(self) -> None:
        config = SimpleNamespace(
            azure_endpoint="https://speech.example.com",
            azure_model="mai-transcribe-1.5",
            azure_transcribe_style="display",
            audio_format="mp3",
            language="en",
            diarize=False,
            max_speakers=8,
        )
        with mock.patch.dict(os.environ, {"AZURE_SPEECH_API_KEY": "test-key"}):
            built = mai.build(config)
        self.assertEqual(built.model, "MAI-Transcribe-2")
        self.assertEqual(built.api_key, "test-key")
        self.assertIsNone(built.max_speakers)

    def test_nondefault_speaker_limit_explains_that_it_cannot_be_honored(self) -> None:
        config = SimpleNamespace(
            azure_endpoint=None,
            azure_transcribe_style="verbatim",
            audio_format="mp3",
            language=None,
            diarize=True,
            max_speakers=2,
        )
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mai.build(config)
        self.assertIn("--max-speakers is not supported", err.getvalue())

    def test_m4a_is_rejected_because_the_service_cannot_decode_it(self) -> None:
        config = SimpleNamespace(
            azure_endpoint=None,
            azure_transcribe_style="display",
            audio_format="m4a",
            language="en",
            diarize=True,
            max_speakers=8,
        )
        with self.assertRaisesRegex(UsageError, "--audio-format m4a.*azure-mai-2"):
            mai.build(config)


if __name__ == "__main__":
    unittest.main()
