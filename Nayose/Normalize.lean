/-
  Normalization: the step that gives the levels their meaning.

  Every fold is a character table applied by `step`. T7 is proved once for any
  table whose images are their own images (`step_idem`), then discharged per
  table with `decide` — so editing a table cannot silently break idempotence.
  That check already caught a real bug: with hiragana and small-kana as separate
  tables, ゖ → ヶ → ケ needs two passes, so the loose table composes them.

  Unicode NFKC (half-width katakana, full-width ASCII) is Python's job: it is a
  standards conformance question, not a matching decision.
-/

namespace Nayose

/-- Spaces (both widths) and the kana middle dot are removed before any fold. -/
def keepChar (c : Char) : Bool :=
  !(c == ' ' || c == '　' || c == '・' || c == '･')

/-- First matching table entry wins; anything else maps to itself. -/
def step (tbl : List (Char × Char)) (c : Char) : Char :=
  match tbl.find? (fun p => p.1 == c) with
  | some p => p.2
  | none => c

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

/-- Hiragana → katakana, plus the two iteration marks. -/
def hiraTable : List (Char × Char) :=
  (List.range 0x56).map (fun i => (Char.ofNat (0x3041 + i), Char.ofNat (0x30A1 + i)))
  ++ [('ゝ', 'ヽ'), ('ゞ', 'ヾ')]

/-- Small kana → large kana (loose only). -/
def smallTable : List (Char × Char) :=
  [('ァ', 'ア'), ('ィ', 'イ'), ('ゥ', 'ウ'), ('ェ', 'エ'), ('ォ', 'オ')
  , ('ッ', 'ツ'), ('ャ', 'ヤ'), ('ュ', 'ユ'), ('ョ', 'ヨ'), ('ヮ', 'ワ')
  , ('ヵ', 'カ'), ('ヶ', 'ケ')]

/-- Voiced kana the plan folds onto their unvoiced neighbours (loose only). -/
def voicedTable : List (Char × Char) :=
  [('ヴ', 'ブ'), ('ヂ', 'ジ'), ('ヅ', 'ズ'), ('ヲ', 'オ')]

def smallVoiced : List (Char × Char) := smallTable ++ voicedTable

/-- Loose = hiragana → large katakana, composed through the small-kana fold. -/
def looseTable : List (Char × Char) :=
  hiraTable.map (fun p => (p.1, step smallVoiced p.2)) ++ smallVoiced

/-- Starter variant list; extend from the standard variant table after profiling. -/
def kanjiTable : List (Char × Char) :=
  [('髙', '高'), ('﨑', '崎'), ('邊', '辺'), ('澤', '沢')]

/-- Kana → the vowel a long-vowel mark takes after it (ケー is written ケイ). -/
def vowels : List (Char × Char) :=
  [('ア', 'ア'), ('イ', 'イ'), ('ウ', 'ウ'), ('エ', 'イ'), ('オ', 'ウ')
  , ('カ', 'ア'), ('キ', 'イ'), ('ク', 'ウ'), ('ケ', 'イ'), ('コ', 'ウ')
  , ('サ', 'ア'), ('シ', 'イ'), ('ス', 'ウ'), ('セ', 'イ'), ('ソ', 'ウ')
  , ('タ', 'ア'), ('チ', 'イ'), ('ツ', 'ウ'), ('テ', 'イ'), ('ト', 'ウ')
  , ('ナ', 'ア'), ('ニ', 'イ'), ('ヌ', 'ウ'), ('ネ', 'イ'), ('ノ', 'ウ')
  , ('ハ', 'ア'), ('ヒ', 'イ'), ('フ', 'ウ'), ('ヘ', 'イ'), ('ホ', 'ウ')
  , ('マ', 'ア'), ('ミ', 'イ'), ('ム', 'ウ'), ('メ', 'イ'), ('モ', 'ウ')
  , ('ヤ', 'ア'), ('ユ', 'ウ'), ('ヨ', 'オ')
  , ('ラ', 'ア'), ('リ', 'イ'), ('ル', 'ウ'), ('レ', 'イ'), ('ロ', 'ウ')
  , ('ワ', 'ア'), ('ヲ', 'オ')
  , ('ガ', 'ア'), ('ギ', 'イ'), ('グ', 'ウ'), ('ゲ', 'イ'), ('ゴ', 'ウ')
  , ('ザ', 'ア'), ('ジ', 'イ'), ('ズ', 'ウ'), ('ゼ', 'イ'), ('ゾ', 'ウ')
  , ('ダ', 'ア'), ('ヂ', 'イ'), ('ヅ', 'ウ'), ('デ', 'イ'), ('ド', 'ウ')
  , ('バ', 'ア'), ('ビ', 'イ'), ('ブ', 'ウ'), ('ベ', 'イ'), ('ボ', 'ウ')
  , ('パ', 'ア'), ('ピ', 'イ'), ('プ', 'ウ'), ('ペ', 'イ'), ('ポ', 'ウ')]

