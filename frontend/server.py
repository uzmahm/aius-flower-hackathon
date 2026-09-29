"""Live console for the event planner. This is the whole front end.

Watches a SuperLink for new event-planner runs. When one starts (you sent a
prompt in `flwr chat`), it opens a window and streams the leader's `UI_EVENT`
lines from `flwr log --stream` into it over Server-Sent Events.

    uv run --project backend python frontend/server.py                    # local
    uv run --project backend python frontend/server.py --superlink supergrid
    uv run --project backend python frontend/server.py --demo             # offline

It reads nothing but the run log and the user profiles on this machine. The
private panels it draws are a narrator's view, never anything that crossed
the network -- see frontend/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
ROOT = UI_DIR.parent
BACKEND_DIR = ROOT / "backend"
LOG_DIR = ROOT / "logs"
PREFIX = "UI_EVENT "
ANSI = re.compile(r"\x1b\[[0-9;]*m")
APP_MARKER = "event-planner"

sys.path.insert(0, str(BACKEND_DIR))
from event_planner import profiles as user_profiles  # noqa: E402


class Hub:
    """Holds the current session's events and fans them out to windows."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.clients: list[queue.Queue] = []
        self.session = 0
        self.nodes: dict | None = None  # latest "nodes" event, kept across sessions

    def reset(self, **info) -> None:
        with self.lock:
            self.session += 1
            self.events = [{"kind": "session", "session": self.session, **info}]
            for client in self.clients:
                client.put(self.events[0])

    def publish(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)
            for client in self.clients:
                client.put(event)

    def set_nodes(self, nodes: list[dict]) -> None:
        """Publish who is connected, but only when it changed."""
        event = {"kind": "nodes", "nodes": nodes}
        with self.lock:
            if event == self.nodes:
                return
            self.nodes = event
            for client in self.clients:
                client.put(event)

    def subscribe(self) -> tuple[queue.Queue, list[dict]]:
        client: queue.Queue = queue.Queue()
        with self.lock:
            self.clients.append(client)
            return client, list(self.events) + ([self.nodes] if self.nodes else [])

    def unsubscribe(self, client: queue.Queue) -> None:
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def has_clients(self) -> bool:
        with self.lock:
            return bool(self.clients)


HUB = Hub()


def profiles() -> dict:
    """Narrator view of every user on this machine. Never sent anywhere.

    Read straight off disk, so a user you spawn with scripts/new_user.py
    shows up in the console with no change here.
    """
    return {
        user: {
            "display_name": entry.get("display_name", user.title()),
            "emoji": entry.get("emoji", "🙂"),
            "role": entry.get("role", "participant"),
            "private": entry.get("private", {}),
        }
        for user, entry in user_profiles.load_all().items()
    }


def local_user_map() -> dict[str, str]:
    """node_id -> user slug, read from the SuperNode logs in logs/.

    Local SuperNodes have no registered names, so the console learns who is
    who from the logs on this machine. On SuperGrid the node names are used.
    """
    mapping: dict[str, str] = {}
    for log in LOG_DIR.glob("supernode-*.log"):
        user = log.stem.removeprefix("supernode-")
        for match in re.finditer(r"SuperNode ID: (\d+)", ANSI.sub("", log.read_text())):
            mapping[match.group(1)] = user
    return mapping


# node_id -> user slug learned from runs. A remote joiner's profile never
# reaches this machine, so their name is only known once a run's identity
# round has asked for it.
SEEN_NAMES: dict[str, str] = {}


def enrich(event: dict) -> dict:
    """Attach a user slug to every node in the roster event.

    The leader already reports one from the identity round; this fills in the
    gap for any node that did not answer it.
    """
    if event.get("kind") == "reply" and event.get("phase") == "identity":
        user = (event.get("fields") or {}).get("user")
        if user:
            SEEN_NAMES[str(event["node"])] = user
    if event.get("kind") == "roster":
        known = set(user_profiles.available())
        mapping = local_user_map()
        for node in event.get("nodes", []):
            name = (node.get("name") or "").lower()
            node["user"] = (
                node.get("user")
                or (name if name in known else None)
                or mapping.get(node["id"])
            )
            if node["user"]:
                SEEN_NAMES[str(node["id"])] = node["user"]
    return event


def parse(line: str) -> dict | None:
    line = ANSI.sub("", line)
    at = line.find(PREFIX)
    if at == -1:
        return None
    try:
        return json.loads(line[at + len(PREFIX):])
    except ValueError:
        return None


# --- opening the window ---------------------------------------------------

def open_window(url: str) -> None:
    """A separate app-style window if Chrome is there, else the default browser."""
    chrome = "/Applications/Google Chrome.app"
    if sys.platform == "darwin" and os.path.exists(chrome):
        subprocess.Popen(
            ["open", "-na", chrome, "--args", f"--app={url}", "--window-size=1440,900"]
        )
    else:
        webbrowser.open_new(url)


def show(url: str) -> None:
    """Open a window unless one is already watching."""
    if not HUB.has_clients():
        open_window(url)


# --- following runs ---------------------------------------------------------

def flwr(*args: str) -> list[str]:
    exe = shutil.which("flwr")
    if exe is None:
        sys.exit(
            "flwr not found. Run via: "
            "uv run --project backend python frontend/server.py"
        )
    return [exe, *args]


