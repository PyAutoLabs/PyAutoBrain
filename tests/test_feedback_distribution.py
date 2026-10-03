"""The distributed feedback command must work without a Brain checkout."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_feedback', ROOT / 'bin/sync_feedback.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_standalone_embeds_canonical_template_and_invitation():
    text = sync.render()
    for filename in ('template.md', 'invitation.md'):
        source = (sync.SOURCE / filename).read_text().split('\n', 1)[1].strip()
        assert source in text
    assert '(template.md)' not in text and '(invitation.md)' not in text
    assert '(#report-template)' in text and '(#portable-invitation)' in text
    assert 'needs no Brain checkout' in text
    assert 'feedback-report: v1' in text


def test_generator_check_reports_drift_without_writing(tmp_path):
    (tmp_path / 'skills').mkdir()
    (tmp_path / 'AGENTS.md').write_text('assistant')
    output = tmp_path / 'skills/feedback.md'
    assert sync.main([str(tmp_path), '--check']) == 1
    assert not output.exists()
    assert sync.main([str(tmp_path)]) == 0
    assert output.read_text() == sync.render()
    assert sync.main([str(tmp_path), '--check']) == 0
    output.write_text('user edit')
    assert sync.main([str(tmp_path), '--check']) == 1
    assert output.read_text() == 'user edit'


def test_clone_boundary_keeps_portable_skill_generic():
    import sys
    sys.path.insert(0, str(ROOT / 'agents/conductors/clone'))
    import _clone
    patterns = _clone.reference_profile('autolens_assistant')['generic']
    for path in ('skills/feedback.md', '.claude/skills/feedback.md', '.claude/commands/feedback.md'):
        assert _clone.match_any(path, patterns)
    assert not _clone.match_any('.codex/skills/autolens-assistant-feedback/SKILL.md', patterns)
