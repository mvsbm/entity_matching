"""The page in a browser (Chromium): every step, a lost server, a busy workspace."""
import threading
import time
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from er.settings import load_settings

from conftest import dirty_csv, flag_wrong


def test_the_page_answers_once_per_key_shows_any_row_and_says_when_the_server_is_gone(ui_page, tmp_path, population):
    from er import cli
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = tmp_path / "run"
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(run), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(run), str(tmp_path / "workspaces"))
    page.wait_for_selector(".tiles")
    page.evaluate("setWorkspace('')")  # the first screen of a new user: no workspace
    page.wait_for_selector(".welcome .example .node.static")  # what it does, by an example, before anything else
    assert not page.is_visible("#lost")  # the lost-server banner, only once it is lost
    assert page.inner_text("h1").endswith("Choose a workspace") and page.get_attribute(".rail li:first-child .navitem", "aria-current") == "page"
    assert page.get_attribute(".navitem[data-screen=records]", "aria-current") == "false"  # the highlight is where you are
    assert all(b.is_disabled() for b in page.query_selector_all("[data-loop]")) and page.is_disabled("#search")  # off until the first run
    page.click("#picker")  # a new workspace, from the picker: a folder in the server's workspaces/, with its own mapping
    page.fill("#new-name", "fresh")
    page.click("#create")
    page.wait_for_selector("h1:has-text('Prepare your data')")  # a new workspace opens on its next step
    assert (tmp_path / "workspaces" / "fresh" / "columns.toml").is_file() and not page.query_selector("details.fgroup")  # nothing to fill before a file
    company = s.columns["company_name"][0][0]
    g.df.rename(columns={s.data.unique_id: "customer_no"}).to_parquet(tmp_path / "theirs.parquet", index=False)
    page.fill("#cin", str(tmp_path / "theirs.parquet"))
    page.click("#load")  # copied into it, then described
    page.wait_for_selector("details.fgroup[data-g='ID'][open]", timeout=60_000)  # the ID it can't find opens its group
    assert page.text_content("#files").startswith("theirs.parquet ·") and "Record ID needed" in page.inner_text("details.fgroup[data-g='ID'] summary")
    assert page.inner_text("#loaded h2.question") == "Customer information" and page.inner_text("#loaded .answer").startswith("Not yet")  # what is still needed, first
    loaded, groups = page.query_selector("#loaded").bounding_box(), page.query_selector("#out").bounding_box()
    assert loaded["y"] + loaded["height"] <= groups["y"]  # did it load, then the columns by field: in reading order
    columns = tmp_path / "workspaces" / "fresh" / "columns.toml"
    assert page.evaluate("""async () => {  // a group whose only suggestion is a feature to add, a kanji name: no Keep all beside it
        const w = await run("columns", "describe workspace"), d = await run("columns", "describe records", {loaded: w.inputs.slice(-1)[0].path});
        const box = document.createElement("div");
        box.innerHTML = features({...d, placements: d.placements.filter((x) => !x.feature.startsWith("Name/"))}, {toggled: new Map(), ghosts: new Set(["Name"])});
        const g = box.querySelector("details.fgroup[data-g='Name']");
        return !!g.querySelector(".frow.offer") && !g.querySelector("[data-keepall]"); }""")
    page.click("[data-suggest='ID']")  # what the file's contents place there, shown, then kept
    page.click(".drop[data-slot='ID/Record ID'] [data-keep]")
    page.wait_for_selector("#out:not([aria-busy]) details.fgroup", state="attached")  # shown at once; written, then the file described again
    assert 'id = "customer_no"' in columns.read_text(encoding="utf-8") and "Record ID needed" not in page.inner_text("details.fgroup[data-g='ID'] summary")
    page.evaluate("document.querySelector(\"details.fgroup[data-g='Name']\").open = true")  # opened: it stays open as the page redraws
    page.click(f".drop[data-slot='Name/Company name'] .colchip[data-col='{company}'] [data-x]")  # taken off
    page.wait_for_selector("#out:not([aria-busy]) details.fgroup", state="attached")
    assert not page.query_selector(f".drop[data-slot='Name/Company name'] .colchip[data-col='{company}']")
    assert load_settings(columns=columns).columns["company_name"] == () and page.query_selector("details.fgroup[data-g='Name'][open]")
    page.evaluate(f"""() => {{  // dragged back from the file's columns: the drag as the browser fires it
        const dt = new DataTransfer(), from = document.querySelector(".tray .colchip[data-col='{company}']");
        const to = document.querySelector(".drop[data-slot='Name/Company name']");
        from.dispatchEvent(new DragEvent("dragstart", {{dataTransfer: dt, bubbles: true}}));
        to.dispatchEvent(new DragEvent("drop", {{dataTransfer: dt, bubbles: true, cancelable: true}})); }}""")
    page.wait_for_selector(f"#out:not([aria-busy]) .drop[data-slot='Name/Company name'] .colchip[data-col='{company}']")
    assert load_settings(columns=columns).columns["company_name"] == ((company,),)
    page.click("[data-add='Name']")  # a feature of their own: named, what it is, its script
    page.fill(".addform input", "Kanji name")
    page.select_option(".addform select >> nth=1", "kanji")
    page.click(".addform .btn.filled")
    assert page.get_attribute("#out", "inert") is not None and page.inner_text(".addform .btn.filled") == "Adding…"  # the page waits for its new shape
    page.wait_for_selector(".drop[data-slot='Name/Kanji name/Family name']")  # with its parts
    assert "person_name_2" in columns.read_text(encoding="utf-8") and "kanji" in page.inner_text(".frow:has(.drop[data-slot='Name/Kanji name'])")
    page.click("[data-remove='Name/Kanji name']")
    page.wait_for_function("() => !document.querySelector(\".drop[data-slot='Name/Kanji name']\")")
    assert "person_name_2" not in columns.read_text(encoding="utf-8")
    page.click(".navitem[data-screen=columns]")
    page.wait_for_selector("#files .tag", state="attached")  # its description starts now
    page.click(".navitem[data-screen=run]")
    page.wait_for_timeout(1500)
    assert not page.query_selector("details.fgroup")  # the page left draws nothing on the page now open
    page.wait_for_selector("#out [data-first]")  # before a first run: how many records, how long, one button
    assert "492 records" in page.inner_text("#out .card") and "theirs" in page.inner_text("#out .card") and not page.query_selector("[data-act='rerun records']")
    page.click("#out [data-first]")  # the file loaded last: nothing to type
    page.wait_for_function("() => document.querySelector('#equiv-line').textContent.includes('resolve records')")
    assert not page.query_selector("#f-input") and "theirs.parquet · 492 records" in page.inner_text("dialog .about") and "theirs.parquet" not in page.inner_text("#equiv-line")
    page.keyboard.press("Escape")
    page.click("#picker")
    page.wait_for_selector("tr[data-w]")
    assert [Path(r.get_attribute("data-w")).name for r in page.query_selector_all("tr[data-w]")] == ["fresh"]  # from disk, not the browser
    page.keyboard.press("Escape")
    page.click(".navitem[data-screen=records]")
    page.evaluate(f"setWorkspace({json.dumps(str(run))})")
    page.wait_for_selector(".tiles")
    assert not any(b.is_disabled() for b in page.query_selector_all("[data-loop]")) and not page.is_disabled("#search")
    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("[data-a=match]")
    page.keyboard.press("m")
    page.keyboard.press("m")  # pressed again before the first answer is back
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
    page.wait_for_timeout(600)
    assert page.inner_text("#written") == "1" and not page.query_selector("#said .banner")  # one answer, no busy folder
    assert "nayose decide pair" in page.inner_text("#term-body")  # the command line it ran
    states = page.evaluate("""() => {  // each place's state, from describe workspace and the pairs describe results says wait
        const kept = resultsNow, run = (pairs, kinds) => ({records: 9, entities: 7, round: 1, pairs: {written_in: 0, ...pairs}, kinds: {decide: 0, written_in: 0, ...kinds}});
        const at = (d, waiting = 0) => { resultsNow = {waiting: [{down_to: 6, up_to: null, pairs: waiting}]}; const p = progress(d); return [p.next, p.steps.pairs.state, p.steps.kinds.state]; };
        const said = [at({event: "error", error: "no run"}), at(run({}, {}), 3), at(run({}, {})), at(run({written_in: 2}, {})), at(run({}, {decide: 4}))];
        resultsNow = kept;
        return said; }""")
    assert states == [["columns", "later", "later"], ["pairs", "attention", "optional"], ["records", "done", "optional"], ["pairs", "attention", "optional"],
                      ["records", "done", "attention"]]  # pairs waiting, or decided and not applied: Review; else Results
    assert page.query_selector(".rail li.attention .sub").inner_text().endswith("waiting")  # the rail points at the pairs still open
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector(".node[data-node=candidates]")
    assert [n.get_attribute("data-node") for n in page.query_selector_all(".flow .node")] == ["records", "rules", "candidates", "score", "accept", "group"]
    questions = page.evaluate("STAGE_Q")
    for node in ["records", "rules", "candidates", "score", "accept", "group"]:  # each stage answers its question first
        page.click(f".node[data-node={node}]")
        page.wait_for_selector(".detail h2.question")
        assert page.inner_text(".detail h2.question") == questions[node]
        if node != "score":
            assert page.inner_text(".detail .qa .answer").strip()  # and says its answer in a sentence
    page.click(".node[data-node=rules]")
    page.click(".detail .pq-more summary")  # its detail, folded: each rule opens its lowest-scoring pairs
    page.click(".detail [data-rule]")
    page.wait_for_selector(".detail .pn-drawer")
    page.click(".node[data-node=candidates]")
    assert "possible pairs" in page.inner_text(".detail .pq-pic")
    page.click(".detail .pq-more summary")
    page.click(".detail [data-key]")
    page.wait_for_function("() => document.querySelector('.detail .pn-drawer')?.textContent.includes('pairs listed')", timeout=30_000)  # a key, inspected
    page.click(".node[data-node=accept]")
    page.click(".detail .pn-band >> nth=-1")
    page.wait_for_selector(".detail .pn-picked .pn-drawer")  # a band of points opens what happened to its pairs
    page.click(".detail .pq-more summary")
    page.wait_for_selector("#ptable tr[data-i]")  # every pattern of what the comparisons said, in its detail
    page.click(".node[data-node=group]")
    assert "entities" in page.inner_text(".detail .qa .answer")
    page.click(".node[data-node=score]")
    page.wait_for_selector(".detail .pn-view .wf-grid", timeout=30_000)  # one pair first: how it scored, step by step
    first = page.inner_text(".detail .pn-view .answer")
    page.click(".detail [data-another]")
    page.wait_for_function("(was) => { const p = document.querySelector('.detail .pn-view .answer'); return p && p.innerText !== was; }", arg=first, timeout=30_000)
    page.click(".detail [data-view=most]")
    assert page.query_selector(".detail .pn-view .pn-bar")  # what counts most
    page.click(".detail .pq-more summary")
    page.click(".detail .pn-comp summary b >> nth=0")  # every comparison: one opens its staircase (its bar's parts open a replay)
    page.wait_for_selector(".stair button[data-step]")  # every step's test replayable
    chips = page.query_selector_all(".stair button[data-step]")
    chips[0].hover()
    chips[1].hover()  # asked before the first one's pair is back: only the second plays, on a pair that stopped at its step
    page.wait_for_function("(s) => document.querySelector('.scene:popover-open .scope')?.textContent.startsWith(`Why this match? · “${level(s.split('|')[1])}”`)",
                           arg=chips[1].get_attribute("data-step"), timeout=30_000)
    page.wait_for_selector(".scene:popover-open .stage text", timeout=30_000)  # replayed on a pair of this run
    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("[data-a=match]")
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")  # the pair written in before: still listed, and can be applied
    assert not page.is_disabled("#apply")
    assert not page.query_selector(".scene:popover-open")  # another page: the replay closed with the one it was on
    page.wait_for_selector("#right .fullrows tbody tr")  # both full rows, each compared column with how it was compared
    compared = [c.inner_text() for c in page.query_selector_all("#right .fullrows tbody td:last-child")]
    assert any(re.search(r"[+-]\d+\.\d$", c) for c in compared), compared  # what it gave, in points
    page.click("#right details.fold-line summary")  # how it scored, step by step: folded under them
    assert page.query_selector(".wf-grid .wf rect.for")  # each comparison moves the total, from the start
    page.hover(".wf-grid [data-how]:not([disabled])")
    page.wait_for_selector(".scene:popover-open .stage text")  # the test replayed over the page, on this pair's values
    page.keyboard.press("Escape")
    assert not page.query_selector(".scene:popover-open")
    from er.standardize import normalize, prepared
    from er.strings import FUNCTIONS
    cases = [("jaro_winkler", "MARTHA", "MARHTA"), ("jaro_winkler", "DIXON", "DICKSONX"), ("jaro_winkler", "ハツトリソウタロウ", "ハツトリソウタ"),
             ("jaro_winkler", "服部蒼太朗", "服部聡太"), ("jaro_winkler", "ABC", "XYZ"), ("jaro", "CRATE", "TRACE"), ("levenshtein", "kitten", "sitting"),
             ("levenshtein", "大田区東蒲田1-9-19", "大田区東蒲田1-8-10"), ("damerau_levenshtein", "CA", "ABC"), ("damerau_levenshtein", "ab", "ba"),
             ("damerau_levenshtein", "1425055915260", "1425055945260"), ("hamming", "1649", "1149"), ("hamming", "1234", "123"), ("jaccard", "サトウ", "サイトウ")]
    got = page.evaluate("(cs) => cs.map(([f, a, b]) => traceScore(f, a, b))", cases)  # what a scene ends on: the engine's own number
    assert got == pytest.approx([FUNCTIONS[f].scorer(a, b) for f, a, b in cases]), list(zip(cases, got))
    raws = [("ハッドリソウタ", ("kana_fold",)), ("東京都大田区東蒲田1丁目9番19号\u3000メゾン青葉806", ("address",)),
            ("イガイカブシキガイシャ", ("nfkc", "strip_legal_form", "kana_fold"))]
    chains = [prepared(v, steps, s.standardize) for v, steps in raws]
    assert [c[-1][1] for c in chains] == [normalize(pd.Series([v]), steps, s.standardize).iloc[0] for v, steps in raws]
    notes = page.evaluate("""(cs) => cs.map(([raw, steps]) => {  // each step replayed: the letters it leaves are the engine's
        let v = raw, notes = [];
        for (const [step, after] of steps) { if (after === v) continue; const t = stepTrace(v, after, step); if (t.result !== after) return null; notes.push(...t.notes); v = after; }
        return notes; })""", [[v, c] for (v, _), c in zip(raws, chains)])
    assert notes[0] == ["small kana → big", "゛ off"] and notes[2] == ["legal form dropped", "゛ off"]
    assert notes[1] == ["full width → half", "丁目・番地・号 → -", "building and room dropped", "prefecture dropped"]
    assert page.inner_text(".card.one .question").startswith("Same customer?")
    card, queue = page.query_selector("#right .card.one").bounding_box(), page.query_selector(".queue").bounding_box()
    assert card["x"] < queue["x"] and card["width"] > queue["width"]  # the pair asked about first and wide, its queue after
    page.click(".tab[data-go=kinds]")  # Review's second tab
    page.wait_for_selector(".tab[data-go=kinds][aria-selected=true]")
    assert page.inner_text("h1") == "Review"
    twice = page.evaluate("""async () => {  // the same command asked twice at once runs once
        const lines = () => [...document.querySelectorAll("#term-body .cmd")].filter((c) => c.textContent.startsWith("nayose list scored")).length;
        const before = lines();
        await Promise.all([run("pairs", "list scored", {status: "waiting"}), run("pairs", "list scored", {status: "waiting"})]);
        return lines() - before; }""")
    assert twice == 1
    assert page.evaluate("""() => {  // a row far past the table's 500 drawn is drawn once picked
        const box = document.body.appendChild(document.createElement("div"));
        const t = grid(box, Array.from({length: 2000}, (_, n) => ({n})), ["n"], {selected: 0});
        t.select(1500);
        return box.querySelector('tr[data-i="1500"]')?.getAttribute("aria-selected") === "true"; }""")
    page.click(".navitem[data-screen=run]")
    page.click("[data-act='rerun records']")
    page.click("dialog .dlg-foot .btn.filled")
    page.wait_for_selector("#out .steps-card")  # one long command at a time: the others wait for it, on this page
    assert page.is_disabled("[data-act='add records']") and page.is_disabled("[data-act='match records']")
    page.wait_for_selector("[data-act='add records']:not([disabled])", timeout=120_000)
    page.click("[data-act='rerun records']")  # started, then left: back on step 3 once it ends, its buttons are free again
    page.click("dialog .dlg-foot .btn.filled")
    page.click(".navitem[data-screen=results]")
    page.wait_for_function("() => task.steps.length >= 1 && task.done === null", timeout=60_000)  # a step has ended; the run goes on
    page.wait_for_function("() => (document.querySelector('.rail li.running[data-busy=run] .run-line') || {textContent: ''}).textContent.trim()")  # its step turns, saying how far: a time left only where something measured says one, else the seconds so far
    page.click(".navitem[data-screen=records]")  # the Overview: what runs now, and the way to it
    page.wait_for_selector("#auto a[data-go=run]", timeout=10_000)
    assert page.inner_text("#auto h2").startswith("Matching again")
    page.click("#auto a[data-go=run]")  # back while it runs: its card, and the stages its steps have filled in, as they stand
    page.wait_for_selector("#out .steps-card .answer:has-text('now:')", timeout=10_000)
    page.wait_for_selector(".node[data-node=records] .n .v", timeout=10_000)
    page.wait_for_selector("#task:has-text('Matching again: done')", timeout=120_000)  # its progress, on whichever page is open
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector("[data-act='add records']:not([disabled])", timeout=10_000)
    httpd.shutdown()
    httpd.server_close()
    nav = page.inner_text("#nav")
    lost = page.evaluate("() => run('pairs', 'list scored')")
    assert lost["event"] == "error" and lost["error"].startswith("Lost the server")
    page.evaluate("() => refresh()")  # the stepper as it was, the loss said once above the page
    assert page.is_visible("#lost") and page.inner_text("#nav") == nav and "Lost the server" not in page.inner_text("#screen")


