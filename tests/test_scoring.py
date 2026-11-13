"""Scoring: string functions, u and m, the weights, the threshold and how it is chosen."""
import logging
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from splink import Linker

from er.config import (Budget, Comparator, Comparison, FSModel, Key, Level, Resolver, Rule, RulesSpec, Stage, ThresholdRule, keys_sql)
from er.evaluate import adopt, fp_upper, paired_test, wilson
from er.match import exact_u, parameters, rule_edges, sample_u, score_fs, train_fs, u_values, waterfall
from er.pipeline import (accept_curve, clustered, select_threshold)
from er.settings import load_settings
from er.standardize import normalize
from er.strings import connect
from er.tune import pick_within_noise

from conftest import PAIR, UID, model


def test_string_functions_are_character_level_and_null_safe(con_db):
    con, _ = con_db  # DuckDB's own jaro_winkler_similarity compares bytes and gives 0.897 here
    assert con.sql("select round(cl_jaro_winkler('サトウヒロシ', 'サトウタカシ'), 3), cl_levenshtein('サトウ', 'サトオ'), "
                   "cl_levenshtein('サトウ', NULL) is null").fetchall() == [(0.844, 1.0, True)]


@pytest.mark.skipif(not hasattr(__import__("os"), "getuid"), reason="POSIX owners and modes")
def test_the_spill_folder_is_the_person_s_own_or_refused(tmp_path, monkeypatch):
    import getpass
    import tempfile
    from er.config import InputError
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    con = connect()[0]
    spill = tmp_path / f"nayose-spill-{getpass.getuser()}"
    assert con.execute("SELECT current_setting('temp_directory')").fetchall()[0][0] == str(spill) and spill.stat().st_mode & 0o777 == 0o700
    spill.chmod(0o755)  # open to others: spilled records could be read
    with pytest.raises(InputError, match="isn't yours alone"):
        connect()
    assert connect({"temp_directory": str(tmp_path / "mine")})[0]  # a folder given: used as it is


def test_typed_addresses_normalize_to_one_key():
    typed = pd.Series(["東京都千代田区丸の内1丁目3番17号", "千代田区丸の内１－３－１７", "東京都千代田区丸の内1-3-17　サクラハイツ101"],
                      dtype="string")
    assert normalize(typed, ("address",), load_settings().standardize).nunique() == 1


def test_a_u_sample_is_drawn_once_per_set_of_records(con_db, records, monkeypatch):
    import er.match as M
    con, db = con_db
    labels = records.set_index(UID)["entity"]
    M.SCORED_U.clear()
    fresh = train_fs(model("labels"), records, db, UID, labels)
    sampled, real = [], M.sample_u
    monkeypatch.setattr(M, "sample_u", lambda m, comps, *a: sampled.extend(c.name for c in comps) or real(m, comps, *a))
    assert model("em").u_keys() == model("labels").u_keys()
    other = train_fs(model("em"), records, db, UID, labels)  # another m method, the same comparisons and records
    con.register("er_shuffled", records.sample(frac=1, random_state=0))  # the same records as a table, in another order
    table = M.scored_sample(model(), "er_shuffled", db, UID)
    assert sampled == []
    assert table == M.scored_sample(model(), records, db, UID) == u_values(other) == u_values(fresh)
    M.SCORED_U.clear()
    again = train_fs(model("labels"), records, db, UID, labels)
    assert sampled == ["name", "phone"] and parameters(fresh).fillna(0).round(12).equals(parameters(again).fillna(0).round(12))


def test_a_u_sample_counted_in_one_pass_gives_splink_s_u_to_the_last_bit(con_db, records):
    from er.match import fs_settings
    _, db = con_db
    gaps = records.assign(name=records["name"].mask(records.index % 7 == 0))  # a missing side: neither level's
    for pairs in (1e4, 300):  # every pair, and the share of records a hash of their ID draws
        m = replace(model(extra_name_levels=(Level(label="never", any_of=(("name", Comparator("jaro_winkler", 0.95)),)),)), u_max_pairs=pairs)
        linker = Linker(db.register(gaps.assign(name__one_byte=normalize(gaps["name"], ("one_byte",), None))), fs_settings(m, UID), log_level=logging.ERROR)
        linker.training.estimate_u_using_random_sampling(max_pairs=pairs, seed=m.seed, min_count_per_level=None, num_chunks=3)
        splink_u, ours = u_values(linker.misc.save_model_to_json()), sample_u(m, list(m.comparisons), gaps, db, UID)
        assert ours == splink_u and "never" not in ours["name"] and 0 < sum(ours["name"].values()) <= 1, pairs


