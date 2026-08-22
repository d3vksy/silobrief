from __future__ import annotations

import contextlib
import io
import sys
import unittest
from importlib.metadata import version
from unittest import mock

from silobrief import __version__
from silobrief.chat_review import ChatReviewError
from silobrief.cli import main
from silobrief.interactive_prompt import PromptComposition
from silobrief.state import SetupError


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class CommandLineTests(unittest.TestCase):
    def test_brief_closes_approval_after_success_rejection_and_base_exceptions(self) -> None:
        class FatalReview(BaseException):
            pass

        for phase in ("success", "rejected", "keyboard", "base"):
            with self.subTest(phase=phase):
                approval = mock.Mock()
                snapshot = mock.Mock(warnings=())
                notes_error = FatalReview("stop") if phase == "base" else None
                review_error: BaseException | None = None
                if phase == "rejected":
                    review_error = ChatReviewError("rejected")
                elif phase == "keyboard":
                    review_error = KeyboardInterrupt()
                stderr = io.StringIO()
                stdout = io.StringIO()

                with (
                    mock.patch("silobrief.cli.find_project_root", return_value=mock.sentinel.root),
                    mock.patch(
                        "silobrief.cli.load_current_index_for_approval",
                        return_value=(mock.sentinel.index, snapshot, approval),
                    ),
                    mock.patch(
                        "silobrief.cli.load_language_settings",
                        return_value={"cli_language": "en", "brief_language": "en"},
                    ),
                    mock.patch("silobrief.cli.load_notes", side_effect=notes_error),
                    mock.patch(
                        "silobrief.cli.review_brief",
                        return_value=mock.sentinel.rendered,
                        side_effect=review_error,
                    ),
                    mock.patch("silobrief.cli.approve_and_write") as write,
                    contextlib.redirect_stderr(stderr),
                    contextlib.redirect_stdout(stdout),
                ):
                    if phase == "success":
                        self.assertEqual(main(["brief", "request", "--out", "brief.md"]), 0)
                        write.assert_called_once()
                    elif phase == "rejected":
                        self.assertEqual(main(["brief", "request", "--out", "brief.md"]), 4)
                    else:
                        expected = KeyboardInterrupt if phase == "keyboard" else FatalReview
                        with self.assertRaises(expected):
                            main(["brief", "request", "--out", "brief.md"])

                approval.close.assert_called_once_with()

    def test_brief_without_prompt_uses_interactive_composer_targets(self) -> None:
        approval = mock.Mock()
        snapshot = mock.Mock(warnings=(), root_identity=mock.sentinel.identity)
        stdout = TtyBuffer()
        stdin = TtyBuffer()

        with (
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch("silobrief.cli.find_project_root", return_value=mock.sentinel.root),
            mock.patch(
                "silobrief.cli.load_current_index_for_approval",
                return_value=(mock.sentinel.index, snapshot, approval),
            ),
            mock.patch(
                "silobrief.cli.load_language_settings",
                return_value={"cli_language": "ko", "brief_language": "ko"},
            ),
            mock.patch("silobrief.cli.load_notes", return_value=mock.sentinel.notes),
            mock.patch(
                "silobrief.cli.load_source_config",
                return_value=(mock.sentinel.config, mock.sentinel.identity),
            ),
            mock.patch(
                "silobrief.cli.list_allowed_file_paths",
                return_value=("app.py", "requirements.txt"),
            ),
            mock.patch(
                "silobrief.cli.compose_brief_prompt",
                return_value=PromptComposition("JWT를 추가해줘", ("login-node",)),
            ) as compose,
            mock.patch("silobrief.cli.review_brief", return_value=mock.sentinel.rendered) as review,
            mock.patch("silobrief.cli.approve_and_write") as write,
        ):
            self.assertEqual(main(["brief"]), 0)

        compose.assert_called_once_with(
            mock.sentinel.index,
            ("app.py", "requirements.txt"),
            language="ko",
        )
        self.assertEqual(
            review.call_args.args[:3],
            ("JWT를 추가해줘", mock.sentinel.index, mock.sentinel.notes),
        )
        self.assertEqual(review.call_args.kwargs["initial_selectors"], ("login-node",))
        write.assert_called_once()
        self.assertEqual(write.call_args.args[1], ".silobrief/exports/brief.md")
        approval.close.assert_called_once_with()

    def test_argparse_error_escapes_terminal_control_characters(self) -> None:
        osc = "\x1b]52;c;Y2xpcGJvYXJk\x07"
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["setup", ".", f"unexpected{osc}\r\nforged"])

        visible = stderr.getvalue()
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(osc, visible)
        self.assertNotIn("\r\nforged", visible)
        self.assertIn("unexpected\\x1b]52;c;Y2xpcGJvYXJk\\x07\\r\\nforged", visible)

    def test_command_error_escapes_untrusted_message(self) -> None:
        osc = "\x1b]52;c;Y2xpcGJvYXJk\x07"
        stderr = io.StringIO()

        with (
            mock.patch("silobrief.cli.find_project_root", side_effect=SetupError(osc)),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as caught,
        ):
            main(["search", "request"])

        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(osc, stderr.getvalue())
        self.assertIn("\\x1b]52;c;Y2xpcGJvYXJk\\x07", stderr.getvalue())

    def test_requires_a_subcommand(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main([])

        self.assertEqual(caught.exception.code, 2)
        self.assertIn("usage: sb", stderr.getvalue())
        self.assertIn(
            "{setup,example,ignore,unignore,init,log,search,language,brief,chat}",
            stderr.getvalue(),
        )

    def test_help_lists_commands_and_succeeds(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["--help"])

        self.assertEqual(caught.exception.code, 0)
        self.assertIn(
            "{setup,example,ignore,unignore,init,log,search,language,brief,chat}",
            stdout.getvalue(),
        )
        self.assertIn("Deprecated alias for 'brief'", stdout.getvalue())


class VersionCommandTests(unittest.TestCase):
    def test_version_uses_installed_package_metadata(self) -> None:
        self.assertEqual(__version__, version("silobrief"))

    def test_version_prints_public_product_name(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["--version"])

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "siloBrief 1.2.0\n")
