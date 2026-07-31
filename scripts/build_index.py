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
    "sources", "universes", "multiverses",
}
MAX_OUTPUT_FILES_PER_REPO = 24
SCRIPT_EXT_RE = re.compile(r"^[\w./-]+\.(py|r|R|sh|jl|ipynb)$")
PLACEHOLDER_RE = re.compile(r"\{(inputs|decisions)\.([A-Za-z0-9_]+)\}")

# Cross-repo reference grammar (astra-spec issues #52/#55 drafts):
#   [source_id:]artifact_or_regex[#universe_or_multiverse]
# and, inside multiverse universe lists, source@commit for a source pinned at
# a historical revision.
INPUT_REF_RE = re.compile(
    r"^(?:(?P<source>[A-Za-z_][A-Za-z0-9_-]*):)?(?P<artifact>[^#\s]+?)(?:#(?P<context>[A-Za-z0-9_.-]+))?$"
)
SOURCE_AT_COMMIT_RE = re.compile(r"^(?P<source>[A-Za-z_][A-Za-z0-9_-]*)@(?P<commit>[0-9a-f]{7,40})$")


def parse_input_ref(text):
    """Parse '[source:]artifact[#context]'; returns a dict or None."""
    m = INPUT_REF_RE.match(str(text or "").strip())
    if not m or not m.group("artifact"):
        return None
    return {
        "source": m.group("source"),
        "artifact": m.group("artifact"),
        "context": m.group("context"),
    }


def parse_sources(doc):
    """The draft 'sources:' registry: external analyses this one draws inputs
    from. Accepts github: owner/repo, uri:/repo_uri: (local or remote), and an
    optional pinned ref:/commit:."""
    out = {}
    raw = doc.get("sources")
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        github = str(entry.get("github") or "").strip().strip("/")
        uri = str(entry.get("repo_uri") or entry.get("uri") or "").strip()
        if not github and "github.com/" in uri:
            github = uri.split("github.com/")[-1].strip("/")
            if github.endswith(".git"):
                github = github[:-4]
        out[str(entry["id"])] = {
            "id": str(entry["id"]),
            "label": condense(entry.get("label") or entry["id"], 120),
            "github": github or None,
            "uri": uri or None,
            "ref": str(entry.get("ref") or entry.get("commit") or "").strip() or None,
        }
    return out


def artifact_matches(pattern, name):
    """A reference artifact may be a plain id or a regex (e.g. '.*_p')."""
    if pattern == name:
        return True
    if any(c in pattern for c in ".*?[]()|+^$"):
        try:
            return re.fullmatch(pattern, name) is not None
        except re.error:
            return False
    return False


def iter_insight_entries(doc):
    for group in ("prior_insights", "findings"):
        raw = doc.get(group)
        entries = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        for e in entries:
            if isinstance(e, dict):
                yield e


def collect_source_refs(doc, sources):
    """Which artifacts (and universe/multiverse contexts) each source is
    consumed through, gathered from input refs and insight evidence."""
    refs = {sid: {"artifacts": set(), "contexts": set()} for sid in sources}

    def add(text):
        ref = parse_input_ref(text)
        if ref and ref["source"] in refs:
            refs[ref["source"]]["artifacts"].add(ref["artifact"])
            if ref["context"]:
                refs[ref["source"]]["contexts"].add(ref["context"])

    for i in doc.get("inputs") or []:
        if isinstance(i, str):
            add(i)
        elif isinstance(i, dict) and str(i.get("source") or "") in refs:
            # Dict form of a source-qualified input: source: + output_id:
            sid = str(i["source"])
            refs[sid]["artifacts"].add(str(i.get("output_id") or i.get("id") or ""))
            if i.get("universe"):
                refs[sid]["contexts"].add(str(i["universe"]))
    for o in doc.get("outputs") or []:
        if isinstance(o, dict):
            for i in o.get("inputs") or []:
                if isinstance(i, str):
                    add(i)
    for e in iter_insight_entries(doc):
        for ev in e.get("evidence") or []:
            if isinstance(ev, dict) and ev.get("artifact"):
                add(str(ev["artifact"]))
    return refs


