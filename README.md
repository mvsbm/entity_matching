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

## Status against the pipeline

| Stage | In Lean | Proofs |
| --- | --- | --- |
| read Parquet → TSV | no (Python, by plan) | — |
| normalize | `Nayose/Normalize.lean`: kana strict, kana loose, kanji variants | T7 ✓ |
| levels | 3 of 12 (`cif`, `ident`, `household`) | T6 on those |
| block | corroboration keys only | T6 |
| score | no | — |
| decide | rules, vetoes, `tier` | T1, T2, T3, T5, T4-review |
| cluster | no | — |
| output | no | — |

## Definition of done

The binary's `main` calls one function `run`. Every theorem is about `run` or a
pure helper it calls — not about a test-only copy. Two end-to-end theorems close
the pipeline:

- **E1 `safe_pairs_returned`** — if the rules make a pair SAFE, the pair is in
  `run`'s output. Chain: rules → corroboration (T5) → a shared key (T6) → the
  key is never stoplisted or truncated (cap lemma) → the pair is generated →
  dedup keeps it → the writer emits it.
- **E2 `merged_groups_consistent`** — the union-find only merges groups whose
  members do not conflict on gender, birth date, given name, kanji or a unique
  identifier (T8), and a refused merge is emitted as CANDIDATE `CHAIN_CONFLICT`.

Milestones, in order, each one green before the next:

| # | Content | Acceptance |
| --- | --- | --- |
| M1 | normalize (done) | `strict_idem`, `loose_idem`, `kanjiNorm_idem` + `#guard` examples |
| M2 | all 12 level functions on `Norm`; delete `profileOf`'s `other` | T6 restated with no assumption; levels ≤ `arity` proved |
| M3 | `decide` returns `{tier, rule, reasons}`; C6 threshold folded in | `Tests.lean` checks rule names and reason codes |
| M4 | keys B1–B9, sorted neighbourhood, cap, stoplist blanking, dedup | E1 |
| M5 | Fellegi-Sunter with integer centibits + monotone-weight check | weight check is a build-time `decide` over the level order |
| M6 | union-find, strongest-first, refused merge → CANDIDATE | E2 |
| M7 | TSV in/out, report, `run` | the binary and the theorems name the same function |

Trust ledger — what stays unproven, and how each is checked:

| Assumption | Why it stays | Checked by |
| --- | --- | --- |
| Unicode NFKC | standards conformance, not a decision | Python `unicodedata`, version pinned |
| Jaro-Winkler | float distance, not part of the SAFE rules | differential test vs Python on name pairs |
| EM for `m` | fitted statistics | synthetic run + the weight check |
| rule/variant/vowel tables | they encode the business rules | `#guard` cases, review samples, `decide` invariants |
| TSV parsing | Lean has no CSV reader | round-trip test on the 1.2M export |

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
