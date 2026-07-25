#!/usr/bin/env python3
"""Read-only scanner for DEAD INTERNAL REFERENCES in workspace prose.

Workspace/HowTo scripts document themselves by pointing at their siblings —
"see the ``modeling/start_here.ipynb`` example", "checkout
``features/extra_galaxies.py``". A restructure moves or renames the target and
the prose keeps pointing at the old name. Nothing catches it: the scripts still
run (Heart stays green), the notebooks still build, only the reader is sent to a
file that no longer exists. This tier is that missing sense.

What is scanned
---------------
The user-facing ``*_workspace`` and ``HowTo*`` repositories (same derivation as
``_hygiene_docstrings.py``: a repo counts once it has a ``scripts/`` directory,
so an un-populated clone is skipped), reading ``scripts/**/*.py`` as whole text
plus the top-level ``README.md``/``README.rst``. Whole-file text rather than an
AST docstring walk is deliberate: these references live in docstrings *and* in
``#`` comments *and* in README prose, and a stray match inside code is filtered
out by the reference patterns below far more cheaply than by tokenizing.

What counts as a reference
--------------------------
Backtick-quoted spans and bare ``scripts/…``/``notebooks/…`` mentions, kept only
when they are unambiguously a file or folder reference:

* ``some/path/name.py`` / ``some/path/name.ipynb`` — a path-qualified file;
* ``name.ipynb`` — a bare notebook name (nothing else in this prose is a
  ``.ipynb``, so bare notebook names stay high-precision);
* ``some/path/`` — a multi-segment folder reference;
* shell globs (``autolens_workspace/*/guides/over_sampling.ipynb``) — the
  workspace's own idiom for "scripts or notebooks", matched as a glob.

How a reference is resolved
---------------------------
Every repo is indexed *canonically*: a leading ``scripts/``/``notebooks/``
segment is dropped and ``.ipynb`` is folded to ``.py``, so the notebook tree and
the script tree that generates it resolve each other (a ``.ipynb`` reference is
satisfied by the matching ``scripts/**/*.py`` and vice versa). A reference
resolves when its canonical form matches an indexed path exactly, as a path
*suffix* (``modeling/start_here.ipynb`` is satisfied by
``imaging/modeling/start_here.py`` — the prose habit of quoting the tail of a
path), or as a glob. Explicit paths are tried against the repo root and against
the referencing file's own directory. A reference prefixed with a sibling repo
name or ``../`` is resolved in that sibling under PYAUTO_ROOT, and one prefixed
with a library package or test-suite name (``autofit/…``, ``test_autolens/…``)
in that library's checkout; when the sibling is not checked out the reference is
skipped, never flagged — this tier
never reports what it could not check.

Suppressions (precision tuning)
-------------------------------
Measured against the real repos, these classes were almost entirely false
positives and are dropped before resolution:

* **Bare ``name.py``** with no path — dominated by module/library names in prose
  (``corner.py``, ``GetDist.py``, ``visualizer.py``, ``profiles.py``) rather
  than workspace files. Cost: a genuinely dead bare script name (a typo'd
  ``proprocess_1_pre_cti.py``) is missed. Bare ``.ipynb`` is kept.
* **Single-segment folder refs** (``image/``, ``channel_NNN/``,
  ``results_folder/``) — these name *output-folder structure* in prose, not repo
  directories.
* **References rooted at a runtime directory** (``output/``, ``dataset/``) —
  written by a run/simulator, so absence proves nothing.
* **Cross-repo references into a repo that is not checked out.**

Known residual false-positive classes (judge, do not auto-fix)
--------------------------------------------------------------
* A reference whose target moved *into a package directory* of the same name
  (``features/extra_galaxies.py`` → ``features/extra_galaxies/modeling.py``) is
  reported: the quoted path is genuinely gone, but the fix is a re-point, not a
  restore.
* A reference written *unqualified* while meaning a sibling repo (a HowTo script
  saying ``scripts/guides/api/data_structures.py`` and meaning the workspace) is
  dead **in the repo that contains it**; the fix is qualification.
* A repo prefix with the wrong case (``autoCTI_workspace/…``) is reported —
  broken as written, cosmetic in impact.

Read-only: this scanner never writes to a scanned repository.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# Backtick-quoted spans, and bare scripts//notebooks/ path mentions.
BACKTICK_REFERENCE = re.compile(r"`([^`\n]{1,200}?)`")
BARE_PATH_REFERENCE = re.compile(
    r"(?<![\w./`-])((?:scripts|notebooks)/[A-Za-z0-9_*][A-Za-z0-9_./*-]*)"
)
# A reference may only contain path characters (a space, quote or bracket means
# it is prose or code, not a path).
PATH_CHARACTERS = re.compile(r"^[A-Za-z0-9_.*/-]+$")
FILE_NAME = re.compile(r"^[A-Za-z0-9_*][A-Za-z0-9_.*-]*\.(?:py|ipynb)$")

# Directory names whose contents are produced by a run, so their absence from a
# checkout proves nothing about the reference.
RUNTIME_DIRECTORIES = frozenset({"output", "outputs", "dataset", "datasets"})
# Directories never worth walking when indexing a repository.
PRUNED_DIRECTORIES = frozenset({".git", ".ipynb_checkpoints", "__pycache__"})
# Library package (or its test suite) -> the repository whose checkout holds it.
LIBRARY_REPOSITORIES = {
    package: repository
    for package, repository in (
        ("autonerves", "PyAutoNerves"),
        ("autofit", "PyAutoFit"),
        ("autoarray", "PyAutoArray"),
        ("autogalaxy", "PyAutoGalaxy"),
        ("autolens", "PyAutoLens"),
        ("autocti", "PyAutoCTI"),
    )
    for package in (package, f"test_{package}")
}


@dataclass(frozen=True)
class Finding:
    repo: str
    file: str
    line: int
    reference: str


def canonical(path: str) -> str:
    """Fold a path onto the shared scripts/notebooks namespace."""
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if len(parts) > 1 and parts[0] in ("scripts", "notebooks"):
        parts = parts[1:]
    folded = "/".join(parts)
    if folded.endswith(".ipynb"):
        folded = folded[: -len(".ipynb")] + ".py"
    return folded


class RepositoryIndex:
    """Canonical file and directory index of one checked-out repository."""

    def __init__(self, path: Path):
        self.path = path
        files: set[str] = set()
        directories: set[str] = set()
        for parent, child_directories, child_files in os.walk(path):
            child_directories[:] = [
                name for name in child_directories if name not in PRUNED_DIRECTORIES
            ]
            base = Path(parent).relative_to(path).as_posix()
            prefix = "" if base == "." else f"{base}/"
            for name in child_directories:
                directories.add(f"{prefix}{name}")
            for name in child_files:
                files.add(f"{prefix}{name}")
        self.files = files | {canonical(name) for name in files}
        self.directories = directories | {canonical(name) for name in directories}

    @staticmethod
    def _matches(pool: set[str], key: str) -> bool:
        if not key:
            return False
        if "*" in key or "?" in key:
            return any(
                fnmatch.fnmatch(entry, key) or fnmatch.fnmatch(entry, f"*/{key}")
                for entry in pool
            )
        return key in pool or any(entry.endswith(f"/{key}") for entry in pool)

    def has_file(self, reference: str) -> bool:
        return self._matches(self.files, canonical(reference))

    def has_directory(self, reference: str) -> bool:
        return self._matches(self.directories, canonical(reference.rstrip("/")))


def is_reference(text: str) -> bool:
    """Return whether a quoted span is a file/folder reference worth resolving."""
    if not text or not PATH_CHARACTERS.match(text):
        return False
    if text.endswith("/"):
        # Multi-segment only: a lone `image/` names output structure, not a repo
        # directory (measured: that class is entirely false positives).
        return "/" in text.rstrip("/")
    name = text.rsplit("/", 1)[-1]
    if not FILE_NAME.match(name):
        return False
    # Bare `name.py` is dominated by module/library names in prose; bare
    # `name.ipynb` is unambiguously a workspace notebook.
    return "/" in text or name.endswith(".ipynb")


def line_numbers(text: str) -> list[int]:
    """Return the character offset at which each line starts."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets[:-1] or [0]


