import os
import re


def test_no_cdn_in_templates():
    """4.0: All JS libraries must be vendored, no external CDN refs in templates."""
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    for fname in os.listdir(templates_dir):
        if not fname.endswith(".html"):
            continue
        path = os.path.join(templates_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # reject any cdn.jsdelivr.net, unpkg, or other external script src
        matches = re.findall(r'<script[^>]*src=["\'](https?://[^"\']+)["\'][^>]*>', content)
        if matches:
            raise AssertionError(
                f"Template {fname} references external CDN: {matches}",
            )

def test_chart_js_vendored():
    """Chart.js UMD bundle must exist in static/."""
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    assert os.path.exists(os.path.join(static_dir, "chart.umd.min.js")), "chart.umd.min.js not vendored"
