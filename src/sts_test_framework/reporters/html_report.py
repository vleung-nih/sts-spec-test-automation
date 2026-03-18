"""
Generate a static HTML table: operation id, summary, path, expected/actual status, errors.
"""
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


def write_html_report(
    summary: dict,
    results: list[dict],
    out_path: str | Path,
    title: str = "STS v2 API Test Report",
    base_url: str | None = None,
    environment: str | None = None,
) -> None:
    """Build rows from ``results``, render via ``_template``, write UTF-8 HTML to disk."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in results:
        status = "Pass" if r.get("passed") else "Fail"
        duration = r.get("duration")
        duration_str = f"{duration * 1000:.0f} ms" if duration is not None else "-"
        # Path column shows full path including query string (e.g. /model/C3DC/versions?skip=-1&limit=10)
        path_cell = r.get("path_display") or r.get("path", "")
        rows.append({
            "operation_id": r.get("operation_id", ""),
            "summary": r.get("summary", ""),
            "path": path_cell,
            "status": status,
            "expected": r.get("expected_status"),
            "actual": r.get("actual_status"),
            "duration": duration_str,
            "error": r.get("error") or "",
        })

    if environment is None and base_url:
        try:
            environment = urlparse(base_url).netloc or base_url
        except Exception:
            environment = base_url

    html = _template(title, summary, rows, base_url=base_url, environment=environment)
    path.write_text(html, encoding="utf-8")


def _template(
    title: str,
    summary: dict,
    rows: list[dict],
    base_url: str | None = None,
    environment: str | None = None,
) -> str:
    """Assemble full HTML document string with inline CSS and result table rows."""
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    p95 = summary.get("p95_ms")
    p95_str = f"{p95} ms" if p95 is not None else "N/A"

    env_block = ""
    if base_url is not None or environment is not None:
        env_lines = []
        if environment is not None:
            env_lines.append(f"<strong>Environment:</strong> {_esc(environment)}")
        if base_url is not None:
            env_lines.append(f"<strong>URL:</strong> <code>{_esc(base_url)}</code>")
        env_block = '<div class="env">' + " &nbsp;|&nbsp; ".join(env_lines) + "</div>"

    rows_html = "".join(
        f"""
        <tr>
            <td>{_esc(r['operation_id'])}</td>
            <td>{_esc(r['summary'])}</td>
            <td><code>{_esc(r['path'])}</code></td>
            <td class="status-{r['status'].lower()}">{r['status']}</td>
            <td>{r['expected']}</td>
            <td>{r['actual']}</td>
            <td>{_esc(r['duration'])}</td>
            <td>{_esc(r['error'][:200] if r['error'] else '')}</td>
        </tr>
        """
        for r in rows
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{_esc(title)}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 1rem 2rem; }}
        h1 {{ margin-bottom: 0.25rem; }}
        .meta {{ color: #666; margin-bottom: 0.5rem; }}
        .env {{ color: #444; margin-bottom: 1rem; font-size: 0.95rem; }}
        .env code {{ background: #f0f0f0; padding: 0.15rem 0.4rem; border-radius: 3px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }}
        th {{ background: #f5f5f5; }}
        .status-pass {{ background: #d4edda; color: #155724; font-weight: 600; }}
        .status-fail {{ background: #f8d7da; color: #721c24; font-weight: 600; }}
        .summary {{ margin-bottom: 1.5rem; }}
        .summary span {{ margin-right: 1.5rem; }}
    </style>
</head>
<body>
    <h1>{_esc(title)}</h1>
    <p class="meta">Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
    {env_block}
    <div class="summary">
        <span><strong>Total:</strong> {total}</span>
        <span><strong>Passed:</strong> {passed}</span>
        <span><strong>Failed:</strong> {failed}</span>
        <span><strong>P95 response:</strong> {p95_str}</span>
    </div>
    <table>
        <thead>
            <tr>
                <th>Operation ID</th>
                <th>Summary</th>
                <th>Path</th>
                <th>Status</th>
                <th>Expected</th>
                <th>Actual</th>
                <th>Duration</th>
                <th>Error</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
</body>
</html>
"""


def _esc(s: str) -> str:
    """Escape HTML special characters for safe insertion in templates."""
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