def line_of(offsets: list[int], position: int) -> int:
    low, high = 0, len(offsets) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if offsets[middle] <= position:
            low = middle
        else:
            high = middle - 1
    return low + 1


def repository_paths(root: Path) -> list[Path]:
    """Return user-facing ``*_workspace`` and ``HowTo*`` repositories."""
    candidates = [*root.glob("*_workspace"), *root.glob("HowTo*")]
    return sorted(
        {path.resolve() for path in candidates if (path / "scripts").is_dir()},
        key=lambda path: path.name.lower(),
    )


def scanned_files(repository: Path) -> list[Path]:
    paths = sorted((repository / "scripts").rglob("*.py"))
    paths += [
        repository / name
        for name in ("README.md", "README.rst")
        if (repository / name).is_file()
    ]
    return paths


class Resolver:
    """Resolve references against the repositories checked out under a root."""

    def __init__(self, root: Path):
        self.root = root
        self.indexes: dict[str, RepositoryIndex] = {}
        self.siblings = {path.name for path in root.iterdir() if path.is_dir()}
        self.suppressed = 0

    def index(self, name: str) -> RepositoryIndex | None:
        if name not in self.indexes:
            path = self.root / name
            if not path.is_dir():
                return None
            self.indexes[name] = RepositoryIndex(path)
        return self.indexes[name]

    def resolves(self, reference: str, repo: str, directory: str) -> bool | None:
        """True/False for a checkable reference; None when it cannot be checked."""
        target = self.index(repo)
        if target is None:
            return None
        path = reference.lstrip("./")
        while path.startswith("../"):
            path = path[3:]
        head = path.split("/", 1)[0]
        if head in RUNTIME_DIRECTORIES:
            return None
        if "/" in path:
            if head in LIBRARY_REPOSITORIES:
                target = self.index(LIBRARY_REPOSITORIES[head])
                directory = ""
            elif head == repo:
                path = path.split("/", 1)[1]
                directory = ""
            elif head in self.siblings:
                target = self.index(head)
                path = path.split("/", 1)[1]
                directory = ""
            if target is None:
                return None
            # Re-check runtime roots AFTER a repo prefix strip: a sibling-
            # qualified `autolens_workspace/dataset/...` is just as
            # unresolvable-by-absence as a bare `dataset/...` (the folder is
            # written at runtime), and checking only the pre-strip head let
            # these through as false positives.
            if path.split("/", 1)[0] in RUNTIME_DIRECTORIES:
                return None
        check = target.has_directory if path.endswith("/") else target.has_file
        return bool(check(path) or (directory and check(f"{directory}/{path}")))