def test_a_u_sample_kept_by_a_workspace_is_read_again_and_drawn_again_once_what_it_rests_on_changes(con_db, records, monkeypatch, tmp_path):
    import er.match as M
    _, db = con_db
    kept = tmp_path / "u_sampled.json"
    M.SCORED_U.clear()
    first = M.scored_sample(model(), records, db, UID, kept=kept)
    assert kept.is_file() and len(json_loads(kept)) == len(model().comparisons)
    sampled, real = [], M.sample_u
    monkeypatch.setattr(M, "sample_u", lambda m, comps, *a: sampled.extend(c.name for c in comps) or real(m, comps, *a))
    M.SCORED_U.clear()  # another process: nothing in memory
    assert M.scored_sample(model(), records, db, UID, kept=kept) == first and sampled == []  # read, never drawn
    monkeypatch.setattr(M, "U_CODE", "another")  # the code that samples changed: drawn again, the same u
    M.SCORED_U.clear()
    assert M.scored_sample(model(), records, db, UID, kept=kept) == first and sampled == ["name", "phone"]
    kept.write_text("{cut short", encoding="utf-8")  # a copy that can't be read: drawn again, never a failure
    M.SCORED_U.clear()
    assert M.scored_sample(model(), records, db, UID, kept=kept) == first
    monkeypatch.setattr(M, "U_KEPT", 2)
    for seed in range(3):  # bounded: the newest U_KEPT
        M.scored_sample(replace(model(), seed=seed), records, db, UID, kept=kept)
    assert len(json_loads(kept)) == 2


def json_loads(f):
    import json
    return json.loads(f.read_text(encoding="utf-8"))


def test_each_distinct_value_normalized_once_gives_the_column_value_by_value_and_the_keys_normalizers_fold_as_said():
    from er.standardize import _normalized
    std = load_settings().standardize
    values = ["ヤマダ　タロウ", "ｻﾄｳﾊﾅｺ", None, "すずき いちろう", "０３－１２３４－５６７８", "東京都港区1丁目2番3号 ビル5F", "(株)サトウ", "", "TANAKA"] * 50
    s = pd.Series(values, dtype="string")
    for steps in (("nfkc",), ("nfkc", "katakana", "strip_spaces"), ("nfkc", "strip_separators"), ("kana_fold", "one_byte"), ("one_byte_hash",), ("address",),
                  ("nfkc", "strip_legal_form", "kana_fold"), ("initial",), ("first3",), ("reverse",), ("casefold",), ("kana_fold", "long_vowel", "last3")):
        got, one_by_one = normalize(s, steps, std), _normalized(s, steps, std)
        assert got.equals(one_by_one) and got.dtype == one_by_one.dtype and got.index.equals(s.index), steps  # the same column, the same type
    names = pd.Series(["サイトオトシオ", "サイトウトシオ", "サトー", "ケエコ", "ナカイサアヤ", "ヤマシタサアヤ", None], dtype="string")
    assert list(normalize(names, ("kana_fold", "long_vowel"), std).fillna("")) == ["サイトウトシオ", "サイトウトシオ", "サトウ", "ケイコ", "ナカイサアヤ", "ヤマシタサアヤ", ""]
    assert list(normalize(names, ("kana_fold", "long_vowel", "last3"), std).fillna(""))[4:] == ["サアヤ", "サアヤ", ""]  # a married name's end, kept
    texts = pd.Series(["東京都港区1丁目", "TANAKA", "", None, "𠀋😀ア"], dtype="string")  # 4-byte characters too
    hashed = normalize(texts, ("one_byte_hash",), std)
    assert hashed.isna().tolist() == [False, True, True, True, False]  # ASCII: none, DuckDB compares it as it is
    assert all(len(h) == len(t) and h.isascii() for h, t in zip(hashed.dropna(), texts[hashed.notna()]))  # one byte a character


