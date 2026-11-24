"""Shared settings from config/settings.toml: paths, datasets, the fields a file's columns hold, and the language-specific
normalization, validated on load. ER_SETTINGS may name another settings file, inside the project or anywhere."""
import os
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

from er.config import COPIES, Data, Derived, InputError, Normalizer, Pipeline, Standardization, check_fields, checked, legal_pattern, only, restrict, sources_text, toml_of
from er.intake import InputSpec

SPECIAL = ("id",)  # a single column, used under its own name: the record id
TRUTH = "entity"  # [columns] entity: the truth's column, in labels/ only (scripts/benchmark.py); no field


@dataclass(frozen=True)
class Settings:
    root: Path                                # project root; every path below is resolved against it
    paths: dict[str, Path]
    data: Data
    standardize: Standardization              # its `derived` builds every field (but id) under its name
    columns: dict[str, tuple[tuple[str, ...], ...]]  # field → its sources: alternatives, each concatenated
    chains: dict[str, tuple[Normalizer, ...]]  # named normalization chains, for config/pipeline.toml
    compute: dict[str, str]                  # DuckDB settings: threads, memory_limit, temp_directory
    detect: dict[str, str]                   # field → what its values look like ([locale.detect]): suggestions only
    flag_company: tuple[str, ...] = ()       # the values of field kind_flag that say company ([kind])
    input: InputSpec = InputSpec()           # how a records file is read, before anything else ([input], er.intake)


def project_root(start: Path | None = None) -> Path:
    """The nearest folder at or above `start` that holds pyproject.toml; without `start`, the project this package is
    part of, wherever the command runs from."""
    here = (start or Path(__file__).parent).resolve()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError(f"no pyproject.toml at or above {here}")


def field(name: str, spec: object, where: Path | str = "config/settings.toml") -> Derived:
    """One [columns] entry: a column, a list of fallback column lists, or {sources, normalize, kind}."""
    sources, normalize = (spec["sources"], spec.get("normalize", ())) if isinstance(spec, dict) else (spec, ())
    sources = ((sources,),) if isinstance(sources, str) else tuple(tuple(alt) for alt in sources)
    checked(all(alt and all(c.strip() for c in alt) for alt in sources), f"[columns] {name}: an alternative with no column", where)  # a stray + or comma: refused, never a field turned off  # no alternative at all: the field has no column, as in a file without it
    kind = spec.get("kind") if isinstance(spec, dict) else None
    checked(kind in (None, "person", "company"), f"[columns] {name}: kind is person or company", where)
    return Derived(name=name, sources=sources, normalize=tuple(normalize), kind=kind)


def shared_name(s: "Settings", column: str) -> "Settings":
    """The settings for a file whose one column holds every name, a person's or a company's: the name fields all read
    it, and full_name, person_name and company_name keep it only on records that lean their kind (er.kind)."""
    kinds = {**NAME_KINDS, "any_name": None}
    derived = tuple(replace(d, sources=((column,),), kind=kinds[d.name]) if d.name in kinds else d for d in s.standardize.derived)
    columns = {f: (((column,),) if f in kinds else src) for f, src in s.columns.items()}
    return replace(s, standardize=replace(s.standardize, derived=derived), columns=columns)


NAME_KINDS = {"full_name": "person", "person_name": "person", "company_name": "company"}  # the name fields a record's kind routes (er.kind)


def settings_path() -> Path:  # the settings file a run reads
    return Path(os.environ.get("ER_SETTINGS") or project_root() / "config" / "settings.toml")


def norm_name(column: str) -> str:  # a column's name as people mean it: width, case and separators aside
    return re.sub(r"[\s_\-・.]+", "", unicodedata.normalize("NFKC", column).casefold())