def findings_in_file(
    resolver: Resolver, repository: Path, path: Path
) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    relative = path.relative_to(repository).as_posix()
    folded = canonical(relative)
    directory = folded.rsplit("/", 1)[0] if "/" in folded else ""
    offsets = line_numbers(text)

    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    matches = [*BACKTICK_REFERENCE.finditer(text), *BARE_PATH_REFERENCE.finditer(text)]
    for match in sorted(matches, key=lambda item: item.start()):
        reference = match.group(1).strip()
        line = line_of(offsets, match.start())
        if (line, reference) in seen or not is_reference(reference):
            continue
        seen.add((line, reference))
        resolved = resolver.resolves(reference, repository.name, directory)
        if resolved is None:
            resolver.suppressed += 1
        elif not resolved:
            findings.append(
                Finding(
                    repo=repository.name,
                    file=relative,
                    line=line,
                    reference=reference,
                )
            )
    return findings


def scan(root: Path) -> tuple[list[Finding], int, int]:
    resolver = Resolver(root)
    repositories = repository_paths(root)
    findings: list[Finding] = []
    for repository in repositories:
        resolver.indexes.setdefault(repository.name, RepositoryIndex(repository))
        for path in scanned_files(repository):
            findings.extend(findings_in_file(resolver, repository, path))
    return findings, len(repositories), resolver.suppressed


def summary_for(findings: list[Finding], repository_count: int, skipped: int) -> str:
    file_count = len({(finding.repo, finding.file) for finding in findings})
    affected = len({finding.repo for finding in findings})
    file_label = "file" if file_count == 1 else "files"
    return (
        f"{len(findings)} dead internal references in {file_count} {file_label} "
        f"across {affected}/{repository_count} repos; "
        f"{skipped} unresolvable refs skipped"
    )


def row_for(root: Path) -> dict:
    findings, repository_count, skipped = scan(root)
    return {
        "mode": "refs",
        "kind": "finding",
        "status": "finding" if findings else "clean",
        "count": len(findings),
        "summary": summary_for(findings, repository_count, skipped),
        "delegate": "/refactor",
        "findings": [asdict(finding) for finding in findings],
    }


def render_human(row: dict) -> None:
    print(row["summary"])
    repo = None
    for finding in row["findings"]:
        if finding["repo"] != repo:
            repo = finding["repo"]
            print(f"  {repo}:")
        print(f"    {finding['file']}:{finding['line']} -> {finding['reference']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json-row", action="store_true")
    output.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    row = row_for(args.root.resolve())
    if args.json_row:
        print(json.dumps(row, sort_keys=True))
    elif args.summary:
        print(f"{row['count']}|{row['summary']}")
    else:
        render_human(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
