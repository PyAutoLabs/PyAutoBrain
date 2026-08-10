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


def test_every_mode_serves_the_compile_axis(tmp_path):
    """The arc is closed: campaign, ingest and triage all answer --axis compile."""
    ws = _workspace(tmp_path)
    for mode in ("campaign", "ingest", "triage"):
        r = _run([mode, "--axis", "compile", "--json"], ws)
        assert r.returncode == 0, f"{mode}: {r.stdout}{r.stderr}"
        assert json.loads(r.stdout)["axis"] == "compile"


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


# ---------------------------------------------------------------------------
# ingest --axis compile (warm pins)
# ---------------------------------------------------------------------------


def _pinned(ws, pins):
    (ws / "scripts" / "misc" / "jax_compile" / "pins.json").write_text(
        json.dumps({"schema": 1, "pins": pins})
    )


def _pin(**kw):
    base = {
        "hardware": "local_cpu",
        "hostname": "laptop",
        "jax_version": "0.10.2",
        "mixed_precision": False,
        "cache_state": "warm",
        "dataset_class": "imaging",
        "model_type": "mge",
        "instrument": "hst",
        "transform": "vag",
        "compile_s": 2.3,
        "source_tag": "census-warm",
        "source_timestamp": "2026-07-01T00:00:00",
    }
    base.update(kw)
    return base


def _warm(**kw):
    base = {
        "cache_state": "warm",
        "hostname": "laptop",
        "timestamp": "2026-08-01T00:00:00",
        "transform": "vag",  # matches _pin's default, so the keys line up
    }
    base.update(kw)
    return _record(**base)


def test_a_warm_row_reverting_toward_cold_is_drift(tmp_path):
    """The alarm the whole arc exists for: the cache stopped being hit."""
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm(compile_s=117.0)]})
    _pinned(ws, [_pin(compile_s=2.3)])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)

    assert len(d["drifted"]) == 1
    x = d["drifted"][0]
    assert (x["pinned_s"], x["observed_s"]) == (2.3, 117.0)
    assert x["ratio"] > 50


def test_rows_predating_the_pin_are_not_drift(tmp_path):
    """The pin was CHOSEN over this history; flagging it reports the
    improvement that set the pin as a regression."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=117.0, timestamp="2026-06-01T00:00:00")],
    })
    _pinned(ws, [_pin(compile_s=2.3, source_timestamp="2026-07-01T00:00:00")])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["drifted"] == []


def test_drift_never_pairs_across_the_comparability_key(tmp_path):
    """A slow row on ANOTHER host/version/precision is not this pin's business."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [
            _warm(compile_s=117.0, hostname="euclid-ral-compute-22"),
            _warm(compile_s=117.0, jax_version="0.11.0"),
            _warm(compile_s=117.0, mixed_precision=True),
        ],
    })
    _pinned(ws, [_pin(compile_s=2.3)])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)

    assert d["drifted"] == [], "cross-key rows must never be reported as drift"
    assert len(d["unpinned"]) == 3, "they are unpinned keys of their own, not silence"


def test_a_jax_version_bump_is_a_new_key_not_a_regression(tmp_path):
    """Cache keys include the jax version, so a bump recompiles once BY DESIGN."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=117.0, jax_version="0.11.0")],
    })
    _pinned(ws, [_pin(compile_s=2.3, jax_version="0.10.2")])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["drifted"] == []
    assert len(d["unpinned"]) == 1


def test_small_absolute_moves_on_cheap_cells_are_not_drift(tmp_path):
    """0.05s -> 0.30s is 6x and completely uninteresting; the absolute floor
    exists so sub-second jitter does not train people to ignore the alarm."""
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm(compile_s=0.30)]})
    _pinned(ws, [_pin(compile_s=0.05)])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["drifted"] == []


def test_large_absolute_move_below_the_ratio_is_not_drift(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm(compile_s=130.0)]})
    _pinned(ws, [_pin(compile_s=100.0)])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["drifted"] == []


def test_cold_rows_are_never_compared_against_a_warm_pin(tmp_path):
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_record(cache_state="cold", compile_s=117.0, hostname="laptop")],
    })
    _pinned(ws, [_pin(compile_s=2.3)])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["drifted"] == [] and d["unpinned"] == []


def test_unpinned_warm_keys_are_reported_once_each(tmp_path):
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=2.0), _warm(compile_s=2.1)],
    })
    _pinned(ws, [])
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["next_action"].startswith("no compile pins")


def test_absent_pins_file_says_so_rather_than_reporting_all_clear(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm()]})
    d = json.loads(_run(["ingest", "--axis", "compile", "--json"], ws).stdout)
    assert d["pins"] == 0
    assert "update_pins.py" in d["next_action"]


def test_brain_comparability_key_matches_the_workspace_definition(tmp_path):
    """The Brain mirrors pins.py rather than importing it (importing the
    workspace would drag the JAX stack in), so pin the two together."""
    import ast as _ast

    ws = _workspace(tmp_path)
    pins_py = ws / "scripts" / "misc" / "jax_compile" / "pins.py"
    pins_py.write_text(
        'COMPARABILITY_FIELDS = ("hardware", "hostname", "jax_version", '
        '"mixed_precision", "cache_state")\n'
        'CELL_FIELDS = ("dataset_class", "model_type", "instrument", "transform")\n'
    )
    tree = _ast.parse(pins_py.read_text())
    found = {
        t.id: _ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, _ast.Assign)
        for t in n.targets
        if isinstance(t, _ast.Name)
    }

    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "profiling"))
    import _profiling  # noqa: PLC0415

    assert _profiling.COMPARABILITY_FIELDS == found["COMPARABILITY_FIELDS"]
    assert _profiling.CELL_FIELDS == found["CELL_FIELDS"]


# ---------------------------------------------------------------------------
# triage --axis compile (classification)
# ---------------------------------------------------------------------------


def _triage(ws):
    r = _run(["triage", "--axis", "compile", "--json"], ws)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_warm_returning_to_its_cold_scale_is_a_cache_regression(tmp_path):
    """The alarm the whole arc exists for."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [
            _record(cache_state="cold", compile_s=117.0, hostname="laptop",
                    transform="vag", timestamp="2026-06-01T00:00:00"),
            _warm(compile_s=110.0),
        ],
    })
    _pinned(ws, [_pin(compile_s=2.3)])
    d = _triage(ws)

    assert d["counts"] == {"cache-regression": 1}
    f = d["findings"][0]
    assert "cold scale" in f["evidence"]
    assert "NOT the library" in f["action"]


