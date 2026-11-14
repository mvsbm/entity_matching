"""Shared settings from config/settings.toml: paths, datasets, the fields a file's columns hold, and the language-specific
normalization, validated on load. ER_SETTINGS may name another settings file. A workspace keeps its own mapping in its
columns.toml ([columns] and [kind]), which replaces the project's (own_columns makes it). set_columns rewrites [columns]
lines of either file."""
import importlib.util
import json
import os
import re
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

from er.config import COPIES, Data, Derived, InputError, Normalizer, Pipeline, Standardization, check_fields, checked, legal_pattern, restrict, sources_text, toml_of
from er.intake import InputSpec
from er.io import replace_text

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
    checked(all(sources), f"[columns] {name}: an alternative with no column", where)  # no alternative at all: the field has no column, as in a file without it
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


def set_name_kinds(path: Path, by_kind: bool) -> None:
    """Each name field kept only on the records that lean its kind (by_kind: kind written on full_name, person_name and
    company_name), or on every record, as mapped (kind taken off), in the [columns] of the file at `path`. O(the file)."""
    current = tomllib.loads(path.read_text(encoding="utf-8"))["columns"]
    have = {f: field(f, current[f], path).sources for f in NAME_KINDS if f in current}
    set_columns(path, have, update={f: {"kind": NAME_KINDS[f] if by_kind else None} for f in have})


def names_by_kind(s: "Settings") -> bool:  # whether a record's name goes only to the side its kind leans to
    return any(d.kind for d in s.standardize.derived if d.name in NAME_KINDS)


def settings_path() -> Path:  # the settings file a run reads
    return Path(os.environ.get("ER_SETTINGS") or project_root() / "config" / "settings.toml")


def columns_file(workspace: str | Path | None) -> Path | None:  # a workspace's own mapping, if it keeps one
    f = Path(workspace) / COLUMNS if workspace else None
    return f if f and f.is_file() else None


HEADER = re.compile(r"\s*\[\[?\s*[\w.\- ]+\s*\]\]?\s*(#.*)?$")  # a table's header line: one of an array written over several lines starts with [ too


def own_columns(path: Path) -> str:
    """A new workspace's columns.toml: the [columns] and [kind] sections of the settings file at `path`, comments kept."""
    keep, out = False, ["# This workspace's mapping: which of its files' columns hold each field. nayose set columns --workspace changes it.\n"]
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if HEADER.match(line):
            keep = line.split("#")[0].strip() in ("[columns]", "[kind]")
            out += ["\n"] if keep else []
        out += [line] if keep else []
    return "".join(out)


def set_columns(path: Path, mapping: dict[str, tuple[tuple[str, ...], ...]], options: Mapping[str, dict] | None = None,
                update: Mapping[str, dict] | None = None) -> None:
    """Rewrite the [columns] lines of the fields in `mapping` in the settings file at `path`: each field's source
    alternatives, tried in order, each one column or several joined (none: the field has no column, and whatever reads it
    is turned off, as for a file that lacks it; the field stays declared, so the pipeline still loads). Every other line, each
    line's comment, and a field's options (normalize, kind) stay; a new field takes its `options`; `update` merges
    options into a field's (None takes one off). The new text is loaded and validated before it replaces the old. O(the file)."""
    text = path.read_text(encoding="utf-8")
    lines, current = text.splitlines(keepends=True), tomllib.loads(text)["columns"]
    start = next(i for i, x in enumerate(lines) if x.strip() == "[columns]")
    end = next((i for i in range(start + 1, len(lines)) if HEADER.match(lines[i])), len(lines))
    toml = lambda v: json.dumps(v, ensure_ascii=False)  # a string or a list of strings: the same in TOML
    for name, sources in mapping.items():
        at = next((i for i in range(start + 1, end) if re.match(rf"{re.escape(name)}\s*=", lines[i])), None)
        old, alts = current.get(name, (options or {}).get(name)), [list(a) for a in sources]
        if name in (update or {}):
            old = {k: v for k, v in {**(old if isinstance(old, dict) else {}), **update[name]}.items() if v is not None}
        value = (f"{{ {', '.join(f'{k} = {toml(v)}' for k, v in {**old, 'sources': alts}.items())} }}" if isinstance(old, dict)
                 else toml(alts[0][0]) if alts and alts == [alts[0][:1]] else toml(alts))
        comment = re.search(r'^[^"#]*(?:"[^"]*"[^"#]*)*\s(#.*)$', lines[at].rstrip("\n")) if at is not None else None
        line = f"{name} = {value}"
        line += (" " * max(1, comment.start(1) - len(line)) + comment.group(1) if comment else "") + "\n"  # the comment in its column
        if at is None:  # a new field: after the section's last one
            last = max(i for i in range(start, end) if re.match(r"\w+\s*=", lines[i]))
            at = next(k for k in range(last + 1, end + 1) if _complete("".join(lines[last:k])))  # past every line of its value
            lines.insert(at, line)
            end += 1
        else:
            span = next(k for k in range(at + 1, end + 1) if _complete("".join(lines[at:k])))  # a value written over several lines: all of them
            lines[at:span] = [line]
            end -= span - at - 1
    def loads(new: Path) -> None:  # what load_settings checks: said, and the old file kept
        try:
            load_settings(new) if "paths" in tomllib.loads(text) else load_settings(columns=new)  # a workspace's file: over the project's
        except Exception as e:
            raise InputError(f"{path}: [columns] would not load: {e}", fix="give each field existing columns; id names one column") from None
    replace_text(path, "".join(lines), loads)