def test_a_one_edit_level_is_counted_exactly_through_deletion_keys(con_db):
    from rapidfuzz.distance import DamerauLevenshtein, Hamming, Levenshtein
    from er.match import counted
    _, db = con_db
    rng = np.random.default_rng(1)  # repeated values, an insertion, an adjacent swap, unequal lengths for Hamming, a blank
    vals = [f"{rng.integers(300):03d}" for _ in range(300)] + ["12", "123", "1234", "2134", None]
    kana = ["".join(rng.choice(list("アアイウ"), rng.integers(0, 5))) for _ in range(len(vals))]  # runs: one deletion from several places
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(len(vals))], "cif": vals, "phone": vals[::-1], "kana": kana}, dtype="string")
    one_off = lambda col, f: Comparison(name=col, null_if_missing=(col,), levels=(
        Level(label="exact", any_of=((col, Comparator("exact")),)), Level(label="one off", any_of=((col, Comparator(f, 1)),))))
    m = FSModel(name="t", comparisons=(one_off("cif", "damerau_levenshtein"), one_off("phone", "hamming"), one_off("kana", "levenshtein")), prior_rules=(),
                prior_recall=0.5, u_max_pairs=1e4, m_method="em", em_rules=(), seed=0, u_exact_by_counts=True, u_near_by_keys=True)
    u = exact_u(m, df, db)
    for name, dist in (("cif", DamerauLevenshtein.distance), ("phone", Hamming.distance), ("kana", Levenshtein.distance)):
        filled = df[name].dropna().tolist()
        pairs = [(a, b) for i, a in enumerate(filled) for b in filled[i + 1:]]
        assert u[name]["exact"] == pytest.approx(sum(a == b for a, b in pairs) / len(pairs))
        assert u[name]["one off"] == pytest.approx(sum(a != b and dist(a, b) <= 1 for a, b in pairs) / len(pairs))
        assert u[name]["else"] == pytest.approx(1 - u[name]["exact"] - u[name]["one off"])
    assert counted(m, u) == {"cif", "phone", "kana"} and counted(replace(m, u_near_by_keys=False), u) == set()  # nothing left to sample


def test_u_sampled_per_comparison_equals_sampling_them_together(con_db, records):
    _, db = con_db
    m = replace(model(), u_max_pairs=2_000)  # fewer than the 7,140 pairs, so a real sample
    name, phone = m.comparisons
    assert sample_u(m, [name, phone], records, db, UID) == {**sample_u(m, [name], records, db, UID), **sample_u(m, [phone], records, db, UID)}


def test_levels_without_an_estimate_get_bounds_not_splink_defaults(con_db, records):
    _, db = con_db  # JW ≥ 0.95 after JW ≥ 0.9: no pair can reach it
    m = model(extra_name_levels=(Level(label="shadowed", any_of=(("name", Comparator("jaro_winkler", 0.95)),)),))
    model_json = train_fs(m, records, db, UID)
    filled = model_json["er"]["filled"]  # m also lists phone: EM blocks on phone, so it can never estimate phone's m
    assert filled["u"] == [["name", "shadowed"]] and ["name", "shadowed"] in filled["m"]
    assert all("m_probability" in lv and "u_probability" in lv for c in model_json["comparisons"]
               for lv in c["comparison_levels"] if not lv.get("is_null_level"))
    assert parameters(model_json).set_index(["comparison", "level"]).at[("name", "shadowed"), "weight"] == 0


def test_registered_pairs_score_like_splink_blocking(con_db, records):
    _, db = con_db
    model_json = train_fs(model(), records, db, UID)
    splink_json = {k: v for k, v in model_json.items() if k != "er"}
    from er.standardize import normalize
    copied = records.assign(name__one_byte=normalize(records["name"], ("one_byte",), None))  # as er.standardize prepares them: Splink's own linker reads every column
    native = Linker(db.register(copied), {**splink_json, "blocking_rules_to_generate_predictions": [keys_sql((Key("phone"),))]},
                    log_level=logging.ERROR).inference.predict().as_pandas_dataframe().astype({"uid_l": "string", "uid_r": "string"})
    ours = score_fs(model_json, records, native[["uid_l", "uid_r"]], db, UID)  # Splink's SQL in one query of ours: the same to the last bit
    both = native.merge(ours, on=["uid_l", "uid_r"], suffixes=("_native", "_registered"))
    assert len(both) == len(native) > 0 and both["gamma_name_native"].nunique() > 1
    for c in ("match_weight", "match_probability", "gamma_name", "gamma_phone"):
        assert (both[f"{c}_native"] == both[f"{c}_registered"]).all(), c


def test_waterfall_bits_sum_to_the_match_weight(con_db, records):
    _, db = con_db
    model_json = train_fs(model(), records, db, UID)
    pairs = pd.DataFrame({"uid_l": ["001a", "000a", "000a"], "uid_r": ["001b", "000b", "059b"]}, dtype="string")
    scored = score_fs(model_json, records, pairs, db, UID)  # exact name, close name, different entity
    for _, row in scored.iterrows():
        bits = waterfall(model_json, {c: row[f"gamma_{c}"] for c in ("name", "phone")}, len(records))
        assert bits["bits"].sum() == pytest.approx(row["match_weight"])