def snapshot_dirs(doc, sources):
    """Committed snapshot directories of upstream artifacts, declared as
    insight evidence with snapshot: + a source-qualified artifact:. Files under
    these paths are cached copies of another repo's outputs, not this repo's."""
    snaps = []
    for e in iter_insight_entries(doc):
        for ev in e.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            snap = str(ev.get("snapshot") or "").strip().strip("/")
            if not snap:
                continue
            ref = parse_input_ref(str(ev.get("artifact") or ""))
            src = sources.get(ref["source"]) if ref and ref["source"] else None
            snaps.append((snap + "/", src))
    return snaps


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

    sources = parse_sources(doc)
    raw_sources = doc.get("sources")
    if raw_sources is not None and not isinstance(raw_sources, list):
        errors.append("'sources' must be a list")
    for entry in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(entry, dict) or not entry.get("id"):
            errors.append("source entries must be mappings with an 'id'")
        elif not (entry.get("github") or entry.get("uri") or entry.get("repo_uri")):
            errors.append(f"source '{entry['id']}' declares no github/uri/repo_uri")

    outputs = doc.get("outputs") or []
    if not isinstance(outputs, list):
        errors.append("'outputs' must be a list")
        outputs = []
    output_ids = {str(o.get("id")) for o in outputs if isinstance(o, dict) and o.get("id")}

    def check_ref(text, pool):
        """Validate one '[source:]artifact[#context]' reference string."""
        ref = parse_input_ref(text)
        if not ref:
            errors.append(f"input reference '{text}' is not parseable")
            return
        if ref["source"]:
            if ref["source"] not in sources:
                errors.append(f"input '{text}' names undeclared source '{ref['source']}'")
            return  # artifact/context live in the source repo; not checkable here
        if not any(artifact_matches(ref["artifact"], p) for p in pool):
            errors.append(f"input '{text}' matches no declared input or output")

    input_ids = set()
    inputs = doc.get("inputs") or []
    if not isinstance(inputs, list):
        errors.append("'inputs' must be a list")
        inputs = []
    string_input_refs = []
    for i in inputs:
        if isinstance(i, str):
            string_input_refs.append(i)  # checked once output ids are in the pool
            continue
        if not isinstance(i, dict) or not i.get("id"):
            errors.append("input entries must be mappings with an 'id'")
            continue
        input_ids.add(i["id"])
        if i.get("from"):
            continue
        src = str(i.get("source") or "")
        if src in sources:
            continue  # source-registry reference, not a file path
        if not (i.get("source") or i.get("ref")):
            errors.append(f"input '{i['id']}' declares no source/ref")
        if is_checkable_path(src) and tree_paths is not None and src not in tree_paths:
            errors.append(f"input '{i['id']}' file missing from repo: {src}")
    for text in string_input_refs:
        check_ref(text, input_ids | output_ids)

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

    universe_ids = set()
    universes = doc.get("universes")
    if universes is not None and not isinstance(universes, list):
        errors.append("'universes' must be a list")
    for u in universes if isinstance(universes, list) else []:
        if not isinstance(u, dict) or not u.get("id"):
            errors.append("universe entries must be mappings with an 'id'")
            continue
        universe_ids.add(str(u["id"]))
        selections = u.get("decisions")
        for did, opt in (selections.items() if isinstance(selections, dict) else []):
            d = decisions.get(did)
            if not isinstance(d, dict):
                errors.append(f"universe '{u['id']}' selects unknown decision '{did}'")
            elif (
                isinstance(opt, str) and opt != "*"
                and isinstance(d.get("options"), dict)
                and opt not in {str(k) for k in d["options"]}
            ):
                errors.append(f"universe '{u['id']}': '{did}' has no option '{opt}'")

    multiverse_ids = set()
    multiverses = doc.get("multiverses")
    if multiverses is not None and not isinstance(multiverses, list):
        errors.append("'multiverses' must be a list")
    for m in multiverses if isinstance(multiverses, list) else []:
        if not isinstance(m, dict) or not m.get("id"):
            errors.append("multiverse entries must be mappings with an 'id'")
            continue
        multiverse_ids.add(str(m["id"]))
        members = m.get("universes")
        if members is None and not isinstance(m.get("decisions"), dict):
            errors.append(f"multiverse '{m['id']}' declares neither universes nor decisions")
        for member in members if isinstance(members, list) else []:
            member = str(member)
            at = SOURCE_AT_COMMIT_RE.match(member)
            if at:
                if at.group("source") not in sources:
                    errors.append(f"multiverse '{m['id']}' pins undeclared source '{at.group('source')}'")
            elif member != "*" and member not in universe_ids:
                errors.append(f"multiverse '{m['id']}' references unknown universe '{member}'")

    # Outputs may consume earlier outputs as inputs (artifact chaining), so
    # the {inputs.<id>} pool includes both input and output ids.
    referable_inputs = input_ids | output_ids
    for o in outputs:
        if not isinstance(o, dict) or not o.get("id"):
            errors.append("output entries must be mappings with an 'id'")
            continue
        if o.get("from"):
            continue
        for i in o.get("inputs") or [] if isinstance(o.get("inputs"), list) else []:
            if isinstance(i, str) and i not in referable_inputs:
                check_ref(i, referable_inputs)
        location = o.get("location")
        if location is not None:
            path = location.get("path") if isinstance(location, dict) else location
            if not str(path or "").strip():
                errors.append(f"output '{o['id']}' location declares no path")
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