def test_step_2_shows_each_change_at_once_writes_them_in_turn_and_a_refused_one_shows_the_workspace(ui_page, tmp_path, population):
    from er import cli
    s, p, g = population
    named = {c: f"c{i:02d}" for i, c in enumerate(g.df.columns)}  # names the mapping doesn't know: every field placed from its values
    g.df.rename(columns=named).to_parquet(tmp_path / "theirs.parquet", index=False)
    home, ws = tmp_path / "workspaces", tmp_path / "workspaces" / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    assert cli.main(["load", "records", str(tmp_path / "theirs.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(ws), str(home), viewport={"width": 1280, "height": 900})
    posted, columns = [], lambda: load_settings(columns=ws / "columns.toml").columns
    page.on("request", lambda r: r.method == "POST" and posted.append(json.loads(r.post_data)["command"]))
    saved = lambda: page.wait_for_selector("#out:not([aria-busy]) details.fgroup", state="attached", timeout=60_000)
    page.click(".navitem[data-screen=columns]")
    page.click("#out [data-suggest='*']", timeout=60_000)
    page.click("#out [data-keepall='*']")  # every suggestion kept, in one write
    saved()
    assert not page.query_selector("#out .banner.bad, #out .need, .drop[data-slot] .colchip.ghost") and columns()["phone"]
    page.evaluate("document.querySelectorAll('details.fgroup').forEach((g) => g.open = true)")
    slot, phone = ".drop[data-slot='Phone/Phone']", columns()["phone"][0][0]
    other = next(c for c in named.values() if c != phone)
    posted.clear()
    page.click(f"{slot} .colchip.in")  # a column clicked: the file's columns in a list, its own chosen
    assert page.eval_on_selector(f"{slot} select", "s => s.value") == phone
    page.click("h1")  # left without a pick: the column as it was, nothing written
    assert page.locator(f"{slot} .colchip.in[data-col='{phone}']").count() == 1 and not posted
    page.click(f"{slot} .colchip.in")
    page.select_option(f"{slot} select", other)
    assert page.locator(f"{slot} .colchip.in[data-col='{other}']").count() == 1 and page.get_attribute("#out", "aria-busy") == "true"  # shown before it is written
    page.click(f"{slot} .hole")  # +: another column, read where the ones before are empty
    page.select_option(f"{slot} select", phone)
    saved()
    assert columns()["phone"] == ((other,), (phone,)) and posted[-1] == "describe records" and "describe workspace" not in posted
    page.click(f"{slot} .colchip.in[data-col='{other}'] [data-x]")
    page.click(f"{slot} .colchip.in[data-col='{phone}'] [data-x]")  # two quick changes: written in turn
    saved()
    assert columns()["phone"] == () and page.inner_text(f"{slot} .hole") == "choose a column"
    page.click("details.tray > summary")
    page.locator(f"details.tray .colchip[data-col='{phone}']").drag_to(page.locator(f".frow:has({slot}) .flab"))  # by mouse, onto the row's name
    saved()
    assert columns()["phone"] == ((phone,),)
    page.focus(f"{slot} .colchip.in [data-x]")
    page.keyboard.press("Enter")  # × by keyboard: taken off, no list
    saved()
    assert columns()["phone"] == () and not page.query_selector(f"{slot} select")
    page.click("#loaded summary")  # another file, and a change made while it loads: shown as written, never the reading from before it
    g.df.rename(columns=named).head(50).to_parquet(tmp_path / "more.parquet", index=False)
    page.fill("#cin", str(tmp_path / "more.parquet"))
    page.click("#load")
    page.click(f"{slot} .hole")
    page.select_option(f"{slot} select", phone)
    page.wait_for_function("() => document.querySelectorAll('#files .tag').length === 2 && !document.querySelector('#out[aria-busy]')", timeout=60_000)
    page.wait_for_timeout(1500)
    assert columns()["phone"] == ((phone,),) and page.locator(f"{slot} .colchip.in[data-col='{phone}']").count() == 1
    assert cli.main(["set", "feature", f"Phone/Phone=GONE,{phone}", "--workspace", str(ws), "--format", "json"]) == 0  # first, a column the file lacks
    reopen = lambda: (page.evaluate("go('columns')"), page.wait_for_selector(f"{slot} .colchip.in", state="attached", timeout=60_000),
                      page.evaluate("document.querySelectorAll('details.fgroup').forEach((g) => g.open = true)"))
    reopen()
    page.click(f"{slot} .colchip.in")
    page.select_option(f"{slot} select", other)
    saved()
    assert columns()["phone"] == ((other,),)  # the column clicked, replaced; the one the file lacks gives way
    page.click("[data-add='Name']")
    posted.clear()
    page.click("[data-cancel]")
    assert not page.query_selector(".addform") and page.query_selector("[data-add='Name']") and not posted  # nothing to undo: nothing runs
    assert cli.main(["add", "feature", "Name/Kanji name", "--type", "person name", "--script", "kanji", "--workspace", str(ws), "--format", "json"]) == 0
    page.evaluate("go('columns')")
    page.wait_for_selector(".drop[data-slot='Name/Kanji name'] .hole", state="attached")
    page.evaluate("document.querySelector(\"details.fgroup[data-g='Name']\").open = true")
    assert cli.main(["remove", "feature", "Name/Kanji name", "--workspace", str(ws), "--format", "json"]) == 0  # gone since the page showed it
    page.click(".drop[data-slot='Name/Kanji name'] .hole")
    page.select_option(".drop[data-slot='Name/Kanji name'] select", other)
    saved()
    assert "no feature Name/Kanji name" in page.inner_text("#out .banner.bad") and not page.query_selector(".drop[data-slot='Name/Kanji name']")  # refused: why, and the workspace as it is
    assert cli.main(["set", "feature", f"Phone/Phone={phone},{other}", "--workspace", str(ws), "--format", "json"]) == 0
    reopen()
    page.evaluate(f"""() => {{  // two changes, and the page left while the first is written: the second is still written
        document.querySelector("{slot} .colchip.in[data-col='{phone}'] [data-x]").click();
        document.querySelector("{slot} .colchip.in[data-col='{other}'] [data-x]").click();
        setTimeout(() => go("run"), 20); }}""")
    for _ in range(300):
        if columns()["phone"] == ():
            break
        page.wait_for_timeout(100)
    assert columns()["phone"] == ()
    page.wait_for_function("() => inflight.size === 0", timeout=60_000)  # the left page's last description read: a change made here after it is drawn
    assert cli.main(["set", "feature", f"Phone/Phone={phone},{other}", "--workspace", str(ws), "--format", "json"]) == 0
    reopen()
    held = []  # the file described again after a change, held while a second change waits behind it and the page is left
    page.route("**/api/run", lambda route: held.append(route) if json.loads(route.request.post_data)["command"] == "describe records" else route.continue_())
    take_off = lambda col: page.evaluate(f"document.querySelector(\"{slot} .colchip.in[data-col='{col}'] [data-x]\").click()")
    take_off(phone)
    for _ in range(300):
        if held:
            break
        page.wait_for_timeout(50)
    take_off(other)
    page.evaluate("go('run')")
    while held:  # each description asked meanwhile, let go
        held.pop().continue_()
    page.unroute("**/api/run")
    for _ in range(300):
        if columns()["phone"] == ():
            break
        page.wait_for_timeout(100)
    assert columns()["phone"] == ()  # the page that asked for the description is gone: the change queued behind it is written all the same


def test_a_long_command_shows_how_far_it_is_in_a_panel_that_folds_and_closes_and_the_drawer_keeps_its_height(ui_page, tmp_path, population):
    from er import cli
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    home = tmp_path / "workspaces"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(home / "w"), str(home), viewport={"width": 1280, "height": 900})
    page.click(".navitem[data-screen=columns]")
    page.fill("#cin", str(tmp_path / "all.parquet"))
    page.click("#load")
    assert page.inner_text("#out .waiting") == "Reading all.parquet…"  # the columns, once read: something says so meanwhile
    page.wait_for_selector("#task:has-text('Loading your file: done')", timeout=60_000)
    page.wait_for_selector("details.fgroup", state="attached")
    page.click("#task-close")
    assert page.is_hidden("#task")
    page.evaluate("() => { task.start('load records', 'j1', Date.now() / 1000 - 10); task.start('add records', 'j2'); task.event({event: 'progress', done: 200, total: 1000, unit: 'rows'}, 'j1'); }")
    assert page.inner_text("#task-line") == "200 of 1,000 rows · about 40 seconds left" and page.get_attribute("#task-bar", "style") == "width: 20%;"
    page.click("#task-fold")  # folded: what it does and how long is left, in its title
    assert page.is_hidden("#task-line") and page.inner_text("#task-title") == "Loading your file · about 40 seconds left"
    page.evaluate("task.end(false, 'refused', 'j2')")  # a second command, refused at once: the panel stays the first's
    assert page.inner_text("#task-title") == "Loading your file · about 40 seconds left"
    page.evaluate("task.end(false, 'no file at x.csv', 'j1')")
    assert page.inner_text("#task-title") == "Loading your file: failed"
    page.evaluate("window.L = {load: 10, budget: 2, fit: 20, rules: 5, candidates: 30, score: 100, cluster: 1, probe: 10, report: 1, write: 1}")  # the last run's steps, 180 s
    assert page.evaluate("runPace(RUN_STEPS, null, 0, 5, null)") == {"done": 0, "left": None, "least": False, "over": False}  # nothing measured yet: no number
    first = page.evaluate("runPace(RUN_STEPS, null, 0, 10, null, {done: 200, total: 1000, unit: 'records'}, 0)")  # a first run: the step's own count, nothing after it
    assert first["left"] == pytest.approx(40) and first["least"] and page.evaluate("paceLine(runPace(RUN_STEPS, null, 0, 10, null, {done: 200, total: 1000, unit: 'records'}, 0))") == "at least 40 seconds left"
    known = page.evaluate("runPace(RUN_STEPS, 'load', 10, 11, L)")  # every step measured last time
    assert known["left"] == pytest.approx(1 + 168) and not known["least"] and known["done"] == pytest.approx(11 / 180)
    late = page.evaluate("runPace(RUN_STEPS, 'load', 10, 40, L)")  # budget well past its last time: said so, only the steps after it counted
    assert late["over"] and late["left"] == pytest.approx(168) and late["least"]
    assert page.evaluate("paceLine(runPace(RUN_STEPS, 'load', 10, 40, L))") == page.evaluate("`longer than last time · at least ${lasts(168)} left`")
    counted = page.evaluate("runPace(RUN_STEPS, 'candidates', 50, 70, L, {done: 25, total: 100, unit: 'pairs'}, 50)")  # its count over last time's: what this run measures
    assert counted["left"] == pytest.approx(60 + 13) and not counted["least"] and counted["done"] == pytest.approx((67 + 25) / 180)
    more = page.evaluate("runPace(RUN_STEPS, 'rules', 40, 50, L, {done: 50, total: 100, unit: 'keys', more: true}, 40)")  # a part of the step its count doesn't cover: a floor
    assert more["left"] == pytest.approx(10 + 113) and more["least"]
    counted_all = page.evaluate("runPace(RUN_STEPS, 'fit', 32, 300, L, {done: 12, total: 12, unit: 'rules'}, 32)")  # every rule applied, the step still at work: by last time
    assert counted_all["over"] and counted_all["left"] == pytest.approx(113 + 30)
    page.evaluate("() => { task.start('resolve records', 'j7', Date.now() / 1000 - 100); task.event({event: 'step', step: 'budget', t: 10}, 'j7'); task.event({event: 'progress', done: 0, total: 8, unit: 'records', t: 60}, 'j7'); }")
    assert page.evaluate("task.pAt") == 60  # a count paced from when it began, not from the step before it
    page.evaluate("task.end(true, '', 'j7')")
    assert page.evaluate("lastRun(2000, {runs: [{what: 'full run', steps: {load: 10, fit: 4}, records: 1000}, {what: 'increment', steps: {load: 1}, records: 5}]})") == {"load": 20, "fit": 8}
    assert page.evaluate("lastRun(2000, {runs: [{what: 'full run', seconds: 9}]})") is None  # a run kept before steps were: nothing to go by
    page.evaluate("() => { task.start('resolve records', 'j3'); task.event({event: 'step', step: 'candidates'}, 'j3'); task.event({event: 'progress', done: 2e6, total: 8e6, unit: 'pairs', likely: 1234}, 'j3'); }")
    assert page.inner_text("#task-title").startswith("Finding matches · ")  # scoring, slice by slice: how far, and the matches so far
    page.click("#task-fold")
    assert page.inner_text("#task-line").startswith("2,000,000 of 8,000,000 pairs scored · 1,234 likely matches so far · ")
    page.evaluate("() => { task.end(true, '', 'j3'); task.start('resolve records', 'j4', Date.now() / 1000 - 200); task.last = L; task.event({event: 'step', step: 'candidates', t: 20}, 'j4'); }")
    held = page.evaluate("task.most")  # scoring well past last time's 100 s (as the server stamped the step: 20 s in): the bar held near its end
    page.evaluate("task.event({event: 'progress', done: 1e6, total: 1e7, unit: 'pairs', likely: 0}, 'j4')")  # then its own count says 10%
    assert held == pytest.approx((67 + 95) / 180) and page.evaluate("task.most") == held and page.get_attribute("#task-bar", "style") == f"width: {round(100 * held)}%;"  # never back
    page.evaluate("() => { task.end(true, '', 'j4'); task.start('load records', 'j5'); go('records'); }")  # a long command this tab started: the Overview says so
    page.wait_for_selector("#auto a[data-go=columns]", timeout=10_000)
    page.evaluate("task.end(true, '', 'j5')")
    page.evaluate("snack('<span class=msg>Copied the report</span>')")
    page.click("#snack .x")  # a notice closed by its ✕
    assert page.is_hidden("#snack")
    page.click("#term-toggle")
    grip = page.locator("#term-grip").bounding_box()
    page.mouse.move(grip["x"] + 300, grip["y"] + 4)
    page.mouse.down()
    page.mouse.move(grip["x"] + 300, grip["y"] - 196, steps=4)  # the drawer, taller by its top edge
    page.mouse.up()
    tall = page.evaluate("document.getElementById('term').offsetHeight")
    assert tall >= 440
    page.reload()
    page.click("#term-toggle")
    assert page.evaluate("document.getElementById('term').offsetHeight") == tall  # as it was left
    page.click(".navitem[data-screen=run]")
    assert re.fullmatch(r"all\.parquet · about \d+ seconds", page.inner_text("#out .answer", timeout=60_000))  # before a run: about how long, from this machine's reading of the file


def test_step_2_shows_what_the_reader_proposes_and_a_click_accepts_one_kind(ui_page, tmp_path, population):
    from er import cli, folder, intake
    s, p, g = population
    dirty_csv(g.df.astype("string"), "FULL_NAME_KANA", "ORIGINAL_ADDRESS", tmp_path / "dirty.csv")
    home = tmp_path / "workspaces"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(home / "w"), str(home), viewport={"width": 1280, "height": 900})
    page.wait_for_selector(".rail")
    page.evaluate(f"setWorkspace({json.dumps(str(home / 'w'))})")
    page.click(".navitem[data-screen=columns]")
    page.fill("#cin", str(tmp_path / "dirty.csv"))
    page.click("#load")
    page.wait_for_selector("#repairs [data-accept]", state="attached", timeout=60_000)
    assert "1 row and 1 value wait for a repair" in page.inner_text("#loaded .answer")  # said where it is asked: did your file load?
    assert page.locator("#repairs summary").all_inner_texts()[:2] == ["1 value garbled by a wrong decoding upstream: decoded back",
                                                                      "1 row whose fields don't line up: re-split where every value fits its column"]
    repairs, watch = page.query_selector("#repairs").bounding_box(), page.query_selector("#out").bounding_box()
    assert repairs["y"] + repairs["height"] <= watch["y"]  # what waits for people, before the columns
    page.click("#repairs details:has([data-accept=realign]) summary")
    assert "," in page.inner_text("#repairs details:has([data-accept=realign]) table")  # before → after, to see first
    page.click("[data-accept=realign]")
    page.click("#dlg button[value=run]")
    page.wait_for_function("() => (document.querySelector('#loaded .answer') || {innerText: 'row'}).innerText.includes('· 1 value waits for a repair')", timeout=60_000)
    part = folder.parts(home / "w")[0]
    assert intake.report(part)["accepted"] == ["realign"] and not page.query_selector("[data-accept=realign]")


def test_step_2_says_what_a_column_holds_instead_and_its_button_sets_it_right(ui_page, tmp_path, population):
    from er import cli
    s, p, g = population
    person = g.df["NYS_CNV_P_NAME_KANA"].isna() & g.df["FULL_NAME_KANA"].notna()
    g.df.assign(NYS_CNV_P_NAME_KANA=g.df["NYS_CNV_P_NAME_KANA"].where(~person, g.df["FULL_NAME_KANA"])).to_parquet(tmp_path / "shared.parquet", index=False)
    home = tmp_path / "workspaces"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    assert cli.main(["set", "feature", "Phone/Phone=POST_CD", "Address/Postal code=", "--workspace", str(home / "w"), "--format", "json"]) == 0  # postal codes read as the phone
    page, server, httpd = ui_page(str(home / "w"), str(home), viewport={"width": 1440, "height": 900})
    page.wait_for_selector(".rail")
    page.evaluate(f"setWorkspace({json.dumps(str(home / 'w'))})")
    page.click(".navitem[data-screen=columns]")
    page.fill("#cin", str(tmp_path / "shared.parquet"))
    page.click("#load")
    row = lambda slot: f".frow:has(.drop[data-slot='{slot}'])"
    page.wait_for_selector(f"{row('Name/Company name')} .fhint", timeout=60_000)
    assert "people's names" in page.inner_text(f"{row('Name/Company name')} .fhint") and not page.inner_text(f"{row('Name/Company name')} .fwarn")  # said once, under it
    assert "look like postal code" in page.inner_text(f"{row('Phone/Phone')} .fhint")
    assert "Company name" in page.inner_text(".fgroup[data-g=Name] .gstat")  # the group says which needs a look
    page.click("[data-hint='Name/Company name']")
    page.wait_for_selector(f"{row('Name/Company name')} .fhint.info", timeout=60_000)  # done, and said as done
    assert 'kind = "company"' in (home / "w" / "columns.toml").read_text(encoding="utf-8") and not page.query_selector("[data-hint='Name/Company name']")
    page.click("[data-hint='Phone/Phone']")
    assert not page.query_selector("[data-hint='Phone/Phone']")  # done: its button goes at once, so a second click sends nothing
    field = lambda f, filled, *alts: dict(field=f, filled=filled, alternatives=[dict(columns=a, found=True) for a in alts])
    together = lambda *fields: page.evaluate("(f) => hurts(f, [], '', {}, [['person_name', 'company_name']]).join(' ')", list(fields))
    assert "Person name is 20% filled" in together(field("person_name", 0.2, ["NAME"]), field("company_name", 0.2, ["NAME"]))  # one column for both: counted once
    assert "Person name" not in together(field("person_name", 0.2, ["SEI", "MEI"], ["SEI", "MEI"]), field("company_name", 0.15, ["CO"]))  # its columns once each: 35%, as check records counts
    page.wait_for_selector(f"{row('Address/Postal code')} .colchip.in[data-col=POST_CD]", state="attached", timeout=60_000)  # in its group, folded: nothing there needs a look
    page.wait_for_function(f"() => !document.querySelector(\"{row('Phone/Phone')} .fhint\")", timeout=60_000)
    assert not page.query_selector(f"{row('Phone/Phone')} .colchip.in")


def test_the_improve_page_tries_a_line_once_adopts_it_and_opens_the_next_round(ui_page, tmp_path, population):
    from er import cli, folder
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "run"
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(ws), str(tmp_path / "workspaces"), viewport={"width": 1280, "height": 900})
    page.wait_for_selector(".tiles")
    page.click(".navitem[data-screen=improve]")  # Setup → Method
    page.wait_for_selector("#out h2.question")
    assert page.inner_text("#out h2.question") == "Is the matching good enough yet?" and "Not known yet" in page.inner_text("#out .qa .answer")
    assert page.query_selector("#out .qa a[data-go=pairs]")  # the way to know: review pairs
    assert page.inner_text("h1") == "Method" and "as tuned" in page.text_content("#rounds")
    page.click("details:has(#line) > summary")
    page.wait_for_selector("#line svg")
    line = p.fs.min_match_weight
    page.fill("#at", f"{line + 2:g}")  # the line dragged: counted at once, and offered as a trial
    page.dispatch_event("#at", "input")
    assert page.inner_text("#at-says").startswith(f"At {line + 2:g}") and page.get_attribute("#at-line", "x1") != page.get_attribute("#line .now", "x1")
    page.click("#at-says [data-try]")
    page.click("#at-says [data-try]", force=True)  # pressed again while it runs: one trial
    page.wait_for_selector(".trial", timeout=120_000)
    assert "Joined, people said different" in page.inner_text(".trial") and len([*(ws / "trials").glob("[0-9]*.json")]) == 1
    page.click("[data-adopt]")
    page.wait_for_selector("#note .banner", timeout=120_000)  # matched again: the next round's pairs
    assert page.inner_text("h1") == "Review" and folder.method(ws) == {"line": line + 2}
    page.click(".navitem[data-screen=improve]")
    page.wait_for_selector("#out h2.question")
    assert "Back to the tuned method" in page.inner_text("#out") and not page.query_selector(".trial")  # the trial adopted: no card


