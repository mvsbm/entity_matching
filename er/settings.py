"""Shared settings from config/settings.toml: paths, datasets, the fields a file's columns hold, and the language-specific
normalization, validated on load. ER_SETTINGS may name another settings file. set_columns rewrites [columns] lines."""
import importlib.util
import json
import os
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

from er.config import Data, Derived, InputError, Normalizer, Pipeline, Standardization, check_fields, legal_pattern, restrict

SPECIAL = ("id", "entity")  # single columns, used under their own names: the record id and the truth


@dataclass(frozen=True)
class Settings:
    root: Path                                # project root; every path below is resolved against it
    paths: dict[str, Path]
    data: Data
    standardize: Standardization              # its `derived` builds every field (except id / entity) under its name
    columns: dict[str, tuple[tuple[str, ...], ...]]  # field → its sources: alternatives, each concatenated
    chains: dict[str, tuple[Normalizer, ...]]  # named normalization chains, for config/pipeline.toml
    compute: dict[str, str]                  # DuckDB settings: threads, memory_limit, temp_directory
    detect: dict[str, str]                   # field → what its values look like ([locale.detect]): suggestions only
    flag_company: tuple[str, ...] = ()       # the values of field kind_flag that say company ([kind])


def project_root(start: Path | None = None) -> Path:
    """The nearest folder at or above `start` that holds pyproject.toml; without `start`, the project this package is
    part of, wherever the command runs from."""
    here = (start or Path(__file__).parent).resolve()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError(f"no pyproject.toml at or above {here}")


def field(name: str, spec: object) -> Derived:
    """One [columns] entry: a column, a list of fallback column lists, or {sources, normalize, kind}."""
    sources, normalize = (spec["sources"], spec.get("normalize", ())) if isinstance(spec, dict) else (spec, ())
    sources = ((sources,),) if isinstance(sources, str) else tuple(tuple(alt) for alt in sources)
    assert sources and all(sources), f"[columns] {name}: no source column"
    kind = spec.get("kind") if isinstance(spec, dict) else None
    assert kind in (None, "person", "company"), f"[columns] {name}: kind is person or company"
    return Derived(name=name, sources=sources, normalize=tuple(normalize), kind=kind)


def shared_name(s: "Settings", column: str) -> "Settings":
    """The settings for a file whose one column holds every name, a person's or a company's: the name fields all read
    it, and full_name, person_name and company_name keep it only on records that lean their kind (er.kind)."""
    kinds = {"full_name": "person", "person_name": "person", "company_name": "company", "any_name": None}
    derived = tuple(replace(d, sources=((column,),), kind=kinds[d.name]) if d.name in kinds else d for d in s.standardize.derived)
    columns = {f: (((column,),) if f in kinds else src) for f, src in s.columns.items()}
    return replace(s, standardize=replace(s.standardize, derived=derived), columns=columns)


def settings_path() -> Path:  # the settings file a run reads
    return Path(os.environ.get("ER_SETTINGS") or project_root() / "config" / "settings.toml")


def set_columns(path: Path, mapping: dict[str, tuple[tuple[str, ...], ...]]) -> None:
    """Rewrite the [columns] lines of the fields in `mapping` in the settings file at `path`: each field's source
    alternatives, tried in order, each one column or several joined (empty: the field goes). Every other line, each
    line's comment, and a field's options (normalize, kind) stay. The new text is loaded and validated before it
    replaces the old. O(the file)."""
    text = path.read_text(encoding="utf-8")
    lines, current = text.splitlines(keepends=True), tomllib.loads(text)["columns"]
    start = next(i for i, x in enumerate(lines) if x.strip() == "[columns]")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    toml = lambda v: json.dumps(v, ensure_ascii=False)  # a string or a list of strings: the same in TOML
    for name, sources in mapping.items():
        at = next((i for i in range(start + 1, end) if re.match(rf"{re.escape(name)}\s*=", lines[i])), None)
        if not sources:
            if at is not None:
                del lines[at]
                end -= 1
            continue
        old, alts = current.get(name), [list(a) for a in sources]
        value = (f"{{ {', '.join(f'{k} = {toml(v)}' for k, v in {**old, 'sources': alts}.items())} }}" if isinstance(old, dict)
                 else toml(alts[0][0]) if alts == [alts[0][:1]] else toml(alts))
        comment = re.search(r'^[^"#]*(?:"[^"]*"[^"#]*)*\s(#.*)$', lines[at].rstrip("\n")) if at is not None else None
        line = f"{name} = {value}"
        line += (" " * max(1, comment.start(1) - len(line)) + comment.group(1) if comment else "") + "\n"  # the comment in its column
        if at is None:  # a new field: after the section's last one
            at = max(i for i in range(start, end) if re.match(r"\w+\s*=", lines[i])) + 1
            lines.insert(at, line)
            end += 1
        else:
            lines[at] = line
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    try:
        load_settings(tmp)
    except Exception as e:  # what load_settings checks: say it, and keep the old file
        tmp.unlink()
        raise InputError(f"{path}: [columns] would not load: {e}", fix="give each field existing columns; id names one column") from None
    os.replace(tmp, path)