def _complete(text: str) -> bool:  # whether these lines hold a whole key = value
    try:
        tomllib.loads(text)
        return True
    except tomllib.TOMLDecodeError:
        return False


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


SCRIPTS = {"kana": ["nfkc", "katakana", "strip_spaces"], "kanji": ["nfkc", "strip_spaces"], "romaji": ["nfkc", "strip_spaces", "casefold"]}  # how a name's script is prepared
ADDED = {"person name": ("person_name", "given_name"), "company name": ("company_name",)}  # an added feature's fields stand beside these


def features_from(columns: Mapping[str, tuple[tuple[str, ...], ...]], added: Mapping[str, dict] | None = None) -> list[dict]:
    """The default structure, filled from a mapping ([columns]), then the features added to it (columns.toml's [features],
    by their main field, each after its group's defaults): each slot's columns from its field's; a person's name read back
    from person_name, or an added one's person_name_N (its alternatives but a last, joined one: the full name; that joined
    one: the family name, then the given name) and given_name (given_name_N). compiled() turns it back into the same
    mapping. O(fields)."""
    alts = lambda f: [list(a) for a in columns.get(f, ())]

    def person(f: dict, name: str, given: str) -> dict:
        full, first = alts(name), alts(given)[:1]
        whole = name == "person_name" and alts("full_name") == full  # full_name holds the first full name, so a lone one is it
        joined = full[-1] if full and len(full[-1]) > 1 and first == [full[-1][-1:]] and not whole else None  # the parts, as compiled() joins them; else a full name of several columns
        return {**{k: v for k, v in f.items() if k != "parts"}, "columns": full[:-1] if joined else full,
                "parts": [dict(name="Family name", role="family", columns=[joined[:-1]] if joined else []),
                          dict(name="Given name", role="given", columns=alts(given))]}
    out = []
    for group, feats in DEFAULT_FEATURES:
        mine = [person(f, "person_name", "given_name") if f["type"] == "person name" else {**f, "columns": alts(f["field"])} for f in feats]
        for field, x in (added or {}).items():
            if x.get("group") == group:
                f = dict(name=x["label"], type=x["type"], script=x.get("script"), field=field, added=True)
                mine.append(person(f, field, given_field(field)) if x["type"] == "person name" else {**f, "columns": alts(field)})
        out.append(dict(group=group, features=mine))
    return out


def given_field(field: str) -> str:  # an added person's name's given name: person_name_2 → given_name_2
    return "given_name" + field.removeprefix("person_name")


