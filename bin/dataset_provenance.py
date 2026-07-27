#!/usr/bin/env python3
"""dataset_provenance.py — classify workspace datasets by WRITE SITE.

`clean_slate.sh` must decide, for each *untracked* ``dataset/<type>/<name>``
directory, whether deleting it is free (a script regenerates it) or expensive
(it is real data that was downloaded, or nobody knows where it came from).

Every workspace ignores ``dataset/`` wholesale and force-adds the real datasets
back, so "untracked" does NOT mean "regenerable". Nor is a name mention enough:
``scripts/interferometer/start_here.py`` names ``sdp81`` (real ALMA data it only
*reads*) three lines apart from the path of ``simulated_lens`` (which it
*writes*). A grep for the dataset name cannot tell those two apart — this helper
exists because that distinction has to be made on data flow, not text.

__The rule: a dataset is regenerable only if a script demonstrably writes it__

For each candidate ``dataset/<type>/<name>`` we scan every ``scripts/**/*.py``
plus the repo's root-level ``*.py`` with ``ast`` and look for a *write site*:

 1. **Path binding** — an assignment whose right-hand side is a path expression
    resolving to the components ``dataset`` / ``<type>`` / ``<name>``. String
    variables are resolved in source order, so ``dataset_type = "imaging"``,
    ``dataset_name = "simple"``, ``dataset_path = Path("dataset", dataset_type,
    dataset_name)`` resolves, as do ``Path("dataset") / t / n`` and
    ``path.join("dataset", t, n)``.
 2. **Flow into a write call** — that bound variable (or a path derived from it,
    ``uv_path = dataset_path / "uv.fits"``) appears in the arguments of a call
    that writes: ``output_to_fits``, ``fits_imaging``, ``json.dump``,
    ``open(..., "w")``, … (see ``WRITE_FUNCS``), or is passed to a helper
    function in the same repo whose own body writes that parameter (one level of
    interprocedural resolution — the ``simulators/util.py`` idiom).

The analysis is **order sensitive**, which is the whole point: ``dataset_path``
is rebound several times in one ``start_here.py``, and only the binding live at
the write call is credited.

__Verdicts__

``DOWNLOADED``    the binding file also fetches over the network (urllib /
                  requests). Real data, cached not redistributed — deleting it
                  costs a large re-download. Wins over any write evidence.
``REGENERABLE``   positive write evidence, no network. Free to delete.
``ORPHAN``        no writer found. Kept, and reported so a human can look.

Deletion requires positive evidence; every uncertainty resolves to ORPHAN.

Usage:
    dataset_provenance.py --repo <repo_root> dataset/<type>/<name> ...
Prints one ``VERDICT <path>`` line per candidate on stdout, and
``WARN unparseable <file>`` lines on stderr for scripts that do not parse.
"""

import argparse
import ast
import sys
import warnings
from pathlib import Path

# Calls that put bytes on disk. Kept explicit rather than pattern-matched: every
# name added here makes the sweep delete more, so each one is a deliberate call.
# Deliberately absent: `aplt.fits_array`, which writes a single auxiliary array
# (a `mask_extra_galaxies.fits`) into a dataset folder. Real datasets get those
# dropped into them by their own `start_here.py` — writing one product is not
# evidence that the script generates the dataset.
WRITE_FUNCS = {
    "output_to_fits",
    "output_to_json",
    "output_to_csv",
    "fits_imaging",
    "fits_interferometer",
    "numpy_array_to_json",
    "to_fits",
    "savetxt",
    "to_csv",
    "dump",
}

# Calls that pull bytes off the network.
NETWORK_FUNCS = {"urlretrieve", "urlopen"}
NETWORK_DOTTED = {"requests.get", "requests.urlretrieve", "requests.post"}
NETWORK_MODULES = {"urllib", "requests"}

# Call names whose positional arguments are path components.
PATH_CALLS = {"Path", "PurePath", "PosixPath", "WindowsPath", "join"}

# `open(path, mode)` counts as a write only for writing modes.
WRITE_MODES = ("w", "a", "x")


def _func_name(node):
    """Trailing name of a call target: `pkg.mod.write` -> `write`, `f` -> `f`."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _dotted_name(node):
    """Full dotted call target where it is a plain attribute chain, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _const_str(node):
    """The string value of a constant or all-constant f-string, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out.append(value.value)
            else:
                return None
        return "".join(out)
    return None


def _is_path_shaped(node):
    """True for `a / b` and `Path(...)` / `path.join(...)` expressions.

    Derived bindings are followed only through these forms. Without the guard,
    `dataset = al.Imaging.from_fits(data_path=dataset_path / "data.fits")` would
    make the *loaded dataset object* carry the real dataset's identity into the
    next `fits_imaging(dataset=dataset, ...)` call, i.e. a read would be
    laundered into a write.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    return isinstance(node, ast.Call) and _func_name(node.func) in PATH_CALLS


