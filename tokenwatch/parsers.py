"""Parsers for coding-agent session logs (JSONL).

Supported:
- Claude Code format: one JSON object per line; ``type`` is "assistant"/"user",
  assistant messages carry ``message.usage.{input_tokens,output_tokens}`` and
  ``message.content[]`` blocks with ``type: "tool_use"`` (name + input).
  Tool results arrive as "user" lines with ``tool_result`` blocks, linked to
  their tool call via ``tool_use_id``.
- Generic best-effort parser: any JSONL object containing a ``usage`` (or
  ``tokens``) dict and tool calls in a few common shapes. Unknown shapes are
  skipped gracefully and counted as warnings — parsing never crashes.

``scan_path`` accepts a single ``*.jsonl`` file or a directory (recursed).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolCall:
    name: str
    input: dict
    id: str | None = None
    result_chars: int = 0
    is_error: bool = False


@dataclass
class Event:
    session_id: str
    timestamp: str | None
    role: str  # "assistant" | "user" | "system"
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tools: list[ToolCall] = field(default_factory=list)
    text_chars: int = 0
    # Raw tool_result blocks on user events; linked to ToolCalls after parsing.
    _result_blocks: list[dict] = field(default_factory=list, repr=False)


@dataclass
class SessionData:
    session_id: str
    path: str
    events: list[Event]
    warnings: int
    source_format: str  # "claude-code" | "generic"


# ---------------------------------------------------------------------------
# Claude Code format
# ---------------------------------------------------------------------------

def _is_claude_code(obj: dict) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("type") in ("assistant", "user", "system")
        and isinstance(obj.get("message"), dict)
    )


def _content_text_length(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                total += len(block.get("text", ""))
        return total
    return 0


def _parse_claude_code_line(obj: dict, session_id: str) -> Event | None:
    msg = obj.get("message", {})
    role = obj.get("type", "user")
    usage = msg.get("usage", {}) or {}
    event = Event(
        session_id=session_id,
        timestamp=obj.get("timestamp"),
        role=role,
        model=msg.get("model"),
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        text_chars=_content_text_length(msg.get("content")),
    )
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                event.tools.append(
                    ToolCall(
                        name=str(block.get("name", "unknown")),
                        input=block.get("input", {}) or {},
                        id=block.get("id"),
                    )
                )
            elif btype == "tool_result":
                event._result_blocks.append(block)
    return event


def _link_tool_results(events: list[Event]) -> None:
    """Attach tool_result blocks to their ToolCall (matched by tool_use_id)."""
    by_id: dict[str, ToolCall] = {}
    ordered: list[ToolCall] = []
    for ev in events:
        for tool in ev.tools:
            ordered.append(tool)
            if tool.id:
                by_id[tool.id] = tool
    for ev in events:
        for block in ev._result_blocks:
            target = None
            rid = block.get("tool_use_id")
            if rid and rid in by_id:
                target = by_id[rid]
            elif ordered:
                # Fallback: attribute to the most recent tool call without a result.
                for tool in reversed(ordered):
                    if tool.result_chars == 0 and not tool.is_error:
                        target = tool
                        break
                target = target or ordered[-1]
            if target is None:
                continue
            content = block.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            target.result_chars = len(str(content))
            target.is_error = bool(block.get("is_error", False))
        ev._result_blocks = []


# ---------------------------------------------------------------------------
# Generic best-effort parser
# ---------------------------------------------------------------------------

def _get_tokens(usage: dict) -> tuple[int, int]:
    get = lambda *keys: next(
        (usage[k] for k in keys if isinstance(usage.get(k), (int, float))), 0
    )
    return int(get("input_tokens", "prompt_tokens", "input")), int(
        get("output_tokens", "completion_tokens", "output")
    )


def _extract_generic_tools(obj: dict) -> list[ToolCall]:
    tools: list[ToolCall] = []
    calls = obj.get("tool_calls") or []
    if isinstance(calls, list):
        for call in calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
            name = call.get("name") or fn.get("name") or "unknown"
            raw_args = call.get("arguments", call.get("input", {}))
            args = (
                json.loads(raw_args)
                if isinstance(raw_args, str) and raw_args.strip().startswith("{")
                else (raw_args if isinstance(raw_args, dict) else {})
            )
            tools.append(ToolCall(name=str(name), input=args))
    fc = obj.get("function_call")
    if isinstance(fc, dict) and fc.get("name"):
        tools.append(ToolCall(name=str(fc["name"]), input=fc.get("arguments", {}) or {}))
    content = obj.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "function_call"):
                tools.append(
                    ToolCall(
                        name=str(block.get("name", "unknown")),
                        input=block.get("input", block.get("arguments", {})) or {},
                        id=block.get("id"),
                    )
                )
    return tools


def _looks_generic(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    usage = obj.get("usage") or obj.get("tokens")
    if isinstance(usage, dict) and usage:
        return True
    if obj.get("tool_calls") or obj.get("function_call"):
        return True
    return False


def _parse_generic_line(obj: dict, session_id: str) -> Event | None:
    usage = obj.get("usage") or obj.get("tokens") or {}
    in_tok, out_tok = _get_tokens(usage) if isinstance(usage, dict) else (0, 0)
    tools = _extract_generic_tools(obj)
    if in_tok == 0 and out_tok == 0 and not tools:
        return None
    role = str(obj.get("role") or obj.get("type") or "assistant")
    text = obj.get("text") or obj.get("content")
    return Event(
        session_id=session_id,
        timestamp=obj.get("timestamp") or obj.get("created_at") or obj.get("time"),
        role=role if role in ("assistant", "user", "system") else "assistant",
        model=obj.get("model"),
        input_tokens=in_tok,
        output_tokens=out_tok,
        tools=tools,
        text_chars=len(text) if isinstance(text, str) else 0,
    )


# ---------------------------------------------------------------------------
# File / directory scanning
# ---------------------------------------------------------------------------

def parse_file(path: str | Path) -> SessionData:
    """Parse one JSONL file into a SessionData (never raises on bad lines)."""
    path = Path(path)
    session_id = path.stem
    events: list[Event] = []
    warnings = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return SessionData(session_id, str(path), [], 1, fmt)
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            warnings += 1
            continue
        try:
            if _is_claude_code(obj):
                ev = _parse_claude_code_line(obj, session_id)
            elif _looks_generic(obj):
                ev = _parse_generic_line(obj, session_id)
            else:
                warnings += 1
                continue
            if ev is not None:
                events.append(ev)
        except Exception:
            warnings += 1
    _link_tool_results(events)
    return SessionData(session_id, str(path), events, warnings, _detect_format(path))


def _detect_format(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _is_claude_code(obj):
                return "claude-code"
            if _looks_generic(obj):
                return "generic"
    except OSError:
        pass
    return "generic"


def iter_jsonl_files(path: str | Path) -> list[Path]:
    """Accept a *.jsonl file or a directory (recursed for *.jsonl)."""
    p = Path(path).expanduser()
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(p.rglob("*.jsonl"))
    raise FileNotFoundError(f"No such file or directory: {path}")


def scan_path(path: str | Path) -> list[SessionData]:
    """Parse every JSONL session under `path`. Never raises on bad files."""
    sessions = []
    for f in iter_jsonl_files(path):
        try:
            sessions.append(parse_file(f))
        except Exception:
            sessions.append(SessionData(f.stem, str(f), [], 1, "generic"))
    return sessions
