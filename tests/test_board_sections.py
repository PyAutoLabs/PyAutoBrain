"""Major-section layout preserves owner content, summaries and navigation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'board'))
import _theme as theme


def page(content):
    return ('<html><body>' + theme.hero('brain', 'Board', navigation=[
        {'href': '#first', 'label': 'First', 'count': 0},
        {'href': '#second', 'label': 'Second', 'count': 'Unknown'},
    ]) + theme.orchestration_panel('brain', '', '', 'Keep <this> payload', organ='brain')
        + content + '<footer>Footer</footer><script>' + theme.JS + '</script></body></html>')


def test_native_sections_and_panel_order_preserve_payloads_and_footer():
    result = theme.section_layout(page('<a id="first"></a><h2>First</h2><p>One</p>'
                                      '<h2 id="second">Second</h2><p>Two</p><ul class="boards"><li>Other boards</li></ul>'))
    assert result.index('class="hero"') < result.index('class="orchestration-panel"') < result.index('class="board-nav"')
    assert result.count('<details class="board-section">') == 2
    assert '<summary><h2>First</h2><span class="section-badge">0</span></summary>' in result
    assert '<span class="section-badge">Unknown</span>' in result
    assert 'Keep &lt;this&gt; payload' in result
    assert '<a id="first"></a>' in result
    assert '</div></details><ul class="boards">' in result
    assert '</ul><footer>Footer</footer>' in result
    assert theme.section_layout(result) == result


def test_nested_owner_sections_do_not_swallow_following_sections():
    result = theme.section_layout(page(
        '<h2 id="first">Observed</h2><div>Rows<details id="row"><summary>Row</summary>Evidence</details></div>'
        '<section aria-labelledby="second"><h2 id="second">Score</h2><p>Score</p></section>'
        '<div class="reasons" id="red"><h2>Blockers</h2><p>Reasons</p></div>'))
    assert result.count('<details class="board-section">') == 3
    assert result.count('id="row"') == 1
    assert '<summary><h2>Blockers</h2>' in result
    assert '<section aria-labelledby="second"><p>Score</p></section>' in result


def test_existing_disclosures_and_cards_are_not_rewrapped():
    result = theme.section_layout(page('<details><summary>Existing</summary><h2>Inner</h2></details>'
                                      '<article><h2>Card</h2></article>'))
    assert '<details class="board-section">' not in result


def test_status_is_explicit_escaped_and_visible_in_summary():
    result = theme.section_layout(page('<h2 id="first">Checks</h2><p>Evidence</p>'),
                                  {'first': {'status': 'red', 'label': '<alert>', 'count': 12}})
    summary = result.split('<details class="board-section"><summary>')[1].split('</summary>')[0]
    assert 'section-status-red' in summary
    assert '&lt;alert&gt;' in summary
    assert '>12</span>' in summary
    assert '<alert>' not in result


def test_wrapped_heading_and_deep_anchor_survive():
    result = theme.section_layout(page('<section id="first"><div class="section-head"><h2>Queue</h2></div>'
                                      '<p id="deep">Item</p></section><h2 id="second">Coverage</h2>'))
    assert result.count('<details class="board-section">') == 2
    assert '<summary><h2>Queue</h2>' in result
    assert 'id="deep"' in result


def test_multiple_metrics_keep_their_labels_instead_of_overwriting():
    source = '<body>' + theme.hero('cortex', 'Board', navigation=[
        {'href': '#runs', 'label': 'Running', 'count': 2},
        {'href': '#runs', 'label': 'Open', 'count': 5},
    ]) + '<h2 id="runs">Runs</h2><p>Evidence</p></body>'
    result = theme.section_layout(source)
    assert '>2 Running · 5 Open</span>' in result
