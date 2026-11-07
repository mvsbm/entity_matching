"""Shared settings from config/settings.toml: paths, datasets, the fields a file's columns hold, and the language-specific
normalization, validated on load. ER_SETTINGS may name another settings file. A workspace keeps its own mapping in its
columns.toml ([columns] and [kind]), which replaces the project's (own_columns makes it). set_columns rewrites [columns]
lines of either file."""
import importlib.util
import json
import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

from er.config import Data, Derived, InputError, Normalizer, Pipeline, Standardization, check_fields, legal_pattern, restrict

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
    assert all(sources), f"[columns] {name}: an alternative with no column"  # no alternative at all: the field has no column, as in a file without it
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


def columns_file(workspace: str | Path | None) -> Path | None:  # a workspace's own mapping, if it keeps one
    f = Path(workspace) / COLUMNS if workspace else None
    return f if f and f.is_file() else None


def own_columns(path: Path) -> str:
    """A new workspace's columns.toml: the [columns] and [kind] sections of the settings file at `path`, comments kept."""
    keep, out = False, ["# This workspace's mapping: which of its files' columns hold each field. nayose set columns --workspace changes it.\n"]
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.lstrip().startswith("["):
            keep = line.split("#")[0].strip() in ("[columns]", "[kind]")
            out += ["\n"] if keep else []
        out += [line] if keep else []
    return "".join(out)


def set_columns(path: Path, mapping: dict[str, tuple[tuple[str, ...], ...]]) -> None:
    """Rewrite the [columns] lines of the fields in `mapping` in the settings file at `path`: each field's source
    alternatives, tried in order, each one column or several joined (none: the field has no column, and whatever reads it
    is turned off, as for a file that lacks it; the field stays declared, so the pipeline still loads). Every other line, each
    line's comment, and a field's options (normalize, kind) stay. The new text is loaded and validated before it
    replaces the old. O(the file)."""
    text = path.read_text(encoding="utf-8")
    lines, current = text.splitlines(keepends=True), tomllib.loads(text)["columns"]
    start = next(i for i, x in enumerate(lines) if x.strip() == "[columns]")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    toml = lambda v: json.dumps(v, ensure_ascii=False)  # a string or a list of strings: the same in TOML
    for name, sources in mapping.items():
        at = next((i for i in range(start + 1, end) if re.match(rf"{re.escape(name)}\s*=", lines[i])), None)
        old, alts = current.get(name), [list(a) for a in sources]
        value = (f"{{ {', '.join(f'{k} = {toml(v)}' for k, v in {**old, 'sources': alts}.items())} }}" if isinstance(old, dict)
                 else toml(alts[0][0]) if alts and alts == [alts[0][:1]] else toml(alts))
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
        load_settings(tmp) if "paths" in tomllib.loads(text) else load_settings(columns=tmp)  # a workspace's file: over the project's
    except Exception as e:  # what load_settings checks: say it, and keep the old file
        tmp.unlink()
        raise InputError(f"{path}: [columns] would not load: {e}", fix="give each field existing columns; id names one column") from None
    os.replace(tmp, path)


# ---------- a workspace's features: groups › features › parts, each with its columns, compiled into [columns] ----------
# The structure is read back from the mapping (features_from), so the two can't disagree.

# The structure a workspace starts with: what people know their file holds, grouped. A slot names the field it fills, or
# for a person's name, the part it plays in the name fields (compiled).
DEFAULT_FEATURES = (
    ("ID", (dict(name="Record ID", type="id", field="id"), dict(name="Customer number", type="id", field="customer_id"))),
    ("Name", (dict(name="Full name", type="person name", script="kana", parts=(dict(name="Family name", role="family"), dict(name="Given name", role="given"))),
              dict(name="Company name", type="company name", field="company_name"),
              dict(name="Person or company", type="flag", field="kind_flag"))),
    ("Address", (dict(name="Address", type="address", field="address"), dict(name="Address code", type="code", field="address_code"),
                 dict(name="Postal code", type="postal code", field="postal_code"), dict(name="Prefecture", type="prefecture", field="prefecture"),
                 dict(name="City", type="city", field="city"), dict(name="Town code", type="code", field="town_code"))),
    ("Phone", (dict(name="Phone", type="phone", field="phone"),)),
    ("Birth date", (dict(name="Birth date", type="date", field="birth_date"),)),
)


def features_from(columns: Mapping[str, tuple[tuple[str, ...], ...]]) -> list[dict]:
    """The default structure, filled from a mapping ([columns]): each slot's columns from its field's; a person's name read
    back from person_name (its alternatives but a last, joined one: the full name; that joined one: the family name, then
    the given name) and given_name. compiled() turns it back into the same mapping. O(fields)."""
    alts = lambda f: [list(a) for a in columns.get(f, ())]
    person = alts("person_name")
    joined = person[-1] if person and len(person[-1]) > 1 else None
    part = lambda role: ([joined[:-1]] if joined else []) if role == "family" else (alts("given_name") or ([joined[-1:]] if joined else []))
    return [dict(group=group, features=[
        {**{k: v for k, v in f.items() if k != "parts"}, "columns": person[:-1] if joined else person,
         "parts": [dict(p, columns=part(p["role"])) for p in f["parts"]]} if f["type"] == "person name" else
        {**f, "columns": alts(f["field"])} for f in feats]) for group, feats in DEFAULT_FEATURES]


