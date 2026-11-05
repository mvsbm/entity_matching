"""The synthetic generator: entities from real reference names, companies and towns, each appearing under one or more
records, with realistic typos, notations, moves, new phones and correlated missing values, then split by entity. Its
spec is config/generator.toml. profile() says how hard the result is: what a customer's records still share.
"""
import json
import tomllib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from rapidfuzz.distance import JaroWinkler

Kind = Literal["person", "company"]


@dataclass(frozen=True, kw_only=True)
class Column:
    name: str
    dtype: str = "string"         # pandas dtype; codes stay string to keep leading zeros
    nullable: bool = True         # nullable columns share the rate_start → rate_end ramp, in column order
    group: str | None = None      # columns in one group share missingness (Spec.nesting), in column order
    kind: Kind | None = None      # filled only on rows of this kind; None = every row
    digits: int | None = None     # exact digit count, checked after generation


@dataclass(frozen=True)
class AddressFormat:
    template: str                 # fields: pref city town chome_jp ban go five building room
    fullwidth: bool = False       # convert ASCII digits and hyphens to full width


@dataclass(frozen=True, kw_only=True)
class Spec:
    seed: int
    entities: int
    company_share: float
    dup_lambda: float                        # extra CONT_IDs per entity, Poisson
    multi_lambda: Mapping[str, Mapping[Kind, float]]  # per attribute (phone, address, name): extra values per entity, Poisson
    cif_keep: float                          # chance a duplicate record reuses the entity's CIF_ID
    cif_typo_rate: float                     # per reused CIF_ID: one wrong digit
    rate_start: float
    rate_end: float
    phone_prefixes: tuple[str, ...]
    phone_digits: int
    ban_max: int
    go_max: int
    address_pool_ratio: float                # pool size / addresses held, per prefecture; < 1 makes unrelated entities share
    full_name_sep: str
    original_name_sep: str
    legal_forms_written: tuple[tuple[str, float], ...]  # how a record writes the legal form, with its weight; "" = left out
    legal_prefix_share: float                # 株式会社〇〇 vs 〇〇株式会社, per company name
    branch_rate: float                       # per company record: a branch written after the name
    branches: tuple[str, ...]
    space_rate: float                        # per person record: a space between surname and given name in FULL_NAME_KANA
    halfwidth_rate: float                    # per record: every name column in half-width katakana
    name_typo_rate: float                    # per record and name part (surname, given name, company name)
    kana_confusions: tuple[tuple[str, str], ...]  # swapped both ways; a dropped character when none applies
    phone_typo_rate: float                   # per record: one wrong PHONE_NUM_4 digit
    address_typo_rate: float                 # per record: one wrong digit (else a dropped character) in ORIGINAL_ADDRESS
    nesting: Mapping[str, float]             # per group: 1 = fully nested missingness, 0 = independent
    buildings: tuple[str, ...]
    original_address_formats: tuple[AddressFormat, ...]
    columns: tuple[Column, ...]

    def __post_init__(self) -> None:
        names = [c.name for c in self.columns]
        assert len(set(names)) == len(names), "duplicate column names"
        assert 0 < self.rate_end <= self.rate_start <= 1
        for g in self.groups:
            assert len({c.kind for c in g}) == 1, f"group mixes kinds: {[c.name for c in g]}"
        assert set(self.nesting) <= {c.group for c in self.columns}, "nesting names an unknown group"
        assert all(0 <= rho <= 1 for rho in self.nesting.values())
        assert set(self.multi_lambda) == {"phone", "address", "name"}, "multi_lambda: phone, address and name"

    @property
    def rates(self) -> dict[str, float]:
        names = [c.name for c in self.columns if c.nullable]
        return dict(zip(names, np.linspace(self.rate_start, self.rate_end, len(names)).tolist()))

    @property
    def groups(self) -> list[list[Column]]:  # ungrouped nullable columns stand alone
        out: dict[str, list[Column]] = {}
        for c in self.columns:
            if c.nullable:
                out.setdefault(c.group or c.name, []).append(c)
        return list(out.values())


@dataclass(frozen=True, kw_only=True)
class Split:
    shares: Mapping[str, float]               # by entity, so a duplicate group never spans two splits
    seed: int

    def __post_init__(self) -> None:
        assert abs(sum(self.shares.values()) - 1) < 1e-9, "split shares must sum to 1"