def test_term_frequencies_come_from_the_fitting_records(con_db, records):
    _, db = con_db
    model_json, plain = train_fs(model(tf=True), records, db, UID), train_fs(model(), records, db, UID)
    other = records.assign(name=records["name"].where(records["uid"].isin(["001a", "001b"]), "ヨソ"))  # the pair's name: 2 of 120

    def weight(m: dict, df: pd.DataFrame, d) -> float:
        return score_fs(m, df, PAIR, d, UID)["match_weight"].item()
    with_tf = weight(model_json, records, db)
    assert with_tf != pytest.approx(weight(plain, records, db))  # the adjustment applies
    assert with_tf == pytest.approx(weight(model_json, other, db)) == pytest.approx(weight(model_json, other, connect()[1]))


def test_prior_is_rescaled_to_the_scored_set_size(con_db, records):
    _, db = con_db
    model_json = train_fs(model(), records, db, UID)
    padded = pd.concat([records, pd.DataFrame({"uid": [f"p{i:03d}" for i in range(120)], "name": "ヨソ", "phone": "9999",
                                               "entity": "pad"}, dtype="string")], ignore_index=True)
    lam = model_json["probability_two_random_records_match"]
    scaled = lam * (len(records) - 1) / (len(padded) - 1)
    expected = math.log2(scaled / (1 - scaled)) - math.log2(lam / (1 - lam))
    assert score_fs(model_json, padded, PAIR, db, UID)["match_weight"].item() - \
        score_fs(model_json, records, PAIR, db, UID)["match_weight"].item() == pytest.approx(expected)


def test_shared_connection_gives_the_same_rules_and_clusters_as_a_fresh_one(con_db):
    _, db = con_db
    spec = RulesSpec(standardize=load_settings().standardize, resolver=Resolver(method="connected_components"),
                     budget=Budget(max_pairs_per_record=10**4, max_block_size=10**4, target_rows=10**4, benchmark_pairs=100),
                     stages=(Stage(name="fuzzy", rules=(Rule(name="R", exact=("phone",), fuzzy=("name",)),),
                                   comparators={"name": Comparator("jaro_winkler", 0.8)}),))
    a = pd.DataFrame({"uid": ["1", "2", "3"], "phone": ["11", "11", "22"], "name": ["サトウ", "サトオ", "スズキ"]}, dtype="string")
    b = pd.DataFrame({"uid": ["7", "8", "9"], "phone": ["33", "33", "33"], "name": ["タナカ", "タナカ", "イトウ"]}, dtype="string")
    base = lambda d: pd.DataFrame({UID: d[UID], "cluster_id": d[UID]})
    first = rule_edges(spec, a, db, UID)[0]
    clustered(db.duckdb_con, db, base(a), first, a[UID], UID)  # leaves whatever it caches on the shared db
    shared, fresh = rule_edges(spec, b, db, UID)[0], rule_edges(spec, b, connect()[1], UID)[0]
    assert shared.reset_index(drop=True).equals(fresh.reset_index(drop=True)) and len(shared) == 1
    assert clustered(db.duckdb_con, db, base(b), shared, b[UID], UID).equals(clustered(*connect(), base(b), fresh, b[UID], UID))


def test_uncertainty():
    lo, hi = wilson(329, 420)
    assert (round(lo, 4), round(hi, 4)) == (0.7415, 0.8201)
    assert abs(fp_upper(0, 57) - 3 / 57) < 0.003       # zero FP among n bounds the rate at ≈ 3/n
    assert round(fp_upper(0, 3000), 4) == 0.001
    t = paired_test(base={("a", "b")}, variant={("a", "b"), ("c", "d"), ("x", "y")}, truth={("a", "b"), ("c", "d")})
    assert (t["TP_gains"], t["TP_losses"], t["FP_added"]) == (1, 0, 1)


def test_threshold_rule_takes_the_first_safe_weight_plus_margin():
    curve = pd.DataFrame(dict(min_match_weight=[0, 2, 4, 6, 8], pairs_FP=[3, 1, 0, 0, 0],
                              stage_fp_rate_hi=[0.03, 0.02, 0.016, 0.019, 0.02]))
    weight, _ = select_threshold(curve, ThresholdRule(grid=(0, 2, 4, 6, 8), max_fp=0, max_fp_rate_hi=0.05, margin_steps=1))
    assert weight == 6


def test_accept_curve_counts_pairs_over_folds():
    class Fold:  # accept_curve reads only the scored pairs
        def __init__(self, weights: list[float], fp: list[bool]):
            self.scored = pd.DataFrame(dict(match_weight=weights, fp=fp, named=True))
    curve = accept_curve([Fold([1, 5, 9], [True, False, False]), Fold([3, 7], [True, False])], [0, 4, 8])
    assert curve[["accepted", "pairs_FP"]].to_numpy().tolist() == [[5, 2], [3, 0], [1, 0]]
    assert curve["stage_fp_rate_hi"].iloc[1] == pytest.approx(fp_upper(0, 3))


