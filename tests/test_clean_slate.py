"""Safety and behavior tests for the generated-cruft cleanup executor."""

import os
import subprocess
from pathlib import Path


BRAIN_HOME = Path(__file__).resolve().parents[1]
CLEAN_SLATE = BRAIN_HOME / "bin" / "clean_slate.sh"
PROVENANCE = BRAIN_HOME / "bin" / "dataset_provenance.py"

# clean_slate.sh only sweeps datasets in the repos it knows are workspaces.
DATASET_REPO = "autolens_workspace"


def _init_repo(root, name, ignore="*.egg-info/\nbuild/\n"):
    repo = root / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if ignore:
        (repo / ".gitignore").write_text(ignore)
    return repo


def _run(root, dry_run=False, packaging_only=True):
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    if dry_run:
        env["DRY_RUN"] = "1"
    args = ["bash", str(CLEAN_SLATE)]
    if packaging_only:
        args.append("--packaging")
    return subprocess.run(args, capture_output=True, text=True, env=env)


def _write(directory, name="generated.txt"):
    directory.mkdir(parents=True)
    (directory / name).write_text("generated")


def _script(repo, rel, source):
    """Drop a workspace script the provenance scan will parse."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def _dataset(repo, dataset_type, name, filename="data.fits"):
    """Create an untracked dataset directory holding one file."""
    path = repo / "dataset" / dataset_type / name
    path.mkdir(parents=True, exist_ok=True)
    if filename:
        (path / filename).write_text("bytes")
    return path


def _track(repo, *rel_paths):
    subprocess.run(["git", "-C", str(repo), "add", "-f", *rel_paths], check=True)


def _provenance(repo, *candidates):
    return subprocess.run(
        ["python3", str(PROVENANCE), "--repo", str(repo), *candidates],
        capture_output=True,
        text=True,
    )


# A simulator that binds its dataset path from `dataset_type`/`dataset_name` and
# writes it — the shape every workspace `simulator.py` uses.
SIMULATOR = '''
from pathlib import Path
import autolens as al
import autolens.plot as aplt

dataset_type = "imaging"
dataset_name = "simple"
dataset_path = Path("dataset", dataset_type, dataset_name)

aplt.fits_imaging(
    dataset=dataset,
    data_path=dataset_path / "data.fits",
    noise_map_path=dataset_path / "noise_map.fits",
    overwrite=True,
)
'''

# The #167 shape: a start_here.py that READS a real dataset by name and, further
# down the same file, REBINDS `dataset_path` and WRITES a simulated one. Only
# the simulated one may be deleted.
START_HERE = '''
from pathlib import Path
import autolens as al
import autolens.plot as aplt

dataset_name = "sdp81"
dataset_path = Path("dataset") / "interferometer" / dataset_name

dataset = al.Interferometer.from_fits(
    data_path=dataset_path / "data.fits",
    noise_map_path=dataset_path / "noise_map.fits",
)

al.output_to_fits(values=image.native, file_path=Path("image.fits"), overwrite=True)

dataset_path = Path("dataset") / "imaging" / "simulated_lens"

al.output_to_fits(
    values=dataset.data.native,
    file_path=dataset_path / "data.fits",
    overwrite=True,
)
'''

DOWNLOADER = '''
from pathlib import Path
import urllib.request

dataset_path = Path("dataset") / "cluster" / "smacs0723"
catalogue_path = dataset_path / "galcat.cat"

if not catalogue_path.exists():
    urllib.request.urlretrieve("https://example.invalid/galcat.cat", catalogue_path)
'''


def test_dry_run_reports_packaging_without_removing_it(tmp_path):
    repo = _init_repo(tmp_path, "PyAutoGalaxy")
    egg_info = repo / "autogalaxy.egg-info"
    build = repo / "build"
    _write(egg_info)
    _write(build)

    result = _run(tmp_path, dry_run=True)

    assert result.returncode == 0, result.stderr
    assert "[dry-run] remove packaging directory autogalaxy.egg-info/" in result.stdout
    assert "[dry-run] remove packaging directory build/" in result.stdout
    assert egg_info.exists() and build.exists()


def test_cleanup_is_root_scoped_ignored_and_tracked_safe(tmp_path):
    repo = _init_repo(tmp_path, "PyAutoGalaxy")
    egg_info = repo / "autogalaxy.egg-info"
    build = repo / "build"
    nested_build = repo / "src" / "build"
    output = repo / "output"
    _write(egg_info)
    _write(build)
    _write(nested_build)
    _write(output)
    (repo / "test_report.md").write_text("keep in packaging-only mode")

    protected = _init_repo(tmp_path, "PyAutoFit")
    _write(protected / "build", "tracked.txt")
    subprocess.run(
        ["git", "-C", str(protected), "add", "-f", "build/tracked.txt"],
        check=True,
    )

    unignored = _init_repo(tmp_path, "PyAutoArray", ignore="")
    _write(unignored / "local.egg-info")

    assistant = _init_repo(tmp_path, "euclid_assistant")
    _write(assistant / "build")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert not egg_info.exists() and not build.exists()
    assert nested_build.exists()
    assert output.exists() and (repo / "test_report.md").exists()
    assert (protected / "build" / "tracked.txt").exists()
    assert (unignored / "local.egg-info").exists()
    assert (assistant / "build").exists()


def test_dataset_written_by_a_simulator_is_removed(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/simulator.py", SIMULATOR)
    dataset = _dataset(repo, "imaging", "simple")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert not dataset.exists()
    assert "remove 1 simulated dataset(s)" in result.stdout


def test_dataset_written_by_a_non_simulator_script_is_removed(tmp_path):
    """The #167 gap: start_here.py writes datasets too, and no simulator does."""
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/start_here.py", START_HERE)
    dataset = _dataset(repo, "imaging", "simulated_lens")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert not dataset.exists()


