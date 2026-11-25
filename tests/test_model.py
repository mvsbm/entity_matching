"""Stage 2, fit (nayose/sql/functions.sql, fit.sql, nayose/em.py): the model nayose learns from the tests' population is
the one recorded: λ, each level's m and u as fitted on the sample and measured again on the file, and the notes, on
the tests' population whole and with the sample cut from it (their digest, to 12 significant digits, in
tests/fixtures/expected.json; NAYOSE_PARITY_WRITE=1 writes it again)."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import nayose
from nayose.engines import DuckDB

EXPECTED = Path(__file__).parent / "fixtures" / "expected.json"


def rounded(x):  # a float to 12 significant digits, in lists and dicts too: a last bit libm may move doesn't count
    return float(f"{x:.12g}") if isinstance(x, float) else [rounded(v) for v in x] if isinstance(x, (list, tuple)) else {k: rounded(v) for k, v in x.items()} if isinstance(x, dict) else x


@pytest.mark.parametrize("sizes", [{}, {"fit_rows": 300, "fit_u_max_pairs": 2000, "u_max_pairs": 5000}], ids=["whole", "sampled"])
def test_the_model_is_as_recorded(tmp_path, population, monkeypatch, sizes):
    g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    c = copy.deepcopy(nayose.config())
    c["fit"].update(sizes)  # a sample cut from the file, and u sampled on both: the hash's draw
    monkeypatch.setattr(nayose, "config", lambda: c)
    engine = DuckDB()
    nayose.records(engine, [tmp_path / "in.parquet"])
    nayose.fit(engine)
    notes = json.loads(engine.value("SELECT notes FROM fit"))
    got = rounded(dict(levels=[list(r) for r in engine.rows("SELECT comparison, label, m, u, file_m, file_u FROM model ORDER BY comparison, gamma")],
                       fit=list(engine.rows("SELECT probability, fit_rows FROM fit")[0]),
                       notes={k: notes[k] for k in ("filled", "skipped", "adjusted", "em_pairs", "file_adjusted")}))
    key, said = f"model_{'sampled' if sizes else 'whole'}", hashlib.sha256(json.dumps(got, sort_keys=True).encode()).hexdigest()[:16]
    if os.environ.get("NAYOSE_PARITY_WRITE"):
        EXPECTED.write_text(json.dumps({**json.loads(EXPECTED.read_text(encoding="utf-8")), key: said}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert said == json.loads(EXPECTED.read_text(encoding="utf-8"))[key]


@pytest.mark.parametrize("module", ["em.py", "entities.py"])
def test_each_python_udf_is_a_python_3_11_module_of_the_standard_library_alone(module):  # BigQuery's: 3.11, no packages
    import ast
    import sys
    tree = ast.parse((nayose.HERE / module).read_text(encoding="utf-8"), feature_version=(3, 11))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in getattr(n, "names", [])}
    assert imported <= sys.stdlib_module_names, imported - sys.stdlib_module_names
