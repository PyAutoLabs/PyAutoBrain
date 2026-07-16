"""Contract tests for the Eyes conductor's CLI footing.

Hermetic: every test fabricates a temp visualization workspace, so surveys and
review surfaces are asserted structurally without depending on the real
checkouts. The conductor is decision-only — asserted explicitly in
test_never_writes — and its core names no repositories (tenant firewall), so
the fixture uses invented domain names.
"""

import json
import os
import subprocess
import time
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"


def _run(args):
    return subprocess.run(
        [str(BRAIN), "eyes", *args], capture_output=True, text=True,
    )


def _make_workspace(root: Path) -> Path:
    """scripts/alpha has a rendered producer (2 png + 1 fits, one grouped),
    scripts/beta has a never-rendered producer, and alpha also has an orphan
    images tree with no producer script."""
    alpha = root / "scripts" / "alpha"
    (alpha / "images" / "visualization" / "sub").mkdir(parents=True)
    (alpha / "images" / "visualization" / "a.png").write_bytes(b"png")
    (alpha / "images" / "visualization" / "sub" / "b.png").write_bytes(b"png")
    (alpha / "images" / "visualization" / "c.fits").write_bytes(b"fits")
    (alpha / "images" / "orphaned_visualization_run").mkdir()
    (alpha / "images" / "orphaned_visualization_run" / "d.png").write_bytes(b"png")
    (alpha / "visualization.py").write_text("# producer\n")
    beta = root / "scripts" / "beta"
    beta.mkdir(parents=True)
    (beta / "visualization_jax.py").write_text("# producer, never run\n")
    return root


def _survey(root):
    result = _run(["--json", "survey", str(root)])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_survey_inventory_gaps_and_orphans(tmp_path):
    s = _survey(_make_workspace(tmp_path))
    assert s["kind"] == "EyesSurvey"
    assert s["domains"] == ["alpha", "beta"]
    by_name = {f"{r['domain']}/{r['script']}": r for r in s["records"]}
    alpha = by_name["alpha/visualization"]
    assert (alpha["n_png"], alpha["n_fits"]) == (2, 1)
    assert "scripts/alpha/images/visualization/sub/b.png" in alpha["figures"]
    assert s["gaps"] == ["beta/visualization_jax"]
    assert s["orphans"] == ["alpha/orphaned_visualization_run"]
    assert s["stale_renders"] == []


def test_survey_flags_stale_render_and_gallery(tmp_path):
    root = _make_workspace(tmp_path)
    gallery = root / "output" / "gallery"
    gallery.mkdir(parents=True)
    (gallery / "gallery.html").write_text("<html>")
    (gallery / "viz_manifest.yaml").write_text("{}")
    assert _survey(root)["gallery"] == {
        "built": True, "manifest": True, "stale": False, "path": "output/gallery",
    }
    # a figure newer than the gallery, and the producer edited later still
    future = time.time() + 60
    os.utime(root / "scripts" / "alpha" / "images" / "visualization" / "a.png",
             (future, future))
    os.utime(root / "scripts" / "alpha" / "visualization.py",
             (future + 60, future + 60))
    s = _survey(root)
    assert s["stale_renders"] == ["alpha/visualization"]
    assert s["gallery"]["stale"] is True


def test_review_surface_batches_and_schema(tmp_path):
    root = _make_workspace(tmp_path)
    result = _run(["--json", "review", str(root), "--batch", "2"])
    assert result.returncode == 0, result.stderr
    r = json.loads(result.stdout)
    assert r["kind"] == "EyesReviewSurface"
    assert r["n_figures"] == 3
    assert [len(b) for b in r["batches"]] == [2, 1]
    assert set(r["note_schema"]) == {
        "figure", "observation", "proposal", "surface", "accepted",
    }
    assert set(r["edit_surfaces"]) == {"config", "plot_api", "script", "data"}


def test_not_a_workspace_exits_4(tmp_path):
    result = _run(["survey", str(tmp_path)])
    assert result.returncode == 4
    assert "not a visualization workspace" in result.stderr


def test_never_writes(tmp_path):
    root = _make_workspace(tmp_path)
    before = sorted(str(p) for p in root.rglob("*"))
    for mode in (["survey", str(root)], ["review", str(root)]):
        assert _run(mode).returncode == 0
    assert sorted(str(p) for p in root.rglob("*")) == before