def compiled(features: list[dict]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """The mapping ([columns]) a structure means: each slot's columns for its field; from the person's name, full_name (its
    first column), person_name (its columns, then the family and given names joined) and given_name; any_name, every
    person and company name alternative. O(slots)."""
    out, person, company = {}, [], []
    for g in features:
        for f in g["features"]:
            if f["type"] == "person name":
                parts = {x["role"]: x["columns"] for x in f.get("parts", [])}
                family, given = parts.get("family", []), parts.get("given", [])
                person = [*f["columns"], *([family[0] + given[0]] if family and given else [])]
                out.update(full_name=f["columns"][:1], person_name=person, given_name=given)
            elif "field" in f:
                out[f["field"]] = f["columns"]
                company = f["columns"] if f["type"] == "company name" else company
    out["any_name"] = [*person, *company]
    return {k: tuple(tuple(a) for a in v) for k, v in out.items()}


def slots(features: list[dict]) -> list[tuple[str, dict]]:  # every slot with its path: group/feature, group/feature/part
    return [(f"{g['group']}/{f['name']}" + (f"/{x['name']}" if x is not f else ""), x) for g in features for f in g["features"] for x in [f, *f.get("parts", [])]]


def features_of(workspace: str | Path | None) -> list[dict]:  # a workspace's structure, read back from its mapping (else the project's)
    return features_from(load_settings(columns=columns_file(workspace)).columns)


def set_features(workspace: str | Path, values: Mapping[str, tuple[tuple[str, ...], ...]]) -> list[dict]:
    """Set slots' columns (by path: group/feature, or group/feature/part), then write the mapping they compile to into
    the workspace's columns.toml, made from the project's first; set_columns checks it loads before it replaces the old.
    O(the file)."""
    ws, feats = Path(workspace), features_of(workspace)
    if not ws.is_dir():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    found = dict(slots(feats))
    for path, alternatives in values.items():
        if path not in found:
            raise InputError(f"no feature {path}", fix="the features: " + ", ".join(found))
        found[path]["columns"] = [list(a) for a in alternatives]
    if not columns_file(ws):
        (ws / COLUMNS).write_text(own_columns(settings_path()), encoding="utf-8")
    set_columns(ws / COLUMNS, compiled(feats))
    return feats


PROFILED = {"full name": "full", "family name": "family", "given name": "given", "address": "address"}  # slot type → the profile's share
SAYS = {"full": "are a known family name and given name", "family": "are known family names", "given": "are known given names",
        "address": "start with a known prefecture or city"}


def placements(features: list[dict], profile: Mapping[str, dict], fit: Mapping[str, Mapping[str, float]], least: float = 0.5) -> list[dict]:
    """For each slot none of whose columns the file holds (profile: the file's columns), the file's column that most looks
    like it and no other slot holds, with the share and
    the evidence: a person's name and an address from the profile (er.source.profiled: known names and places, in the
    feature's script), anything else from its field's fit (its [locale.detect] pattern; an ID: filled, each value once).
    Strongest first, each column placed once, none under `least`. Suggestions only. O(slots · columns)."""
    here = lambda alt: set(alt) <= set(profile)
    used = {c for _, x in slots(features) for alt in x.get("columns", []) if here(alt) for c in alt}
    script = {path: f.get("script") for g in features for f in g["features"] for path, x in slots([dict(g, features=[f])])}
    kinds = {"person name": "full name", "family": "family name", "given": "given name"}
    found = []
    for path, x in slots(features):
        if any(here(alt) for alt in x.get("columns", [])):
            continue
        kind = kinds.get(x.get("role")) or kinds.get(x.get("type"), x.get("type"))
        if kind in PROFILED:
            share = {c: p[PROFILED[kind]] for c, p in profile.items() if kind == "address" or not script[path] or p["script"] == script[path]}
            why = lambda c: f"{share[c]:.0%} {SAYS[PROFILED[kind]]}" + (f", in {script[path]}" if script[path] and kind != "address" else "")
        elif x.get("field") in fit:
            share = dict(fit[x["field"]])
            why = lambda c, f=x["field"]: f"{share[c]:.0%} " + ("filled, each value once" if f == "id" else f"look like {f.replace('_', ' ')}")
        else:
            continue
        found += [(v, path, c, why(c)) for c, v in share.items() if v >= least]
    out, taken, placed = [], set(used), set()
    for v, path, c, why in sorted(found, key=lambda t: -t[0]):
        if c not in taken and path not in placed:
            out.append(dict(feature=path, column=c, share=v, why=why))
            taken.add(c)
            placed.add(path)
    return out


def load_settings(path: Path | None = None, columns: Path | None = None) -> Settings:
    """The settings file at `path` (settings_path()); with `columns`, a workspace's columns.toml, whose [columns] and
    [kind] replace the file's."""
    path = Path(path or settings_path())
    root = project_root(path.parent)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    if columns:
        own = tomllib.loads(Path(columns).read_text(encoding="utf-8"))
        cfg = {**cfg, "columns": own["columns"], "kind": own.get("kind", {})}
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
