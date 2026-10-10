"""Command-line interface for TokenWatch."""

from __future__ import annotations

import argparse
import json
import sys

from tokenwatch import __version__
from tokenwatch.costs import load_prices
from tokenwatch.metrics import analyze
from tokenwatch.parsers import scan_path
from tokenwatch.report import generate_html


def _print_text(metrics: dict) -> None:
    s = metrics["summary"]
    print("TokenWatch report")
    print("=================")
    print(
        f"Sessions: {s['sessions']}   "
        f"Tokens: {s['total_input_tokens']:,} in / {s['total_output_tokens']:,} out   "
        f"Est. cost: ${s['estimated_cost_usd']:.2f}"
    )
    if s["warnings"]:
        print(f"Skipped {s['warnings']} malformed log line(s).")
    print("\nCost by model:")
    for m in metrics["per_model"]:
        tag = " (est.)" if m["estimated"] else ""
        print(
            f"  {m['model']}{tag}: "
            f"{m['input_tokens']:,} in / {m['output_tokens']:,} out — ${m['cost']:.4f}"
        )
    print("\nTool usage:")
    for t in metrics["per_tool"]:
        print(
            f"  {t['tool']}: {t['calls']} calls, "
            f"~{t['result_tokens']:,} result tokens, {t['errors']} errors"
        )
    if metrics["top_files"]:
        print("\nMost-read files:")
        for f in metrics["top_files"][:10]:
            print(f"  {f['file']}: {f['reads']} reads")
    print("\nWaste flags:")
    for flag in metrics["waste_flags"]:
        print(f"  - {flag}")
    if metrics["per_day"]:
        print("\nCost per day:")
        peak = max(d["cost"] for d in metrics["per_day"]) or 1.0
        for d in metrics["per_day"]:
            width = max(1, int(30 * d["cost"] / peak))
            print(f"  {d['date']}  ${d['cost']:.2f}  {'█' * width}")
    print(f"\n{s['price_note']}")


def cmd_scan(args: argparse.Namespace) -> int:
    overrides = load_prices(args.prices) if args.prices else None
    try:
        sessions = scan_path(args.logdir)
    except FileNotFoundError as exc:
        print(f"tokenwatch: error: {exc}", file=sys.stderr)
        return 2
    if not sessions:
        print("tokenwatch: no *.jsonl session files found.", file=sys.stderr)
        return 1
    metrics = analyze(sessions, price_overrides=overrides)

    if args.json:
        print(json.dumps(metrics, indent=2))
    if args.out:
        html = generate_html(metrics)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"Wrote HTML report to {args.out}")
    if not args.json and not args.out:
        _print_text(metrics)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tokenwatch",
        description="Token/cost observability for coding-agent session logs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan session logs and report token usage/cost.")
    scan.add_argument("logdir", help="A *.jsonl session file or a directory (recursed).")
    scan.add_argument("--out", metavar="report.html", default=None,
                      help="Write a self-contained HTML report to this path.")
    scan.add_argument("--json", action="store_true",
                      help="Print the full metrics as JSON to stdout.")
    scan.add_argument("--prices", metavar="prices.json", default=None,
                      help='JSON file overriding model prices, e.g. {"sonnet": [3.0, 15.0]}.')
    scan.set_defaults(func=cmd_scan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
