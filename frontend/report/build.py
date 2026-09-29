"""Inject trace.json into template.html so the report can never drift.

    uv run --project backend python frontend/report/make_trace.py > frontend/report/trace.json
    uv run --project backend python frontend/report/build.py

Or just: scripts/report.sh
"""

from __future__ import annotations

import pathlib

HERE = pathlib.Path(__file__).parent


def main() -> None:
    """Write report.html from the template and the current trace."""
    template = (HERE / "template.html").read_text()
    trace = (HERE / "trace.json").read_text().strip()
    if "__TRACE__" not in template:
        raise SystemExit("template is missing its __TRACE__ marker")
    # </script> inside embedded JSON would close the host script tag early.
    safe = trace.replace("</", "<\\/")
    out = HERE / "report.html"
    out.write_text(template.replace("__TRACE__", safe))
    print(f"{out} written ({len(out.read_text()):,} bytes)")


if __name__ == "__main__":
    main()