def test_review_counts_down_an_answer_waits_out_a_busy_workspace_and_auto_merge_turns_off_to_the_same_entities(ui_page, tmp_path, population, capsys, monkeypatch):
    from er import cli, folder
    s, p, g = population
    uid = s.data.unique_id
    flag_wrong(g.df).to_parquet(tmp_path / "all.parquet", index=False)  # every record flagged person: the engine flags the companies it is sure of
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "workspace", "w", "--format", "json"]) == 0  # a new workspace: nothing merges without people
    ws = tmp_path / "workspaces" / "w"
    assert cli.main(["resolve", "records", "all.parquet", "--workspace", str(ws), "--format", "json"]) == 0
    capsys.readouterr()
    page, server, httpd = ui_page(str(ws), str(tmp_path / "workspaces"), viewport={"width": 1280, "height": 900})
    page.wait_for_selector(".tiles")
    assert page.inner_text("h1") == "Results" and "you decide every pair" in page.inner_text("#out .card .answer")
    assert page.evaluate("""() => { const bar = document.querySelector("#busybar"), asked = run("records", "describe results"), during = !bar.hidden;
        return asked.then(() => [during, bar.hidden]); }""") == [True, True]  # the app bar's line: on while the page reads, off once it has its answer
    waiting = int(re.search(r"[\d,]+", page.inner_text("a.tile[data-go=pairs]:not([data-merge]) .num")).group().replace(",", ""))
    assert waiting > 2 and page.inner_text(".rail li.attention .sub") == f"{waiting:,} waiting"  # the tile and the rail say one number
    tiles = {page.inner_text(f"{t} h3"): page.inner_text(t) for t in [f"a.tile:nth-child({k})" for k in range(1, page.locator("a.tile").count() + 1)]}
    assert " found" in tiles["Could it miss a real match?"] and "isn't checked" in tiles["Could it miss a real match?"]  # what was checked, never "about 0 missed"
    assert "flagged" in tiles["Person or company?"] and "matched as the engine says" in tiles["Person or company?"]
    minutes = -(-waiting * 20 // 60)
    assert page.inner_text("a.tile[data-go=pairs]:not([data-merge]) p.muted") == f"about {minutes} minute{'s' * (minutes != 1)} to review them all, if each pair takes 20 seconds"
    assert page.evaluate("[reviewTime(5400), reviewTime(129.7 * 3600)]") == ["1.5 hours", "130 hours"]  # how long, then what it rests on
    page.click("a.tile[data-tab=entities]")  # a tile opens its own tab
    page.wait_for_selector(".tab[data-tab=entities][aria-selected=true]")
    page.wait_for_timeout(1000)
    assert page.query_selector(".tab[data-tab=entities][aria-selected=true]") and page.inner_text("h1") == "Explore"
    page.click(".navitem[data-screen=records]")
    page.click("a.tile[data-merge]")  # and the one about merging, the dialog it is about
    page.wait_for_selector("dialog[open] [data-add]")
    page.keyboard.press("Escape")
    page.evaluate("scrollTo(0, 400)")
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector("#out h2.question.big")  # step 3, opened at its top: what the last run did, and the way to its results
    assert page.evaluate("scrollY") == 0 and page.query_selector("#out .card a[data-go=records]")
    answer, strip_ = page.query_selector("#out .card").bounding_box(), page.query_selector("#flow").bounding_box()
    assert answer["y"] + answer["height"] <= strip_["y"]  # what it found, then how: in reading order
    page.click("[data-act='add records']")  # a new file, never the one matched already
    page.wait_for_selector("#f-input")
    assert page.get_attribute("#f-input", "required") is not None and page.get_attribute("#f-input", "placeholder") == "the new records file"
    page.keyboard.press("Escape")
    page.click(".node[data-node=accept]")
    page.click(".detail .pq-more summary")
    page.click("#ptable tr[data-i]")  # the run as patterns, in Matched's detail: one picked, its pairs to explain
    page.click("#pex [data-x]")
    page.wait_for_selector("dialog .wf-grid")
    assert page.inner_text("dialog h2").startswith("Why these two scored")
    page.click("dialog [data-how]")  # its steps, kept open over the dialog: the popup's own buttons answer there too
    page.wait_for_selector(".scene:popover-open .stage text")
    page.click(".scene [data-x]")
    assert not page.query_selector(".scene:popover-open") and page.query_selector("dialog[open]")
    page.keyboard.press("Escape")
    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("#right .fullrows tbody tr")  # the best pair first, both full rows
    assert page.inner_text("#done-line").startswith(f"{waiting:,} pairs waiting from")
    page.keyboard.press("m")
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
    assert page.inner_text("#done-line").startswith(f"{waiting - 1:,} pair") and page.query_selector("#left tr[data-k='0'] .ink-good")  # decided: marked in the queue
    held, go = threading.Event(), threading.Event()
    def other_job():  # another job writes to the workspace for a moment
        with folder.run_lock(ws):
            held.set()
            go.wait(10)
    other = threading.Thread(target=other_job)
    other.start()
    assert held.wait(10)
    page.keyboard.press("n")  # refused as busy, then tried again once the other job is done
    page.wait_for_timeout(1500)
    go.set()
    other.join(30)
    assert not other.is_alive()
    page.wait_for_function("() => document.querySelector('#written').textContent === '2'", timeout=15_000)
    assert not page.query_selector("#said .banner") and page.inner_text(".rail li.attention .sub") == f"{waiting - 2:,} waiting"
    entities = lambda: set(pd.read_parquet(ws / "gold.parquet").groupby("cluster_id")[uid].agg(frozenset))
    before = entities()
    page.click("#merge")  # merge without people, by their own conditions: no run
    page.click("dialog [data-add]")
    page.fill("dialog [data-v=points]", "")  # a condition half set is never applied as another
    page.wait_for_function("() => document.querySelector('dialog [data-set]').disabled")
    page.fill("dialog [data-v=points]", "12")
    page.wait_for_function("() => /would merge/.test(document.querySelector('dialog .preview').textContent)", timeout=30_000)
    page.click("dialog [data-set]")
    assert page.inner_text("dialog h2") == "Merge by these conditions"
    page.click("dialog .dlg-foot .btn.filled")
    page.wait_for_selector("#note .banner:has-text('Merged by your conditions')", timeout=60_000)
    assert folder.method(ws)["merge"] == {"join": "and", "when": [{"points": 12}]} and entities() != before
    page.click("#merge")
    page.click("dialog [data-none]")
    page.click("dialog [data-set]")
    page.click("dialog .dlg-foot .btn.filled")
    page.wait_for_selector("#note .banner:has-text('Nothing merges without you now')", timeout=60_000)
    assert "merge" not in folder.method(ws) and entities() == before  # turned off: what it merged, apart again

    page.click("#nav [data-screen=lookup]")  # Look up: off until the index is built, then a record typed in, its entities best first
    page.wait_for_selector("#build")
    assert page.is_disabled("#lu button[type=submit]") and page.get_attribute("#lu", "inert") is not None
    page.click("#build")
    page.wait_for_selector("#lu:not([inert]) button[type=submit]:not([disabled])", timeout=120_000)
    assert page.is_hidden("#task") and page.inner_text("#out .card .answer").startswith("Index of")  # its progress said in the card, no panel over the results
    rec = pd.read_parquet(tmp_path / "all.parquet").iloc[5]
    for c in ("FULL_NAME_KANA", "PHONE_NUM_4", "POST_CD"):
        if isinstance(rec[c], str):
            page.fill(f"#lu input[name='{c}']", rec[c])
    page.keyboard.press("Enter")
    page.wait_for_selector("#found .lu-hit", timeout=60_000)  # the record itself is in the run: it is found first
    assert page.locator("#found .lu-hit").first.locator("[data-record]").get_attribute("data-record") in set(pd.read_parquet(ws / "gold.parquet").set_index(uid).loc[[rec[uid]], "cluster_id"]) | {rec[uid]}
    assert "ms" in page.inner_text("#found .card .answer") and "ready" in page.inner_text("#nav [data-screen=lookup]")

    named = pd.read_parquet(tmp_path / "all.parquet").dropna(subset=["FULL_NAME_KANA"])  # as one types: suggestions, no Enter
    first, second = named["FULL_NAME_KANA"].iloc[0][:3], next(n[:3] for n in named["FULL_NAME_KANA"] if n[:3] != named["FULL_NAME_KANA"].iloc[0][:3])
    for c in ("FULL_NAME_KANA", "PHONE_NUM_4", "POST_CD"):
        page.fill(f"#lu input[name='{c}']", "")
    page.locator("#lu input[name='FULL_NAME_KANA']").press_sequentially(first, delay=60)
    page.wait_for_selector("#suggest .lu-hit", timeout=30_000)
    assert "start with what you typed" in page.inner_text("#suggest .card .answer") and page.locator("#suggest .lu-hit .chip:has-text('name')").count()
    page.fill("#lu-top", "1")  # Show: how many, kept in this browser
    page.dispatch_event("#lu-top", "change")
    page.wait_for_function("() => document.querySelectorAll('#suggest .lu-hit').length === 1", timeout=30_000)
    page.reload()
    page.wait_for_selector("#lu-top")
    assert page.input_value("#lu-top") == "1"
    page.evaluate("""(slow) => { const real = window.fetch; window.fetch = async (u, o) => {  // the first answer arrives after the second
        if (o && o.body && o.body.includes(slow)) await new Promise((r) => setTimeout(r, 1500)); return real(u, o); }; }""", f"FULL_NAME_KANA={first}")
    name = page.locator("#lu input[name='FULL_NAME_KANA']")
    name.fill(first)
    name.dispatch_event("input")
    page.wait_for_timeout(300)  # its search asked, its answer held back
    name.fill(second)
    name.dispatch_event("input")
    page.wait_for_selector("#suggest .lu-hit", timeout=30_000)
    later = page.inner_html("#suggest")
    page.wait_for_timeout(2500)  # the first answer has arrived meanwhile: it never replaces the second's
    assert page.inner_html("#suggest") == later


def test_auto_mode_runs_from_the_first_screen_and_its_report_waits_on_the_overview(ui_page, tmp_path, population):
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    page, server, httpd = ui_page(None, str(tmp_path / "workspaces"))
    page.wait_for_selector(".welcome [data-auto]")  # beside creating a workspace, before anything else
    page.click(".welcome [data-auto]")
    page.fill("#f-input", str(tmp_path / "all.parquet"))
    page.wait_for_function("() => document.querySelector('#equiv-line').textContent.startsWith('nayose try everything')")  # the command line it runs
    page.click("dialog button[value=run]")
    page.wait_for_selector(".steps-card li:has-text('workspace')", timeout=60_000)  # each step as it ends; the new workspace opened
    assert page.inner_text("#picker").startswith("Workspace: auto-")
    page.click("[data-screen=columns]")  # the person goes elsewhere while it runs
    page.wait_for_selector("h1:has-text('Prepare your data')")
    page.wait_for_selector("#task:has-text('Auto mode: done')", timeout=300_000)  # it ends
    page.click(".navitem[data-screen=records]")  # back on the Overview: the report to send
    page.wait_for_selector("#copy-report")
    assert page.inner_text("#auto h2.question") == "What should I send?" and page.inner_text("#auto .report").startswith("# nayose auto mode")
    page.click("#copy-report")  # no clipboard in this browser: the report is selected for the person to copy
    page.wait_for_function("() => getSelection().toString().startsWith('# nayose auto mode')")
    first = page.inner_text("#picker")
    pd.DataFrame({"CONT_ID": [f"{i:04d}" for i in range(50)], "NOTE": ["x"] * 50}).to_parquet(tmp_path / "bare.parquet", index=False)
    page.click("#screen [data-auto]")  # again, from the Overview, on a file with no name: the check stops it
    page.fill("#f-input", str(tmp_path / "bare.parquet"))
    page.click("dialog button[value=run]")
    page.wait_for_function(f"() => document.querySelector('#auto .report') && document.querySelector('#picker').innerText !== {first!r}", timeout=120_000)
    assert "✗ check" in page.inner_text("#auto .report") and not page.query_selector("#auto .banner")  # its report, not a bare exit code


def test_the_page_keeps_its_step_through_back_reload_and_a_run_and_says_what_was_decided(ui_page, tmp_path, population):
    s, p, g = population
    flag_wrong(g.df).to_parquet(tmp_path / "all.parquet", index=False)  # every record flagged person: the engine flags the companies it is sure of
    page, server, httpd = ui_page(None, str(tmp_path / "workspaces"))
    page.wait_for_selector(".welcome")
    page.evaluate("go('pairs')")  # a place that follows a run, before a workspace: the way in, across the page
    page.wait_for_selector("#screen .welcome")
    assert not page.query_selector("#screen .split") and page.url.endswith("#pairs")
    page.click("#picker")
    page.fill("#new-name", "w")
    page.click("#create")
    page.wait_for_selector("h1:has-text('Prepare your data')")
    (tmp_path / "workspaces" / "w" / "method.toml").unlink()  # the method as tuned: pairs on the sheet to decide
    page.fill("#cin", str(tmp_path / "all.parquet"))
    page.click("#load")
    page.wait_for_selector("#loaded a[data-go=run]", timeout=60_000)
    page.evaluate("go('pairs')")  # before a run: the next step, not an error
    page.wait_for_selector("#screen .card.empty a[data-go=run]")
    assert not page.query_selector("#screen .banner.error, #screen .split")
    page.go_back()  # Back walks the steps
    page.wait_for_selector("h1:has-text('Prepare your data')")
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector("[data-first]")
    page.click("[data-first]")
    page.click("dialog button[value=run]")
    page.wait_for_selector(".steps-card")
    page.reload()  # mid-run: the step it was on, the run followed to its end
    page.wait_for_selector("h1:has-text('Find matches')")
    page.wait_for_selector(".spin", timeout=10_000)
    page.wait_for_selector("h2.question.big", timeout=120_000)  # the run's result, drawn when it ended
    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("[data-a=no_match]")
    page.keyboard.press("n")  # different, then back to it
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
    page.keyboard.press("ArrowUp")
    page.wait_for_selector("#right .chip:has-text('you: different')")
    assert page.get_attribute("#right [data-a=no_match]", "aria-pressed") == "true" and page.get_attribute("#right [data-a=match]", "aria-pressed") == "false"
    said = page.evaluate("""() => hurts([{field: "phone", filled: null}, {field: "person_name", filled: 0.2}, {field: "company_name", filled: 0.15}, {field: "birth_date", filled: 0.1}],
        ["level phone: exact (needs ['phone'])", "comparison phone", "prior rule ['full_name', 'address_code', 'phone']", "EM rule ['phone']", "probe phone (needs ['phone'])",
         "generator phone_initial (needs ['phone'])"],
        "", {}, [["person_name", "company_name"]]).map((x) => x.replace(/<[^>]+>/g, ""))""")
    assert said == ["Birth date is 10% filled: matching leans on it less",  # a person's and a company's name, filled together: no warning
                    "No column is mapped to phone: 1 way of finding pairs, 1 comparison step, 3 checks turned off"], said  # every check, in words
    verdict = page.evaluate("""() => [trialCard({trial: 1, method: {}, base: {matched: 2, expected_false: 0, entities: 9}, variant: {matched: 2, expected_false: 0, entities: 9},
        different_joined: {base: 1, variant: 1}, same_apart: {base: 0, variant: 0}, fixed: [{}], broken: [{}], apart: 1, together: 1}),
        trialCard({trial: 2, method: {}, base: {matched: 2}, variant: {matched: 1}, different_joined: {base: 1, variant: 0}, same_apart: {base: 0, variant: 0}, fixed: [{}], broken: [], apart: 1, together: 0})]
        .map((h) => [h.includes("Worse"), h.includes("Better"), h.includes('btn filled" data-adopt')])""")
    assert verdict == [[True, False, False], [False, True, True]]  # one it sets wrong is worse, however the totals net out; Adopt stands out only when better
    page.click(".tab[data-go=kinds]")  # Review's second tab
    page.wait_for_selector("[data-a=person]")
    assert page.get_attribute("#some [data-part=flagged]", "aria-selected") == "true" and "Flagged" in page.inner_text("#some")  # the flagged records first
    assert {r.strip() for r in page.locator("#left tbody tr td:first-child").all_inner_texts()} == {"flagged"}  # drawn at random or not
    page.keyboard.press("1")
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
    page.click("#some [data-part=measure]")  # the draw that teaches the engine: optional, apart
    page.wait_for_selector("#some [data-part=measure][aria-selected=true]")
    assert "optional" in page.inner_text("#some") and page.inner_text("#written") == "1"  # an answer from the other part still counts to apply
    page.click("#some [data-part=flagged]")
    page.wait_for_selector("#some [data-part=flagged][aria-selected=true]")
    page.reload()  # the answer as the server keeps it: a code, said in words
    page.wait_for_selector("[data-a=person]")
    page.keyboard.press("ArrowUp")
    page.wait_for_selector("#right .chip:has-text('answered · person')")
    assert page.get_attribute("#right [data-a=person]", "aria-pressed") == "true"
    from er.cli import main
    phone = s.columns["phone"][0][0]
    assert main(["set", "columns", "phone=", "--workspace", str(tmp_path / "workspaces" / "w")]) == 0  # an empty slot
    page.click(".navitem[data-screen=columns]")
    page.wait_for_selector(".drop[data-slot*='hone'] .hole", state="attached", timeout=60_000)
    group = page.query_selector("details.fgroup:has(.drop[data-slot*='hone'] .hole)")
    if not group.get_attribute("open"):
        group.query_selector("summary").click()  # its group, opened
    hole = page.wait_for_selector(".drop[data-slot*='hone'] .hole")
    hole.focus()
    page.keyboard.press("Enter")  # by keyboard: the file's columns in a list
    page.select_option(".drop select", phone)
    page.wait_for_selector("#out:not([aria-busy]) details.fgroup", state="attached", timeout=30_000)
    assert phone in (tmp_path / "workspaces" / "w" / "columns.toml").read_text(encoding="utf-8").split("phone =", 1)[1].split("\n", 1)[0]  # saved


def test_a_file_loaded_after_a_run_is_offered_to_the_run_first(ui_page, tmp_path, population):
    from er import cli, folder
    s, p, g = population
    half = len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    g.df.iloc[half:].to_parquet(tmp_path / "batch.parquet", index=False)
    ws = tmp_path / "workspaces" / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(tmp_path / "workspaces")]) == 0
    assert cli.main(["resolve", "records", str(tmp_path / "first.parquet"), "--workspace", str(ws)]) == 0
    assert cli.main(["load", "records", str(tmp_path / "batch.parquet"), "--workspace", str(ws)]) == 0  # loaded on step 2, after the run
    page, server, httpd = ui_page(str(ws), str(tmp_path / "workspaces"))
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector(".card.ready [data-add]")
    assert "Replace the run" in page.inner_text(".card.ready")  # matching it alone is said for what it does
    page.click(".card.ready [data-first]")
    page.wait_for_function("() => document.querySelector('#equiv-line').textContent.endsWith('--overwrite')")  # what it says: the run's results go
    page.keyboard.press("Escape")
    page.click(".card.ready [data-add]")
    assert "batch.parquet" in page.inner_text("dialog .about")
    page.click("dialog button[value=run]")
    page.wait_for_selector(".card.ready", state="detached", timeout=120_000)  # added: nothing left not matched
    page.wait_for_selector("h2.question.big")
    assert all(x["read"] for x in folder.loaded(ws))


