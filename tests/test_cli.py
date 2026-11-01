"""Tests for the command line: help, version, exit codes and colors.

Standard library only (``python3 -m unittest discover tests``), matching the
project's zero-dependency policy.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitler import __version__, cli
from subtitler.errors import UserFacingError


def run(
    *argv: str, stdout_tty: bool = False, stderr_tty: bool = False
) -> tuple[int, str, str]:
    """Runs subtitler as a shell would and returns its exit code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    with (
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
        mock.patch.object(out, "isatty", return_value=stdout_tty),
        mock.patch.object(err, "isatty", return_value=stderr_tty),
    ):
        try:
            code = cli.main(list(argv))
        except SystemExit as stop:
            code = stop.code or 0
    return code, out.getvalue(), err.getvalue()


def forced_colors(**extra: str):
    """An environment where Python colors output even though it isn't a terminal."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("NO_COLOR", "PYTHON_COLORS", "TERM")
    }
    return mock.patch.dict(os.environ, {**env, "FORCE_COLOR": "1", **extra}, clear=True)


class HelpTest(unittest.TestCase):
    def test_both_help_flags_print_the_same_help(self) -> None:
        code, expected, err = run("--help")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("usage: subtitler", expected)
        self.assertEqual(run("-h"), (0, expected, ""))

    def test_the_description_is_the_repos_description(self) -> None:
        self.assertIn("\nSubtitles for any video, in any language.\n", run("--help")[1])

    def test_a_bare_run_prints_the_help_and_whats_missing(self) -> None:
        # Nothing to subtitle is not a failure: WinGet-style checks start tools bare.
        help_text = run("--help")[1]
        self.assertEqual(run(), (0, f"{help_text}\n{cli.MISSING_INPUT}\n", ""))

    def test_the_help_word_prints_the_same_help(self) -> None:
        expected = run("--help")[1]
        self.assertEqual(run("help"), (0, expected, ""))
        self.assertEqual(run("--no-color", "help"), (0, expected, ""))

    def test_help_says_how_to_reach_a_file_named_like_a_command(self) -> None:
        self.assertIn("./help", run("--help")[1])

    def test_help_of_one_command(self) -> None:
        for argv in (("help", "update"), ("help", "upgrade"), ("update", "--help")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv)
                self.assertEqual((code, err), (0, ""))
                self.assertIn("usage: subtitler update", out)
                self.assertIn("latest release", out)

    def test_upgrade_is_the_same_command_as_update(self) -> None:
        self.assertEqual(run("upgrade", "--help"), run("update", "--help"))

    def test_update_has_help_of_its_own(self) -> None:
        self.assertNotEqual(run("update", "--help")[1], run("--help")[1])

    def test_an_unknown_command_after_help_is_a_mistake(self) -> None:
        code, out, err = run("help", "bogus")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("subtitler help: error:", err)

    def test_a_mistake_on_a_command_exits_2(self) -> None:
        code, out, err = run("update", "--bogus")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("subtitler: error: unrecognized arguments: --bogus", err)

    def test_command_words_and_flags_can_still_be_input_filenames(self) -> None:
        for argv, name in (
            (["./help"], "help"),
            (["./version"], "version"),
            (["./update"], "update"),
            (["./upgrade"], "upgrade"),
            (["--", "help"], "help"),
            (["--", "--no-color"], "--no-color"),
            (["--provider", "scribe", "update"], "update"),
        ):
            with (
                self.subTest(argv=argv),
                mock.patch("subtitler.cli.run", return_value=0) as pipeline,
            ):
                self.assertEqual(run(*argv), (0, "", ""))
                self.assertEqual(pipeline.call_args.args[0].input_path.name, name)

    def test_help_describes_only_current_provider_defaults(self) -> None:
        self.assertNotIn("OpenAI", run("--help")[1])


class VersionTest(unittest.TestCase):
    def test_every_form_prints_the_name_and_version(self) -> None:
        for form in ("-V", "--version", "version"):
            with self.subTest(form=form):
                self.assertEqual(run(form), (0, f"subtitler {__version__}\n", ""))


class UpdateCommandTest(unittest.TestCase):
    def test_update_and_upgrade_run_the_update(self) -> None:
        for word in ("update", "upgrade"):
            with (
                self.subTest(word=word),
                mock.patch("subtitler.update.run", return_value=0) as update,
            ):
                self.assertEqual(run(word), (0, "", ""))
                update.assert_called_once_with()

    def test_a_failed_update_exits_1_with_a_message(self) -> None:
        failure = UserFacingError("can't check the latest release: offline")
        with mock.patch("subtitler.update.run", side_effect=failure):
            self.assertEqual(
                run("update"),
                (1, "", "subtitler: can't check the latest release: offline\n"),
            )


class ExitCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.empty_srt = self.root / "empty.srt"
        self.empty_srt.write_text("", encoding="utf-8")
        self.addCleanup(self.temp.cleanup)

    def test_command_line_mistakes_exit_2_with_a_message_on_stderr(self) -> None:
        srt = str(self.empty_srt)
        for argv in (
            ["--bogus"],
            ["--provider", "bogus"],
            ["--max-speakers", "x"],
            [str(self.root / "missing.mp4")],
            [str(self.root)],
            ["--provider", "scribe"],
            [srt, "--emit-worksheet", str(self.root / "ws.txt")],
            [srt, "--emit-worksheet", "a", "--apply-worksheet", "b"],
            [srt, "--apply-worksheet", str(self.root / "ws.txt")],
            [
                srt,
                "--apply-worksheet",
                str(self.root / "nope.txt"),
                "--target-language",
                "en",
            ],
            [
                str(self.root / "nope.srt"),
                "--emit-worksheet",
                "ws.txt",
                "--target-language",
                "en",
            ],
        ):
            with self.subTest(argv=argv):
                code, out, err = run(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("subtitler: error:", err)

    def test_a_failure_while_running_exits_1(self) -> None:
        code, out, err = run(
            str(self.empty_srt),
            "--emit-worksheet",
            str(self.root / "ws.txt"),
            "--target-language",
            "en",
        )
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("subtitler: no subtitle cues found in "), err)

    def test_invalid_input_is_rejected_before_checking_external_tools(self) -> None:
        with mock.patch("subtitler.media.shutil.which", return_value=None):
            code, out, err = run(str(self.root / "missing.mp4"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("subtitler: error: input file does not exist", err)

    def test_a_valid_input_without_tools_is_a_runtime_failure(self) -> None:
        with mock.patch("subtitler.media.shutil.which", return_value=None):
            code, out, err = run(str(self.empty_srt))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("subtitler: ffmpeg is required", err)

    def test_filesystem_and_encoding_failures_have_clean_diagnostics(self) -> None:
        valid = self.root / "valid.srt"
        valid.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        invalid = self.root / "invalid.srt"
        invalid.write_bytes(b"\xff\xfe")
        for source, destination in (
            (valid, self.root),
            (invalid, self.root / "worksheet.txt"),
        ):
            with self.subTest(source=source):
                code, out, err = run(
                    str(source),
                    "--emit-worksheet",
                    str(destination),
                    "--target-language",
                    "en",
                )
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("subtitler: "), err)
                self.assertNotIn("Traceback", err)

    @unittest.skipUnless(
        sys.version_info >= (3, 14), "argparse suggests fixes from Python 3.14 on"
    )
    def test_a_typo_gets_a_suggestion(self) -> None:
        self.assertIn("maybe you meant 'scribe'?", run("--provider", "scrbe")[2])


@unittest.skipUnless(
    sys.version_info >= (3, 14), "argparse colors its output from Python 3.14 on"
)
class ColorTest(unittest.TestCase):
    def test_help_is_colored_in_a_terminal(self) -> None:
        with forced_colors():
            self.assertIn("\x1b[", run("--help", stdout_tty=True)[1])

    def test_no_color_turns_colors_off_wherever_it_appears(self) -> None:
        with forced_colors():
            for argv in (
                ["--no-color", "--help"],
                ["--help", "--no-color"],
                ["--no-col", "--help"],
                ["--help", "--no-col"],
            ):
                with self.subTest(argv=argv):
                    code, out, _ = run(*argv, stdout_tty=True)
                    self.assertEqual(code, 0)
                    self.assertNotIn("\x1b[", out)

    def test_no_color_scanning_preserves_data_and_other_options(self) -> None:
        with forced_colors():
            self.assertIn("\x1b[", run("--no-diarize", "--help", stdout_tty=True)[1])
            code, _, err = run("--", "--no-color", stderr_tty=True)
            self.assertEqual(code, 2)
            self.assertIn("\x1b[", err)

    def test_no_color_and_a_dumb_terminal_win_over_python_settings(self) -> None:
        for env in ({"NO_COLOR": "1"}, {"TERM": "dumb"}):
            with self.subTest(env=env), forced_colors(PYTHON_COLORS="1", **env):
                self.assertNotIn("\x1b[", run("--help", stdout_tty=True)[1])
                self.assertNotIn(
                    "\x1b[", run("--bogus", stdout_tty=True, stderr_tty=True)[2]
                )

    def test_redirected_output_stays_plain(self) -> None:
        with forced_colors():
            self.assertNotIn("\x1b[", run("--help")[1])
            self.assertNotIn("\x1b[", run("--bogus")[2])


if __name__ == "__main__":
    unittest.main()
