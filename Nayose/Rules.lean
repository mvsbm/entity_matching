/-
  The SAFE / CANDIDATE decision, as data.

  A `Profile` is one level per field. Level 0 is always MISSING; higher means
  more agreement, except for `ident`, where the plan orders
  CONFLICT < NONE_SHARED < SHARED_OTHER < SHARED_UNIQUE.

  Every rule in the plan is "at-least" shaped: a conjunction of disjunctions of
  conjunctions of lower bounds. `Rule.groups` is exactly that shape, so the
  proofs read the same list the runner reads, and `needs` / `forcesCorroboration`
  are data checks rather than prose.
-/

namespace Nayose

inductive Kind where
  | person
  | org
  deriving DecidableEq, Repr

inductive Field where
  | kanaFull
  | kanaSur
  | kanaGiv
  | kanjiFull
  | dob
  | gender
  | cif
  | ident
  | household
  | age
  | orgName
  | orgForm
  deriving DecidableEq, Repr

/-- Level 0 is MISSING everywhere: neither side has the value, so nothing agrees. -/
structure Profile where
  kind : Kind
  level : Field → Nat

open Field

namespace Lvl
/- Level names as used by the plan. The same number means different things in
different fields, so each rule atom carries the field it belongs to. -/
def missing := 0
def diff := 1
def close := 2
def swapped := 3          -- kanaFull
def looseFull := 4        -- kanaFull
def exactFull := 5        -- kanaFull
def loosePart := 3        -- kanaSur, kanaGiv
def exactPart := 4        -- kanaSur, kanaGiv
def near := 2             -- dob
def dobExact := 3         -- dob
def same := 2             -- gender, household, orgForm
def shared := 2           -- cif, household
def noneShared := 2       -- ident
def sharedOther := 3      -- ident
def sharedUnique := 4     -- ident
def variant := 3          -- kanjiFull
def kanjiExact := 4       -- kanjiFull
def normalized := 3       -- orgName
def orgExact := 4         -- orgName
def inconsistent := 1     -- age
def consistent := 2       -- age
end Lvl

/-- The highest level each field can reach; a profile above it is malformed. -/
def arity : Field → Nat
  | kanaFull => 5
  | kanaSur => 4
  | kanaGiv => 4
  | kanjiFull => 4
  | dob => 3
  | gender => 2
  | cif => 2
  | ident => 4
  | household => 2
  | age => 2
  | orgName => 4
  | orgForm => 2

/-- The level at which a field counts as shared corroboration; `none` for fields
that are never corroboration. This is what makes blocking safe. -/
def corroborationThreshold : Field → Option Nat
  | cif => some Lvl.shared
  | ident => some Lvl.sharedOther
  | household => some Lvl.shared
  | _ => none

abbrev Atom := Field × Nat

/-- An atom fires when the field's level is at least the atom's threshold. -/
def Atom.fires (a : Atom) (p : Profile) : Bool := decide (a.2 ≤ p.level a.1)

def Atom.isCorroboration (a : Atom) : Bool :=
  match corroborationThreshold a.1 with
  | some t => decide (t ≤ a.2)
  | none => false

/-- One alternative of a disjunction: a conjunction of atoms. -/
abbrev Alt := List Atom
/-- One required group: at least one alternative must hold. -/
abbrev Group := List Alt

structure Rule where
  name : String
  kind : Kind
  groups : List Group
  deriving Repr

/-- A rule holds when every group has a satisfied alternative. -/
def Rule.holds (r : Rule) (p : Profile) : Bool :=
  r.kind == p.kind && r.groups.all fun g => g.any fun alt => alt.all fun a => a.fires p

/-- The rule needs field `f` at level `l` or above in every satisfying profile:
some required group has every alternative carrying such an atom. -/
def Rule.needs (r : Rule) (f : Field) (l : Nat) : Bool :=
  r.groups.any fun g =>
    g.all fun alt => alt.any fun a => a.1 == f && decide (l ≤ a.2)

/-- The rule cannot hold unless some corroboration field is at least shared. -/
def Rule.forcesCorroboration (r : Rule) : Bool :=
  r.groups.any fun g => g.all fun alt => alt.any Atom.isCorroboration