def test_look_up_and_the_score_chart_behave_as_a_person_uses_them(ui_page, tmp_path, population, say, monkeypatch):
    """By keyboard and mouse: a name typed in hiragana, a phone in full-width digits and a placeholder each answered as a
    person expects; Show kept; a chart that leaves an increment out says so, with the action that counts it; a file's
    values written two ways offered as one on Your data, in one click."""
    import json
    from er import cli
    s, p, g = population
    uid = s.data.unique_id
    monkeypatch.chdir(tmp_path)
    df = g.df.copy()
    batch = df.sample(40, random_state=3)
    df.drop(batch.index).to_parquet("first.parquet", index=False)
    batch.to_parquet("batch.parquet", index=False)
    say("create", "workspace", "w")
    ws, at = tmp_path / "workspaces" / "w", ("--workspace", "workspaces/w")
    assert say("resolve", "records", "first.parquet", *at)[0] == 0 and say("build", "index", *at)[0] == 0
    assert say("add", "records", "batch.parquet", *at)[0] == 0  # the index kept up to date by it
    one = df.drop(batch.index).dropna(subset=["FULL_NAME_KANA", "PHONE_NUM_4"]).iloc[0]
    hira = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in one["FULL_NAME_KANA"])
    wide = "".join(chr(ord(c) + 0xFEE0) for c in one["PHONE_NUM_4"])
    page, server, httpd = ui_page(str(ws), str(tmp_path / "workspaces"), {"width": 1440, "height": 900})
    shot = lambda name: page.screenshot(path=str(tmp_path / f"{name}.png"), full_page=True)

    page.click("#nav [data-screen=lookup]")
    page.wait_for_selector("#lu:not([inert])", timeout=60_000)
    name = page.locator("#lu input[name='FULL_NAME_KANA']")
    name.click()
    page.keyboard.type(hira, delay=40)  # in hiragana, as an IME leaves it
    page.wait_for_selector("#suggest .lu-hit", timeout=30_000)
    shown = lambda: [x.get_attribute("data-record") for x in page.query_selector_all("#suggest .lu-hit [data-record]")]
    page.wait_for_function("(r) => [...document.querySelectorAll('#suggest .lu-hit [data-record]')].some((x) => x.dataset.record === r)", arg=one[uid], timeout=30_000)
    shot("hiragana")
    name.fill("")
    page.wait_for_function("() => document.querySelector('#suggest').innerHTML === ''", timeout=30_000)  # nothing typed: nothing suggested
    page.locator("#lu input[name='PHONE_NUM_4']").click()
    page.keyboard.type(wide, delay=40)  # full-width digits
    page.wait_for_function("(r) => [...document.querySelectorAll('#suggest .lu-hit')].some((c) => c.querySelector(`[data-record='${r}']`) && /phone/.test(c.textContent))",
                           arg=one[uid], timeout=30_000)
    shot("full-width")
    page.locator("#lu input[name='PHONE_NUM_4']").fill("")
    name.click()
    page.keyboard.type("-")  # a placeholder alone: nothing to search by, no error
    page.wait_for_function("() => /Nothing to search by yet/.test(document.querySelector('#suggest')?.textContent || '')", timeout=30_000)
    assert not page.query_selector("#suggest .banner")
    sent = []
    page.on("request", lambda q: q.url.endswith("/api/run") and "search records" in (q.post_data or "") and sent.append(q.post_data))
    page.evaluate("""() => { const i = document.querySelector("#lu input[name='FULL_NAME_KANA']"); i.value = "まt";  // an IME converting: no value yet
        i.dispatchEvent(new InputEvent("input", {bubbles: true, isComposing: true})); }""")
    page.wait_for_timeout(800)
    assert not sent  # nothing searched while the word is chosen
    page.evaluate("""() => { const i = document.querySelector("#lu input[name='FULL_NAME_KANA']"); i.value = "-"; i.dispatchEvent(new CompositionEvent("compositionend", {bubbles: true})); }""")
    page.wait_for_timeout(800)  # past the pause
    assert sent  # searched once it is chosen
    page.keyboard.press("Enter")  # looked up: refused in words a person reads
    page.wait_for_selector("#found .banner", timeout=30_000)
    assert "read as missing" in page.inner_text("#found .banner") and "COLUMN=VALUE" not in page.inner_text("#found .banner")
    shot("placeholder")
    name.fill(one["FULL_NAME_KANA"])  # a name alone: none reaches the line, and the page says how near the nearest came
    page.keyboard.press("Enter")
    page.wait_for_function("() => /None reaches/.test(document.querySelector('#found')?.textContent || '')", timeout=30_000)
    assert "One value alone weighs too little" in page.inner_text("#found") and "None here looks like it" not in page.inner_text("#found")
    shot("name-alone")
    page.fill("#lu-top", "1")
    page.dispatch_event("#lu-top", "change")
    name.fill(one["FULL_NAME_KANA"][:2])
    page.wait_for_function("() => document.querySelectorAll('#suggest .lu-hit').length === 1", timeout=30_000)
    page.reload()
    page.wait_for_selector("#lu-top")
    assert page.input_value("#lu-top") == "1" and shown() == []
    from er import index
    cap = index.CAP
    monkeypatch.setattr(index, "CAP", 3)  # a name too common to list whole: how many, and its first by name, still shown
    page.fill("#lu-top", "5")
    page.dispatch_event("#lu-top", "change")
    page.locator("#lu input[name='FULL_NAME_KANA']").fill(df["FULL_NAME_KANA"].dropna().str[0].value_counts().index[0])
    page.wait_for_function("() => /records start with .*: the first by name below/.test(document.querySelector('#suggest')?.textContent || '')", timeout=30_000)
    assert page.locator("#suggest .lu-hit").count() >= 1
    shot("too-common")
    monkeypatch.setattr(index, "CAP", cap)

    log = json.loads((ws / "steps.json").read_text(encoding="utf-8"))  # a run logged before each counted its own bands
    for run in log["runs"]:
        for x in run["steps"]:
            x.pop("bands", None)
    (ws / "steps.json").write_text(json.dumps(log), encoding="utf-8")
    page.click("#nav [data-screen=records]")
    page.wait_for_selector(".tile:has-text('How did the scores come out?')", timeout=60_000)
    assert "the 40 records added since aren't in it" in page.inner_text(".tile:has-text('How did the scores come out?')")
    shot("results-uncounted")
    page.click("#nav [data-screen=results]")
    page.wait_for_selector("#rerun-count", timeout=60_000)
    total = cli.describe_results_({"workspace": str(ws)}, None)["listed"]
    page.wait_for_function("(n) => document.querySelector('#screen').innerText.includes(`of ${n.toLocaleString('en-US')}`)", arg=total, timeout=30_000)
    assert f"The {total:,} at 0 or more" in page.inner_text("#screen")  # the count its list shows
    shot("explore-uncounted")
    page.click("#rerun-count")  # the one action: matching run again, its dialog open on Find matches
    page.wait_for_selector("h1:has-text('Find matches')", timeout=30_000)
    page.wait_for_selector("#dlg[open]")
    assert "Run matching again" in page.inner_text("#dlg")
    page.keyboard.press("Escape")

    say("create", "workspace", "plain")
    plain = ("--workspace", "workspaces/plain")
    say("set", "preparation", "phone=", *plain)  # a workspace whose mapping reads phones as written
    pd.concat([df, df.iloc[[0]].assign(**{uid: "9" * len(df[uid].iloc[0]), "PHONE_NUM_4": "12-34"})]).to_parquet("hyphens.parquet", index=False)
    assert say("resolve", "records", "hyphens.parquet", *plain)[0] == 0  # it has run: a change of its mapping owes the run again
    page.click("#picker")
    page.click("text=plain")
    page.click("#nav [data-screen=columns]")
    page.wait_for_selector("button.mini:has-text('Read as one')", timeout=60_000)
    shot("your-data-hint")
    page.click("button.mini:has-text('Read as one')")
    page.wait_for_function("() => ![...document.querySelectorAll('button.mini')].some((b) => b.textContent.includes('Read as one'))", timeout=60_000)
    assert '"strip_separators"' in (tmp_path / "workspaces" / "plain" / "columns.toml").read_text(encoding="utf-8")
    page.wait_for_selector("#rerun-owed", timeout=30_000)  # said where the person is, with the one action
    assert "changed since the last run" in page.inner_text("#loaded .answer")
    shot("your-data-fixed")
    page.click("#rerun-owed")
    page.wait_for_selector("h1:has-text('Find matches')", timeout=30_000)
    page.wait_for_function("() => /changed: run again/.test(document.querySelector('.pagehead')?.textContent || '')", timeout=30_000)  # its step says so too


