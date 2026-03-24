#!/usr/bin/env python3
"""Upload desktop build artifacts to a GitHub release."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx


def find_or_create_release(
    client: httpx.Client,
    repo: str,
    version: str,
) -> int:
    """Find existing release by tag or create a new draft. Returns release ID."""
    resp = client.get(f"https://api.github.com/repos/{repo}/releases/tags/{version}")
    if resp.status_code == 200:
        release_id = resp.json()["id"]
        print(f"  Found existing release {version} (id={release_id})")
        return release_id

    resp = client.post(
        f"https://api.github.com/repos/{repo}/releases",
        json={
            "tag_name": version,
            "name": f"Hypomnema {version}",
            "body": f"Desktop release {version}",
            "draft": True,
            "prerelease": False,
        },
    )
    resp.raise_for_status()
    release_id = resp.json()["id"]
    print(f"  Created draft release {version} (id={release_id})")
    return release_id


def upload_asset(
    client: httpx.Client,
    repo: str,
    release_id: int,
    artifact: Path,
) -> None:
    """Upload a file as a release asset."""
    size_mb = artifact.stat().st_size / 1024 / 1024
    print(f"  Uploading {artifact.name} ({size_mb:.1f} MB)...")
    with artifact.open("rb") as f:
        resp = client.post(
            f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets",
            params={"name": artifact.name},
            content=f,
            headers={"Content-Type": "application/octet-stream"},
        )
    resp.raise_for_status()
    print(f"  Uploaded {artifact.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Hypomnema release to GitHub")
    parser.add_argument("--version", required=True, help="Release version tag (e.g. v0.1.0)")
    parser.add_argument("--artifact", required=True, action="append", dest="artifacts",
                        help="Path to artifact file (can be specified multiple times)")
    parser.add_argument("--repo", required=True, help="GitHub repository (e.g. owner/hypomnema)")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    artifact_paths: list[Path] = []
    for a in args.artifacts:
        p = Path(a)
        if not p.exists():
            print(f"ERROR: Artifact not found: {p}", file=sys.stderr)
            sys.exit(1)
        artifact_paths.append(p)

    with httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=300.0,
    ) as client:
        release_id = find_or_create_release(client, args.repo, args.version)

        for artifact in artifact_paths:
            upload_asset(client, args.repo, release_id, artifact)

    print("\nDone!")


if __name__ == "__main__":
    main()
