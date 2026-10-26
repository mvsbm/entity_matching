/-
  The plan's own evaluation table, at the level of tiers. Each `#guard` is one
  row: if a rule edit changes a tier, this file stops compiling.

  Levels: kana_full 0-5, kana_sur/giv 0-4, kanji_full 0-4, dob 0-3, gender 0-2,
  cif 0-2, ident 0-4, household 0-2, age 0-2, org_name 0-4, org_form 0-2.
-/

import Nayose.Rules
import Nayose.Compare
import Nayose.Normalize

open Nayose Field

def prof (kind : Kind) (fs : List (Field × Nat)) : Profile :=
  { kind := kind
    level := fun f => (fs.find? (·.1 == f)).map (·.2) |>.getD 0 }

-- T1 / T2 / T3 / T5 / T6 rest on nothing but these definitions.
#print axioms Nayose.tier_safe_iff
#print axioms Nayose.veto_blocks_safe
#print axioms Nayose.safe_person_needs_dob
#print axioms Nayose.safe_has_corroboration
#print axioms Nayose.review_mono
#print axioms Nayose.safe_shares_corroboration_key

-- Duplicates the plan says must be SAFE -------------------------------------

-- Exact duplicate, same CIF
#guard (prof .person [(kanaFull, 5), (dob, 3), (cif, 2)]).tier == .safe
-- Half-width kana + kanji variant, same CIF (normalization is upstream; levels equal)
#guard (prof .person [(kanaFull, 5), (kanjiFull, 3), (dob, 3), (cif, 2)]).tier == .safe
-- Long-vowel spelling, same household
#guard (prof .person [(kanaFull, 4), (dob, 3), (household, 2)]).tier == .safe
-- Org (株) vs 株式会社, same CIF
#guard (prof .org [(orgName, 4), (cif, 2)]).tier == .safe
-- Chain link with kanji missing
#guard (prof .person [(kanaFull, 5), (dob, 3), (cif, 2)]).tier == .safe
-- S2: unique identifier, any birth-date NEAR, one name half loose
#guard (prof .person [(ident, 4), (dob, 3), (kanaSur, 3)]).tier == .safe

-- Duplicates the plan says go to review ------------------------------------

-- Birth-date typo
#guard (prof .person [(kanaFull, 5), (dob, 2)]).tier == .candidate
-- Reversed surname/given
#guard (prof .person [(kanaFull, 3), (dob, 3)]).tier == .candidate
-- Surname change, same household
#guard (prof .person [(kanaGiv, 3), (dob, 3), (household, 2)]).tier == .candidate
-- Org 株式会社X vs X株式会社, different CIF
#guard (prof .org [(orgName, 3), (cif, 1)]).tier == .candidate
-- Chain ends 佐藤博 / 佐藤宏: S1 would hold, the kanji veto sends it to review
#guard (prof .person [(kanaFull, 5), (dob, 3), (cif, 2), (kanjiFull, 1)]).tier == .candidate
-- Kanji homonym, same kana and birth date, no corroboration
#guard (prof .person [(kanaFull, 5), (dob, 3), (kanjiFull, 2)]).tier == .candidate
-- Twin: same household, surname, birth date, differing kanji
#guard (prof .person [(kanaFull, 5), (kanaSur, 3), (dob, 3), (household, 2),
                      (kanjiFull, 1)]).tier == .candidate

-- Look-alikes the plan says must not come back -----------------------------

-- Same-name parent, same household, different given name and birth date
#guard (prof .person [(kanaFull, 1), (kanaGiv, 1), (dob, 1), (household, 2),
                      (kanjiFull, 1)]).tier == .none
-- Persons never match orgs, even with identical levels
#guard (prof .person [(orgName, 4), (cif, 2)]).tier == .none
#guard (prof .org [(kanaFull, 5), (dob, 3), (cif, 2)]).tier == .none
-- Name and birth date agree, but nothing corroborates: not SAFE
#guard (prof .person [(kanaFull, 5), (dob, 3)]).tier == .candidate

-- Normalization (T7 is proved in Nayose/Normalize.lean; these fix the data) -----

#print axioms Nayose.strict_idem
#print axioms Nayose.loose_idem
#print axioms Nayose.kanjiNorm_idem

-- Strict: hiragana to katakana, separators out, small kana and vowels untouched
#guard strict "さとう たろう" == "サトウタロウ"
#guard strict "サトウ・タロウ" == "サトウタロウ"
#guard strict "ゆーこ" == "ユーコ"
#guard strict "ヴ" == "ヴ"

-- Loose: small kana enlarged, voiced folded, long vowels spelled out
#guard loose "ゆーこ" == "ユウコ"
#guard loose "けーこ" == "ケイコ"
#guard loose "おーさま" == "オウサマ"
#guard loose "コーヒー" == "コウヒイ"
#guard loose "ヴ" == "ブ"
#guard loose "ヂヅヲ" == "ジズオ"
#guard loose "きゃく" == "キヤク"
-- ゖ is small ケ: one pass must reach ケ, not stop at ヶ
#guard loose "ゖ" == "ケ"
#guard loose "ゎ" == "ワ"
-- a mark with nothing to lengthen is dropped
#guard loose "ー" == ""

-- Kanji variants (starter list)
#guard kanjiNorm "髙橋" == "高橋"
#guard kanjiNorm "澤田" == "沢田"

-- T7 as a property, on the shapes that actually occur
#guard strict (strict "さとう たろう") == strict "さとう たろう"
#guard loose (loose "ゆーこ") == loose "ゆーこ"
#guard loose (loose "ゖゃー・ヂ") == loose "ゖゃー・ヂ"
#guard kanjiNorm (kanjiNorm "髙﨑邊澤") == kanjiNorm "髙﨑邊澤"
