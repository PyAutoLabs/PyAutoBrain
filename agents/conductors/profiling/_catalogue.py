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
        if doc.get("schema") != "profiling-summary" or doc.get("version") not in (1, 2):
            raise ValueError("Unsupported published profiling catalogue")
        if "script_routes" not in doc:
            return None
        if doc["version"] != 2:
            raise ValueError("Source routes require profiling-summary v2")
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
