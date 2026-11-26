"""The functions nayose's SQL calls by name, the same on both engines: the character-level comparisons (rapidfuzz in
DuckDB, JavaScript in BigQuery) scoring as recorded (tests/fixtures/expected.json), the portable hash, and NFKC."""
import hashlib
import json
import random
import unicodedata
from pathlib import Path

import pandas as pd
import pytest

from nayose.engines import BUILT_IN, FUNCTIONS, STRINGS, DuckDB

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "expected.json").read_text(encoding="utf-8"))


def pairs(n: int, seed: int = 0) -> list[tuple[str, str]]:
    """Kana and ASCII values with their typos: a character changed, two swapped, one dropped or added, and unrelated ones."""
    rng = random.Random(seed)
    kana, ascii_ = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンガギグゲゴー", "abcdefgh0123"
    word = lambda alphabet: "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9)))
    out = []
    for _ in range(n):
        alphabet = kana if rng.random() < 0.7 else ascii_
        a, b = word(alphabet), []
        b = list(a)
        for _ in range(rng.randint(0, 3)):
            op = rng.random()
            if op < 0.3 and b:
                b[rng.randrange(len(b))] = rng.choice(alphabet)
            elif op < 0.5 and len(b) > 1:
                i = rng.randrange(len(b) - 1)
                b[i], b[i + 1] = b[i + 1], b[i]
            elif op < 0.7 and b:
                del b[rng.randrange(len(b))]
            else:
                b.insert(rng.randrange(len(b) + 1), rng.choice(alphabet))
        out.append((a, "".join(b) if rng.random() < 0.8 else word(alphabet)))
    return out


@pytest.fixture(scope="module")
def duck():
    engine = DuckDB()
    yield engine
    engine.close()


def test_the_comparisons_score_as_recorded_to_the_last_bit(duck):
    duck.con.register("t", pd.DataFrame(pairs(5_000), columns=["a", "b"], dtype="string").assign(i=range(5_000)))
    for name, (similarity, _) in FUNCTIONS.items():
        for cut in ("", ", 0.8" if similarity else ", 1", ", 0.95" if similarity else ", 2"):
            rows = duck.con.execute(f"SELECT cl_{name}{'_cut' if cut else ''}(a, b{cut}) FROM t ORDER BY i").fetchall()
            assert hashlib.sha256(repr(rows).encode()).hexdigest()[:16] == EXPECTED["comparisons"][f"{name}{cut}"], (name, cut)


def test_duckdb_s_own_comparisons_answer_where_both_strings_are_a_byte_a_character_as_the_twins_do(duck):
    one_byte = str.maketrans({chr(0x30A0 + i): chr(1 + i) for i in range(96)})  # records.sql's one-byte copies
    given = pairs(5_000)
    given += [(a.translate(one_byte), b.translate(one_byte)) for a, b in given if a and b and all("\u30a0" <= c <= "\u30ff" for c in a + b)]
    given += [("", ""), ("", "a"), ("abc", "abd"), ("ab", "abc"), ("0312", "0321"), ("1", "12")]
    duck.con.register("t3", pd.DataFrame(given, columns=["a", "b"], dtype="string"))
    for name, (similarity, _) in FUNCTIONS.items():
        for cut in ("0.75", "0.95") if similarity else ("1", "2"):
            test = ">=" if similarity else "<="
            assert duck.con.execute(f"""SELECT a, b FROM t3 WHERE cl_{name}(a, b) IS DISTINCT FROM twin_{name}(a, b)
                OR (cl_{name}_cut(a, b, {cut}) {test} {cut}) IS DISTINCT FROM (twin_{name}_cut(a, b, {cut}) {test} {cut})""").fetchall() == [], name
    assert duck.con.execute("SELECT COUNT(*) FROM t3 WHERE strlen(a) = length(a) AND strlen(b) = length(b) AND a <> '' AND b <> ''").fetchall()[0][0] > 1_000


def test_javascript_scores_as_the_duckdb_twins_do(duck):
    import py_mini_racer as mini_racer
    ctx = mini_racer.MiniRacer()
    ctx.eval(STRINGS.read_text(encoding="utf-8"))
    given = pairs(20_000)
    duck.con.register("t2", pd.DataFrame(given, columns=["a", "b"], dtype="string").assign(i=range(len(given))))
    for name in (n for n in FUNCTIONS if n not in BUILT_IN):  # BigQuery's own: deploy/smoke.py checks it there
        got = json.loads(ctx.eval(f"JSON.stringify({json.dumps(given, ensure_ascii=False)}.map(([a, b]) => {name}(a, b)))"))
        want = [x for (x,) in duck.con.execute(f"SELECT cl_{name}(a, b) FROM t2 ORDER BY i").fetchall()]
        assert [(a, b) for (a, b), g, w in zip(given, got, want) if g != w] == [], name


def test_the_one_byte_hash_is_as_recorded(duck):
    values = ["東京都千代田区丸の内1-1-1", "ｱｲｳ", "サトウ", None, "𠮷野家", "abc", "東京都千代田区丸の内1-1-1"]
    got = [r[0] for r in duck.con.execute("SELECT one_byte_hash(x) FROM (SELECT unnest(?) AS x)", [values]).fetchall()]
    assert got == EXPECTED["one_byte_hash"]
    assert got[0] == got[-1] and all(c.isascii() for c in got[0])


def test_the_portable_hash_and_nfkc(duck):
    values = ["サトウ", "", None, "12345", "ｶﾌﾞｼｷｶﾞｲｼｬ", "㈱ヤマダ"]
    got = [r[0] for r in duck.con.execute("SELECT er_hash(x) FROM (SELECT unnest(?) AS x)", [values]).fetchall()]
    assert got == [int(hashlib.md5((v or "").encode()).hexdigest()[:15], 16) for v in values]  # MD5's first 60 bits: what every sample and order by hash reads
    got = [r[0] for r in duck.con.execute("SELECT nfkc(x) FROM (SELECT unnest(?) AS x)", [values]).fetchall()]
    assert got == [None if v is None else unicodedata.normalize("NFKC", v) for v in values] and got[4] == "カブシキガイシャ" and got[5] == "(株)ヤマダ"


def test_a_name_s_jaro_winkler_never_passes_the_most_its_letters_allow(tmp_path, population):
    import nayose
    named = population.df[population.df["FULL_NAME_KANA"].notna()].head(300)
    typo = named.assign(CONT_ID="9" + named["CONT_ID"].str[1:], FULL_NAME_KANA=named["FULL_NAME_KANA"].str[:-1] + "アア")  # a letter changed and repeated
    pd.concat([named, typo]).to_parquet(tmp_path / "in.parquet", index=False)
    engine = DuckDB()
    nayose.records(engine, [tmp_path / "in.parquet"])
    got = engine.rows("""SELECT COUNT(*), COUNT(CASE WHEN name_jw_most(x, y) < cl_jaro_winkler(x.person_name__kana_fold, y.person_name__kana_fold)
                                                     - CAST(0.000001 AS FLOAT64) THEN 1 END),
                                COUNT(CASE WHEN name_jw_most(x, y) < CAST(0.75 AS FLOAT64) THEN 1 END)
                         FROM records AS x JOIN records AS y ON x.id < y.id
                         WHERE x.person_name__kana_fold IS NOT NULL AND y.person_name__kana_fold IS NOT NULL""")
    pairs, above, settled = got[0]
    assert pairs > 100_000 and above == 0 and settled > pairs / 2  # never under the score, and most pairs settled without a call
