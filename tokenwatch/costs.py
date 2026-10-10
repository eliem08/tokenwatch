"""Approximate per-model price table (USD per 1M tokens).

These are APPROXIMATE public list prices, captured Oct 2026. TokenWatch is not
affiliated with any model provider and prices change often. Treat every dollar
figure as a rough estimate, and override with your own numbers via:

    tokenwatch scan <logdir> --prices my-prices.json

The JSON file maps a model-name substring to [input_per_1M, output_per_1M],
e.g. {"sonnet": [3.0, 15.0]}. Overrides take precedence over this table.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# (input $/1M tokens, output $/1M tokens) — approximate public prices, Oct 2026.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    # --- Anthropic Claude ---
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-3-7-sonnet": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-5-haiku": (0.8, 4.0),
    "claude-3-haiku": (0.25, 1.25),
    # --- OpenAI ---
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "o4-mini": (1.1, 4.4),
}

# Fallback rate for models we don't recognise (roughly a mid-tier model).
DEFAULT_RATE: tuple[float, float] = (3.0, 15.0)

PRICE_NOTE = (
    "Costs are estimates from approximate public prices (Oct 2026); "
    "override with --prices."
)


def _normalize(model: str) -> str:
    """Lowercase and strip provider prefixes / date suffixes for matching."""
    m = model.strip().lower()
    m = re.sub(r"^(anthropic/|openai/)", "", m)
    m = re.sub(r"-\d{8}$", "", m)  # e.g. claude-sonnet-4-5-20250929
    return m


def load_prices(path: str | Path) -> dict[str, tuple[float, float]]:
    """Load user price overrides: {model_substring: [in_per_1M, out_per_1M]}.

    Also accepts {"model": {"input": x, "output": y}} shape.
    """
    data = json.loads(Path(path).read_text())
    out: dict[str, tuple[float, float]] = {}
    for key, val in data.items():
        if isinstance(val, dict):
            out[_normalize(key)] = (float(val["input"]), float(val["output"]))
        else:
            rate_in, rate_out = val
            out[_normalize(key)] = (float(rate_in), float(rate_out))
    return out


def lookup(
    model: str | None, overrides: dict[str, tuple[float, float]] | None = None
) -> tuple[float, float, bool]:
    """Return (input_rate, output_rate, estimated) for a model name.

    `estimated` is True when we fell back to DEFAULT_RATE or matched only
    loosely — the caller should surface that uncertainty in the report.
    """
    if not model:
        return (*DEFAULT_RATE, True)
    norm = _normalize(model)

    def _search(table: dict[str, tuple[float, float]]):
        if norm in table:
            return table[norm], False
        # Longest-substring match so "claude-sonnet-4-5" beats "sonnet".
        for key in sorted(table, key=len, reverse=True):
            if key in norm or norm in key:
                return table[key], False
        return None

    if overrides:
        hit = _search({_normalize(k): v for k, v in overrides.items()})
        if hit:
            return (*hit[0], hit[1])
    hit = _search(PRICE_TABLE)
    if hit:
        return (*hit[0], hit[1])
    return (*DEFAULT_RATE, True)


def cost_for(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    overrides: dict[str, tuple[float, float]] | None = None,
) -> tuple[float, bool]:
    """Estimated USD cost for a message. Returns (cost, estimated)."""
    rate_in, rate_out, estimated = lookup(model, overrides)
    cost = (input_tokens / 1_000_000) * rate_in + (output_tokens / 1_000_000) * rate_out
    return cost, estimated