def vowelOf (c : Char) : Option Char := (vowels.find? (fun p => p.1 == c)).map (·.2)

-- ---------------------------------------------------------------------------
-- T7: one table lookup, idempotent once per table
-- ---------------------------------------------------------------------------

theorem step_eq_self_or_image (tbl : List (Char × Char)) (c : Char) :
    step tbl c = c ∨ ∃ p ∈ tbl, step tbl c = p.2 := by
  cases hf : tbl.find? (fun p => p.1 == c) with
  | none => exact Or.inl (by simp [step, hf])
  | some p =>
      exact Or.inr ⟨p, List.mem_of_find?_eq_some hf, by simp [step, hf]⟩

theorem step_idem (tbl : List (Char × Char))
    (h : tbl.all (fun p => decide (step tbl p.2 = p.2)) = true) (c : Char) :
    step tbl (step tbl c) = step tbl c := by
  rcases step_eq_self_or_image tbl c with hc | ⟨p, hp, hval⟩
  · rw [hc, hc]
  · rw [hval]
    exact of_decide_eq_true (List.all_eq_true.mp h p hp)

theorem step_kept (tbl : List (Char × Char))
    (h : tbl.all (fun p => decide (keepChar p.2 = true)) = true)
    (c : Char) (hc : keepChar c = true) : keepChar (step tbl c) = true := by
  rcases step_eq_self_or_image tbl c with he | ⟨p, hp, hval⟩
  · rw [he]; exact hc
  · rw [hval]; exact of_decide_eq_true (List.all_eq_true.mp h p hp)

theorem step_ne_mark (tbl : List (Char × Char))
    (h : tbl.all (fun p => decide (p.2 ≠ 'ー')) = true)
    (c : Char) (hc : c ≠ 'ー') : step tbl c ≠ 'ー' := by
  rcases step_eq_self_or_image tbl c with he | ⟨p, hp, hval⟩
  · rw [he]; exact hc
  · rw [hval]; exact of_decide_eq_true (List.all_eq_true.mp h p hp)

theorem hira_step : ∀ c, step hiraTable (step hiraTable c) = step hiraTable c :=
  step_idem hiraTable (by decide)

theorem hira_kept : ∀ c, keepChar c = true → keepChar (step hiraTable c) = true :=
  step_kept hiraTable (by decide)

theorem loose_kept : ∀ c, keepChar c = true → keepChar (step looseTable c) = true :=
  step_kept looseTable (by decide)

theorem kanji_kept : ∀ c, keepChar c = true → keepChar (step kanjiTable c) = true :=
  step_kept kanjiTable (by decide)

theorem loose_step : ∀ c, step looseTable (step looseTable c) = step looseTable c :=
  step_idem looseTable (by decide)

theorem kanji_step : ∀ c, step kanjiTable (step kanjiTable c) = step kanjiTable c :=
  step_idem kanjiTable (by decide)

