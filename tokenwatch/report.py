"""Generate a single self-contained HTML report (no external dependencies).

Everything is inlined — CSS and charts are plain HTML/CSS, so the file works
fully offline. Bar charts are simple <div> bars; no JavaScript, no CDNs.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _cards(summary: dict, waste_flags: list[str]) -> str:
    top_flag = waste_flags[0] if waste_flags else "—"
    # Trim the top flag for card display; full text lives in the flags section.
    short_flag = top_flag if len(top_flag) <= 140 else top_flag[:137] + "..."
    cards = [
        ("Estimated cost", f"${summary['estimated_cost_usd']:.2f}", "USD"),
        ("Total tokens", _fmt_int(summary["total_tokens"]),
         f"{_fmt_int(summary['total_input_tokens'])} in / {_fmt_int(summary['total_output_tokens'])} out"),
        ("Sessions", str(summary["sessions"]), f"{summary['files_touched']} files touched"),
        ("Top waste flag", "", short_flag),
    ]
    out = ['<section class="cards">']
    for title, big, small in cards:
        out.append(
            f'<div class="card"><div class="card-title">{_esc(title)}</div>'
            f'<div class="card-big">{_esc(big)}</div>'
            f'<div class="card-small">{_esc(small)}</div></div>'
        )
    out.append("</section>")
    return "\n".join(out)


def _bars(per_day: list[dict]) -> str:
    if not per_day:
        return "<p>No timestamped data for a daily trend.</p>"
    peak = max(d["cost"] for d in per_day) or 1.0
    out = ['<div class="bars">']
    for d in per_day:
        width = max(2.0, 100.0 * d["cost"] / peak)
        out.append(
            '<div class="bar-row">'
            f'<span class="bar-label">{_esc(d["date"])}</span>'
            '<span class="bar-track">'
            f'<span class="bar-fill" style="width:{width:.1f}%"></span>'
            "</span>"
            f'<span class="bar-val">${d["cost"]:.2f}</span>'
            "</div>"
        )
    out.append("</div>")
    return "\n".join(out)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table>"


def generate_html(metrics: dict) -> str:
    """Render the full metrics dict as a self-contained HTML document."""
    s = metrics["summary"]
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    model_rows = [
        [
            _esc(m["model"]) + (" <span class='tag'>est.</span>" if m["estimated"] else ""),
            _fmt_int(m["input_tokens"]),
            _fmt_int(m["output_tokens"]),
            f"${m['cost']:.4f}",
        ]
        for m in metrics["per_model"]
    ]
    tool_rows = [
        [_esc(t["tool"]), str(t["calls"]), _fmt_int(t["result_tokens"]), str(t["errors"])]
        for t in metrics["per_tool"]
    ]
    file_rows = [[f"<code>{_esc(f['file'])}</code>", str(f["reads"])] for f in metrics["top_files"]]
    sess_rows = [
        [
            f"<code>{_esc(x['session_id'])}</code>",
            str(x["messages"]),
            _fmt_int(x["input_tokens"]),
            _fmt_int(x["output_tokens"]),
            f"${x['cost']:.4f}",
            _esc(", ".join(x["models"]) or "—"),
        ]
        for x in metrics["per_session"]
    ]
    flags = "\n".join(f"<li>{_esc(f)}</li>" for f in metrics["waste_flags"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TokenWatch Report</title>
<style>
  :root {{ --bg:#0f1115; --panel:#171b22; --line:#2a3140; --txt:#e8ecf3;
          --dim:#9aa4b5; --accent:#6ea8fe; --warn:#f0b429; --ok:#4cc38a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         background:var(--bg); color:var(--txt); line-height:1.5; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:32px 20px 64px; }}
  header h1 {{ margin:0 0 4px; font-size:28px; }}
  header p {{ margin:0 0 24px; color:var(--dim); }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:28px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; }}
  .card-title {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); }}
  .card-big {{ font-size:30px; font-weight:700; margin:6px 0; }}
  .card-small {{ font-size:13px; color:var(--dim); }}
  h2 {{ font-size:18px; margin:32px 0 12px; border-bottom:1px solid var(--line); padding-bottom:6px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--dim); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.05em; }}
  tr:hover td {{ background:#1c222c; }}
  td:nth-child(n+2), th:nth-child(n+2) {{ text-align:right; }}
  td:first-child, th:first-child {{ text-align:left; }}
  code {{ background:#222a38; padding:2px 6px; border-radius:4px; font-size:13px; }}
  .tag {{ font-size:11px; color:var(--warn); border:1px solid var(--warn); border-radius:4px; padding:0 4px; }}
  .bars {{ display:flex; flex-direction:column; gap:8px; }}
  .bar-row {{ display:flex; align-items:center; gap:10px; font-size:14px; }}
  .bar-label {{ width:110px; color:var(--dim); font-variant-numeric:tabular-nums; }}
  .bar-track {{ flex:1; background:#222a38; border-radius:4px; height:18px; }}
  .bar-fill {{ display:block; height:100%; background:var(--accent); border-radius:4px; }}
  .bar-val {{ width:80px; text-align:right; font-variant-numeric:tabular-nums; }}
  ul.flags {{ list-style:none; padding:0; margin:0; }}
  ul.flags li {{ background:var(--panel); border-left:3px solid var(--warn); padding:10px 14px;
                 margin-bottom:8px; border-radius:0 8px 8px 0; font-size:14px; }}
  footer {{ margin-top:40px; color:var(--dim); font-size:13px; border-top:1px solid var(--line); padding-top:12px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🔍 TokenWatch Report</h1>
    <p>Token &amp; cost observability for coding-agent sessions &middot; generated {generated}</p>
  </header>
  {_cards(s, metrics["waste_flags"])}
  <h2>Waste flags</h2>
  <ul class="flags">
{flags}
  </ul>
  <h2>Cost per day</h2>
  {_bars(metrics["per_day"])}
  <h2>Cost by model</h2>
  {_table(["Model", "Input tokens", "Output tokens", "Est. cost"], model_rows)}
  <h2>Tool usage</h2>
  {_table(["Tool", "Calls", "Result tokens (est.)", "Errors"], tool_rows)}
  <h2>Most-read files</h2>
  {_table(["File", "Reads"], file_rows)}
  <h2>Sessions</h2>
  {_table(["Session", "Assistant msgs", "Input tokens", "Output tokens", "Est. cost", "Models"], sess_rows)}
  <footer>
    {_esc(s["price_note"])}
    {"Some costs are estimated because the model was not in the price table." if s["cost_estimated"] else ""}
    {s["warnings"]} malformed log line(s) skipped during parsing.
  </footer>
</div>
</body>
</html>
"""
