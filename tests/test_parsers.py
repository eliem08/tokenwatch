"""Tests for tokenwatch.parsers (plus cost lookup and metrics smoke checks)."""

import json
from pathlib import Path

import pytest

from tokenwatch.parsers import parse_file, scan_path, _looks_generic
from tokenwatch.costs import cost_for, lookup, load_prices
from tokenwatch.metrics import analyze

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SAMPLE = EXAMPLES / "sample-session.jsonl"


def test_sample_session_parses():
    session = parse_file(SAMPLE)
    assert session.source_format == "claude-code"
    assert session.warnings == 0
    assert session.session_id == "sample-session"
    events = session.events
    assert len(events) == 28
    assistants = [e for e in events if e.role == "assistant"]
    assert len(assistants) == 14
    assert sum(e.input_tokens for e in assistants) == 200700
    assert sum(e.output_tokens for e in assistants) == 6330
    assert assistants[0].model == "claude-sonnet-4-5-20250929"


def test_tool_calls_and_results_linked():
    session = parse_file(SAMPLE)
    tools = [t for e in session.events for t in e.tools]
    names = [t.name for t in tools]
    assert names.count("Read") == 5
    assert names.count("Edit") == 3
    assert names.count("Bash") == 3
    assert names.count("Grep") == 1
    # Every tool call got its result linked.
    assert all(t.result_chars > 0 for t in tools)
    # Exactly one tool call errored (the failing npm test).
    errors = [t for t in tools if t.is_error]
    assert len(errors) == 1
    assert errors[0].name == "Bash"
    # File paths extracted from tool inputs.
    read_paths = [
        t.input.get("file_path") for t in tools if t.name == "Read"
    ]
    assert read_paths.count("src/App.tsx") == 3


def test_metrics_waste_heuristics_fire():
    metrics = analyze([parse_file(SAMPLE)])
    s = metrics["summary"]
    assert s["sessions"] == 1
    assert s["total_input_tokens"] == 200700
    assert s["cost_estimated"] is False  # sonnet-4-5 is in the price table
    flags = metrics["waste_flags"]
    assert any("re-reading" in f for f in flags), flags
    assert any("error" in f.lower() for f in flags), flags
    # Two days of activity.
    assert [d["date"] for d in metrics["per_day"]] == ["2026-10-08", "2026-10-09"]
    # Top file is the thrice-read component.
    assert metrics["top_files"][0]["file"] == "src/App.tsx"
    assert metrics["top_files"][0]["reads"] == 3


def test_cost_lookup_and_overrides(tmp_path):
    rate_in, rate_out, estimated = lookup("claude-sonnet-4-5-20250929")
    assert (rate_in, rate_out) == (3.0, 15.0)
    assert estimated is False

    rate_in, rate_out, estimated = lookup("some-future-model-x99")
    assert estimated is True  # falls back to DEFAULT_RATE

    cost, _ = cost_for("gpt-5-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(2.25)

    prices_file = tmp_path / "prices.json"
    prices_file.write_text(json.dumps({"sonnet": [1.0, 2.0]}))
    overrides = load_prices(prices_file)
    cost, _ = cost_for("claude-sonnet-4-5", 1_000_000, 0, overrides)
    assert cost == pytest.approx(1.0)


def test_generic_parser_skips_unknown_shapes(tmp_path):
    p = tmp_path / "weird.jsonl"
    p.write_text(
        "\n".join([
            json.dumps({"hello": "world"}),                       # unknown -> warning
            "not json at all {{{",                                 # bad json -> warning
            "",                                                   # blank -> ignored
            json.dumps({"model": "gpt-5-mini",
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                        "tool_calls": [{"function": {"name": "exec",
                                                    "arguments": '{"cmd": "ls"}'}}]}),
        ])
    )
    session = parse_file(p)
    assert session.warnings == 2
    assert len(session.events) == 1
    ev = session.events[0]
    assert ev.input_tokens == 100 and ev.output_tokens == 20
    assert ev.tools[0].name == "exec"


def test_scan_path_accepts_file_and_dir():
    one = scan_path(SAMPLE)
    assert len(one) == 1
    many = scan_path(EXAMPLES)
    assert len(many) >= 1
    with pytest.raises(FileNotFoundError):
        scan_path(EXAMPLES / "does-not-exist.jsonl")


def test_empty_and_missing_file(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    session = parse_file(empty)
    assert session.events == [] and session.warnings == 0
    metrics = analyze([session])
    assert metrics["summary"]["total_tokens"] == 0
