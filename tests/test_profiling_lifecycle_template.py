"""The likelihood-lifecycle template renders into census-clean Mind prompts.

`skills/profiling/lifecycle.md` is rendered here the way phase 8's verb will:
plain placeholder substitution, one fenced `prompt <path>` block per step. The
rendered prompts are filed into a synthetic Mind and judged by the intake
conductor's own `census` — the check `pyauto-brain intake census` applies — so
the header rules are never restated in this file.
"""

import importlib.util
import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
TEMPLATE = BRAIN_HOME / "skills" / "profiling" / "lifecycle.md"
_spec = importlib.util.spec_from_file_location(
    "_intake_lifecycle_under_test",
    BRAIN_HOME / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_lifecycle_under_test"] = _intake
_spec.loader.exec_module(_intake)

PLACEHOLDERS = ("<dataset_type>", "<variant>", "<instrument>", "<regime>", "<trigger>")
BLOCK = re.compile(r"^```prompt (\S+)\n(.*?)^```$", re.M | re.S)
# The Mind vocabulary keywords the template uses (PyAutoMind themes.md).
THEMES = ("profiling", "dashboard", "visualization", "hpc-gpu", "assistants",
          "jax-gradient", "samplers", "mind-workflow")


def _render(values):
    text = TEMPLATE.read_text()
    for placeholder, value in zip(PLACEHOLDERS, values):
        text = text.replace(placeholder, value)
    return BLOCK.findall(text)


def _file(mind, blocks):
    (mind / "themes.md").write_text(
        "# Themes\n\n## Vocabulary\n\n" + "".join(f"- `{t}`: x\n" for t in THEMES))
    for rel, body in blocks:
        path = mind / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return _intake.census(mind)


def test_template_uses_one_placeholder_set_and_eight_steps():
    text = TEMPLATE.read_text()
    blocks = BLOCK.findall(text)
    assert len(blocks) == 8
    used = set(re.findall(r"<[a-z_]+>", "".join(path + body for path, body in blocks)))
    # `<id>`, `<n>`, `<setup_id>`, `<host_class>`, `<model_variant>` and
    # `<sampler>` are literal path grammar inside the prose, not placeholders.
    assert used - {"<id>", "<n>", "<setup_id>", "<host_class>", "<model_variant>",
                   "<sampler>"} == set(PLACEHOLDERS)


def test_imaging_delaunay_render_passes_the_census_header_check(tmp_path):
    blocks = _render(("imaging", "delaunay", "hst", "standard", "new"))
    assert not any(p in path + body for path, body in blocks for p in PLACEHOLDERS)
    c = _file(tmp_path, blocks)
    assert len(c["records"]) == 8
    assert c["hygiene"] == [] and c["theme_flags"] == [] and c["drift"] == []
    assert c["witness_flags"] == []
    phases = []
    for r in c["records"]:
        assert r["missing"] == [], r["path"]
        assert r["epic"] == "lifecycle-imaging-delaunay"
        assert isinstance(r["phase"], int)
        assert r["witness"]
        # the folder after the work type is the census target: it must agree
        # with the prompt's own Type:/Target: header
        assert r["header"]["type"] == r["work_type"]
        assert r["header"]["target"] == r["target"]
        assert ("blocked-by" in r["header"]) == (r["phase"] != 0)
        phases.append(r["phase"])
    assert sorted(phases) == list(range(8))


def test_reoptimised_render_starts_at_l2_unblocked(tmp_path):
    blocks = [(path, body) for path, body in _render(
        ("interferometer", "mge", "sma", "standard", "reoptimised"))
        if not re.search(r"_l[01]_", path)]
    # rendering rule 1: the entry step drops its Blocked-by line
    blocks = [(p, re.sub(r"^Blocked-by: .*Phase 1\n", "", b, flags=re.M)) for p, b in blocks]
    c = _file(tmp_path, blocks)
    by_phase = {r["phase"]: r for r in c["records"]}
    assert sorted(by_phase) == [2, 3, 4, 5, 6, 7]
    assert "blocked-by" not in by_phase[2]["header"]
    assert all(r["missing"] == [] for r in c["records"])
    assert "trigger `reoptimised`" in (tmp_path / by_phase[2]["path"]).read_text()
