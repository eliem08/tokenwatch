"""Aggregate parsed sessions into cost/token/waste metrics."""

from __future__ import annotations

from collections import Counter, defaultdict

from tokenwatch.costs import cost_for, PRICE_NOTE
from tokenwatch.parsers import SessionData

# Rough chars-per-token for estimating tool-result token sizes.
CHARS_PER_TOKEN = 4

# Heuristic thresholds.
REREAD_PCT_THRESHOLD = 0.20      # >20% of tool-result tokens are re-reads -> flag
VERBOSE_RATIO_THRESHOLD = 0.60   # output/input token ratio above this -> flag


def _file_from_tool_input(tool_input: dict) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "file", "filename"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def analyze(
    sessions: list[SessionData],
    price_overrides: dict | None = None,
) -> dict:
    """Compute per-session and overall metrics. Returns a JSON-serialisable dict."""
    total_in = total_out = 0
    total_cost = 0.0
    estimated_cost = False
    per_model: dict[str, dict] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "estimated": False})
    per_tool: dict[str, dict] = defaultdict(lambda: {"calls": 0, "result_tokens": 0, "errors": 0})
    file_reads: Counter = Counter()
    per_day: dict[str, float] = defaultdict(float)
    reread_tokens = 0
    total_result_tokens = 0
    error_calls = 0
    warnings = 0
    per_session = []

    for session in sessions:
        warnings += session.warnings
        s_in = s_out = 0
        s_cost = 0.0
        s_models: Counter = Counter()
        # Track Read calls per file within this session for re-read detection.
        reads_seen: dict[str, int] = defaultdict(int)

        for ev in session.events:
            if ev.role != "assistant":
                continue
            s_in += ev.input_tokens
            s_out += ev.output_tokens
            cost, est = cost_for(ev.model, ev.input_tokens, ev.output_tokens, price_overrides)
            s_cost += cost
            estimated_cost = estimated_cost or est
            model_key = ev.model or "unknown"
            m = per_model[model_key]
            m["input_tokens"] += ev.input_tokens
            m["output_tokens"] += ev.output_tokens
            m["cost"] += cost
            m["estimated"] = m["estimated"] or est
            s_models[model_key] += 1
            if ev.timestamp:
                per_day[ev.timestamp[:10]] += cost

            for tool in ev.tools:
                t = per_tool[tool.name]
                t["calls"] += 1
                rt = tool.result_chars // CHARS_PER_TOKEN
                t["result_tokens"] += rt
                total_result_tokens += rt
                if tool.is_error:
                    t["errors"] += 1
                    error_calls += 1
                fpath = _file_from_tool_input(tool.input)
                if fpath and tool.name.lower() == "read":
                    file_reads[fpath] += 1
                    reads_seen[fpath] += 1
                    if reads_seen[fpath] > 1:
                        reread_tokens += rt

        total_in += s_in
        total_out += s_out
        total_cost += s_cost
        per_session.append(
            {
                "session_id": session.session_id,
                "path": session.path,
                "format": session.source_format,
                "messages": sum(1 for e in session.events if e.role == "assistant"),
                "input_tokens": s_in,
                "output_tokens": s_out,
                "cost": round(s_cost, 4),
                "models": sorted(s_models),
                "warnings": session.warnings,
            }
        )

    # ---------------- Waste heuristics (plain English) ----------------
    waste_flags: list[str] = []
    if total_result_tokens > 0 and reread_tokens / total_result_tokens > REREAD_PCT_THRESHOLD:
        pct = 100 * reread_tokens / total_result_tokens
        # Name the worst offender.
        worst = file_reads.most_common(1)
        example = f" — e.g. '{worst[0][0]}' was read {worst[0][1]} times" if worst else ""
        waste_flags.append(
            f"{pct:.0f}% of input tokens from tool results (~{reread_tokens:,} tokens) "
            f"came from re-reading files already read in the same session{example}. "
            "Consider asking the agent to keep file contents in context instead of re-reading."
        )
    if total_in > 0 and total_out / total_in > VERBOSE_RATIO_THRESHOLD:
        ratio = total_out / total_in
        waste_flags.append(
            f"Output tokens are {ratio:.0%} of input tokens — responses may be verbose. "
            "Shorter, denser answers would cut the most expensive tokens first (output)."
        )
    if error_calls:
        waste_flags.append(
            f"{error_calls} tool call{'s' if error_calls != 1 else ''} returned "
            f"{'errors' if error_calls != 1 else 'an error'} — each failed call usually "
            "burns a full retry loop of input + output tokens."
        )
    if per_session:
        priciest = max(per_session, key=lambda s: s["cost"])
        if priciest["cost"] > 0 and len(per_session) > 1:
            waste_flags.append(
                f"Session '{priciest['session_id']}' cost ${priciest['cost']:.2f}, "
                "the most expensive session — worth reviewing what it was doing."
            )
    if not waste_flags:
        waste_flags.append("No major waste patterns detected. Your agents are behaving.")

    per_session.sort(key=lambda s: s["cost"], reverse=True)

    return {
        "summary": {
            "sessions": len(sessions),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "estimated_cost_usd": round(total_cost, 4),
            "cost_estimated": estimated_cost,
            "warnings": warnings,
            "files_touched": len(file_reads),
            "price_note": PRICE_NOTE,
        },
        "per_model": [
            {
                "model": k,
                "input_tokens": v["input_tokens"],
                "output_tokens": v["output_tokens"],
                "cost": round(v["cost"], 4),
                "estimated": v["estimated"],
            }
            for k, v in sorted(per_model.items(), key=lambda kv: kv[1]["cost"], reverse=True)
        ],
        "per_tool": [
            {
                "tool": k,
                "calls": v["calls"],
                "result_tokens": v["result_tokens"],
                "errors": v["errors"],
            }
            for k, v in sorted(per_tool.items(), key=lambda kv: kv[1]["calls"], reverse=True)
        ],
        "top_files": [
            {"file": f, "reads": c} for f, c in file_reads.most_common(20)
        ],
        "per_day": [
            {"date": d, "cost": round(c, 4)}
            for d, c in sorted(per_day.items())
        ],
        "per_session": per_session,
        "waste_flags": waste_flags,
        "stats": {
            "reread_tokens": reread_tokens,
            "total_result_tokens": total_result_tokens,
            "error_tool_calls": error_calls,
        },
    }
