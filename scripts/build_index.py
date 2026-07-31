#!/usr/bin/env python3
"""Build the ASTRA Discoverability index.

Outputs:
  site/projects.json   one entry per repo with a root astra.yaml
  site/datasets.json   content-addressed data files (git blob SHA) with every
                       repo that carries them as an input or committed output
  site/badges/*.svg    verification badge for every indexed repo — blue
                       "astra | verified" when validation passes, red
                       "astra | failing" otherwise (same URL either way)

Discovery channels (each independently fault-tolerant): code search, topic
search, the host repo itself, and scripts/seeds.txt.

Two tiers:
  indexed   the file parses as YAML and looks ASTRA-shaped (listed)
  verified  the spec passes schema validation against the ASTRA reference
            (known top-level fields, options as labelled mappings, valid
            defaults, recipe commands present, placeholder references declared)
            AND every declared local input file and recipe script actually
            exists in the repo tree.

Usage:
    GITHUB_TOKEN=... python3 scripts/build_index.py [--out site/projects.json]
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import traceback

import requests
import yaml

API = "https://api.github.com"
SEARCH_QUERIES = [
    "filename:astra.yaml path:/",
    "outputs filename:astra.yaml path:/",  # fallback if qualifier-only is rejected
]
TOPIC_QUERIES = ["topic:astra", "topic:astra-analysis", "topic:lightcone-cli"]
SEARCH_THROTTLE_S = 7  # code search: 10 req/min

ALLOWED_TOP_LEVEL = {
    "id", "version", "name", "description", "tags", "inputs", "outputs",
    "decisions", "prior_insights", "findings", "analyses", "container",
}
MAX_OUTPUT_FILES_PER_REPO = 24
SCRIPT_EXT_RE = re.compile(r"^[\w./-]+\.(py|r|R|sh|jl|ipynb)$")
PLACEHOLDER_RE = re.compile(r"\{(inputs|decisions)\.([A-Za-z0-9_]+)\}")


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
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "n/a"
                print(f"  code query {query!r} failed ({code})", file=sys.stderr)
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
        time.sleep(2)
    return repos


def is_astra_spec(text):
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


def is_checkable_path(source):
    """Local repo path with no URL scheme, template placeholders, or prose."""
    if not source or "://" in source or source.startswith("/"):
        return False
    if "{" in source or "*" in source or " " in source:
        return False
    return True


def validate_spec(doc, tree_paths):
    """Schema + structural validation per the ASTRA reference. Returns a list
    of human-readable failures; empty list means verified."""
    errors = []

    unknown = sorted(set(doc) - ALLOWED_TOP_LEVEL)
    if unknown:
        errors.append("unknown top-level field(s): " + ", ".join(unknown))
    if not str(doc.get("version") or "").strip():
        errors.append("missing top-level 'version'")

    input_ids = set()
    inputs = doc.get("inputs") or []
    if not isinstance(inputs, list):
        errors.append("'inputs' must be a list")
        inputs = []
    for i in inputs:
        if not isinstance(i, dict) or not i.get("id"):
            errors.append("input entries must be mappings with an 'id'")
            continue
        input_ids.add(i["id"])
        if i.get("from"):
            continue
        if not (i.get("source") or i.get("ref")):
            errors.append(f"input '{i['id']}' declares no source/ref")
        src = str(i.get("source") or "")
        if is_checkable_path(src) and tree_paths is not None and src not in tree_paths:
            errors.append(f"input '{i['id']}' file missing from repo: {src}")

    decision_ids = set()
    decisions = doc.get("decisions") or {}
    if decisions and not isinstance(decisions, dict):
        errors.append("'decisions' must be a mapping")
        decisions = {}
    for did, d in decisions.items():
        decision_ids.add(did)
        if not isinstance(d, dict):
            errors.append(f"decision '{did}' must be a mapping")
            continue
        if d.get("from"):
            continue
        opts = d.get("options")
        if not isinstance(opts, dict) or not opts:
            errors.append(f"decision '{did}': options must be a mapping of option-id to {{label: ...}}")
            continue
        for oid, o in opts.items():
            if not isinstance(o, dict) or not o.get("label"):
                errors.append(f"decision '{did}' option '{oid}' missing required 'label'")
                break
        default = d.get("default")
        if default is None:
            errors.append(f"decision '{did}' missing 'default'")
        elif str(default) not in {str(k) for k in opts}:
            errors.append(f"decision '{did}' default '{default}' is not one of its options")

    outputs = doc.get("outputs") or []
    if not isinstance(outputs, list):
        errors.append("'outputs' must be a list")
        outputs = []
    # Outputs may consume earlier outputs as inputs (artifact chaining), so
    # the {inputs.<id>} pool includes both input and output ids.
    output_ids = {str(o.get("id")) for o in outputs if isinstance(o, dict) and o.get("id")}
    referable_inputs = input_ids | output_ids
    for o in outputs:
        if not isinstance(o, dict) or not o.get("id"):
            errors.append("output entries must be mappings with an 'id'")
            continue
        if o.get("from"):
            continue
        recipe = o.get("recipe") or {}
        command = str(recipe.get("command") or "") if isinstance(recipe, dict) else ""
        if not command:
            errors.append(f"output '{o['id']}' has no recipe command")
            continue
        for kind, ref in PLACEHOLDER_RE.findall(command):
            pool = referable_inputs if kind == "inputs" else decision_ids
            if ref not in pool:
                errors.append(f"output '{o['id']}' references undeclared {kind[:-1]} '{ref}'")
        declared = o.get(  # placeholders must also be listed in the output's provenance
            "inputs"
        )
        if isinstance(declared, list):
            for kind, ref in PLACEHOLDER_RE.findall(command):
                if kind == "inputs" and ref not in declared:
                    errors.append(f"output '{o['id']}' uses input '{ref}' not listed in its inputs")
                    break
        if tree_paths is not None:
            for token in command.split():
                if SCRIPT_EXT_RE.match(token) and "{" not in token:
                    if token.startswith("/"):
                        errors.append(f"output '{o['id']}' recipe uses a script outside the repository: {token}")
                    elif token not in tree_paths:
                        errors.append(f"output '{o['id']}' script missing from repo: {token}")
                    break

    return errors[:8]


def extract_findings(doc):
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


def fetch_tree(s, full_name, branch):
    r = get_with_retry(s, f"{API}/repos/{full_name}/git/trees/{branch}", {"recursive": "1"})
    if r is None or r.status_code != 200:
        return None
    data = r.json()
    if data.get("truncated"):
        # An incomplete listing would produce false "file missing" verdicts.
        return None
    blobs = {}
    for node in data.get("tree", []):
        if node.get("type") == "blob":
            blobs[node["path"]] = (node.get("sha"), node.get("size", 0))
    return blobs


def collect_data_files(doc, blobs, repo, branch, analysis_name):
    """Content-addressed occurrences: declared inputs present in the tree,
    plus committed files under results/ that belong to a declared output."""
    occurrences = []
    for i in doc.get("inputs") or []:
        if not isinstance(i, dict):
            continue
        src = str(i.get("source") or "")
        if is_checkable_path(src) and src in blobs:
            sha, size = blobs[src]
            occurrences.append({
                "hash": sha,
                "name": src.rstrip("/").split("/")[-1],
                "path": src,
                "size": size,
                "role": "input",
                "ref_id": i.get("id"),
                "repo": repo,
                "branch": branch,
                "analysis": analysis_name,
            })

    out_ids = {str(o.get("id")) for o in doc.get("outputs") or [] if isinstance(o, dict) and o.get("id")}
    candidates = []
    for path, (sha, size) in blobs.items():
        if not path.startswith("results/"):
            continue
        segments = path.split("/")
        stem = segments[-1].rsplit(".", 1)[0]
        matched = next((oid for oid in out_ids if oid in segments[:-1] or oid == stem), None)
        if matched:
            candidates.append((len(segments), path, sha, size, matched))
    candidates.sort()
    dropped = max(0, len(candidates) - MAX_OUTPUT_FILES_PER_REPO)
    for depth, path, sha, size, oid in candidates[:MAX_OUTPUT_FILES_PER_REPO]:
        occurrences.append({
            "hash": sha,
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "size": size,
            "role": "output",
            "ref_id": oid,
            "repo": repo,
            "branch": branch,
            "analysis": analysis_name,
        })
    if dropped:
        print(f"  {repo}: capped committed output files ({dropped} more not hashed)", file=sys.stderr)
    return occurrences


BADGE_STATUSES = {
    # status -> (right-panel width, right-panel color)
    "verified": (71, "#23479f"),
    "failing": (57, "#c8442d"),
}


def badge_svg(status):
    right_w, color = BADGE_STATUSES[status]
    total = 47 + right_w
    text_x = 47 + right_w // 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="astra: {status}">
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#fff" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="47" height="20" fill="#40434a"/>
    <rect x="47" width="{right_w}" height="20" fill="{color}"/>
    <rect width="{total}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="24" y="14">astra</text>
    <text x="{text_x}" y="14">{status}</text>
  </g>
</svg>
"""


