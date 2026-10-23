"""Read project-owned source routing without importing scientific modules."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

_TOKEN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]*\Z")


def _token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"Invalid profiling identity: {value!r}")
    return value


def _path(value):
    if not isinstance(value, str) or "\\" in value:
        raise ValueError("Invalid profiling source path")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or ".." in path.parts
            or len(path.parts) < 3 or path.parts[0] != "scripts" or path.suffix != ".py"
            or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in path.parts)):
        raise ValueError(f"Unsafe profiling source path: {value!r}")
    return value


def read_catalogue(ws: Path):
    """Local manifest first, then published v2 extension; None means pre-migration.

    A present but invalid new producer never falls back to executable-source AST.
    File digests identify the routing bytes read, not a measurement revision.
    """
    local = ws / "catalogue/script_routes.json"
    published = ws / "dashboard/catalogue.json"
    source = local if local.is_file() else published
    if not source.is_file():
        return None
    raw = source.read_bytes()
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Unreadable profiling catalogue: {source.relative_to(ws)}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Profiling catalogue must be an object")
    if source == published:
        if doc.get("schema") != "profiling-summary" or doc.get("version") not in (1, 2, 3):
            raise ValueError("Unsupported published profiling catalogue")
        if "script_routes" not in doc:
            return None
        if doc["version"] not in (2, 3):
            raise ValueError("Source routes require profiling-summary v2 or v3")
        doc = doc["script_routes"]
    if not isinstance(doc, dict) or doc.get("schema") != "profiling-script-routes" or doc.get("version") != 1:
        raise ValueError("Unsupported profiling script routes schema/version")
    entries = doc.get("routes")
    cells = doc.get("runtime_cells")
    if not isinstance(entries, list) or not isinstance(cells, list) or not cells:
        raise ValueError("Profiling routes and nonempty runtime_cells are required")
    paths = set()
    route_by_path = {}
    aliases = set()
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("Invalid profiling route entry")
        path, legacy = _path(row.get("path")), _path(row.get("legacy"))
        if path in paths or legacy in aliases:
            raise ValueError("Duplicate profiling source route")
        dataset = _token(row.get("dataset"))
        model = _token(row.get("model"))
        measurement = row.get("measurement")
        _token(measurement[1:] if isinstance(measurement, str) and measurement.startswith("_") else measurement)
        if path != f"scripts/{dataset}/{model}/{row['measurement']}.py":
            raise ValueError("Route identity does not match its source path")
        route_by_path[path] = row
        paths.add(path)
        aliases.add(legacy)
    grid = []
    seen = set()
    for row in cells:
        if not isinstance(row, dict):
            raise ValueError("Invalid runtime cell")
        dataset, model = _token(row.get("dataset")), _token(row.get("model"))
        instruments = row.get("instruments")
        if not isinstance(instruments, list):
            raise ValueError("Runtime instruments must be a list")
        instruments = tuple(_token(value) for value in instruments)
        if len(set(instruments)) != len(instruments) or (dataset, model) in seen:
            raise ValueError("Duplicate runtime cell or instrument")
        if _path(row.get("path")) not in paths:
            raise ValueError("Runtime cell refers to an undeclared source route")
        route = route_by_path[row["path"]]
        if dataset != route["dataset"] or model not in (route["model"], PurePosixPath(route["legacy"]).stem):
            raise ValueError("Runtime cell identity does not match its source route")
        seen.add((dataset, model))
        grid.append((dataset, model, instruments))
    probe = doc.get("compile_probe")
    if probe is not None:
        if not isinstance(probe, dict):
            raise ValueError("Invalid compile probe declaration")
        paths.add(_path(probe.get("path")))
        if probe.get("builder_status") not in ("available", "unavailable", "unknown"):
            raise ValueError("Unknown compile builder status")
        transforms = probe.get("transforms")
        if not isinstance(transforms, list) or not transforms:
            raise ValueError("Compile transforms must be a nonempty list")
        for value in transforms:
            _token(value)
        if len(set(transforms)) != len(transforms):
            raise ValueError("Duplicate compile transform")
    return {
        "grid": grid,
        "source": source.relative_to(ws).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "version": 1,
        "runtime_cells": cells,
        "compile_probe": probe,
        "missing_sources": sorted(path for path in paths if not (ws / path).is_file()),
    }


# ---------------------------------------------------------------------------
# profiling-summary@3: the lifecycle catalogue (PyAutoPulse REFERENCE.md)
# ---------------------------------------------------------------------------
#
# The vocabulary below mirrors the Pulse contract's enumerations for the fields
# the conductor reads. Pulse validates the whole document; the conductor only
# refuses what it cannot place on its coverage grid. It REPORTS the producer's
# `class` and `status` and never assigns either.

SETUP_ID_GRAMMAR = "<backend>_<device>_<operator>_<precision>[_<transformer>]"
SETUP_BACKENDS = ("numba", "jax")
SETUP_DEVICES = ("cpu", "gpu")
SETUP_OPERATORS = ("dense", "sparse", "na")
SETUP_PRECISIONS = ("fp64", "mixed")
# `na` is the absence of a transformer and is never spelled in a setup_id.
SETUP_TRANSFORMERS = ("dft", "nufft", "wtilde", "streaming")
DATASET_TYPES = ("imaging", "interferometer", "datacube", "point_source_image",
                 "point_source_source", "multi_galaxy", "group", "cluster",
                 "multi_dataset", "weak")
CLASSES = ("optimal", "secondary", "experimental")
# `archived` records leave `records[]` (counted in `archive_record_count`).
STATUSES = ("current", "superseded")
# Host classes with this prefix never qualify as `current` (reference-host rule).
LOCAL_HOST_PREFIX = "local_"
LIFECYCLE_SOURCE = "dashboard/catalogue.json"


class SetupIdError(ValueError):
    """A `setup_id` that does not follow the canonical grammar."""

    def __init__(self, value, where=""):
        place = f" in {where}" if where else ""
        super().__init__(f"SetupIdError: {value!r}{place} does not match {SETUP_ID_GRAMMAR}")


def parse_setup_id(value, where=""):
    """`setup_id` -> {backend, device, operator, precision, transformer}.

    Refuses anything off the grammar with `SetupIdError`, including an explicit
    `_na` transformer (the canonical form omits it)."""
    parts = value.split("_") if isinstance(value, str) else []
    if len(parts) not in (4, 5):
        raise SetupIdError(value, where)
    backend, device, operator, precision = parts[:4]
    transformer = parts[4] if len(parts) == 5 else "na"
    if (backend not in SETUP_BACKENDS or device not in SETUP_DEVICES
            or operator not in SETUP_OPERATORS or precision not in SETUP_PRECISIONS
            or (len(parts) == 5 and transformer not in SETUP_TRANSFORMERS)):
        raise SetupIdError(value, where)
    return {"backend": backend, "device": device, "operator": operator,
            "precision": precision, "transformer": transformer}


def is_local_host(host_class):
    return isinstance(host_class, str) and host_class.startswith(LOCAL_HOST_PREFIX)


def pin_order(pin):
    """Sortable form of a release pin (`2026.10.16.2`); None when unparsable."""
    if not isinstance(pin, str):
        return None
    try:
        return tuple(int(part) for part in pin.split("."))
    except ValueError:
        return None


def lifecycle_key(row, where):
    """(dataset_type, variant, instrument, setup_id, host_class, model_variant,
    measurement) — the Pulse one-current-per-key identity."""
    likelihood = row.get("likelihood")
    if not isinstance(likelihood, dict):
        raise ValueError(f"Lifecycle row without a likelihood: {where}")
    dataset_type = _token(likelihood.get("dataset_type"))
    if dataset_type not in DATASET_TYPES:
        raise ValueError(f"Unknown dataset_type {dataset_type!r}: {where}")
    setup_id = row.get("setup_id")
    setup = parse_setup_id(setup_id, where)
    declared = row.get("setup")
    if isinstance(declared, dict) and any(
            declared.get(field, setup[field]) != setup[field] for field in setup):
        raise ValueError(f"setup does not match setup_id {setup_id!r}: {where}")
    return (dataset_type, _token(likelihood.get("variant")), _token(row.get("instrument")),
            setup_id, _token(row.get("host_class")), _token(row.get("model_variant")),
            _token(row.get("measurement")))


def read_lifecycle(ws: Path):
    """The published `profiling-summary@3` catalogue, or None (v1/v2/absent).

    None keeps every caller on its pre-lifecycle path unchanged; an unreadable
    published file is left to `read_catalogue`, which already owns that error.
    A v3 document the grid cannot place is refused, never half-read.
    """
    source = ws / LIFECYCLE_SOURCE
    if not source.is_file():
        return None
    raw = source.read_bytes()
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(doc, dict) or doc.get("schema") != "profiling-summary" or doc.get("version") != 3:
        return None
    records, planned = doc.get("records"), doc.get("planned_cells", [])
    if not isinstance(records, list) or not isinstance(planned, list):
        raise ValueError("profiling-summary@3 records and planned_cells must be lists")
    rows = []
    for index, record in enumerate(records):
        where = f"records[{index}]"
        if not isinstance(record, dict):
            raise ValueError(f"Invalid lifecycle record: {where}")
        key = lifecycle_key(record, where)
        if record.get("class") not in CLASSES:
            raise ValueError(f"Unknown class {record.get('class')!r}: {where}")
        if record.get("status") not in STATUSES:
            raise ValueError(f"Status {record.get('status')!r} cannot be in records[]: {where}")
        rows.append({"id": str(record.get("id", where)), "key": key, "class": record["class"],
                     "status": record["status"], "release_pin": record.get("release_pin")})
    cells = {}
    for index, cell in enumerate(planned):
        where = f"planned_cells[{index}]"
        if not isinstance(cell, dict):
            raise ValueError(f"Invalid planned cell: {where}")
        key = lifecycle_key(cell, where)
        if cell.get("class") not in CLASSES:
            raise ValueError(f"Unknown class {cell.get('class')!r}: {where}")
        if key in cells:
            raise ValueError(f"Duplicate planned cell: {where}")
        cells[key] = cell["class"]
    # The pin a current record is judged against: the envelope's own when it
    # declares one, else the newest pin the catalogue's records carry.
    pin, pin_source = doc.get("release_pin"), "envelope"
    if pin_order(pin) is None:
        pins = [r["release_pin"] for r in rows if pin_order(r["release_pin"]) is not None]
        pin, pin_source = (max(pins, key=pin_order), "newest record") if pins else (None, None)
    return {
        "source": LIFECYCLE_SOURCE,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "version": 3,
        "release_pin": pin,
        "release_pin_source": pin_source,
        "archive_record_count": doc.get("archive_record_count"),
        "records": rows,
        "planned": cells,
    }
