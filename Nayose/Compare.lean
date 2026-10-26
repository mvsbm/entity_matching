/-
  Compare: the corroboration levels and the keys blocking uses.

  Only the corroboration fields are derived here. Name and birth-date levels come
  from the Python side, because Jaro-Winkler is deliberately outside the proofs
  (the plan tests it instead). That boundary is exactly where T6 lives: `profileOf`
  says the corroboration part of a profile really is these functions.
-/

import Nayose.Rules

namespace Nayose

open Field

/-- Raw corroboration fields of one contact. Identifiers are (ID_TP_CD, value). -/
structure Rec where
  cif : Option String
  idents : List (String × String)
  household : Option String

/-- Identifier types that are one-per-person. Empty until profiling names them;
until then S2 never fires. -/
def uniqueTypes : List String := []

def sharedIdents (a b : Rec) : List (String × String) :=
  a.idents.filter fun p => decide (p ∈ b.idents)

def hasConflict (a b : Rec) : Bool :=
  a.idents.any fun p => b.idents.any fun q => p.1 == q.1 && p.2 != q.2

def cifLevel (a b : Rec) : Nat :=
  match a.cif, b.cif with
  | some x, some y => if x = y then Lvl.shared else Lvl.diff
  | _, _ => Lvl.missing

def householdLevel (a b : Rec) : Nat :=
  match a.household, b.household with
  | some x, some y => if x = y then Lvl.shared else Lvl.diff
  | _, _ => Lvl.missing

/-- CONFLICT < NONE_SHARED < SHARED_OTHER < SHARED_UNIQUE, as in the plan. -/
def identLevel (a b : Rec) : Nat :=
  if a.idents.isEmpty || b.idents.isEmpty then Lvl.missing
  else if (sharedIdents a b).any fun k => decide (k.1 ∈ uniqueTypes) then Lvl.sharedUnique
  else match sharedIdents a b with
    | [] => if hasConflict a b then Lvl.diff else Lvl.noneShared
    | _ => Lvl.sharedOther

/-- The blocking keys a shared corroboration value implies. Tags keep a CIF value
from colliding with an identifier value or a household id. -/
def cifKey (r : Rec) : Option (String × String) := r.cif.map fun v => ("CIF", v)
def hhKey (r : Rec) : Option (String × String) := r.household.map fun v => ("HH", v)
def identKey (p : String × String) : String × String := ("ID:" ++ p.1, p.2)

def corroborationKeys (r : Rec) : List (String × String) :=
  (cifKey r).toList ++ r.idents.map identKey ++ (hhKey r).toList

/-- A profile whose corroboration part comes from the two records. -/
@[simp] theorem corroborationThreshold_cif : corroborationThreshold cif = some Lvl.shared := rfl
@[simp] theorem corroborationThreshold_ident : corroborationThreshold ident = some Lvl.sharedOther := rfl
@[simp] theorem corroborationThreshold_household :
    corroborationThreshold household = some Lvl.shared := rfl

def profileOf (kind : Kind) (other : Field → Nat) (a b : Rec) : Profile where
  kind := kind
  level := fun f =>
    match f with
    | cif => cifLevel a b
    | ident => identLevel a b
    | household => householdLevel a b
    | f => other f

-- ---------------------------------------------------------------------------
-- Extracting the shared value from a level
-- ---------------------------------------------------------------------------

theorem cifLevel_le_two (a b : Rec) : cifLevel a b ≤ Lvl.shared := by
  unfold cifLevel
  split
  · split <;> simp [Lvl.shared, Lvl.diff]
  · simp [Lvl.shared, Lvl.missing]

theorem householdLevel_le_two (a b : Rec) : householdLevel a b ≤ Lvl.shared := by
  unfold householdLevel
  split
  · split <;> simp [Lvl.shared, Lvl.diff]
  · simp [Lvl.shared, Lvl.missing]

theorem cif_shared {a b : Rec} (h : Lvl.shared ≤ cifLevel a b) :
    ∃ v, a.cif = some v ∧ b.cif = some v := by
  have heq : cifLevel a b = Lvl.shared := Nat.le_antisymm (cifLevel_le_two a b) h
  cases ha : a.cif with
  | none => simp [cifLevel, ha, Lvl.shared, Lvl.missing] at heq
  | some x =>
    cases hb : b.cif with
    | none => simp [cifLevel, ha, hb, Lvl.shared, Lvl.missing] at heq
    | some y =>
      by_cases hxy : x = y
      · exact ⟨x, rfl, by rw [hxy]⟩
      · simp [cifLevel, ha, hb, hxy, Lvl.shared, Lvl.diff] at heq

