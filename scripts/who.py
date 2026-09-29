#!/usr/bin/env python3
"""Show who has joined the federation: every SuperNode, with its agent's name.

    scripts/who.py                        # local leader
    scripts/who.py --superlink supergrid

Local users are named from logs/supernode-<user>.log. Someone who joined from
another laptop keeps their profile there, so the leader only learns their name
when a run asks every node who it speaks for. After the first prompt in
`flwr chat`, their name comes from the live console's roster.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def list_nodes(superlink: str) -> list[dict]:
    out = subprocess.run(
        ["uv", "run", "--quiet", "--project", str(ROOT / "backend"),
         "flwr", "supernode", "list", superlink, "--format", "json"],
        capture_output=True, text=True,
    ).stdout
    try:
        return json.loads(out).get("nodes", [])
    except ValueError:
        sys.exit(f"Could not list nodes on '{superlink}'. Is the leader running?")


def names_from_logs() -> dict[str, str]:
    names: dict[str, str] = {}
    for log in LOG_DIR.glob("supernode-*.log"):
        user = log.stem.removeprefix("supernode-")
        for match in re.finditer(r"SuperNode ID: (\d+)", ANSI.sub("", log.read_text())):
            names[match.group(1)] = user
    return names


def names_from_console(url: str) -> dict[str, str]:
    """Node -> user from the last run's roster, as the console holds it."""
    names: dict[str, str] = {}
    try:
        stream = urllib.request.urlopen(url, timeout=2)
        for raw in stream:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("kind") == "roster":
                for node in event.get("nodes", []):
                    if node.get("user"):
                        names[str(node["id"])] = node["user"]
            elif event.get("kind") == "reply" and event.get("phase") == "identity":
                user = (event.get("fields") or {}).get("user")
                if user:
                    names[str(event["node"])] = user
    except (OSError, socket.timeout, ValueError):
        pass
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--superlink", default="local-agent")
    parser.add_argument("--console", default="http://127.0.0.1:8765/events")
    args = parser.parse_args()

    nodes = list_nodes(args.superlink)
    local = names_from_logs()
    seen = names_from_console(args.console)

    rows = []
    for node in nodes:
        nid = node["node-id"]
        if nid in local:
            who = f"{local[nid]} (this laptop)"
        elif nid in seen:
            who = f"{seen[nid]} (remote)"
        else:
            who = "remote, name known after the first prompt"
        rows.append((nid, who, node.get("status", "?")))

    width = max([len("Node ID")] + [len(r[0]) for r in rows])
    agent_width = max([len("Agent")] + [len(r[1]) for r in rows])
    print(f"{'Node ID':<{width}}  {'Agent':<{agent_width}}  Status")
    print(f"{'-' * width}  {'-' * agent_width}  ------")
    for nid, who, status in rows:
        print(f"{nid:<{width}}  {who:<{agent_width}}  {status}")
    online = sum(1 for _, _, s in rows if s == "online")
    print(f"\n{online} online")


if __name__ == "__main__":
    main()