def enrich(s, full_name):
    r = get_with_retry(s, f"{API}/repos/{full_name}")
    if r is None or r.status_code != 200:
        print(f"  skip {full_name}: repo fetch failed", file=sys.stderr)
        return None, []
    repo = r.json()
    branch = repo.get("default_branch", "main")
    raw = get_with_retry(s, f"https://raw.githubusercontent.com/{full_name}/{branch}/astra.yaml")
    if raw is None or raw.status_code != 200:
        print(f"  skip {full_name}: astra.yaml fetch failed", file=sys.stderr)
        return None, []
    doc = is_astra_spec(raw.text)
    if doc is None:
        print(f"  skip {full_name}: astra.yaml is not an ASTRA spec", file=sys.stderr)
        return None, []

    blobs = fetch_tree(s, full_name, branch)
    tree_paths = set(blobs) if blobs is not None else None
    errors = validate_spec(doc, tree_paths)
    if tree_paths is None:
        errors = (errors + ["repo tree unavailable; file checks skipped"])[:8]

    astra_name = str(doc.get("name", "")).strip() or None
    occurrences = collect_data_files(doc, blobs or {}, repo["full_name"], branch, astra_name or repo["full_name"])

    project = {
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "default_branch": branch,
        "description": condense(doc.get("description") or repo.get("description") or "", 480),
        "stars": repo.get("stargazers_count", 0),
        "pushed_at": repo.get("pushed_at"),
        "topics": (repo.get("topics") or [])[:6],
        "astra_tags": [str(t) for t in (doc.get("tags") or []) if isinstance(t, (str, int))][:6],
        "astra_name": astra_name,
        "outputs_list": [
            {"label": condense(o.get("label") or o.get("id") or "", 120), "type": str(o.get("type") or "")}
            for o in (doc.get("outputs") or [])
            if isinstance(o, dict)
        ][:16],
        "outputs": len(doc.get("outputs") or []),
        "inputs": len(doc.get("inputs") or []),
        "findings_list": extract_findings(doc),
        "verified": not errors,
        "verification_errors": errors,
    }
    return project, occurrences


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

    site_dir = os.path.dirname(os.path.abspath(args.out))
    badge_dir = os.path.join(site_dir, "badges")
    os.makedirs(badge_dir, exist_ok=True)

    projects, all_occurrences = [], []
    for full_name in sorted(repos):
        try:
            p, occs = enrich(s, full_name)
        except Exception:
            print(f"  {full_name} crashed during enrich:", file=sys.stderr)
            traceback.print_exc()
            continue
        if p:
            projects.append(p)
            all_occurrences.extend(occs)
            with open(os.path.join(badge_dir, p["full_name"].replace("/", "--") + ".svg"), "w") as f:
                f.write(badge_svg("verified" if p["verified"] else "failing"))
            status = "verified" if p["verified"] else "indexed"
            print(f"  + {full_name} ({status})", file=sys.stderr)

    if not projects:
        sys.exit("error: no valid projects found — refusing to overwrite the index")

    now = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    projects.sort(key=lambda p: (-p["stars"], p["full_name"].lower()))
    with open(args.out, "w") as f:
        json.dump({"generated_at": now, "count": len(projects), "projects": projects}, f, indent=2)
        f.write("\n")

    datasets = {}
    for occ in all_occurrences:
        d = datasets.setdefault(occ["hash"], {"hash": occ["hash"], "names": [], "occurrences": []})
        if occ["name"] not in d["names"]:
            d["names"].append(occ["name"])
        if len(d["occurrences"]) < 40:
            d["occurrences"].append(occ)
    dataset_list = sorted(
        datasets.values(),
        key=lambda d: (-len({o["repo"] for o in d["occurrences"]}), d["names"][0].lower()),
    )
    with open(os.path.join(site_dir, "datasets.json"), "w") as f:
        json.dump({"generated_at": now, "count": len(dataset_list), "datasets": dataset_list}, f, indent=2)
        f.write("\n")

    print(
        f"wrote {args.out} ({len(projects)} projects) and datasets.json ({len(dataset_list)} files)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