def load_settings(path: Path | None = None) -> Settings:
    """The settings file at `path` (settings_path()). Its paths are the project's it is in, or, outside any (a private
    mapping kept out of the repository), this package's."""
    path = Path(path or settings_path())
    try:
        root = project_root(path.parent)
    except FileNotFoundError:
        root = project_root()
    cfg = toml_of(path)
    paths, sets = {name: root / rel for name, rel in cfg.get("paths", {}).items()}, cfg.get("datasets", {})  # the design kit's: a job needs neither
    steps = set(get_args(Normalizer)) - set(COPIES)  # the comparisons' own copy (er.config.Comparator.copy): not a key's

    loc = cfg["locale"]
    checked(len(loc["kana_fold_from"]) == len(loc["kana_fold_to"]), "kana_fold_from / kana_fold_to must align character by character", path)
    chains = {name: tuple(c) for name, c in loc.get("chains", {}).items()}
    unknown = {s for c in chains.values() for s in c} - steps
    checked(not unknown, f"[locale.chains]: unknown normalizers {unknown}", path)

    cols = cfg["columns"]
    for name in SPECIAL:
        checked(isinstance(cols.get(name), str), f"[columns] {name} must name one column", path)
    checked(isinstance(cols.get(TRUTH, ""), str), f"[columns] {TRUTH} must name one column", path)
    fields = {name: field(name, spec, path) for name, spec in cols.items() if name not in (*SPECIAL, TRUTH)}
    unknown = {s for d in fields.values() for s in d.normalize} - steps
    checked(not unknown, f"[columns]: unknown normalizers {unknown}", path)
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
        data=Data(unique_id=cols["id"], bronze_dir=paths.get("bronze"), labels_dir=paths.get("labels"), datasets=tuple(sets.get("all", ())),
                  entity_id=cols.get(TRUTH), household_id=sets.get("household")),
        standardize=std,
        columns={**{name: ((cols[name],),) for name in SPECIAL}, **{name: d.sources for name, d in fields.items()}},
        chains=chains,
        compute={k: str(v) for k, v in cfg.get("compute", {}).items()},
        detect={**loc.get("detect", {}), "company_name": legal_pattern(std)},  # a company name holds a legal form: the run's own table
        flag_company=tuple(str(v) for v in cfg.get("kind", {}).get("flag_company", ())),
        input=input_spec(cfg.get("input", {})),
    )


def input_spec(cfg: dict) -> InputSpec:  # [input]: the placeholders read as missing
    only("[input]", cfg, InputSpec.__dataclass_fields__)
    return InputSpec(**{k: tuple(map(str, v)) if isinstance(v, list) else v for k, v in cfg.items()})


def present_fields(s: Settings, file_columns: Iterable[str]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """The fields a file holds: for each, the source alternatives whose columns are all in the file."""
    cols = set(file_columns)
    return {name: alts for name, sources in s.columns.items() if (alts := tuple(a for a in sources if set(a) <= cols))}


def counted_once(p: Pipeline, present: dict[str, tuple]) -> None:
    """Refuses two compared fields that read the same columns (`present`: each field's sources): one value counted
    twice, its weight inflated. The name fields share a column by design."""
    seen: dict[tuple, str] = {}
    for f in sorted({col for c in p.fs.model.comparisons for lv in c.levels for col, _ in lv.any_of if "name" not in col} & set(present)):
        if (other := seen.setdefault(present[f], f)) != f:
            raise InputError(f"{other} and {f} both read {sources_text(present[f])}: the model would count one value twice",
                             fix=f"map each to a column of its own in config/settings.toml [columns] ({f} = …), or leave one unmapped")


def fit_to_file(p: Pipeline, s: Settings, file_columns: Iterable[str]) -> tuple[Pipeline, list[str]]:
    """The pipeline for one file: stops if a mandatory field (or every field of a one_of group) is absent; derives each
    field only from the sources the file has; disables whatever reads an absent optional field, and lists it."""
    present = present_fields(s, file_columns)
    check_fields(p.fields, set(present), s.columns)
    counted_once(p, present)
    std = replace(s.standardize, derived=tuple(replace(d, sources=present[d.name]) for d in s.standardize.derived if d.name in present))
    return restrict(replace(p, fs=replace(p.fs, standardize=std)), set(present))