structure Veto where
  name : String
  field : Field
  lo : Nat
  hi : Nat

/-- Fires when the field is present (`lo ≤ level`) and at most `hi`. -/
def Veto.fires (v : Veto) (p : Profile) : Bool :=
  decide (v.lo ≤ p.level v.field) && decide (p.level v.field ≤ v.hi)

def vetoRules : List Veto :=
  [ ⟨"BIRTH_DATE_DIFF", dob, Lvl.diff, Lvl.diff⟩
  , ⟨"GENDER_DIFF", gender, Lvl.diff, Lvl.diff⟩
  , ⟨"GIVEN_NAME_DIFF", kanaGiv, Lvl.diff, Lvl.diff⟩
  , ⟨"KANJI_CLOSE_OR_DIFF", kanjiFull, Lvl.diff, Lvl.close⟩
  , ⟨"IDENTIFIER_CONFLICT", ident, Lvl.diff, Lvl.diff⟩
  , ⟨"ORG_LEGAL_FORM_DIFF", orgForm, Lvl.diff, Lvl.diff⟩
  ]

/-- One group of corroboration alternatives: cif shared, identifier shared, or
the same household. -/
def corroborationGroup : Group :=
  [ [⟨cif, Lvl.shared⟩]
  , [⟨ident, Lvl.sharedOther⟩]
  , [⟨household, Lvl.shared⟩]
  ]

def safeRules : List Rule :=
  [ ⟨"S1_KANA_DOB_CORROBORATION", .person,
      [ [[⟨kanaFull, Lvl.looseFull⟩], [⟨kanaSur, Lvl.loosePart⟩, ⟨kanaGiv, Lvl.loosePart⟩]]
      , [[⟨dob, Lvl.dobExact⟩]]
      , corroborationGroup ]⟩
  , ⟨"S2_UNIQUE_IDENTIFIER", .person,
      [ [[⟨ident, Lvl.sharedUnique⟩]]
      , [[⟨dob, Lvl.dobExact⟩]]
      , [[⟨kanaSur, Lvl.loosePart⟩], [⟨kanaGiv, Lvl.loosePart⟩]] ]⟩
  , ⟨"S3_ORG", .org,
      [ [[⟨orgName, Lvl.normalized⟩, ⟨ident, Lvl.sharedUnique⟩]
        , [⟨orgName, Lvl.orgExact⟩, ⟨cif, Lvl.shared⟩]] ]⟩
  ]

def candidateRules : List Rule :=
  [ ⟨"C1_GIVEN_NAME_CORROBORATION", .person,
      [ [[⟨kanaGiv, Lvl.loosePart⟩]]
      , [[⟨dob, Lvl.dobExact⟩]]
      , corroborationGroup ]⟩
  , ⟨"C2_KANA_BIRTH_DATE_NEAR", .person,
      [ [[⟨kanaFull, Lvl.looseFull⟩]], [[⟨dob, Lvl.near⟩]] ]⟩
  , ⟨"C3_KANA_CLOSE", .person,
      [ [[⟨kanaFull, Lvl.close⟩]], [[⟨dob, Lvl.dobExact⟩]] ]⟩
  , ⟨"C4_ORG_NAME", .org, [ [[⟨orgName, Lvl.close⟩]] ]⟩
  ]

/-- SAFE, CANDIDATE, or not returned at all. -/
inductive Tier where
  | safe
  | candidate
  | none
  deriving DecidableEq, Repr

namespace Profile

def vetoed (p : Profile) : Bool := vetoRules.any fun v => v.fires p

def fires (rs : List Rule) (p : Profile) : Bool := rs.any fun r => r.holds p

/-- SAFE unless a veto fires; a vetoed pair that a rule still matches is the
plan's pattern C5 and goes to review. -/
def tier (p : Profile) : Tier :=
  match p.vetoed, p.fires safeRules, p.fires candidateRules with
  | false, true, _ => .safe
  | _, false, false => .none
  | _, _, _ => .candidate

def Le (p q : Profile) : Prop := p.kind = q.kind ∧ ∀ f, p.level f ≤ q.level f

end Profile

