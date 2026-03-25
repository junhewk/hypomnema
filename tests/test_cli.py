"""Tests for CLI orchestration."""

from __future__ import annotations

import argparse
import sys
from typing import Any

import hypomnema.cli as cli_mod


class TestLoadSettings:
    def test_load_settings_defaults_to_server_for_serve(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("HYPOMNEMA_MODE", raising=False)
        settings = cli_mod._load_settings("server")
        assert settings.mode == "server"
        assert settings.host == "0.0.0.0"

    def test_load_settings_respects_explicit_mode_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("HYPOMNEMA_MODE", "local")
        settings = cli_mod._load_settings("server")
        assert settings.mode == "local"
        assert settings.host == "127.0.0.1"


class TestMain:
    def test_defaults_to_dev_when_no_subcommand(self, monkeypatch: Any) -> None:
        captured_args: list[argparse.Namespace] = []

        def fake_cmd_dev(args: argparse.Namespace) -> None:
            captured_args.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", fake_cmd_dev)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(sys, "argv", ["hypomnema"])

        cli_mod.main()

        assert len(captured_args) == 1
        assert captured_args[0].command == "dev"
        assert captured_args[0].no_browser is False

    def test_dispatches_eval_tidy_text(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_eval(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_eval_tidy_text", fake_eval)
        monkeypatch.setattr(
            sys,
            "argv",
            ["hypomnema", "eval", "tidy-text", "--dataset", "smoke", "--no-judge"],
        )

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].command == "eval"
        assert calls[0].eval_command == "tidy-text"
        assert calls[0].dataset == "smoke"
        assert calls[0].no_judge is True

    def test_dispatches_eval_tidy_text_with_tidy_level(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_eval(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_eval_tidy_text", fake_eval)
        monkeypatch.setattr(
            sys,
            "argv",
            ["hypomnema", "eval", "tidy-text", "--tidy-level", "full_revision"],
        )

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].tidy_level == "full_revision"

    def test_dispatches_eval_tidy_text_matrix(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_eval(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_eval_tidy_text_matrix", fake_eval)
        monkeypatch.setattr(
            sys,
            "argv",
            ["hypomnema", "eval", "tidy-text-matrix"],
        )

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].command == "eval"
        assert calls[0].eval_command == "tidy-text-matrix"
        assert calls[0].tidy_level is None
        assert calls[0].max_cases == 18
        assert calls[0].case_id is None
        assert calls[0].generated_json is None
        assert calls[0].refresh_corpus is False
        assert calls[0].with_judge is False

    def test_dispatches_eval_engram_dedupe(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_eval(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_eval_tidy_text", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_eval_engram_dedupe", fake_eval)
        monkeypatch.setattr(
            sys,
            "argv",
            ["hypomnema", "eval", "engram-dedupe", "--dataset", "full"],
        )

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].command == "eval"
        assert calls[0].eval_command == "engram-dedupe"
        assert calls[0].dataset == "full"

    def test_dispatches_tidy_backfill(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_backfill(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_tidy_backfill", fake_backfill)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "hypomnema",
                "tidy",
                "backfill",
                "--level",
                "light_cleanup",
                "--scope",
                "missing",
            ],
        )

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].command == "tidy"
        assert calls[0].tidy_command == "backfill"
        assert calls[0].level == "light_cleanup"
        assert calls[0].scope == "missing"

    def test_dispatches_desktop(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_desktop(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_desktop", fake_desktop)
        monkeypatch.setattr(sys, "argv", ["hypomnema", "desktop"])

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].command == "desktop"
