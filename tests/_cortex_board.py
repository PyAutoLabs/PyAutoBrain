"""tests/_cortex_board.py — the two-organ test fixture's science half.

The builder behind `test_cortex_conductor.py`'s `board` fixture, lifted here so
`test_batch_kinds.py` can raise the same tree without a second copy of it. It
is a *builder*, not a fixture: each test module wraps it in its own
`@pytest.fixture` (they need different scopes and different companions), and
nothing here imports pytest.

The laptop tree it imitates was read on 2026-09-01: a profiling-style project
(`logs/output/output.<jobid>.out`, run dirs under `output/searches/**/<hash>/`
beside a `<hash>.zip`, result JSONs carrying a top-level `version`) and a
subhalo-style one (`hpc/batch_cpu/output/…`, no `Finished.` line, no version
key anywhere, and seven run dirs that are stale partial extractions of an
authoritative zip).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path


HEALTHY_OUT = (
    "2026-08-30 09:00:00,101 - autofit - INFO - Starting the search\n"
    "2026-08-30 09:30:00,101 - autofit - INFO - 5000 iterations\n"
    "2026-08-30 09:51:00,900 - autofit - INFO - Search complete\n"
    "Finished.\n")
BENIGN_ERR = (
    "/usr/lib/python3/site-packages/numba/core/ir.py:112: UserWarning: "
    "Cannot cache compiled function\n"
    "  warnings.warn(msg)\n")
SUMMARY = "Total Samples = 4000\nTime To Run = {}\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _zip_summary(path: Path, hours: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("search.summary", SUMMARY.format(hours))
    return path


def _phase(project, number, slug, budget, runs, where, witness_prose,
           minutes=5, state="running"):
    stems = ", ".join(r.split(":")[0].split("_")[0] for r in runs)
    body = "\n".join(f"- {r}" for r in runs)
    return (f"# {project.title()} — phase {number}: {slug}\n\n"
            f"Project: {project}\nPhase: {number}\nState: {state}\n"
            f"Witness: {witness_prose}\nBudget: {budget}\n"
            f"Runs: {stems}\nReview-minutes: {minutes}\n"
            f"Filed: 2026-08-30\n\n"
            f"## Question\n\nDoes it converge?\n\n"
            f"## Witness\n\n{witness_prose}\n\n"
            f"## Where to look\n\n- `{where}`\n\n"
            f"## Runs\n\n{body}\n\n## Ruling\n\n(none)\n")


PROJECTS = """# Test fixture — two science projects, two laptop layouts.

example:
  remote: none
  local_path: {local}
  ral_root: /ral/example
  mirror: {mirror}
  sync_cli: hpc/sync
  sync_verbs: [pull, submit, jobs, tail]
  ledger: wiki/project/state.md
  witness_file: results/**/*.json
  partition: gpu
  status: active

subhalo:
  remote: none
  local_path: {sub}
  ral_root: /ral/subhalo
  mirror: none
  sync_cli: hpc/sync
  sync_verbs: [pull, submit, jobs, tail]
  ledger: wiki/project/state.md
  witness_file: results/**/*.json
  partition: ral
  status: active
"""


def build_board(tmp_path: Path, skeleton: Path) -> dict:
    """A tmp Cortex with three live phases, and the two laptop trees they
    were pulled into.

    The fixture's `projects.yaml` points at fictional absolute paths (it is the
    one file in the organism allowed to carry one), so the rows are rewritten
    to the tmp trees here — the conductor must reach a project only through
    that file, never through a path of its own.
    """
    root = tmp_path / "cortex"
    shutil.copytree(skeleton, root)
    mirror, local, sub = (tmp_path / "mirror", tmp_path / "local",
                          tmp_path / "subhalo")
    for d in (mirror, local, sub):
        d.mkdir()
    (root / "projects.yaml").write_text(
        PROJECTS.format(local=local, mirror=mirror, sub=sub), encoding="utf-8")

    # --- member 1: healthy, profiling-style -------------------------------
    _write(mirror / "logs/output/output.400100.out", HEALTHY_OUT)
    _write(mirror / "logs/error/error.400100.err", BENIGN_ERR)
    run1 = mirror / "output/searches/bright/aaaa1111"
    _write(run1 / "search.summary", SUMMARY.format("0:51:28.387009"))
    (run1 / ".completed").write_text("", encoding="utf-8")
    _write(mirror / "results/searches/bright/aaaa1111.json",
           json.dumps({"version": "2026.8.17.1", "log_likelihood": 1234.5,
                       "total_samples": 4000}))
    _write(mirror / ".cortex/pull.json", json.dumps(
        {"pulled_at": "2026-08-31T10:00Z",
         "runs": {"400100": {"checkpoint_bytes": 40960,
                             "checkpoint_mtime": "2026-08-30T09:51Z"}}}))
    _write(root / "phases/example/11_healthy.md", _phase(
        "example", 11, "the bright lens", "6:00",
        ["400100: done — gpu — submitted 2026-08-30 — wall 0:51"],
        mirror / "output/searches/bright",
        "a result JSON carrying the installed stack's version stamp"))

    # --- member 2: the run resumed the previous fit ------------------------
    _write(mirror / "logs/output/output.400200.out",
           HEALTHY_OUT.replace("Starting the search",
                               "Fit Already Completed: skipping"))
    _write(mirror / "logs/error/error.400200.err", BENIGN_ERR)
    run2 = mirror / "output/searches/faint/bbbb2222"
    _write(run2 / "search.summary", SUMMARY.format("0:44:00.000000"))
    (run2 / ".completed").write_text("", encoding="utf-8")
    _write(mirror / "results/searches/faint/bbbb2222.json",
           json.dumps({"version": "2026.8.17.1", "log_likelihood": 1200.0}))
    _write(root / "phases/example/12_resumed.md", _phase(
        "example", 12, "the faint lens", "6:00",
        ["400200: done — gpu — submitted 2026-08-30 — wall 0:44"],
        mirror / "output/searches/faint",
        "a result JSON carrying the installed stack's version stamp"))

    # --- member 3: subhalo-style — zip authoritative, no version stamp -----
    _write(sub / "hpc/batch_cpu/output/output.400300_0.out",
           "2026-08-30 08:00:00,000 - autofit - INFO - Starting the search\n")
    _write(sub / "hpc/batch_cpu/error/error.400300_0.err", BENIGN_ERR)
    # the extracted dir is a stale partial: its summary is the wrong run.
    _write(sub / "output/lens_a/cccc3333/search.summary",
           SUMMARY.format("0:04:00.000000"))
    _zip_summary(sub / "output/lens_a/cccc3333.zip", "0:51:28.387009")
    _write(sub / "results/pipeline/lens_a.json",
           json.dumps({"log_likelihood": 999.0, "n_live": 200}))
    _write(root / "phases/subhalo/01_partial.md", _phase(
        "subhalo", 1, "the partial extraction", "1:00",
        ["400300_0: done — ral — submitted 2026-08-30 — wall 0:51"],
        sub / "output/lens_a",
        "the pipeline JSON lands for the lens"))

    return {"root": root, "mirror": mirror, "local": local, "sub": sub}
