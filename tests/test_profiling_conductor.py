"""Contract tests for the profiling conductor's CLI footing.

Hermetic: every test builds a synthetic `autolens_profiling` fixture in a temp
dir and passes it via `--workspace`, so the assertions never depend on the state
of the real checkout (whose corpus grows every campaign).

Profiling was the only conductor without a test file when the compile axis was
added; the runtime-axis cases here exist to hold that surface still while the
compile axis grows beside it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"

# Two cells, deliberately asymmetric: one with instruments spanning two entries
# and one single-instrument cell, so cell-expansion bugs cannot hide.
FIXTURE_CELLS = """
CELLS: list[tuple[str, str, tuple[str, ...]]] = [
    ("imaging", "mge", ("hst", "jwst")),
    ("interferometer", "pixelization", ("sma",)),
]
"""

FIXTURE_TRANSFORMS = 'TRANSFORMS = ("jit", "vag")\n'


def _run(args, workspace, root=None):
    env = {**os.environ, "PYAUTO_ROOT": str(root or workspace.parent)}
    return subprocess.run(
        [sys.executable, str(BRAIN_HOME / "agents" / "conductors" / "profiling" / "_profiling.py"), *args,
         "--workspace", str(workspace)],
        capture_output=True, text=True, env=env,
    )


def _record(**kw):
    base = {
        "transform": "jit",
        "trace_s": 1.0,
        "compile_s": 2.0,
        "first_s": 0.1,
        "steady_s": 0.01,
        "dataset_class": "imaging",
        "model_type": "mge",
        "instrument": "hst",
        "hardware": "local_cpu",
        "jax_version": "0.10.2",
        "cache_dir": "",
        "mixed_precision": False,
        "tag": "t",
    }
    base.update(kw)
    return base


def _workspace(tmp_path, records_by_file=None):
    ws = tmp_path / "autolens_profiling"
    lr = ws / "scripts" / "misc" / "likelihood_runtime"
    lr.mkdir(parents=True)
    (lr / "sweep.py").write_text(FIXTURE_CELLS)

    jc = ws / "scripts" / "misc" / "jax_compile"
    jc.mkdir(parents=True)
    (jc / "probe.py").write_text(FIXTURE_TRANSFORMS)

    for rel, records in (records_by_file or {}).items():
        p = jc / "results" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(records))

    (ws / "results" / "runtime").mkdir(parents=True)
    vram = ws / "scripts" / "misc" / "vram"
    vram.mkdir(parents=True)
    (vram / "config.py").write_text("VMAP_BATCH = {}\nVMAP_BATCH_SPARSE = {}\nPROVENANCE = {}\n")
    (ws / "hpc" / "batch_gpu").mkdir(parents=True)
    return ws


# ---------------------------------------------------------------------------
# compile axis
# ---------------------------------------------------------------------------


def test_compile_axis_counts_grid_coverage(tmp_path):
    """Records land on the grid via their own fields, not their file path."""
    ws = _workspace(tmp_path, {
        # Filed under mge.json but carrying an interferometer/pixelization cell:
        # placing by path would put this on the wrong cell entirely.
        "local_cpu/mge.json": [
            _record(transform="jit"),
            _record(transform="vag"),
            _record(dataset_class="interferometer", model_type="pixelization",
                    instrument="sma", transform="jit"),
        ],
    })
    r = _run(["campaign", "--axis", "compile", "--json"], ws)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)

    assert d["axis"] == "compile"
    assert d["grid_cells"] == 3            # (imaging,mge,hst/jwst) + (interf,pix,sma)
    assert d["transforms"] == ["jit", "vag"]
    assert d["runs_done"] == 3             # 3 of 3x2 cell/transform runs
    assert d["runs_missing"] == 3
    assert "imaging/mge/jwst [jit]" in d["missing"]
    assert "interferometer/pixelization/sma [vag]" in d["missing"]


def test_off_grid_records_are_reported_not_dropped(tmp_path):
    """knn / delaunay_matern are real measurements, not noise, and not coverage."""
    ws = _workspace(tmp_path, {
        "local_cpu/knn.json": [_record(model_type="knn"), _record(model_type="knn", transform="vag")],
    })
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)

    assert d["runs_done"] == 0, "off-grid records must not count as grid coverage"
    assert d["off_grid"] == [{"cell": "imaging/knn/hst", "records": 2}]


def test_sibling_instrument_records_are_not_called_malformed(tmp_path):
    """export_probe.py / trace_profile.py share the results tree with probe.py.

    Their records lack the whole identity triple because they are a different
    schema, not because they are corrupt — reporting them as malformed would
    send someone to fix a file that is working correctly.
    """
    ws = _workspace(tmp_path, {
        "local_cpu/export_probe.json": [
            {"transform": "jit", "model_type": "mge", "tag": "census"},
            {"transform": "vag", "model_type": "mge", "tag": "census"},
        ],
        "local_cpu/mge.json": [_record()],
    })
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)

    assert d["malformed"] == []
    assert d["foreign_records"] == [{"file": "local_cpu/export_probe.json", "records": 2}]
    assert d["runs_done"] == 1, "the real probe record still counts"


def test_a_genuinely_incomplete_probe_record_is_still_malformed(tmp_path):
    """One field missing is corruption; the whole identity triple is a sibling."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_record(instrument=None), _record()],
    })
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)

    assert d["foreign_records"] == []
    assert len(d["malformed"]) == 1
    m = d["malformed"][0]
    assert m["record"] == "local_cpu/mge.json[0]"
    assert m["missing"] == ["instrument"]
    assert d["runs_done"] == 1, "the well-formed sibling record still counts"