-- ---------------------------------------------------------------------------
-- T1: the tier never depends on weights or thresholds.
-- ---------------------------------------------------------------------------

/-- What the scorer produces: a profile plus fitted weights. The weights order
CANDIDATEs; they cannot move a pair into SAFE, because `tier` does not see them. -/
structure Scored where
  profile : Profile
  weight : Int

def Scored.tier (s : Scored) : Tier := s.profile.tier

theorem safe_indep_of_weights (s : Scored) : s.tier = s.profile.tier := rfl

-- ---------------------------------------------------------------------------
-- T2 / the shape of the decision
-- ---------------------------------------------------------------------------

theorem tier_safe_iff (p : Profile) :
    p.tier = .safe ↔ p.vetoed = false ∧ p.fires safeRules = true := by
  unfold Profile.tier
  split <;> simp_all

theorem veto_blocks_safe (p : Profile) (h : p.vetoed) : p.tier ≠ .safe := by
  unfold Profile.tier
  split <;> simp_all

theorem in_review {p : Profile} (h : p.tier ≠ .none) :
    p.fires safeRules = true ∨ p.fires candidateRules = true := by
  cases hv : p.vetoed <;> cases hs : p.fires safeRules <;> cases hc : p.fires candidateRules
  all_goals simp [Profile.tier, hv, hs, hc] at h ⊢

theorem not_in_review {p : Profile} (h : p.tier = .none) :
    p.fires safeRules = false ∧ p.fires candidateRules = false := by
  cases hv : p.vetoed <;> cases hs : p.fires safeRules <;> cases hc : p.fires candidateRules
  all_goals simp [Profile.tier, hv, hs, hc] at h ⊢

-- ---------------------------------------------------------------------------
-- T3: a MISSING field never satisfies an atom, and every person SAFE rule
-- needs an exact birth date.
-- ---------------------------------------------------------------------------

theorem atom_missing (p : Profile) (f : Field) (l : Nat)
    (hzero : p.level f = 0) (hpos : 0 < l) : Atom.fires (f, l) p = false := by
  simp [Atom.fires, hzero, Nat.not_le.mpr hpos]

theorem needs_holds {r : Rule} {p : Profile} {f : Field} {l : Nat}
    (h : r.holds p = true) (hn : r.needs f l = true) : l ≤ p.level f := by
  simp only [Rule.holds, Bool.and_eq_true] at h
  obtain ⟨-, hg⟩ := h
  simp only [Rule.needs, List.any_eq_true] at hn
  obtain ⟨g, hgm, hall⟩ := hn
  obtain ⟨alt, halt, hfired⟩ := List.any_eq_true.mp (List.all_eq_true.mp hg g hgm)
  obtain ⟨a, ha, hatom⟩ := List.any_eq_true.mp (List.all_eq_true.mp hall alt halt)
  have hfeq : a.1 = f := by
    have h := hatom; simp only [Bool.and_eq_true, beq_iff_eq] at h; exact h.1
  have hl : l ≤ a.2 := by
    have h := hatom; simp only [Bool.and_eq_true, decide_eq_true_eq] at h; exact h.2
  have hfire : a.2 ≤ p.level a.1 := by
    simpa [Atom.fires] using List.all_eq_true.mp hfired a ha
  rw [hfeq] at hfire
  exact Nat.le_trans hl hfire

/-- Data check: every person SAFE rule requires an exact birth date. -/
theorem safe_person_rules_need_dob :
    (safeRules.filter (fun r => r.kind == .person)).all
      (fun r => r.needs dob Lvl.dobExact) = true := by decide

