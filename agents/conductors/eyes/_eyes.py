"""
agents/conductors/eyes/_eyes.py — the Eyes Agent core (the perceptive
function: the organism's sense of its own appearance).

Consumes a **visualization workspace**: any repo implementing the gallery
contract — `scripts/<domain>/images/<script>/**` figure trees written by the
domain's visualization scripts, plus `output/gallery/` (gallery.html +
viz_manifest.yaml) from the workspace's own gallery builder. The workspace
root is always a CLI argument: this file names no repositories (tenant
firewall — an adopting fork points it at its own workspace).

Modes:
  survey <root>   inventory + render staleness + gallery currency + gaps
                  -> EyesSurvey
  review <root>   ordered figure batches + the critique-note schema the
                  agentic review loop consumes -> EyesReviewSurface
                  --against <dir>: paper-informed pass — the directory's
                  figures (a paper's extracted panels) ride along as
                  reference context; notes may then carry a `reference`

Instances by name: `--instance <name>` (repeatable) resolves a checkout
through the PyAutoEyes organ's `registry.yaml` — the registry is data, so
this file still names no instance. Handing either mode the organ root
itself (a directory holding `registry.yaml`) covers every registered
instance. A registered instance with no local checkout is skipped with a
note, never guessed at.

Decision-only, stdlib-only: reads the filesystem, writes nothing, renders
nothing (rendering is the workspace's `gallery/gallery_run.sh`), and
never edits plot source — accepted critiques route to intake/start_dev.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BRAIN_HOME / "agents"))
import _pyauto_root  # noqa: E402
from _repo_paths import repo_path  # noqa: E402

# The organ that holds the instance registry — an organ name, not an
# instance fact (the same footing as the Cortex conductor's CORTEX_REPO).
EYES_REPO = "PyAutoEyes"
REGISTRY_FILE = "registry.yaml"

# Exit codes: 0 decision emitted · 2 unknown instance / unreadable registry
# · 4 not a visualization workspace (or no registered instance is local).
RC_OK, RC_REGISTRY, RC_NOT_WORKSPACE = 0, 2, 4

# Any script whose stem contains this token is treated as a figure producer;
# its images land in scripts/<domain>/images/<stem>/.
PRODUCER_TOKEN = "visualization"

# Where an accepted critique is edited, and which dev route ships it. The
# review loop tags every note with one of these surfaces.
EDIT_SURFACES = {
    "config": "workspace config/visualize yaml (plot defaults, include flags)",
    "plot_api": "library plot functions (the functional aplt.* API) — library PR",
    "script": "the producing visualization script itself — workspace PR",
    "data": "dataset / simulator inputs — workspace PR",
}


def _domains(root: Path):
    scripts = root / "scripts"
    if not scripts.is_dir():
        return []
    return sorted(p for p in scripts.iterdir() if p.is_dir())


def scan(root: Path) -> dict:
    """One record per producer script and per images tree, joined by stem."""
    records = []
    for domain_dir in _domains(root):
        images_dir = domain_dir / "images"
        producers = {p.stem: p for p in sorted(domain_dir.glob("*.py"))
                     if PRODUCER_TOKEN in p.stem}
        image_trees = ({p.name: p for p in sorted(images_dir.iterdir()) if p.is_dir()}
                       if images_dir.is_dir() else {})
        for stem in sorted(set(producers) | set(image_trees)):
            script = producers.get(stem)
            tree = image_trees.get(stem)
            pngs = sorted(tree.rglob("*.png")) if tree else []
            fits = sorted(tree.rglob("*.fits")) if tree else []
            newest_png = max((f.stat().st_mtime for f in pngs), default=None)
            records.append({
                "domain": domain_dir.name,
                "script": stem,
                "script_exists": script is not None,
                "rendered": bool(pngs),
                "n_png": len(pngs),
                "n_fits": len(fits),
                "figures": [str(f.relative_to(root)) for f in pngs],
                # stale render: the producer changed after its newest figure
                "stale": (script is not None and newest_png is not None
                          and script.stat().st_mtime > newest_png),
                "newest_png_mtime": newest_png,
            })
    return {"records": records}


def gallery_status(root: Path, records, tracked_manifest: str | None = None) -> dict:
    gallery = root / "output" / "gallery"
    html = gallery / "gallery.html"
    manifest = gallery / "viz_manifest.yaml"
    newest = max((r["newest_png_mtime"] for r in records
                  if r["newest_png_mtime"] is not None), default=None)
    built = html.is_file()
    status = {
        "built": built,
        "manifest": manifest.is_file(),
        "stale": (built and newest is not None
                  and newest > html.stat().st_mtime),
        "path": str(gallery.relative_to(root)),
    }
    if tracked_manifest is not None:
        # The registry row names the manifest the project repo commits (the
        # organ's read contract); the local output/gallery build is optional.
        status["tracked_manifest"] = {
            "path": tracked_manifest,
            "present": (root / tracked_manifest).is_file(),
        }
    return status


def survey(root: Path, tracked_manifest: str | None = None) -> dict:
    records = scan(root)["records"]
    return {
        "kind": "EyesSurvey",
        "workspace": str(root),
        "domains": sorted({r["domain"] for r in records}),
        "records": records,
        "gaps": [f"{r['domain']}/{r['script']}" for r in records
                 if r["script_exists"] and not r["rendered"]],
        "orphans": [f"{r['domain']}/{r['script']}" for r in records
                    if not r["script_exists"]],
        "stale_renders": [f"{r['domain']}/{r['script']}" for r in records
                          if r["stale"]],
        "gallery": gallery_status(root, records, tracked_manifest),
        "next_action": ("run the workspace's gallery/gallery_run.sh "
                        "for stale/missing renders, then `eyes review`"),
    }


# -------------------------------------------------------------- registry ---
class RegistryError(Exception):
    """The organ registry is missing, unreadable, or lacks a named instance."""


def eyes_root(explicit: str | None = None) -> Path:
    """Where the PyAutoEyes organ is: `explicit` → `$PYAUTO_EYES` → beside
    this Brain checkout → `repo_path($PYAUTO_ROOT, PyAutoEyes)`."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("PYAUTO_EYES")
    if env:
        return Path(env).expanduser().resolve()
    sibling = BRAIN_HOME.parent / EYES_REPO
    if (sibling / REGISTRY_FILE).is_file():
        return sibling.resolve()
    return repo_path(_pyauto_root.pyauto_root(), EYES_REPO).resolve()


