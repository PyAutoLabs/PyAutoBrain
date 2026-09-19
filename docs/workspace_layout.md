# Repository locations

`PyAutoMind/repos.yaml` declares each repository's identity and optional canonical
`path`. Science checkouts may live in family folders and infrastructure in
`organs/`; the workspace marker stays at the outer root. CI and task bundles may still place the same checkouts side by side.

Python callers use `agents/_repo_paths.py`: `repo_path(root, name)` locates a
repository in the supplied context, `required=True` additionally requires a Git
checkout, and `iter_checkouts(root)` enumerates flat and one-level family checkouts.
Discovery stops at repository boundaries. Multiple distinct checkouts with the same
identity are an error. Missing optional paths remain visible to coverage checks.
`bootstrap_repo_path(root, name)` discovers Mind before reading the manifest,
so moving the manifest does not introduce a circular lookup dependency.
Shell callers source `bin/_repo_paths.sh` and use `pyauto_repo_path` or
`pyauto_repo_list`; always check their exit status before interpreting absence.

## Local migration

Make and inspect a journal before changing canonical directory placement. This
example moves Brain itself from the root into `organs/`; use its current location
for each command:

```bash
python3 PyAutoBrain/bin/regroup_workspace.py plan --root "$PWD" \
  --bundles-root "${PWD}-wt" --state .migration/regroup.json
python3 PyAutoBrain/bin/regroup_workspace.py apply --state .migration/regroup.json
source activate.sh
python3 organs/PyAutoBrain/bin/regroup_workspace.py verify --state .migration/regroup.json
```

The command renames existing directories without copying or cleaning their contents,
repairs registered Git worktrees and dependency links, and updates local IDE paths.
It preserves dirty files and ignored data, validates directory identity and Git state,
and records original link/configuration values. A source changed since planning or
an occupied destination stops the operation. A failed application rolls back.

To reverse an applied move before making further changes:

```bash
python3 organs/PyAutoBrain/bin/regroup_workspace.py rollback --state .migration/regroup.json
```

Keep the journal outside the directories being moved. After successful validation,
retain it as the local migration receipt. Existing shells retain their old environment;
source the generated root `activate.sh` before further Python work. Task bundles keep
flat repository names and their own activation files.