def collect_data_files(doc, blobs, repo, branch, analysis_name, sources):
    """Content-addressed occurrences: declared inputs present in the tree,
    committed snapshots of upstream artifacts (inputs attributed to their
    source repo), and committed files under results/ that belong to a
    declared output."""
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

    # Snapshot copies of another repo's outputs are inputs here, never this
    # repo's outputs — this is what makes one repo's output another's input
    # on the shared content-addressed page.
    snaps = snapshot_dirs(doc, sources)
    snapshot_paths = set()
    for path, (sha, size) in sorted(blobs.items()):
        hit = next((s for s in snaps if path.startswith(s[0])), None)
        if hit is None:
            continue
        snapshot_paths.add(path)
        if len(snapshot_paths) > MAX_OUTPUT_FILES_PER_REPO:
            continue
        src_info = hit[1]
        occ = {
            "hash": sha,
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "size": size,
            "role": "input",
            "ref_id": path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            "repo": repo,
            "branch": branch,
            "analysis": analysis_name,
        }
        if src_info:
            occ["source_repo"] = src_info.get("github") or src_info.get("uri")
            occ["source_label"] = src_info.get("label")
        occurrences.append(occ)

    out_ids = {str(o.get("id")) for o in doc.get("outputs") or [] if isinstance(o, dict) and o.get("id")}
    candidates = []
    for path, (sha, size) in blobs.items():
        if not path.startswith("results/") or path in snapshot_paths:
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
    sources = parse_sources(doc)
    occurrences = collect_data_files(
        doc, blobs or {}, repo["full_name"], branch, astra_name or repo["full_name"], sources
    )
    source_refs = collect_source_refs(doc, sources)
    sources_list = []
    for sid, src in sources.items():
        refs = source_refs.get(sid, {"artifacts": set(), "contexts": set()})
        sources_list.append({
            "id": sid,
            "label": src["label"],
            "github": src["github"],
            "uri": src["uri"],
            "ref": src["ref"],
            "artifacts": sorted(a for a in refs["artifacts"] if a)[:12],
            "contexts": sorted(refs["contexts"])[:6],
        })

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
        "sources_list": sources_list,
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