theorem household_shared {a b : Rec} (h : Lvl.shared ≤ householdLevel a b) :
    ∃ v, a.household = some v ∧ b.household = some v := by
  have heq : householdLevel a b = Lvl.shared :=
    Nat.le_antisymm (householdLevel_le_two a b) h
  cases ha : a.household with
  | none => simp [householdLevel, ha, Lvl.shared, Lvl.missing] at heq
  | some x =>
    cases hb : b.household with
    | none => simp [householdLevel, ha, hb, Lvl.shared, Lvl.missing] at heq
    | some y =>
      by_cases hxy : x = y
      · exact ⟨x, rfl, by rw [hxy]⟩
      · simp [householdLevel, ha, hb, hxy, Lvl.shared, Lvl.diff] at heq

theorem ident_shared {a b : Rec} (h : Lvl.sharedOther ≤ identLevel a b) :
    ∃ k, k ∈ a.idents ∧ k ∈ b.idents := by
  have he : ¬ ((a.idents.isEmpty || b.idents.isEmpty) = true) := by
    intro he
    have hl : identLevel a b = Lvl.missing := by simp [identLevel, he]
    rw [hl] at h
    simp [Lvl.sharedOther, Lvl.missing] at h
  by_cases hu : ((sharedIdents a b).any (fun k => decide (k.1 ∈ uniqueTypes))) = true
  · obtain ⟨k, hk, -⟩ := List.any_eq_true.mp hu
    have hbm : k ∈ b.idents := of_decide_eq_true (List.mem_filter.mp hk).2
    exact ⟨k, (List.mem_filter.mp hk).1, hbm⟩
  · cases hs : sharedIdents a b with
    | nil =>
        have hl : identLevel a b =
            if hasConflict a b then Lvl.diff else Lvl.noneShared := by
          simp [identLevel, he, hs]
        rw [hl] at h
        split at h <;> simp [Lvl.sharedOther, Lvl.diff, Lvl.noneShared] at h
    | cons k _ =>
        have hk : k ∈ sharedIdents a b := by simp [hs]
        have hbm : k ∈ b.idents := of_decide_eq_true (List.mem_filter.mp hk).2
        exact ⟨k, (List.mem_filter.mp hk).1, hbm⟩

-- ---------------------------------------------------------------------------
-- T6: a SAFE pair always shares a corroboration block key, so blocking can't
-- drop it. This is T5 read on the records instead of the profile.
-- ---------------------------------------------------------------------------

theorem safe_shares_corroboration_key (a b : Rec) (kind : Kind) (other : Field → Nat)
    (h : (profileOf kind other a b).tier = .safe) :
    ∃ k, k ∈ corroborationKeys a ∧ k ∈ corroborationKeys b := by
  obtain ⟨f, hsome, hlevel⟩ := safe_has_corroboration (profileOf kind other a b) h
  cases f with
  | cif =>
      have hc : Lvl.shared ≤ cifLevel a b := by simpa [profileOf] using hlevel
      obtain ⟨v, ha, hb⟩ := cif_shared hc
      exact ⟨("CIF", v), by simp [corroborationKeys, cifKey, ha],
                          by simp [corroborationKeys, cifKey, hb]⟩
  | ident =>
      have hc : Lvl.sharedOther ≤ identLevel a b := by simpa [profileOf] using hlevel
      obtain ⟨k, ha, hb⟩ := ident_shared hc
      have hka : identKey k ∈ a.idents.map identKey := List.mem_map.mpr ⟨k, ha, rfl⟩
      have hkb : identKey k ∈ b.idents.map identKey := List.mem_map.mpr ⟨k, hb, rfl⟩
      exact ⟨identKey k, by simp [corroborationKeys, hka],
                         by simp [corroborationKeys, hkb]⟩
  | household =>
      have hc : Lvl.shared ≤ householdLevel a b := by simpa [profileOf] using hlevel
      obtain ⟨v, ha, hb⟩ := household_shared hc
      exact ⟨("HH", v), by simp [corroborationKeys, hhKey, ha],
                         by simp [corroborationKeys, hhKey, hb]⟩
  | kanaFull => simp [corroborationThreshold] at hsome
  | kanaSur => simp [corroborationThreshold] at hsome
  | kanaGiv => simp [corroborationThreshold] at hsome
  | kanjiFull => simp [corroborationThreshold] at hsome
  | dob => simp [corroborationThreshold] at hsome
  | gender => simp [corroborationThreshold] at hsome
  | age => simp [corroborationThreshold] at hsome
  | orgName => simp [corroborationThreshold] at hsome
  | orgForm => simp [corroborationThreshold] at hsome

end Nayose
