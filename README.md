# Nayose — Lean 4 core

```bash
lake build                    # library + export exe
lake exe export rules.json    # the table Python must evaluate
lake env lean Tests.lean      # the plan's evaluation table, as #guard checks
```

## What is proven

No `sorry`; only `propext` and `Quot.sound`.

| Theorem | File | Content |
| --- | --- | --- |
| `safe_indep_of_weights` | `Rules.lean` | T1 — fitted weights cannot move a pair into SAFE |
| `tier_safe_iff` | `Rules.lean` | SAFE holds exactly when no veto fires and a SAFE rule holds |
| `veto_blocks_safe` | `Rules.lean` | T2 — any veto present means never SAFE |
| `atom_missing`, `safe_person_needs_dob` | `Rules.lean` | T3 — MISSING never agrees; a person SAFE has an exact birth date |
| `review_mono` | `Rules.lean` | T4 in its true form — improving a field can cost SAFE but never review |
| `safe_has_corroboration` | `Rules.lean` | T5 — every SAFE pair has a shared CIF, identifier or household |
| `needs_holds` | `Rules.lean` | the link between the rule data and its required fields |
| `safe_shares_corroboration_key` | `Compare.lean` | T6 — a SAFE pair always shares a blocking key |

`Rules.lean` is the table; `tier` reads it; the proofs read the same list the
runner reads. `safe_person_rules_need_dob` and `safe_rules_force_corroboration`
are `decide` checks over that data, so a bad rule edit fails the build.

## Not proven, by design

- Jaro-Winkler, TSV parsing, EM, and the union-find loop. The plan tests these.
- Every level except `cif` / `ident` / `household` is supplied by the Python
  runner through `profileOf`'s `other` function.
- Half-width kana are assumed already folded (NFKC upstream); the level `LOOSE`
  carries the long-vowel spelling.
- T7 (fold idempotence) and T8 (chain merge) are not written yet.

## Layout

| Path | Content |
| --- | --- |
| `Nayose/Rules.lean` | levels, profile, rule and veto data, `tier`, T1–T5 |
| `Nayose/Compare.lean` | corroboration levels from records, keys, T6 |
| `Export.lean` | `rules.json` |
| `Tests.lean` | the plan's 13-case table as `#guard`, plus axiom prints |
