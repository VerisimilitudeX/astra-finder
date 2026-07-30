#!/usr/bin/env python3
"""Build site/projects.json: every public GitHub repo with an astra.yaml at root.

Uses the GitHub code search API (requires a token; in CI the Actions
GITHUB_TOKEN suffices). Code search is capped at 10 requests/minute, so
search pages are throttled. Each candidate repo's astra.yaml is fetched and
validated so that unrelated files that merely share the name are excluded.

Usage:
    GITHUB_TOKEN=... python3 scripts/build_index.py [--out site/projects.json]
"""

import argparse
import datetime
import json
import os
import sys
import time

import requests
import yaml

API = "https://api.github.com"
SEARCH_QUERIES = [
    "filename:astra.yaml path:/",
    # Fallback with a search term in case GitHub rejects qualifier-only queries.
    "outputs filename:astra.yaml path:/",
]
SEARCH_THROTTLE_S = 7  # code search: 10 req/min


def session_with_token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("error: GITHUB_TOKEN is required (code search rejects unauthenticated requests)")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "astra-finder-indexer",
    })
    return s


def search_repos(s):
    """Return {full_name: default_branch_file_path} for repos with a root astra.yaml."""
    repos = {}
    for query in SEARCH_QUERIES:
        url = f"{API}/search/code"
        params = {"q": query, "per_page": 100}
        page = 1
        while url:
            r = s.get(url, params=params)
            if r.status_code == 422:
                print(f"  query rejected (422): {query!r} — trying next", file=sys.stderr)
                break
            if r.status_code == 403 and "rate limit" in r.text.lower():
                print("  search rate limited; sleeping 60s", file=sys.stderr)
                time.sleep(60)
                continue
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                # path:/ can still return nested matches on some queries; enforce root.
                if item.get("path") == "astra.yaml":
                    repos[item["repository"]["full_name"]] = item["repository"]
            nxt = r.links.get("next", {}).get("url")
            url, params = nxt, None
            page += 1
            if url:
                time.sleep(SEARCH_THROTTLE_S)
        if repos:
            break  # primary query worked; no need for the fallback
    return repos


def is_astra_spec(text):
    """A root astra.yaml counts as ASTRA if it parses to a mapping with a
    name and at least one structural ASTRA key."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict) or "name" not in doc:
        return None
    if not any(k in doc for k in ("outputs", "decisions", "version", "inputs")):
        return None
    return doc


def enrich(s, full_name):
    r = s.get(f"{API}/repos/{full_name}")
    if r.status_code != 200:
        print(f"  skip {full_name}: repo fetch {r.status_code}", file=sys.stderr)
        return None
    repo = r.json()
    branch = repo.get("default_branch", "main")
    raw = s.get(
        f"https://raw.githubusercontent.com/{full_name}/{branch}/astra.yaml",
        headers={"Accept": "text/plain"},
    )
    if raw.status_code != 200:
        print(f"  skip {full_name}: astra.yaml fetch {raw.status_code}", file=sys.stderr)
        return None
    doc = is_astra_spec(raw.text)
    if doc is None:
        print(f"  skip {full_name}: astra.yaml is not an ASTRA spec", file=sys.stderr)
        return None
    description = (doc.get("description") or repo.get("description") or "").strip()
    description = " ".join(description.split())
    if len(description) > 200:
        description = description[:197].rstrip() + "..."
    return {
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "description": description,
        "stars": repo.get("stargazers_count", 0),
        "pushed_at": repo.get("pushed_at"),
        "astra_name": str(doc.get("name", "")).strip() or None,
        "outputs": len(doc.get("outputs") or []),
        "decisions": len(doc.get("decisions") or []),
        "inputs": len(doc.get("inputs") or []),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="site/projects.json")
    args = parser.parse_args()

    s = session_with_token()

    print("searching for root astra.yaml files...", file=sys.stderr)
    repos = search_repos(s)
    # Code search never indexes forks, so the repo hosting this index (a fork)
    # would be invisible to itself. Always include it as a candidate; it still
    # goes through the same astra.yaml validation as everything else.
    self_repo = os.environ.get("GITHUB_REPOSITORY")
    if self_repo:
        repos.setdefault(self_repo, {"full_name": self_repo})
    print(f"found {len(repos)} candidate repos", file=sys.stderr)

    projects = []
    for full_name in sorted(repos):
        p = enrich(s, full_name)
        if p:
            projects.append(p)
            print(f"  + {full_name} ({p['stars']}★)", file=sys.stderr)

    if not projects:
        sys.exit("error: no valid projects found — refusing to overwrite the index")

    projects.sort(key=lambda p: (-p["stars"], p["full_name"].lower()))
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "count": len(projects),
        "projects": projects,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"wrote {args.out} with {len(projects)} projects", file=sys.stderr)


if __name__ == "__main__":
    main()