theorem safe_person_needs_dob (p : Profile) (hk : p.kind = .person)
    (h : p.tier = .safe) : Lvl.dobExact ≤ p.level dob := by
  obtain ⟨-, hs⟩ := tier_safe_iff p |>.mp h
  simp only [Profile.fires, List.any_eq_true] at hs
  obtain ⟨r, hr, hrh⟩ := hs
  have hkind : (r.kind == .person) = true := by
    have hk' := hrh
    simp only [Rule.holds, Bool.and_eq_true] at hk'
    rw [beq_iff_eq.mp hk'.1, hk]
    simp
  have hmem : r ∈ safeRules.filter (fun r => r.kind == .person) := by
    simp only [List.mem_filter]
    exact ⟨hr, hkind⟩
  exact needs_holds hrh (List.all_eq_true.mp safe_person_rules_need_dob r hmem)

-- ---------------------------------------------------------------------------
-- T5: every SAFE pair is corroborated.
-- ---------------------------------------------------------------------------

theorem forces_holds {r : Rule} {p : Profile}
    (h : r.holds p = true) (hc : r.forcesCorroboration = true) :
    ∃ f, (corroborationThreshold f).isSome = true ∧
      (corroborationThreshold f).getD 0 ≤ p.level f := by
  simp only [Rule.holds, Bool.and_eq_true] at h
  obtain ⟨-, hg⟩ := h
  simp only [Rule.forcesCorroboration, List.any_eq_true] at hc
  obtain ⟨g, hgm, hall⟩ := hc
  obtain ⟨alt, halt, hfired⟩ := List.any_eq_true.mp (List.all_eq_true.mp hg g hgm)
  obtain ⟨a, ha, hcorr⟩ := List.any_eq_true.mp (List.all_eq_true.mp hall alt halt)
  simp only [Atom.isCorroboration] at hcorr
  split at hcorr
  · rename_i t ht
    refine ⟨a.1, by simp [ht], ?_⟩
    have hl : t ≤ a.2 := of_decide_eq_true hcorr
    simp only [ht, Option.getD_some]
    have hfire : a.2 ≤ p.level a.1 := by
      simpa [Atom.fires] using List.all_eq_true.mp hfired a ha
    exact Nat.le_trans hl hfire
  · exact absurd hcorr (by simp)

theorem safe_rules_force_corroboration :
    safeRules.all Rule.forcesCorroboration = true := by decide

theorem safe_has_corroboration (p : Profile) (h : p.tier = .safe) :
    ∃ f, (corroborationThreshold f).isSome = true ∧
      (corroborationThreshold f).getD 0 ≤ p.level f := by
  obtain ⟨-, hs⟩ := tier_safe_iff p |>.mp h
  simp only [Profile.fires, List.any_eq_true] at hs
  obtain ⟨r, hr, hrh⟩ := hs
  exact forces_holds hrh (List.all_eq_true.mp safe_rules_force_corroboration r hr)

-- ---------------------------------------------------------------------------
-- T4, in the form the code needs: fixing a field upward can cost SAFE (a newly
-- populated field can fire a veto) but can never push a pair out of review.
-- ---------------------------------------------------------------------------

theorem Rule.holds_mono {r : Rule} {p q : Profile} (h : p.Le q)
    (hr : r.holds p = true) : r.holds q = true := by
  obtain ⟨hk, hl⟩ := h
  simp only [Rule.holds, Bool.and_eq_true] at hr ⊢
  refine ⟨?_, ?_⟩
  · rw [← hk]; exact hr.1
  simp only [List.all_eq_true]
  intro g hgm
  obtain ⟨alt, halt, hfired⟩ := List.any_eq_true.mp (List.all_eq_true.mp hr.2 g hgm)
  refine List.any_eq_true.mpr ⟨alt, halt, ?_⟩
  simp only [List.all_eq_true] at hfired ⊢
  intro a ha
  simp only [Atom.fires, decide_eq_true_eq] at hfired ⊢
  exact Nat.le_trans (hfired a ha) (hl a.1)

theorem fires_mono {rs : List Rule} {p q : Profile} (h : p.Le q)
    (hr : p.fires rs = true) : q.fires rs = true := by
  simp only [Profile.fires, List.any_eq_true] at hr ⊢
  obtain ⟨r, hrm, hrh⟩ := hr
  exact ⟨r, hrm, Rule.holds_mono h hrh⟩

theorem review_mono {p q : Profile} (h : p.Le q) (hp : p.tier ≠ .none) :
    q.tier ≠ .none := by
  rcases in_review hp with h' | h'
  · have := fires_mono (rs := safeRules) h h'
    intro hnone
    simp [not_in_review hnone |>.1] at this
  · have := fires_mono (rs := candidateRules) h h'
    intro hnone
    simp [not_in_review hnone |>.2] at this

end Nayose
