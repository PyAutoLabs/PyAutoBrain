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

Decision-only, stdlib-only: reads the filesystem, writes nothing, renders
nothing (rendering is the workspace's `scripts/gallery/gallery_run.sh`), and
never edits plot source — accepted critiques route to intake/start_dev.
"""

import argparse
import json
import sys
from pathlib import Path

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


def gallery_status(root: Path, records) -> dict:
    gallery = root / "output" / "gallery"
    html = gallery / "gallery.html"
    manifest = gallery / "viz_manifest.yaml"
    newest = max((r["newest_png_mtime"] for r in records
                  if r["newest_png_mtime"] is not None), default=None)
    built = html.is_file()
    return {
        "built": built,
        "manifest": manifest.is_file(),
        "stale": (built and newest is not None
                  and newest > html.stat().st_mtime),
        "path": str(gallery.relative_to(root)),
    }


def survey(root: Path) -> dict:
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
        "gallery": gallery_status(root, records),
        "next_action": ("run the workspace's scripts/gallery/gallery_run.sh "
                        "for stale/missing renders, then `eyes review`"),
    }


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
    print(f"Next action:    {s['next_action']}")


def _print_review(r: dict):
    print("== EyesReviewSurface ==")
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eyes")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("survey", "review"):
        p = sub.add_parser(mode)
        p.add_argument("workspace", help="visualization-workspace root")
        if mode == "review":
            p.add_argument("--batch", type=int, default=8)
            p.add_argument("--against", default=None,
                           help="reference-figure directory (paper-informed pass)")
    args = parser.parse_args(argv)

    root = Path(args.workspace).resolve()
    if not (root / "scripts").is_dir():
        print(f"eyes: not a visualization workspace (no scripts/): {root}",
              file=sys.stderr)
        return 4

    against = None
    if args.mode == "review" and args.against is not None:
        against = Path(args.against).resolve()
        if not (against.is_dir() and any(
                f.suffix.lower() in REFERENCE_SUFFIXES
                for f in against.rglob("*"))):
            print(f"eyes: no reference figures (png/jpg) under: {against}",
                  file=sys.stderr)
            return 4

    decision = (survey(root) if args.mode == "survey"
                else review(root, args.batch, against))
    if args.json:
        print(json.dumps(decision, indent=2))
    elif args.mode == "survey":
        _print_survey(decision)
    else:
        _print_review(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
