"""Tests for CLI orchestration."""

from __future__ import annotations

import argparse
import sys
import types
from typing import TYPE_CHECKING, Any

from hypomnema import cli as cli_mod

if TYPE_CHECKING:
    from pathlib import Path


def _make_frontend_dir(tmp_path: Path) -> Path:
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "package.json").write_text('{"name":"frontend"}', encoding="utf-8")
    return frontend_dir


class TestServeCommand:
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

    def test_build_signature_tracks_frontend_api_env(self) -> None:
        settings = type("Settings", (), {"port": 8073})()
        assert cli_mod._frontend_build_signature(settings) == (
            "NEXT_PUBLIC_API_PORT=8073\n"
            "NEXT_PUBLIC_API_URL=auto"
        )

    def test_rebuilds_when_next_dir_only_contains_dev_artifacts(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        frontend_dir = _make_frontend_dir(tmp_path)
        (frontend_dir / ".next" / "dev").mkdir(parents=True)

        build_calls: list[tuple[list[str], dict[str, Any]]] = []
        run_kwargs: dict[str, Any] = {}

        monkeypatch.setattr(cli_mod, "_FRONTEND_DIR", frontend_dir)
        monkeypatch.setattr(cli_mod, "_find_npm", lambda: "npm")
        monkeypatch.setattr(cli_mod, "_ensure_node_modules", lambda _npm: None)
        monkeypatch.setattr(cli_mod, "_write_frontend_build_signature", lambda *_args: None)

        def fake_build(cmd: list[str], **kwargs: Any) -> None:
            build_calls.append((cmd, kwargs))

        def fake_run(**kwargs: Any) -> None:
            run_kwargs.update(kwargs)

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_build)
        monkeypatch.setattr(cli_mod, "_run", fake_run)

        cli_mod.cmd_serve(argparse.Namespace(build=False))

        assert len(build_calls) == 1
        cmd, kwargs = build_calls[0]
        assert cmd == ["npm", "run", "build"]
        assert kwargs["cwd"] == frontend_dir
        assert kwargs["check"] is True
        assert kwargs["env"]["NEXT_PUBLIC_API_URL"] == "auto"
        assert kwargs["env"]["NEXT_PUBLIC_API_PORT"] == "8073"

        assert run_kwargs["frontend_cmd"] == ["npm", "run", "start"]
        assert run_kwargs["reload"] is False
        assert run_kwargs["open_browser"] is False

    def test_skips_rebuild_when_production_build_exists(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        frontend_dir = _make_frontend_dir(tmp_path)
        next_dir = frontend_dir / ".next"
        next_dir.mkdir()
        (next_dir / "BUILD_ID").write_text("build-id", encoding="utf-8")

        build_calls: list[tuple[list[str], dict[str, Any]]] = []
        run_kwargs: dict[str, Any] = {}

        monkeypatch.setattr(cli_mod, "_FRONTEND_DIR", frontend_dir)
        monkeypatch.setattr(cli_mod, "_find_npm", lambda: "npm")
        monkeypatch.setattr(cli_mod, "_ensure_node_modules", lambda _npm: None)
        monkeypatch.setattr(cli_mod, "_write_frontend_build_signature", lambda *_args: None)

        build_env_file = next_dir / cli_mod._FRONTEND_BUILD_ENV_FILE
        build_env_file.write_text(
            cli_mod._frontend_build_signature(type("Settings", (), {"port": 8073})()),
            encoding="utf-8",
        )

        def fake_build(cmd: list[str], **kwargs: Any) -> None:
            build_calls.append((cmd, kwargs))

        def fake_run(**kwargs: Any) -> None:
            run_kwargs.update(kwargs)

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_build)
        monkeypatch.setattr(cli_mod, "_run", fake_run)

        cli_mod.cmd_serve(argparse.Namespace(build=False))

        assert build_calls == []
        assert run_kwargs["frontend_cmd"] == ["npm", "run", "start"]

    def test_rebuilds_when_cached_build_env_is_outdated(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        frontend_dir = _make_frontend_dir(tmp_path)
        next_dir = frontend_dir / ".next"
        next_dir.mkdir()
        (next_dir / "BUILD_ID").write_text("build-id", encoding="utf-8")
        (next_dir / cli_mod._FRONTEND_BUILD_ENV_FILE).write_text(
            "NEXT_PUBLIC_API_PORT=9000\nNEXT_PUBLIC_API_URL=auto",
            encoding="utf-8",
        )

        build_calls: list[tuple[list[str], dict[str, Any]]] = []

        monkeypatch.setattr(cli_mod, "_FRONTEND_DIR", frontend_dir)
        monkeypatch.setattr(cli_mod, "_find_npm", lambda: "npm")
        monkeypatch.setattr(cli_mod, "_ensure_node_modules", lambda _npm: None)
        monkeypatch.setattr(cli_mod, "_run", lambda **_kwargs: None)
        monkeypatch.setattr(cli_mod, "_write_frontend_build_signature", lambda *_args: None)

        def fake_build(cmd: list[str], **kwargs: Any) -> None:
            build_calls.append((cmd, kwargs))

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_build)

        cli_mod.cmd_serve(argparse.Namespace(build=False))

        assert len(build_calls) == 1

    def test_run_exports_backend_mode_for_factory_app(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        frontend_dir = _make_frontend_dir(tmp_path)
        captured: dict[str, str] = {}

        class FakeProc:
            def terminate(self) -> None:
                return None

            def wait(self, timeout: int) -> None:
                return None

        def fake_uvicorn_run(*args: Any, **kwargs: Any) -> None:
            captured["mode"] = cli_mod.os.environ.get("HYPOMNEMA_MODE", "")
            captured["host"] = kwargs["host"]

        monkeypatch.setattr(cli_mod, "_FRONTEND_DIR", frontend_dir)
        monkeypatch.setattr(cli_mod, "_ensure_frontend", lambda: None)
        monkeypatch.setattr(cli_mod, "_ensure_node_modules", lambda _npm: None)
        monkeypatch.setattr(cli_mod.subprocess, "Popen", lambda *args, **kwargs: FakeProc())
        monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
        monkeypatch.delenv("HYPOMNEMA_MODE", raising=False)

        settings = cli_mod._load_settings("server")
        cli_mod._run(
            settings=settings,
            npm="npm",
            reload=False,
            frontend_cmd=["npm", "run", "start"],
            open_browser=False,
        )

        assert captured["mode"] == "server"
        assert captured["host"] == "0.0.0.0"
        assert "HYPOMNEMA_MODE" not in cli_mod.os.environ


class TestMain:
    def test_defaults_to_dev_when_no_subcommand(
        self,
        monkeypatch: Any,
    ) -> None:
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

    def test_dispatches_eval_tidy_text_generation_overrides(self, monkeypatch: Any) -> None:
        calls: list[argparse.Namespace] = []

        def fake_eval(args: argparse.Namespace) -> None:
            calls.append(args)

        monkeypatch.setattr(cli_mod, "cmd_dev", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_serve", lambda _args: None)
        monkeypatch.setattr(cli_mod, "cmd_eval_tidy_text", fake_eval)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "hypomnema",
                "eval",
                "tidy-text",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
            ],
        )

        cli_mod.main()

        assert len(calls) == 1
        assert calls[0].provider == "openai"
        assert calls[0].model == "gpt-5-mini"

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
