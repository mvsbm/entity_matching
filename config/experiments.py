"""Development only: the variants scripts/choose.py tries on config/pipeline.toml, the order it decides them in, and
the Optuna search spaces (off by default). A variant is code, so this is Python; everything else is config/*.toml.
Each variant is a change to a configuration, written once; DECISIONS adopt them in order, each on top of the choice
so far, by er.evaluate.adopt: "better" needs a significant paired gain on the selection set (no FP added); "cheaper"
and "safer" (more pairs, gain at scale) no paired loss there; "chosen" is the owner's call for a gain the selection sets
are too small to show (no FP may be added, recall may move). "better", "cheaper" and "safer" also need no net loss on val
(at least as many true pairs gained as lost, no more false pairs added than removed); "chosen" needs only the second.
"""
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from er.config import (Candidate, Comparator, Comparison, FSSpec, FSTune, Key, Level, Pipeline, RulesSpec, SortedNeighbourhood, TfidfNeighbours,
                       Tune, KeyBlocker, with_comparators, with_level, without_tf)

FOLD, COMPANY = ("kana_fold",), ("nfkc", "strip_legal_form", "kana_fold")
READING, GIVEN_TAIL = ("kana_fold", "long_vowel"), ("kana_fold", "long_vowel", "last3")


# ---------- stage 1: rules ----------

def rules_changes(p: Pipeline) -> dict[str, Callable[[RulesSpec], RulesSpec]]:
    def f2_by_address_prefix(s: RulesSpec) -> RulesSpec:
        """F2 joined on the phone + the normalized address's first 3 characters (the city), not the phone alone.
        F2 accepts only close addresses, and close normalized addresses share their start."""
        block = (Key("address", ("address", "first3")),)
        return replace(s, stages=tuple(replace(st, rules=tuple(replace(r, blocking=block) if r.name == "F2_NAME~_ADDRESS~_PHONE"
                                                                else r for r in st.rules)) for st in s.stages))

    return {
        "fold_levenshtein": lambda s: with_comparators(s, "fuzzy", {"person_name": Comparator("levenshtein", 1, FOLD),
                                                                    "company_name": Comparator("levenshtein", 1, COMPANY)}),
        "fold_exact": lambda s: with_comparators(s, "fuzzy", {"person_name": Comparator("exact", normalize=FOLD),
                                                              "company_name": Comparator("exact", normalize=COMPANY)}),
        "raw_jaro_winkler": lambda s: with_comparators(s, "fuzzy", {"person_name": Comparator("jaro_winkler", 0.92),
                                                                    "company_name": Comparator("jaro_winkler", 0.92)}),
        "optuna_comparators": lambda s: with_comparators(s, "fuzzy", {  # an Optuna study's suggestion (trial 33); passed adopt
            "person_name": Comparator("damerau_levenshtein", 2, FOLD), "company_name": Comparator("levenshtein", 1, COMPANY),
            "address": Comparator("jaro_winkler", 0.9, ("address",)), "phone": Comparator("hamming", 1)}),
        # a fuzzy address leaves rule F2 joining on the phone alone, whose pairs grow with N²
        "f2_address_exact": lambda s: with_comparators(s, "fuzzy", {"address": Comparator("exact", normalize=("address",))}),
        "f2_address_prefix": f2_by_address_prefix,
    }


RULES_DECISIONS = (("fold_levenshtein", "better"), ("fold_exact", "cheaper"), ("f2_address_exact", "cheaper"),
                   ("f2_address_prefix", "cheaper"), ("optuna_comparators", "better"))   # the suggestion last: it was found on top of the rest


