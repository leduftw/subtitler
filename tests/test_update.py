"""Tests for `subtitler update`: telling the channel, and what each one runs.

Standard library only (``python3 -m unittest discover tests``), matching the
project's zero-dependency policy.
"""

from __future__ import annotations

import contextlib
import email.message
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitler import update
from subtitler.errors import UserFacingError

NOWHERE = Path("/nowhere")


class ChannelTest(unittest.TestCase):
    def test_homebrew_keeps_subtitler_in_its_cellar(self) -> None:
        for path in (
            "/opt/homebrew/Cellar/subtitler/1.0.0/bin/subtitler",
            "/usr/local/Cellar/subtitler/1.0.0/bin/subtitler",
            "/home/linuxbrew/.linuxbrew/Cellar/subtitler/1.0.0/bin/subtitler",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    update.channel_of(Path(path), True, NOWHERE), update.HOMEBREW
                )

    def test_winget_keeps_subtitler_in_its_packages_folder(self) -> None:
        package = "leduftw.subtitler_Microsoft.Winget.Source_8wekyb3d8bbwe"
        for root in (
            r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages",
            r"C:\Program Files\WinGet\Packages",
            r"C:\Program Files (x86)\WinGet\Packages",
            r"D:\Portable apps",
        ):
            path = Path(f"{root}\\{package}\\subtitler.exe")
            with self.subTest(path=path):
                self.assertEqual(update.channel_of(path, True, NOWHERE), update.WINGET)

    def test_winget_identity_matches_a_whole_directory_ignoring_case(self) -> None:
        package = "LEDUFTW.SUBTITLER_MICROSOFT.WINGET.SOURCE_8WEKYB3D8BBWE"
        self.assertEqual(
            update.channel_of(
                Path(f"D:/Portable/{package}/subtitler.exe"), True, NOWHERE
            ),
            update.WINGET,
        )
        for path in (
            f"D:/Portable/backup-{package}/subtitler.exe",
            f"D:/Portable/{package}-backup/subtitler.exe",
            f"D:/Portable/{package}",
            "C:/Users/me/AppData/Local/Microsoft/WinGet/subtitler.exe",
            "C:/Program Files/WinGet/Packages/another.tool/subtitler.exe",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    update.channel_of(Path(path), True, NOWHERE), update.INSTALLER
                )

    def test_any_other_standalone_program_came_from_the_installer(self) -> None:
        for path in ("/home/me/.local/bin/subtitler", "/usr/local/bin/subtitler"):
            with self.subTest(path=path):
                self.assertEqual(
                    update.channel_of(Path(path), True, NOWHERE), update.INSTALLER
                )

    def test_uv_and_pipx_leave_a_file_in_the_environment_they_made(self) -> None:
        for name, channel in (
            ("uv-receipt.toml", update.UV),
            ("pipx_metadata.json", update.PIPX),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                environment = Path(temp)
                (environment / name).write_text("", encoding="utf-8")
                module = (
                    environment / "lib/python3.13/site-packages/subtitler/update.py"
                )
                self.assertEqual(update.channel_of(module, False, environment), channel)

    def test_pip_installs_into_site_packages(self) -> None:
        for path in (
            "/home/me/.venv/lib/python3.13/site-packages/subtitler/update.py",
            "/usr/lib/python3/dist-packages/subtitler/update.py",
            r"C:\Python314\Lib\site-packages\subtitler\update.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    update.channel_of(Path(path), False, NOWHERE), update.PIP
                )

    def test_anything_else_is_a_clone(self) -> None:
        path = Path("/home/me/subtitler/src/subtitler/update.py")
        self.assertEqual(update.channel_of(path, False, NOWHERE), update.CLONE)

    def test_a_clone_stays_a_clone_in_a_tool_managers_environment(self) -> None:
        path = Path("/home/me/subtitler/src/subtitler/update.py")
        for name in ("uv-receipt.toml", "pipx_metadata.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                environment = Path(temp)
                (environment / name).write_text("", encoding="utf-8")
                self.assertEqual(
                    update.channel_of(path, False, environment), update.CLONE
                )

    def test_a_clone_inside_a_folder_called_cellar_is_still_a_clone(self) -> None:
        path = Path("/Cellar/subtitler/src/subtitler/update.py")
        self.assertEqual(update.channel_of(path, False, NOWHERE), update.CLONE)


class PlanTest(unittest.TestCase):
    def command(self, channel: str, windows: bool = False) -> list[str]:
        chosen = update.plan(channel, NOWHERE, windows)
        assert chosen is not None
        return chosen.command

    def test_each_channel_updates_with_its_own_tool(self) -> None:
        self.assertEqual(
            self.command(update.HOMEBREW), ["brew", "upgrade", "leduftw/tap/subtitler"]
        )
        self.assertEqual(
            self.command(update.WINGET, windows=True),
            ["winget", "upgrade", "--id", "leduftw.subtitler"],
        )
        self.assertEqual(
            self.command(update.UV), ["uv", "tool", "upgrade", "leduftw-subtitler"]
        )
        self.assertEqual(
            self.command(update.PIPX), ["pipx", "upgrade", "leduftw-subtitler"]
        )

    def test_pip_upgrades_the_python_running_subtitler(self) -> None:
        self.assertEqual(
            self.command(update.PIP),
            [sys.executable, "-m", "pip", "install", "--upgrade", "leduftw-subtitler"],
        )

    def test_nothing_updates_a_clone(self) -> None:
        self.assertIsNone(update.plan(update.CLONE, NOWHERE, False))

    def test_windows_cant_replace_a_running_program(self) -> None:
        for channel in (update.WINGET, update.UV, update.PIPX, update.PIP):
            with self.subTest(channel=channel):
                chosen = update.plan(channel, NOWHERE, True)
                assert chosen is not None
                self.assertTrue(chosen.detach)
        chosen = update.plan(update.HOMEBREW, NOWHERE, False)
        assert chosen is not None
        self.assertFalse(chosen.detach)

    def test_the_installer_reinstalls_into_the_same_folder(self) -> None:
        unix = update.plan(update.INSTALLER, NOWHERE, False)
        assert unix is not None
        self.assertEqual(unix.command[0], "sh")
        self.assertIn(update.INSTALLER_SH, unix.command[-1])
        self.assertEqual(unix.install_dir, NOWHERE)
        self.assertFalse(unix.detach)

        windows = update.plan(update.INSTALLER, NOWHERE, True)
        assert windows is not None
        self.assertEqual(windows.command[0], "powershell")
        self.assertIn(update.INSTALLER_PS1, windows.command[-1])
        self.assertTrue(windows.detach)

    def test_the_installer_is_told_the_version_and_the_folder(self) -> None:
        chosen = update.plan(update.INSTALLER, NOWHERE, False)
        assert chosen is not None
        environment = update.update_environment(chosen, "1.4.0")
        self.assertEqual(environment["SUBTITLER_VERSION"], "1.4.0")
        self.assertEqual(environment["SUBTITLER_INSTALL_DIR"], str(NOWHERE))

    def test_a_package_manager_gets_no_installer_settings(self) -> None:
        chosen = update.plan(update.HOMEBREW, NOWHERE, False)
        assert chosen is not None
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(update.update_environment(chosen, "1.4.0"), {})


@unittest.skipIf(os.name == "nt", "these use a POSIX shell")
class CarryOutTest(unittest.TestCase):
    def test_a_failed_download_cant_run_a_partial_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            curl = folder / "curl"
            curl.write_text(
                f"#!/bin/sh\necho 'touch {folder}/ran'\nexit 22\n", encoding="utf-8"
            )
            curl.chmod(0o755)
            chosen = update.plan(update.INSTALLER, folder, False)
            assert chosen is not None
            path = f"{folder}{os.pathsep}/usr/bin{os.pathsep}/bin"
            with (
                mock.patch.dict(os.environ, {"PATH": path}),
                self.assertRaisesRegex(UserFacingError, "exit code 22"),
            ):
                update.carry_out(chosen, "1.4.0")
            self.assertFalse((folder / "ran").exists())

    def test_a_missing_package_manager_is_reported(self) -> None:
        chosen = update.Plan("Homebrew", ["/nowhere/brew"])
        with self.assertRaisesRegex(UserFacingError, "can't run /nowhere/brew"):
            update.carry_out(chosen, "1.4.0")

    def test_a_package_manager_failure_is_reported(self) -> None:
        chosen = update.Plan("Homebrew", ["sh", "-c", "exit 9"])
        with self.assertRaisesRegex(
            UserFacingError, r"Homebrew didn't finish the update \(exit code 9\)"
        ):
            update.carry_out(chosen, "1.4.0")


class VersionTest(unittest.TestCase):
    def test_versions_compare_as_numbers(self) -> None:
        self.assertEqual(update.parse_version("1.10.0"), (1, 10, 0))
        self.assertGreater(
            update.parse_version("1.10.0"), update.parse_version("1.9.9")
        )

    def test_anything_else_isnt_a_version(self) -> None:
        for text in ("1.2", "1.2.3.4", "v1.2.3", "1.2.x", "", "1.2.٣"):
            with self.subTest(text=text):
                self.assertIsNone(update.parse_version(text))

    def test_the_latest_release_comes_from_where_the_redirect_lands(self) -> None:
        base = "https://github.com/leduftw/subtitler/releases"
        self.assertEqual(update.version_from_url(f"{base}/tag/v1.4.0"), "1.4.0")
        self.assertIsNone(update.version_from_url(base))
        self.assertIsNone(update.version_from_url(""))


class RunTest(unittest.TestCase):
    """The whole command, with the network and the channel's tool replaced."""

    def run_update(
        self, latest: str, channel: str = update.HOMEBREW, published: bool = True
    ) -> tuple[str, mock.Mock]:
        output = io.StringIO()
        with (
            mock.patch.object(update, "__version__", "1.2.0"),
            mock.patch.object(update, "channel_of", return_value=channel),
            mock.patch.object(update, "latest_version", return_value=latest),
            mock.patch.object(update, "published", return_value=published),
            mock.patch.object(update, "carry_out") as carry_out,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(update.run(), 0)
        return output.getvalue(), carry_out

    def test_the_latest_version_needs_nothing(self) -> None:
        output, carry_out = self.run_update("1.2.0")
        self.assertEqual(output, "subtitler 1.2.0 is the latest version.\n")
        carry_out.assert_not_called()

    def test_a_newer_copy_is_left_alone(self) -> None:
        output, carry_out = self.run_update("1.1.9")
        self.assertIn("newer than the latest release, 1.1.9", output)
        carry_out.assert_not_called()

    def test_a_newer_release_is_installed_through_the_channel(self) -> None:
        output, carry_out = self.run_update("1.3.0")
        self.assertEqual(output, "Updating subtitler 1.2.0 to 1.3.0 with Homebrew.\n")
        self.assertEqual(carry_out.call_args.args[1], "1.3.0")

    def test_a_release_not_on_winget_yet_says_so(self) -> None:
        output, carry_out = self.run_update("1.3.0", update.WINGET, published=False)
        self.assertIn("not on WinGet yet", output)
        carry_out.assert_not_called()

    def test_a_release_not_on_pypi_yet_says_so(self) -> None:
        for channel in (update.UV, update.PIPX, update.PIP):
            with self.subTest(channel=channel):
                output, carry_out = self.run_update("1.3.0", channel, published=False)
                self.assertIn("not on PyPI yet", output)
                carry_out.assert_not_called()

    def test_a_clone_is_refused_before_anything_goes_online(self) -> None:
        with (
            mock.patch.object(update, "channel_of", return_value=update.CLONE),
            mock.patch.object(update, "latest_version") as latest,
            self.assertRaisesRegex(UserFacingError, "git pull"),
        ):
            update.run()
        latest.assert_not_called()


def landing_on(url: str) -> mock.MagicMock:
    """What urlopen returns after following redirects to ``url``."""
    response = mock.MagicMock()
    response.__enter__.return_value.geturl.return_value = url
    return response


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.com", code, "error", email.message.Message(), None
    )


class NetworkTest(unittest.TestCase):
    def test_the_latest_version_is_read_from_the_redirect(self) -> None:
        landed = f"{update.LATEST_RELEASE.removesuffix('latest')}tag/v1.4.0"
        with mock.patch("urllib.request.urlopen", return_value=landing_on(landed)):
            self.assertEqual(update.latest_version(), "1.4.0")

    def test_no_release_yet_is_reported(self) -> None:
        landed = update.LATEST_RELEASE.removesuffix("/latest")
        with (
            mock.patch("urllib.request.urlopen", return_value=landing_on(landed)),
            self.assertRaisesRegex(UserFacingError, "no release"),
        ):
            update.latest_version()

    def test_being_offline_is_reported(self) -> None:
        offline = urllib.error.URLError("no route to host")
        with (
            mock.patch("urllib.request.urlopen", side_effect=offline),
            self.assertRaisesRegex(UserFacingError, "can't check the latest release"),
        ):
            update.latest_version()

    def test_a_missing_file_means_not_published(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=http_error(404)):
            self.assertFalse(update.published("https://example.com", "WinGet"))

    def test_any_other_error_isnt_read_as_not_published(self) -> None:
        with (
            mock.patch("urllib.request.urlopen", side_effect=http_error(503)),
            self.assertRaisesRegex(UserFacingError, "can't check WinGet"),
        ):
            update.published("https://example.com", "WinGet")


if __name__ == "__main__":
    unittest.main()