def _is_write_call(node, name):
    if name in WRITE_FUNCS:
        return True
    if name != "open":
        return False
    mode = None
    if len(node.args) > 1:
        mode = _const_str(node.args[1])
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = _const_str(keyword.value)
    return bool(mode) and mode[0] in WRITE_MODES


def _is_network_call(node, name):
    if name in NETWORK_FUNCS:
        return True
    dotted = _dotted_name(node.func)
    return dotted in NETWORK_DOTTED


class _Flow:
    """Order-sensitive forward scan of one module (or one function body).

    `paths` maps a variable name to the set of opaque keys it currently refers
    to. In the module pass a key is a `(type, name)` candidate; in the
    helper-function pass it is a `("param", <name>)` marker, so the same
    machinery reports which parameters a helper writes.
    """

    def __init__(self, candidates, helpers=None, initial_paths=None):
        self.candidates = candidates
        self.helpers = helpers or {}
        self.strs = {}
        self.paths = dict(initial_paths or {})
        self.written = set()
        self.network_keys = set()
        self.bound = set()
        self.uses_network = False

    # -- resolution -------------------------------------------------------

    def _components(self, node):
        """Path components of an expression; unresolvable pieces become None."""
        text = _const_str(node)
        if text is not None:
            return [part for part in text.split("/") if part]
        if isinstance(node, ast.Name):
            value = self.strs.get(node.id)
            return [part for part in value.split("/") if part] if value else [None]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self._components(node.left) + self._components(node.right)
        if isinstance(node, ast.Call) and _func_name(node.func) in PATH_CALLS:
            out = []
            for arg in node.args:
                out.extend(self._components(arg))
            return out
        return [None]

    def _candidate_of(self, node):
        """The candidate a path expression names, else None."""
        if not (_is_path_shaped(node) or _const_str(node) is not None):
            return None
        components = self._components(node)
        for i in range(len(components) - 2):
            if components[i] != "dataset":
                continue
            pair = (components[i + 1], components[i + 2])
            if pair in self.candidates:
                return pair
        return None

    def _keys_of(self, node):
        """Keys an expression refers to: a resolved path, or a bound variable."""
        keys = set()
        direct = self._candidate_of(node)
        if direct is not None:
            keys.add(direct)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in self.paths:
                keys |= self.paths[sub.id]
            elif sub is not node and isinstance(sub, ast.expr):
                nested = self._candidate_of(sub)
                if nested is not None:
                    keys.add(nested)
        return keys

    def _call_keys(self, node):
        keys = set()
        for arg in node.args:
            keys |= self._keys_of(arg)
        for keyword in node.keywords:
            keys |= self._keys_of(keyword.value)
        return keys

    # -- statements -------------------------------------------------------

    def run(self, body):
        for node in body:
            self._stmt(node)

    def _stmt(self, node):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._import(node)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # The body is analysed on its own in the helper pass; run it here
            # too (module-level scripts define and call helpers inline), with
            # the parameters shadowing any same-named module binding.
            shadowed = self.paths, self.strs
            self.paths = {k: v for k, v in self.paths.items() if k not in _params(node)}
            self.strs = {k: v for k, v in self.strs.items() if k not in _params(node)}
            self.run(node.body)
            self.paths, self.strs = shadowed
            return
        if isinstance(node, ast.Assign):
            self._exprs(node.value)
            for target in node.targets:
                self._bind(target, node.value)
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self._exprs(node.value)
                self._bind(node.target, node.value)
            return

        for field, value in ast.iter_fields(node):
            if field in ("body", "orelse", "finalbody", "handlers"):
                continue
            for expr in _expr_fields(value):
                self._exprs(expr)
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list):
                self.run(block)
        for handler in getattr(node, "handlers", []):
            self.run(handler.body)

    def _import(self, node):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif node.module:
            names = [node.module]
        for name in names:
            if name.split(".")[0] in NETWORK_MODULES:
                self.uses_network = True

    def _bind(self, target, value):
        if not isinstance(target, ast.Name):
            return
        name = target.id
        text = _const_str(value)
        if text is not None:
            self.strs[name] = text
            self.paths.pop(name, None)
            return
        self.strs.pop(name, None)
        candidate = self._candidate_of(value)
        if candidate is not None:
            self.paths[name] = {candidate}
            self.bound.add(candidate)
            return
        derived = set()
        if _is_path_shaped(value):
            for sub in ast.walk(value):
                if isinstance(sub, ast.Name) and sub.id in self.paths:
                    derived |= self.paths[sub.id]
        if derived:
            self.paths[name] = derived
        else:
            self.paths.pop(name, None)

    def _exprs(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                self._call(sub)

    def _call(self, node):
        name = _func_name(node.func)
        if name is None:
            return
        if _is_network_call(node, name):
            self.uses_network = True
            self.network_keys |= self._call_keys(node)
        if _is_write_call(node, name):
            self.written |= self._call_keys(node)
            return
        params = self.helpers.get(name)
        if not params:
            return
        order, writers = params
        for index, arg in enumerate(node.args):
            if index < len(order) and order[index] in writers:
                self.written |= self._keys_of(arg)
        for keyword in node.keywords:
            if keyword.arg in writers:
                self.written |= self._keys_of(keyword.value)


def _params(node):
    args = node.args
    names = [a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


def _expr_fields(value):
    """Expressions reachable from a statement field, ignoring nested bodies."""
    if isinstance(value, ast.expr):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, ast.expr):
                yield item
            elif isinstance(item, ast.withitem):
                yield item.context_expr
                if item.optional_vars is not None:
                    yield item.optional_vars
    elif isinstance(value, ast.withitem):
        yield value.context_expr


def _python_files(repo):
    """`scripts/**/*.py` plus root-level `*.py`, skipping hidden dirs/caches."""
    files = sorted(repo.glob("*.py"))
    scripts = repo / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.rglob("*.py")):
            parts = path.relative_to(repo).parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            files.append(path)
    return files


