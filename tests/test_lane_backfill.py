"""The Lane backfill (PyAutoBrain#608, M1.3 slice 2): `bin/lane_backfill.py`
and the intake inference words it shares.

Witness (b): the proposal covers every planner-pool draft that lacks a valid
`Lane:`, and applying it to a copy leaves none without one.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "intake"))
import _intake  # noqa: E402
from _sizing import declared_header  # noqa: E402

_spec = importlib.util.spec_from_file_location("lane_backfill", BRAIN / "bin" / "lane_backfill.py")
lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lb)


# --- intake learns the missing words ---------------------------------------------

@pytest.mark.parametrize("text,lane", [
    ("Re-run the timing leg on the A100 for @PyAutoBrain.", "ral"),
    ("Profile it on two A100s.", "ral"),
    ("Submit the sweep to the HPC queue.", "ral"),
    ("Submit it with SLURM.", "ral"),
    ("Outputs live under /mnt/ral/jnightin/out.", "ral"),
    ("Compare the GPU and CPU timings.", "gpu"),
    ("Read the cutouts from /mnt/d/archive.", "wsl-data"),
    ("Fit the Euclid private data release.", "local-dev"),
    ("Needs the private datasets on the laptop.", "local-dev"),
])
def test_intake_infers_the_new_lane_words(text, lane):
    assert _intake.infer_lane(text) == lane
    assert f"\nLane: {lane}" in _intake.analyse(text + " @PyAutoBrain", "test")["header"]


@pytest.mark.parametrize("text", [
    "Tidy a docstring.",
    "The PyAutoGPU venv path is documented.",     # no word boundary: not the GPU
    "A general refactor of the parser.",          # `RAL` must be its own word
    "Point the gpu flag at the right default.",  # lower-case code identifier
])
def test_intake_stays_narrow(text):
    assert _intake.infer_lane(text) == "any"


def test_ral_outranks_gpu_and_evidence_is_the_matching_words():
    lane, snippet = _intake.infer_lane_evidence(
        "Benchmark on the GPU. The full sweep runs on the RAL A100 nodes.")
    assert lane == "ral" and "RAL" in snippet


# --- the backfill ------------------------------------------------------------------

def _prompt(lane_line: str, body: str, unattended="ready") -> str:
    return (f"# T\n\nType: feature\nTarget: PyAutoBrain\nRepos:\n- PyAutoBrain\n"
            f"Autonomy: safe\nConsequence: glance\nWitness: w\nReview-minutes: 3\n"
            f"Unattended: {unattended}\n{lane_line}\n\n{body}\n")


def _mind(tmp_path) -> Path:
    mind = tmp_path / "mind"
    d = mind / "draft" / "feature" / "pyautobrain"
    d.mkdir(parents=True)
    files = {
        "ral.md": _prompt("", "Time it on the A100 via sbatch."),
        "gpu.md": _prompt("", "Compare GPU throughput."),
        "wsl.md": _prompt("", "Data under /mnt/c/Users/x/data."),
        "private.md": _prompt("", "Needs the private data on disk."),
        "plain.md": _prompt("", "Tidy a docstring."),
        "invalid.md": _prompt("Lane: any | local-dev", "Tidy."),
        "declared.md": _prompt("Lane: local-dev", "Mentions RAL but declares."),
        "not_ready.md": _prompt("", "On RAL.", unattended="needs-slicing"),
    }
    for name, text in files.items():
        (d / name).write_text(text)
    return mind


def _lane_less_pool(mind: Path) -> set[str]:
    return {d["path"] for d in lb.lane_less(mind)}


def test_witness_b_proposal_covers_the_pool_and_apply_leaves_none(tmp_path):
    mind = _mind(tmp_path)
    before = _lane_less_pool(mind)
    rows = lb.propose(mind)
    assert {r["path"] for r in rows} == before          # covers every one
    by = {Path(r["path"]).stem: r for r in rows}
    assert {k: by[k]["lane"] for k in by} == {
        "ral": "ral", "gpu": "gpu", "wsl": "wsl-data", "private": "local-dev",
        "plain": "any", "invalid": "any"}
    assert "A100" in by["ral"]["evidence"] and by["plain"]["evidence"] == ""
    assert "not_ready" not in by and "declared" not in by   # outside the pool / declared

    # Applied to a COPY, through the human-skimmable table, edits honoured.
    copy = tmp_path / "copy"
    shutil.copytree(mind, copy)
    table = tmp_path / "proposals.md"
    text = lb.table(rows, scope="test")
    table.write_text(text.replace("| `draft/feature/pyautobrain/gpu.md` | `gpu` |",
                                  "| `draft/feature/pyautobrain/gpu.md` | `any` |"))
    assert lb.main(["--mind", str(copy), "--apply", "--from", str(table)]) == 0
    assert _lane_less_pool(copy) == set()               # none left without one
    gpu = (copy / "draft/feature/pyautobrain/gpu.md").read_text()
    assert declared_header(gpu)["lane"] == "any"        # the human's overrule won
    # Lane: lands after Unattended:, the invalid line is replaced, the rest kept.
    ral = (copy / "draft/feature/pyautobrain/ral.md").read_text()
    assert "Unattended: ready\nLane: ral\n" in ral
    inv = (copy / "draft/feature/pyautobrain/invalid.md").read_text()
    assert inv.count("Lane:") == 1 and "Lane: any\n" in inv
    # The original Mind is untouched: proposing never writes.
    assert _lane_less_pool(mind) == before


def test_apply_without_a_table_reproposes_and_all_widens_the_scope(tmp_path):
    mind = _mind(tmp_path)
    assert lb.main(["--mind", str(mind), "--apply"]) == 0
    assert _lane_less_pool(mind) == set()
    assert {Path(d["path"]).stem for d in lb.lane_less(mind, every=True)} == {"not_ready"}


def test_apply_refuses_a_bad_lane_and_a_declared_one(tmp_path):
    mind = _mind(tmp_path)
    written, refused = lb.apply(mind, [
        {"path": "draft/feature/pyautobrain/plain.md", "lane": "cloud"},
        {"path": "draft/feature/pyautobrain/declared.md", "lane": "any"},
        {"path": "draft/feature/pyautobrain/missing.md", "lane": "any"}])
    assert written == [] and len(refused) == 3


def test_proposal_mode_writes_only_the_table(tmp_path, capsys):
    mind = _mind(tmp_path)
    before = {f: f.read_text() for f in mind.rglob("*.md")}
    out = tmp_path / "scratch" / "proposals.md"
    assert lb.main(["--mind", str(mind), "--out", str(out)]) == 0
    assert {f: f.read_text() for f in mind.rglob("*.md")} == before
    text = out.read_text()
    assert "Counts: `any` 2" in text and text.count("| `draft/") == 6
    assert "--from belongs" not in capsys.readouterr().err
    assert lb.main(["--mind", str(mind), "--from", str(out)]) == 2
