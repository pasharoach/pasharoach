#!/usr/bin/env python3
"""Aggregate total GitHub release downloads across all owned repos and update a gist JSON for shields.io endpoint."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Tuple

API_BASE = "https://api.github.com"


def github_request(url: str, token: str) -> Tuple[object, Dict[str, str]]:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        headers = {k: v for k, v in resp.headers.items()}
        return json.loads(body), headers


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' not in part:
            continue
        left = part.split(";")[0].strip()
        if left.startswith("<") and left.endswith(">"):
            return left[1:-1]
    return None


def paginated_get(url: str, token: str) -> Iterable[object]:
    next_url = url
    while next_url:
        payload, headers = github_request(next_url, token)
        if isinstance(payload, list):
            for item in payload:
                yield item
        else:
            yield payload
        next_url = parse_next_link(headers.get("Link"))


def humanize(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k".rstrip("0").rstrip(".") + "k"
    return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".") + "M"


def total_release_downloads(username: str, token: str) -> int:
    repos_url = f"{API_BASE}/users/{urllib.parse.quote(username)}/repos?type=owner&per_page=100"
    total = 0

    for repo in paginated_get(repos_url, token):
        if not isinstance(repo, dict):
            continue

        repo_name = repo.get("name")
        if not repo_name:
            continue

        releases_url = (
            f"{API_BASE}/repos/{urllib.parse.quote(username)}/{urllib.parse.quote(repo_name)}/releases?per_page=100"
        )

        for release in paginated_get(releases_url, token):
            if not isinstance(release, dict):
                continue
            assets = release.get("assets", [])
            if not isinstance(assets, list):
                continue
            for asset in assets:
                if isinstance(asset, dict):
                    total += int(asset.get("download_count", 0) or 0)

    return total


def update_gist(gist_id: str, filename: str, content: str, token: str) -> None:
    url = f"{API_BASE}/gists/{urllib.parse.quote(gist_id)}"
    payload = {"files": {filename: {"content": content}}}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="PATCH")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"Unexpected status updating gist: {resp.status}")
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gist update failed: HTTP {e.code} {details}") from e


def main() -> int:
    username = os.getenv("GH_USERNAME", "").strip()
    gist_id = os.getenv("GIST_ID", "").strip()
    gist_filename = os.getenv("GIST_FILENAME", "downloads-total.json").strip() or "downloads-total.json"

    read_token = os.getenv("GH_READ_TOKEN", "").strip()
    write_token = os.getenv("GH_PAT", "").strip()

    if not username:
        print("Missing GH_USERNAME", file=sys.stderr)
        return 1
    if not gist_id:
        print("Missing GIST_ID", file=sys.stderr)
        return 1
    if not read_token:
        print("Missing GH_READ_TOKEN", file=sys.stderr)
        return 1
    if not write_token:
        print("Missing GH_PAT", file=sys.stderr)
        return 1

    total = total_release_downloads(username, read_token)

    badge = {
        "schemaVersion": 1,
        "label": "total downloads",
        "message": humanize(total),
        "color": "f3b3c5",
    }

    update_gist(gist_id, gist_filename, json.dumps(badge, ensure_ascii=True), write_token)

    print(f"Updated total downloads badge: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
