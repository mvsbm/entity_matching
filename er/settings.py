"""Shared settings from config/settings.toml: paths, datasets, the fields a file's columns hold, and the language-specific
normalization, validated on load. ER_SETTINGS may name another settings file. A workspace's own columns.toml
([columns] and [kind]), if it keeps one, replaces the project's."""
import importlib.util
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

from er.config import COPIES, Data, Derived, InputError, Normalizer, Pipeline, Standardization, check_fields, checked, legal_pattern, restrict, sources_text, toml_of
from er.intake import InputSpec

SPECIAL = ("id", "entity")  # single columns, used under their own names: the record id and the truth
COLUMNS = "columns.toml"  # a workspace's own [columns] and [kind]: which of its files' columns hold each field


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


def columns_file(workspace: str | Path | None) -> Path | None:  # a workspace's own mapping, if it keeps one
    f = Path(workspace) / COLUMNS if workspace else None
    return f if f and f.is_file() else None


# ---------- a workspace's features: groups › features › parts, each with its columns, compiled into [columns] ----------
# The structure is read back from the mapping (features_from), so the two can't disagree.


ADDED = {"person name": ("person_name", "given_name"), "company name": ("company_name",)}  # an added feature's fields stand beside these


def given_field(field: str) -> str:  # an added person's name's given name: person_name_2 → given_name_2
    return "given_name" + field.removeprefix("person_name")


def added_of(workspace: str | Path | None) -> dict[str, dict]:  # the features added in a workspace: columns.toml's [features]
    f = columns_file(workspace)
    return toml_of(f).get("features", {}) if f else {}


def beside(added: Mapping[str, dict]) -> list[tuple[str, str]]:
    """Each added field, and the field it stands beside (config.widen): a person's name and its given name beside
    person_name and given_name, a company name beside company_name."""
    return [pair for field, x in added.items() for pair in
            ([(field, "person_name"), (given_field(field), "given_name")] if x["type"] == "person name" else [(field, ADDED[x["type"]][0])])]


SAYS = {"full": "are a known family name and given name", "family": "are known family names", "given": "are known given names",
        "address": "start with a known prefecture or city"}


def norm_name(column: str) -> str:  # a column's name as people mean it: width, case and separators aside
    return re.sub(r"[\s_\-・.]+", "", unicodedata.normalize("NFKC", column).casefold())


def load_settings(path: Path | None = None, columns: Path | None = None) -> Settings:
    """The settings file at `path` (settings_path()); with `columns`, a workspace's columns.toml, whose [columns] and
    [kind] replace the file's."""
    path = Path(path or settings_path())
    root = project_root(path.parent)
    cfg = toml_of(path)
    if columns:
        own = toml_of(columns)
        cfg = {**cfg, "columns": own["columns"], "kind": own.get("kind", {})}
    paths = {name: root / rel for name, rel in cfg["paths"].items()}
    steps = set(get_args(Normalizer)) - set(COPIES)  # the comparisons' own copy (er.config.Comparator.copy): not a key's

    loc = cfg["locale"]
    checked(len(loc["kana_fold_from"]) == len(loc["kana_fold_to"]), "kana_fold_from / kana_fold_to must align character by character", path)
    chains = {name: tuple(c) for name, c in loc.get("chains", {}).items()}
    unknown = {s for c in chains.values() for s in c} - steps
    checked(not unknown, f"[locale.chains]: unknown normalizers {unknown}", path)

    cols = cfg["columns"]
    for name in SPECIAL:
        checked(isinstance(cols.get(name), str), f"[columns] {name} must name one column", columns or path)
    fields = {name: field(name, spec, columns or path) for name, spec in cols.items() if name not in SPECIAL}
    unknown = {s for d in fields.values() for s in d.normalize} - steps
    checked(not unknown, f"[columns]: unknown normalizers {unknown}", columns or path)
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
                  datasets=tuple(cfg["datasets"]["all"]), unique_id=cols["id"], entity_id=cols["entity"], household_id=cfg["datasets"].get("household"),
                  synthetic=bool(cfg["datasets"]["synthetic"])),
        standardize=std,
        columns={**{name: ((cols[name],),) for name in SPECIAL}, **{name: d.sources for name, d in fields.items()}},
        chains=chains,
        compute={k: str(v) for k, v in cfg.get("compute", {}).items()},
        detect={**loc.get("detect", {}), "company_name": legal_pattern(std)},  # a company name holds a legal form: the run's own table
        flag_company=tuple(str(v) for v in cfg.get("kind", {}).get("flag_company", ())),
        input=input_spec(cfg.get("input", {})),
    )


def input_spec(cfg: dict) -> InputSpec:  # [input]: the encodings tried, the placeholders, how sure a proposed repair must be
    unknown = set(cfg) - set(InputSpec.__dataclass_fields__)
    checked(not unknown, f"[input]: unknown keys {sorted(unknown)}")
    return InputSpec(**{k: tuple(map(str, v)) if isinstance(v, list) else v for k, v in cfg.items()})


def load_experiments(root: Path):  # config/experiments.py: the development variants, as a module
    spec = importlib.util.spec_from_file_location("experiments", root / "config" / "experiments.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def fit_to_file(p: Pipeline, s: Settings, file_columns: Iterable[str], labelled: bool = False) -> tuple[Pipeline, list[str]]:
    """The pipeline for one file: stops if a mandatory field (or every field of a one_of group) is absent; derives each
    field only from the sources the file has; disables whatever reads an absent optional field, and lists it."""
    present = present_fields(s, file_columns)
    check_fields(p.fields, set(present), s.columns, labelled)
    counted_once(p, present)
    std = replace(s.standardize, derived=tuple(replace(d, sources=present[d.name]) for d in s.standardize.derived if d.name in present))
    return restrict(replace(p, rules=replace(p.rules, standardize=std), fs=replace(p.fs, standardize=std)), set(present))
