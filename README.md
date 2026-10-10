# 🔍 TokenWatch

**Token & cost observability for coding agents.** Point it at your Claude Code / Codex / Cursor session logs and get a clear picture of where your tokens — and money — actually go.

Coding-agent bills are opaque. You see a monthly total, but not *which session* burned it, *which tool* kept re-reading the same file, or *which model* you were really paying for. TokenWatch parses the JSONL session logs these tools already write to disk, attributes cost per model, and flags waste in plain English.

## Quickstart

```bash
pip install tokenwatch

# Scan all your Claude Code sessions, write a self-contained HTML report
tokenwatch scan ~/.claude/projects --out report.html

# Or just print a text summary
tokenwatch scan ~/.claude/projects

# Machine-readable metrics
tokenwatch scan ~/.claude/projects --json > metrics.json

# Single session file works too
tokenwatch scan ./my-session.jsonl --out report.html
```

Then open `report.html` in any browser — it's a single file with no external dependencies, so it works fully offline.

## What the report shows

- **Summary cards** — estimated total cost, total input/output tokens, session count, and the single biggest waste flag
- **Waste flags** — plain-English findings like *"43% of input tokens from tool results came from re-reading files already read in the same session"* or *"3 tool calls returned errors — each failed call usually burns a full retry loop"*
- **Cost-per-day trend** — bar chart built from message timestamps
- **Cost by model** — tokens and estimated spend per model (models missing from the price table are marked `est.`)
- **Tool usage** — calls, estimated result tokens, and error counts per tool
- **Most-read files** — which files the agent kept coming back to
- **Per-session table** — every session ranked by cost

## Supported log formats

| Format | Detection | Notes |
|---|---|---|
| Claude Code (`~/.claude/projects/*/*.jsonl`) | automatic | assistant `usage`, `tool_use` blocks, `tool_result` linking (incl. `is_error`) |
| Generic JSONL | best-effort | any object with a `usage`/`tokens` dict and tool calls; unknown shapes are skipped with a warning count, never a crash |

Give it a directory and it recurses for `*.jsonl`. Give it one file and it parses just that.

## How cost estimation works

TokenWatch ships with an **approximate** per-model price table (USD per 1M input/output tokens, captured Oct 2026) covering common Claude and GPT models. Model names are fuzzy-matched (date suffixes and provider prefixes are stripped), and anything unrecognised falls back to a clearly-marked estimated rate.

Prices change constantly and TokenWatch is not affiliated with any provider — **treat every dollar figure as a rough estimate**. Bring your own numbers any time:

```bash
tokenwatch scan ~/.claude/projects --prices my-prices.json --out report.html
```

`my-prices.json` maps a model-name substring to `[input_per_1M, output_per_1M]`:

```json
{
  "sonnet": [3.0, 15.0],
  "my-fine-tune": [5.0, 20.0]
}
```

## Waste heuristics

TokenWatch currently flags:

1. **Re-reads** — more than 20% of tool-result tokens coming from files already read in the same session (the classic "agent reads the same 8k file three times" loop)
2. **Verbose responses** — output tokens exceeding 60% of input tokens (output is the most expensive token class)
3. **Error retries** — tool calls that returned errors, each of which typically burns a full retry loop
4. **Priciest session** — the single most expensive session, so you know where to look first

Thresholds are conservative on purpose — a flag is a conversation starter, not a verdict.

## Project layout

```
tokenwatch/
├── tokenwatch/
│   ├── __init__.py     # public API
│   ├── cli.py          # argparse: `tokenwatch scan <logdir> [--out] [--json] [--prices]`
│   ├── parsers.py      # Claude Code + generic JSONL parsers
│   ├── costs.py        # approximate price table, fuzzy matching, --prices overrides
│   ├── metrics.py      # aggregation + waste heuristics
│   └── report.py       # single-file HTML report (inline CSS, no dependencies)
├── examples/
│   └── sample-session.jsonl   # realistic 2-day Claude Code session
├── tests/
│   └── test_parsers.py
├── pyproject.toml
├── LICENSE (MIT)
└── README.md
```

## Roadmap

- [ ] Codex / Cursor native log formats (beyond the generic parser)
- [ ] Cache-token / prompt-caching breakdown (Claude Code logs `cache_creation_input_tokens`)
- [ ] Per-project rollups for monorepos with many session files
- [ ] Watch mode: live-updating report as sessions grow
- [ ] Export to CSV for spreadsheet analysis

## Contributing

Issues and PRs welcome. Run the checks before submitting:

```bash
pip install -e ".[dev]"   # or: pip install -e . && pip install pytest
python -m pytest
python -m tokenwatch.cli scan examples/sample-session.jsonl --out /tmp/report.html
```

## License

MIT — see [LICENSE](LICENSE). © 2026 Ilyass Emssaad.
