"""The page in a browser (Chromium): every step, a lost server, a busy workspace."""
import threading
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from er.settings import load_settings

from conftest import dirty_csv


def test_the_page_answers_once_per_key_shows_any_row_and_says_when_the_server_is_gone(ui_page, tmp_path, population):
    from er import cli
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = tmp_path / "run"
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(run), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(run), str(tmp_path / "workspaces"))
    page.wait_for_selector(".next")
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
    assert page.inner_text("#loaded h2.question") == "Did your file load?" and page.inner_text("#loaded .answer").startswith("Not yet")  # its question first
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
    page.wait_for_selector(".next")
    assert not any(b.is_disabled() for b in page.query_selector_all("[data-loop]")) and not page.is_disabled("#search")
    page.click(".navitem[data-screen=pairs]")
    page.wait_for_selector("[data-a=match]")
    page.keyboard.press("m")
    page.keyboard.press("m")  # pressed again before the first answer is back
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
    page.wait_for_timeout(600)
    assert page.inner_text("#written") == "1" and not page.query_selector("#said .banner")  # one answer, no busy folder
    assert "nayose decide pair" in page.inner_text("#term-body")  # the command line it ran
    states = page.evaluate("""() => {  // each step's state, read from the workspace as describe workspace gives it
        const run = (pairs, kinds, audits = {checked: 0, false: 0}) => ({records: 9, entities: 7, round: 1, audits,
          pairs: {decide: 0, audit: 0, written_in: 0, ...pairs}, kinds: {decide: 0, measure: 0, written_in: 0, ...kinds}});
        const at = (d) => { const p = progress(d); return [p.next, p.steps.pairs.state, p.steps.kinds.state]; };
        return [at({event: "error", error: "no run"}), at(run({decide: 3}, {measure: 20})), at(run({}, {measure: 20})), at(run({}, {written_in: 2})),
                at(run({}, {measure: 20}, {checked: 50, false: 0})), at(run({}, {written_in: 2}, {checked: 12, false: 1}))]; }""")
    assert states == [["columns", "later", "later"], ["pairs", "attention", "optional"], ["improve", "done", "optional"], ["kinds", "done", "attention"],
                      ["results", "done", "optional"], ["improve", "done", "attention"]]  # the loop until audits hold; a false one first
    assert page.query_selector(".rail li.attention .sub").inner_text().endswith("to decide")  # the stepper points at the open pairs
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector(".node[data-node=candidates]")
    assert [n.get_attribute("data-node") for n in page.query_selector_all(".flow .node")] == ["records", "rules", "candidates", "score", "accept", "people", "group"]
    questions = page.evaluate("STAGE_Q")
    for node in ["records", "rules", "candidates", "score", "accept", "people", "group"]:  # each stage answers its question first
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
    assert page.query_selector(".wf-grid .wf rect.for")  # each comparison moves the total, from the start, toward the line
    assert not page.query_selector(".scene:popover-open")  # another page: the replay closed with the one it was on
    page.wait_for_selector(".wf-grid [data-how]")  # then the test that set each step, and what found the pair
    assert page.query_selector(".found-path .tag") and "points: about" in page.inner_text(".odds")
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
    path = page.inner_text("#path")  # how much each part covers: all the records, the pairs listed, the one shown
    assert re.fullmatch(r"All [\d,]+ records\s*›\s*[\d,]+ pairs to review\s*›\s*This pair · \d+ of [\d,]+", path), path
    assert page.query_selector(".zone.all .flow") and page.inner_text(".card.one .question").startswith("Same entity?")
    card, queue = page.query_selector("#right .card.one").bounding_box(), page.query_selector(".queue").bounding_box()
    assert card["x"] < queue["x"] and card["width"] > queue["width"]  # the pair asked about first and wide, its queue after
    assert not page.query_selector(".stepfoot a.filled")  # pairs still open here: the way on doesn't stand out yet
    page.click(".stepfoot a[data-go=kinds]")
    page.wait_for_selector("h1:has-text('Confirm person or company')")
    twice = page.evaluate("""async () => {  // the same command asked twice at once runs once
        const lines = () => [...document.querySelectorAll("#term-body .cmd")].filter((c) => c.textContent.startsWith("nayose list pairs")).length;
        const before = lines();
        await Promise.all([run("pairs", "list pairs"), run("pairs", "list pairs")]);
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
    lost = page.evaluate("() => run('pairs', 'list pairs')")
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
    from er import cli, intake
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
    part = next((home / "w" / "inputs").iterdir())
    assert intake.report(part)["accepted"] == ["realign"] and not page.query_selector("[data-accept=realign]")


def test_the_improve_page_tries_a_line_once_adopts_it_and_opens_the_next_round(ui_page, tmp_path, population):
    from er import cli, folder
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "run"
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    page, server, httpd = ui_page(str(ws), str(tmp_path / "workspaces"), viewport={"width": 1280, "height": 900})
    page.wait_for_selector(".next")
    assert "round 1" in page.inner_text(".rail li.loopstep .sub")  # the loop, under step 4
    page.click(".navitem[data-screen=pairs]")
    page.click(".stepfoot [data-go=improve]")  # from step 4's foot
    page.wait_for_selector("#out h2.question")
    assert page.inner_text("#out h2.question") == "Is the matching good enough yet?" and "Not known yet" in page.inner_text("#out .qa .answer")
    assert page.inner_text("h1") == "Improve matching" and "as tuned" in page.text_content("#rounds")
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
    assert page.inner_text("h1").endswith("Review possible matches") and folder.method(ws) == {"line": line + 2}
    page.wait_for_function("() => document.querySelector('.rail li.loopstep .sub').textContent.includes('round 2')")
    page.click(".navitem[data-screen=improve]")
    page.wait_for_selector("#out h2.question")
    assert "Back to the tuned method" in page.inner_text("#out") and not page.query_selector(".trial")  # the trial adopted: no card


def test_step_4_shows_the_trust_line_lowers_it_and_an_answer_waits_out_a_busy_workspace(ui_page, tmp_path, population, capsys, monkeypatch):
    from er import cli, folder
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "workspace", "w", "--format", "json"]) == 0  # a new workspace: nothing merges by itself
    ws = tmp_path / "workspaces" / "w"
    assert cli.main(["resolve", "records", "all.parquet", "--workspace", str(ws), "--format", "json"]) == 0
    capsys.readouterr()
    page, server, httpd = ui_page(str(ws), str(tmp_path / "workspaces"), viewport={"width": 1280, "height": 900})
    page.wait_for_selector(".next")
    assert page.inner_text(".rail li:last-child .sub") == "none joined yet"  # step 6: nothing joined, nothing to see
    page.evaluate("scrollTo(0, 400)")
    page.click(".navitem[data-screen=run]")
    page.wait_for_selector("#out h2.question.big")  # step 3, opened at its top: what the run did, and what waits
    said = page.inner_text("#out .card")
    assert page.evaluate("scrollY") == 0 and "Nothing merged by points yet: you check pairs first · 20+ can merge now" in said  # nothing scores 20 here
    assert page.query_selector(".flow .node[data-node=people]") and page.query_selector("#out .card [data-go=pairs]")
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
    page.wait_for_selector(".trustbar")
    assert page.inner_text(".trustbar").startswith("Nothing merges by points yet")
    page.click("#workload summary")  # how many pairs people must check, range by range: read once opened
    page.wait_for_selector("#workload .answer")
    assert page.inner_text("#workload .answer").startswith(("To let pairs scoring", "Nothing to check")) and page.query_selector("#workload tr[data-i]")
    page.click("[data-trust='lower trust']")  # nothing scores 20 on this population: that range merges at once
    page.click("dialog button[value=run]")
    page.wait_for_selector("#note .banner", timeout=120_000)
    assert folder.method(ws) == {"trust": 20.0}
    page.wait_for_function("() => document.querySelector('.trustbar')?.textContent.includes('checking 12–20: 0 of')")
    assert "Drawn from the pairs scoring 12–20" in page.inner_text("#right")
    page.keyboard.press("m")
    page.wait_for_function("() => document.querySelector('.trustbar')?.textContent.includes('checking 12–20: 1 of')")
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
    assert not page.query_selector("#said .banner") and "1 different" in page.inner_text(".trustbar")
    assert "12–20" in page.inner_text(".rail li.attention .sub")


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
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    page, server, httpd = ui_page(None, str(tmp_path / "workspaces"))
    page.wait_for_selector(".welcome")
    page.click(".navitem[data-screen=pairs]")  # a step that follows a run, before a workspace: the way in, across the page
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
    page.click(".navitem[data-screen=pairs]")  # before a run: the next step, not an error
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
    page.wait_for_selector("#right .chip:has-text('decided · different')")
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
    box = page.evaluate("""() => { const b = document.createElement("div"); showWorkload(b, {ranges: [
        {down_to: 20, up_to: null, pairs: 3, checked: 3, different: 1, sample: 3, chance_clean: null, reviews_left: 0, reviews_to_here: 0},
        {down_to: 12, up_to: 20, pairs: 40, checked: 0, different: 0, sample: 40, chance_clean: null, reviews_left: 40, reviews_to_here: 40}],
        hours: {to_each_line: [0, 0.1]}, seconds_per_pair: 10, unnamed: 0}); return b.querySelector(".answer").textContent; }""")
    assert box.startswith("Pairs scoring 20+ and below stay with you"), box  # not "to let 12–20 merge": nothing below a false pair merges by points
    box = page.evaluate("""() => { const b = document.createElement("div"); showWorkload(b, {ranges: [
        {down_to: 20, up_to: null, pairs: 3, checked: 0, different: 0, sample: 3, chance_clean: 1, reviews_left: 0, reviews_to_here: 0},
        {down_to: 12, up_to: 20, pairs: 40, checked: 0, different: 0, sample: 30, chance_clean: 0.9, reviews_left: 30, reviews_to_here: 30},
        {down_to: 8, up_to: 12, pairs: 60, checked: 1, different: 1, sample: 60, chance_clean: null, reviews_left: 59, reviews_to_here: 89}],
        hours: {to_each_line: [0, 0.1, 0.2]}, seconds_per_pair: 10, unnamed: 0}); return b.querySelector(".answer").textContent; }""")
    assert "8–12 and below stay with you" in box and "To let pairs scoring 12–20 merge: 30 pairs" in box, box  # both: what can merge, and what can't
    page.click(".navitem[data-screen=kinds]")
    page.wait_for_selector("[data-a=person]")
    page.keyboard.press("1")
    page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
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
