"""Tests for CLI orchestration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from hypomnema import cli as cli_mod


def _make_frontend_dir(tmp_path: Path) -> Path:
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "package.json").write_text('{"name":"frontend"}', encoding="utf-8")
    return frontend_dir


class TestServeCommand:
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
        assert kwargs["env"]["NEXT_PUBLIC_API_URL"] == "http://127.0.0.1:8073"

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

        def fake_build(cmd: list[str], **kwargs: Any) -> None:
            build_calls.append((cmd, kwargs))

        def fake_run(**kwargs: Any) -> None:
            run_kwargs.update(kwargs)

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_build)
        monkeypatch.setattr(cli_mod, "_run", fake_run)

        cli_mod.cmd_serve(argparse.Namespace(build=False))

        assert build_calls == []
        assert run_kwargs["frontend_cmd"] == ["npm", "run", "start"]


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
