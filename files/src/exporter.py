"""exporter.py - JSON/HTML export for default element scanner mode."""

import json
import os
from datetime import datetime
from urllib.parse import urlparse


def _safe_name(url: str) -> str:
        host = urlparse(url).netloc.replace(".", "_").replace(":", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"report_{host}_{ts}"


def export_json(result, out_dir: str = "reports") -> str:
        os.makedirs(out_dir, exist_ok=True)
        filename = _safe_name(result.url) + ".json"
        path = os.path.join(out_dir, filename)

        with open(path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

        return path


def export_html(result, out_dir: str = "reports") -> str:
        os.makedirs(out_dir, exist_ok=True)
        filename = _safe_name(result.url) + ".html"
        path = os.path.join(out_dir, filename)

        forms_rows = "".join(
                f"<tr><td>{i}</td><td>{f.method}</td><td>{f.fields}</td><td>{f.action or '(same page)'}</td></tr>"
                for i, f in enumerate(result.forms[:100], start=1)
        )
        links_rows = "".join(
                f"<tr><td>{i}</td><td>{l.kind}</td><td>{l.text}</td><td>{l.href}</td></tr>"
                for i, l in enumerate(result.links[:200], start=1)
        )
        buttons_rows = "".join(
                f"<tr><td>{i}</td><td>{b.type}</td><td>{b.text}</td></tr>"
                for i, b in enumerate(result.buttons[:100], start=1)
        )

        html = f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>WebScanner Report - {result.page_title or result.url}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; }}
        h1, h2 {{ margin: 0 0 12px; }}
        .meta {{ margin-bottom: 18px; color: #444; }}
        .cards {{ display: grid; grid-template-columns: repeat(3, minmax(120px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
        .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; }}
        .label {{ font-size: 12px; color: #666; }}
        .value {{ font-size: 24px; font-weight: 700; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0 24px; }}
        th, td {{ border: 1px solid #e5e5e5; padding: 8px; text-align: left; vertical-align: top; }}
        th {{ background: #f7f7f7; }}
    </style>
</head>
<body>
    <h1>WebScanner Element Report</h1>
    <div class=\"meta\">
        <div><strong>URL:</strong> {result.url}</div>
        <div><strong>Final URL:</strong> {result.final_url}</div>
        <div><strong>Title:</strong> {result.page_title or '(no title)'}</div>
        <div><strong>Scan Time:</strong> {result.scan_time_s}s</div>
    </div>

    <div class=\"cards\">
        <div class=\"card\"><div class=\"label\">Forms</div><div class=\"value\">{result.total_forms}</div></div>
        <div class=\"card\"><div class=\"label\">Links</div><div class=\"value\">{result.total_links}</div></div>
        <div class=\"card\"><div class=\"label\">Buttons</div><div class=\"value\">{result.total_buttons}</div></div>
    </div>

    <h2>Forms</h2>
    <table>
        <thead><tr><th>#</th><th>Method</th><th>Fields</th><th>Action</th></tr></thead>
        <tbody>{forms_rows or '<tr><td colspan="4">No forms found</td></tr>'}</tbody>
    </table>

    <h2>Links</h2>
    <table>
        <thead><tr><th>#</th><th>Kind</th><th>Text</th><th>Href</th></tr></thead>
        <tbody>{links_rows or '<tr><td colspan="4">No links found</td></tr>'}</tbody>
    </table>

    <h2>Buttons</h2>
    <table>
        <thead><tr><th>#</th><th>Type</th><th>Text</th></tr></thead>
        <tbody>{buttons_rows or '<tr><td colspan="3">No buttons found</td></tr>'}</tbody>
    </table>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
                f.write(html)

        return path
