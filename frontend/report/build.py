"""Inject trace.json into ui.template.html so the UI can never drift.

    PYTHONPATH=. python make_trace.py > trace.json
    python build_ui.py
"""

from __future__ import annotations

import pathlib

HERE = pathlib.Path(__file__).parent


def main() -> None:
    """Write ui.html from the template and the current trace."""
    template = (HERE / "ui.template.html").read_text()
    trace = (HERE / "trace.json").read_text().strip()
    if "__TRACE__" not in template:
        raise SystemExit("template is missing its __TRACE__ marker")
    # </script> inside embedded JSON would close the host script tag early.
    safe = trace.replace("</", "<\\/")
    (HERE / "ui.html").write_text(template.replace("__TRACE__", safe))
    print(f"ui.html written ({len((HERE / 'ui.html').read_text()):,} bytes)")


if __name__ == "__main__":
    main()