_ROW = re.compile(r"^  - (\w+):\s*(.*?)\s*$")
_FIELD = re.compile(r"^    (\w+):\s*(.*?)\s*$")


def _scalar(raw: str) -> str:
    raw = raw.split(" #", 1)[0].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def read_registry(organ: Path) -> list[dict]:
    """The `instances:` rows of the organ's registry.yaml, stdlib-only.

    The registry is a flat list of string mappings (validated by the organ's
    own `pyauto-eyes check`); this reads exactly that shape and nothing
    more, so the conductor needs no YAML dependency.
    """
    path = organ / REGISTRY_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"cannot read the instance registry {path}: {exc}") from exc
    rows, active = [], False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.rstrip() == "instances:":
            active = True
            continue
        if not active:
            continue
        if not line.startswith(" "):
            break
        m = _ROW.match(line)
        if m:
            rows.append({m[1]: _scalar(m[2])})
            continue
        m = _FIELD.match(line)
        if m and rows:
            rows[-1][m[1]] = _scalar(m[2])
    rows = [r for r in rows if r.get("name")]
    if not rows:
        raise RegistryError(f"no instances in {path}")
    return rows


def is_organ_root(path: Path) -> bool:
    """A directory holding the instance registry and no figure tree of its own."""
    return (path / REGISTRY_FILE).is_file() and not (path / "scripts").is_dir()