def _parse(path):
    try:
        with warnings.catch_warnings():
            # Workspace docstrings are full of `\d`-style sequences; their
            # SyntaxWarnings are not our business and would drown real output.
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        # A single broken script must not take the whole sweep down; say so and
        # move on, which costs at worst an ORPHAN verdict (the safe direction).
        print(f"WARN unparseable {path}", file=sys.stderr)
        return None
    except OSError as error:
        print(f"WARN unreadable {path} ({error})", file=sys.stderr)
        return None


def _helper_writers(trees):
    """Map helper name -> (parameter order, parameters written by its body).

    Resolved to a fixpoint so `a()` calling `b()` calling `output_to_fits()`
    still credits `a`'s parameter. Names are merged repo-wide; a collision only
    ever means "some function of this name writes this parameter", which is
    still positive evidence of a write.
    """
    defs = {}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, (node, _params(node)))

    helpers = {name: (order, set()) for name, (_, order) in defs.items()}
    for _ in range(3):
        changed = False
        for name, (node, order) in defs.items():
            markers = {param: {("param", param)} for param in order}
            flow = _Flow(set(), helpers=helpers, initial_paths=markers)
            flow.run(node.body)
            writers = {key[1] for key in flow.written if key[0] == "param"}
            if not writers <= helpers[name][1]:
                helpers[name] = (order, helpers[name][1] | writers)
                changed = True
        if not changed:
            break
    return helpers


def classify(repo, candidates):
    """Return {(type, name): verdict} for the requested candidates."""
    pairs = set(candidates)
    trees = [tree for tree in (_parse(p) for p in _python_files(repo)) if tree is not None]
    helpers = _helper_writers(trees)

    regenerable, downloaded = set(), set()
    for tree in trees:
        flow = _Flow(pairs, helpers=helpers)
        flow.run(tree.body)
        regenerable |= flow.written
        downloaded |= flow.network_keys
        if flow.uses_network:
            # A file that binds a dataset path and talks to the network is
            # caching real data there (smacs0723 writes CSVs *derived from* its
            # downloads). Blanket-marking every path it binds keeps them all.
            downloaded |= flow.bound

    verdicts = {}
    for pair in pairs:
        if pair in downloaded:
            verdicts[pair] = "DOWNLOADED"
        elif pair in regenerable:
            verdicts[pair] = "REGENERABLE"
        else:
            verdicts[pair] = "ORPHAN"
    return verdicts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("candidates", nargs="+", help="dataset/<type>/<name> paths")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    if not repo.is_dir():
        parser.error(f"repo not found: {repo}")

    wanted = []
    for rel in args.candidates:
        parts = Path(rel.rstrip("/")).parts
        wanted.append((rel, (parts[1], parts[2]) if len(parts) >= 3 else None))

    verdicts = classify(repo, [pair for _, pair in wanted if pair is not None])
    for rel, pair in wanted:
        print(f"{verdicts.get(pair, 'ORPHAN')} {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
