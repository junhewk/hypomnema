#!/usr/bin/env python3
"""Upload desktop build artifacts to a Gitea release."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx


def find_or_create_release(
    client: httpx.Client,
    base_url: str,
    repo: str,
    version: str,
) -> int:
    """Find existing release by tag or create a new one. Returns release ID."""
    # Check if release exists
    resp = client.get(f"{base_url}/api/v1/repos/{repo}/releases/tags/{version}")
    if resp.status_code == 200:
        release_id = resp.json()["id"]
        print(f"  Found existing release {version} (id={release_id})")
        return release_id

    # Create new release
    resp = client.post(
        f"{base_url}/api/v1/repos/{repo}/releases",
        json={
            "tag_name": version,
            "name": f"Hypomnema {version}",
            "body": f"Desktop release {version}",
            "draft": False,
            "prerelease": False,
        },
    )
    resp.raise_for_status()
    release_id = resp.json()["id"]
    print(f"  Created release {version} (id={release_id})")
    return release_id


def upload_asset(
    client: httpx.Client,
    base_url: str,
    repo: str,
    release_id: int,
    artifact: Path,
) -> None:
    """Upload a file as a release asset."""
    print(f"  Uploading {artifact.name} ({artifact.stat().st_size / 1024 / 1024:.1f} MB)...")
    with artifact.open("rb") as f:
        resp = client.post(
            f"{base_url}/api/v1/repos/{repo}/releases/{release_id}/assets",
            params={"name": artifact.name},
            content=f,
            headers={"Content-Type": "application/octet-stream"},
        )
    resp.raise_for_status()
    print(f"  Uploaded {artifact.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Hypomnema release to Gitea")
    parser.add_argument("--version", required=True, help="Release version tag (e.g. v0.1.0)")
    parser.add_argument("--artifact", required=True, action="append", dest="artifacts",
                        help="Path to artifact file (can be specified multiple times)")
    parser.add_argument("--gitea-url", required=True, help="Gitea server URL (e.g. http://host:3000)")
    parser.add_argument("--repo", required=True, help="Repository path (e.g. jk/hypomnema)")
    args = parser.parse_args()

    token = os.environ.get("GITEA_TOKEN")
    if not token:
        print("ERROR: GITEA_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Validate artifacts exist
    artifact_paths: list[Path] = []
    for a in args.artifacts:
        p = Path(a)
        if not p.exists():
            print(f"ERROR: Artifact not found: {p}", file=sys.stderr)
            sys.exit(1)
        artifact_paths.append(p)

    base_url = args.gitea_url.rstrip("/")

    with httpx.Client(
        headers={"Authorization": f"token {token}"},
        timeout=300.0,
    ) as client:
        release_id = find_or_create_release(client, base_url, args.repo, args.version)

        for artifact in artifact_paths:
            upload_asset(client, base_url, args.repo, release_id, artifact)

    print("\nDone!")


if __name__ == "__main__":
    main()
