import json
import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "codex_usage.py"
SPEC = importlib.util.spec_from_file_location("codex_usage", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
aggregate, parse_rollout = MODULE.aggregate, MODULE.parse_rollout


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    return path


def test_uses_last_cumulative_snapshot_and_keeps_subsets_separate(tmp_path):
    path = _write(
        tmp_path / "one.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "s1",
                    "model": "gpt-6-astra",
                    "reasoning_effort": "medium",
                },
                "timestamp": "2026-01-01T00:00:00Z",
            },
            {
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 4,
                            "output_tokens": 3,
                            "reasoning_output_tokens": 1,
                        }
                    }
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 20,
                            "cached_input_tokens": 7,
                            "output_tokens": 8,
                            "reasoning_output_tokens": 2,
                        }
                    }
                },
                "timestamp": "2026-01-01T00:01:00Z",
            },
        ],
    )
    result = parse_rollout(path)
    assert result["usage"] == {
        "input_tokens": 20,
        "cached_input_tokens": 7,
        "uncached_input_tokens": 13,
        "output_tokens": 8,
        "reasoning_output_tokens": 2,
        "total_tokens": 28,
    }
    assert result["duration_seconds"] == 60


def test_reports_model_effort_changes_and_coordination_without_causality(tmp_path):
    path = _write(
        tmp_path / "switch.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {"id": "switch", "model": "astra", "effort": "medium"},
            },
            {
                "type": "turn_context",
                "payload": {"model": "sol", "reasoning_effort": "high"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "collaboration.spawn_agent",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "total_token_usage": {
                        "input_tokens": 1,
                        "cached_input_tokens": 0,
                        "output_tokens": 1,
                        "reasoning_output_tokens": 0,
                    }
                },
            },
        ],
    )
    result = parse_rollout(path)
    assert result["models"] == ["astra", "sol"]
    assert result["reasoning_efforts"] == ["high", "medium"]
    assert result["coordination"] == {"spawn": 1}


def test_missing_or_malformed_usage_stays_unknown(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{bad}\n{"type":"session_meta","payload":{"id":"bad"}}\n')
    report = aggregate([path], set())
    assert report["complete"] is False
    assert report["totals"] is None
    assert "malformed JSON" in " ".join(report["sessions"][0]["limitations"])


def test_deduplicates_file_and_session_and_flags_child_uncertainty(tmp_path):
    usage = {
        "input_tokens": 2,
        "cached_input_tokens": 1,
        "output_tokens": 1,
        "reasoning_output_tokens": 0,
    }
    one = _write(
        tmp_path / "one.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "same"}},
            {"payload": {"total_token_usage": usage}},
        ],
    )
    two = _write(
        tmp_path / "two.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "same"}},
            {"payload": {"total_token_usage": usage}},
        ],
    )
    report = aggregate([one, one, two], {two.resolve()})
    assert len(report["sessions"]) == 1
    assert any("duplicate" in item for item in report["limitations"])
    assert any("inherit parent events" in item for item in report["limitations"])


def test_output_structure_never_contains_conversation_payload(tmp_path):
    secret = "private prompt and tool arguments"
    path = _write(
        tmp_path / "private.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "private"}},
            {
                "type": "response_item",
                "payload": {"type": "message", "content": secret},
            },
            {
                "payload": {
                    "total_token_usage": {
                        "input_tokens": 1,
                        "cached_input_tokens": 0,
                        "output_tokens": 1,
                        "reasoning_output_tokens": 0,
                    }
                }
            },
        ],
    )
    assert secret not in json.dumps(parse_rollout(path))


def test_invalid_counter_snapshot_is_unknown(tmp_path):
    path = _write(
        tmp_path / "invalid.jsonl",
        [
            {
                "payload": {
                    "total_token_usage": {
                        "input_tokens": 1,
                        "cached_input_tokens": 2,
                        "output_tokens": "bad",
                        "reasoning_output_tokens": None,
                    }
                }
            }
        ],
    )
    result = parse_rollout(path)
    assert result["complete"] is False
    assert result["usage"] is None


def test_invalid_latest_snapshot_does_not_fall_back_to_provisional(tmp_path):
    valid = {
        "input_tokens": 2,
        "cached_input_tokens": 1,
        "output_tokens": 1,
        "reasoning_output_tokens": 0,
    }
    path = _write(
        tmp_path / "provisional.jsonl",
        [
            {"payload": {"total_token_usage": valid}},
            {"payload": {"total_token_usage": valid | {"output_tokens": None}}},
        ],
    )
    result = parse_rollout(path)
    assert result["complete"] is False
    assert result["usage"] is None


def test_conflicting_duplicate_session_is_incomplete(tmp_path):
    one = _write(
        tmp_path / "one.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "dup"}},
            {
                "payload": {
                    "total_token_usage": {
                        "input_tokens": 2,
                        "cached_input_tokens": 1,
                        "output_tokens": 1,
                        "reasoning_output_tokens": 0,
                    }
                }
            },
        ],
    )
    two = _write(
        tmp_path / "two.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "dup"}},
            {
                "payload": {
                    "total_token_usage": {
                        "input_tokens": 3,
                        "cached_input_tokens": 1,
                        "output_tokens": 1,
                        "reasoning_output_tokens": 0,
                    }
                }
            },
        ],
    )
    report = aggregate([one, two], set())
    assert report["complete"] is False
    assert report["totals"] is None
    assert "conflicting" in " ".join(report["limitations"])


def test_text_cli_handles_unreadable_requested_session(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "missing.jsonl")],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "unknown/incomplete" in result.stdout
    assert "unreadable" in result.stdout