def test_tier_split_does_not_reuse_the_runtime_config_names(tmp_path):
    """hardware+mixed_precision is a different vocabulary from TIER_CONFIGS.

    An fp64 and an mp record on the same hardware are the SAME compile tier —
    folding precision into the tier (as the runtime config names do) would
    double-count them.
    """
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_record(), _record(mixed_precision=True)],
        "local_gpu_NVIDIA_A100_80GB_PCIe/mge.json": [
            _record(hardware="local_gpu_NVIDIA_A100_80GB_PCIe"),
        ],
        "local_gpu_RTX_2060/mge.json": [_record(hardware="local_gpu_RTX_2060")],
    })

    local = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)
    assert local["runs_done"] == 1, "fp64 + mp on one hardware is one cell/transform run"
    assert local["other_hardware"] == [{"hardware": "local_gpu_RTX_2060", "records": 1}]

    a100 = json.loads(_run(["campaign", "--axis", "compile", "--tier", "a100", "--json"], ws).stdout)
    assert a100["runs_done"] == 1
    # The RTX row is not the A100 tier either — it must not be absorbed by it.
    assert a100["other_hardware"] == [{"hardware": "local_gpu_RTX_2060", "records": 1}]


def test_dispatch_plan_names_the_missing_cell_and_transforms(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_record(transform="jit")]})
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)

    hst = [s for s in d["dispatch_plan"] if "--instrument hst" in s]
    assert len(hst) == 1
    assert "--dataset-class imaging" in hst[0] and "--model-type mge" in hst[0]
    assert "--transforms vag" in hst[0], "only the missing transform is dispatched"


def test_transforms_come_from_the_workspace_not_a_copy(tmp_path):
    """probe.py owns the transform axis; the Brain must not carry a stale copy."""
    ws = _workspace(tmp_path)
    (ws / "scripts" / "misc" / "jax_compile" / "probe.py").write_text(
        'TRANSFORMS = ("jit", "vag", "some_future_transform")\n'
    )
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)
    assert "some_future_transform" in d["transforms"]


def test_unreadable_corpus_file_does_not_take_the_mode_down(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_record()]})
    (ws / "scripts" / "misc" / "jax_compile" / "results" / "local_cpu" / "broken.json").write_text("{{")
    r = _run(["campaign", "--axis", "compile", "--json"], ws)
    assert r.returncode == 0
    assert json.loads(r.stdout)["runs_done"] == 1


def test_absent_compile_corpus_reports_zero_coverage(tmp_path):
    ws = _workspace(tmp_path)
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)
    assert d["runs_done"] == 0
    assert d["runs_missing"] == 6
    assert "outstanding" in d["next_action"]


def test_compile_axis_never_compares_timings(tmp_path):
    """Coverage only. Comparing rows across the comparability key is phase 2/3."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_record(compile_s=2.0), _record(compile_s=900.0, tag="loaded")],
    })
    d = json.loads(_run(["campaign", "--axis", "compile", "--json"], ws).stdout)
    assert "COVERAGE only" in d["policy"]
    blob = json.dumps(d)
    assert "900" not in blob, "a timing value must not leak into a coverage decision"


def test_bad_tier_is_an_error(tmp_path):
    ws = _workspace(tmp_path)
    d = json.loads(_run(["campaign", "--axis", "compile", "--tier", "nope", "--json"], ws).stdout)
    assert "unknown tier" in d["error"]


# ---------------------------------------------------------------------------
# axis routing
# ---------------------------------------------------------------------------


def test_compile_axis_is_refused_for_ingest_and_triage(tmp_path):
    """Better a usage error than runtime findings reported under a compile flag."""
    ws = _workspace(tmp_path)
    for mode in ("ingest", "triage"):
        r = _run([mode, "--axis", "compile"], ws)
        assert r.returncode == 5, f"{mode}: {r.stdout}{r.stderr}"
        assert "not implemented" in r.stderr


def test_missing_workspace_exits_4(tmp_path):
    r = _run(["campaign", "--axis", "compile"], tmp_path / "nope")
    assert r.returncode == 4


# ---------------------------------------------------------------------------
# runtime axis — held still while the compile axis grows beside it
# ---------------------------------------------------------------------------


def test_runtime_axis_is_the_default_and_unaffected(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_record()]})
    default = _run(["campaign", "--json"], ws)
    explicit = _run(["campaign", "--axis", "runtime", "--json"], ws)
    assert default.returncode == 0
    assert default.stdout == explicit.stdout

    d = json.loads(default.stdout)
    assert "axis" not in d, "the runtime decision shape must not change"
    assert d["grid_cells"] == 3
    # 3 cells x 2 local configs, none present in the empty runtime tree.
    assert d["runs_missing"] == 6
    assert d["runs_done"] == 0
    assert d["runs_unusable"] == 0
    # The runtime axis buckets by sweep CONFIG name; a compile transform name
    # appearing here would mean the two vocabularies had been crossed.
    assert all("local_cpu_" in run_id for run_id in d["missing"])
    assert not any(tf in run_id for run_id in d["missing"] for tf in ("[jit]", "[vag]"))


def test_runtime_ingest_and_triage_still_run(tmp_path):
    ws = _workspace(tmp_path)
    for mode in ("ingest", "triage"):
        r = _run([mode, "--json"], ws)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["mode"] == mode


def test_cli_dispatcher_exposes_the_axis_flag(tmp_path):
    """The flag must reach the agent through bin/pyauto-brain, not just directly."""
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_record()]})
    r = subprocess.run(
        [str(BRAIN), "profiling", "campaign", "--axis", "compile", "--json", "--workspace", str(ws)],
        capture_output=True, text=True, env={**os.environ, "PYAUTO_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["axis"] == "compile"