-- ---------------------------------------------------------------------------
-- Folding a string
-- ---------------------------------------------------------------------------

def foldList (tbl : List (Char × Char)) : List Char → List Char
  | [] => []
  | c :: cs => if keepChar c then step tbl c :: foldList tbl cs else foldList tbl cs

theorem foldList_fixed (tbl : List (Char × Char))
    (hstep : ∀ c, step tbl (step tbl c) = step tbl c)
    (hkeep : ∀ c, keepChar c = true → keepChar (step tbl c) = true) :
    ∀ s : List Char, ∀ c ∈ foldList tbl s, keepChar c = true ∧ step tbl c = c := by
  intro s
  induction s with
  | nil => intro c hc; cases hc
  | cons x xs ih =>
      intro c hc
      by_cases hx : keepChar x = true
      · simp only [foldList, hx, if_true, List.mem_cons] at hc
        rcases hc with rfl | hc
        · exact ⟨hkeep x hx, hstep x⟩
        · exact ih c hc
      · simp only [foldList, hx, if_false] at hc
        exact ih c hc

theorem foldList_of_fixed (tbl : List (Char × Char)) :
    ∀ s : List Char, (∀ c ∈ s, keepChar c = true ∧ step tbl c = c) →
      foldList tbl s = s := by
  intro s
  induction s with
  | nil => intro _; rfl
  | cons x xs ih =>
      intro h
      have hx := h x (by simp)
      have hxs : ∀ c ∈ xs, keepChar c = true ∧ step tbl c = c :=
        fun c hc => h c (by simp [hc])
      simp only [foldList, hx.1, if_true, hx.2]
      rw [ih hxs]

/-- T7: folding twice is folding once. -/
theorem foldList_idem (tbl : List (Char × Char))
    (hstep : ∀ c, step tbl (step tbl c) = step tbl c)
    (hkeep : ∀ c, keepChar c = true → keepChar (step tbl c) = true)
    (s : List Char) : foldList tbl (foldList tbl s) = foldList tbl s :=
  foldList_of_fixed tbl _ (foldList_fixed tbl hstep hkeep s)

def strict (s : String) : String := String.ofList (foldList hiraTable s.toList)

def kanjiNorm (s : String) : String := String.ofList (foldList kanjiTable s.toList)

theorem strict_idem (s : String) : strict (strict s) = strict s := by
  unfold strict
  rw [String.toList_ofList, foldList_idem hiraTable hira_step hira_kept]

theorem kanjiNorm_idem (s : String) : kanjiNorm (kanjiNorm s) = kanjiNorm s := by
  unfold kanjiNorm
  rw [String.toList_ofList, foldList_idem kanjiTable kanji_step kanji_kept]

-- ---------------------------------------------------------------------------
-- Loose fold: separators out, small kana enlarged, long vowels spelled out
-- ---------------------------------------------------------------------------

theorem vowel_spec {p v : Char} (h : vowelOf p = some v) : ∃ q ∈ vowels, q.2 = v := by
  unfold vowelOf at h
  cases hf : vowels.find? (fun q => q.1 == p) with
  | none => simp [hf] at h
  | some q =>
      have hqv : q.2 = v := by simpa [hf] using h
      exact ⟨q, List.mem_of_find?_eq_some hf, hqv⟩

theorem vowel_kept {p v : Char} (h : vowelOf p = some v) : keepChar v = true := by
  obtain ⟨q, hq, rfl⟩ := vowel_spec h
  exact of_decide_eq_true (List.all_eq_true.mp (by decide : vowels.all
    (fun q => decide (keepChar q.2 = true)) = true) q hq)

theorem vowel_ne_mark {p v : Char} (h : vowelOf p = some v) : v ≠ 'ー' := by
  obtain ⟨q, hq, rfl⟩ := vowel_spec h
  exact of_decide_eq_true (List.all_eq_true.mp (by decide : vowels.all
    (fun q => decide (q.2 ≠ 'ー')) = true) q hq)

