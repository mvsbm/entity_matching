"""The page's server: its link, its commands, its layout against the declarations."""
import json
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
        status, d = call("GET", "/api/commands")
        assert status == 200 and [c["name"] for c in d["commands"]] == [c.name for c in cli.COMMANDS] and d["workspace"] == str(tmp_path / "run")
        assert call("GET", "/")[0] == 200
        line, j = job("resolve records", {"input": str(tmp_path / "all.parquet"), "workspace": str(tmp_path / "run")})
        assert line == f"nayose resolve records {tmp_path / 'all.parquet'} --workspace {tmp_path / 'run'}" and j["exit"] == 0
        assert {e["event"] for e in j["events"]} == {"step", "result"}  # each step as it finished, then the result
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
        assert not server.jobs  # a job the page has read to its end is dropped
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