FULLWIDTH = str.maketrans("0123456789-", "０１２３４５６７８９－")
HALFWIDTH = {unicodedata.normalize("NFKC", chr(c)): chr(c) for c in range(0xFF66, 0xFF9E)}  # katakana → its half-width form
MARKS = {"\u3099": "ﾞ", "\u309a": "ﾟ"}  # the voicing marks, written after the half-width letter


def halfwidth(s: str) -> str:  # ガ → ｶﾞ: how many systems store katakana; NFKC turns it back
    return "".join(HALFWIDTH.get(d[0], d[0]) + "".join(MARKS.get(m, m) for m in d[1:])
                   for d in (unicodedata.normalize("NFD", ch) for ch in s))


def load_reference(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def read(name: str) -> pd.DataFrame:
        return pd.DataFrame(json.loads((folder / name).read_text(encoding="utf-8")))
    persons, companies, towns = read("individual.json"), read("companies.json"), read("addresses.json")
    towns["chome"] = pd.Series([None if pd.isna(c) else int(c) for c in towns["chome"]], dtype=object)  # int, or None (no 丁目)
    towns = towns.drop_duplicates(["city_code", "town", "chome"], ignore_index=True)  # geolonia repeats some towns per 小字
    towns["town_seq"] = towns.groupby("city_code")["town"].transform(lambda t: pd.factorize(t, sort=True)[0] + 1)
    assert towns["town_seq"].max() < 1000, "town sequence must fit 3 digits of ADDR_CD"
    return persons, companies, towns


@dataclass(frozen=True)
class Address:
    town: int                     # row in the town reference
    ban: int
    go: int
    code: str                     # SOURCE_ADDR_CD


@dataclass
class Generated:
    df: pd.DataFrame              # pipeline columns, with missing cells
    clean: pd.DataFrame           # pipeline columns before blanking
    with_truth: pd.DataFrame      # clean + ENTITY_ID, KIND
    truth: pd.DataFrame
    applies: dict[str, pd.Series]
    typos: dict[str, int]


def generate(spec: Spec, persons: pd.DataFrame, companies: pd.DataFrame, towns: pd.DataFrame) -> Generated:
    rng = np.random.default_rng(spec.seed)
    digits = {c.name: c.digits for c in spec.columns}
    confusions = [(a, b) for x, y in spec.kana_confusions for a, b in ((x, y), (y, x))]
    typos = {"name": 0, "phone": 0, "address": 0, "cif": 0}
    town_rows = towns.to_dict("records")
    surname_pool = persons["surname_kana"].to_numpy()

    def pick[T](xs: Sequence[T]) -> T:
        return xs[rng.integers(len(xs))]

    def distinct_digits(n: int, k: int) -> list[str]:  # n distinct k-digit numbers
        return [str(x) for x in 10 ** (k - 1) + rng.choice(9 * 10 ** (k - 1), n, replace=False)]

    def phone() -> str:
        prefix = pick(spec.phone_prefixes)
        rest = spec.phone_digits - len(prefix)
        return f"{prefix}{rng.integers(10 ** rest):0{rest}d}"

    def kana_typo(s: str) -> str:  # one realistic kana error: a confusable swap, else a dropped character
        spots = [(i, b) for i, ch in enumerate(s) for a, b in confusions if ch == a]
        if spots:
            i, b = pick(spots)
            return s[:i] + b + s[i + 1:]
        return drop_one(s)

    def drop_one(s: str) -> str:  # drop a non-initial character; 1-character values (e.g. the surname イ) stay intact
        if len(s) < 2:
            return s
        i = int(rng.integers(1, len(s)))
        return s[:i] + s[i + 1:]

    def digit_typo(s: str) -> str:  # one wrong digit, keeping its width; else a dropped character
        spots = [i for i, ch in enumerate(s) if ch.isdigit()]
        if not spots:
            return drop_one(s)
        i = pick(spots)
        d = (unicodedata.digit(s[i]) + int(rng.integers(1, 10))) % 10
        return s[:i] + (chr(0xFF10 + d) if ord(s[i]) >= 0xFF10 else str(d)) + s[i + 1:]

    def noisy(s: str, kind: Literal["name", "phone", "address", "cif"]) -> str:
        rate = {"name": spec.name_typo_rate, "phone": spec.phone_typo_rate, "address": spec.address_typo_rate, "cif": spec.cif_typo_rate}[kind]
        if rng.random() >= rate:
            return s
        typos[kind] += 1
        return kana_typo(s) if kind == "name" else digit_typo(s)

    def five(a: Address) -> str:  # 丁目-番-号, or 番-号 where the town has no 丁目
        chome = town_rows[a.town]["chome"]
        return f"{chome}-{a.ban}-{a.go}" if chome is not None else f"{a.ban}-{a.go}"

    def address_columns(a: Address) -> dict[str, str]:
        t = town_rows[a.town]
        addr_cd = f"{t['city_code']}{t['town_seq']:03d}{t['chome'] or 0:03d}"  # 住所コード: municipality + town no. + chome
        return dict(POST_CD=t["postal"], POST_CD_KANA=t["postal"], SOURCE_ADDR_CD=a.code, ADDRESS_FIVE=five(a),
                    ADDRESS_FIVE_KANA=five(a), ADDR_CD_KANA=addr_cd, ADDR_CD=addr_cd,
                    STD_ADDRESS=f"{t['pref']}{t['city']}{t['town']}{five(a)}", ADDRESS_ONE=t["pref"], ADDRESS_TWO=t["city"])

    def original_address(a: Address) -> str:  # uncleaned, the way it was typed in
        t = town_rows[a.town]
        building, room = pick(spec.buildings), f"{rng.integers(1, 10)}0{rng.integers(1, 10)}"
        fmt = pick(spec.original_address_formats)
        s = fmt.template.format(pref=t["pref"], city=t["city"], town=t["town"], ban=a.ban, go=a.go, five=five(a),
                                chome_jp=f"{t['chome']}丁目" if t["chome"] is not None else "", building=building, room=room)
        return noisy(s.translate(FULLWIDTH) if fmt.fullwidth else s, "address")

    kinds = np.where(rng.random(spec.entities) < spec.company_share, "company", "person")
    n_phone, n_addr, n_name = (1 + rng.poisson(np.array([spec.multi_lambda[a][k] for k in kinds])) for a in ("phone", "address", "name"))
    n_rec = 1 + rng.poisson(spec.dup_lambda, spec.entities)
    assert spec.entities <= len(persons), f"{spec.entities:,} entities need as many distinct personas; there are {len(persons):,}"
    # without replacement: two entities drawn from one persona would be clones (same name and prefecture), which no
    # matcher can tell apart. Companies use it only for a population-weighted prefecture.
    persona = rng.choice(len(persons), size=spec.entities, replace=False)
    pref = persons["prefecture"].to_numpy()[persona]

    # Address pool per prefecture, smaller than what its entities hold, so unrelated entities sometimes share (households)
    towns_in = {p: g.index.to_numpy() for p, g in towns.groupby("pref")}
    assert set(pref) <= set(towns_in), f"prefectures without towns: {set(pref) - set(towns_in)}"
    need = pd.Series(n_addr).groupby(pref).sum()
    codes = iter(distinct_digits(int(need.sum()), digits["SOURCE_ADDR_CD"]))
    pools: dict[str, list[Address]] = {}
    for p, k in need.items():
        t = towns_in[p]
        shape = (len(t), spec.ban_max, spec.go_max)
        size = min(max(1, int(k * spec.address_pool_ratio)), int(np.prod(shape)))
        ti, b, g = np.unravel_index(rng.choice(np.prod(shape), size, replace=False), shape)
        pools[p] = [Address(int(t[i]), int(bb) + 1, int(gg) + 1, next(codes)) for i, bb, gg in zip(ti, b, g)]

    cifs = iter(distinct_digits(spec.entities + n_rec.sum(), digits["CIF_ID"]))
    company_names = companies["name_kana"].to_numpy()
    rows: list[dict[str, str]] = []
    for e, kind in enumerate(kinds):
        phones = [phone() for _ in range(n_phone[e])]
        pool = pools[pref[e]]
        addrs = rng.choice(len(pool), min(n_addr[e], len(pool)), replace=False).tolist()
        if kind == "person":  # extra surnames (maiden / married) come from the persona surname pool
            names, given = [persons.at[persona[e], "surname_kana"]], persons.at[persona[e], "given_kana"]
            while len(names) < n_name[e]:
                s = pick(surname_pool)
                names += [s] if s not in names else []
        else:  # (name, legal form in front?)
            names = [(s, rng.random() < spec.legal_prefix_share) for s in rng.choice(company_names, n_name[e], replace=False).tolist()]
        base_cif = next(cifs)
        forms, weights = zip(*spec.legal_forms_written)
        for r in range(n_rec[e]):
            a = pool[pick(addrs)]
            cif = base_cif if r == 0 else noisy(base_cif, "cif") if rng.random() < spec.cif_keep else next(cifs)
            row = dict(ENTITY_ID=f"E{e:06d}", KIND=str(kind), PHONE_NUM_4=noisy(pick(phones)[-digits["PHONE_NUM_4"]:], "phone"),
                       CIF_ID=cif, ORIGINAL_ADDRESS=original_address(a), **address_columns(a))
            if kind == "person":  # typos go into the parts, so every name column agrees
                last, first = noisy(pick(names), "name"), noisy(given, "name")
                sep = "　" if rng.random() < spec.space_rate else spec.full_name_sep
                row |= dict(FULL_NAME_KANA=f"{last}{sep}{first}", O_PERSON_NAME_KANA=f"{last}{spec.original_name_sep}{first}",
                            LAST_NAME_KANA=last, GIVEN_NAME_KANA=first)
            else:  # the legal form written one of several ways, sometimes a branch after it
                stem, legal_first = pick(names)
                stem, legal = noisy(stem, "name"), forms[rng.choice(len(forms), p=np.array(weights) / sum(weights))]
                name = legal + stem if legal_first else stem + legal
                row["NYS_CNV_P_NAME_KANA"] = name + (f"　{pick(spec.branches)}" if rng.random() < spec.branch_rate else "")
            if rng.random() < spec.halfwidth_rate:  # the system that took this record stores half-width katakana
                row |= {c: halfwidth(row[c]) for c in ("FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA",
                                                       "NYS_CNV_P_NAME_KANA") if c in row}
            rows.append(row)

    with_truth = pd.DataFrame(rows).sample(frac=1, random_state=rng, ignore_index=True)  # shuffle so duplicates aren't adjacent
    with_truth.insert(0, "CONT_ID", [f"{i:0{digits['CONT_ID']}d}" for i in range(1, len(with_truth) + 1)])
    clean = with_truth.reindex(columns=[c.name for c in spec.columns]).astype({c.name: c.dtype for c in spec.columns})
    truth = with_truth[["CONT_ID", "ENTITY_ID", "KIND"]].astype("string")

    # A cell stays filled iff its score ranks below round(rate · n), so every rate is exact.
    # score = ρ · (per-row group draw) + (1 − ρ) · (per-cell draw): ρ = 1 nests the group fully.
    rates = spec.rates
    applies = {c.name: with_truth["KIND"].eq(c.kind) if c.kind else pd.Series(True, index=with_truth.index) for c in spec.columns}
    df = clean.copy()
    for group in spec.groups:
        idx = df.index[applies[group[0].name]]
        rho = spec.nesting.get(group[0].group, 1.0)
        shared = rng.random(len(idx))
        for c in group:
            score = rho * shared + (1 - rho) * rng.random(len(idx))
            rank = pd.Series(score.argsort().argsort(), index=idx)
            df.loc[rank.index[rank >= round(rates[c.name] * len(idx))], c.name] = None
    return Generated(df, clean, with_truth, truth, applies, typos)


def check(spec: Spec, g: Generated) -> None:
    rates = spec.rates
    for c in spec.columns:
        applies = g.applies[c.name]
        assert g.df[c.name].dtype == c.dtype, c.name
        assert g.clean[c.name].notna().equals(applies), f"{c.name}: clean data must be filled exactly where it applies"
        if c.digits:
            assert g.df[c.name].dropna().str.fullmatch(rf"\d{{{c.digits}}}").all(), c.name
        expected = round(rates[c.name] * applies.sum()) if c.nullable else applies.sum()
        assert g.df[c.name].notna().sum() == expected, c.name
    for group in spec.groups:
        if spec.nesting.get(group[0].group, 1.0) == 1:
            for prev, c in zip(group, group[1:]):
                assert not (g.df[c.name].notna() & g.df[prev.name].isna()).any(), (prev.name, c.name)
    assert g.df["CONT_ID"].is_unique  # the key a user's input is joined back by
    assert g.with_truth.groupby("CIF_ID")["ENTITY_ID"].nunique().max() == 1  # no CIF_ID shared by two entities
    assert g.with_truth.groupby("SOURCE_ADDR_CD")["STD_ADDRESS"].nunique().max() == 1
    assert g.with_truth.groupby("STD_ADDRESS")["SOURCE_ADDR_CD"].nunique().max() == 1


def profile(g: Generated) -> pd.Series:
    """How hard the population is: the share of true pairs (two records of one entity) that share each field exactly;
    the direct share (the same CIF_ID and name, or the same name, address code and phone), what exact rules settle;
    and the share with nothing in common: no field equal and names not even close (Jaro–Winkler under 0.75 after
    NFKC, spaces dropped), the pairs no method can find. O(pairs)."""
    d = g.df.merge(g.truth[["CONT_ID", "ENTITY_ID"]], on="CONT_ID")
    p = d.merge(d, on="ENTITY_ID", suffixes=("_l", "_r"))
    p = p[p["CONT_ID_l"] < p["CONT_ID_r"]]
    same = lambda c: ((p[f"{c}_l"] == p[f"{c}_r"]) & p[f"{c}_l"].notna()).fillna(False).to_numpy(bool)
    name_l, name_r = (p[f"FULL_NAME_KANA_{s}"].fillna(p[f"NYS_CNV_P_NAME_KANA_{s}"]) for s in "lr")
    name = ((name_l == name_r) & name_l.notna()).fillna(False).to_numpy(bool)
    plain = lambda s: unicodedata.normalize("NFKC", s).replace(" ", "").replace("　", "") if isinstance(s, str) else None
    close = np.array([a is not None and b is not None and JaroWinkler.similarity(a, b) >= 0.75
                      for a, b in zip(name_l.map(plain), name_r.map(plain))], dtype=bool)
    cif, phone, code = same("CIF_ID"), same("PHONE_NUM_4"), same("SOURCE_ADDR_CD")
    shared = cif | name | phone | code | same("STD_ADDRESS") | same("POST_CD") | same("GIVEN_NAME_KANA") | same("LAST_NAME_KANA")
    return pd.Series({"true pairs": len(p), "same customer ID": cif.mean(), "same exact name": name.mean(), "same phone": phone.mean(),
                      "same address code": code.mean(), "same standard address": same("STD_ADDRESS").mean(),
                      "direct (exact rules)": ((cif & name) | (name & code & phone)).mean(), "nothing in common": (~shared & ~close).mean()})


def load_spec(path: Path) -> tuple[Spec, Split]:
    """config/generator.toml → the population spec and the split."""
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    p = dict(cfg["population"])
    spec = Spec(**{**p, "multi_lambda": {a: dict(v) for a, v in p["multi_lambda"].items()}, "phone_prefixes": tuple(p["phone_prefixes"]),
                   "legal_forms_written": tuple(map(tuple, p["legal_forms_written"])), "branches": tuple(p["branches"]),
                   "kana_confusions": tuple(map(tuple, p["kana_confusions"])), "nesting": dict(p["nesting"]),
                   "buildings": tuple(p["buildings"]),
                   "original_address_formats": tuple(AddressFormat(**f) for f in p["original_address_formats"]),
                   "columns": tuple(Column(**c) for c in p["columns"])})
    return spec, Split(shares=dict(cfg["split"]["shares"]), seed=cfg["split"]["seed"])


def split_by_entity(truth: pd.DataFrame, split: Split) -> pd.Series:
    """Each record's split name: entities shuffled with split.seed and cut by split.shares, so a duplicate group never
    spans two splits."""
    entities = np.random.default_rng(split.seed).permutation(truth["ENTITY_ID"].unique())
    cuts = np.round(np.cumsum(list(split.shares.values())) * len(entities)).astype(int)[:-1]
    of = {e: name for name, part in zip(split.shares, np.split(entities, cuts)) for e in part}
    out = truth["ENTITY_ID"].map(of).rename("split")
    assert out.notna().all() and truth.assign(split=out).groupby("ENTITY_ID")["split"].nunique().max() == 1
    for name, share in split.shares.items():
        assert abs(truth.loc[out == name, "ENTITY_ID"].nunique() / len(entities) - share) <= 0.01, name
    return out