def test_adopt_by_rule():
    sel = dict(TP_gains=10, TP_losses=0, p=0.002, FP_added=0, FP_removed=0)
    val = dict(TP_gains=1, TP_losses=0, FP_added=0, FP_removed=0)
    assert adopt("better", sel, val, 0.05)
    assert not adopt("better", sel | dict(FP_added=1), val, 0.05)       # adds a false pair on the selection set
    assert not adopt("better", sel | dict(p=0.2), val, 0.05)            # gain within noise
    assert not adopt("better", sel, val | dict(TP_losses=2), 0.05)       # loses on val
    assert adopt("cheaper", dict(sel, TP_gains=0, p=1.0), val, 0.05)
    assert not adopt("cheaper", sel | dict(TP_losses=1), val, 0.05)


def test_pick_within_noise_prefers_the_cheaper_tie():
    front = pd.DataFrame(dict(recall=[0.90, 0.91], lo=[0.87, 0.88], hi=[0.93, 0.94], ok=[True, True], cost=[100, 900]))
    assert pick_within_noise(front, "recall", "lo", "hi", "ok", "cost") == 0
    assert pick_within_noise(front.assign(ok=False), "recall", "lo", "hi", "ok", "cost") is None  # no fallback to failing rows


def test_settings_resolve_paths_from_any_working_folder(monkeypatch):
    root = load_settings().root
    monkeypatch.chdir(root / "notebooks")
    assert load_settings().data.bronze_dir == root / "data" / "medallion" / "bronze"


def test_a_comparison_told_its_threshold_passes_and_fails_the_pairs_the_full_score_does():
    import random
    import pyarrow as pa
    from er.strings import FUNCTIONS, udf
    rnd = random.Random(0)
    letters = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホ東京大阪市区町村一二三丁目番地号ビル0123456789"
    word = lambda: "".join(rnd.choice(letters) for _ in range(rnd.choice([0, 1, 2, 3, 4, 6, 12, 40, 150, 300])))
    base = [word() for _ in range(4000)]
    a = pa.array(base + base[:2000])
    b = pa.array([word() for _ in range(4000)] + [x[:-1] + rnd.choice(letters) if x else x for x in base[:2000]])  # unrelated, and one edit apart
    for function, thresholds in {"jaro_winkler": [0.95, 0.9, 0.8, 0.75, 0, 1, 1.5], "jaro": [0.9], "levenshtein": [1, 2, 1.5, 0, -1],
                                 "damerau_levenshtein": [1, 2], "hamming": [1]}.items():  # past the ends: every pair passes, or none, as before
        full = np.asarray(udf(function)(a, b))
        for t in thresholds:  # 0.8 included: a full score just under it is stored as float32 at it, and passes
            cut = np.asarray(udf(function, cut=True)(a, b, pa.array([float(t)] * len(a))))
            passes = (lambda x: x >= t) if FUNCTIONS[function].similarity else (lambda x: x <= t)
            assert (passes(full) == passes(cut)).all() and (full[passes(full)] == cut[passes(full)]).all(), (function, t)


