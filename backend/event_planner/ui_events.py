"""Progress lines for the live console in ../../frontend.

The leader prints one `UI_EVENT {json}` line per protocol step. print() lands
in the run's log, which `flwr log --stream` relays to the console server, so
this works the same against a local SuperLink and on SuperGrid. The lines
carry only what the leader already holds -- offers, bits, the outcome --
never anything from a participant's private profile.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

PREFIX = "UI_EVENT "
_seq = itertools.count()


def emit(kind: str, **data: Any) -> None:
    """Print one console event. `seq` lets the reader drop duplicates."""
    print(PREFIX + json.dumps({"kind": kind, "seq": next(_seq), **data}), flush=True)