def compiled(features: list[dict]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """The mapping ([columns]) a structure means: each slot's columns for its field; from the person's name, full_name (its
    first column), person_name (its columns, then the family and given names joined) and given_name, and from an added one
    its own person_name_N and given_name_N; any_name, every default person and company name alternative (the
    person-or-company model reads it, in the script it was trained on). O(slots)."""
    out, person, company = {}, [], []
    for g in features:
        for f in g["features"]:
            if f["type"] == "person name":
                parts = {x["role"]: x["columns"] for x in f.get("parts", [])}
                family, given = parts.get("family", []), parts.get("given", [])
                alts = [*f["columns"], *([family[0] + given[0]] if family and given else [])]
                if f.get("added"):
                    out.update({f["field"]: alts, given_field(f["field"]): given})
                else:
                    person = alts
                    out.update(full_name=f["columns"][:1], person_name=alts, given_name=given)
            elif "field" in f:
                out[f["field"]] = f["columns"]
                company = f["columns"] if f["field"] == "company_name" else company
    out["any_name"] = [*person, *company]
    return {k: tuple(tuple(a) for a in v) for k, v in out.items()}


def added_of(workspace: str | Path | None) -> dict[str, dict]:  # the features added in a workspace: columns.toml's [features]
    f = columns_file(workspace)
    return toml_of(f).get("features", {}) if f else {}


def beside(added: Mapping[str, dict]) -> list[tuple[str, str]]:
    """Each added field, and the field it stands beside (config.widen): a person's name and its given name beside
    person_name and given_name, a company name beside company_name."""
    return [pair for field, x in added.items() for pair in
            ([(field, "person_name"), (given_field(field), "given_name")] if x["type"] == "person name" else [(field, ADDED[x["type"]][0])])]


def slots(features: list[dict]) -> list[tuple[str, dict]]:  # every slot with its path: group/feature, group/feature/part
    return [(f"{g['group']}/{f['name']}" + (f"/{x['name']}" if x is not f else ""), x) for g in features for f in g["features"] for x in [f, *f.get("parts", [])]]


def features_of(workspace: str | Path | None) -> list[dict]:  # a workspace's structure, read back from its mapping (else the project's)
    return features_from(load_settings(columns=columns_file(workspace)).columns, added_of(workspace))


def write_added(path: Path, added: Mapping[str, dict]) -> None:
    """Write columns.toml's [features] (the features added, by their main field) in place of the old, under a temporary
    name first, checked to load, then renamed. O(the file)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if (start := next((i for i, x in enumerate(lines) if x.split("#")[0].strip() == "[features]"), None)) is not None:
        end = next((i for i in range(start + 1, len(lines)) if HEADER.match(lines[i])), len(lines))
        del lines[start:end]
    text = "".join(lines).rstrip("\n") + "\n"
    if added:
        toml = lambda v: json.dumps(v, ensure_ascii=False)
        text += "\n[features]                                       # features added in this workspace: nayose add feature\n" + "".join(
            f"{k} = {{ {', '.join(f'{a} = {toml(b)}' for a, b in v.items() if b is not None)} }}\n" for k, v in added.items())
    replace_text(path, text, lambda new: load_settings(columns=new))


def add_feature(workspace: str | Path, path: str, kind: str, script: str | None = None, column: str | None = None) -> list[dict]:
    """Add a feature to a group (path: group/name): a person's name, with its family and given names, or a company name,
    in a script (kana, kanji, romaji: how its values are prepared). Its fields are numbered beside the ones it stands
    with (person_name_2, given_name_2; company_name_2), written into the workspace's columns.toml with the column given,
    if any, and named in [features]. A run compares it with them (config.widen). O(the file)."""
    ws, feats = Path(workspace), features_of(workspace)
    group, _, label = path.partition("/")
    if not ws.is_dir():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    if group != "Name" or kind not in ADDED:
        raise InputError(f"{path}: a {kind} can't be added there", fix="add a person name or a company name to Name: Name/<its name>")
    if not label.strip() or any(c in label for c in "/=,+"):
        raise InputError(f"{path}: name the feature", fix="for example Name/Kanji name, without / = , or +")
    if path in dict(slots(feats)):
        raise InputError(f"{path} exists", fix="choose another name")
    if not columns_file(ws):
        (ws / COLUMNS).write_text(own_columns(settings_path()), encoding="utf-8")
    current, base = load_settings(columns=ws / COLUMNS).columns, ADDED[kind][0]
    field = f"{base}_{next(n for n in range(2, 1000) if f'{base}_{n}' not in current)}"
    fields = [field, given_field(field)] if kind == "person name" else [field]
    norm = SCRIPTS[script or "kana"]
    set_columns(ws / COLUMNS, {f: ((column,),) if column and f == field else () for f in fields}, options={f: {"normalize": norm} for f in fields})
    write_added(ws / COLUMNS, {**added_of(ws), field: dict(group=group, label=label.strip(), type=kind, script=script)})
    return features_of(ws)


def remove_feature(workspace: str | Path, path: str) -> list[dict]:
    """Remove a feature added to a workspace (path: group/name): its fields leave columns.toml, and its name [features].
    A default feature stays; its columns can be taken off instead. O(the file)."""
    ws = Path(workspace)
    f = next((f for g in features_of(ws) for f in g["features"] if f"{g['group']}/{f['name']}" == path), None)
    if f is None or not f.get("added"):
        raise InputError(f"{path}: not a feature added here", fix="only an added feature can be removed; take a default one's columns off instead")
    fields = {f["field"], given_field(f["field"])} if f["type"] == "person name" else {f["field"]}
    lines = (ws / COLUMNS).read_text(encoding="utf-8").splitlines(keepends=True)
    replace_text(ws / COLUMNS, "".join(x for x in lines if not any(re.match(rf"{re.escape(n)}\s*=", x) for n in fields)))
    write_added(ws / COLUMNS, {k: v for k, v in added_of(ws).items() if k != f["field"]})
    return features_of(ws)


def set_features(workspace: str | Path, values: Mapping[str, tuple[tuple[str, ...], ...]]) -> list[dict]:
    """Set slots' columns (by path: group/feature, or group/feature/part), then write the mapping they compile to into
    the workspace's columns.toml, made from the project's first; set_columns checks it loads before it replaces the old.
    O(the file)."""
    ws, feats = Path(workspace), features_of(workspace)
    if not ws.is_dir():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    before = compiled(feats)  # what the slots compile to now: only the fields this change moves are written
    found = dict(slots(feats))
    for path, alternatives in values.items():
        if path not in found:
            raise InputError(f"no feature {path}", fix="the features: " + ", ".join(found))
        found[path]["columns"] = [list(a) for a in alternatives]
    for path, x in found.items():  # a family name is read joined to the given name's first column: one, with a given name
        if x.get("role") == "family" and x["columns"] and (len(x["columns"]) > 1 or not found[path.rsplit("/", 1)[0] + "/Given name"]["columns"]):
            raise InputError(f"{path}: a family name is read joined to the given name, one column", fix="give it one column, and the given name its own")
    if not columns_file(ws):
        (ws / COLUMNS).write_text(own_columns(settings_path()), encoding="utf-8")
    after = compiled(feats)  # a field set by set columns (full_name = another column) stays, unless this change moves it
    set_columns(ws / COLUMNS, {f: v for f, v in after.items() if before.get(f) != v})
    return features_of(ws)


PHONE_NAME = re.compile(r"phone|tel|mobile|cell|keitai|denwa|電話|携帯")  # a column named for a phone (not a fax: it doesn't take calls)
PROFILED = {"full name": "full", "family name": "family", "given name": "given", "address": "address"}  # slot type → the profile's share
SAYS = {"full": "are a known family name and given name", "family": "are known family names", "given": "are known given names",
        "address": "start with a known prefecture or city"}


def norm_name(column: str) -> str:  # a column's name as people mean it: width, case and separators aside
    return re.sub(r"[\s_\-・.]+", "", unicodedata.normalize("NFKC", column).casefold())


def placements(features: list[dict], profile: Mapping[str, dict], fit: Mapping[str, Mapping[str, float]], least: float = 0.5) -> list[dict]:
    """For each slot none of whose columns the file holds (profile: the file's columns), the file's column that most looks
    like it, with the share and the evidence: a person's name and an address from the profile (er.source.profiled: known
    names and places, in the feature's script), anything else from its field's fit (its [locale.detect] pattern; an ID:
    every value different). The slot with the fewest columns that could fill it is placed first, so a broad pattern (five
    digits or more) doesn't take what only a narrow one (a postal code) fits; then the best free column, the file's order
    breaking ties. A column no other slot holds, and not one holding the same values as a placed one (profile: same).
    Suggestions only. O(slots · columns)."""
    here = lambda alt: set(alt) <= set(profile)
    taken = {c for _, x in slots(features) for alt in x.get("columns", []) if here(alt) for c in alt}
    script = {path: f.get("script") for g in features for f in g["features"] for path, x in slots([dict(g, features=[f])])}
    kinds = {"person name": "full name", "family": "family name", "given": "given name"}
    order = {c: i for i, c in enumerate(profile)}
    candidates, why = {}, {}
    for path, x in slots(features):
        if any(here(alt) for alt in x.get("columns", [])):
            continue
        kind = kinds.get(x.get("role")) or kinds.get(x.get("type"), x.get("type"))
        if kind in PROFILED:
            share = {c: p[PROFILED[kind]] for c, p in profile.items() if kind == "address" or not script[path] or p["script"] == script[path]}
            say = f" {SAYS[PROFILED[kind]]}" + (f", in {script[path]}" if script[path] and kind != "address" else "")
        elif x.get("type") == "phone":  # its name says phone and its values are numbers; else its values alone, 4 digits
            named = {c: p["phone"] for c, p in profile.items() if PHONE_NAME.search(norm_name(c)) and "fax" not in norm_name(c) and p.get("phone", 0) >= 0.8}
            share = {c: v for c, v in fit.get(x["field"], {}).items() if c not in named} | {c: 1 + v for c, v in named.items()}  # a name that says so first
            say = " look like phone numbers"
        elif x.get("field") in fit:
            share, say = dict(fit[x["field"]]), " filled, each value once" if x["field"] == "id" else f" look like {x['field'].replace('_', ' ')}"
            if x["type"] == "id" and x["field"] != "id":  # another ID: its pattern, and how few records share a value (an address code repeats)
                share = {c: v * fit.get("id", {}).get(c, 0) for c, v in share.items()}
                say += ", mostly each value once"
        else:
            continue
        floor = 0.99 if x.get("field") == "id" else least  # an ID: every value different, or nothing
        candidates[path], why[path] = {c: v for c, v in share.items() if v >= floor}, say
    out = []
    for path in sorted(candidates, key=lambda p: len(candidates[p])):
        free = [(v, -order[c], c) for c, v in candidates[path].items() if c not in taken and not set(profile[c].get("same", ())) & taken]
        if free:
            v, _, c = max(free)
            v, named = (v - 1, True) if v > 1 else (v, False)  # a phone named so: its share as it is, and its name said
            out.append(dict(feature=path, column=c, share=v, why=("its name says phone; " if named else "") + f"{v:.0%}{why[path]}"))
            taken.add(c)
    return out


def offers(features: list[dict], profile: Mapping[str, dict], least: float = 0.5) -> list[dict]:
    """New features the file's contents suggest: for each script its full names come in (er.source.profiled) that no
    person's name feature holds, the unused column with the most full names in it, offered as a Name feature in that
    script, with the share and the evidence. Suggestions only. O(columns)."""
    here = lambda alt: set(alt) <= set(profile)
    taken = {c for _, x in slots(features) for alt in x.get("columns", []) if here(alt) for c in alt}
    have = {f.get("script") or "kana" for g in features for f in g["features"] if f["type"] == "person name"}
    out = []
    for script in SCRIPTS:
        free = [(p["full"], -i, c) for i, (c, p) in enumerate(profile.items())
                if p["script"] == script and p["full"] >= least and c not in taken and not set(p.get("same", ())) & taken]
        if script not in have and free:
            share, _, c = max(free)
            out.append(dict(feature=f"Name/{script.capitalize()} name", type="person name", script=script, column=c, share=share,
                            why=f"{share:.0%} are a known family name and given name, in {script}"))
    return out


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
                             fix=f"map each to a column of its own (nayose set columns {f}=… --workspace …), or leave one unmapped")


def fit_to_file(p: Pipeline, s: Settings, file_columns: Iterable[str], labelled: bool = False) -> tuple[Pipeline, list[str]]:
    """The pipeline for one file: stops if a mandatory field (or every field of a one_of group) is absent; derives each
    field only from the sources the file has; disables whatever reads an absent optional field, and lists it."""
    present = present_fields(s, file_columns)
    check_fields(p.fields, set(present), s.columns, labelled)
    counted_once(p, present)
    std = replace(s.standardize, derived=tuple(replace(d, sources=present[d.name]) for d in s.standardize.derived if d.name in present))
    return restrict(replace(p, rules=replace(p.rules, standardize=std), fs=replace(p.fs, standardize=std)), set(present))
