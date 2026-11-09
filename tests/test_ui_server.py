"""The page's server: its link, its commands, its layout against the declarations."""
import json
import shlex
from pathlib import Path





def test_the_ui_serves_only_its_own_link_and_runs_the_commands_as_nayose_does(tmp_path, population):
    import http.client
    import threading
    import time
    from http.server import ThreadingHTTPServer
    from er import cli, ui
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    server = ui.Server(str(tmp_path / "run"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.handler(server))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method: str, path: str, body: dict | None = None, token: str = server.token, host: str = f"127.0.0.1:{port}"):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"X-Token": token, "Host": host})
        r = c.getresponse()
        data = r.read()
        return r.status, json.loads(data) if path.startswith("/api") else data.decode()

    def job(command: str, args: dict) -> tuple[str, dict]:
        status, started = call("POST", "/api/run", dict(command=command, args=args))
        assert status == 200, started
        deadline = time.monotonic() + 120
        while not (j := call("GET", f"/api/job/{started['job']}")[1])["done"]:
            assert time.monotonic() < deadline, f"{command} never ended"
            time.sleep(0.1)
        return started["command"], j

    try:
        assert call("GET", "/api/commands", token="wrong")[0] == 403  # another user of the machine: no link, no page
        assert call("GET", "/api/commands", host="example.com")[0] == 403  # a page elsewhere, through DNS rebinding
        status, page = call("GET", "/", token="old")
        assert status == 403 and "Open the link" in page  # an old link: a page in words
        status, d = call("GET", "/api/commands")
        assert status == 200 and [c["name"] for c in d["commands"]] == [c.name for c in cli.COMMANDS] and d["workspace"] == str(tmp_path / "run")
        assert call("GET", "/")[0] == 200
        line, j = job("resolve records", {"input": str(tmp_path / "all.parquet"), "workspace": str(tmp_path / "run")})
        assert line == shlex.join(["nayose", "resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(tmp_path / "run")]) and j["exit"] == 0
        assert {e["event"] for e in j["events"]} == {"step", "progress", "result"}  # each step as it finished, how far scoring is, then the result
        _, j = job("list pairs", {"workspace": str(tmp_path / "run"), "open": True})
        assert j["exit"] == 0 and j["events"][-1]["pairs"]
        _, j = job("describe entity", {"id": "nobody", "workspace": str(tmp_path / "run")})
        assert j["exit"] == 2 and j["events"][-1]["event"] == "error" and j["events"][-1]["fix"]
        dry = call("POST", "/api/run", dict(command="list pairs", args={"workspace": "r", "open": True}, dry=True))[1]
        assert dry == {"command": "nayose list pairs --workspace r --open"}  # the equivalent command line, nothing run
        assert call("POST", "/api/run", dict(command="list pairs", args={"nope": 1}))[0] == 400  # only declared parameters
        assert call("POST", "/api/run", dict(command="delete everything", args={}))[0] == 400  # only declared commands
        _, j = job("describe entity", {"workspace": str(tmp_path / "run")})  # no ID: nayose's parser refuses it, as on the command line
        assert j["exit"] == 2 and "required" in j["events"][-1]["error"]
        _, j = job("describe entity", {"id": "-h", "workspace": str(tmp_path / "run")})  # a value that looks like an option is a value
        assert j["exit"] == 2 and "SystemExit" not in j["events"][-1]["error"] and "-h" in j["events"][-1]["error"]
        assert server.jobs and all(j.read is not None for j in server.jobs.values())  # read to its end: kept a minute, for a page reloaded meanwhile
        old = next(k for k, j in server.jobs.items() if j.code == 2)
        for j in server.jobs.values():
            j.read -= 61
        _, j = job("list pairs", {"workspace": str(tmp_path / "run")})
        assert len(server.jobs) == 1  # a minute on, the others are gone
        late = call("GET", f"/api/job/{old}")[1]  # a tab that polls late: how it ended, kept
        assert late["done"] and late["exit"] == 2 and late["events"][-1]["event"] == "error"
        assert call("GET", "/api/running")[1] == {}
        status, started = call("POST", "/api/run", dict(command="resolve records", args={"workspace": str(tmp_path / "run"), "overwrite": True}))
        deadline = time.monotonic() + 30
        while not (running := call("GET", "/api/running")[1]):  # a page drawn while it runs finds it
            assert time.monotonic() < deadline
            time.sleep(0.05)
        since = running.pop("since")  # when it began: a page drawn now says how long it has run
        assert running == {"job": started["job"], "command": "resolve records", "workspace": str(tmp_path / "run")} and time.time() - 60 < since <= time.time()
        while not call("GET", f"/api/job/{started['job']}")[1]["done"]:
            time.sleep(0.1)
        assert call("GET", "/api/running")[1] == {}
    finally:
        httpd.shutdown()


def test_quick_commands_at_once_leave_the_process_s_stderr_alone():
    import sys
    import time
    from er import ui
    real, server = sys.stderr, ui.Server("nowhere")
    for _ in range(10):  # the page starts several at once on every load
        jobs = [server.start("list columns", {})[1] for _ in range(8)] + [server.start("describe entity", {"workspace": "nowhere"})[1]]
        deadline = time.monotonic() + 30
        while any(j.code is None for j in jobs):
            assert time.monotonic() < deadline, "a quick job never ended"
            time.sleep(0.01)
        assert sys.stderr is real and jobs[-1].code == 2


def test_the_ui_layout_names_only_declared_commands_parameters_and_result_fields():
    import re
    from er import cli
    html = Path(cli.__file__).with_name("ui.html").read_text(encoding="utf-8")
    layout = json.loads(re.search(r'<script type="application/json" id="layout">(.*?)</script>', html, re.S).group(1))
    declared = {c.name: c for c in cli.COMMANDS}
    for screen in layout["screens"]:
        for u in screen["uses"]:
            c = declared[u["command"]]
            params = {p.name for p in c.params}
            assert set(u["args"]) <= params and set(u.get("form", [])) <= params, (screen["id"], u["command"])
            assert set(u["reads"]) <= set(c.result), (screen["id"], u["command"], set(u["reads"]) - set(c.result))
    placed = {(s["id"], u["command"]) for s in layout["screens"] for u in s["uses"]}
    called = {(m.group(1), m.group(2)) for m in re.finditer(r'(?:run|action)\("(\w+)", "(\w+ \w+)"', html)}
    assert called and called <= placed  # every command the page runs, it runs as the layout places it
    for sc in layout["screens"]:  # a stage's panel runs its commands on whichever page shows it
        need = {"score": {"list patterns", "explain pair", "compare records"}, "candidates": {"describe key"}}
        assert all({(sc["id"], c) for c in need.get(stage, ())} <= placed for stage in sc["strip"]), sc["id"]
    block = html.split("const QUEUES = {", 1)[1].split("\n};", 1)[0]
    named = {(q, c) for q, body in re.findall(r"\n  (\w+): \{title(.*?)(?=\n  \w+: \{title|$)", block, re.S)
             for c in re.findall(r'(?:list|one|apply): "(\w+ \w+)"', body)}
    assert len(named) == 6 and named <= placed  # each review queue's commands, placed on its own page
    from er.report import GRAPH_NODES
    screens, flow = {sc["id"]: sc for sc in layout["screens"]}, layout["workflow"]
    assert all(set(sc["strip"]) <= set(GRAPH_NODES) for sc in screens.values())  # each page's flow strip: stages describe matching gives
    loop = flow["improve"]  # the loop's page: after a step, and back to the one that runs the method again
    assert set(flow["steps"]) <= {*screens, "workspace"} and all(x in flow["steps"] for x in screens if x not in ("records", loop["screen"]))  # every page a step
    assert loop["screen"] in screens and {loop["after"], loop["back"]} <= set(flow["steps"])
    assert all(l["to"] in flow["steps"] and {(l["screen"], c) for c in l["via"]} <= placed for l in flow["loops"])


def test_a_long_command_that_ends_with_its_result_and_exit_2_is_no_crash(tmp_path, fake_cli):
    from er import ui
    fake_cli('print(json.dumps({"event": "step", "step": "load", "seconds": 1.0}))\nprint(json.dumps({"event": "result", "command": "try everything", "ok": False}))\nsys.exit(2)')
    job = ui.Job(["try", "everything", "x.csv"])  # a command that stopped on a mistake people fix, yet said its result (try everything does)
    ui.Server()._long(job)
    assert job.code == 2 and [e["event"] for e in job.events] == ["step", "result"]  # its result, for the page to show
    fake_cli('print("Traceback (most recent call last):")\nprint("KeyError: 1")\nsys.exit(1)')
    job = ui.Job(["try", "everything", "x.csv"])
    ui.Server()._long(job)
    assert job.code == 1 and job.events[-1]["event"] == "error" and "KeyError" in job.events[-1]["error"]  # a crash: said


def test_a_value_like_an_option_stays_a_value_wherever_it_goes():
    from er import cli, ui
    for args, want in (({"id": "a", "between": ["-h", "y"], "workspace": "w"}, ("a", ["-h", "y"])),
                       ({"id": "-A1", "between": ["x", "y"], "workspace": "w"}, ("-A1", ["x", "y"]))):
        a = cli.parser(ui.Refusing).parse_args(ui.as_json(ui.argv("split entity", args)))
        assert (a.id, a.between, a.workspace, a.format) == (*want, "w", "json")
    assert cli.parser().parse_args(["resolve", "records", "f", "--workspace", "w", "--compute", "threads=2", "memory_limit=1GB"]).compute == ["threads=2", "memory_limit=1GB"]


def test_quick_commands_in_bursts_leave_no_threads_behind(tmp_path, population):
    import os
    import subprocess
    import time
    from er import cli, ui
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(tmp_path / "run"), "--format", "json"]) == 0
    task = Path("/proc/self/task")

    def threads() -> int:  # the OS threads of this process: Linux's /proc, macOS's ps, Windows' thread snapshot
        if task.is_dir():
            return len(os.listdir(task))
        if os.name != "nt":
            return subprocess.run(["ps", "-M", str(os.getpid())], capture_output=True, text=True).stdout.count("\n") - 1
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):  # THREADENTRY32
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]
        k = ctypes.WinDLL("kernel32")
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE  # pointer-wide handles
        k.Thread32First.argtypes = k.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        snap, e, n = k.CreateToolhelp32Snapshot(4, 0), Entry(dwSize=ctypes.sizeof(Entry)), 0  # TH32CS_SNAPTHREAD
        more = k.Thread32First(snap, ctypes.byref(e))
        while more:
            n += e.th32OwnerProcessID == os.getpid()
            more = k.Thread32Next(snap, ctypes.byref(e))
        k.CloseHandle(snap)
        return n
    server, ws = ui.Server(str(tmp_path / "run")), str(tmp_path / "run")
    start = threads()
    for _ in range(8):  # a page's loads: several at once, again and again
        jobs = [server.start(c, {"workspace": ws})[1] for c in ("describe workspace", "describe matching", "list pairs", "describe method", "describe review", "list patterns")]
        while any(j.code is None for j in jobs):
            time.sleep(0.05)
    assert threads() < start + 60, (start, threads())  # each command's connections, and their worker threads, gone with it
