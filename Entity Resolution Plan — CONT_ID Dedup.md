# Entity Resolution Plan — CONT\_ID Dedup

Oct 26, 2026 · @Marvin Ma

## Goal and guarantees

The pipeline compares the 1.2M CONT\_IDs and outputs pairs that are likely the same person or organization, each with a tier, a score and reasons.

- **SAFE**: pairs that can be merged. Target is zero wrong merges, and every SAFE decision comes from rules proven in Lean 4.
- **CANDIDATE**: a high-recall list for human review, ranked by score, so likely duplicates aren't missed.

**What Lean guarantees:** the rules do exactly what the spec says, for every possible input. For example, a pair with two different valid birth dates is never SAFE, a missing value never counts as agreement, and blocking never drops a pair the SAFE rules would accept.

**What Lean can't guarantee:** that the spec matches reality. Whether two records really are one person is measured by reviewing samples (see Evaluation).

## State of the art

Current entity resolution runs in four stages: blocking, pairwise matching, clustering and evaluation ([survey, ACM 2026](https://www.citedrive.com/en/discovery/a-comprehensive-survey-of-deep-learning-for-entity-resolution/)). The best tool at each stage depends on whether you have labels and can use LLMs; here you have neither, and you want proofs.

| Stage | Best practice now | Used here |
| --- | --- | --- |
| Blocking | Union of exact keys plus top-k retrieval on character 3-grams (TF-IDF/BM25). [Sparkly](https://www.vldb.org/pvldb/vol16/p1507-paulsen.pdf) beat deep-learning blockers on all 15 benchmark datasets and blocked 26M records in about 2 hours. | Corroboration keys (CIF, ID, household) guarantee SAFE recall; name keys and sorted-neighbourhood passes add CANDIDATE recall. 3-gram top-k is a later add-on. |
| Matching | Fellegi-Sunter probabilistic model with EM and term-frequency adjustment. [Splink](https://www.gov.uk/government/publications/joined-up-data-in-government-the-future-of-data-linking-methods/splink-mojs-open-source-library-for-probabilistic-record-linkage-at-scale), built on it, links about 15M records in under an hour at the UK Ministry of Justice. With labels, Transformer matchers lead; LLM matchers are emerging. | Fellegi-Sunter + EM for scores; SAFE comes from proven rules. A supervised matcher once reviewed pairs exist. |
| Clustering | Connected components with cannot-link constraints, or correlation clustering. | Union-find that refuses any merge whose groups conflict, with the key lemma proven. |
| Evaluation | Clerical review samples and synthetic duplicates. | Same. |

The Lean layer is the unusual part: most pipelines test their rules, while this one proves them.

## Decisions so far

| Topic | Decision |
| --- | --- |
| Data | 1.2M rows (test), one row per CONT\_ID; phones, addresses and identifiers held as lists |
| Fields, phase 1 | CONT\_ID, PERSON\_ORG\_CODE, IDENTIFIER\_ID + ID\_TP\_CD, CIF\_ID, kanji and kana names, O\_PERSON\_NAME, GENDER\_TP\_CD, BIRTH\_DT, AGE, HOLDHOUSE\_ID, ORG\_NAME. Phones and addresses in phase 2 |
| Names | Kana is the primary key (more complete); kanji supports and can veto |
| O\_ columns | Original values before processing; used only when the processed value is empty |
| BIRTH\_DT | 19000101 means missing and never counts as agreement |
| AGE | Not derived from BIRTH\_DT; weak evidence in the score only |
| CIF\_ID | Customer key but unreliable: corroborates a name match, never enough alone, and a different CIF\_ID is not a veto |
| WINKEY | Internal job name; not used |
| Persons vs orgs | Never compared with each other |
| Error priority | Both: SAFE prevents wrong merges at all cost; CANDIDATE catches missed duplicates |
| Labels and AI | No labels yet; no LLM; embedding models allowed |
| Runtime | Lean 4 compiles to a standalone binary. If your policy allows running it on the data PC, the whole pipeline is Lean; otherwise Lean exports its decision table and Python/Polars runs it |
| Output | Pairs with tier, score and reason codes |

## Architecture

The whole pipeline is written in Lean 4 and compiles to one standalone binary. It needs no Lean install to run. If running that binary on the data PC isn't allowed, it exports the full decision table instead, and a Python/Polars runner looks rules up rather than re-implementing them.

&#91;embedded content: pipeline architecture · dev machine and data PC\]

Every step from normalization to output is Lean code; only reading Parquet is Polars, because Lean has no Parquet reader. Rules are data in `Rules.lean` and the proofs are about that same data, so there's no gap between what is proven and what runs.

## Normalization and comparison levels

Each field is cleaned once, then each pair gets one level per field. Level 0 always means MISSING (either side empty), and higher means more agreement. Because every field has 3–6 levels, the set of possible pair profiles is finite (about 1.2 million), which is what makes the rules checkable.

**Normalization**

- **Kana strict:** half-width → full-width katakana, voiced marks merged (ｶﾞ → ガ), hiragana → katakana, spaces and ・ removed.
- **Kana loose:** strict, plus small → large kana (ッ → ツ, ャ → ヤ), ヴ → ブ, ヂ → ジ, ヅ → ズ, ヲ → オ, and long vowels spelled out (ユーコ → ユウコ, ケーコ → ケイコ).
- **Kanji:** spaces removed, full-width ASCII folded, variant forms folded (髙 → 高, 﨑 → 崎, 邊 → 辺, 澤 → 沢). The starter table must be extended from a standard variant list.
- **Org names:** legal form removed and kept with its position, because 株式会社ABC and ABC株式会社 can be different companies (株式会社, ㈱, (株), 有限会社…).
- **BIRTH\_DT:** first 8 digits as yyyymmdd; 19000101 or an impossible date → missing.
- **Shared-value stoplist:** a CIF, ID or household value carried by more than B records is treated as missing (it's a placeholder, not an identifier).

**Levels**

| Field | Levels, low → high (0 = MISSING) |
| --- | --- |
| Kana full name | DIFF · CLOSE (Jaro-Winkler ≥ 0.92) · SWAPPED (surname/given reversed) · LOOSE · EXACT |
| Kana surname, kana given name | DIFF · CLOSE · LOOSE · EXACT |
| Kanji full name | DIFF · CLOSE · VARIANT · EXACT |
| Birth date | DIFF · NEAR (one-digit typo, day/month swap, or one day apart) · EXACT |
| Gender | DIFF · SAME |
| CIF\_ID | DIFF · SHARED |
| Identifier | CONFLICT (same unique type, different value) · NONE\_SHARED · SHARED\_OTHER · SHARED\_UNIQUE |
| Household | DIFF · SAME |
| Age | INCONSISTENT · CONSISTENT (within 2 years) |
| Org name | DIFF · CLOSE · NORMALIZED (legal form differs or missing) · EXACT (same name and same legal form in the same position) |
| Legal form | DIFF · SAME |

Thresholds (0.92, 2 years) are starting values, tuned in Evaluation.

## Blocking

Comparing every pair of 1.2M rows means about 7.2 × 10^11 comparisons, so only pairs that share a key are compared. Keys come in two groups with different jobs, and every key includes PERSON\_ORG\_CODE, so persons and orgs never meet.

| Key | Group | Catches |
| --- | --- | --- |
| B5 CIF\_ID value | Corroboration | Shared customer key |
| B6 Identifier (type + value) | Corroboration | Shared identifier |
| B7 HOLDHOUSE\_ID | Corroboration | Duplicates inside a household |
| B1 Kana full name (loose) | Name | Same name, any birth date |
| B2 Kana surname (loose) + birth date | Name | Given-name typos |
| B3 Kana given name (loose) + birth date | Name | Surname typos and surname changes |
| B4 Kanji full name (variant-folded) | Name | Missing or wrong kana |
| B8 Surname/given pair, sorted | Name | Surname and given name reversed |
| B9 Org name without legal form | Name | Org duplicates |
| Sorted neighbourhood (window 5) | Name | Typos that change the key: neighbours after sorting by loose name, then by reversed name |

**SAFE recall is guaranteed by the corroboration keys alone.** Every SAFE rule needs a shared CIF, identifier or household, and Lean proves that (theorem T6). Those blocks are never truncated (see the stoplist), so no SAFE pair can be missed.

**Name keys only add CANDIDATE recall.** A name block over the cap B (default 1,000) is skipped and logged, never silently cut.

**Embedding retrieval (optional).** Character 3-gram TF-IDF top-k neighbours, the Sparkly approach, can be added later in Python as another candidate source; it never affects SAFE.

## Decision rules

A pair is SAFE when a SAFE rule holds and no veto fires. It is a CANDIDATE when a candidate pattern holds or its score clears the threshold. Rules are written as data in `Rules.lean`, so the proofs read them directly.

**Vetoes** (any one blocks SAFE; the pair can still be a CANDIDATE):

- Birth date DIFF
- Gender DIFF
- Kana given name DIFF (protects parents/children and twins)
- Kanji full name CLOSE or DIFF (佐藤博 vs 佐藤宏 are both サトウ ヒロシ)
- Unique-type identifier CONFLICT
- Org legal form DIFF

**SAFE rules**

| Rule | Needs |
| --- | --- |
| S1 Person, name + birth date + corroboration | Kana full ≥ LOOSE (or surname and given both ≥ LOOSE), birth date EXACT, and one of: CIF SHARED, identifier SHARED, household SAME |
| S2 Person, unique identifier | Identifier SHARED\_UNIQUE, birth date EXACT, and kana surname or given ≥ LOOSE |
| S3 Org | Org name ≥ NORMALIZED with identifier SHARED\_UNIQUE, or org name EXACT with CIF SHARED |

Why S1 needs corroboration: about 40 people share each birth date in 1.2M rows, and kana merges different kanji. Name + birth date alone would pair some different people.

**CANDIDATE patterns**

| Pattern | Needs | Typical case |
| --- | --- | --- |
| C1 | Kana given ≥ LOOSE, birth date EXACT, corroboration | Surname change after marriage |
| C2 | Kana full ≥ LOOSE, birth date ≥ NEAR | Birth-date typo |
| C3 | Kana full ≥ CLOSE (includes SWAPPED), birth date EXACT | Name typo or reversed name |
| C4 | Org name ≥ CLOSE | Org name variant |
| C5 | A SAFE rule holds but a veto fired | Needs a human |
| C6 | Score ≥ threshold | Everything else likely |

Every pattern is "at least" shaped, so fixing a typo can never push a pair out of review (theorem T4).

**Chain check.** SAFE pairs can chain: A–B and B–C are SAFE, but A and C conflict (B has no kanji; A is 佐藤博, C is 佐藤宏). SAFE pairs are merged strongest first. A merge is refused when the two groups disagree on gender, given name, kanji, birth date or a unique identifier, and that pair is downgraded to CANDIDATE with reason CHAIN\_CONFLICT.

## What Lean 4 proves

Each line is a theorem over all inputs, not a test over samples.

| # | Theorem (in `Rules.lean`, `Compare.lean`, `Cluster.lean`) | Plain meaning |
| --- | --- | --- |
| T1 | `tier_safe_iff`, `safe_indep_of_weights` | SAFE depends only on the rules, never on the fitted weights or thresholds |
| T2 | `veto_blocks_safe` | Any veto present → never SAFE |
| T3 | `Atom.eval_missing`, `safe_person_needs_dob` | A MISSING field never satisfies a rule; a person SAFE always has an exact birth date |
| T4 | `tier_mono` | Moving any field toward agreement never lowers the tier (given weights that rise with agreement, checked at runtime) — proven as `review_mono`: an improved field can cost SAFE, because a newly populated kanji or given name can fire a veto, but it can never drop the pair out of review. `tier_mono` as written is false with vetoes; the review form is what the code needs. |
| T5 | `safe_has_corroboration` | Every SAFE pair has a shared CIF, identifier or household |
| T6 | `safe_shares_corroboration_key` | Restated on the actual records: a SAFE pair always shares a corroboration block key, so blocking can't miss it |
| T7 | `lookupD_idem` + table checks | Character folding is idempotent: folding twice equals folding once |
| T8 | `agrees_merge`, `agree_no_*_veto` | The chain check's merge test is sound: members of a merged group never veto each other on gender, birth date, given name or kanji (the unique-ID part is checked but not proven) |

**Not proven (tested instead):** TSV parsing, Jaro-Winkler, EM, the union-find loop around the T8 lemma, and the link from keys to buckets. These are short, and the synthetic-data run checks them end to end.

## Scoring without labels

CANDIDATE ranking uses a Fellegi-Sunter model fitted without labels, fitted separately for persons and orgs.

- **u** (how often unrelated pairs show each level) is measured on 1M random pairs.
- **m** (how often true matches show it) and the match rate λ come from EM over the profile counts of the blocked pairs.
- **Weight** of a level = log2(m/u), stored as integer centibits (100 = 1 bit), so the proofs can use integer arithmetic. MISSING weighs 0.
- **Term frequency:** agreeing on a rare surname, given name or org name earns a bonus over a common one (ワタヌキ beats サトウ). The bonus is never negative, which keeps T4 valid.
- **Output:** match weight = log2 prior odds + score, and probability = 1 / (1 + 2^−weight).

Before scoring, the pipeline forces each field's weights to rise with agreement and checks it; T4 assumes exactly this. The candidate threshold is set as a minimum probability (default 0.2).

## Output

One TSV of pairs (one row per pair, `cont_id_a` < `cont_id_b` by input order) plus a run report.

| Column | Content |
| --- | --- |
| cont\_id\_a, cont\_id\_b | The pair |
| person\_org\_code | Shared PERSON\_ORG\_CODE |
| tier | SAFE or CANDIDATE |
| rule | Rule or pattern that fired, e.g. S1\_KANA\_DOB\_CIF, C2\_KANA\_DOB\_NEAR, SCORE |
| match\_weight | log2 odds of a match |
| match\_probability | 0–1 |
| reasons | e.g. KANA\_FULL=EXACT, BIRTH\_DATE=EXACT, KANJI=VARIANT, CIF=SHARED, VETO\_GIVEN\_NAME\_DIFF, CHAIN\_CONFLICT |
| profile | Every field's level, for audit |

The run report lists pair counts by tier and rule, skipped oversized blocks, stoplisted values, fitted weights and the result of the weight check. Polars reads the TSV straight into Parquet.

## Evaluation without labels

All checks run on the data PC, so no data leaves it.

**Recall, from synthetic duplicates.** Copy a few thousand real records, apply realistic edits, insert them, and count how many come back as SAFE or CANDIDATE. The edits: kana typos, ー/ウ and small-kana variants, kanji variants, a one-digit birth-date typo, surname change, reversed names and blanked fields. Results are reported per edit type, so weak spots show.

**Precision, from a review sample.** Someone who knows the data reviews a stratified sample, e.g. 300 SAFE and 300 CANDIDATE pairs across score bands. Zero wrong merges in 300 SAFE pairs means the true error rate is below about 1% at 95% confidence (rule of three). Showing below 0.1% needs about 3,000.

**Coincidence estimate.** Count pairs that agree on kana full name and birth date but conflict on kanji. This is a floor on how often different people look alike on kana + date, and it shows why S1 needs corroboration.

The reviewed pairs become the first labeled set; later they tune thresholds and can train a supervised matcher.

## Synthetic test

A Python mirror of the Lean rules (rules only, no scoring) ran here on 25,359 synthetic records and found every planted duplicate, with zero wrong SAFE merges, even after chaining all SAFE pairs. The Lean binary itself has not run yet; once it compiles, `scripts/evaluate.py` runs the same check on its output.

| Case | Kind | SAFE | CANDIDATE | Not returned |
| --- | --- | --- | --- | --- |
| Exact duplicate, same CIF | Duplicate | 983 | 0 | 0 |
| Half-width kana + kanji variant, same CIF | Duplicate | 1,001 | 0 | 0 |
| Long-vowel spelling, same household | Duplicate | 582 | 0 | 0 |
| Org (株) vs 株式会社, same CIF | Duplicate | 7 | 0 | 0 |
| Birth-date typo | Duplicate | 0 | 630 | 0 |
| Reversed surname/given | Duplicate | 0 | 712 | 0 |
| Surname change, same household | Duplicate | 0 | 287 | 0 |
| Org 株式会社X vs X株式会社, different CIF | Duplicate | 0 | 7 | 0 |
| Chain link with kanji missing | Duplicate | 33 | 17 | 0 |
| Chain ends 佐藤博 / 佐藤宏 | Look-alike | 0 | 50 | 0 |
| Kanji homonym, same kana and birth date | Look-alike | 0 | 100 | 0 |
| Twin: same household, surname, birth date | Look-alike | 0 | 14 | 406 |
| Same-name parent, same household | Look-alike | 0 | 0 | 373 |

The 14 twins returned as CANDIDATE have given names that differ only in kanji (優子 / 裕子, both ユウコ); the kanji veto keeps them out of SAFE. In the chain case, the check keeps one link of each A–B–C chain and sends the other to review.

## Time complexity

Every one of the N = 1.2M records is read, normalized and indexed; only pair comparisons are pruned. Total cost is O(N log N + P), where P is the number of candidate pairs, and the block-size cap B keeps P near-linear in N.

| Step | Time | Memory | How it stays fast |
| --- | --- | --- | --- |
| Load + normalize | O(N·L) | O(N) | One pass; L = name length, about 10 characters |
| Build key index | O(N·K) expected | O(N·K) | Hash map key → row ids; K = keys per record, about 10 |
| Generate pairs from keys | O(Σ\|block\|²) ≤ O(N·K·B) | O(B) per record | Pairs streamed per record and de-duplicated locally; no global pair list |
| Sorted-neighbourhood pass | O(N log N + N·w) | O(N·w) | Two sorts (name, reversed name), window w ≈ 5 |
| Compare | O(P·L²) ≈ O(P) | O(1) per pair | Jaro-Winkler on short names; equality checks first |
| Decide tier | O(1) per pair | — | Rule lists are fixed and short |
| Fit u (random pairs) | O(R) | O(D) | R ≈ 1M random pairs, independent of P |
| EM for m | O(P) once, then O(I·D·F) | O(D) | Pairs are aggregated into D distinct profiles first; D is thousands, not millions |
| Score + write | O(P) | O(output) | Second streaming pass |
| Chain check | O(S log S + S log N) | O(N) | Union-find with union by size; S = SAFE pairs |

**Why the cap can't break SAFE.** A value shared by more than B records (a dummy CIF or ID, say) is treated as missing everywhere. So every corroboration block is at most B and never truncated, and every SAFE pair is still generated. Oversized name blocks are skipped and logged; they only affect the CANDIDATE tier.

**Parallelism.** Both passes are independent per record, so they split by record range across cores (Lean `Task.spawn`, `--threads`).

## Phases

1. ~~**Compile the Lean project**~~ — **done**: `lake build` is green on Lean 4.35.0. T1–T5 and T6 are proven, the rule table is exported to `rules.json`, and `Tests.lean` holds the evaluation table below as `#guard` checks. T7 and T8 are not written yet. (Building it already caught one rule-transcription bug: S1's kana requirement was encoded as two required groups instead of one with two alternatives.)
2. **Profile (data PC)** — aggregate stats only: null and placeholder rates, ID\_TP\_CD values and how often each identifier is shared, CIF and household sharing, gender codes, block sizes. Settles the open items.
3. **Run on synthetic data** — a generator with planted duplicates and look-alikes checks the whole pipeline before it touches real data.
4. **Run on the 1.2M test set** — export Parquet → TSV with Polars, run `nayose run`, read the report.
5. **Evaluate and tune** — synthetic recall, review sample, thresholds. Rule changes go back through Lean.
6. **Phase 2 fields** — phones and addresses (STD\_ADDRESS, POST\_CD, BARCODE). They add corroboration for persons and are the main evidence for orgs.

## Open items

| Item | Default until answered | Settled by |
| --- | --- | --- |
| IDENTIFIER\_ID may be a surrogate key (one per identifier row, never shared), as in IBM MDM, where the actual number sits in another column | Used as given; if profiling shows no value is shared by two CONT\_IDs, the ID value column must be added | Profiling, then you |
| Which ID\_TP\_CD types are one-per-person | None marked unique, so S2 never fires | Profiling shows sharing per type; you name the types (`--unique-id-types`) |
| Which PERSON\_ORG\_CODE value means org | Guessed per record (org name filled, person names empty) | You (`--org-codes`) |
| GENDER\_TP\_CD codes meaning unknown | Only empty is unknown; an unknown code vs M/F vetoes, which errs safe | Profiling, then you |
| Same household, different given name | Veto; never SAFE | Your call |
| Surname change after marriage | SAFE only with a unique identifier (S2); otherwise CANDIDATE (C1) | Your call |
| Person ↔ org matching | Never (assumed from your answers) | Confirm |
| NYS\_CNV\_P\_NAME / NYS\_CNV\_O\_NAME | Not used in phase 1 | Profiling of character patterns |
| Running a compiled binary on the data PC | Assumed not allowed; Python runs the exported table | You |
| Who reviews sample pairs | — | You |
