/-
  Exports the rule table the proofs were checked against, for the Python runner.
  The plan's runtime branch: Lean proves the table, Python looks the same table up.
-/

import Nayose.Rules
import Nayose.Compare

open Nayose Field

def fieldJson : Field → String
  | kanaFull => "\"kana_full\""
  | kanaSur => "\"kana_sur\""
  | kanaGiv => "\"kana_giv\""
  | kanjiFull => "\"kanji_full\""
  | dob => "\"dob\""
  | gender => "\"gender\""
  | cif => "\"cif\""
  | ident => "\"ident\""
  | household => "\"household\""
  | age => "\"age\""
  | orgName => "\"org_name\""
  | orgForm => "\"org_form\""

def kindJson : Kind → String
  | .person => "\"person\""
  | .org => "\"org\""

def joinStr (sep : String) : List String → String
  | [] => ""
  | [x] => x
  | x :: xs => x ++ sep ++ joinStr sep xs

def atomJson (a : Atom) : String := "[" ++ fieldJson a.1 ++ "," ++ toString a.2 ++ "]"

def altJson (alt : Alt) : String := "[" ++ joinStr "," (alt.map atomJson) ++ "]"

def groupJson (g : Group) : String := "[" ++ joinStr "," (g.map altJson) ++ "]"

def ruleJson (r : Rule) : String :=
  "{\"name\":" ++ "\"" ++ r.name ++ "\"" ++
  ",\"kind\":" ++ kindJson r.kind ++
  ",\"groups\":[" ++ joinStr "," (r.groups.map groupJson) ++ "]}"

def vetoJson (v : Veto) : String :=
  "{\"name\":\"" ++ v.name ++ "\"" ++
  ",\"field\":" ++ fieldJson v.field ++
  ",\"lo\":" ++ toString v.lo ++
  ",\"hi\":" ++ toString v.hi ++ "}"

def allFields : List Field :=
  [kanaFull, kanaSur, kanaGiv, kanjiFull, dob, gender, cif, ident, household, age,
   orgName, orgForm]

def arityJson : String :=
  "[" ++ joinStr "," (allFields.map fun f => "[" ++ fieldJson f ++ "," ++ toString (arity f) ++ "]") ++ "]"

def corrEntry (f : Field) : List String :=
  match corroborationThreshold f with
  | some t => ["[" ++ fieldJson f ++ "," ++ toString t ++ "]"]
  | none => []

def corroborationJson : String :=
  "[" ++ joinStr "," ((allFields.map corrEntry).flatten) ++ "]"

def table : String :=
  "{\"rules_version\":1," ++
  "\"arity\":" ++ arityJson ++ "," ++
  "\"corroboration\":" ++ corroborationJson ++ "," ++
  "\"vetoes\":[" ++ joinStr "," (vetoRules.map vetoJson) ++ "]," ++
  "\"safe\":[" ++ joinStr "," (safeRules.map ruleJson) ++ "]," ++
  "\"candidate\":[" ++ joinStr "," (candidateRules.map ruleJson) ++ "]}"

def main (args : List String) : IO UInt32 := do
  let path := args.head?.getD "rules.json"
  IO.FS.writeFile path table
  IO.println s!"wrote {path} ({table.length} bytes)"
  return 0