def test_step_2_generates_synthetic_records_by_size_and_difficulty_once_per_click(ui_page, tmp_path):
    from er import cli, folder
    home, ws = tmp_path / "workspaces", tmp_path / "workspaces" / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(ws), str(home), viewport={"width": 1280, "height": 900})
    posted = []
    page.on("request", lambda r: r.method == "POST" and not json.loads(r.post_data).get("dry") and posted.append(json.loads(r.post_data)))
    page.click(".navitem[data-screen=columns]")
    assert not page.is_visible("#gsize")  # folded until asked for
    page.click("#synth > summary")
    page.select_option("#gsize", "10000")
    page.select_option("#glevel", "hard")
    page.click("#gen")
    assert page.is_disabled("#gen") and page.is_disabled("#load")  # one at a time, either way
    page.click("#gen", force=True)  # a second click while it runs: nothing
    page.click(".navitem[data-screen=records]")
    page.click(".navitem[data-screen=columns]")  # left and back while it runs: drawn waiting, then freed and drawn once it ends
    assert page.is_disabled("#gen") and page.is_disabled("#load") and page.input_value("#gsize") == "10000" and page.input_value("#glevel") == "hard"  # as it was asked
    page.wait_for_selector("#loaded .answer:has-text('10,000 records')", timeout=120_000)
    assert [x for x in posted if x["command"] == "generate records"] == [{"command": "generate records", "args": {"records": "10000", "difficulty": "hard", "workspace": str(ws)}}]
    assert "synthetic-hard-10000.parquet · 10,000 records" in page.inner_text("#loaded") and page.is_visible("#loaded [data-go=run]")
    page.click("#loaded details.fold-line > summary")  # Load another file: synthetic records there too
    page.click("#loaded #synth > summary")
    assert not page.is_disabled("#gen") and not page.is_disabled("#load")
    page.select_option("#gsize", "10000")
    page.select_option("#glevel", "hard")
    page.click("#gen")
    page.wait_for_function("() => { const b = document.querySelector('#gen'); return b && !b.disabled && b.textContent === 'Generate'; }", timeout=120_000)
    assert len(folder.parts(ws)) == 1 and not page.query_selector("#out .banner.bad")  # the same records: held already, nothing copied
    free = "() => { const b = document.querySelector('#gen'); return b && !b.disabled && b.textContent === 'Generate'; }"
    for size, level in (("1000", "easy"), ("10000", "hard")):  # another, then the first again: held already, and the one a run reads
        page.evaluate("document.querySelectorAll('#loaded details').forEach((d) => { d.open = true; })")
        page.select_option("#gsize", size)
        page.select_option("#glevel", level)
        page.click("#gen")
        page.wait_for_function(free, timeout=120_000)
    page.wait_for_function("() => document.querySelector('#loaded .answer').innerText.includes('synthetic-hard-10000.parquet')", timeout=30_000)  # step 2: the file given last
    assert "10,000 records" in page.inner_text("#loaded .answer") and "synthetic-hard-10000" in page.inner_text(".navitem[data-screen=columns]")  # its count, and the step list
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector("[data-first]")
    assert len(folder.parts(ws)) == 2 and "synthetic-hard-10000.parquet" in page.inner_text("#out")  # the file given last, not the newest copy