def test_growth_with_no_cold_scale_match_routes_to_the_library(tmp_path):
    """Not everything slow is the cache; what is left over is a bug/ candidate."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [
            _record(cache_state="cold", compile_s=117.0, hostname="laptop",
                    transform="vag", timestamp="2026-06-01T00:00:00"),
            _warm(compile_s=8.0),  # 3.5x the pin, nowhere near 117s
        ],
    })
    _pinned(ws, [_pin(compile_s=2.3)])
    d = _triage(ws)

    assert d["counts"] == {"library-regression": 1}
    assert "intake" in d["findings"][0]["action"]
    assert "never debugs the library here" in d["findings"][0]["action"]


def test_a_busy_host_is_not_a_regression(tmp_path):
    """Compile runs on host cores; load alone has produced 7x errors here."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [
            _warm(compile_s=8.0, host_state={"cpu_count": 8, "load_avg_1m": 14.0}),
        ],
    })
    _pinned(ws, [_pin(compile_s=2.3)])
    d = _triage(ws)

    assert d["counts"] == {"host-load": 1}
    assert "NOT a regression until re-measured" in d["findings"][0]["action"]


def test_a_big_gpu_jump_reads_as_autotune(tmp_path):
    ws = _workspace(tmp_path, {
        "local_gpu_NVIDIA_A100_80GB_PCIe/mge.json": [
            _warm(compile_s=50.0, hardware="local_gpu_NVIDIA_A100_80GB_PCIe"),
        ],
    })
    _pinned(ws, [_pin(compile_s=2.3, hardware="local_gpu_NVIDIA_A100_80GB_PCIe")])
    d = _triage(ws)

    assert d["counts"] == {"autotune-regression": 1}
    assert "XLA_FLAGS" in d["findings"][0]["action"]


def test_a_jax_bump_is_an_expected_recompile_not_a_regression(tmp_path):
    """Cache keys include the jax version, so a bump recompiles once BY DESIGN."""
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=117.0, jax_version="0.11.0")],
    })
    _pinned(ws, [_pin(compile_s=2.3, jax_version="0.10.2")])
    d = _triage(ws)

    assert d["counts"] == {"expected-recompile": 1}
    f = d["findings"][0]
    assert "BY DESIGN" in f["evidence"]
    assert "not drift" in f["action"]


def test_a_new_machine_is_classified_as_such(tmp_path):
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=9.0, hostname="euclid-ral-compute-22")],
    })
    _pinned(ws, [_pin(compile_s=2.3, hostname="laptop")])
    d = _triage(ws)

    assert d["counts"] == {"new-machine": 1}
    assert "never comparable across machines" in d["findings"][0]["action"]


def test_an_unrelated_cell_is_simply_new(tmp_path):
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=9.0, model_type="pixelization")],
    })
    _pinned(ws, [_pin(compile_s=2.3, model_type="mge")])
    d = _triage(ws)
    assert d["counts"] == {"new-cell": 1}


def test_bookkeeping_classifications_do_not_count_as_actionable(tmp_path):
    ws = _workspace(tmp_path, {
        "local_cpu/mge.json": [_warm(compile_s=117.0, jax_version="0.11.0")],
    })
    _pinned(ws, [_pin(compile_s=2.3, jax_version="0.10.2")])
    d = _triage(ws)
    assert "1 finding(s); 0 needing action" in d["next_action"]


def test_a_clean_corpus_reports_no_findings(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm(compile_s=2.3)]})
    _pinned(ws, [_pin(compile_s=2.3)])
    d = _triage(ws)
    assert d["findings"] == []
    assert "no compile findings" in d["next_action"]


def test_no_pins_says_so_rather_than_reporting_clean(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm()]})
    d = _triage(ws)
    assert d["findings"] == []
    assert "update_pins.py" in d["next_action"]


def test_internal_plumbing_is_not_emitted(tmp_path):
    """The raw key tuples are implementation detail, not part of the decision."""
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm(compile_s=117.0)]})
    _pinned(ws, [_pin(compile_s=2.3)])
    for mode in ("ingest", "triage"):
        r = _run([mode, "--axis", "compile", "--json"], ws)
        assert "_key" not in r.stdout, mode


def test_triage_writes_nothing_to_the_workspace(tmp_path):
    ws = _workspace(tmp_path, {"local_cpu/mge.json": [_warm(compile_s=117.0)]})
    _pinned(ws, [_pin(compile_s=2.3)])
    before = {p: p.stat().st_mtime_ns for p in ws.rglob("*") if p.is_file()}
    _triage(ws)
    after = {p: p.stat().st_mtime_ns for p in ws.rglob("*") if p.is_file()}
    assert before == after, "the conductor reasons and delegates; it never edits the workspace"
