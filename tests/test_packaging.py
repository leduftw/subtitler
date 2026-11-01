"""Tests for what ships: the version, the package name and the translation guide.

Standard library only (``python3 -m unittest discover tests``), matching the
project's zero-dependency policy.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from subtitler import __version__, cli, translate, update


def pyproject() -> str:
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


class VersionTest(unittest.TestCase):
    def test_the_package_and_the_code_report_one_version(self) -> None:
        # `playbook release` moves both; the release check refuses a mismatch.
        version = re.search(r'(?m)^version = "([^"]+)"', pyproject())
        assert version is not None
        self.assertEqual(version.group(1), __version__)


class PackageTest(unittest.TestCase):
    def test_update_upgrades_the_package_this_project_publishes(self) -> None:
        name = re.search(r'(?m)^name = "([^"]+)"', pyproject())
        assert name is not None
        self.assertEqual(name.group(1), update.PACKAGE)

    def test_the_guide_is_in_the_package(self) -> None:
        self.assertIn("translation_guide.md", pyproject())


class TranslationGuideTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guide = translate.translation_guide()

    def test_it_covers_the_whole_workflow(self) -> None:
        for words in (
            "--emit-worksheet",
            "--apply-worksheet",
            "Keep every line number",
        ):
            with self.subTest(words=words):
                self.assertIn(words, self.guide)

    def test_it_works_without_a_clone_or_python(self) -> None:
        self.assertNotIn("./subtitler <", self.guide)
        self.assertNotIn("python3", self.guide)
        self.assertNotIn("import ", self.guide)
        self.assertNotIn("align.py", self.guide)

    def test_it_says_what_changes_in_a_clone(self) -> None:
        self.assertIn("`./subtitler`", self.guide)

    def test_help_points_an_agent_at_it(self) -> None:
        self.assertIn("--translation-guide", cli.build_parser().format_help())

    def test_the_worksheet_points_at_it_too(self) -> None:
        cue = translate.parse_srt("1\n00:00:00,000 --> 00:00:01,000\nHola\n")
        self.assertIn(
            "subtitler --translation-guide", translate.emit_worksheet(cue, "es", "en")
        )

    def test_the_guide_doesnt_change_what_a_worksheet_reads_back(self) -> None:
        cues = translate.parse_srt("1\n00:00:00,000 --> 00:00:01,000\nHola\n")
        worksheet = translate.emit_worksheet(cues, "es", "en").replace("Hola", "Hello")
        self.assertEqual(translate.apply_worksheet(worksheet, cues)[0].text, "Hello")

    def test_the_repos_skill_reads_the_same_guide(self) -> None:
        skill = ROOT / ".claude/skills/translate-subtitles/SKILL.md"
        text = skill.read_text(encoding="utf-8")
        self.assertIn("./subtitler --translation-guide", text)
        self.assertIn("src/subtitler/translation_guide.md", text)


if __name__ == "__main__":
    unittest.main()