theorem vowel_fixed {p v : Char} (h : vowelOf p = some v) : step looseTable v = v := by
  obtain ⟨q, hq, rfl⟩ := vowel_spec h
  exact of_decide_eq_true (List.all_eq_true.mp (by decide : vowels.all
    (fun q => decide (step looseTable q.2 = q.2)) = true) q hq)

theorem loose_mark (c : Char) (h : c ≠ 'ー') : step looseTable c ≠ 'ー' :=
  step_ne_mark looseTable (by decide) c h

def loosePg (prev : Option Char) : List Char → List Char
  | [] => []
  | c :: cs =>
      if keepChar c then
        if c = 'ー' then
          match prev.bind vowelOf with
          | some v => v :: loosePg (some v) cs
          | none => loosePg prev cs
        else
          let d := step looseTable c
          d :: loosePg (some d) cs
      else loosePg prev cs

theorem loosePg_fixed (s : List Char) (prev : Option Char) :
    ∀ c ∈ loosePg prev s, keepChar c = true ∧ c ≠ 'ー' ∧ step looseTable c = c := by
  induction s generalizing prev with
  | nil => intro c hc; cases hc
  | cons x xs ih =>
      intro c hc
      by_cases hk : keepChar x = true
      · by_cases hm : x = 'ー'
        · subst hm
          cases hb : prev.bind vowelOf with
          | none =>
              have hstep : loosePg prev ('ー' :: xs) = loosePg prev xs := by
                simp [loosePg, hk, hb]
              rw [hstep] at hc
              exact ih prev c hc
          | some v =>
              have hstep : loosePg prev ('ー' :: xs) = v :: loosePg (some v) xs := by
                simp [loosePg, hk, hb]
              rw [hstep] at hc
              cases hp : prev with
              | none => simp [hp] at hb
              | some p =>
                  have hv : vowelOf p = some v := by simpa [hp] using hb
                  rcases List.mem_cons.mp hc with hcv | hc'
                  · subst hcv
                    exact ⟨vowel_kept hv, vowel_ne_mark hv, vowel_fixed hv⟩
                  · exact ih (some v) c hc'
        · have hstep : loosePg prev (x :: xs) =
              step looseTable x :: loosePg (some (step looseTable x)) xs := by
            simp [loosePg, hk, hm]
          rw [hstep] at hc
          rcases List.mem_cons.mp hc with hcv | hc'
          · subst hcv
            exact ⟨loose_kept x hk, loose_mark x hm, loose_step x⟩
          · exact ih (some (step looseTable x)) c hc'
      · have hstep : loosePg prev (x :: xs) = loosePg prev xs := by
          simp [loosePg, hk]
        rw [hstep] at hc
        exact ih prev c hc

theorem loosePg_of_fixed : ∀ (prev : Option Char) (s : List Char),
    (∀ c ∈ s, keepChar c = true ∧ c ≠ 'ー' ∧ step looseTable c = c) →
      loosePg prev s = s := by
  intro prev s
  induction s generalizing prev with
  | nil => intro _; rfl
  | cons x xs ih =>
      intro h
      have hx := h x (by simp)
      have hxs : ∀ c ∈ xs, keepChar c = true ∧ c ≠ 'ー' ∧ step looseTable c = c :=
        fun c hc => h c (by simp [hc])
      have hstep : loosePg prev (x :: xs) =
          x :: loosePg (some x) xs := by
        simp [loosePg, hx.1, hx.2.1, hx.2.2]
      rw [hstep]
      rw [ih (some x) hxs]

def loose (s : String) : String := String.ofList (loosePg none s.toList)

theorem loose_idem (s : String) : loose (loose s) = loose s := by
  unfold loose
  rw [String.toList_ofList, loosePg_of_fixed none _ (loosePg_fixed s.toList none)]

end Nayose