def test_a_comparison_asked_of_duckdb_first_passes_the_pairs_the_python_function_does():
    import random
    from er.config import Comparator
    from er.standardize import normalize
    from er.strings import connect, spent
    rnd = random.Random(1)
    kata, roman, digits, kanji = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンガギグゲゴヴァィゥェォャュョッー・", "ABCDEFGHIJKLMNOPQRSTUVWXYZ abc", "0123456789", "東京大阪市区町村一二三丁目番地号"
    word = lambda letters: "".join(rnd.choice(letters) for _ in range(rnd.choice([1, 2, 3, 4, 6, 8, 12, 40, 90])))
    def near(x: str) -> str:  # one edit away: a substitution, a swap of two, an insertion or a deletion
        i = rnd.randrange(len(x))
        return rnd.choice([x[:i] + rnd.choice(x) + x[i + 1:], x[:i] + x[i + 1:i + 2] + x[i:i + 1] + x[i + 2:], x[:i] + rnd.choice(x) + x[i:], x[:i] + x[i + 1:] or x])
    left, right = [], []
    for letters in (kata, roman, digits, kanji, kata + roman, kata + kanji):
        for _ in range(1500):
            x = word(letters)
            left.append(x); right.append(rnd.choice([word(letters), near(x), near(near(x)), x, word(kata), word(digits), None]))
    left += [None, "アイ", "", "ア"]; right += ["アイ", None, "ア", ""]
    con, _ = connect()
    df = pd.DataFrame({"x_l": left, "x_r": right}, dtype="string")  # '' kept: records not prepared by er.standardize may hold it
    for side in ("l", "r"):
        df[f"x__one_byte_{side}"] = normalize(df[f"x_{side}"], ("one_byte",), None)
        df[f"x__one_byte_hash_{side}"] = normalize(df[f"x_{side}"], ("one_byte_hash",), None).where(df.index % 5 > 0)  # a record prepared without it: the bytes' bound
    copies = df["x__one_byte_l"].dropna()
    assert len(copies) > 1500 and (copies.str.len() == copies.map(lambda v: len(v.encode("utf-8")))).all()  # one byte each
    con.register("er_pairs", df.assign(i=range(len(df))))
    con.execute("CREATE TABLE pairs AS SELECT * FROM er_pairs")
    for function, thresholds in {"jaro_winkler": [0.95, 0.9, 0.8, 0.75, 0, 1, 1.5], "jaro": [0.9, 0.7], "hamming": [1, 0, 2],
                                 "damerau_levenshtein": [1, 2], "levenshtein": [1, 2]}.items():
        for t in thresholds:
            comp = Comparator(function=function, threshold=t)
            plain = f'coalesce(cl_{function}_cut("x_l", "x_r", {t}) {">=" if function.startswith("jaro") else "<="} {t}, FALSE)'
            before = spent().get(function, (0, 0))[1]
            fast, slow = con.execute(f"SELECT list(coalesce({comp.sql('x', level=True)}, FALSE) ORDER BY i), list({plain} ORDER BY i) FROM pairs").fetchall()[0]
            assert fast == slow, (function, t, [(df.x_l[i], df.x_r[i]) for i, (p, q) in enumerate(zip(fast, slow)) if p != q][:3])
            settled = con.execute(f"SELECT list({comp.sql('x', level=True, settled=True)} ORDER BY i) FROM pairs").fetchall()[0][0]
            assert all(s is None or s == f for s, f in zip(settled, fast)), (function, t)  # what DuckDB settles is the test's answer
            assert function in ("damerau_levenshtein", "levenshtein") or sum(s is not None for s in settled) > len(df) / 2, (function, t)
            assert function == "jaro" or spent()[function][1] - before < 1.5 * len(df), (function, t)  # the plain query's, and few of its: most pairs never reach Python
    rule = Comparator(function="jaro_winkler", threshold=0.8).sql("x")  # a rule's form: equal values pass too
    assert "jaro_winkler_similarity" in rule and rule.startswith('(l."x" = r."x" OR')


def test_an_em_step_that_finds_no_likely_match_at_a_level_leaves_it_unestimated_instead_of_stopping():
    import splink.comparison_library as cl
    from er.match import _populate, _unseen_when_zero
    level = next(lv for lv in cl.ExactMatch("name").get_comparison("duckdb").comparison_levels if lv.comparison_vector_value == 1)
    zero = lambda: {"name": {1: {"m_probability": 0.0, "u_probability": 0.1}}}  # one record copied many times outweighs the rest
    with pytest.raises(ValueError, match="m_probability value 0.0"):
        _populate(set(), level, "name", zero())  # Splink's own step: the run stops
    _unseen_when_zero(set(), level, "name", zero())
    assert not level._m_is_trained  # saved without m: train_fs gives it m = u, 0 bits, and lists it as unestimated
    _unseen_when_zero(set(), level, "name", {"name": {1: {"m_probability": 0.25, "u_probability": 0.1}}})
    assert level.m_probability == 0.25  # an m it can hold is taken as found
    _unseen_when_zero(set(), level, "name", {"name": {1: {"m_probability": float("nan"), "u_probability": 0.1}}})
    assert not level._m_is_trained  # no match at all in the comparison (0 / 0): Splink would take it, and every weight be NaN


def test_a_floor_leaves_out_exactly_the_pairs_below_it_and_scores_the_rest_to_the_last_bit(tmp_path, population):
    from er.match import bound_tests
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    uid, con, db = s.data.unique_id, run.con, run.db
    l, r = f"{uid}_l", f"{uid}_r"
    con.execute(f"""CREATE OR REPLACE TABLE er_all AS SELECT a.{uid} AS {l}, b.{uid} AS {r} FROM (SELECT {uid} FROM records LIMIT 300) a
        JOIN (SELECT {uid} FROM records LIMIT 300) b ON a.{uid} < b.{uid}""")  # every pair of 300 records: almost all below 0
    every = score_fs(run.scoring, "records", "er_all", db, uid).set_index([l, r]).sort_index()
    bound = bound_tests(p.fs.model)
    assert None in bound.values() and any(bound.values())  # some at their own level, the costly ones bounded by what DuckDB settles
    for floor in (0.0, p.fs.min_match_weight):
        kept = score_fs(run.scoring, "records", "er_all", db, uid, floor=floor, bound=bound).set_index([l, r]).sort_index()
        pd.testing.assert_frame_equal(kept, every.loc[kept.index])  # each scored to the last bit
        assert every.index[every["match_weight"] >= floor].isin(kept.index).all()  # none at the floor or above left out
        left = every.drop(kept.index)
        assert len(left) and (left["match_weight"] < floor).all()  # and every one left out below it
    con.execute("CREATE OR REPLACE TABLE er_some AS SELECT * FROM er_all LIMIT 7")
    held = score_fs(run.scoring, "records", "er_all", db, uid, floor=1e9, bound=bound, exempt="er_some")
    assert len(held) == 7  # nothing reaches that floor: only the exempt pairs are scored