def rules_tune(optuna_dir: Path) -> Tune:
    return Tune(
        stage="fuzzy",
        space={
            "person_name": (Candidate("exact", FOLD), Candidate("jaro_winkler", FOLD, 0.85, 0.98, 0.01),
                            Candidate("jaro_winkler", (), 0.85, 0.98, 0.01), Candidate("levenshtein", FOLD, 1, 2, 1),
                            Candidate("damerau_levenshtein", FOLD, 1, 2, 1)),
            "company_name": (Candidate("exact", COMPANY), Candidate("jaro_winkler", COMPANY, 0.88, 0.98, 0.01),
                             Candidate("levenshtein", COMPANY, 1, 3, 1), Candidate("jaccard", (), 0.75, 0.95, 0.01)),
            "address": (Candidate("exact", ("address",)), Candidate("levenshtein", ("address",), 1, 3, 1),
                        Candidate("jaro_winkler", ("address",), 0.90, 0.99, 0.01)),
            "phone": (Candidate("hamming", (), 1, 1, 1), Candidate("damerau_levenshtein", (), 1, 1, 1)),
        },
        n_trials=60, seed=0,
        enabled=False,  # scripts/choose.py --optuna searches again; optuna_comparators keeps the last suggestion that passed adopt
        storage_path=optuna_dir / "deterministic_matching.db", study_prefix="deterministic",
        dashboard_host="127.0.0.1", dashboard_port=8080,
    )


# ---------- stage 2: Fellegi–Sunter ----------

NAME_KEYS = ("person_name", "company_name", "company_name_deletions", "person_name_deletions_postal_area", "given_name_postal")
ADDRESS_KEYS = ("address_phone", "address_code_phone", "address_name_initial", "address_code_name_initial", "given_name_address_code")