def instance_checkout(row: dict, organ: Path) -> Path | None:
    """A registered instance's local checkout: grouped `<root>/<path>`, then
    flat `<root>/<repo>`, for the workspace root and the roots the organ
    itself sits under. None when it is not on this machine."""
    roots = [_pyauto_root.pyauto_root(), organ.parent.parent, organ.parent]
    seen = []
    for base in roots:
        if base in seen:
            continue
        seen.append(base)
        for rel in (row.get("path"), row.get("repo")):
            if rel and (base / rel / "scripts").is_dir():
                return (base / rel).resolve()
    return None


def select_instances(organ: Path, names: list[str] | None) -> list[dict]:
    rows = read_registry(organ)
    if not names:
        return rows
    known = {r["name"]: r for r in rows}
    missing = [n for n in names if n not in known]
    if missing:
        raise RegistryError(
            f"no instance {', '.join(map(repr, missing))} in {organ / REGISTRY_FILE} "
            f"(known: {', '.join(known)})")
    return [known[n] for n in names]


REFERENCE_SUFFIXES = (".png", ".jpg", ".jpeg")


def review(root: Path, batch: int, against: Path | None = None) -> dict:
    records = scan(root)["records"]
    figures = [f for r in records for f in r["figures"]]
    batches = [figures[i:i + batch] for i in range(0, len(figures), batch)]
    surface = {
        "kind": "EyesReviewSurface",
        "workspace": str(root),
        "n_figures": len(figures),
        "batch_size": batch,
        "batches": batches,
        "note_schema": {
            "figure": "workspace-relative figure path",
            "observation": "what looks wrong / could improve (human or agent)",
            "proposal": "the concrete change",
            "surface": f"one of {sorted(EDIT_SURFACES)}",
            "reference": ("reference figure that motivated the note "
                          "(paper-informed passes only; optional)"),
            "accepted": "true only after explicit human agreement",
        },
        "edit_surfaces": EDIT_SURFACES,
        "next_action": ("review each batch (read the figures directly), "
                        "collect notes against note_schema, then file one "
                        "intake prompt per coherent accepted change — never "
                        "edit plot source in-session"),
    }
    if against is not None:
        surface["reference_figures"] = [
            str(f) for f in sorted(against.rglob("*"))
            if f.suffix.lower() in REFERENCE_SUFFIXES
        ]
        surface["next_action"] = (
            "read the reference figures FIRST and write an explicit "
            "convention list (colormaps, panel composition, annotations, "
            "colorbars, fonts, scale bars), then " + surface["next_action"]
        )
    return surface


def _print_survey(s: dict):
    print("== EyesSurvey ==")
    if s.get("instance"):
        print(f"Instance:       {s['instance']}")
    print(f"Workspace:      {s['workspace']}")
    print(f"Domains:        {', '.join(s['domains']) or '(none)'}")
    for r in s["records"]:
        flags = []
        if r["stale"]:
            flags.append("STALE")
        if not r["rendered"]:
            flags.append("NEVER-RENDERED" if r["script_exists"] else "ORPHAN-IMAGES")
        print(f"  {r['domain']}/{r['script']}: {r['n_png']} png, "
              f"{r['n_fits']} fits{'  [' + ', '.join(flags) + ']' if flags else ''}")
    g = s["gallery"]
    state = "not built" if not g["built"] else ("STALE" if g["stale"] else "current")
    print(f"Gallery:        {g['path']} — {state}"
          f"{' (manifest missing)' if g['built'] and not g['manifest'] else ''}")
    tracked = g.get("tracked_manifest")
    if tracked:
        print(f"Tracked manifest: {tracked['path']} — "
              f"{'present' if tracked['present'] else 'MISSING'}")
    print(f"Next action:    {s['next_action']}")