def list_runs(superlink: str) -> list[dict]:
    try:
        out = subprocess.run(
            flwr("list", superlink, "--format", "json"),
            capture_output=True, text=True, timeout=30,
        ).stdout
        return json.loads(out).get("runs", [])
    except (subprocess.SubprocessError, ValueError):
        return []


def run_finished(run_id: str, superlink: str) -> bool:
    for run in list_runs(superlink):
        if run["run-id"] == run_id:
            return str(run.get("status", "")).startswith("finished")
    return False


def follow(run_id: str, superlink: str) -> None:
    """Poll one run's log and publish each UI event once.

    `flwr log --stream` opened the moment a run is created can hang without
    ever printing, so the whole log is re-read every couple of seconds and
    events are de-duplicated by their sequence number.
    """
    seen: set[int] = set()
    while True:
        finished = run_finished(run_id, superlink)
        try:
            out = subprocess.run(
                flwr("log", run_id, superlink, "--show"),
                capture_output=True, text=True, timeout=60,
            ).stdout
        except subprocess.SubprocessError:
            out = ""
        for line in out.splitlines():
            event = parse(line)
            if event is None or event.get("seq") in seen:
                continue
            seen.add(event.get("seq"))
            HUB.publish(enrich(event))
        if finished:
            break
        time.sleep(2)
    HUB.publish({"kind": "stream_closed", "run_id": run_id})


FOLLOWING: set[str] = set()


def start_following(run_id: str, superlink: str, url: str) -> None:
    if run_id in FOLLOWING:
        return
    FOLLOWING.add(run_id)
    HUB.reset(run_id=run_id, source=superlink, profiles=profiles())
    show(url)
    threading.Thread(target=follow, args=(run_id, superlink), daemon=True).start()


def watch(superlink: str, url: str) -> None:
    """Poll for new event-planner runs and follow each one."""
    runs = list_runs(superlink)
    known = {run["run-id"] for run in runs}
    print(f"Watching {superlink} for new {APP_MARKER} runs "
          f"({len(known)} existing ignored). Send a prompt in flwr chat.")
    for run in runs:
        if APP_MARKER in str(run.get("fab-id", "")) and not str(run.get("status", "")).startswith("finished"):
            print(f"Run {run['run-id']} already in progress -> following it")
            start_following(run["run-id"], superlink, url)
    while True:
        for run in list_runs(superlink):
            run_id = run["run-id"]
            if run_id in known:
                continue
            known.add(run_id)
            if APP_MARKER not in str(run.get("fab-id", "")):
                continue
            print(f"New run {run_id} -> opening console")
            start_following(run_id, superlink, url)
        time.sleep(2)


def watch_nodes(superlink: str) -> None:
    """Keep the console's "who's here" list in step with the SuperLink."""
    while True:
        try:
            out = subprocess.run(
                flwr("supernode", "list", superlink, "--format", "json"),
                capture_output=True, text=True, timeout=30,
            ).stdout
            listed = json.loads(out).get("nodes", [])
        except (subprocess.SubprocessError, ValueError):
            listed = None
        if listed is not None:
            local = local_user_map()
            HUB.set_nodes([
                {
                    "id": str(node["node-id"]),
                    "user": local.get(str(node["node-id"])) or SEEN_NAMES.get(str(node["node-id"])),
                    "local": str(node["node-id"]) in local,
                    "status": node.get("status", "unknown"),
                }
                for node in listed
                if node.get("status") != "unregistered"
            ])
        time.sleep(3)


def demo(url: str, speed: float = 1.0) -> None:
    """Replay a simulated run with pauses, so the console can be rehearsed."""
    out = subprocess.run(
        [sys.executable, "-m", "event_planner.simulate"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)},
    ).stdout
    events = [e for e in map(parse, out.splitlines()) if e]
    HUB.reset(run_id="demo", source="simulate", profiles=profiles())
    show(url)
    for _ in range(50):  # give the window a moment to connect
        if HUB.has_clients():
            break
        time.sleep(0.1)
    time.sleep(1.5 / speed)
    pauses = {"start": 1.6, "roster": 2.0, "ask": 1.4, "reply": 1.1, "round": 1.8,
              "tally": 2.2, "consensus": 1.5, "done": 0}
    for event in events:
        HUB.publish(enrich(event))
        time.sleep(pauses.get(event["kind"], 1.0) / speed)


# --- HTTP ---------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # keep the terminal quiet
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = (UI_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/events":
            self.stream()
        elif self.path == "/demo":
            threading.Thread(target=demo, args=(self.server.url, self.server.speed), daemon=True).start()
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        client, backlog = HUB.subscribe()
        try:
            hello = {"kind": "hello", "profiles": profiles()}
            for event in [hello, *backlog]:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    event = client.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            HUB.unsubscribe(client)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--superlink", default="local-agent",
                        help="SuperLink connection from ~/.flwr/config.toml")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--demo", action="store_true",
                        help="replay a simulated run instead of watching a SuperLink")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="demo replay speed multiplier (2 = twice as fast)")
    parser.add_argument("--run", metavar="RUN_ID",
                        help="also show this run, even if it has already finished")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.url = f"http://127.0.0.1:{args.port}/"
    server.speed = args.speed
    print(f"Console at {server.url}")

    if args.demo:
        threading.Thread(target=demo, args=(server.url, args.speed), daemon=True).start()
    else:
        if args.run:
            start_following(args.run, args.superlink, server.url)
        threading.Thread(target=watch, args=(args.superlink, server.url), daemon=True).start()
        threading.Thread(target=watch_nodes, args=(args.superlink,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
