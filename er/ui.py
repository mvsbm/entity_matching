"""nayose open ui: the commands in a browser, on this machine only. The page (er/ui.html) holds the screens: which
commands each one places, in which order, with which parameters taken from what the person typed, and how it draws
their results. The server knows nothing of the screens. It serves the page and three endpoints:

    GET  /api/commands          every command's declaration (er.cli.COMMANDS): the page builds its forms from them
    POST /api/run               {"command": "list pairs", "args": {...}} → the job, and the nayose command it runs;
                                with "dry": true, the command only, for the page to show before it runs
    GET  /api/job/<id>?from=n   the job's events from the n-th on, whether it ended, and its exit code

Each job is parsed by nayose's own parser, built to raise a refusal rather than print it and exit: quick jobs run in
threads, which can't share the process's stderr. A quick command (a list, a describe, one answer) runs in this
process; any other runs as python -m er.cli … --format json in a process of its own, one at a time, so a crash or a
memory spike can't take the page down. A finished job is dropped once the page has read its last events. The server binds 127.0.0.1; every request needs the token in the link it prints, and a Host
of 127.0.0.1 or localhost, so neither another user of the machine nor a web page elsewhere can use it.
"""
import argparse
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
                              required=p.required, optional=p.optional, metavar=p.shown) for p in c.params]) for c in cli.COMMANDS]


def command(name: str) -> cli.Command:
    if (c := next((c for c in cli.COMMANDS if c.name == name), None)) is None:
        raise InputError(f"no command {name}", fix="the commands: " + ", ".join(x.name for x in cli.COMMANDS))
    return c


def argv(name: str, args: dict) -> list[str]:
    """The command line for a command and the values the page gives its parameters: what the page shows and runs."""
    c = command(name)
    if unknown := set(args) - {p.name for p in c.params}:
        raise InputError(f"{name} has no parameter {', '.join(sorted(unknown))}", fix=f"see nayose {name} --help")
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


def fail(job: Job, error: str, code: int, fix: str = "") -> None:  # the job's end, as an error event cli.Emit writes
    Collect(job).error(InputError(error, fix), code)
    job.code = code


class Refusing(argparse.ArgumentParser):
    """nayose's parser for the page: a refusal raised, never printed to the process's stderr and exited."""

    def error(self, message: str) -> None:
        raise InputError(message, fix=f"{self.prog} --help says what it takes")


class Server:
    def __init__(self, workspace: str | None = None, home: str = "workspaces"):
        self.token, self.jobs, self.lock, self.long = secrets.token_urlsafe(24), {}, threading.Lock(), threading.Lock()
        self.workspace = workspace            # the workspace the page starts with
        self.home = home                      # the folder its workspaces are in

    def start(self, name: str, args: dict) -> tuple[str, Job]:
        words = argv(name, args)
        job, key = Job(words), secrets.token_hex(8)
        with self.lock:
            self.jobs[key] = job
        threading.Thread(target=self._quick if command(name).quick else self._long, args=(job,), daemon=True).start()
        return key, job

    def _quick(self, job: Job) -> None:
        emit = Collect(job)
        try:
            a = cli.parser(Refusing).parse_args([*job.words, "--format", "json"])
            result = a.command.run({p.name: getattr(a, p.name) for p in a.command.params}, emit)
            result.pop("exit_code", None)
            emit.result(a.command, result)
            job.code = 0
        except InputError as e:  # the parser's refusal, or a mistake people fix
            fail(job, str(e), 75 if isinstance(e, cli.Busy) else 2, e.fix)
        except (Exception, SystemExit) as e:  # a bug, or argparse leaving (an ID typed as -h): its message, so the page doesn't hang
            oom = cli.out_of_memory(e)
            fail(job, str(oom), 2, oom.fix) if oom else fail(job, f"{type(e).__name__}: {e}", 1)

    def _long(self, job: Job) -> None:
        if not self.long.acquire(blocking=False):
            return fail(job, "another long command is running", 75, "wait for it to finish")
        try:  # stderr joins stdout: one pipe, read to its end, so a long traceback can't fill a pipe no one reads
            done = subprocess.Popen([sys.executable, "-m", "er.cli", *job.words, "--format", "json"], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            other = []
            for line in done.stdout:  # each step as it finishes; anything else is a crash's traceback
                try:
                    job.events.append(json.loads(line))
                except json.JSONDecodeError:
                    other.append(line.strip())
            code = done.wait()
            if code and not any(e.get("event") == "error" for e in job.events):  # a crash: the last line of its traceback
                return fail(job, " ".join(x for x in other if x)[-300:] or f"exit {code}", code)
            job.code = code
        except OSError as e:  # the process didn't start
            fail(job, f"{type(e).__name__}: {e}", 1)
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
                self._send(200, dict(commands=declarations(), workspace=server.workspace, home=server.home))
            elif url.path.startswith("/api/job/") and (job := server.jobs.get(key := url.path.rsplit("/", 1)[1])):
                done = job.code is not None  # read first: a finished job's events are all there
                events = job.events[int(parse_qs(url.query).get("from", ["0"])[0]):]
                if done:  # its last events go now: nothing keeps a job the page has read
                    with server.lock:
                        server.jobs.pop(key, None)
                self._send(200, dict(events=events, done=done, exit=job.code))
            else:
                self._send(404, {"error": "no such page"})

        def do_POST(self) -> None:
            if not self._allowed():
                return
            if urlparse(self.path).path != "/api/run":
                return self._send(404, {"error": "no such page"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if body.get("dry"):  # the equivalent command line, from the code that runs it
                    return self._send(200, dict(command=shlex.join(["nayose", *argv(body.get("command", ""), body.get("args") or {})])))
                key, job = server.start(body.get("command", ""), body.get("args") or {})
            except (InputError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e), "fix": getattr(e, "fix", "")})
            self._send(200, dict(job=key, command=shlex.join(["nayose", *job.words])))
    return Handler


def serve(port: int, workspace: str | None, home: str, say, open_browser: bool = True) -> None:
    """Serve the page on 127.0.0.1:port until stopped (Ctrl-C)."""
    server = Server(workspace, home)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler(server))
    link = f"http://127.0.0.1:{httpd.server_address[1]}/?token={server.token}"
    say(f"open {link}\n  only this machine can reach it, and only with this link; Ctrl-C stops it", link=link)
    if open_browser:
        webbrowser.open(link)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