def test_pairs_that_cant_reach_0_left_out_as_the_keys_list_them_change_no_score_no_customer_no_gate_and_no_count(tmp_path, population, monkeypatch):
    from dataclasses import replace
    from er import candidates as C
    from er.run import Run
    s, p0, g = population
    p = replace(p0, fs=replace(p0.fs, budget=replace(p0.fs.budget, sample_pairs=0)))  # a block of 2 records oversized: the gate decides hundreds
    monkeypatch.setattr("er.run.review_floor", lambda pipeline: -50.0)  # and keeps many, pairs below 0 its hits
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    monkeypatch.setattr(C, "KEEP_SLICE", 7)  # many slices
    monkeypatch.setattr("er.run.idle", lambda run: (run.pipeline.fs.blockers, []))  # every key runs: the pairs each lists are compared
    gate, budget, seen = C._gate, Run.budget, []

    def spy(blockers, r, big, parts, *args):  # the distinct pairs the normal blocks list, as the gate counts them
        seen.append(r.con.execute(f"SELECT count(*) FROM (SELECT DISTINCT l, r FROM ({' UNION ALL '.join(parts)}))").fetchall()[0][0])
        return gate(blockers, r, big, parts, *args)
    monkeypatch.setattr(C, "_gate", spy)
    Run(p, s, reaching_only=False).full(tmp_path / "in.parquet", tmp_path / "first")
    monkeypatch.setattr(C, "_gate", gate)
    monkeypatch.setattr(Run, "budget", lambda self, stop=True: budget(self, stop=False))  # the budget's own stop is not what this tests
    monkeypatch.setattr(Run, "capacity", lambda self: seen[0] + 3)  # tight: the gate keeps blocks while they fit, and skips the rest
    every = Run(p, s, reaching_only=False).full(tmp_path / "in.parquet", tmp_path / "every")  # every pair the keys list stored, as before
    kept = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "kept")
    read = lambda run, what: run.con.sql(what).df().sort_values(list(run.con.sql(what).columns)).reset_index(drop=True)
    assert kept._count("cands") < every._count("cands")  # fewer stored
    for what in ("SELECT * FROM scores WHERE match_weight >= 0", f"SELECT * FROM ({kept.scored()}) WHERE match_weight >= 0", "SELECT * FROM gold"):
        pd.testing.assert_frame_equal(read(kept, what), read(every, what))  # to the last bit
    gated = lambda run: run.gated.drop(columns=["best"]).sort_values(["generator", "value"]).reset_index(drop=True)
    assert set(every.gated["decision"]) >= {"kept", "skipped: over capacity"}  # the capacity binds
    pd.testing.assert_frame_equal(gated(kept), gated(every))  # every block sampled, scored and decided alike
    facts = lambda run, step: next(x for x in run.steps if x["step"] == step)
    for step, keys in (("candidates", ("candidates", "oversized_kept", "gate_pairs")), ("score", ("unscored", "bands"))):
        assert {k: facts(kept, step)[k] for k in keys} == {k: facts(every, step)[k] for k in keys}  # the counts people read
    pairs = lambda run: {x["name"]: x["pairs"] for x in facts(run, "candidates")["generators"]}
    assert pairs(kept) == pairs(every)  # each key's pairs, as listed


def test_a_bound_settles_a_level_only_where_the_scored_model_wrote_it_as_the_method_does(population):
    import copy
    from er.match import bound_sql, bound_tests, fs_settings
    s, p, g = population
    settings = fs_settings(p.fs.model, "uid").create_settings_dict("duckdb")
    for c in settings["comparisons"]:
        for lv in c["comparison_levels"]:
            lv.update(m_probability=0.5, u_probability=0.1)
    settings["probability_two_random_records_match"] = 1e-6
    tests = bound_tests(p.fs.model)
    costly = next(c for c in settings["comparisons"] if tests[c["output_column_name"]])
    other = copy.deepcopy(settings)  # a model fitted under another method: its first costly level is another test
    level = next(lv for lv in next(c for c in other["comparisons"] if c["output_column_name"] == costly["output_column_name"])["comparison_levels"]
                 if not lv.get("is_null_level"))
    level["sql_condition"] += " AND TRUE"
    settled = lambda x: bound_sql(x, tests).count("coalesce((")  # a comparison's unsettled outcomes, one per level that may be NULL
    assert settled(settings) > settled(other)  # that comparison at its best level; the others settled as before