def load_settings(path: Path | None = None) -> Settings:
    path = Path(path or settings_path())
    root = project_root(path.parent)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    paths = {name: root / rel for name, rel in cfg["paths"].items()}
    steps = set(get_args(Normalizer))

    loc = cfg["locale"]
    assert len(loc["kana_fold_from"]) == len(loc["kana_fold_to"]), "kana_fold_from / kana_fold_to must align character by character"
    chains = {name: tuple(c) for name, c in loc.get("chains", {}).items()}
    unknown = {s for c in chains.values() for s in c} - steps
    assert not unknown, f"[locale.chains]: unknown normalizers {unknown}"

    cols = cfg["columns"]
    for name in SPECIAL:
        assert isinstance(cols.get(name), str), f"[columns] {name} must name one column"
    fields = {name: field(name, spec) for name, spec in cols.items() if name not in SPECIAL}
    unknown = {s for d in fields.values() for s in d.normalize} - steps
    assert not unknown, f"[columns]: unknown normalizers {unknown}"
    # a field that is its own single column, unnormalized, needs no copy
    derived = tuple(d for d in fields.values() if d.sources != ((d.name,),) or d.normalize)

    std = Standardization(kana_fold=dict(zip(loc["kana_fold_from"], loc["kana_fold_to"])),
                          legal_forms=tuple(loc["legal_forms"]), legal_front=tuple(loc.get("legal_front", ())),
                          legal_end=tuple(loc.get("legal_end", ())), prefectures=tuple(loc["prefectures"]),
                          address_replacements=tuple(map(tuple, loc["address_replacements"])),
                          address_cut_at=loc["address_cut_at"], derived=derived)
    return Settings(
        root=root,
        paths=paths,
        data=Data(bronze_dir=paths["bronze"], labels_dir=paths["labels"], gold_dir=paths["gold"],
                  experiments_dir=paths["experiments"], models_dir=paths["models"],
                  datasets=tuple(cfg["datasets"]["all"]), unique_id=cols["id"], entity_id=cols["entity"],
                  synthetic=bool(cfg["datasets"]["synthetic"])),
        standardize=std,
        columns={**{name: ((cols[name],),) for name in SPECIAL}, **{name: d.sources for name, d in fields.items()}},
        chains=chains,
        compute={k: str(v) for k, v in cfg.get("compute", {}).items()},
        detect={**loc.get("detect", {}), "company_name": legal_pattern(std)},  # a company name holds a legal form: the run's own table
        flag_company=tuple(str(v) for v in cfg.get("kind", {}).get("flag_company", ())),
    )


def load_experiments(root: Path):  # config/experiments.py: the development variants, as a module
    spec = importlib.util.spec_from_file_location("experiments", root / "config" / "experiments.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def present_fields(s: Settings, file_columns: Iterable[str]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """The fields a file holds: for each, the source alternatives whose columns are all in the file."""
    cols = set(file_columns)
    return {name: alts for name, sources in s.columns.items() if (alts := tuple(a for a in sources if set(a) <= cols))}


def fit_to_file(p: Pipeline, s: Settings, file_columns: Iterable[str], labelled: bool = False) -> tuple[Pipeline, list[str]]:
    """The pipeline for one file: stops if a mandatory field (or every field of a one_of group) is absent; derives each
    field only from the sources the file has; disables whatever reads an absent optional field, and lists it."""
    present = present_fields(s, file_columns)
    check_fields(p.fields, set(present), s.columns, labelled)
    std = replace(s.standardize, derived=tuple(replace(d, sources=present[d.name]) for d in s.standardize.derived if d.name in present))
    return restrict(replace(p, rules=replace(p.rules, standardize=std), fs=replace(p.fs, standardize=std)), set(present))
