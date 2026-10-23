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
        self.assertIn("\nsubtitles for any video, in any language\n", run("--help")[1])

    def test_a_bare_run_prints_the_help_and_whats_missing(self) -> None:
        # Nothing to subtitle is not a failure: WinGet-style checks start tools bare.
        help_text = run("--help")[1]
        self.assertEqual(run(), (0, f"{help_text}\n{cli.MISSING_INPUT}\n", ""))

    def test_help_is_not_a_word_here(self) -> None:
        # The argument is a file, so `subtitler help` must mean a file called help.
        code, out, err = run("help")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("input file does not exist", err)


class VersionTest(unittest.TestCase):
    def test_both_version_flags_print_the_name_and_version(self) -> None:
        for flag in ("-V", "--version"):
            with self.subTest(flag=flag):
                self.assertEqual(run(flag), (0, f"subtitler {__version__}\n", ""))


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
            for argv in (["--no-color", "--help"], ["--help", "--no-color"]):
                with self.subTest(argv=argv):
                    code, out, _ = run(*argv, stdout_tty=True)
                    self.assertEqual(code, 0)
                    self.assertNotIn("\x1b[", out)

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