def fs_changes(p: Pipeline) -> dict[str, Callable[[FSSpec], FSSpec]]:
    pool: Mapping = p.generators
    as_written = p.fs.blockers

    def cif_one_digit_off(s: FSSpec) -> FSSpec:
        """The customer ID typed with one digit wrong: a level between exact and else."""
        off = Level(label="one digit off", any_of=(("customer_id", Comparator("damerau_levenshtein", 1)),))
        return replace(s, model=replace(s.model, comparisons=tuple(replace(c, levels=(*c.levels, off)) if c.name == "cif" else c
                                                                   for c in s.model.comparisons)))

    def graded_address(s: FSSpec) -> FSSpec:
        """Credit for a move nearby: after the same postal code, the same town, the same city, the same prefecture."""
        near = tuple(Level(label=label, any_of=((field, Comparator("exact")),))
                     for label, field in (("same town", "town_code"), ("same city", "city"), ("same prefecture", "prefecture")))
        return replace(s, model=replace(s.model, comparisons=tuple(
            replace(c, levels=(*c.levels, *near), null_if_missing=(*c.null_if_missing, "town_code", "city", "prefecture"))
            if c.name == "address" else c for c in s.model.comparisons)))

    def with_key(name: str) -> Callable[[FSSpec], FSSpec]:
        return lambda s: s if pool[name] in s.blockers else replace(s, blockers=(*s.blockers, pool[name]))

    def birth_date(s: FSSpec) -> FSSpec:
        """The birth date, where both records hold one: the same, one digit off or two adjacent digits swapped, else.
        Sparse, so it settles few pairs, but a namesake born on another day is strong evidence against a match."""
        levels = (Level(label="exact", any_of=(("birth_date", Comparator("exact")),)),
                  Level(label="one digit off", any_of=(("birth_date", Comparator("damerau_levenshtein", 1)),)))
        return replace(s, model=replace(s.model, comparisons=(*s.model.comparisons,
                                                              Comparison(name="birth", levels=levels, null_if_missing=("birth_date",)))))

    def name_level(label: str, after: str, normalize: tuple) -> Callable[[FSSpec], FSSpec]:
        """A name level `label` after level `after`: the person names equal once written with `normalize`."""
        new = Level(label=label, any_of=(("person_name", Comparator("exact", normalize=normalize)),))
        at = lambda c: [lv.label for lv in c.levels].index(after) + 1
        return lambda s: replace(s, model=replace(s.model, comparisons=tuple(
            replace(c, levels=(*c.levels[:at(c)], new, *c.levels[at(c):])) if c.name == "name" else c for c in s.model.comparisons)))

    def given_comparison(*tail: tuple) -> Callable[[FSSpec], FSSpec]:
        """The given name compared on its own, where both records hold one: the same, one edit apart, else. A household
        shares the family name, address and phone, which reach the line together; its members' given names differ.
        With `tail`, the end of the full name stands in where a record has no given name."""
        cond = lambda comp: (("given_name", replace(comp, normalize=FOLD)), *((("person_name", replace(comp, normalize=GIVEN_TAIL)),) if tail else ()))
        given = Comparison(name="given", null_if_missing=("given_name", *(("person_name",) if tail else ())), levels=(
            Level(label="exact", any_of=cond(Comparator("exact"))), Level(label="one edit", any_of=cond(Comparator("damerau_levenshtein", 1)))))
        return lambda s: replace(s, model=replace(s.model, comparisons=(*s.model.comparisons, given)))

    def optuna_suggestion(s: FSSpec) -> FSSpec:  # an Optuna study's suggestion (trial 12); passed adopt
        model = without_tf(s.model)
        for (comparison, label), threshold in {("name", "fold JW high"): 0.95, ("name", "fold JW low"): 0.75,
                                               ("company", "JW high"): 0.97, ("company", "JW low"): 0.80}.items():
            model = with_level(model, comparison, label, threshold=threshold)
        off = {"person_name", "company_name", "sn_person_name", "tfidf_company_name"}
        return replace(s, blockers=tuple(b for b in as_written if b.name not in off), model=model)

    return {
        "labels": lambda s: replace(s, model=replace(s.model, m_method="labels")),
        "no_term_frequency": lambda s: replace(s, model=without_tf(s.model)),
        "exact_keys_only": lambda s: replace(s, blockers=tuple(b for b in s.blockers if isinstance(b, KeyBlocker))),
        "levenshtein_names": lambda s: replace(s, model=with_level(with_level(s.model, "name", "fold JW high", function="levenshtein",
                                                                              threshold=1), "name", "fold JW low", function="levenshtein", threshold=2)),
        "optuna_suggestion": optuna_suggestion,
        "u_from_1e6_pairs": lambda s: replace(s, model=replace(s.model, u_max_pairs=1e6)),  # u-sampling ≈ 6× cheaper
        "compound_phone_keys": lambda s: replace(s, blockers=tuple(b for b in s.blockers if b.name != "phone") + tuple(
            pool[n] for n in ("phone_prefecture", "phone_postal_area", "phone_name_initial"))),
        "sorted_names_for_tfidf": lambda s: replace(s, blockers=tuple(b for b in s.blockers if not isinstance(b, TfidfNeighbours)) + tuple(
            pool[n] for n in ("sn_person_name", "sn_person_name_reversed") if pool[n] not in s.blockers)),
        "name_keys": lambda s: replace(s, blockers=s.blockers + tuple(pool[n] for n in NAME_KEYS if pool[n] not in s.blockers)),
        # the address alone grows like N² (about 5 pairs per record at 10⁶); the address with the phone, the name's first
        # letter or the given name finds the same potential matches, linearly
        "bounded_address_keys": lambda s: replace(s, blockers=tuple(b for b in s.blockers if b.name not in ("address", "address_code"))
                                                  + tuple(pool[n] for n in ADDRESS_KEYS if pool[n] not in s.blockers)),
        # once every potential match shares a key (window_only), a window adds only pairs below the threshold, 3 per record each
        "no_sorted_windows": lambda s: replace(s, blockers=tuple(b for b in s.blockers if not isinstance(b, SortedNeighbourhood))),
        "bridge_rule_clusters": lambda s: replace(s, bridge=True),  # stage 2 may join two clusters the rules formed
        "u_from_scored_file": lambda s: replace(s, model=replace(s.model, u_from_scored=True)),  # calibrated at every file size
        # exact, where a 10⁷-pair sample can't see an agreement rarer than one in 10⁹ pairs (exact name, CIF ID in a big file)
        "u_exact_by_counts": lambda s: replace(s, model=replace(s.model, u_exact_by_counts=True)),
        "cif_one_digit_off": cif_one_digit_off,
        "graded_address": graded_address,
        "birth_date": birth_date,
        # the keys those levels need: a pair they lift over the threshold must share a key, or it is never compared
        "cif_deletion_key": with_key("cif_deletions"),
        "birth_date_key": with_key("birth_date"),
        "given_name_phone_key": with_key("given_name_phone"),
        "birth_date_deletion_key": with_key("birth_date_deletions_prefecture"),
        # what the keys miss most: one name, its long vowel written another way, in another postal area; a married
        # name, its given name kept beside the phone, postal code or area that stay
        "name_reading_key": with_key("name_reading"),
        "given_tail_keys": lambda s: with_key("postal_area_given_tail")(with_key("postal_given_tail")(with_key("phone_given_tail")(s))),
        # the pairs those keys list, scored as strangers: one name, its long vowel written another way; a married name
        "same_reading_level": name_level("same reading", "fold exact", READING),
        "same_given_tail_level": name_level("same given name", "given name", GIVEN_TAIL),
        "given_comparison": given_comparison(),
        "given_or_tail_comparison": given_comparison(GIVEN_TAIL),
        # a household shares address and phone, which alone reach the threshold: without a name compared, people decide
        "name_needed": lambda s: replace(s, needs=("name", "company")),
        # one edit apart, counted exactly through the values' one-deletion keys: a 10⁷-pair sample sees about one CIF
        # typo pair, none in a big file; cif, phone and birth need no sample then. Increments count it again, O(U·L)
        "u_near_by_keys": lambda s: replace(s, model=replace(s.model, u_near_by_keys=True)),
        # with u_from_scored, the fit's u feed only EM: 10⁶ pairs do there, the scores keep u_max_pairs
        "fit_u_from_1e6_pairs": lambda s: replace(s, model=replace(s.model, fit_u_max_pairs=1e6)),
        # never reached in the sample or in EM (0 bits), yet a second Jaro–Winkler call on every company pair
        "company_without_jw_high": lambda s: replace(s, model=replace(s.model, comparisons=tuple(
            replace(c, levels=tuple(lv for lv in c.levels if lv.label != "JW high")) if c.name == "company" else c
            for c in s.model.comparisons))),
    }