def test_policy_rows_sit_in_each_record_s_full_row_chosen_by_their_chips_with_the_pair_s_other_candidates_beside_it(ui_page, tmp_path, population):
    from er import cli
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    home, ws = tmp_path / "workspaces", tmp_path / "workspaces" / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    given = pd.DataFrame([{uid: int(i), "PLAN": f"plan {i}-{k}", "NOTE": "not shown"} for n, i in enumerate(g.df[uid]) for k in range(n % 3 + 1)])  # a number key, 1 to 3 rows each
    given.to_parquet(tmp_path / "contracts.parquet", index=False)
    plans = lambda i: list(given.loc[given[uid] == int(i), "PLAN"])
    lines = lambda cell: cell.locator("div").all_inner_texts()
    page, server, httpd = ui_page(str(ws), str(home), viewport={"width": 1440, "height": 900})
    page.click(".navitem[data-screen=columns]")
    page.wait_for_selector("#din")
    assert page.inner_text("#details h2.question") == "Policy information" and not page.query_selector("#details .answer")
    page.fill("#din", str(tmp_path / "contracts.parquet"))
    page.click("#dload")
    page.wait_for_selector("#dlist input[data-col=NOTE]:checked", timeout=60_000)
    assert "100% of records have some" in page.inner_text("#details .answer")
    page.uncheck("#dlist input[data-col=NOTE]")  # not shown to reviewers
    deadline = time.time() + 15
    while json.loads((ws / "details" / "details.json").read_text(encoding="utf-8"))["shown"] != ["PLAN"] and time.time() < deadline:
        time.sleep(0.2)
    assert json.loads((ws / "details" / "details.json").read_text(encoding="utf-8"))["shown"] == ["PLAN"]

    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("#right .fullrows tr.det-head", timeout=60_000)
    page.fill("#from", "0")
    page.keyboard.press("Tab")  # every pair waiting: some share a record
    page.wait_for_function("() => document.querySelector('#done-line, .progress').innerText.includes('from 0 points')", timeout=60_000)
    page.wait_for_selector("#left tr.pick")
    queue = [r.locator("td div").all_inner_texts()[:2] for r in page.locator("#left tr.pick").all()]
    seen = {}
    for k, ids in enumerate(queue):
        for i in ids:
            seen.setdefault(i, []).append(k)
    twice = next(i for i, ks in seen.items() if len(ks) > 1)  # a record in two pairs: the other a candidate beside the pair
    page.locator("#left tr.pick").nth(seen[twice][0]).click()
    page.wait_for_function("() => document.querySelectorAll('#right .fullrows thead th').length >= 5", timeout=60_000)
    heads = page.locator("#right .fullrows thead th").all_inner_texts()
    assert "a candidate with" in heads[3] and page.locator("#right .fullrows thead [data-open]").count() >= 1
    assert page.locator("#right .fullrows tbody tr").first.get_attribute("class") == "det-head"  # the policies first, then the record's own columns
    assert page.locator("#right tr.det-row td.col").all_inner_texts() == ["PLAN"]  # the column turned off left out
    ids = [h.split("\n")[0] for h in heads[1:-1]]
    cells = page.locator("#right tr.det-row").first.locator("td.det-v")
    assert [lines(cells.nth(k)) for k in range(len(ids))] == [plans(i)[:1] for i in ids]  # each record's first policy, unless others are chosen
    a = ids[0]
    for chip in page.locator(f"#right [data-rec='{a}'][aria-pressed=false]").all():
        chip.click()
    assert lines(page.locator("#right tr.det-row").first.locator("td.det-v").first) == plans(a)  # every one chosen: each on its own line, in the file's order
    dots = page.locator("#right tr.det-row").first.locator("td.det-v").first.locator(".pdot")
    assert len({d.get_attribute("style") for d in dots.all()}) == len(plans(a))  # a color each
    assert "no policy in common" in page.inner_text("#right tr.det-head td.col") or len(ids) > 2  # the pair's flag: a fact of the two
    for sec, rows in (("policy", "#right tr.det-row"), ("customer", "#right tr.fr-same, #right tr.fr-different, #right tr.fr-empty")):  # each section folded, then opened
        page.click(f"#right [data-sec={sec}]")
        assert page.locator(rows).count() == 0 and page.get_attribute(f"#right [data-sec={sec}]", "aria-expanded") == "false"
        page.click(f"#right [data-sec={sec}]")
        assert page.locator(rows).count() > 0
    page.locator("#right .fullrows thead [data-open]").first.click()  # a candidate's own pair, opened
    page.wait_for_function(f"() => document.querySelector('#right .fullrows thead')?.innerText.includes({json.dumps(twice)})", timeout=30_000)

    assert page.evaluate(r"""() => {  // one policy number, one color, both sides; a new one, the farthest from those in use
      const det = {file: "x", columns: ["P"], records: [{id: "a", rows: [["p1"], ["p2"]], total: 2}, {id: "b", rows: [["p2"], ["p3"]], total: 2}]};
      const chosen = {a: new Set([0, 1]), b: new Set([0, 1])}, html = detailRows(det, ["a", "b"], "", () => true, chosen);
      const colors = [...html.matchAll(/--pc: (oklch\([^)]*\))/g)].map((m) => m[1]);  // the chips', then the lines', each record's in turn
      const many = [], used = [];
      for (let n = 0; n < 50; n++) { const c = polColor(used); used.push(c.lab); many.push(c.css); }
      return colors.includes(chosen.colors.get("p2").css) && new Set([...chosen.colors.values()].map((c) => c.css)).size === 3 && new Set(many).size === 50
        && html.includes("1 in common");
    }""")

    page.evaluate("location.hash = '#kinds'")  # a record asked person or company: its rows too
    page.wait_for_selector("#right .det-box tr.det-head", timeout=60_000)
    asked = page.get_attribute("#right .det-box", "data-id")
    assert lines(page.locator("#right .det-box td.det-v").first) == plans(asked)[:1]

    one = str(g.df[uid].iloc[4])
    page.evaluate(f"go('results', {{tab: 'records', record: {json.dumps(one)}}})")  # Explore's one record
    page.wait_for_selector("#rec tr.det-head", timeout=60_000)
    assert lines(page.locator("#rec td.det-v").first) == plans(one)[:1] and page.locator("#rec [data-policy]").count() == len(plans(one))  # a chip each, one policy too

    page.click(".navitem[data-screen=pairs]")  # the line between the pair and its queue: dragged, kept
    page.wait_for_selector(".grip-v")
    grip = page.locator(".grip-v").bounding_box()
    before = page.locator("#right").bounding_box()["width"]
    page.mouse.move(grip["x"] + 6, grip["y"] + 100)
    page.mouse.down()
    page.mouse.move(grip["x"] + 160, grip["y"] + 100, steps=6)
    page.mouse.up()
    wider = page.locator("#right").bounding_box()["width"]
    page.reload()
    page.wait_for_selector("#right .fullrows")
    assert wider > before + 100 and abs(page.locator("#right").bounding_box()["width"] - wider) < 8  # the next visit too


