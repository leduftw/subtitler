"""Tests for cue construction, speaker handling, and SRT rendering.

Standard library only (``python3 -m unittest discover tests``), matching the
project's zero-dependency policy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_subtitle_cli.align import align_text_to_words  # noqa: E402
from ai_subtitle_cli.providers import _azure_speech as az  # noqa: E402
from ai_subtitle_cli.providers import elevenlabs_scribe as scribe  # noqa: E402
from ai_subtitle_cli.srt import Cue, group_words_into_cues, render_srt  # noqa: E402


def words(*specs: tuple[int, int, str, int | None]) -> list[Cue]:
    return [Cue(start, end, text, speaker) for start, end, text, speaker in specs]


class RenderSrtTest(unittest.TestCase):
    def test_no_speaker_data_renders_without_dashes(self) -> None:
        srt = render_srt([Cue(0, 1000, "Alone here."), Cue(1000, 2000, "Still alone.")])
        self.assertNotIn("- ", srt)

    def test_single_speaker_renders_without_dashes(self) -> None:
        srt = render_srt([Cue(0, 1000, "Just me.", 0), Cue(1000, 2000, "Only me.", 0)])
        self.assertNotIn("- ", srt)

    def test_marks_each_change_of_speaker(self) -> None:
        srt = render_srt(
            [
                Cue(0, 1000, "First speaker.", 0),
                Cue(1000, 2000, "Second speaker.", 1),
                Cue(2000, 3000, "Still the second.", 1),
                Cue(3000, 4000, "Back to the first.", 0),
            ]
        )
        self.assertIn("- First speaker.", srt)
        self.assertIn("- Second speaker.", srt)
        self.assertIn("\nStill the second.", srt)  # continuation: no dash
        self.assertIn("- Back to the first.", srt)

    def test_numbers_cues_sequentially(self) -> None:
        srt = render_srt([Cue(0, 1000, "a"), Cue(1000, 2000, "b"), Cue(2000, 3000, "c")])
        self.assertEqual([line for line in srt.splitlines() if line.isdigit()], ["1", "2", "3"])

    def test_empty_input_renders_empty(self) -> None:
        self.assertEqual(render_srt([]), "")


class GroupWordsTest(unittest.TestCase):
    def test_splits_at_a_change_of_speaker(self) -> None:
        """The interruption case: two voices 50ms apart must not merge into one cue."""
        cues = group_words_into_cues(
            words(
                (7120, 7400, "But,", 0),
                (7400, 7600, "I", 0),
                (7650, 7800, "You", 1),
                (7800, 8000, "don't", 1),
                (8000, 8250, "wanna", 1),
                (8250, 8400, "do", 1),
                (8400, 8700, "that.", 1),
            )
        )
        self.assertEqual([cue.text for cue in cues], ["But, I", "You don't wanna do that."])
        self.assertEqual([cue.speaker for cue in cues], [0, 1])

    def test_still_splits_on_a_long_pause_within_one_speaker(self) -> None:
        cues = group_words_into_cues(
            words((0, 200, "one", 0), (200, 400, "two", 0), (5000, 5200, "later", 0))
        )
        self.assertEqual([cue.text for cue in cues], ["one two", "later"])

    def test_keeps_one_speaker_together(self) -> None:
        cues = group_words_into_cues(words((0, 200, "all", 0), (200, 400, "one", 0), (400, 600, "cue", 0)))
        self.assertEqual([cue.text for cue in cues], ["all one cue"])

    def test_fewer_than_two_words_signals_fallback(self) -> None:
        self.assertEqual(group_words_into_cues(words((0, 200, "lonely", 0))), [])


class AlignTest(unittest.TestCase):
    def test_transfers_timings_and_speakers_onto_transcript_wording(self) -> None:
        timed = words(
            (7120, 7400, "but", 0),
            (7400, 7600, "i", 0),
            (7650, 7800, "you", 1),
            (7800, 8000, "dont", 1),
            (8000, 8250, "wanna", 1),
            (8250, 8400, "do", 1),
            (8400, 8700, "that", 1),
        )
        aligned = align_text_to_words("But, I— You don't wanna do that.", timed)

        self.assertEqual([cue.text for cue in aligned], ["But,", "I—", "You", "don't", "wanna", "do", "that."])
        self.assertEqual([cue.speaker for cue in aligned], [0, 0, 1, 1, 1, 1, 1])
        self.assertEqual(aligned[0].start_ms, 7120)
        self.assertEqual(aligned[-1].end_ms, 8700)

    def test_unmatched_transcript_words_inherit_the_preceding_speaker(self) -> None:
        timed = words((0, 500, "hello", 0), (1000, 1500, "goodbye", 1))
        aligned = align_text_to_words("hello there goodbye", timed)
        speakers = {cue.text: cue.speaker for cue in aligned}
        self.assertEqual(speakers["hello"], 0)
        self.assertEqual(speakers["there"], 0)  # interpolated, attributed to the speaker it follows
        self.assertEqual(speakers["goodbye"], 1)

    def test_cues_never_overlap(self) -> None:
        timed = words((0, 900, "a", 0), (500, 1200, "b", 1), (1100, 1500, "c", 1))
        aligned = align_text_to_words("a b c", timed)
        for earlier, later in zip(aligned, aligned[1:]):
            self.assertLessEqual(earlier.end_ms, later.start_ms)

    def test_empty_inputs_yield_no_cues(self) -> None:
        self.assertEqual(align_text_to_words("", words((0, 100, "x", 0))), [])
        self.assertEqual(align_text_to_words("something", []), [])


class AzureDefinitionTest(unittest.TestCase):
    def test_omits_diarization_when_not_requested(self) -> None:
        self.assertEqual(az.build_fast_definition("en-US", None), {"locales": ["en-US"]})

    def test_enables_diarization_with_max_speakers(self) -> None:
        self.assertEqual(
            az.build_fast_definition("en-US", 2),
            {"locales": ["en-US"], "diarization": {"enabled": True, "maxSpeakers": 2}},
        )

    def test_clamps_max_speakers_to_the_range_azure_accepts(self) -> None:
        self.assertEqual(az.build_fast_definition(None, 1)["diarization"], {"enabled": True, "maxSpeakers": 2})
        self.assertEqual(az.build_fast_definition(None, 99)["diarization"], {"enabled": True, "maxSpeakers": 35})


class AzureResponseTest(unittest.TestCase):
    # Shaped like a real diarized fast-transcription response.
    PAYLOAD = {
        "durationMilliseconds": 9000,
        "combinedPhrases": [{"channel": 0, "text": "But, I You don't wanna do that."}],
        "phrases": [
            {
                "speaker": 0,
                "offsetMilliseconds": 7120,
                "durationMilliseconds": 480,
                "text": "But, I",
                "words": [
                    {"text": "But,", "offsetMilliseconds": 7120, "durationMilliseconds": 280},
                    {"text": "I", "offsetMilliseconds": 7400, "durationMilliseconds": 200},
                ],
            },
            {
                "speaker": 1,
                "offsetMilliseconds": 7650,
                "durationMilliseconds": 1050,
                "text": "You don't wanna do that.",
                "words": [
                    {"text": "You", "offsetMilliseconds": 7650, "durationMilliseconds": 150},
                    {"text": "don't", "offsetMilliseconds": 7800, "durationMilliseconds": 200},
                    {"text": "wanna", "offsetMilliseconds": 8000, "durationMilliseconds": 250},
                    {"text": "do", "offsetMilliseconds": 8250, "durationMilliseconds": 150},
                    {"text": "that.", "offsetMilliseconds": 8400, "durationMilliseconds": 300},
                ],
            },
        ],
    }

    def test_keeps_interrupted_speakers_in_separate_cues(self) -> None:
        cues = az.transcription_to_cues(self.PAYLOAD)
        self.assertEqual([cue.text for cue in cues], ["But, I", "You don't wanna do that."])
        self.assertEqual([cue.speaker for cue in cues], [0, 1])

    def test_renders_dialogue_with_speaker_changes_marked(self) -> None:
        srt = render_srt(az.transcription_to_cues(self.PAYLOAD))
        self.assertIn("- But, I", srt)
        self.assertIn("- You don't wanna do that.", srt)

    def test_words_inherit_their_phrase_speaker(self) -> None:
        collected = az.collect_words(self.PAYLOAD)
        self.assertEqual([word.speaker for word in collected], [0, 0, 1, 1, 1, 1, 1])

    def test_undiarized_response_yields_no_speakers(self) -> None:
        payload = {
            "phrases": [
                {
                    "offsetMilliseconds": 0,
                    "durationMilliseconds": 500,
                    "text": "no speaker field here",
                    "words": [
                        {"text": "no", "offsetMilliseconds": 0, "durationMilliseconds": 200},
                        {"text": "speaker", "offsetMilliseconds": 200, "durationMilliseconds": 300},
                    ],
                }
            ]
        }
        cues = az.transcription_to_cues(payload)
        self.assertTrue(all(cue.speaker is None for cue in cues))
        self.assertNotIn("- ", render_srt(cues))

    def test_falls_back_to_combined_text_when_there_are_no_phrases(self) -> None:
        cues = az.transcription_to_cues({"combinedPhrases": [{"text": "only this"}]})
        self.assertEqual([cue.text for cue in cues], ["only this"])


class ScribeResponseTest(unittest.TestCase):
    # Shaped like a real Scribe v2 response: a flat token stream, seconds, string speaker ids.
    PAYLOAD = {
        "language_code": "en",
        "text": "But, I You don't wanna do that.",
        "words": [
            {"text": "But,", "type": "word", "start": 7.12, "end": 7.40, "speaker_id": "speaker_0"},
            {"text": " ", "type": "spacing", "start": 7.40, "end": 7.40, "speaker_id": "speaker_0"},
            {"text": "I", "type": "word", "start": 7.40, "end": 7.60, "speaker_id": "speaker_0"},
            {"text": "You", "type": "word", "start": 7.65, "end": 7.80, "speaker_id": "speaker_1"},
            {"text": "don't", "type": "word", "start": 7.80, "end": 8.00, "speaker_id": "speaker_1"},
            {"text": "wanna", "type": "word", "start": 8.00, "end": 8.25, "speaker_id": "speaker_1"},
            {"text": "do", "type": "word", "start": 8.25, "end": 8.40, "speaker_id": "speaker_1"},
            {"text": "that.", "type": "word", "start": 8.40, "end": 8.70, "speaker_id": "speaker_1"},
        ],
    }

    def test_converts_seconds_to_milliseconds(self) -> None:
        collected = scribe.collect_words(self.PAYLOAD)
        self.assertEqual((collected[0].start_ms, collected[0].end_ms), (7120, 7400))

    def test_drops_spacing_tokens(self) -> None:
        collected = scribe.collect_words(self.PAYLOAD)
        self.assertEqual([w.text for w in collected][:3], ["But,", "I", "You"])

    def test_maps_speaker_id_strings_to_ints(self) -> None:
        collected = scribe.collect_words(self.PAYLOAD)
        self.assertEqual([w.speaker for w in collected], [0, 0, 1, 1, 1, 1, 1])

    def test_keeps_audio_events_but_not_spacing(self) -> None:
        payload = {
            "words": [
                {"text": "(laughter)", "type": "audio_event", "start": 1.0, "end": 2.0},
                {"text": " ", "type": "spacing", "start": 2.0, "end": 2.0},
            ]
        }
        self.assertEqual([w.text for w in scribe.collect_words(payload)], ["(laughter)"])

    def test_numbers_unrecognized_speaker_labels_by_first_appearance(self) -> None:
        payload = {
            "words": [
                {"text": "a", "type": "word", "start": 0.0, "end": 0.1, "speaker_id": "alice"},
                {"text": "b", "type": "word", "start": 0.1, "end": 0.2, "speaker_id": "bob"},
                {"text": "c", "type": "word", "start": 0.2, "end": 0.3, "speaker_id": "alice"},
            ]
        }
        self.assertEqual([w.speaker for w in scribe.collect_words(payload)], [0, 1, 0])

    def test_undiarized_response_yields_no_speakers(self) -> None:
        payload = {"words": [{"text": "hi", "type": "word", "start": 0.0, "end": 0.5}]}
        self.assertEqual(scribe.collect_words(payload)[0].speaker, None)

    def test_missing_or_malformed_words_yield_nothing(self) -> None:
        self.assertEqual(scribe.collect_words({}), [])
        self.assertEqual(scribe.collect_words({"words": "nope"}), [])
        # A word with no start time can't be placed.
        self.assertEqual(scribe.collect_words({"words": [{"text": "x", "type": "word"}]}), [])

    def test_end_to_end_splits_the_interruption(self) -> None:
        cues = group_words_into_cues(scribe.collect_words(self.PAYLOAD))
        self.assertEqual([c.text for c in cues], ["But, I", "You don't wanna do that."])
        self.assertIn("- But, I", render_srt(cues))

    def test_transcribe_groups_words_into_cues(self) -> None:
        """Scribe times every word, so the provider must group before returning.

        Returning the raw word list yields one subtitle per word.
        """
        provider = scribe.ElevenLabsScribeProvider(
            api_key="stub", language="en", max_speakers=8, tag_audio_events=False
        )
        provider._post = lambda audio_path, timeout: self.PAYLOAD  # type: ignore[method-assign]

        cues = provider.transcribe(Path("unused.mp3"), 30)
        self.assertEqual([c.text for c in cues], ["But, I", "You don't wanna do that."])
        self.assertLess(len(cues), len(scribe.collect_words(self.PAYLOAD)))


class ProviderRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        from ai_subtitle_cli import providers

        self.providers = providers

    def test_only_useful_providers_are_selectable(self) -> None:
        self.assertEqual(
            self.providers.NAMES,
            (self.providers.SCRIBE, self.providers.AZURE_FAST, self.providers.AZURE_HYBRID),
        )

    def test_azure_mai_is_hidden_from_the_cli(self) -> None:
        """MAI alone yields one enormous cue, so it isn't offered as a choice."""
        self.assertNotIn(self.providers.AZURE_MAI, self.providers.NAMES)

    def test_azure_mai_stays_reachable_for_internal_use(self) -> None:
        # azure-hybrid builds MAI requests, and the CLI reads its spec for --azure-model.
        spec = self.providers.spec(self.providers.AZURE_MAI)
        self.assertTrue(spec.internal)
        self.assertEqual(spec.default_model, "mai-transcribe-1.5")

    def test_the_default_provider_is_selectable(self) -> None:
        self.assertIn(self.providers.DEFAULT, self.providers.NAMES)

    def test_every_selectable_provider_can_report_its_languages(self) -> None:
        for name in self.providers.NAMES:
            self.assertTrue(self.providers.spec(name).languages, f"{name} lists no languages")


class ResolveDiarizeTest(unittest.TestCase):
    def setUp(self) -> None:
        from ai_subtitle_cli import providers

        self.providers = providers

    def test_defaults_on_where_supported(self) -> None:
        from ai_subtitle_cli.config import resolve_diarize

        self.assertTrue(resolve_diarize(None, self.providers.spec(self.providers.AZURE_FAST)))
        self.assertTrue(resolve_diarize(None, self.providers.spec(self.providers.AZURE_HYBRID)))
        self.assertTrue(resolve_diarize(None, self.providers.spec(self.providers.SCRIBE)))

    def test_defaults_off_where_unsupported(self) -> None:
        from ai_subtitle_cli.config import resolve_diarize

        self.assertFalse(resolve_diarize(None, self.providers.spec(self.providers.AZURE_MAI)))

    def test_explicit_no_diarize_wins(self) -> None:
        from ai_subtitle_cli.config import resolve_diarize

        self.assertFalse(resolve_diarize(False, self.providers.spec(self.providers.AZURE_FAST)))


if __name__ == "__main__":
    unittest.main()
