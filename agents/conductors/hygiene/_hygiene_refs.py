#!/usr/bin/env python3
"""Read-only scanner for FOLDER-LIST DRIFT in workspace prose.

Two directions of the same defect, scanned together:

* **dead references** — prose names a file or folder that no longer exists;
* **undocumented folders** — a folder exists that its own parent README never
  names (see ``documented_directories``).

The rest of this docstring describes the dead-reference direction, which is the
older and more intricate of the two.

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
plus every ``scripts/**/README.md``, every ``config/**/README.md``, and the
top-level ``README.md``/``README.rst``. Whole-file text rather than an AST
docstring walk is deliberate: these references live in docstrings *and* in
``#`` comments *and* in README prose, and a stray match inside code is filtered
out by the reference patterns below far more cheaply than by tokenizing.

The nested READMEs matter because each package documents its own contents there,
so a restructure leaves a folder list describing the *old* shape while every
script still runs — the exact blind spot that let ``autolens_workspace``'s root
README advertise a ``slam_pipeline/`` directory long after it was gone.

What counts as a reference
--------------------------
Backtick-quoted spans and bare ``scripts/…``/``notebooks/…`` mentions, kept only
when they are unambiguously a file or folder reference:

* ``some/path/name.py`` / ``some/path/name.ipynb`` — a path-qualified file;
* ``name.ipynb`` — a bare notebook name (nothing else in this prose is a
  ``.ipynb``, so bare notebook names stay high-precision);
* ``some/path/`` — a multi-segment folder reference;
* ``some/path`` — a multi-segment folder reference written *without* the
  trailing slash, the dominant README idiom (``data_preparation/imaging``). Only
  trusted when the repo index confirms one end names something real, so prose
  that merely contains a slash (``bulge/disk``) is skipped, not flagged;
* ``config/priors/light.yaml`` — a path-qualified ``.yaml``/``.rst`` file;
* ``- `name`: what it holds`` — a **structure-list bullet**, the one idiom in
  which a bare backticked word is reliably a path. See the calibration note
  below, which is what keeps this rule from firing on parameter glossaries;
* shell globs (``autolens_workspace/*/guides/over_sampling.ipynb``) — the
  workspace's own idiom for "scripts or notebooks", matched as a glob.

Structure-list calibration
--------------------------
A markdown bullet list may enumerate folders *or* describe parameters, and a bare
word alone cannot distinguish them. The list itself is the evidence: an
extension-less bullet name is only trusted when at least ``STRUCTURE_LIST_QUORUM``
names in the same contiguous block resolve, so a folder list with one stale entry
reports it while a glossary — where nothing resolves — is skipped whole. Names
carrying a file extension (``.yaml``/``.yml``/``.rst``/``.ipynb``) are
unambiguous and bypass the quorum, which is what catches a ``config/`` README
still inventorying deleted YAML.

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
* A **dataset** path written without its ``dataset/`` prefix
  (``autolens_workspace/imaging/multi/simple__no_lens_light``) is reported: the
  runtime-directory suppression keys off the prefix, and without it the path is
  genuinely wrong as written. The fix is qualification, not a restore.
* An extension-less pair whose *tail* happens to name a real directory
  (``light/mass``, where ``mass/`` exists under ``config/priors/``) can survive
  the anchoring guard. Rare, and judged like any other finding.

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
# Path-qualified config/doc files (`config/priors/light.yaml`). Only meaningful
# when the token carries a directory, so a bare `general.yaml` in prose is not
# swept up here — the structure-list rule below owns that case.
QUALIFIED_FILE_NAME = re.compile(r"^[A-Za-z0-9_*][A-Za-z0-9_.*-]*\.(?:ya?ml|rst)$")

# A workspace structure list: ``- `name`: what it holds``. This bullet idiom is
# how every workspace README documents its own folders, and it is the only place
# a *bare* backticked word is reliably a path rather than prose, so the rule is
# confined to it.
STRUCTURE_BULLET = re.compile(r"^[ \t]*[-*][ \t]+`([^`\n]+)`[ \t]*:", re.MULTILINE)
BARE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
# Extensions that make a bare structure-list name unambiguously a file (nothing
# else in this prose is a `.yaml`), so they bypass the calibration below.
BULLET_FILE_SUFFIXES = (".yaml", ".yml", ".rst", ".ipynb")
# A bullet block is treated as a *structure* list only when at least this many
# of its extension-less names resolve. See `structure_findings`.
STRUCTURE_LIST_QUORUM = 2

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
    kind: str = "dead"


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
    # An absolute path names a filesystem outside the repo (an HPC scratch
    # directory, a mount point) and can never be resolved against a checkout.
    if text.startswith("/"):
        return False
    if text.endswith("/"):
        # Multi-segment only: a lone `image/` names output structure, not a repo
        # directory (measured: that class is entirely false positives).
        return "/" in text.rstrip("/")
    name = text.rsplit("/", 1)[-1]
    if not FILE_NAME.match(name):
        if "/" not in text:
            return False
        # A path-qualified config/doc file (`config/priors/light.yaml`).
        if QUALIFIED_FILE_NAME.match(name):
            return True
        # A multi-segment token whose last segment carries no extension is a
        # directory reference written *without* a trailing slash — the dominant
        # README idiom (`data_preparation/imaging`). Prose that merely contains a
        # slash (`bulge/disk`) is filtered at resolution time by `_is_anchored`,
        # which checks the reference against the repo index.
        return "." not in name
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
    # Nested README.md files carry the bulk of the folder-structure prose: each
    # package documents its own contents, and a restructure leaves those lists
    # pointing at the old shape. ``config/`` READMEs inventory the shipped YAML
    # the same way.
    paths += sorted((repository / "scripts").rglob("README.md"))
    configuration = repository / "config"
    if configuration.is_dir():
        paths += sorted(configuration.rglob("README.md"))
    paths += [
        repository / name
        for name in ("README.md", "README.rst")
        if (repository / name).is_file()
    ]
    return paths


def _is_anchored(target: "RepositoryIndex", path: str) -> bool:
    """Whether an extension-less multi-segment token looks like a real path.

    Prose uses a slash as shorthand too ("bulge/disk", "light/mass"), and those
    must not be reported as dead paths. A genuine reference almost always has at
    least one end matching something real — either the leading directory
    (``data_preparation/imaging``) or, when the *head* is what drifted, the tail
    (``sdvanced/modeling``, ``guide/advanced``, where a typo'd first segment is
    the whole finding). Requiring both would miss precisely those.
    """
    head, tail = path.split("/", 1)[0], path.rsplit("/", 1)[-1]
    return bool(
        target.has_directory(head)
        or target.has_directory(tail)
        or target.has_file(f"{tail}.py")
    )


def _resolves_extensionless(
    target: "RepositoryIndex", path: str, directory: str
) -> bool:
    """Resolve a reference carrying no file extension.

    It may name a folder, or a file whose extension the prose dropped — the
    workspace habit of writing "see ``features/pixelization/modeling``". The
    index is canonical (``.ipynb`` folded to ``.py``), so ``.py`` is the only
    suffix worth trying.
    """
    candidates = [path]
    if directory:
        candidates.append(f"{directory}/{path}")
    return any(
        target.has_directory(candidate)
        or target.has_file(candidate)
        or target.has_file(f"{candidate}.py")
        for candidate in candidates
    )


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
        # Strip leading `./` and `../` as *prefixes*. `lstrip("./")` would strip
        # the character set, silently mangling every reference to a dot-directory
        # (`.claude/skills` -> `claude/skills`, `.github/workflows` ->
        # `github/workflows`) and then reporting it as dead.
        path = reference
        while True:
            if path.startswith("../"):
                path = path[3:]
            elif path.startswith("./"):
                path = path[2:]
            else:
                break
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
        if path.endswith("/"):
            check = target.has_directory
            return bool(check(path) or (directory and check(f"{directory}/{path}")))
        if "." in path.rsplit("/", 1)[-1]:
            check = target.has_file
            return bool(check(path) or (directory and check(f"{directory}/{path}")))
        # Extension-less: either a folder, or a file whose extension the prose
        # dropped ("see features/pixelization/modeling").
        if "/" in path and not _is_anchored(target, path):
            # Guard against prose that merely contains a slash ("bulge/disk"):
            # at least one end must name something real. Reported as
            # unresolvable rather than dead — never flag a guess.
            return None
        return _resolves_extensionless(target, path, directory)

    def resolves_name(self, name: str, repo: str, directory: str) -> bool | None:
        """Resolve a bare structure-list name as either a folder or a file."""
        target = self.index(repo)
        if target is None:
            return None
        if name in RUNTIME_DIRECTORIES:
            return None
        if "." in name:
            return bool(
                target.has_file(name)
                or (directory and target.has_file(f"{directory}/{name}"))
            )
        return _resolves_extensionless(target, name, directory)


def bullet_blocks(text: str, offsets: list[int]) -> list[list[tuple[int, str]]]:
    """Group ``- `name`: …`` bullets into contiguous lists.

    Bullets more than three lines apart belong to different lists (a heading or
    a paragraph separates them); a wrapped bullet keeps its list intact.
    """
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    previous = None
    for match in STRUCTURE_BULLET.finditer(text):
        line = line_of(offsets, match.start())
        if previous is not None and line - previous > 3:
            blocks.append(current)
            current = []
        current.append((line, match.group(1).strip()))
        previous = line
    if current:
        blocks.append(current)
    return blocks


def structure_findings(
    resolver: Resolver, repo: str, directory: str, text: str, offsets: list[int]
) -> list[tuple[int, str]]:
    """Dead references among a markdown file's structure-list bullets.

    A bare backticked word is only a path in this one idiom, and even here a
    bullet list may describe parameters rather than folders. The list itself is
    the calibration: extension-less names are trusted only when at least
    ``STRUCTURE_LIST_QUORUM`` of that block's names actually resolve, so a
    parameter glossary (where none resolve) is skipped whole. Names carrying a
    file extension are unambiguous and bypass the quorum — which is what catches
    a config README still inventorying deleted YAML.
    """
    findings: list[tuple[int, str]] = []
    for block in bullet_blocks(text, offsets):
        named = [(line, name) for line, name in block if BARE_NAME.match(name)]
        resolved, unresolved = [], []
        for line, name in named:
            if name.endswith(BULLET_FILE_SUFFIXES):
                if resolver.resolves_name(name, repo, directory) is False:
                    findings.append((line, name))
                continue
            state = resolver.resolves_name(name, repo, directory)
            if state is None:
                continue
            (resolved if state else unresolved).append((line, name))
        if len(resolved) >= STRUCTURE_LIST_QUORUM:
            findings.extend(unresolved)
    return findings


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

    if path.suffix == ".md":
        for line, name in structure_findings(
            resolver, repository.name, directory, text, offsets
        ):
            if (line, name) in seen:
                continue
            seen.add((line, name))
            findings.append(
                Finding(
                    repo=repository.name, file=relative, line=line, reference=name
                )
            )
    return sorted(findings, key=lambda finding: (finding.line, finding.reference))


def documented_directories(repository: Path) -> list[Finding]:
    """Report example folders that their own parent README never mentions.

    The inverse of the dead-reference scan above: that one starts from prose and
    asks whether the target exists, this one starts from what exists and asks
    whether any prose names it. Both directions are the same defect seen from
    two ends — a folder list that has drifted from the tree — but they fail
    apart. A package added without touching its parent README leaves every
    reference resolving perfectly while the folder is invisible to a reader
    browsing the list. ``interferometer/features/datacube`` sat unlisted that
    way for three months (autolens_workspace#482), and the audit that found it
    turned up thirteen more in the same repo.

    Precision comes from the direction of travel: the candidates are real
    directories read off the filesystem, so the "is this token a path or a
    parameter name?" ambiguity that constrains the structure-list rule above
    cannot arise here, and no quorum heuristic is needed. The mention test is
    deliberately permissive in the other axis — a bare word-boundary search of
    the whole README — so bold bullets (``- **`name`**``), trailing slashes
    (``- `name/```) and plain prose all count as documenting the folder. Only a
    folder named *nowhere at all* is reported.

    A directory is a candidate only if it carries example content (a script,
    notebook, or its own README); asset and output directories are skipped.
    """
    findings: list[Finding] = []
    scripts = repository / "scripts"
    if not scripts.is_dir():
        return findings
    for readme in sorted(scripts.rglob("README.md")):
        try:
            text = readme.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for child in sorted(readme.parent.iterdir()):
            if not child.is_dir() or child.name in PRUNED_DIRECTORIES:
                continue
            if child.name.startswith((".", "__")):
                continue
            has_content = any(
                any(child.rglob(pattern))
                for pattern in ("*.py", "*.ipynb", "README.md")
            )
            if not has_content:
                continue
            if re.search(rf"\b{re.escape(child.name)}\b", text):
                continue
            findings.append(
                Finding(
                    repo=repository.name,
                    file=readme.relative_to(repository).as_posix(),
                    line=1,
                    reference=f"{child.name}/ (folder exists, README never names it)",
                    kind="orphan",
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
        findings.extend(documented_directories(repository))
    return findings, len(repositories), resolver.suppressed


def summary_for(findings: list[Finding], repository_count: int, skipped: int) -> str:
    file_count = len({(finding.repo, finding.file) for finding in findings})
    affected = len({finding.repo for finding in findings})
    file_label = "file" if file_count == 1 else "files"
    dead = sum(1 for finding in findings if finding.kind == "dead")
    orphans = sum(1 for finding in findings if finding.kind == "orphan")
    return (
        f"{len(findings)} folder-list defects ({dead} dead references, "
        f"{orphans} undocumented folders) in {file_count} {file_label} "
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
        arrow = "!!" if finding.get("kind") == "orphan" else "->"
        print(f"    {finding['file']}:{finding['line']} {arrow} {finding['reference']}")


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
