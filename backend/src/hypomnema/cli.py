"""CLI entry point — single command to run Hypomnema."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hypomnema.config import Settings

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend"


def _find_npm() -> str:
    npm = shutil.which("npm")
    if npm is None:
        print("Error: Node.js not found. Install from https://nodejs.org", file=sys.stderr)
        sys.exit(1)
    return npm


def _ensure_frontend() -> None:
    if not (_FRONTEND_DIR / "package.json").exists():
        print(f"Error: frontend/package.json not found at {_FRONTEND_DIR}", file=sys.stderr)
        sys.exit(1)


def _ensure_node_modules(npm: str) -> None:
    if not (_FRONTEND_DIR / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run([npm, "install"], cwd=_FRONTEND_DIR, check=True)


def _has_production_frontend_build(next_dir: Path) -> bool:
    """Return whether `.next` contains a production build usable by `next start`."""
    return next_dir.exists() and (next_dir / "BUILD_ID").is_file()


def _open_when_ready(url: str, port: int, timeout: int = 30) -> None:
    import webbrowser

    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(f"http://localhost:{port}", timeout=2)  # noqa: S310
            webbrowser.open(url)
            return
        except Exception:  # noqa: BLE001
            sleep(0.5)


def _resolve_host(settings: "Settings") -> str:
    """Resolve the host for URLs that browsers will use.

    0.0.0.0 binds all interfaces but isn't a valid browser URL — resolve to
    the machine's hostname so remote clients can reach the backend.
    """
    import socket

    host = settings.host
    if host == "0.0.0.0":  # noqa: S104
        host = socket.gethostname()
        try:
            host = socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
        except OSError:
            pass
    return host


def _frontend_env(settings: "Settings") -> dict[str, str]:
    """Build environment for the frontend process."""
    public_host = _resolve_host(settings)
    env = {
        **os.environ,
        "PORT": str(settings.frontend_port),
        "NEXT_PUBLIC_API_URL": f"http://{public_host}:{settings.port}",
    }
    # In server mode, bind Next.js to all interfaces so it's reachable remotely
    if settings.is_remote:
        env["HOSTNAME"] = "0.0.0.0"
    return env


def _run(
    *,
    settings: "Settings",
    npm: str,
    reload: bool,
    frontend_cmd: list[str],
    open_browser: bool,
) -> None:
    import uvicorn

    _ensure_frontend()
    _ensure_node_modules(npm)

    frontend_proc = subprocess.Popen(
        frontend_cmd,
        cwd=_FRONTEND_DIR,
        env=_frontend_env(settings),
    )

    if open_browser:
        url = f"http://localhost:{settings.frontend_port}"
        threading.Thread(
            target=_open_when_ready,
            args=(url, settings.frontend_port),
            daemon=True,
        ).start()

    try:
        uvicorn.run(
            "hypomnema.main:create_app",
            factory=True,
            host=settings.host,
            port=settings.port,
            reload=reload,
            reload_dirs=[str(_REPO_ROOT / "backend" / "src")] if reload else None,
            log_level="info",
        )
    finally:
        frontend_proc.terminate()
        try:
            frontend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend_proc.kill()


def cmd_dev(args: argparse.Namespace) -> None:
    from hypomnema.config import Settings

    npm = _find_npm()
    settings = Settings()
    _run(
        settings=settings,
        npm=npm,
        reload=True,
        frontend_cmd=[npm, "run", "dev"],
        open_browser=not args.no_browser,
    )


def cmd_serve(args: argparse.Namespace) -> None:
    from hypomnema.config import Settings

    npm = _find_npm()
    settings = Settings()

    # Build with NEXT_PUBLIC_API_URL so Next.js inlines the correct backend URL
    next_dir = _FRONTEND_DIR / ".next"
    if args.build or not _has_production_frontend_build(next_dir):
        _ensure_frontend()
        _ensure_node_modules(npm)
        if args.build:
            print("Building frontend for production...")
        else:
            print("Production frontend build missing or incomplete; rebuilding...")
        subprocess.run(
            [npm, "run", "build"],
            cwd=_FRONTEND_DIR,
            env=_frontend_env(settings),
            check=True,
        )

    _run(
        settings=settings,
        npm=npm,
        reload=False,
        frontend_cmd=[npm, "run", "start"],
        open_browser=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hypomnema",
        description="Automated Ontological Synthesizer",
    )
    sub = parser.add_subparsers(dest="command")

    dev_p = sub.add_parser("dev", help="Development mode (default)")
    dev_p.add_argument("--no-browser", action="store_true")

    serve_p = sub.add_parser("serve", help="Production mode")
    serve_p.add_argument("--build", action="store_true", help="Force frontend rebuild")

    args = parser.parse_args()
    if args.command is None:
        args.command = "dev"
        args.no_browser = False
    if args.command == "dev":
        cmd_dev(args)
    elif args.command == "serve":
        cmd_serve(args)
