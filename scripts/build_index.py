#!/usr/bin/env python3
"""Build site/projects.json: every public GitHub repo with an astra.yaml at root.

Discovery channels (each independently fault-tolerant — one failing channel
never sinks the run):
  1. Code search:   filename:astra.yaml path:/          (10 req/min, throttled)
  2. Topic search:  topic:astra, topic:astra-analysis, topic:lightcone-cli
  3. Self repo:     $GITHUB_REPOSITORY (forks are invisible to code search)
  4. Seed list:     scripts/seeds.txt  (search-index lag escape hatch)

Every candidate's astra.yaml is fetched and validated before listing. The
index records outputs, findings (label + claim), and input datasets (for the
lineage view), and writes one verification badge SVG per listed repo under
site/badges/.

Usage:
    GITHUB_TOKEN=... python3 scripts/build_index.py [--out site/projects.json]
"""

import argparse
import datetime
import json
import os
import sys
import time
import traceback

import requests
import yaml

API = "https://api.github.com"
SEARCH_QUERIES = [
    "filename:astra.yaml path:/",
    # Fallback with a search term in case GitHub rejects qualifier-only queries.
    "outputs filename:astra.yaml path:/",
]
TOPIC_QUERIES = ["topic:astra", "topic:astra-analysis", "topic:lightcone-cli"]
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


def get_with_retry(s, url, params=None, attempts=3):
    """GET with backoff on transient failures; returns Response or None."""
    for attempt in range(attempts):
        try:
            r = s.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  request error ({e}); retrying", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (403, 429) and attempt < attempts - 1:
            wait = int(r.headers.get("Retry-After", 0)) or 30 * (attempt + 1)
            print(f"  {r.status_code} from {url}; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code >= 500 and attempt < attempts - 1:
            time.sleep(10 * (attempt + 1))
            continue
        return r
    return None


def search_code(s):
    repos = {}
    for query in SEARCH_QUERIES:
        url, params = f"{API}/search/code", {"q": query, "per_page": 100}
        while url:
            r = get_with_retry(s, url, params)
            if r is None or r.status_code == 422:
                print(f"  code query {query!r} unavailable", file=sys.stderr)
                break
            if r.status_code != 200:
                print(f"  code query {query!r} failed ({r.status_code})", file=sys.stderr)
                break
            for item in r.json().get("items", []):
                if item.get("path") == "astra.yaml":
                    repos[item["repository"]["full_name"]] = item["repository"]
            url, params = r.links.get("next", {}).get("url"), None
            if url:
                time.sleep(SEARCH_THROTTLE_S)
        if repos:
            break
    return repos


def search_topics(s):
    repos = {}
    for query in TOPIC_QUERIES:
        r = get_with_retry(s, f"{API}/search/repositories", {"q": query, "per_page": 100})
        if r is None or r.status_code != 200:
            print(f"  topic query {query!r} failed", file=sys.stderr)
            continue
        for item in r.json().get("items", []):
            repos[item["full_name"]] = item
        time.sleep(2)  # repo search: 30 req/min
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


def condense(text, limit):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def extract_findings(doc):
    """findings: may be a mapping id -> entry or a list of entries."""
    raw = doc.get("findings")
    entries = []
    if isinstance(raw, dict):
        entries = [v for v in raw.values() if isinstance(v, dict)]
    elif isinstance(raw, list):
        entries = [v for v in raw if isinstance(v, dict)]
    out = []
    for e in entries[:6]:
        label = condense(e.get("label") or e.get("id") or "", 160)
        claim = condense(e.get("claim") or e.get("statement") or "", 320)
        if label or claim:
            out.append({"label": label, "claim": claim})
    return out


def extract_inputs(doc):
    out = []
    for i in doc.get("inputs") or []:
        if not isinstance(i, dict):
            continue
        source = str(i.get("source") or "")
        dataset = source.rstrip("/").split("/")[-1] if source else ""
        out.append({
            "label": condense(i.get("label") or i.get("id") or "", 120),
            "dataset": dataset,
        })
    return out[:8]


BADGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="118" height="20" role="img" aria-label="astra: verified">
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#fff" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <clipPath id="r"><rect width="118" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="47" height="20" fill="#40434a"/>
    <rect x="47" width="71" height="20" fill="#23479f"/>
    <rect width="118" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="24" y="14">astra</text>
    <text x="82" y="14">verified</text>
  </g>
</svg>
"""


def write_badge(badge_dir, full_name):
    os.makedirs(badge_dir, exist_ok=True)
    path = os.path.join(badge_dir, full_name.replace("/", "--") + ".svg")
    with open(path, "w") as f:
        f.write(BADGE_SVG)


def enrich(s, full_name):
    r = get_with_retry(s, f"{API}/repos/{full_name}")
    if r is None or r.status_code != 200:
        print(f"  skip {full_name}: repo fetch failed", file=sys.stderr)
        return None
    repo = r.json()
    branch = repo.get("default_branch", "main")
    raw = get_with_retry(
        s, f"https://raw.githubusercontent.com/{full_name}/{branch}/astra.yaml"
    )
    if raw is None or raw.status_code != 200:
        print(f"  skip {full_name}: astra.yaml fetch failed", file=sys.stderr)
        return None
    doc = is_astra_spec(raw.text)
    if doc is None:
        print(f"  skip {full_name}: astra.yaml is not an ASTRA spec", file=sys.stderr)
        return None
    outputs_list = [
        {"label": condense(o.get("label") or o.get("id") or "", 120), "type": str(o.get("type") or "")}
        for o in (doc.get("outputs") or [])
        if isinstance(o, dict)
    ][:16]
    return {
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "description": condense(doc.get("description") or repo.get("description") or "", 480),
        "stars": repo.get("stargazers_count", 0),
        "pushed_at": repo.get("pushed_at"),
        "topics": (repo.get("topics") or [])[:6],
        "astra_tags": [str(t) for t in (doc.get("tags") or []) if isinstance(t, (str, int))][:6],
        "astra_name": str(doc.get("name", "")).strip() or None,
        "outputs_list": outputs_list,
        "outputs": len(doc.get("outputs") or []),
        "inputs_list": extract_inputs(doc),
        "findings_list": extract_findings(doc),
        "inputs": len(doc.get("inputs") or []),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="site/projects.json")
    args = parser.parse_args()

    s = session_with_token()
    repos = {}

    for name, channel in (("code search", search_code), ("topic search", search_topics)):
        print(f"discovering via {name}...", file=sys.stderr)
        try:
            found = channel(s)
            print(f"  {name}: {len(found)} repos", file=sys.stderr)
            for full_name, repo in found.items():
                repos.setdefault(full_name, repo)
        except Exception:
            print(f"  {name} crashed:", file=sys.stderr)
            traceback.print_exc()

    # Code search never indexes forks, so the repo hosting this index (a fork)
    # would be invisible to itself.
    self_repo = os.environ.get("GITHUB_REPOSITORY")
    if self_repo:
        repos.setdefault(self_repo, {"full_name": self_repo})
    seeds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.txt")
    if os.path.exists(seeds_path):
        with open(seeds_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    repos.setdefault(line, {"full_name": line})

    print(f"{len(repos)} candidate repos total", file=sys.stderr)

    badge_dir = os.path.join(os.path.dirname(os.path.abspath(args.out)), "badges")
    projects = []
    for full_name in sorted(repos):
        try:
            p = enrich(s, full_name)
        except Exception:
            print(f"  {full_name} crashed during enrich:", file=sys.stderr)
            traceback.print_exc()
            continue
        if p:
            projects.append(p)
            write_badge(badge_dir, p["full_name"])
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
