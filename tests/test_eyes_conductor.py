"""Contract tests for the Eyes conductor's CLI footing.

Hermetic: every test fabricates a temp visualization workspace, so surveys and
review surfaces are asserted structurally without depending on the real
checkouts. The conductor is decision-only — asserted explicitly in
test_never_writes — and its core names no repositories (tenant firewall), so
the fixture uses invented domain names.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"


def _run(args, env=None):
    return subprocess.run(
        [str(BRAIN), "eyes", *args], capture_output=True, text=True,
        env={**os.environ, **(env or {})},
    )


def _make_workspace(root: Path) -> Path:
    """scripts/alpha has a rendered producer (2 png + 1 fits, one grouped),
    scripts/beta has a never-rendered producer, and alpha also has an orphan
    images tree with no producer script."""
    alpha = root / "scripts" / "alpha"
    alpha.mkdir(parents=True)
    # producer first, figures after — the normal rendered state (a figure
    # written before its script would nondeterministically flag STALE)
    (alpha / "visualization.py").write_text("# producer\n")
    (alpha / "images" / "visualization" / "sub").mkdir(parents=True)
    (alpha / "images" / "visualization" / "a.png").write_bytes(b"png")
    (alpha / "images" / "visualization" / "sub" / "b.png").write_bytes(b"png")
    (alpha / "images" / "visualization" / "c.fits").write_bytes(b"fits")
    (alpha / "images" / "orphaned_visualization_run").mkdir()
    (alpha / "images" / "orphaned_visualization_run" / "d.png").write_bytes(b"png")
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
        "figure", "observation", "proposal", "surface", "reference", "accepted",
    }
    assert set(r["edit_surfaces"]) == {"config", "plot_api", "script", "data"}
    assert "reference_figures" not in r


def test_review_against_reference_dir(tmp_path):
    root = _make_workspace(tmp_path / "ws")
    ref = tmp_path / "paper_figs"
    (ref / "nested").mkdir(parents=True)
    (ref / "fig1.png").write_bytes(b"png")
    (ref / "nested" / "fig2.JPG").write_bytes(b"jpg")
    (ref / "notes.txt").write_text("not a figure")
    result = _run(["--json", "review", str(root), "--against", str(ref)])
    assert result.returncode == 0, result.stderr
    r = json.loads(result.stdout)
    assert r["reference_figures"] == [
        str(ref / "fig1.png"), str(ref / "nested" / "fig2.JPG"),
    ]
    assert r["next_action"].startswith("read the reference figures FIRST")
    # review targets are unchanged — references are context, not batch items
    assert r["n_figures"] == 3


def test_review_against_empty_dir_exits_4(tmp_path):
    root = _make_workspace(tmp_path / "ws")
    ref = tmp_path / "empty"
    ref.mkdir()
    result = _run(["review", str(root), "--against", str(ref)])
    assert result.returncode == 4
    assert "no reference figures" in result.stderr


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


# ---------------------------------------------------------- the registry ---
# `--instance <name>` resolves through the organ's registry.yaml. The fixture
# is an invented organ + registry (tenant firewall): one instance checked out
# in the grouped layout, one checked out flat, one not on this machine.
REGISTRY = """\
# fabricated instance registry
schema: 1
instances:
  - name: alpha
    repo: alpha_visualization
    path: fam/alpha_visualization
    github: ExampleOrg/alpha_visualization
    manifest: gallery/viz_manifest.yaml
  - name: beta
    repo: beta_visualization
    path: fam/beta_visualization   # flat checkout only
    manifest: "gallery/viz_manifest.yaml"
  - name: gamma
    repo: gamma_visualization
    path: fam/gamma_visualization
    manifest: gallery/viz_manifest.yaml
"""


def _organ_workspace(tmp_path):
    ws = tmp_path / "ws"
    organ = ws / "organs" / "EyesOrgan"
    organ.mkdir(parents=True)
    (organ / "registry.yaml").write_text(REGISTRY)
    alpha = _make_workspace(ws / "fam" / "alpha_visualization")
    (alpha / "gallery").mkdir()
    (alpha / "gallery" / "viz_manifest.yaml").write_text("schema: 1\n")
    _make_workspace(ws / "beta_visualization")
    env = {"PYAUTO_ROOT": str(ws), "PYAUTO_EYES": str(organ)}
    return ws, organ, env


def test_instance_resolves_through_the_registry(tmp_path):
    ws, _, env = _organ_workspace(tmp_path)
    r = _run(["--json", "survey", "--instance", "alpha"], env)
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["kind"] == "EyesSurvey" and s["instance"] == "alpha"
    assert Path(s["workspace"]) == (ws / "fam" / "alpha_visualization").resolve()
    assert s["gaps"] == ["beta/visualization_jax"]
    # The registry's tracked manifest is checked, beside the local gallery.
    assert s["gallery"]["tracked_manifest"] == {
        "path": "gallery/viz_manifest.yaml", "present": True}
    # A flat bundle checkout (<root>/<repo>) resolves too.
    r = _run(["--json", "survey", "--instance", "beta"], env)
    assert r.returncode == 0, r.stderr
    beta = json.loads(r.stdout)
    assert Path(beta["workspace"]) == (ws / "beta_visualization").resolve()
    assert beta["gallery"]["tracked_manifest"]["present"] is False


def test_the_organ_root_means_every_registered_instance(tmp_path):
    _, organ, env = _organ_workspace(tmp_path)
    for mode in ("survey", "review"):
        r = _run(["--json", mode, str(organ)], env)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["kind"] == "EyesInstanceSet" and out["mode"] == mode
        assert [d["instance"] for d in out["decisions"]] == ["alpha", "beta"]
        # The instance with no local checkout is skipped with a note, not guessed.
        assert out["skipped"] == [{
            "instance": "gamma",
            "reason": "no local checkout at fam/gamma_visualization"}]
        assert "instance gamma: no local checkout" in r.stderr
    text = _run(["survey", str(organ)], env)
    assert text.stdout.count("== EyesSurvey ==") == 2
    assert "Instance:       alpha" in text.stdout


def test_unknown_instance_names_the_known_ones(tmp_path):
    _, _, env = _organ_workspace(tmp_path)
    r = _run(["survey", "--instance", "delta"], env)
    assert r.returncode == 2
    assert "no instance 'delta'" in r.stderr and "known: alpha, beta, gamma" in r.stderr


def test_an_instance_with_no_checkout_exits_4(tmp_path):
    _, _, env = _organ_workspace(tmp_path)
    r = _run(["survey", "--instance", "gamma"], env)
    assert r.returncode == 4
    assert "no registered instance has a local checkout" in r.stderr


def test_a_missing_registry_exits_2(tmp_path):
    env = {"PYAUTO_ROOT": str(tmp_path), "PYAUTO_EYES": str(tmp_path / "none")}
    r = _run(["survey", "--instance", "alpha"], env)
    assert r.returncode == 2
    assert "cannot read the instance registry" in r.stderr


def test_the_conductor_names_no_instance():
    # Tenant firewall: the registry is data. The conductor's code may name
    # the organ that holds it, never a project repo or an instance key.
    src = (BRAIN_HOME / "agents" / "conductors" / "eyes" / "_eyes.py").read_text()
    assert "_visualization" not in src
    assert not re.search(r"[\"']lens[\"']", src)