def test_step_2_s_policy_columns_are_one_list_in_their_order_dragged_and_kept_even_just_before_leaving(ui_page, tmp_path):
    from er import cli
    uid = load_settings().data.unique_id
    home, ws = tmp_path / "workspaces", tmp_path / "workspaces" / "w"
    pd.DataFrame({uid: ["0001", "0002"], "FULL_NAME_KANA": ["ヤマダタロウ", "スズキハナコ"]}).to_parquet(tmp_path / "records.parquet", index=False)
    pd.DataFrame({uid: [1, 1, 2], "PLAN": ["a", "b", "c"], "START": ["2020", "2021", "2022"], "AGENT": ["x", "y", "z"]}).to_parquet(tmp_path / "contracts.parquet", index=False)
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    for words in (["load", "records", str(tmp_path / "records.parquet")], ["load", "details", str(tmp_path / "contracts.parquet"), "--columns", "PLAN", "START"]):
        assert cli.main([*words, "--workspace", str(ws), "--format", "json"]) == 0
    shown = lambda: json.loads((ws / "details" / "details.json").read_text(encoding="utf-8"))["shown"]
    def until(want):
        deadline = time.time() + 15
        while shown() != want and time.time() < deadline:
            time.sleep(0.2)
        assert shown() == want
    page, server, httpd = ui_page(str(ws), str(home), viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.click(".navitem[data-screen=columns]")
    page.wait_for_selector("#dlist .drow.on")
    on = lambda: [r.get_attribute("data-col") for r in page.locator("#dlist .drow.on").all()]
    assert on() == ["PLAN", "START"] and page.locator("#dlist .drow:not(.on)[data-col]").count() == 1  # shown, in order; then the others
    page.check("#dlist input[data-col=AGENT]")  # ticked: shown, last
    until(["PLAN", "START", "AGENT"])
    page.focus("#dlist .drow[data-col=AGENT]")
    page.keyboard.press("Alt+ArrowUp")  # moved one place up, the keyboard staying on it
    until(["PLAN", "AGENT", "START"])
    assert page.evaluate("document.activeElement.dataset.col") == "AGENT"
    rows = page.locator("#dlist .drow.on")
    src, dst = rows.nth(2).bounding_box(), rows.nth(0).bounding_box()
    page.mouse.move(src["x"] + 10, src["y"] + src["height"] / 2)
    page.mouse.down()
    page.mouse.move(dst["x"] + 10, dst["y"] + 4, steps=8)  # dragged by its dots above the first
    page.mouse.up()
    until(["START", "PLAN", "AGENT"])
    assert "names each policy" in page.inner_text("#dlist .drow[data-col=START]")
    page.fill("#dfind", "ag")
    assert [r.get_attribute("data-col") for r in page.locator("#dlist .drow[data-col]").all()] == ["AGENT"]  # one search, both parts
    page.fill("#dfind", "")

    page.evaluate("(() => { const real = runOnce; window.runOnce = (c, ...r) => c === 'describe records' ? new Promise((ok) => setTimeout(() => ok(real(c, ...r)), 3000)) : real(c, ...r); })()")
    page.evaluate("go('columns')")  # drawn again, its file's description slow: a change waits behind it
    page.wait_for_selector("#dlist input[data-col=PLAN]")
    page.uncheck("#dlist input[data-col=PLAN]")
    page.evaluate("go('run')")  # left before the change is saved
    until(["START", "AGENT"])
    assert not errors  # saved all the same


def test_a_command_the_server_started_without_says_start_it_again_and_frees_its_buttons(ui_page, tmp_path, monkeypatch):
    from er import cli, folder, ui
    home, ws = tmp_path / "workspaces", tmp_path / "workspaces" / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(home), "--format", "json"]) == 0
    known = ui.declarations
    monkeypatch.setattr(ui, "declarations", lambda: [c for c in known() if c["name"] != "generate records"])  # a server started before the update that added it
    page, server, httpd = ui_page(str(ws), str(home))
    page.click(".navitem[data-screen=columns]")
    page.click("#synth > summary")
    page.click("#gen")
    page.wait_for_selector("#out .banner")
    assert "started before an update" in page.inner_text("#out .banner") and not folder.parts(ws)
    assert not page.is_disabled("#gen") and not page.is_disabled("#load") and page.inner_text("#gen") == "Generate"