def test_chunks_cleaned_ahead_stop_at_the_first_error_instead_of_cleaning_the_rest():
    import concurrent.futures
    import threading
    import time
    from er.run import ahead
    done, lock = [], threading.Lock()

    def clean(i):
        time.sleep(0.01)
        if i == 2:
            raise ValueError("bad chunk")
        with lock:
            done.append(i)
        return i
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        got = []
        with pytest.raises(ValueError, match="bad chunk"):
            for x in ahead(pool, clean, range(100), 3):
                got.append(x)
    assert got == [0, 1] and len(done) < 10  # in order, and the chunks queued after the error never cleaned


def test_em_s_m_is_held_within_what_its_evidence_can_say():
    import math
    from er.config import Comparator, Comparison, FSModel, Level
    from er.match import sensible_m
    level = lambda label, f, t=None: Level(label=label, any_of=(("x", Comparator(f, t)),))
    comps = (Comparison(name="phone", null_if_missing=("x",), levels=(level("exact", "exact"), level("one digit off", "hamming", 1))),
             Comparison(name="cif", null_if_missing=("x",), levels=(level("exact", "exact"), level("one digit off", "damerau_levenshtein", 1))))
    model = FSModel(name="t", comparisons=comps, prior_rules=(), prior_recall=0.5, u_max_pairs=1e4, m_method="em", em_rules=(), seed=0)
    lv = lambda label, m, u: {"label_for_charts": label, "m_probability": m, "u_probability": u}
    js = {"comparisons": [
        {"output_column_name": "phone", "comparison_levels": [{"is_null_level": True}, lv("exact", 0.9, 1e-4), lv("one digit off", 1e-12, 1e-3), lv("else", 0.1, 0.999)]},
        {"output_column_name": "cif", "comparison_levels": [{"is_null_level": True}, lv("exact", 1e-6, 1e-6), lv("one digit off", 0.1, 1e-5), lv("else", 0.9, 1.0)]}]}
    changed = sensible_m(model, js, {("cif", "exact")})  # cif's exact level never reached by a match in training
    bits = {(c["output_column_name"], x["label_for_charts"]): math.log2(x["m_probability"] / x["u_probability"])
            for c in js["comparisons"] for x in c["comparison_levels"] if not x.get("is_null_level")}
    assert bits["phone", "one digit off"] == pytest.approx(bits["phone", "else"])  # a typo no more evidence against than no agreement
    assert bits["phone", "exact"] > 13  # what EM learned from agreement stands
    assert bits["cif", "one digit off"] == pytest.approx(0, abs=1e-9)  # neighbouring IDs, not a typo of a shared one
    assert {(c, lv) for c, lv, *_ in changed} == {("phone", "one digit off"), ("cif", "one digit off")}


def test_one_name_in_a_person_field_and_the_company_field_is_compared_on_its_kind_s_side_only():
    from er.config import load_pipeline
    from er.kind import classifier
    from er.settings import load_settings
    from er.standardize import prepare
    s = load_settings()
    p = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    records = pd.DataFrame({"CONT_ID": ["1", "2", "3"], "FULL_NAME_KANA": ["ヤマダタロウ", None, "スズキハナコ"], "O_PERSON_NAME_KANA": [None] * 3,
                            "LAST_NAME_KANA": [None] * 3, "GIVEN_NAME_KANA": [None] * 3,
                            "NYS_CNV_P_NAME_KANA": ["ﾔﾏﾀﾞﾀﾛｳ", "ｶﾌﾞｼｷｶﾞｲｼｬﾔﾏﾀﾞｼｮｳｼﾞ", "ﾀﾅｶｼｮｳｼﾞ"]}, dtype="string")
    df = prepare(s.standardize, records, [], {"full_name", "person_name", "company_name"}, kind=classifier(s, p.kind))
    assert df.loc[0, "full_name"] == "ヤマダタロウ" and pd.isna(df.loc[0, "company_name"])  # a person's name in both: the person side only
    assert df.loc[1, "company_name"].endswith("ヤマダショウジ")  # a company keeps its name
    assert df.loc[2, "full_name"] == "スズキハナコ" and df.loc[2, "company_name"] == "タナカショウジ"  # two different names: both kept
