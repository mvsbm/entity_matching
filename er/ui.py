"""nayose open ui: the commands in a browser, on this machine only. The page (er/ui.html) holds the screens: which
commands each one places, in which order, with which parameters taken from what the person typed, and how it draws
their results. The server knows nothing of the screens. It serves the page and three endpoints:

    GET  /api/commands          every command's declaration (er.cli.COMMANDS): the page builds its forms from them
    POST /api/run               {"command": "list pairs", "args": {...}} → the job, and the nayose command it runs
    GET  /api/job/<id>?from=n   the job's events from the n-th on, whether it ended, and its exit code

Each job is parsed by nayose's own parser. A quick command (a list, a describe, one answer) runs in this process; any
other runs as python -m er.cli … --format json in a process of its own, one at a time, so a crash or a memory spike
can't take the page down. The server binds 127.0.0.1; every request needs the token in the link it prints, and a Host
of 127.0.0.1 or localhost, so neither another user of the machine nor a web page elsewhere can use it.
"""
import contextlib
import io
import json
import secrets
import shlex
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from er import cli
from er.config import InputError

PAGE = Path(__file__).with_name("ui.html")


def declarations() -> list[dict]:
    """What the page needs of each command to place it and build its form: the declaration, as data."""
    return [dict(name=c.name, verb=c.verb, noun=c.noun, help=c.help, about=c.about, example=c.example, quick=c.quick, result=c.result,
                 params=[dict(name=p.name, help=p.help, kind=p.kind, choices=list(p.choices), positional=p.positional,
                              required=p.required, metavar=p.shown) for p in c.params]) for c in cli.COMMANDS]


def argv(command: str, args: dict) -> list[str]:
    """The command line for a command and the values the page gives its parameters: what the page shows and runs."""
    c = next((c for c in cli.COMMANDS if c.name == command), None)
    if c is None:
        raise InputError(f"no command {command}", fix="the commands: " + ", ".join(x.name for x in cli.COMMANDS))
    if unknown := set(args) - {p.name for p in c.params}:
        raise InputError(f"{command} has no parameter {', '.join(sorted(unknown))}", fix="see nayose " + command + " --help")
    words = [c.verb, c.noun]
    for p in c.params:
        v = args.get(p.name)
        if v in (None, "", False, []):
            continue
        values = [str(x) for x in v] if isinstance(v, list) else [str(v)]
        if p.kind == "flag":
            words.append(f"--{p.name}")
        else:
            words += values if p.positional else [f"--{p.name}", *values]
    return words


@dataclass
class Job:
    words: list[str]
    events: list[dict] = field(default_factory=list)
    code: int | None = None                   # None while it runs


class Collect(cli.Emit):  # a quick command's events, kept for the page as JSON would carry them
    def __init__(self, job: Job):
        super().__init__("json")
        self.job = job

    def _json(self, event: str, x: dict) -> None:
        self.job.events.append({"event": event, **cli.plain(x)})


class Server:
    def __init__(self, run: str | None = None):
        self.token, self.jobs, self.lock, self.long = secrets.token_urlsafe(24), {}, threading.Lock(), threading.Lock()
        self.run = run                        # the run folder the page starts with

    def start(self, command: str, args: dict) -> tuple[str, Job]:
        words = argv(command, args)
        job, key = Job(words), secrets.token_hex(8)
        with self.lock:
            self.jobs[key] = job
        quick = next(c for c in cli.COMMANDS if c.name == command).quick
        threading.Thread(target=self._quick if quick else self._long, args=(job,), daemon=True).start()
        return key, job

    def _quick(self, job: Job) -> None:
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                a = cli.parser().parse_args([*job.words, "--format", "json"])
        except SystemExit:  # the parser refused it, as it would on the command line
            job.events.append(dict(event="error", error=err.getvalue().strip().splitlines()[-1], fix="", hints={}, exit=2))
            job.code = 2
            return
        emit = Collect(job)
        try:
            result = a.command.run({p.name: getattr(a, p.name) for p in a.command.params}, emit)
            result.pop("exit_code", None)
            emit.result(a.command, result)
            job.code = 0
        except InputError as e:
            job.code = 75 if isinstance(e, cli.Busy) else 2
            emit.error(e, job.code)
        except Exception as e:  # a bug, not a mistake people fix: its message, so the page doesn't hang
            job.events.append(dict(event="error", error=f"{type(e).__name__}: {e}", fix="", hints={}, exit=1))
            job.code = 1

    def _long(self, job: Job) -> None:
        if not self.long.acquire(blocking=False):
            job.events.append(dict(event="error", error="another long command is running", fix="wait for it to finish", hints={}, exit=75))
            job.code = 75
            return
        try:
            done = subprocess.Popen([sys.executable, "-m", "er.cli", *job.words, "--format", "json"], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1)
            for line in done.stdout:  # each step as it finishes
                with contextlib.suppress(json.JSONDecodeError):
                    job.events.append(json.loads(line))
            code = done.wait()
            if code and not any(e.get("event") == "error" for e in job.events):  # a crash: the last lines of its traceback
                job.events.append(dict(event="error", error=" ".join(done.stderr.read().strip().splitlines()[-1:]), fix="", hints={}, exit=code))
            job.code = code
        finally:
            self.long.release()


def handler(server: Server):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # quiet: the terminal shows the link only
            pass

        def _allowed(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            token = self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if host not in ("127.0.0.1", "localhost") or not secrets.compare_digest(token, server.token):
                self._send(403, {"error": "this page needs the link nayose open ui printed"})
                return False
            return True

        def _send(self, status: int, body: object, kind: str = "application/json") -> None:
            data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self._allowed():
                return
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, PAGE.read_text(encoding="utf-8"), "text/html")
            elif url.path == "/api/commands":
                self._send(200, dict(commands=declarations(), run=server.run))
            elif url.path.startswith("/api/job/") and (job := server.jobs.get(url.path.rsplit("/", 1)[1])):
                start = int(parse_qs(url.query).get("from", ["0"])[0])
                self._send(200, dict(events=job.events[start:], done=job.code is not None, exit=job.code))
            else:
                self._send(404, {"error": "no such page"})

        def do_POST(self) -> None:
            if not self._allowed():
                return
            if urlparse(self.path).path != "/api/run":
                return self._send(404, {"error": "no such page"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                key, job = server.start(body.get("command", ""), body.get("args") or {})
            except (InputError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e), "fix": getattr(e, "fix", "")})
            self._send(200, dict(job=key, command=shlex.join(["nayose", *job.words])))
    return Handler


def serve(port: int, run: str | None, say, open_browser: bool = True) -> None:
    """Serve the page on 127.0.0.1:port until stopped (Ctrl-C)."""
    server = Server(run)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler(server))
    link = f"http://127.0.0.1:{httpd.server_address[1]}/?token={server.token}"
    say(f"open {link}\n  only this machine can reach it, and only with this link; Ctrl-C stops it", link=link)
    if open_browser:
        webbrowser.open(link)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