def _print_review(r: dict):
    print("== EyesReviewSurface ==")
    if r.get("instance"):
        print(f"Instance:       {r['instance']}")
    print(f"Workspace:      {r['workspace']}")
    print(f"Figures:        {r['n_figures']} in {len(r['batches'])} "
          f"batch(es) of <= {r['batch_size']}")
    if "reference_figures" in r:
        print(f"References:     {len(r['reference_figures'])} figure(s) "
              f"(paper-informed pass)")
    for i, b in enumerate(r["batches"], start=1):
        print(f"  batch {i}: {b[0]} .. {b[-1]}  ({len(b)} figures)")
    print("Edit surfaces:")
    for k, v in r["edit_surfaces"].items():
        print(f"  {k:<9} {v}")
    print(f"Next action:    {r['next_action']}")


def _targets(args):
    """[(instance name or None, checkout, tracked manifest or None)] plus the
    skipped instances [(name, reason)]. Raises RegistryError."""
    names = args.instance or []
    if args.workspace is None and not names:
        raise SystemExit("eyes: give a workspace root, the PyAutoEyes organ "
                         "root, or --instance <name>")
    if args.workspace is not None and not names:
        root = Path(args.workspace).resolve()
        if not is_organ_root(root):
            return [(None, root, None)], []
        organ = root
    elif args.workspace is not None:
        organ = Path(args.workspace).resolve()
        if not is_organ_root(organ):
            raise SystemExit("eyes: --instance with a positional root needs "
                             "the PyAutoEyes organ root there")
    else:
        organ = eyes_root()
    targets, skipped = [], []
    for row in select_instances(organ, names):
        checkout = instance_checkout(row, organ)
        if checkout is None:
            skipped.append((row["name"], f"no local checkout at {row.get('path') or row.get('repo')}"))
        else:
            targets.append((row["name"], checkout, row.get("manifest")))
    return targets, skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eyes")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("survey", "review"):
        p = sub.add_parser(mode)
        p.add_argument("workspace", nargs="?", default=None,
                       help="visualization-workspace root, or the PyAutoEyes "
                            "organ root (every registered instance)")
        p.add_argument("--instance", action="append", metavar="NAME",
                       help="a registered instance, resolved through the "
                            "PyAutoEyes registry.yaml (repeatable)")
        if mode == "review":
            p.add_argument("--batch", type=int, default=8)
            p.add_argument("--against", default=None,
                           help="reference-figure directory (paper-informed pass)")
    args = parser.parse_args(argv)

    try:
        targets, skipped = _targets(args)
    except RegistryError as exc:
        print(f"eyes: {exc}", file=sys.stderr)
        return RC_REGISTRY
    for name, reason in skipped:
        print(f"eyes: instance {name}: {reason} — skipped", file=sys.stderr)

    against = None
    if args.mode == "review" and args.against is not None:
        against = Path(args.against).resolve()
        if not (against.is_dir() and any(
                f.suffix.lower() in REFERENCE_SUFFIXES
                for f in against.rglob("*"))):
            print(f"eyes: no reference figures (png/jpg) under: {against}",
                  file=sys.stderr)
            return RC_NOT_WORKSPACE

    decisions = []
    for name, root, tracked in targets:
        if not (root / "scripts").is_dir():
            print(f"eyes: not a visualization workspace (no scripts/): {root}",
                  file=sys.stderr)
            if name is None:
                return RC_NOT_WORKSPACE
            skipped.append((name, f"not a visualization workspace: {root}"))
            continue
        decision = (survey(root, tracked) if args.mode == "survey"
                    else review(root, args.batch, against))
        if name is not None:
            decision = {"instance": name, **decision}
        decisions.append(decision)
    if not decisions:
        print("eyes: no registered instance has a local checkout here",
              file=sys.stderr)
        return RC_NOT_WORKSPACE

    registry_run = targets and targets[0][0] is not None
    if args.json:
        if registry_run and (len(decisions) > 1 or skipped):
            print(json.dumps({
                "kind": "EyesInstanceSet",
                "mode": args.mode,
                "decisions": decisions,
                "skipped": [{"instance": n, "reason": r} for n, r in skipped],
            }, indent=2))
        else:
            print(json.dumps(decisions[0], indent=2))
    else:
        for i, decision in enumerate(decisions):
            if i:
                print()
            (_print_survey if args.mode == "survey" else _print_review)(decision)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