def test_each_page_reads_its_own_workspace_and_every_tab_waits_out_a_long_command(ui_page, tmp_path, population, fake_cli):
    from er import cli
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    g.df.iloc[: len(g.df) // 2].to_parquet(tmp_path / "half.parquet", index=False)
    home = tmp_path / "workspaces"
    for name in ("ran", "half", "fresh"):
        assert cli.main(["create", "workspace", name, "--home", str(home), "--format", "json"]) == 0
    for name, f in (("ran", "all"), ("half", "half")):
        assert cli.main(["resolve", "records", str(tmp_path / f"{f}.parquet"), "--workspace", str(home / name), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(home / "ran"), str(home), viewport={"width": 1280, "height": 900})
    base = page.url.split("#")[0]
    page.goto(base + "#run")
    page.reload()  # opened at its address: drawn from its own steps, as a run's page after a run
    page.wait_for_selector("[data-act='rerun records']", timeout=30_000)
    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("#right [data-a]", timeout=30_000)
    ran_line, was = page.inner_text(".navitem[data-screen=pairs]"), page.input_value("#from")
    page.fill("#from", "")
    page.dispatch_event("#from", "change")  # emptied: as it was, never 0
    assert was not in ("", "0") and page.input_value("#from") == was
    page.evaluate(f"setWorkspace({json.dumps(str(home / 'half'))})")  # another workspace, on Review: its own line, never the last one's
    page.wait_for_selector("#right [data-a]", timeout=30_000)
    page.wait_for_function(f"() => document.querySelector('.navitem[data-screen=pairs]').innerText !== {json.dumps(ran_line)}", timeout=30_000)
    page.evaluate(f"setWorkspace({json.dumps(str(home / 'fresh'))})")
    page.click(".navitem[data-screen=results]")  # Explore before a run: what to do first, no endless wait
    page.wait_for_selector("#tabbody .card", timeout=30_000)
    page.wait_for_function("() => !document.querySelector('#screen .loading')", timeout=30_000)
    page.click(".navitem[data-screen=columns]")
    posted = []
    page.on("request", lambda r: r.method == "POST" and posted.append(json.loads(r.post_data)["command"]))
    page.fill("#cin", "/tmp/やまだ")
    page.dispatch_event("#cin", "keydown", {"key": "Enter", "isComposing": True})  # the Enter that ends a kana-to-kanji conversion
    page.wait_for_timeout(300)
    assert "load records" not in posted
    page.evaluate(f"setWorkspace({json.dumps(str(home / 'ran'))})")
    page.wait_for_function(f"() => document.querySelector('.navitem[data-screen=pairs]')?.innerText === {json.dumps(ran_line)}", timeout=30_000)
    other = page.context.browser.new_page()  # another tab, drawn before the long command starts
    other.goto(base + "#run")
    other.wait_for_selector("[data-act='rerun records']", timeout=30_000)
    theirs = []
    other.on("request", lambda r: r.method == "POST" and json.loads(r.post_data).get("command") == "rerun records" and not json.loads(r.post_data).get("dry") and theirs.append(1))
    end = tmp_path / "end-the-run"  # the run lasts until the test ends it: never over before a slow machine has looked
    fake_cli('print(json.dumps({"event": "step", "step": "load", "seconds": 0.1}), flush=True)\n'
             f't = time.time()\nwhile not os.path.exists({str(end)!r}) and time.time() - t < 120:\n    time.sleep(0.1)\n'
             'print(json.dumps({"event": "result", "summary": [["records", "1"]]}), flush=True)')
    page.click(".navitem[data-screen=run]")
    page.click("[data-act='rerun records']")
    page.click("#dlg button[value=run]")  # its dialog: waited for, as slow as a machine draws it
    page.wait_for_selector(".steps-card", timeout=30_000)
    page.click(".navitem[data-screen=pairs]")  # Review while its workspace matches again: answers wait for it
    page.wait_for_selector("#right [data-a]", timeout=30_000)
    assert page.is_disabled("#right [data-a=match]")
    posted.clear()
    page.keyboard.press("m")
    other.click("[data-act='rerun records']")  # the other tab, never told: follows the run, never starts one beside it
    other.click("#dlg button[value=run]")
    other.wait_for_selector(".steps-card", timeout=30_000)  # the run as it goes, here too
    end.touch()
    other.wait_for_selector("text=ran from another tab", timeout=60_000)  # and once it ends, said
    assert "decide pair" not in posted and not theirs
    page.wait_for_function("() => !document.querySelector('#right [data-a=match]')?.disabled", timeout=60_000)  # it ended: answers back
    narrow = page.context.browser.new_page()
    narrow.set_viewport_size({"width": 390, "height": 800})
    narrow.goto(base)
    narrow.wait_for_selector("#picker span")
    assert narrow.inner_text("#picker").strip() == "ran"  # the workspace's own name, at phone width
