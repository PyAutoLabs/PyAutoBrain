"""The output guard catches regressions without a hard-coded skill registry."""
import sys
from html import escape
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "board"))
from copy_contract import assert_portable_copy_payloads  # noqa: E402


@pytest.mark.parametrize("attribute", ["data-cmd", "data-copy"])
@pytest.mark.parametrize("payload", ["/health", "  /new_skill task\nKeep edits.",
                                     "/future-skill --auto"])
def test_rejects_client_commands_in_either_clipboard_attribute(attribute, payload):
    page = f'<button {attribute}="{escape(payload, quote=True)}">Copy</button>'
    with pytest.raises(AssertionError, match="Assistant-specific copy payloads"):
        assert_portable_copy_payloads(page)


def test_checks_entities_and_every_button_not_just_the_first():
    page = '<button data-cmd="Use the health skill.">Copy</button>'
    page += '<button data-copy="&#10;&#47;future_skill task">Copy</button>'
    with pytest.raises(AssertionError, match="future_skill"):
        assert_portable_copy_payloads(page)


@pytest.mark.parametrize("payload", ["Use the health skill. Inspect CI.",
    "bash bin/morning.sh", "pyauto-heart tick && pyauto-heart readiness",
    "/usr/bin/tool --flag", "Read /tmp/input and use the health skill."])
def test_prose_shell_commands_and_absolute_paths_are_allowed(payload):
    assert_portable_copy_payloads(
        f'<button data-cmd="{escape(payload, quote=True)}">Copy</button>')


@pytest.mark.parametrize("marker", ['class="copy term"',
                                     'aria-label="copy command: run the check"'])
def test_explicit_terminal_buttons_can_copy_a_root_executable(marker):
    assert_portable_copy_payloads(f'<button {marker} data-cmd="/tool --flag">Run</button>')


@pytest.mark.parametrize("page", ["", '<a href="/health">Health</a>',
                                 '<script>const example = "/health";</script>'])
def test_missing_clipboard_buttons_cannot_pass_vacuously(page):
    with pytest.raises(AssertionError, match="No copy payloads"):
        assert_portable_copy_payloads(page)