FS_DECISIONS = (("no_term_frequency", "better"), ("exact_keys_only", "cheaper"), ("optuna_suggestion", "better"),
                ("u_from_1e6_pairs", "cheaper"), ("compound_phone_keys", "cheaper"), ("sorted_names_for_tfidf", "cheaper"),
                ("name_keys", "safer"), ("bounded_address_keys", "cheaper"), ("no_sorted_windows", "cheaper"), ("bridge_rule_clusters", "better"), ("u_from_scored_file", "chosen"),
                ("u_exact_by_counts", "chosen"), ("cif_one_digit_off", "better"),
                ("cif_deletion_key", "safer"), ("graded_address", "better"), ("birth_date", "better"),
                ("birth_date_key", "safer"), ("given_name_phone_key", "safer"), ("birth_date_deletion_key", "safer"),
                ("u_near_by_keys", "chosen"), ("fit_u_from_1e6_pairs", "cheaper"), ("company_without_jw_high", "cheaper"),
                ("name_needed", "chosen"),  # the owner's call: a pair with no name compared goes to people, whatever its score
                ("name_reading_key", "safer"), ("given_tail_keys", "safer"), ("same_reading_level", "better"), ("same_given_tail_level", "better"),
                ("given_comparison", "better"), ("given_or_tail_comparison", "better"))


def fs_tune(optuna_dir: Path) -> FSTune:
    return FSTune(
        toggle_blockers=("person_name", "company_name", "sn_person_name", "sn_person_name_reversed", "sn_company_name"),
        m_methods=("em", "labels"),
        tf_options=(True, False),
        level_thresholds={("name", "fold JW high"): (0.88, 0.97, 0.01), ("name", "fold JW low"): (0.75, 0.90, 0.01),
                          ("company", "JW high"): (0.88, 0.97, 0.01), ("company", "JW low"): (0.75, 0.90, 0.01)},
        n_trials=30, seed=0,
        enabled=False,  # as rules_tune
        storage_path=optuna_dir / "probabilistic_matching.db", study_prefix="probabilistic",
        dashboard_host="127.0.0.1", dashboard_port=8081,
    )