def test_dataset_only_read_by_name_is_kept_while_written_one_is_removed(tmp_path):
    """Name mention must never classify — only a write site may.

    One file names the real `sdp81` dataset (which it loads) and writes
    `simulated_lens`. The reader must survive; the written one must not.
    """
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/start_here.py", START_HERE)
    real = _dataset(repo, "interferometer", "sdp81")
    simulated = _dataset(repo, "imaging", "simulated_lens")

    verdicts = _provenance(
        repo, "dataset/interferometer/sdp81", "dataset/imaging/simulated_lens"
    )
    assert verdicts.returncode == 0, verdicts.stderr
    assert "ORPHAN dataset/interferometer/sdp81" in verdicts.stdout
    assert "REGENERABLE dataset/imaging/simulated_lens" in verdicts.stdout

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert real.exists(), "a dataset that is only READ must never be deleted"
    assert not simulated.exists()
    assert "orphan dataset (no writer): dataset/interferometer/sdp81" in result.stdout


def test_downloaded_dataset_is_kept_silently(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/cluster/lenstool/data.py", DOWNLOADER)
    dataset = _dataset(repo, "cluster", "smacs0723", filename="galcat.cat")

    verdicts = _provenance(repo, "dataset/cluster/smacs0723")
    assert "DOWNLOADED dataset/cluster/smacs0723" in verdicts.stdout

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert dataset.exists()
    assert "smacs0723" not in result.stdout, "downloaded data is kept without comment"


def test_tracked_dataset_is_never_deleted_and_is_restored(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/simulator.py", SIMULATOR)
    dataset = _dataset(repo, "imaging", "simple")
    _track(repo, "dataset/imaging/simple/data.fits")
    (dataset / "data.fits").write_text("clobbered by a run")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert dataset.exists(), "a dataset holding tracked files is never a candidate"
    assert (dataset / "data.fits").read_text() == "bytes"
    assert "restore 1 modified dataset file(s)" in result.stdout


def test_dataset_with_no_writer_is_reported_as_an_orphan(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/simulator.py", SIMULATOR)
    orphan = _dataset(repo, "imaging", "tutorial")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert orphan.exists()
    assert "orphan dataset (no writer): dataset/imaging/tutorial" in result.stdout


def test_oversized_committed_dataset_warns_once_per_directory(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    dataset = _dataset(repo, "imaging", "cosmos_web_ring", filename=None)
    for name in ("data.fits", "noise_map.fits"):
        with open(dataset / name, "wb") as f:
            f.truncate(6 * 1024 * 1024)
    _track(repo, "dataset/imaging/cosmos_web_ring")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    warnings = [
        line for line in result.stdout.splitlines() if "committed dataset" in line
    ]
    assert len(warnings) == 1, warnings
    assert "dataset/imaging/cosmos_web_ring is 12 MB (>5 MB)" in warnings[0]


def test_empty_dataset_directories_are_pruned(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    empty = repo / "dataset" / "imaging" / "leftover"
    empty.mkdir(parents=True)

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert not empty.exists()


def test_ipynb_checkpoints_go_but_pycache_stays(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    checkpoints = repo / "scripts" / "imaging" / ".ipynb_checkpoints"
    pycache = repo / "scripts" / "imaging" / "__pycache__"
    _write(checkpoints, "start_here-checkpoint.ipynb")
    _write(pycache, "util.cpython-311.pyc")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert not checkpoints.exists()
    assert pycache.exists(), "__pycache__ is an import-speed cache, not cruft"


def test_dry_run_reports_dataset_actions_without_taking_them(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/start_here.py", START_HERE)
    simulated = _dataset(repo, "imaging", "simulated_lens")
    real = _dataset(repo, "interferometer", "sdp81")
    empty = repo / "dataset" / "imaging" / "leftover"
    empty.mkdir(parents=True)
    checkpoints = repo / "scripts" / ".ipynb_checkpoints"
    _write(checkpoints, "start_here-checkpoint.ipynb")

    result = _run(tmp_path, dry_run=True, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert "[dry-run] remove 1 simulated dataset(s)" in result.stdout
    assert "[dry-run] remove 1 empty dataset directory" in result.stdout
    assert "[dry-run] remove scripts/.ipynb_checkpoints/" in result.stdout
    assert simulated.exists() and real.exists()
    assert empty.exists() and checkpoints.exists()


def test_provenance_helper_failure_aborts_the_sweep(tmp_path):
    """No fallback: a broken helper must stop the run, never guess."""
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _dataset(repo, "imaging", "simple")
    broken = tmp_path / "bin"
    broken.mkdir()
    (broken / "dataset_provenance.py").write_text("import sys\nsys.exit(3)\n")
    (broken / "clean_slate.sh").write_text(CLEAN_SLATE.read_text())

    env = {**os.environ, "PYAUTO_ROOT": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(broken / "clean_slate.sh")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "dataset_provenance.py failed" in result.stderr


def test_unparseable_script_warns_without_crashing_the_sweep(tmp_path):
    repo = _init_repo(tmp_path, DATASET_REPO, ignore="")
    _script(repo, "scripts/imaging/simulator.py", SIMULATOR)
    _script(repo, "scripts/imaging/broken.py", "def f(:\n")
    dataset = _dataset(repo, "imaging", "simple")

    result = _run(tmp_path, packaging_only=False)

    assert result.returncode == 0, result.stderr
    assert "WARN unparseable" in result.stderr
    assert not dataset.exists()
