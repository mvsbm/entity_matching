// Lean compiler output
// Module: Nayose.Rules
// Imports: public import Init public meta import Init
#include <lean/lean.h>
#if defined(__clang__)
#pragma clang diagnostic ignored "-Wunused-parameter"
#pragma clang diagnostic ignored "-Wunused-label"
#elif defined(__GNUC__) && !defined(__CLANG__)
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-label"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#endif
#ifdef __cplusplus
extern "C" {
#endif
uint8_t lean_nat_dec_eq(lean_object*, lean_object*);
uint8_t lean_nat_dec_le(lean_object*, lean_object*);
lean_object* l_Repr_addAppParen(lean_object*, lean_object*);
lean_object* lean_nat_to_int(lean_object*);
lean_object* l_Nat_reprFast(lean_object*);
lean_object* l_List_reverse___redArg(lean_object*);
lean_object* l_Std_Format_joinSep___at___00Lean_Syntax_formatStxAux_spec__2(lean_object*, lean_object*);
lean_object* lean_string_length(lean_object*);
lean_object* l_String_quote(lean_object*);
uint8_t lean_nat_dec_le(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorIdx(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorIdx___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim(lean_object*, lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Kind_ofNat(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ofNat___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_instDecidableEqKind(uint8_t, uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instDecidableEqKind___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_Nayose_instReprKind_repr___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 19, .m_capacity = 19, .m_length = 18, .m_data = "Nayose.Kind.person"};
static const lean_object* lp_nayose_Nayose_instReprKind_repr___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprKind_repr___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_instReprKind_repr___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprKind_repr___closed__0_value)}};
static const lean_object* lp_nayose_Nayose_instReprKind_repr___closed__1 = (const lean_object*)&lp_nayose_Nayose_instReprKind_repr___closed__1_value;
static const lean_string_object lp_nayose_Nayose_instReprKind_repr___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 16, .m_capacity = 16, .m_length = 15, .m_data = "Nayose.Kind.org"};
static const lean_object* lp_nayose_Nayose_instReprKind_repr___closed__2 = (const lean_object*)&lp_nayose_Nayose_instReprKind_repr___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_instReprKind_repr___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprKind_repr___closed__2_value)}};
static const lean_object* lp_nayose_Nayose_instReprKind_repr___closed__3 = (const lean_object*)&lp_nayose_Nayose_instReprKind_repr___closed__3_value;
static lean_once_cell_t lp_nayose_Nayose_instReprKind_repr___closed__4_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Nayose_instReprKind_repr___closed__4;
static lean_once_cell_t lp_nayose_Nayose_instReprKind_repr___closed__5_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Nayose_instReprKind_repr___closed__5;
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprKind_repr(uint8_t, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprKind_repr___boxed(lean_object*, lean_object*);
static const lean_closure_object lp_nayose_Nayose_instReprKind___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_closure_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 245}, .m_fun = (void*)lp_nayose_Nayose_instReprKind_repr___boxed, .m_arity = 2, .m_num_fixed = 0, .m_objs = {} };
static const lean_object* lp_nayose_Nayose_instReprKind___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprKind___closed__0_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_instReprKind = (const lean_object*)&lp_nayose_Nayose_instReprKind___closed__0_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorIdx(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorIdx___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim(lean_object*, lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Field_ofNat(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ofNat___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_instDecidableEqField(uint8_t, uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instDecidableEqField___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 22, .m_capacity = 22, .m_length = 21, .m_data = "Nayose.Field.kanaFull"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__0_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__1 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__1_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 21, .m_capacity = 21, .m_length = 20, .m_data = "Nayose.Field.kanaSur"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__2 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__2_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__3 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__3_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 21, .m_capacity = 21, .m_length = 20, .m_data = "Nayose.Field.kanaGiv"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__4 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__4_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__5 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__5_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 23, .m_capacity = 23, .m_length = 22, .m_data = "Nayose.Field.kanjiFull"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__6 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__6_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__6_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__7 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__7_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 17, .m_capacity = 17, .m_length = 16, .m_data = "Nayose.Field.dob"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__8 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__8_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__8_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__9 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__9_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 20, .m_capacity = 20, .m_length = 19, .m_data = "Nayose.Field.gender"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__10 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__10_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__10_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__11 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__11_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__12_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 17, .m_capacity = 17, .m_length = 16, .m_data = "Nayose.Field.cif"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__12 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__12_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__12_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__13 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__13_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__14_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 19, .m_capacity = 19, .m_length = 18, .m_data = "Nayose.Field.ident"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__14 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__14_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__15_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__14_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__15 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__15_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__16_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 23, .m_capacity = 23, .m_length = 22, .m_data = "Nayose.Field.household"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__16 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__16_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__17_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__16_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__17 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__17_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__18_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 17, .m_capacity = 17, .m_length = 16, .m_data = "Nayose.Field.age"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__18 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__18_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__19_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__18_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__19 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__19_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__20_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 21, .m_capacity = 21, .m_length = 20, .m_data = "Nayose.Field.orgName"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__20 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__20_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__21_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__20_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__21 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__21_value;
static const lean_string_object lp_nayose_Nayose_instReprField_repr___closed__22_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 21, .m_capacity = 21, .m_length = 20, .m_data = "Nayose.Field.orgForm"};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__22 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__22_value;
static const lean_ctor_object lp_nayose_Nayose_instReprField_repr___closed__23_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__22_value)}};
static const lean_object* lp_nayose_Nayose_instReprField_repr___closed__23 = (const lean_object*)&lp_nayose_Nayose_instReprField_repr___closed__23_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprField_repr(uint8_t, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprField_repr___boxed(lean_object*, lean_object*);
static const lean_closure_object lp_nayose_Nayose_instReprField___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_closure_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 245}, .m_fun = (void*)lp_nayose_Nayose_instReprField_repr___boxed, .m_arity = 2, .m_num_fixed = 0, .m_objs = {} };
static const lean_object* lp_nayose_Nayose_instReprField___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprField___closed__0_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_instReprField = (const lean_object*)&lp_nayose_Nayose_instReprField___closed__0_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_missing;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_diff;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_close;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_swapped;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_looseFull;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_exactFull;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_loosePart;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_exactPart;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_near;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_dobExact;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_same;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_shared;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_noneShared;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_sharedOther;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_sharedUnique;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_variant;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_kanjiExact;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_normalized;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_orgExact;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_inconsistent;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Lvl_consistent;
LEAN_EXPORT lean_object* lp_nayose_Nayose_arity(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_arity___boxed(lean_object*);
static const lean_ctor_object lp_nayose_Nayose_corroborationThreshold___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(2) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationThreshold___closed__0 = (const lean_object*)&lp_nayose_Nayose_corroborationThreshold___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationThreshold___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(3) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationThreshold___closed__1 = (const lean_object*)&lp_nayose_Nayose_corroborationThreshold___closed__1_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_corroborationThreshold(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_corroborationThreshold___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Atom_fires(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Atom_fires___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Atom_isCorroboration(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Atom_isCorroboration___boxed(lean_object*);
static const lean_string_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "("};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__0 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__0_value;
static const lean_string_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = ","};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__1 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__1_value;
static const lean_ctor_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__1_value)}};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__2 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__2_value;
static const lean_ctor_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__2_value),((lean_object*)(((size_t)(1) << 1) | 1))}};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3_value;
static const lean_string_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = ")"};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__4 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__4_value;
static lean_once_cell_t lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__5_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__5;
static lean_once_cell_t lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__6_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__6;
static const lean_ctor_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__0_value)}};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__7 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__7_value;
static const lean_ctor_object lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__4_value)}};
static const lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__8 = (const lean_object*)&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__8_value;
LEAN_EXPORT lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3_spec__5_spec__8(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3_spec__5(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3(lean_object*, lean_object*);
static const lean_string_object lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "[]"};
static const lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__0 = (const lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__0_value;
static const lean_ctor_object lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__0_value)}};
static const lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__1 = (const lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__1_value;
static const lean_string_object lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "["};
static const lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__2 = (const lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__2_value;
static const lean_string_object lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "]"};
static const lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__3 = (const lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__3_value;
static lean_once_cell_t lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__4_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__4;
static lean_once_cell_t lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5;
static const lean_ctor_object lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__2_value)}};
static const lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__6 = (const lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__6_value;
static const lean_ctor_object lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__3_value)}};
static const lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__7 = (const lean_object*)&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__7_value;
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2_spec__5_spec__8(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2_spec__5(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1_spec__4_spec__8(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1_spec__4(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0___redArg(lean_object*);
static const lean_string_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "{ "};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__0_value;
static const lean_string_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 5, .m_capacity = 5, .m_length = 4, .m_data = "name"};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__1 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__1_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__1_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__2 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)(((size_t)(0) << 1) | 1)),((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__2_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__3 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__3_value;
static const lean_string_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 5, .m_capacity = 5, .m_length = 4, .m_data = " := "};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__4 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__4_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__5 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__5_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 5}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__3_value),((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__5_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__6 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__6_value;
static lean_once_cell_t lp_nayose_Nayose_instReprRule_repr___redArg___closed__7_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__7;
static const lean_string_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 5, .m_capacity = 5, .m_length = 4, .m_data = "kind"};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__8 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__8_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__8_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__9 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__9_value;
static const lean_string_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 7, .m_capacity = 7, .m_length = 6, .m_data = "groups"};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__10 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__10_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__10_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__11 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__11_value;
static lean_once_cell_t lp_nayose_Nayose_instReprRule_repr___redArg___closed__12_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__12;
static const lean_string_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = " }"};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__13 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__13_value;
static lean_once_cell_t lp_nayose_Nayose_instReprRule_repr___redArg___closed__14_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__14;
static lean_once_cell_t lp_nayose_Nayose_instReprRule_repr___redArg___closed__15_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__15;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__16_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__0_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__16 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__16_value;
static const lean_ctor_object lp_nayose_Nayose_instReprRule_repr___redArg___closed__17_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__13_value)}};
static const lean_object* lp_nayose_Nayose_instReprRule_repr___redArg___closed__17 = (const lean_object*)&lp_nayose_Nayose_instReprRule_repr___redArg___closed__17_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprRule_repr___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprRule_repr(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprRule_repr___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___boxed(lean_object*, lean_object*);
static const lean_closure_object lp_nayose_Nayose_instReprRule___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_closure_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 245}, .m_fun = (void*)lp_nayose_Nayose_instReprRule_repr___boxed, .m_arity = 2, .m_num_fixed = 0, .m_objs = {} };
static const lean_object* lp_nayose_Nayose_instReprRule___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprRule___closed__0_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_instReprRule = (const lean_object*)&lp_nayose_Nayose_instReprRule___closed__0_value;
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_holds_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_holds_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_holds_spec__1(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_holds_spec__1___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_holds_spec__2(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_holds_spec__2___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Rule_holds(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Rule_holds___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_needs_spec__0(uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_needs_spec__0___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_needs_spec__1(uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_needs_spec__1___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_needs_spec__2(uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_needs_spec__2___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Rule_needs(lean_object*, uint8_t, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Rule_needs___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__0(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__0___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_forcesCorroboration_spec__1(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_forcesCorroboration_spec__1___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__2(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__2___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Rule_forcesCorroboration(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Rule_forcesCorroboration___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Veto_fires(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Veto_fires___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_Nayose_vetoRules___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 16, .m_capacity = 16, .m_length = 15, .m_data = "BIRTH_DATE_DIFF"};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__0 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*3 + 8, .m_other = 3, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__0_value),((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(1) << 1) | 1)),LEAN_SCALAR_PTR_LITERAL(4, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__1 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__1_value;
static const lean_string_object lp_nayose_Nayose_vetoRules___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 12, .m_capacity = 12, .m_length = 11, .m_data = "GENDER_DIFF"};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__2 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*3 + 8, .m_other = 3, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__2_value),((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(1) << 1) | 1)),LEAN_SCALAR_PTR_LITERAL(5, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__3 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__3_value;
static const lean_string_object lp_nayose_Nayose_vetoRules___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 16, .m_capacity = 16, .m_length = 15, .m_data = "GIVEN_NAME_DIFF"};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__4 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*3 + 8, .m_other = 3, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__4_value),((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(1) << 1) | 1)),LEAN_SCALAR_PTR_LITERAL(2, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__5 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__5_value;
static const lean_string_object lp_nayose_Nayose_vetoRules___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 20, .m_capacity = 20, .m_length = 19, .m_data = "KANJI_CLOSE_OR_DIFF"};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__6 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__6_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*3 + 8, .m_other = 3, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__6_value),((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(2) << 1) | 1)),LEAN_SCALAR_PTR_LITERAL(3, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__7 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__7_value;
static const lean_string_object lp_nayose_Nayose_vetoRules___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 20, .m_capacity = 20, .m_length = 19, .m_data = "IDENTIFIER_CONFLICT"};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__8 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__8_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*3 + 8, .m_other = 3, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__8_value),((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(1) << 1) | 1)),LEAN_SCALAR_PTR_LITERAL(7, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__9 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__9_value;
static const lean_string_object lp_nayose_Nayose_vetoRules___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 20, .m_capacity = 20, .m_length = 19, .m_data = "ORG_LEGAL_FORM_DIFF"};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__10 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__10_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*3 + 8, .m_other = 3, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__10_value),((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(1) << 1) | 1)),LEAN_SCALAR_PTR_LITERAL(11, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__11 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__11_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__12_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__11_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__12 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__12_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__9_value),((lean_object*)&lp_nayose_Nayose_vetoRules___closed__12_value)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__13 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__13_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__14_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__7_value),((lean_object*)&lp_nayose_Nayose_vetoRules___closed__13_value)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__14 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__14_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__15_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__5_value),((lean_object*)&lp_nayose_Nayose_vetoRules___closed__14_value)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__15 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__15_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__16_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__3_value),((lean_object*)&lp_nayose_Nayose_vetoRules___closed__15_value)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__16 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__16_value;
static const lean_ctor_object lp_nayose_Nayose_vetoRules___closed__17_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_vetoRules___closed__1_value),((lean_object*)&lp_nayose_Nayose_vetoRules___closed__16_value)}};
static const lean_object* lp_nayose_Nayose_vetoRules___closed__17 = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__17_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_vetoRules = (const lean_object*)&lp_nayose_Nayose_vetoRules___closed__17_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(6) << 1) | 1)),((lean_object*)(((size_t)(2) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__0 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__0_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__1 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__1_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(7) << 1) | 1)),((lean_object*)(((size_t)(3) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__2 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__2_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__3 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__3_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(8) << 1) | 1)),((lean_object*)(((size_t)(2) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__4 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__4_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__5 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__5_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__5_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__6 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__6_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__3_value),((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__6_value)}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__7 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__7_value;
static const lean_ctor_object lp_nayose_Nayose_corroborationGroup___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__1_value),((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__7_value)}};
static const lean_object* lp_nayose_Nayose_corroborationGroup___closed__8 = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__8_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_corroborationGroup = (const lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__8_value;
static const lean_string_object lp_nayose_Nayose_safeRules___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 26, .m_capacity = 26, .m_length = 25, .m_data = "S1_KANA_DOB_CORROBORATION"};
static const lean_object* lp_nayose_Nayose_safeRules___closed__0 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(0) << 1) | 1)),((lean_object*)(((size_t)(4) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__1 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__1_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__1_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__2 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)(((size_t)(3) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__3 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__3_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(2) << 1) | 1)),((lean_object*)(((size_t)(3) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__4 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__4_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__5 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__5_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__3_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__5_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__6 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__6_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__6_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__7 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__7_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__2_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__7_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__8 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__8_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(4) << 1) | 1)),((lean_object*)(((size_t)(3) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__9 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__9_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__9_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__10 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__10_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__10_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__11 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__11_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__12_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__8_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__12 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__12_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__11_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__12_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__13 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__13_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__14_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__8_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__13_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__14 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__14_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__15_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__0_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__14_value),LEAN_SCALAR_PTR_LITERAL(0, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__15 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__15_value;
static const lean_string_object lp_nayose_Nayose_safeRules___closed__16_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 21, .m_capacity = 21, .m_length = 20, .m_data = "S2_UNIQUE_IDENTIFIER"};
static const lean_object* lp_nayose_Nayose_safeRules___closed__16 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__16_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__17_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(7) << 1) | 1)),((lean_object*)(((size_t)(4) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__17 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__17_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__18_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__17_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__18 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__18_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__19_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__18_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__19 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__19_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__20_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__3_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__20 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__20_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__21_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__5_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__21 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__21_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__22_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__20_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__21_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__22 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__22_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__23_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__22_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__23 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__23_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__24_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__11_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__23_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__24 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__24_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__25_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__19_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__24_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__25 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__25_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__26_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__16_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__25_value),LEAN_SCALAR_PTR_LITERAL(0, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__26 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__26_value;
static const lean_string_object lp_nayose_Nayose_safeRules___closed__27_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 7, .m_capacity = 7, .m_length = 6, .m_data = "S3_ORG"};
static const lean_object* lp_nayose_Nayose_safeRules___closed__27 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__27_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__28_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(10) << 1) | 1)),((lean_object*)(((size_t)(3) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__28 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__28_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__29_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__28_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__18_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__29 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__29_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__30_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(10) << 1) | 1)),((lean_object*)(((size_t)(4) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__30 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__30_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__31_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__30_value),((lean_object*)&lp_nayose_Nayose_corroborationGroup___closed__1_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__31 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__31_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__32_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__31_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__32 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__32_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__33_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__29_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__32_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__33 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__33_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__34_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__33_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__34 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__34_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__35_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__27_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__34_value),LEAN_SCALAR_PTR_LITERAL(1, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__35 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__35_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__36_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__35_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__36 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__36_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__37_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__26_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__36_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__37 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__37_value;
static const lean_ctor_object lp_nayose_Nayose_safeRules___closed__38_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__15_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__37_value)}};
static const lean_object* lp_nayose_Nayose_safeRules___closed__38 = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__38_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_safeRules = (const lean_object*)&lp_nayose_Nayose_safeRules___closed__38_value;
static const lean_string_object lp_nayose_Nayose_candidateRules___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 28, .m_capacity = 28, .m_length = 27, .m_data = "C1_GIVEN_NAME_CORROBORATION"};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__0 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__21_value),((lean_object*)&lp_nayose_Nayose_safeRules___closed__13_value)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__1 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__1_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__0_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__1_value),LEAN_SCALAR_PTR_LITERAL(0, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__2 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__2_value;
static const lean_string_object lp_nayose_Nayose_candidateRules___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 24, .m_capacity = 24, .m_length = 23, .m_data = "C2_KANA_BIRTH_DATE_NEAR"};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__3 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__3_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__2_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__4 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(4) << 1) | 1)),((lean_object*)(((size_t)(2) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__5 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__5_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__5_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__6 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__6_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__6_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__7 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__7_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__7_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__8 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__8_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__4_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__8_value)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__9 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__9_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__3_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__9_value),LEAN_SCALAR_PTR_LITERAL(0, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__10 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__10_value;
static const lean_string_object lp_nayose_Nayose_candidateRules___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 14, .m_capacity = 14, .m_length = 13, .m_data = "C3_KANA_CLOSE"};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__11 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__11_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__12_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(0) << 1) | 1)),((lean_object*)(((size_t)(2) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__12 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__12_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__13_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__12_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__13 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__13_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__14_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__13_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__14 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__14_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__15_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_safeRules___closed__11_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__15 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__15_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__16_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__14_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__15_value)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__16 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__16_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__17_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__11_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__16_value),LEAN_SCALAR_PTR_LITERAL(0, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__17 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__17_value;
static const lean_string_object lp_nayose_Nayose_candidateRules___closed__18_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 12, .m_capacity = 12, .m_length = 11, .m_data = "C4_ORG_NAME"};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__18 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__18_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__19_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)(((size_t)(10) << 1) | 1)),((lean_object*)(((size_t)(2) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__19 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__19_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__20_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__19_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__20 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__20_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__21_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__20_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__21 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__21_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__22_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__21_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__22 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__22_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__23_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 8, .m_other = 2, .m_tag = 0}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__18_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__22_value),LEAN_SCALAR_PTR_LITERAL(1, 0, 0, 0, 0, 0, 0, 0)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__23 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__23_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__24_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__23_value),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__24 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__24_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__25_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__17_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__24_value)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__25 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__25_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__26_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__10_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__25_value)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__26 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__26_value;
static const lean_ctor_object lp_nayose_Nayose_candidateRules___closed__27_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)&lp_nayose_Nayose_candidateRules___closed__2_value),((lean_object*)&lp_nayose_Nayose_candidateRules___closed__26_value)}};
static const lean_object* lp_nayose_Nayose_candidateRules___closed__27 = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__27_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_candidateRules = (const lean_object*)&lp_nayose_Nayose_candidateRules___closed__27_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorIdx(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorIdx___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim(lean_object*, lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim___redArg(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim___redArg___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim(lean_object*, uint8_t, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Tier_ofNat(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ofNat___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_instDecidableEqTier(uint8_t, uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instDecidableEqTier___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_Nayose_instReprTier_repr___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 17, .m_capacity = 17, .m_length = 16, .m_data = "Nayose.Tier.safe"};
static const lean_object* lp_nayose_Nayose_instReprTier_repr___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__0_value;
static const lean_ctor_object lp_nayose_Nayose_instReprTier_repr___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__0_value)}};
static const lean_object* lp_nayose_Nayose_instReprTier_repr___closed__1 = (const lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__1_value;
static const lean_string_object lp_nayose_Nayose_instReprTier_repr___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 22, .m_capacity = 22, .m_length = 21, .m_data = "Nayose.Tier.candidate"};
static const lean_object* lp_nayose_Nayose_instReprTier_repr___closed__2 = (const lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__2_value;
static const lean_ctor_object lp_nayose_Nayose_instReprTier_repr___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__2_value)}};
static const lean_object* lp_nayose_Nayose_instReprTier_repr___closed__3 = (const lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__3_value;
static const lean_string_object lp_nayose_Nayose_instReprTier_repr___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 17, .m_capacity = 17, .m_length = 16, .m_data = "Nayose.Tier.none"};
static const lean_object* lp_nayose_Nayose_instReprTier_repr___closed__4 = (const lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__4_value;
static const lean_ctor_object lp_nayose_Nayose_instReprTier_repr___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*1 + 0, .m_other = 1, .m_tag = 3}, .m_objs = {((lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__4_value)}};
static const lean_object* lp_nayose_Nayose_instReprTier_repr___closed__5 = (const lean_object*)&lp_nayose_Nayose_instReprTier_repr___closed__5_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprTier_repr(uint8_t, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprTier_repr___boxed(lean_object*, lean_object*);
static const lean_closure_object lp_nayose_Nayose_instReprTier___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_closure_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 245}, .m_fun = (void*)lp_nayose_Nayose_instReprTier_repr___boxed, .m_arity = 2, .m_num_fixed = 0, .m_objs = {} };
static const lean_object* lp_nayose_Nayose_instReprTier___closed__0 = (const lean_object*)&lp_nayose_Nayose_instReprTier___closed__0_value;
LEAN_EXPORT const lean_object* lp_nayose_Nayose_instReprTier = (const lean_object*)&lp_nayose_Nayose_instReprTier___closed__0_value;
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Profile_vetoed_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Profile_vetoed_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Profile_vetoed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Profile_vetoed___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Profile_fires(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Profile_fires___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Profile_tier(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Profile_tier___boxed(lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_Scored_tier(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Scored_tier___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___redArg(uint8_t, uint8_t, uint8_t, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___redArg___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter(lean_object*, uint8_t, uint8_t, uint8_t, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Atom_isCorroboration_match__1_splitter___redArg(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Atom_isCorroboration_match__1_splitter(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorIdx(uint8_t v_x_1_){
_start:
{
if (v_x_1_ == 0)
{
lean_object* v___x_2_; 
v___x_2_ = lean_unsigned_to_nat(0u);
return v___x_2_;
}
else
{
lean_object* v___x_3_; 
v___x_3_ = lean_unsigned_to_nat(1u);
return v___x_3_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorIdx___boxed(lean_object* v_x_4_){
_start:
{
uint8_t v_x_boxed_5_; lean_object* v_res_6_; 
v_x_boxed_5_ = lean_unbox(v_x_4_);
v_res_6_ = lp_nayose_Nayose_Kind_ctorIdx(v_x_boxed_5_);
return v_res_6_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim___redArg(lean_object* v_k_7_){
_start:
{
lean_inc(v_k_7_);
return v_k_7_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim___redArg___boxed(lean_object* v_k_8_){
_start:
{
lean_object* v_res_9_; 
v_res_9_ = lp_nayose_Nayose_Kind_ctorElim___redArg(v_k_8_);
lean_dec(v_k_8_);
return v_res_9_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim(lean_object* v_motive_10_, lean_object* v_ctorIdx_11_, uint8_t v_t_12_, lean_object* v_h_13_, lean_object* v_k_14_){
_start:
{
lean_inc(v_k_14_);
return v_k_14_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ctorElim___boxed(lean_object* v_motive_15_, lean_object* v_ctorIdx_16_, lean_object* v_t_17_, lean_object* v_h_18_, lean_object* v_k_19_){
_start:
{
uint8_t v_t_boxed_20_; lean_object* v_res_21_; 
v_t_boxed_20_ = lean_unbox(v_t_17_);
v_res_21_ = lp_nayose_Nayose_Kind_ctorElim(v_motive_15_, v_ctorIdx_16_, v_t_boxed_20_, v_h_18_, v_k_19_);
lean_dec(v_k_19_);
lean_dec(v_ctorIdx_16_);
return v_res_21_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim___redArg(lean_object* v_person_22_){
_start:
{
lean_inc(v_person_22_);
return v_person_22_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim___redArg___boxed(lean_object* v_person_23_){
_start:
{
lean_object* v_res_24_; 
v_res_24_ = lp_nayose_Nayose_Kind_person_elim___redArg(v_person_23_);
lean_dec(v_person_23_);
return v_res_24_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim(lean_object* v_motive_25_, uint8_t v_t_26_, lean_object* v_h_27_, lean_object* v_person_28_){
_start:
{
lean_inc(v_person_28_);
return v_person_28_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_person_elim___boxed(lean_object* v_motive_29_, lean_object* v_t_30_, lean_object* v_h_31_, lean_object* v_person_32_){
_start:
{
uint8_t v_t_boxed_33_; lean_object* v_res_34_; 
v_t_boxed_33_ = lean_unbox(v_t_30_);
v_res_34_ = lp_nayose_Nayose_Kind_person_elim(v_motive_29_, v_t_boxed_33_, v_h_31_, v_person_32_);
lean_dec(v_person_32_);
return v_res_34_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim___redArg(lean_object* v_org_35_){
_start:
{
lean_inc(v_org_35_);
return v_org_35_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim___redArg___boxed(lean_object* v_org_36_){
_start:
{
lean_object* v_res_37_; 
v_res_37_ = lp_nayose_Nayose_Kind_org_elim___redArg(v_org_36_);
lean_dec(v_org_36_);
return v_res_37_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim(lean_object* v_motive_38_, uint8_t v_t_39_, lean_object* v_h_40_, lean_object* v_org_41_){
_start:
{
lean_inc(v_org_41_);
return v_org_41_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_org_elim___boxed(lean_object* v_motive_42_, lean_object* v_t_43_, lean_object* v_h_44_, lean_object* v_org_45_){
_start:
{
uint8_t v_t_boxed_46_; lean_object* v_res_47_; 
v_t_boxed_46_ = lean_unbox(v_t_43_);
v_res_47_ = lp_nayose_Nayose_Kind_org_elim(v_motive_42_, v_t_boxed_46_, v_h_44_, v_org_45_);
lean_dec(v_org_45_);
return v_res_47_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Kind_ofNat(lean_object* v_n_48_){
_start:
{
lean_object* v___x_49_; uint8_t v___x_50_; 
v___x_49_ = lean_unsigned_to_nat(0u);
v___x_50_ = lean_nat_dec_le(v_n_48_, v___x_49_);
if (v___x_50_ == 0)
{
uint8_t v___x_51_; 
v___x_51_ = 1;
return v___x_51_;
}
else
{
uint8_t v___x_52_; 
v___x_52_ = 0;
return v___x_52_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Kind_ofNat___boxed(lean_object* v_n_53_){
_start:
{
uint8_t v_res_54_; lean_object* v_r_55_; 
v_res_54_ = lp_nayose_Nayose_Kind_ofNat(v_n_53_);
lean_dec(v_n_53_);
v_r_55_ = lean_box(v_res_54_);
return v_r_55_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_instDecidableEqKind(uint8_t v_x_56_, uint8_t v_y_57_){
_start:
{
lean_object* v___x_58_; lean_object* v___x_59_; uint8_t v___x_60_; 
v___x_58_ = lp_nayose_Nayose_Kind_ctorIdx(v_x_56_);
v___x_59_ = lp_nayose_Nayose_Kind_ctorIdx(v_y_57_);
v___x_60_ = lean_nat_dec_eq(v___x_58_, v___x_59_);
lean_dec(v___x_59_);
lean_dec(v___x_58_);
return v___x_60_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instDecidableEqKind___boxed(lean_object* v_x_61_, lean_object* v_y_62_){
_start:
{
uint8_t v_x_20__boxed_63_; uint8_t v_y_21__boxed_64_; uint8_t v_res_65_; lean_object* v_r_66_; 
v_x_20__boxed_63_ = lean_unbox(v_x_61_);
v_y_21__boxed_64_ = lean_unbox(v_y_62_);
v_res_65_ = lp_nayose_Nayose_instDecidableEqKind(v_x_20__boxed_63_, v_y_21__boxed_64_);
v_r_66_ = lean_box(v_res_65_);
return v_r_66_;
}
}
static lean_object* _init_lp_nayose_Nayose_instReprKind_repr___closed__4(void){
_start:
{
lean_object* v___x_73_; lean_object* v___x_74_; 
v___x_73_ = lean_unsigned_to_nat(2u);
v___x_74_ = lean_nat_to_int(v___x_73_);
return v___x_74_;
}
}
static lean_object* _init_lp_nayose_Nayose_instReprKind_repr___closed__5(void){
_start:
{
lean_object* v___x_75_; lean_object* v___x_76_; 
v___x_75_ = lean_unsigned_to_nat(1u);
v___x_76_ = lean_nat_to_int(v___x_75_);
return v___x_76_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprKind_repr(uint8_t v_x_77_, lean_object* v_prec_78_){
_start:
{
lean_object* v___y_80_; lean_object* v___y_87_; 
if (v_x_77_ == 0)
{
lean_object* v___x_93_; uint8_t v___x_94_; 
v___x_93_ = lean_unsigned_to_nat(1024u);
v___x_94_ = lean_nat_dec_le(v___x_93_, v_prec_78_);
if (v___x_94_ == 0)
{
lean_object* v___x_95_; 
v___x_95_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_80_ = v___x_95_;
goto v___jp_79_;
}
else
{
lean_object* v___x_96_; 
v___x_96_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_80_ = v___x_96_;
goto v___jp_79_;
}
}
else
{
lean_object* v___x_97_; uint8_t v___x_98_; 
v___x_97_ = lean_unsigned_to_nat(1024u);
v___x_98_ = lean_nat_dec_le(v___x_97_, v_prec_78_);
if (v___x_98_ == 0)
{
lean_object* v___x_99_; 
v___x_99_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_87_ = v___x_99_;
goto v___jp_86_;
}
else
{
lean_object* v___x_100_; 
v___x_100_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_87_ = v___x_100_;
goto v___jp_86_;
}
}
v___jp_79_:
{
lean_object* v___x_81_; lean_object* v___x_82_; uint8_t v___x_83_; lean_object* v___x_84_; lean_object* v___x_85_; 
v___x_81_ = ((lean_object*)(lp_nayose_Nayose_instReprKind_repr___closed__1));
lean_inc(v___y_80_);
v___x_82_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_82_, 0, v___y_80_);
lean_ctor_set(v___x_82_, 1, v___x_81_);
v___x_83_ = 0;
v___x_84_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_84_, 0, v___x_82_);
lean_ctor_set_uint8(v___x_84_, sizeof(void*)*1, v___x_83_);
v___x_85_ = l_Repr_addAppParen(v___x_84_, v_prec_78_);
return v___x_85_;
}
v___jp_86_:
{
lean_object* v___x_88_; lean_object* v___x_89_; uint8_t v___x_90_; lean_object* v___x_91_; lean_object* v___x_92_; 
v___x_88_ = ((lean_object*)(lp_nayose_Nayose_instReprKind_repr___closed__3));
lean_inc(v___y_87_);
v___x_89_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_89_, 0, v___y_87_);
lean_ctor_set(v___x_89_, 1, v___x_88_);
v___x_90_ = 0;
v___x_91_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_91_, 0, v___x_89_);
lean_ctor_set_uint8(v___x_91_, sizeof(void*)*1, v___x_90_);
v___x_92_ = l_Repr_addAppParen(v___x_91_, v_prec_78_);
return v___x_92_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprKind_repr___boxed(lean_object* v_x_101_, lean_object* v_prec_102_){
_start:
{
uint8_t v_x_117__boxed_103_; lean_object* v_res_104_; 
v_x_117__boxed_103_ = lean_unbox(v_x_101_);
v_res_104_ = lp_nayose_Nayose_instReprKind_repr(v_x_117__boxed_103_, v_prec_102_);
lean_dec(v_prec_102_);
return v_res_104_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorIdx(uint8_t v_x_107_){
_start:
{
switch(v_x_107_)
{
case 0:
{
lean_object* v___x_108_; 
v___x_108_ = lean_unsigned_to_nat(0u);
return v___x_108_;
}
case 1:
{
lean_object* v___x_109_; 
v___x_109_ = lean_unsigned_to_nat(1u);
return v___x_109_;
}
case 2:
{
lean_object* v___x_110_; 
v___x_110_ = lean_unsigned_to_nat(2u);
return v___x_110_;
}
case 3:
{
lean_object* v___x_111_; 
v___x_111_ = lean_unsigned_to_nat(3u);
return v___x_111_;
}
case 4:
{
lean_object* v___x_112_; 
v___x_112_ = lean_unsigned_to_nat(4u);
return v___x_112_;
}
case 5:
{
lean_object* v___x_113_; 
v___x_113_ = lean_unsigned_to_nat(5u);
return v___x_113_;
}
case 6:
{
lean_object* v___x_114_; 
v___x_114_ = lean_unsigned_to_nat(6u);
return v___x_114_;
}
case 7:
{
lean_object* v___x_115_; 
v___x_115_ = lean_unsigned_to_nat(7u);
return v___x_115_;
}
case 8:
{
lean_object* v___x_116_; 
v___x_116_ = lean_unsigned_to_nat(8u);
return v___x_116_;
}
case 9:
{
lean_object* v___x_117_; 
v___x_117_ = lean_unsigned_to_nat(9u);
return v___x_117_;
}
case 10:
{
lean_object* v___x_118_; 
v___x_118_ = lean_unsigned_to_nat(10u);
return v___x_118_;
}
default: 
{
lean_object* v___x_119_; 
v___x_119_ = lean_unsigned_to_nat(11u);
return v___x_119_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorIdx___boxed(lean_object* v_x_120_){
_start:
{
uint8_t v_x_boxed_121_; lean_object* v_res_122_; 
v_x_boxed_121_ = lean_unbox(v_x_120_);
v_res_122_ = lp_nayose_Nayose_Field_ctorIdx(v_x_boxed_121_);
return v_res_122_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim___redArg(lean_object* v_k_123_){
_start:
{
lean_inc(v_k_123_);
return v_k_123_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim___redArg___boxed(lean_object* v_k_124_){
_start:
{
lean_object* v_res_125_; 
v_res_125_ = lp_nayose_Nayose_Field_ctorElim___redArg(v_k_124_);
lean_dec(v_k_124_);
return v_res_125_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim(lean_object* v_motive_126_, lean_object* v_ctorIdx_127_, uint8_t v_t_128_, lean_object* v_h_129_, lean_object* v_k_130_){
_start:
{
lean_inc(v_k_130_);
return v_k_130_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ctorElim___boxed(lean_object* v_motive_131_, lean_object* v_ctorIdx_132_, lean_object* v_t_133_, lean_object* v_h_134_, lean_object* v_k_135_){
_start:
{
uint8_t v_t_boxed_136_; lean_object* v_res_137_; 
v_t_boxed_136_ = lean_unbox(v_t_133_);
v_res_137_ = lp_nayose_Nayose_Field_ctorElim(v_motive_131_, v_ctorIdx_132_, v_t_boxed_136_, v_h_134_, v_k_135_);
lean_dec(v_k_135_);
lean_dec(v_ctorIdx_132_);
return v_res_137_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim___redArg(lean_object* v_kanaFull_138_){
_start:
{
lean_inc(v_kanaFull_138_);
return v_kanaFull_138_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim___redArg___boxed(lean_object* v_kanaFull_139_){
_start:
{
lean_object* v_res_140_; 
v_res_140_ = lp_nayose_Nayose_Field_kanaFull_elim___redArg(v_kanaFull_139_);
lean_dec(v_kanaFull_139_);
return v_res_140_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim(lean_object* v_motive_141_, uint8_t v_t_142_, lean_object* v_h_143_, lean_object* v_kanaFull_144_){
_start:
{
lean_inc(v_kanaFull_144_);
return v_kanaFull_144_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaFull_elim___boxed(lean_object* v_motive_145_, lean_object* v_t_146_, lean_object* v_h_147_, lean_object* v_kanaFull_148_){
_start:
{
uint8_t v_t_boxed_149_; lean_object* v_res_150_; 
v_t_boxed_149_ = lean_unbox(v_t_146_);
v_res_150_ = lp_nayose_Nayose_Field_kanaFull_elim(v_motive_145_, v_t_boxed_149_, v_h_147_, v_kanaFull_148_);
lean_dec(v_kanaFull_148_);
return v_res_150_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim___redArg(lean_object* v_kanaSur_151_){
_start:
{
lean_inc(v_kanaSur_151_);
return v_kanaSur_151_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim___redArg___boxed(lean_object* v_kanaSur_152_){
_start:
{
lean_object* v_res_153_; 
v_res_153_ = lp_nayose_Nayose_Field_kanaSur_elim___redArg(v_kanaSur_152_);
lean_dec(v_kanaSur_152_);
return v_res_153_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim(lean_object* v_motive_154_, uint8_t v_t_155_, lean_object* v_h_156_, lean_object* v_kanaSur_157_){
_start:
{
lean_inc(v_kanaSur_157_);
return v_kanaSur_157_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaSur_elim___boxed(lean_object* v_motive_158_, lean_object* v_t_159_, lean_object* v_h_160_, lean_object* v_kanaSur_161_){
_start:
{
uint8_t v_t_boxed_162_; lean_object* v_res_163_; 
v_t_boxed_162_ = lean_unbox(v_t_159_);
v_res_163_ = lp_nayose_Nayose_Field_kanaSur_elim(v_motive_158_, v_t_boxed_162_, v_h_160_, v_kanaSur_161_);
lean_dec(v_kanaSur_161_);
return v_res_163_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim___redArg(lean_object* v_kanaGiv_164_){
_start:
{
lean_inc(v_kanaGiv_164_);
return v_kanaGiv_164_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim___redArg___boxed(lean_object* v_kanaGiv_165_){
_start:
{
lean_object* v_res_166_; 
v_res_166_ = lp_nayose_Nayose_Field_kanaGiv_elim___redArg(v_kanaGiv_165_);
lean_dec(v_kanaGiv_165_);
return v_res_166_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim(lean_object* v_motive_167_, uint8_t v_t_168_, lean_object* v_h_169_, lean_object* v_kanaGiv_170_){
_start:
{
lean_inc(v_kanaGiv_170_);
return v_kanaGiv_170_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanaGiv_elim___boxed(lean_object* v_motive_171_, lean_object* v_t_172_, lean_object* v_h_173_, lean_object* v_kanaGiv_174_){
_start:
{
uint8_t v_t_boxed_175_; lean_object* v_res_176_; 
v_t_boxed_175_ = lean_unbox(v_t_172_);
v_res_176_ = lp_nayose_Nayose_Field_kanaGiv_elim(v_motive_171_, v_t_boxed_175_, v_h_173_, v_kanaGiv_174_);
lean_dec(v_kanaGiv_174_);
return v_res_176_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim___redArg(lean_object* v_kanjiFull_177_){
_start:
{
lean_inc(v_kanjiFull_177_);
return v_kanjiFull_177_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim___redArg___boxed(lean_object* v_kanjiFull_178_){
_start:
{
lean_object* v_res_179_; 
v_res_179_ = lp_nayose_Nayose_Field_kanjiFull_elim___redArg(v_kanjiFull_178_);
lean_dec(v_kanjiFull_178_);
return v_res_179_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim(lean_object* v_motive_180_, uint8_t v_t_181_, lean_object* v_h_182_, lean_object* v_kanjiFull_183_){
_start:
{
lean_inc(v_kanjiFull_183_);
return v_kanjiFull_183_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_kanjiFull_elim___boxed(lean_object* v_motive_184_, lean_object* v_t_185_, lean_object* v_h_186_, lean_object* v_kanjiFull_187_){
_start:
{
uint8_t v_t_boxed_188_; lean_object* v_res_189_; 
v_t_boxed_188_ = lean_unbox(v_t_185_);
v_res_189_ = lp_nayose_Nayose_Field_kanjiFull_elim(v_motive_184_, v_t_boxed_188_, v_h_186_, v_kanjiFull_187_);
lean_dec(v_kanjiFull_187_);
return v_res_189_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim___redArg(lean_object* v_dob_190_){
_start:
{
lean_inc(v_dob_190_);
return v_dob_190_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim___redArg___boxed(lean_object* v_dob_191_){
_start:
{
lean_object* v_res_192_; 
v_res_192_ = lp_nayose_Nayose_Field_dob_elim___redArg(v_dob_191_);
lean_dec(v_dob_191_);
return v_res_192_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim(lean_object* v_motive_193_, uint8_t v_t_194_, lean_object* v_h_195_, lean_object* v_dob_196_){
_start:
{
lean_inc(v_dob_196_);
return v_dob_196_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_dob_elim___boxed(lean_object* v_motive_197_, lean_object* v_t_198_, lean_object* v_h_199_, lean_object* v_dob_200_){
_start:
{
uint8_t v_t_boxed_201_; lean_object* v_res_202_; 
v_t_boxed_201_ = lean_unbox(v_t_198_);
v_res_202_ = lp_nayose_Nayose_Field_dob_elim(v_motive_197_, v_t_boxed_201_, v_h_199_, v_dob_200_);
lean_dec(v_dob_200_);
return v_res_202_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim___redArg(lean_object* v_gender_203_){
_start:
{
lean_inc(v_gender_203_);
return v_gender_203_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim___redArg___boxed(lean_object* v_gender_204_){
_start:
{
lean_object* v_res_205_; 
v_res_205_ = lp_nayose_Nayose_Field_gender_elim___redArg(v_gender_204_);
lean_dec(v_gender_204_);
return v_res_205_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim(lean_object* v_motive_206_, uint8_t v_t_207_, lean_object* v_h_208_, lean_object* v_gender_209_){
_start:
{
lean_inc(v_gender_209_);
return v_gender_209_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_gender_elim___boxed(lean_object* v_motive_210_, lean_object* v_t_211_, lean_object* v_h_212_, lean_object* v_gender_213_){
_start:
{
uint8_t v_t_boxed_214_; lean_object* v_res_215_; 
v_t_boxed_214_ = lean_unbox(v_t_211_);
v_res_215_ = lp_nayose_Nayose_Field_gender_elim(v_motive_210_, v_t_boxed_214_, v_h_212_, v_gender_213_);
lean_dec(v_gender_213_);
return v_res_215_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim___redArg(lean_object* v_cif_216_){
_start:
{
lean_inc(v_cif_216_);
return v_cif_216_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim___redArg___boxed(lean_object* v_cif_217_){
_start:
{
lean_object* v_res_218_; 
v_res_218_ = lp_nayose_Nayose_Field_cif_elim___redArg(v_cif_217_);
lean_dec(v_cif_217_);
return v_res_218_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim(lean_object* v_motive_219_, uint8_t v_t_220_, lean_object* v_h_221_, lean_object* v_cif_222_){
_start:
{
lean_inc(v_cif_222_);
return v_cif_222_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_cif_elim___boxed(lean_object* v_motive_223_, lean_object* v_t_224_, lean_object* v_h_225_, lean_object* v_cif_226_){
_start:
{
uint8_t v_t_boxed_227_; lean_object* v_res_228_; 
v_t_boxed_227_ = lean_unbox(v_t_224_);
v_res_228_ = lp_nayose_Nayose_Field_cif_elim(v_motive_223_, v_t_boxed_227_, v_h_225_, v_cif_226_);
lean_dec(v_cif_226_);
return v_res_228_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim___redArg(lean_object* v_ident_229_){
_start:
{
lean_inc(v_ident_229_);
return v_ident_229_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim___redArg___boxed(lean_object* v_ident_230_){
_start:
{
lean_object* v_res_231_; 
v_res_231_ = lp_nayose_Nayose_Field_ident_elim___redArg(v_ident_230_);
lean_dec(v_ident_230_);
return v_res_231_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim(lean_object* v_motive_232_, uint8_t v_t_233_, lean_object* v_h_234_, lean_object* v_ident_235_){
_start:
{
lean_inc(v_ident_235_);
return v_ident_235_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ident_elim___boxed(lean_object* v_motive_236_, lean_object* v_t_237_, lean_object* v_h_238_, lean_object* v_ident_239_){
_start:
{
uint8_t v_t_boxed_240_; lean_object* v_res_241_; 
v_t_boxed_240_ = lean_unbox(v_t_237_);
v_res_241_ = lp_nayose_Nayose_Field_ident_elim(v_motive_236_, v_t_boxed_240_, v_h_238_, v_ident_239_);
lean_dec(v_ident_239_);
return v_res_241_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim___redArg(lean_object* v_household_242_){
_start:
{
lean_inc(v_household_242_);
return v_household_242_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim___redArg___boxed(lean_object* v_household_243_){
_start:
{
lean_object* v_res_244_; 
v_res_244_ = lp_nayose_Nayose_Field_household_elim___redArg(v_household_243_);
lean_dec(v_household_243_);
return v_res_244_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim(lean_object* v_motive_245_, uint8_t v_t_246_, lean_object* v_h_247_, lean_object* v_household_248_){
_start:
{
lean_inc(v_household_248_);
return v_household_248_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_household_elim___boxed(lean_object* v_motive_249_, lean_object* v_t_250_, lean_object* v_h_251_, lean_object* v_household_252_){
_start:
{
uint8_t v_t_boxed_253_; lean_object* v_res_254_; 
v_t_boxed_253_ = lean_unbox(v_t_250_);
v_res_254_ = lp_nayose_Nayose_Field_household_elim(v_motive_249_, v_t_boxed_253_, v_h_251_, v_household_252_);
lean_dec(v_household_252_);
return v_res_254_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim___redArg(lean_object* v_age_255_){
_start:
{
lean_inc(v_age_255_);
return v_age_255_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim___redArg___boxed(lean_object* v_age_256_){
_start:
{
lean_object* v_res_257_; 
v_res_257_ = lp_nayose_Nayose_Field_age_elim___redArg(v_age_256_);
lean_dec(v_age_256_);
return v_res_257_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim(lean_object* v_motive_258_, uint8_t v_t_259_, lean_object* v_h_260_, lean_object* v_age_261_){
_start:
{
lean_inc(v_age_261_);
return v_age_261_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_age_elim___boxed(lean_object* v_motive_262_, lean_object* v_t_263_, lean_object* v_h_264_, lean_object* v_age_265_){
_start:
{
uint8_t v_t_boxed_266_; lean_object* v_res_267_; 
v_t_boxed_266_ = lean_unbox(v_t_263_);
v_res_267_ = lp_nayose_Nayose_Field_age_elim(v_motive_262_, v_t_boxed_266_, v_h_264_, v_age_265_);
lean_dec(v_age_265_);
return v_res_267_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim___redArg(lean_object* v_orgName_268_){
_start:
{
lean_inc(v_orgName_268_);
return v_orgName_268_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim___redArg___boxed(lean_object* v_orgName_269_){
_start:
{
lean_object* v_res_270_; 
v_res_270_ = lp_nayose_Nayose_Field_orgName_elim___redArg(v_orgName_269_);
lean_dec(v_orgName_269_);
return v_res_270_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim(lean_object* v_motive_271_, uint8_t v_t_272_, lean_object* v_h_273_, lean_object* v_orgName_274_){
_start:
{
lean_inc(v_orgName_274_);
return v_orgName_274_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgName_elim___boxed(lean_object* v_motive_275_, lean_object* v_t_276_, lean_object* v_h_277_, lean_object* v_orgName_278_){
_start:
{
uint8_t v_t_boxed_279_; lean_object* v_res_280_; 
v_t_boxed_279_ = lean_unbox(v_t_276_);
v_res_280_ = lp_nayose_Nayose_Field_orgName_elim(v_motive_275_, v_t_boxed_279_, v_h_277_, v_orgName_278_);
lean_dec(v_orgName_278_);
return v_res_280_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim___redArg(lean_object* v_orgForm_281_){
_start:
{
lean_inc(v_orgForm_281_);
return v_orgForm_281_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim___redArg___boxed(lean_object* v_orgForm_282_){
_start:
{
lean_object* v_res_283_; 
v_res_283_ = lp_nayose_Nayose_Field_orgForm_elim___redArg(v_orgForm_282_);
lean_dec(v_orgForm_282_);
return v_res_283_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim(lean_object* v_motive_284_, uint8_t v_t_285_, lean_object* v_h_286_, lean_object* v_orgForm_287_){
_start:
{
lean_inc(v_orgForm_287_);
return v_orgForm_287_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_orgForm_elim___boxed(lean_object* v_motive_288_, lean_object* v_t_289_, lean_object* v_h_290_, lean_object* v_orgForm_291_){
_start:
{
uint8_t v_t_boxed_292_; lean_object* v_res_293_; 
v_t_boxed_292_ = lean_unbox(v_t_289_);
v_res_293_ = lp_nayose_Nayose_Field_orgForm_elim(v_motive_288_, v_t_boxed_292_, v_h_290_, v_orgForm_291_);
lean_dec(v_orgForm_291_);
return v_res_293_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Field_ofNat(lean_object* v_n_294_){
_start:
{
lean_object* v___x_295_; uint8_t v___x_296_; 
v___x_295_ = lean_unsigned_to_nat(5u);
v___x_296_ = lean_nat_dec_le(v_n_294_, v___x_295_);
if (v___x_296_ == 0)
{
lean_object* v___x_297_; uint8_t v___x_298_; 
v___x_297_ = lean_unsigned_to_nat(8u);
v___x_298_ = lean_nat_dec_le(v_n_294_, v___x_297_);
if (v___x_298_ == 0)
{
lean_object* v___x_299_; uint8_t v___x_300_; 
v___x_299_ = lean_unsigned_to_nat(9u);
v___x_300_ = lean_nat_dec_le(v_n_294_, v___x_299_);
if (v___x_300_ == 0)
{
lean_object* v___x_301_; uint8_t v___x_302_; 
v___x_301_ = lean_unsigned_to_nat(10u);
v___x_302_ = lean_nat_dec_le(v_n_294_, v___x_301_);
if (v___x_302_ == 0)
{
uint8_t v___x_303_; 
v___x_303_ = 11;
return v___x_303_;
}
else
{
uint8_t v___x_304_; 
v___x_304_ = 10;
return v___x_304_;
}
}
else
{
uint8_t v___x_305_; 
v___x_305_ = 9;
return v___x_305_;
}
}
else
{
lean_object* v___x_306_; uint8_t v___x_307_; 
v___x_306_ = lean_unsigned_to_nat(6u);
v___x_307_ = lean_nat_dec_le(v_n_294_, v___x_306_);
if (v___x_307_ == 0)
{
lean_object* v___x_308_; uint8_t v___x_309_; 
v___x_308_ = lean_unsigned_to_nat(7u);
v___x_309_ = lean_nat_dec_le(v_n_294_, v___x_308_);
if (v___x_309_ == 0)
{
uint8_t v___x_310_; 
v___x_310_ = 8;
return v___x_310_;
}
else
{
uint8_t v___x_311_; 
v___x_311_ = 7;
return v___x_311_;
}
}
else
{
uint8_t v___x_312_; 
v___x_312_ = 6;
return v___x_312_;
}
}
}
else
{
lean_object* v___x_313_; uint8_t v___x_314_; 
v___x_313_ = lean_unsigned_to_nat(2u);
v___x_314_ = lean_nat_dec_le(v_n_294_, v___x_313_);
if (v___x_314_ == 0)
{
lean_object* v___x_315_; uint8_t v___x_316_; 
v___x_315_ = lean_unsigned_to_nat(3u);
v___x_316_ = lean_nat_dec_le(v_n_294_, v___x_315_);
if (v___x_316_ == 0)
{
lean_object* v___x_317_; uint8_t v___x_318_; 
v___x_317_ = lean_unsigned_to_nat(4u);
v___x_318_ = lean_nat_dec_le(v_n_294_, v___x_317_);
if (v___x_318_ == 0)
{
uint8_t v___x_319_; 
v___x_319_ = 5;
return v___x_319_;
}
else
{
uint8_t v___x_320_; 
v___x_320_ = 4;
return v___x_320_;
}
}
else
{
uint8_t v___x_321_; 
v___x_321_ = 3;
return v___x_321_;
}
}
else
{
lean_object* v___x_322_; uint8_t v___x_323_; 
v___x_322_ = lean_unsigned_to_nat(0u);
v___x_323_ = lean_nat_dec_le(v_n_294_, v___x_322_);
if (v___x_323_ == 0)
{
lean_object* v___x_324_; uint8_t v___x_325_; 
v___x_324_ = lean_unsigned_to_nat(1u);
v___x_325_ = lean_nat_dec_le(v_n_294_, v___x_324_);
if (v___x_325_ == 0)
{
uint8_t v___x_326_; 
v___x_326_ = 2;
return v___x_326_;
}
else
{
uint8_t v___x_327_; 
v___x_327_ = 1;
return v___x_327_;
}
}
else
{
uint8_t v___x_328_; 
v___x_328_ = 0;
return v___x_328_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Field_ofNat___boxed(lean_object* v_n_329_){
_start:
{
uint8_t v_res_330_; lean_object* v_r_331_; 
v_res_330_ = lp_nayose_Nayose_Field_ofNat(v_n_329_);
lean_dec(v_n_329_);
v_r_331_ = lean_box(v_res_330_);
return v_r_331_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_instDecidableEqField(uint8_t v_x_332_, uint8_t v_y_333_){
_start:
{
lean_object* v___x_334_; lean_object* v___x_335_; uint8_t v___x_336_; 
v___x_334_ = lp_nayose_Nayose_Field_ctorIdx(v_x_332_);
v___x_335_ = lp_nayose_Nayose_Field_ctorIdx(v_y_333_);
v___x_336_ = lean_nat_dec_eq(v___x_334_, v___x_335_);
lean_dec(v___x_335_);
lean_dec(v___x_334_);
return v___x_336_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instDecidableEqField___boxed(lean_object* v_x_337_, lean_object* v_y_338_){
_start:
{
uint8_t v_x_20__boxed_339_; uint8_t v_y_21__boxed_340_; uint8_t v_res_341_; lean_object* v_r_342_; 
v_x_20__boxed_339_ = lean_unbox(v_x_337_);
v_y_21__boxed_340_ = lean_unbox(v_y_338_);
v_res_341_ = lp_nayose_Nayose_instDecidableEqField(v_x_20__boxed_339_, v_y_21__boxed_340_);
v_r_342_ = lean_box(v_res_341_);
return v_r_342_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprField_repr(uint8_t v_x_379_, lean_object* v_prec_380_){
_start:
{
lean_object* v___y_382_; lean_object* v___y_389_; lean_object* v___y_396_; lean_object* v___y_403_; lean_object* v___y_410_; lean_object* v___y_417_; lean_object* v___y_424_; lean_object* v___y_431_; lean_object* v___y_438_; lean_object* v___y_445_; lean_object* v___y_452_; lean_object* v___y_459_; 
switch(v_x_379_)
{
case 0:
{
lean_object* v___x_465_; uint8_t v___x_466_; 
v___x_465_ = lean_unsigned_to_nat(1024u);
v___x_466_ = lean_nat_dec_le(v___x_465_, v_prec_380_);
if (v___x_466_ == 0)
{
lean_object* v___x_467_; 
v___x_467_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_382_ = v___x_467_;
goto v___jp_381_;
}
else
{
lean_object* v___x_468_; 
v___x_468_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_382_ = v___x_468_;
goto v___jp_381_;
}
}
case 1:
{
lean_object* v___x_469_; uint8_t v___x_470_; 
v___x_469_ = lean_unsigned_to_nat(1024u);
v___x_470_ = lean_nat_dec_le(v___x_469_, v_prec_380_);
if (v___x_470_ == 0)
{
lean_object* v___x_471_; 
v___x_471_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_389_ = v___x_471_;
goto v___jp_388_;
}
else
{
lean_object* v___x_472_; 
v___x_472_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_389_ = v___x_472_;
goto v___jp_388_;
}
}
case 2:
{
lean_object* v___x_473_; uint8_t v___x_474_; 
v___x_473_ = lean_unsigned_to_nat(1024u);
v___x_474_ = lean_nat_dec_le(v___x_473_, v_prec_380_);
if (v___x_474_ == 0)
{
lean_object* v___x_475_; 
v___x_475_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_396_ = v___x_475_;
goto v___jp_395_;
}
else
{
lean_object* v___x_476_; 
v___x_476_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_396_ = v___x_476_;
goto v___jp_395_;
}
}
case 3:
{
lean_object* v___x_477_; uint8_t v___x_478_; 
v___x_477_ = lean_unsigned_to_nat(1024u);
v___x_478_ = lean_nat_dec_le(v___x_477_, v_prec_380_);
if (v___x_478_ == 0)
{
lean_object* v___x_479_; 
v___x_479_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_403_ = v___x_479_;
goto v___jp_402_;
}
else
{
lean_object* v___x_480_; 
v___x_480_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_403_ = v___x_480_;
goto v___jp_402_;
}
}
case 4:
{
lean_object* v___x_481_; uint8_t v___x_482_; 
v___x_481_ = lean_unsigned_to_nat(1024u);
v___x_482_ = lean_nat_dec_le(v___x_481_, v_prec_380_);
if (v___x_482_ == 0)
{
lean_object* v___x_483_; 
v___x_483_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_410_ = v___x_483_;
goto v___jp_409_;
}
else
{
lean_object* v___x_484_; 
v___x_484_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_410_ = v___x_484_;
goto v___jp_409_;
}
}
case 5:
{
lean_object* v___x_485_; uint8_t v___x_486_; 
v___x_485_ = lean_unsigned_to_nat(1024u);
v___x_486_ = lean_nat_dec_le(v___x_485_, v_prec_380_);
if (v___x_486_ == 0)
{
lean_object* v___x_487_; 
v___x_487_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_417_ = v___x_487_;
goto v___jp_416_;
}
else
{
lean_object* v___x_488_; 
v___x_488_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_417_ = v___x_488_;
goto v___jp_416_;
}
}
case 6:
{
lean_object* v___x_489_; uint8_t v___x_490_; 
v___x_489_ = lean_unsigned_to_nat(1024u);
v___x_490_ = lean_nat_dec_le(v___x_489_, v_prec_380_);
if (v___x_490_ == 0)
{
lean_object* v___x_491_; 
v___x_491_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_424_ = v___x_491_;
goto v___jp_423_;
}
else
{
lean_object* v___x_492_; 
v___x_492_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_424_ = v___x_492_;
goto v___jp_423_;
}
}
case 7:
{
lean_object* v___x_493_; uint8_t v___x_494_; 
v___x_493_ = lean_unsigned_to_nat(1024u);
v___x_494_ = lean_nat_dec_le(v___x_493_, v_prec_380_);
if (v___x_494_ == 0)
{
lean_object* v___x_495_; 
v___x_495_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_431_ = v___x_495_;
goto v___jp_430_;
}
else
{
lean_object* v___x_496_; 
v___x_496_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_431_ = v___x_496_;
goto v___jp_430_;
}
}
case 8:
{
lean_object* v___x_497_; uint8_t v___x_498_; 
v___x_497_ = lean_unsigned_to_nat(1024u);
v___x_498_ = lean_nat_dec_le(v___x_497_, v_prec_380_);
if (v___x_498_ == 0)
{
lean_object* v___x_499_; 
v___x_499_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_438_ = v___x_499_;
goto v___jp_437_;
}
else
{
lean_object* v___x_500_; 
v___x_500_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_438_ = v___x_500_;
goto v___jp_437_;
}
}
case 9:
{
lean_object* v___x_501_; uint8_t v___x_502_; 
v___x_501_ = lean_unsigned_to_nat(1024u);
v___x_502_ = lean_nat_dec_le(v___x_501_, v_prec_380_);
if (v___x_502_ == 0)
{
lean_object* v___x_503_; 
v___x_503_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_445_ = v___x_503_;
goto v___jp_444_;
}
else
{
lean_object* v___x_504_; 
v___x_504_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_445_ = v___x_504_;
goto v___jp_444_;
}
}
case 10:
{
lean_object* v___x_505_; uint8_t v___x_506_; 
v___x_505_ = lean_unsigned_to_nat(1024u);
v___x_506_ = lean_nat_dec_le(v___x_505_, v_prec_380_);
if (v___x_506_ == 0)
{
lean_object* v___x_507_; 
v___x_507_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_452_ = v___x_507_;
goto v___jp_451_;
}
else
{
lean_object* v___x_508_; 
v___x_508_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_452_ = v___x_508_;
goto v___jp_451_;
}
}
default: 
{
lean_object* v___x_509_; uint8_t v___x_510_; 
v___x_509_ = lean_unsigned_to_nat(1024u);
v___x_510_ = lean_nat_dec_le(v___x_509_, v_prec_380_);
if (v___x_510_ == 0)
{
lean_object* v___x_511_; 
v___x_511_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_459_ = v___x_511_;
goto v___jp_458_;
}
else
{
lean_object* v___x_512_; 
v___x_512_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_459_ = v___x_512_;
goto v___jp_458_;
}
}
}
v___jp_381_:
{
lean_object* v___x_383_; lean_object* v___x_384_; uint8_t v___x_385_; lean_object* v___x_386_; lean_object* v___x_387_; 
v___x_383_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__1));
lean_inc(v___y_382_);
v___x_384_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_384_, 0, v___y_382_);
lean_ctor_set(v___x_384_, 1, v___x_383_);
v___x_385_ = 0;
v___x_386_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_386_, 0, v___x_384_);
lean_ctor_set_uint8(v___x_386_, sizeof(void*)*1, v___x_385_);
v___x_387_ = l_Repr_addAppParen(v___x_386_, v_prec_380_);
return v___x_387_;
}
v___jp_388_:
{
lean_object* v___x_390_; lean_object* v___x_391_; uint8_t v___x_392_; lean_object* v___x_393_; lean_object* v___x_394_; 
v___x_390_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__3));
lean_inc(v___y_389_);
v___x_391_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_391_, 0, v___y_389_);
lean_ctor_set(v___x_391_, 1, v___x_390_);
v___x_392_ = 0;
v___x_393_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_393_, 0, v___x_391_);
lean_ctor_set_uint8(v___x_393_, sizeof(void*)*1, v___x_392_);
v___x_394_ = l_Repr_addAppParen(v___x_393_, v_prec_380_);
return v___x_394_;
}
v___jp_395_:
{
lean_object* v___x_397_; lean_object* v___x_398_; uint8_t v___x_399_; lean_object* v___x_400_; lean_object* v___x_401_; 
v___x_397_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__5));
lean_inc(v___y_396_);
v___x_398_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_398_, 0, v___y_396_);
lean_ctor_set(v___x_398_, 1, v___x_397_);
v___x_399_ = 0;
v___x_400_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_400_, 0, v___x_398_);
lean_ctor_set_uint8(v___x_400_, sizeof(void*)*1, v___x_399_);
v___x_401_ = l_Repr_addAppParen(v___x_400_, v_prec_380_);
return v___x_401_;
}
v___jp_402_:
{
lean_object* v___x_404_; lean_object* v___x_405_; uint8_t v___x_406_; lean_object* v___x_407_; lean_object* v___x_408_; 
v___x_404_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__7));
lean_inc(v___y_403_);
v___x_405_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_405_, 0, v___y_403_);
lean_ctor_set(v___x_405_, 1, v___x_404_);
v___x_406_ = 0;
v___x_407_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_407_, 0, v___x_405_);
lean_ctor_set_uint8(v___x_407_, sizeof(void*)*1, v___x_406_);
v___x_408_ = l_Repr_addAppParen(v___x_407_, v_prec_380_);
return v___x_408_;
}
v___jp_409_:
{
lean_object* v___x_411_; lean_object* v___x_412_; uint8_t v___x_413_; lean_object* v___x_414_; lean_object* v___x_415_; 
v___x_411_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__9));
lean_inc(v___y_410_);
v___x_412_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_412_, 0, v___y_410_);
lean_ctor_set(v___x_412_, 1, v___x_411_);
v___x_413_ = 0;
v___x_414_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_414_, 0, v___x_412_);
lean_ctor_set_uint8(v___x_414_, sizeof(void*)*1, v___x_413_);
v___x_415_ = l_Repr_addAppParen(v___x_414_, v_prec_380_);
return v___x_415_;
}
v___jp_416_:
{
lean_object* v___x_418_; lean_object* v___x_419_; uint8_t v___x_420_; lean_object* v___x_421_; lean_object* v___x_422_; 
v___x_418_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__11));
lean_inc(v___y_417_);
v___x_419_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_419_, 0, v___y_417_);
lean_ctor_set(v___x_419_, 1, v___x_418_);
v___x_420_ = 0;
v___x_421_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_421_, 0, v___x_419_);
lean_ctor_set_uint8(v___x_421_, sizeof(void*)*1, v___x_420_);
v___x_422_ = l_Repr_addAppParen(v___x_421_, v_prec_380_);
return v___x_422_;
}
v___jp_423_:
{
lean_object* v___x_425_; lean_object* v___x_426_; uint8_t v___x_427_; lean_object* v___x_428_; lean_object* v___x_429_; 
v___x_425_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__13));
lean_inc(v___y_424_);
v___x_426_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_426_, 0, v___y_424_);
lean_ctor_set(v___x_426_, 1, v___x_425_);
v___x_427_ = 0;
v___x_428_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_428_, 0, v___x_426_);
lean_ctor_set_uint8(v___x_428_, sizeof(void*)*1, v___x_427_);
v___x_429_ = l_Repr_addAppParen(v___x_428_, v_prec_380_);
return v___x_429_;
}
v___jp_430_:
{
lean_object* v___x_432_; lean_object* v___x_433_; uint8_t v___x_434_; lean_object* v___x_435_; lean_object* v___x_436_; 
v___x_432_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__15));
lean_inc(v___y_431_);
v___x_433_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_433_, 0, v___y_431_);
lean_ctor_set(v___x_433_, 1, v___x_432_);
v___x_434_ = 0;
v___x_435_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_435_, 0, v___x_433_);
lean_ctor_set_uint8(v___x_435_, sizeof(void*)*1, v___x_434_);
v___x_436_ = l_Repr_addAppParen(v___x_435_, v_prec_380_);
return v___x_436_;
}
v___jp_437_:
{
lean_object* v___x_439_; lean_object* v___x_440_; uint8_t v___x_441_; lean_object* v___x_442_; lean_object* v___x_443_; 
v___x_439_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__17));
lean_inc(v___y_438_);
v___x_440_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_440_, 0, v___y_438_);
lean_ctor_set(v___x_440_, 1, v___x_439_);
v___x_441_ = 0;
v___x_442_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_442_, 0, v___x_440_);
lean_ctor_set_uint8(v___x_442_, sizeof(void*)*1, v___x_441_);
v___x_443_ = l_Repr_addAppParen(v___x_442_, v_prec_380_);
return v___x_443_;
}
v___jp_444_:
{
lean_object* v___x_446_; lean_object* v___x_447_; uint8_t v___x_448_; lean_object* v___x_449_; lean_object* v___x_450_; 
v___x_446_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__19));
lean_inc(v___y_445_);
v___x_447_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_447_, 0, v___y_445_);
lean_ctor_set(v___x_447_, 1, v___x_446_);
v___x_448_ = 0;
v___x_449_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_449_, 0, v___x_447_);
lean_ctor_set_uint8(v___x_449_, sizeof(void*)*1, v___x_448_);
v___x_450_ = l_Repr_addAppParen(v___x_449_, v_prec_380_);
return v___x_450_;
}
v___jp_451_:
{
lean_object* v___x_453_; lean_object* v___x_454_; uint8_t v___x_455_; lean_object* v___x_456_; lean_object* v___x_457_; 
v___x_453_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__21));
lean_inc(v___y_452_);
v___x_454_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_454_, 0, v___y_452_);
lean_ctor_set(v___x_454_, 1, v___x_453_);
v___x_455_ = 0;
v___x_456_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_456_, 0, v___x_454_);
lean_ctor_set_uint8(v___x_456_, sizeof(void*)*1, v___x_455_);
v___x_457_ = l_Repr_addAppParen(v___x_456_, v_prec_380_);
return v___x_457_;
}
v___jp_458_:
{
lean_object* v___x_460_; lean_object* v___x_461_; uint8_t v___x_462_; lean_object* v___x_463_; lean_object* v___x_464_; 
v___x_460_ = ((lean_object*)(lp_nayose_Nayose_instReprField_repr___closed__23));
lean_inc(v___y_459_);
v___x_461_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_461_, 0, v___y_459_);
lean_ctor_set(v___x_461_, 1, v___x_460_);
v___x_462_ = 0;
v___x_463_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_463_, 0, v___x_461_);
lean_ctor_set_uint8(v___x_463_, sizeof(void*)*1, v___x_462_);
v___x_464_ = l_Repr_addAppParen(v___x_463_, v_prec_380_);
return v___x_464_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprField_repr___boxed(lean_object* v_x_513_, lean_object* v_prec_514_){
_start:
{
uint8_t v_x_653__boxed_515_; lean_object* v_res_516_; 
v_x_653__boxed_515_ = lean_unbox(v_x_513_);
v_res_516_ = lp_nayose_Nayose_instReprField_repr(v_x_653__boxed_515_, v_prec_514_);
lean_dec(v_prec_514_);
return v_res_516_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_missing(void){
_start:
{
lean_object* v___x_519_; 
v___x_519_ = lean_unsigned_to_nat(0u);
return v___x_519_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_diff(void){
_start:
{
lean_object* v___x_520_; 
v___x_520_ = lean_unsigned_to_nat(1u);
return v___x_520_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_close(void){
_start:
{
lean_object* v___x_521_; 
v___x_521_ = lean_unsigned_to_nat(2u);
return v___x_521_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_swapped(void){
_start:
{
lean_object* v___x_522_; 
v___x_522_ = lean_unsigned_to_nat(3u);
return v___x_522_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_looseFull(void){
_start:
{
lean_object* v___x_523_; 
v___x_523_ = lean_unsigned_to_nat(4u);
return v___x_523_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_exactFull(void){
_start:
{
lean_object* v___x_524_; 
v___x_524_ = lean_unsigned_to_nat(5u);
return v___x_524_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_loosePart(void){
_start:
{
lean_object* v___x_525_; 
v___x_525_ = lean_unsigned_to_nat(3u);
return v___x_525_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_exactPart(void){
_start:
{
lean_object* v___x_526_; 
v___x_526_ = lean_unsigned_to_nat(4u);
return v___x_526_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_near(void){
_start:
{
lean_object* v___x_527_; 
v___x_527_ = lean_unsigned_to_nat(2u);
return v___x_527_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_dobExact(void){
_start:
{
lean_object* v___x_528_; 
v___x_528_ = lean_unsigned_to_nat(3u);
return v___x_528_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_same(void){
_start:
{
lean_object* v___x_529_; 
v___x_529_ = lean_unsigned_to_nat(2u);
return v___x_529_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_shared(void){
_start:
{
lean_object* v___x_530_; 
v___x_530_ = lean_unsigned_to_nat(2u);
return v___x_530_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_noneShared(void){
_start:
{
lean_object* v___x_531_; 
v___x_531_ = lean_unsigned_to_nat(2u);
return v___x_531_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_sharedOther(void){
_start:
{
lean_object* v___x_532_; 
v___x_532_ = lean_unsigned_to_nat(3u);
return v___x_532_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_sharedUnique(void){
_start:
{
lean_object* v___x_533_; 
v___x_533_ = lean_unsigned_to_nat(4u);
return v___x_533_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_variant(void){
_start:
{
lean_object* v___x_534_; 
v___x_534_ = lean_unsigned_to_nat(3u);
return v___x_534_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_kanjiExact(void){
_start:
{
lean_object* v___x_535_; 
v___x_535_ = lean_unsigned_to_nat(4u);
return v___x_535_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_normalized(void){
_start:
{
lean_object* v___x_536_; 
v___x_536_ = lean_unsigned_to_nat(3u);
return v___x_536_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_orgExact(void){
_start:
{
lean_object* v___x_537_; 
v___x_537_ = lean_unsigned_to_nat(4u);
return v___x_537_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_inconsistent(void){
_start:
{
lean_object* v___x_538_; 
v___x_538_ = lean_unsigned_to_nat(1u);
return v___x_538_;
}
}
static lean_object* _init_lp_nayose_Nayose_Lvl_consistent(void){
_start:
{
lean_object* v___x_539_; 
v___x_539_ = lean_unsigned_to_nat(2u);
return v___x_539_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_arity(uint8_t v_x_540_){
_start:
{
switch(v_x_540_)
{
case 0:
{
lean_object* v___x_541_; 
v___x_541_ = lean_unsigned_to_nat(5u);
return v___x_541_;
}
case 4:
{
lean_object* v___x_542_; 
v___x_542_ = lean_unsigned_to_nat(3u);
return v___x_542_;
}
case 5:
{
lean_object* v___x_543_; 
v___x_543_ = lean_unsigned_to_nat(2u);
return v___x_543_;
}
case 6:
{
lean_object* v___x_544_; 
v___x_544_ = lean_unsigned_to_nat(2u);
return v___x_544_;
}
case 8:
{
lean_object* v___x_545_; 
v___x_545_ = lean_unsigned_to_nat(2u);
return v___x_545_;
}
case 9:
{
lean_object* v___x_546_; 
v___x_546_ = lean_unsigned_to_nat(2u);
return v___x_546_;
}
case 11:
{
lean_object* v___x_547_; 
v___x_547_ = lean_unsigned_to_nat(2u);
return v___x_547_;
}
default: 
{
lean_object* v___x_548_; 
v___x_548_ = lean_unsigned_to_nat(4u);
return v___x_548_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_arity___boxed(lean_object* v_x_549_){
_start:
{
uint8_t v_x_84__boxed_550_; lean_object* v_res_551_; 
v_x_84__boxed_550_ = lean_unbox(v_x_549_);
v_res_551_ = lp_nayose_Nayose_arity(v_x_84__boxed_550_);
return v_res_551_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_corroborationThreshold(uint8_t v_x_556_){
_start:
{
switch(v_x_556_)
{
case 6:
{
goto v___jp_557_;
}
case 7:
{
lean_object* v___x_559_; 
v___x_559_ = ((lean_object*)(lp_nayose_Nayose_corroborationThreshold___closed__1));
return v___x_559_;
}
case 8:
{
goto v___jp_557_;
}
default: 
{
lean_object* v___x_560_; 
v___x_560_ = lean_box(0);
return v___x_560_;
}
}
v___jp_557_:
{
lean_object* v___x_558_; 
v___x_558_ = ((lean_object*)(lp_nayose_Nayose_corroborationThreshold___closed__0));
return v___x_558_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_corroborationThreshold___boxed(lean_object* v_x_561_){
_start:
{
uint8_t v_x_41__boxed_562_; lean_object* v_res_563_; 
v_x_41__boxed_562_ = lean_unbox(v_x_561_);
v_res_563_ = lp_nayose_Nayose_corroborationThreshold(v_x_41__boxed_562_);
return v_res_563_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Atom_fires(lean_object* v_a_564_, lean_object* v_p_565_){
_start:
{
lean_object* v_fst_566_; lean_object* v_snd_567_; lean_object* v_level_568_; lean_object* v___x_569_; uint8_t v___x_570_; 
v_fst_566_ = lean_ctor_get(v_a_564_, 0);
lean_inc(v_fst_566_);
v_snd_567_ = lean_ctor_get(v_a_564_, 1);
lean_inc(v_snd_567_);
lean_dec_ref(v_a_564_);
v_level_568_ = lean_ctor_get(v_p_565_, 0);
lean_inc_ref(v_level_568_);
lean_dec_ref(v_p_565_);
v___x_569_ = lean_apply_1(v_level_568_, v_fst_566_);
v___x_570_ = lean_nat_dec_le(v_snd_567_, v___x_569_);
lean_dec(v___x_569_);
lean_dec(v_snd_567_);
return v___x_570_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Atom_fires___boxed(lean_object* v_a_571_, lean_object* v_p_572_){
_start:
{
uint8_t v_res_573_; lean_object* v_r_574_; 
v_res_573_ = lp_nayose_Nayose_Atom_fires(v_a_571_, v_p_572_);
v_r_574_ = lean_box(v_res_573_);
return v_r_574_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Atom_isCorroboration(lean_object* v_a_575_){
_start:
{
lean_object* v_fst_576_; lean_object* v_snd_577_; uint8_t v___x_578_; lean_object* v___x_579_; 
v_fst_576_ = lean_ctor_get(v_a_575_, 0);
v_snd_577_ = lean_ctor_get(v_a_575_, 1);
v___x_578_ = lean_unbox(v_fst_576_);
v___x_579_ = lp_nayose_Nayose_corroborationThreshold(v___x_578_);
if (lean_obj_tag(v___x_579_) == 0)
{
uint8_t v___x_580_; 
v___x_580_ = 0;
return v___x_580_;
}
else
{
lean_object* v_val_581_; uint8_t v___x_582_; 
v_val_581_ = lean_ctor_get(v___x_579_, 0);
lean_inc(v_val_581_);
lean_dec_ref_known(v___x_579_, 1);
v___x_582_ = lean_nat_dec_le(v_val_581_, v_snd_577_);
lean_dec(v_val_581_);
return v___x_582_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Atom_isCorroboration___boxed(lean_object* v_a_583_){
_start:
{
uint8_t v_res_584_; lean_object* v_r_585_; 
v_res_584_ = lp_nayose_Nayose_Atom_isCorroboration(v_a_583_);
lean_dec_ref(v_a_583_);
v_r_585_ = lean_box(v_res_584_);
return v_r_585_;
}
}
static lean_object* _init_lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__5(void){
_start:
{
lean_object* v___x_594_; lean_object* v___x_595_; 
v___x_594_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__0));
v___x_595_ = lean_string_length(v___x_594_);
return v___x_595_;
}
}
static lean_object* _init_lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__6(void){
_start:
{
lean_object* v___x_596_; lean_object* v___x_597_; 
v___x_596_ = lean_obj_once(&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__5, &lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__5_once, _init_lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__5);
v___x_597_ = lean_nat_to_int(v___x_596_);
return v___x_597_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(lean_object* v_x_602_){
_start:
{
lean_object* v_fst_603_; lean_object* v_snd_604_; lean_object* v___x_606_; uint8_t v_isShared_607_; uint8_t v_isSharedCheck_629_; 
v_fst_603_ = lean_ctor_get(v_x_602_, 0);
v_snd_604_ = lean_ctor_get(v_x_602_, 1);
v_isSharedCheck_629_ = !lean_is_exclusive(v_x_602_);
if (v_isSharedCheck_629_ == 0)
{
v___x_606_ = v_x_602_;
v_isShared_607_ = v_isSharedCheck_629_;
goto v_resetjp_605_;
}
else
{
lean_inc(v_snd_604_);
lean_inc(v_fst_603_);
lean_dec(v_x_602_);
v___x_606_ = lean_box(0);
v_isShared_607_ = v_isSharedCheck_629_;
goto v_resetjp_605_;
}
v_resetjp_605_:
{
lean_object* v___x_608_; uint8_t v___x_609_; lean_object* v___x_610_; lean_object* v___x_611_; lean_object* v___x_613_; 
v___x_608_ = lean_unsigned_to_nat(0u);
v___x_609_ = lean_unbox(v_fst_603_);
lean_dec(v_fst_603_);
v___x_610_ = lp_nayose_Nayose_instReprField_repr(v___x_609_, v___x_608_);
v___x_611_ = lean_box(0);
if (v_isShared_607_ == 0)
{
lean_ctor_set_tag(v___x_606_, 1);
lean_ctor_set(v___x_606_, 1, v___x_611_);
lean_ctor_set(v___x_606_, 0, v___x_610_);
v___x_613_ = v___x_606_;
goto v_reusejp_612_;
}
else
{
lean_object* v_reuseFailAlloc_628_; 
v_reuseFailAlloc_628_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_628_, 0, v___x_610_);
lean_ctor_set(v_reuseFailAlloc_628_, 1, v___x_611_);
v___x_613_ = v_reuseFailAlloc_628_;
goto v_reusejp_612_;
}
v_reusejp_612_:
{
lean_object* v___x_614_; lean_object* v___x_615_; lean_object* v___x_616_; lean_object* v___x_617_; lean_object* v___x_618_; lean_object* v___x_619_; lean_object* v___x_620_; lean_object* v___x_621_; lean_object* v___x_622_; lean_object* v___x_623_; lean_object* v___x_624_; lean_object* v___x_625_; uint8_t v___x_626_; lean_object* v___x_627_; 
v___x_614_ = l_Nat_reprFast(v_snd_604_);
v___x_615_ = lean_alloc_ctor(3, 1, 0);
lean_ctor_set(v___x_615_, 0, v___x_614_);
v___x_616_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v___x_616_, 0, v___x_615_);
lean_ctor_set(v___x_616_, 1, v___x_613_);
v___x_617_ = l_List_reverse___redArg(v___x_616_);
v___x_618_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3));
v___x_619_ = l_Std_Format_joinSep___at___00Lean_Syntax_formatStxAux_spec__2(v___x_617_, v___x_618_);
v___x_620_ = lean_obj_once(&lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__6, &lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__6_once, _init_lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__6);
v___x_621_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__7));
v___x_622_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_622_, 0, v___x_621_);
lean_ctor_set(v___x_622_, 1, v___x_619_);
v___x_623_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__8));
v___x_624_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_624_, 0, v___x_622_);
lean_ctor_set(v___x_624_, 1, v___x_623_);
v___x_625_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_625_, 0, v___x_620_);
lean_ctor_set(v___x_625_, 1, v___x_624_);
v___x_626_ = 0;
v___x_627_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_627_, 0, v___x_625_);
lean_ctor_set_uint8(v___x_627_, sizeof(void*)*1, v___x_626_);
return v___x_627_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3_spec__5_spec__8(lean_object* v_x_630_, lean_object* v_x_631_, lean_object* v_x_632_){
_start:
{
if (lean_obj_tag(v_x_632_) == 0)
{
lean_dec(v_x_630_);
return v_x_631_;
}
else
{
lean_object* v_head_633_; lean_object* v_tail_634_; lean_object* v___x_636_; uint8_t v_isShared_637_; uint8_t v_isSharedCheck_644_; 
v_head_633_ = lean_ctor_get(v_x_632_, 0);
v_tail_634_ = lean_ctor_get(v_x_632_, 1);
v_isSharedCheck_644_ = !lean_is_exclusive(v_x_632_);
if (v_isSharedCheck_644_ == 0)
{
v___x_636_ = v_x_632_;
v_isShared_637_ = v_isSharedCheck_644_;
goto v_resetjp_635_;
}
else
{
lean_inc(v_tail_634_);
lean_inc(v_head_633_);
lean_dec(v_x_632_);
v___x_636_ = lean_box(0);
v_isShared_637_ = v_isSharedCheck_644_;
goto v_resetjp_635_;
}
v_resetjp_635_:
{
lean_object* v___x_639_; 
lean_inc(v_x_630_);
if (v_isShared_637_ == 0)
{
lean_ctor_set_tag(v___x_636_, 5);
lean_ctor_set(v___x_636_, 1, v_x_630_);
lean_ctor_set(v___x_636_, 0, v_x_631_);
v___x_639_ = v___x_636_;
goto v_reusejp_638_;
}
else
{
lean_object* v_reuseFailAlloc_643_; 
v_reuseFailAlloc_643_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_643_, 0, v_x_631_);
lean_ctor_set(v_reuseFailAlloc_643_, 1, v_x_630_);
v___x_639_ = v_reuseFailAlloc_643_;
goto v_reusejp_638_;
}
v_reusejp_638_:
{
lean_object* v___x_640_; lean_object* v___x_641_; 
v___x_640_ = lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(v_head_633_);
v___x_641_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_641_, 0, v___x_639_);
lean_ctor_set(v___x_641_, 1, v___x_640_);
v_x_631_ = v___x_641_;
v_x_632_ = v_tail_634_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3_spec__5(lean_object* v_x_645_, lean_object* v_x_646_, lean_object* v_x_647_){
_start:
{
if (lean_obj_tag(v_x_647_) == 0)
{
lean_dec(v_x_645_);
return v_x_646_;
}
else
{
lean_object* v_head_648_; lean_object* v_tail_649_; lean_object* v___x_651_; uint8_t v_isShared_652_; uint8_t v_isSharedCheck_659_; 
v_head_648_ = lean_ctor_get(v_x_647_, 0);
v_tail_649_ = lean_ctor_get(v_x_647_, 1);
v_isSharedCheck_659_ = !lean_is_exclusive(v_x_647_);
if (v_isSharedCheck_659_ == 0)
{
v___x_651_ = v_x_647_;
v_isShared_652_ = v_isSharedCheck_659_;
goto v_resetjp_650_;
}
else
{
lean_inc(v_tail_649_);
lean_inc(v_head_648_);
lean_dec(v_x_647_);
v___x_651_ = lean_box(0);
v_isShared_652_ = v_isSharedCheck_659_;
goto v_resetjp_650_;
}
v_resetjp_650_:
{
lean_object* v___x_654_; 
lean_inc(v_x_645_);
if (v_isShared_652_ == 0)
{
lean_ctor_set_tag(v___x_651_, 5);
lean_ctor_set(v___x_651_, 1, v_x_645_);
lean_ctor_set(v___x_651_, 0, v_x_646_);
v___x_654_ = v___x_651_;
goto v_reusejp_653_;
}
else
{
lean_object* v_reuseFailAlloc_658_; 
v_reuseFailAlloc_658_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_658_, 0, v_x_646_);
lean_ctor_set(v_reuseFailAlloc_658_, 1, v_x_645_);
v___x_654_ = v_reuseFailAlloc_658_;
goto v_reusejp_653_;
}
v_reusejp_653_:
{
lean_object* v___x_655_; lean_object* v___x_656_; lean_object* v___x_657_; 
v___x_655_ = lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(v_head_648_);
v___x_656_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_656_, 0, v___x_654_);
lean_ctor_set(v___x_656_, 1, v___x_655_);
v___x_657_ = lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3_spec__5_spec__8(v_x_645_, v___x_656_, v_tail_649_);
return v___x_657_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3(lean_object* v_x_660_, lean_object* v_x_661_){
_start:
{
if (lean_obj_tag(v_x_660_) == 0)
{
lean_object* v___x_662_; 
lean_dec(v_x_661_);
v___x_662_ = lean_box(0);
return v___x_662_;
}
else
{
lean_object* v_tail_663_; 
v_tail_663_ = lean_ctor_get(v_x_660_, 1);
if (lean_obj_tag(v_tail_663_) == 0)
{
lean_object* v_head_664_; lean_object* v___x_665_; 
lean_dec(v_x_661_);
v_head_664_ = lean_ctor_get(v_x_660_, 0);
lean_inc(v_head_664_);
lean_dec_ref_known(v_x_660_, 2);
v___x_665_ = lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(v_head_664_);
return v___x_665_;
}
else
{
lean_object* v_head_666_; lean_object* v___x_667_; lean_object* v___x_668_; 
lean_inc(v_tail_663_);
v_head_666_ = lean_ctor_get(v_x_660_, 0);
lean_inc(v_head_666_);
lean_dec_ref_known(v_x_660_, 2);
v___x_667_ = lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(v_head_666_);
v___x_668_ = lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3_spec__5(v_x_661_, v___x_667_, v_tail_663_);
return v___x_668_;
}
}
}
}
static lean_object* _init_lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__4(void){
_start:
{
lean_object* v___x_674_; lean_object* v___x_675_; 
v___x_674_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__2));
v___x_675_ = lean_string_length(v___x_674_);
return v___x_675_;
}
}
static lean_object* _init_lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5(void){
_start:
{
lean_object* v___x_676_; lean_object* v___x_677_; 
v___x_676_ = lean_obj_once(&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__4, &lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__4_once, _init_lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__4);
v___x_677_ = lean_nat_to_int(v___x_676_);
return v___x_677_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(lean_object* v_a_682_){
_start:
{
if (lean_obj_tag(v_a_682_) == 0)
{
lean_object* v___x_683_; 
v___x_683_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__1));
return v___x_683_;
}
else
{
lean_object* v___x_684_; lean_object* v___x_685_; lean_object* v___x_686_; lean_object* v___x_687_; lean_object* v___x_688_; lean_object* v___x_689_; lean_object* v___x_690_; lean_object* v___x_691_; uint8_t v___x_692_; lean_object* v___x_693_; 
v___x_684_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3));
v___x_685_ = lp_nayose_Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__3(v_a_682_, v___x_684_);
v___x_686_ = lean_obj_once(&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5, &lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5_once, _init_lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5);
v___x_687_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__6));
v___x_688_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_688_, 0, v___x_687_);
lean_ctor_set(v___x_688_, 1, v___x_685_);
v___x_689_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__7));
v___x_690_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_690_, 0, v___x_688_);
lean_ctor_set(v___x_690_, 1, v___x_689_);
v___x_691_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_691_, 0, v___x_686_);
lean_ctor_set(v___x_691_, 1, v___x_690_);
v___x_692_ = 0;
v___x_693_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_693_, 0, v___x_691_);
lean_ctor_set_uint8(v___x_693_, sizeof(void*)*1, v___x_692_);
return v___x_693_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2_spec__5_spec__8(lean_object* v_x_694_, lean_object* v_x_695_, lean_object* v_x_696_){
_start:
{
if (lean_obj_tag(v_x_696_) == 0)
{
lean_dec(v_x_694_);
return v_x_695_;
}
else
{
lean_object* v_head_697_; lean_object* v_tail_698_; lean_object* v___x_700_; uint8_t v_isShared_701_; uint8_t v_isSharedCheck_708_; 
v_head_697_ = lean_ctor_get(v_x_696_, 0);
v_tail_698_ = lean_ctor_get(v_x_696_, 1);
v_isSharedCheck_708_ = !lean_is_exclusive(v_x_696_);
if (v_isSharedCheck_708_ == 0)
{
v___x_700_ = v_x_696_;
v_isShared_701_ = v_isSharedCheck_708_;
goto v_resetjp_699_;
}
else
{
lean_inc(v_tail_698_);
lean_inc(v_head_697_);
lean_dec(v_x_696_);
v___x_700_ = lean_box(0);
v_isShared_701_ = v_isSharedCheck_708_;
goto v_resetjp_699_;
}
v_resetjp_699_:
{
lean_object* v___x_703_; 
lean_inc(v_x_694_);
if (v_isShared_701_ == 0)
{
lean_ctor_set_tag(v___x_700_, 5);
lean_ctor_set(v___x_700_, 1, v_x_694_);
lean_ctor_set(v___x_700_, 0, v_x_695_);
v___x_703_ = v___x_700_;
goto v_reusejp_702_;
}
else
{
lean_object* v_reuseFailAlloc_707_; 
v_reuseFailAlloc_707_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_707_, 0, v_x_695_);
lean_ctor_set(v_reuseFailAlloc_707_, 1, v_x_694_);
v___x_703_ = v_reuseFailAlloc_707_;
goto v_reusejp_702_;
}
v_reusejp_702_:
{
lean_object* v___x_704_; lean_object* v___x_705_; 
v___x_704_ = lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(v_head_697_);
v___x_705_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_705_, 0, v___x_703_);
lean_ctor_set(v___x_705_, 1, v___x_704_);
v_x_695_ = v___x_705_;
v_x_696_ = v_tail_698_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2_spec__5(lean_object* v_x_709_, lean_object* v_x_710_, lean_object* v_x_711_){
_start:
{
if (lean_obj_tag(v_x_711_) == 0)
{
lean_dec(v_x_709_);
return v_x_710_;
}
else
{
lean_object* v_head_712_; lean_object* v_tail_713_; lean_object* v___x_715_; uint8_t v_isShared_716_; uint8_t v_isSharedCheck_723_; 
v_head_712_ = lean_ctor_get(v_x_711_, 0);
v_tail_713_ = lean_ctor_get(v_x_711_, 1);
v_isSharedCheck_723_ = !lean_is_exclusive(v_x_711_);
if (v_isSharedCheck_723_ == 0)
{
v___x_715_ = v_x_711_;
v_isShared_716_ = v_isSharedCheck_723_;
goto v_resetjp_714_;
}
else
{
lean_inc(v_tail_713_);
lean_inc(v_head_712_);
lean_dec(v_x_711_);
v___x_715_ = lean_box(0);
v_isShared_716_ = v_isSharedCheck_723_;
goto v_resetjp_714_;
}
v_resetjp_714_:
{
lean_object* v___x_718_; 
lean_inc(v_x_709_);
if (v_isShared_716_ == 0)
{
lean_ctor_set_tag(v___x_715_, 5);
lean_ctor_set(v___x_715_, 1, v_x_709_);
lean_ctor_set(v___x_715_, 0, v_x_710_);
v___x_718_ = v___x_715_;
goto v_reusejp_717_;
}
else
{
lean_object* v_reuseFailAlloc_722_; 
v_reuseFailAlloc_722_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_722_, 0, v_x_710_);
lean_ctor_set(v_reuseFailAlloc_722_, 1, v_x_709_);
v___x_718_ = v_reuseFailAlloc_722_;
goto v_reusejp_717_;
}
v_reusejp_717_:
{
lean_object* v___x_719_; lean_object* v___x_720_; lean_object* v___x_721_; 
v___x_719_ = lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(v_head_712_);
v___x_720_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_720_, 0, v___x_718_);
lean_ctor_set(v___x_720_, 1, v___x_719_);
v___x_721_ = lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2_spec__5_spec__8(v_x_709_, v___x_720_, v_tail_713_);
return v___x_721_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2(lean_object* v_x_724_, lean_object* v_x_725_){
_start:
{
if (lean_obj_tag(v_x_724_) == 0)
{
lean_object* v___x_726_; 
lean_dec(v_x_725_);
v___x_726_ = lean_box(0);
return v___x_726_;
}
else
{
lean_object* v_tail_727_; 
v_tail_727_ = lean_ctor_get(v_x_724_, 1);
if (lean_obj_tag(v_tail_727_) == 0)
{
lean_object* v_head_728_; lean_object* v___x_729_; 
lean_dec(v_x_725_);
v_head_728_ = lean_ctor_get(v_x_724_, 0);
lean_inc(v_head_728_);
lean_dec_ref_known(v_x_724_, 2);
v___x_729_ = lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(v_head_728_);
return v___x_729_;
}
else
{
lean_object* v_head_730_; lean_object* v___x_731_; lean_object* v___x_732_; 
lean_inc(v_tail_727_);
v_head_730_ = lean_ctor_get(v_x_724_, 0);
lean_inc(v_head_730_);
lean_dec_ref_known(v_x_724_, 2);
v___x_731_ = lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(v_head_730_);
v___x_732_ = lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2_spec__5(v_x_725_, v___x_731_, v_tail_727_);
return v___x_732_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(lean_object* v_a_733_){
_start:
{
if (lean_obj_tag(v_a_733_) == 0)
{
lean_object* v___x_734_; 
v___x_734_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__1));
return v___x_734_;
}
else
{
lean_object* v___x_735_; lean_object* v___x_736_; lean_object* v___x_737_; lean_object* v___x_738_; lean_object* v___x_739_; lean_object* v___x_740_; lean_object* v___x_741_; lean_object* v___x_742_; uint8_t v___x_743_; lean_object* v___x_744_; 
v___x_735_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3));
v___x_736_ = lp_nayose_Std_Format_joinSep___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__2(v_a_733_, v___x_735_);
v___x_737_ = lean_obj_once(&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5, &lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5_once, _init_lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5);
v___x_738_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__6));
v___x_739_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_739_, 0, v___x_738_);
lean_ctor_set(v___x_739_, 1, v___x_736_);
v___x_740_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__7));
v___x_741_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_741_, 0, v___x_739_);
lean_ctor_set(v___x_741_, 1, v___x_740_);
v___x_742_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_742_, 0, v___x_737_);
lean_ctor_set(v___x_742_, 1, v___x_741_);
v___x_743_ = 0;
v___x_744_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_744_, 0, v___x_742_);
lean_ctor_set_uint8(v___x_744_, sizeof(void*)*1, v___x_743_);
return v___x_744_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1_spec__4_spec__8(lean_object* v_x_745_, lean_object* v_x_746_, lean_object* v_x_747_){
_start:
{
if (lean_obj_tag(v_x_747_) == 0)
{
lean_dec(v_x_745_);
return v_x_746_;
}
else
{
lean_object* v_head_748_; lean_object* v_tail_749_; lean_object* v___x_751_; uint8_t v_isShared_752_; uint8_t v_isSharedCheck_759_; 
v_head_748_ = lean_ctor_get(v_x_747_, 0);
v_tail_749_ = lean_ctor_get(v_x_747_, 1);
v_isSharedCheck_759_ = !lean_is_exclusive(v_x_747_);
if (v_isSharedCheck_759_ == 0)
{
v___x_751_ = v_x_747_;
v_isShared_752_ = v_isSharedCheck_759_;
goto v_resetjp_750_;
}
else
{
lean_inc(v_tail_749_);
lean_inc(v_head_748_);
lean_dec(v_x_747_);
v___x_751_ = lean_box(0);
v_isShared_752_ = v_isSharedCheck_759_;
goto v_resetjp_750_;
}
v_resetjp_750_:
{
lean_object* v___x_754_; 
lean_inc(v_x_745_);
if (v_isShared_752_ == 0)
{
lean_ctor_set_tag(v___x_751_, 5);
lean_ctor_set(v___x_751_, 1, v_x_745_);
lean_ctor_set(v___x_751_, 0, v_x_746_);
v___x_754_ = v___x_751_;
goto v_reusejp_753_;
}
else
{
lean_object* v_reuseFailAlloc_758_; 
v_reuseFailAlloc_758_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_758_, 0, v_x_746_);
lean_ctor_set(v_reuseFailAlloc_758_, 1, v_x_745_);
v___x_754_ = v_reuseFailAlloc_758_;
goto v_reusejp_753_;
}
v_reusejp_753_:
{
lean_object* v___x_755_; lean_object* v___x_756_; 
v___x_755_ = lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(v_head_748_);
v___x_756_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_756_, 0, v___x_754_);
lean_ctor_set(v___x_756_, 1, v___x_755_);
v_x_746_ = v___x_756_;
v_x_747_ = v_tail_749_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1_spec__4(lean_object* v_x_760_, lean_object* v_x_761_, lean_object* v_x_762_){
_start:
{
if (lean_obj_tag(v_x_762_) == 0)
{
lean_dec(v_x_760_);
return v_x_761_;
}
else
{
lean_object* v_head_763_; lean_object* v_tail_764_; lean_object* v___x_766_; uint8_t v_isShared_767_; uint8_t v_isSharedCheck_774_; 
v_head_763_ = lean_ctor_get(v_x_762_, 0);
v_tail_764_ = lean_ctor_get(v_x_762_, 1);
v_isSharedCheck_774_ = !lean_is_exclusive(v_x_762_);
if (v_isSharedCheck_774_ == 0)
{
v___x_766_ = v_x_762_;
v_isShared_767_ = v_isSharedCheck_774_;
goto v_resetjp_765_;
}
else
{
lean_inc(v_tail_764_);
lean_inc(v_head_763_);
lean_dec(v_x_762_);
v___x_766_ = lean_box(0);
v_isShared_767_ = v_isSharedCheck_774_;
goto v_resetjp_765_;
}
v_resetjp_765_:
{
lean_object* v___x_769_; 
lean_inc(v_x_760_);
if (v_isShared_767_ == 0)
{
lean_ctor_set_tag(v___x_766_, 5);
lean_ctor_set(v___x_766_, 1, v_x_760_);
lean_ctor_set(v___x_766_, 0, v_x_761_);
v___x_769_ = v___x_766_;
goto v_reusejp_768_;
}
else
{
lean_object* v_reuseFailAlloc_773_; 
v_reuseFailAlloc_773_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v_reuseFailAlloc_773_, 0, v_x_761_);
lean_ctor_set(v_reuseFailAlloc_773_, 1, v_x_760_);
v___x_769_ = v_reuseFailAlloc_773_;
goto v_reusejp_768_;
}
v_reusejp_768_:
{
lean_object* v___x_770_; lean_object* v___x_771_; lean_object* v___x_772_; 
v___x_770_ = lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(v_head_763_);
v___x_771_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_771_, 0, v___x_769_);
lean_ctor_set(v___x_771_, 1, v___x_770_);
v___x_772_ = lp_nayose_List_foldl___at___00List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1_spec__4_spec__8(v_x_760_, v___x_771_, v_tail_764_);
return v___x_772_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1(lean_object* v_x_775_, lean_object* v_x_776_){
_start:
{
if (lean_obj_tag(v_x_775_) == 0)
{
lean_object* v___x_777_; 
lean_dec(v_x_776_);
v___x_777_ = lean_box(0);
return v___x_777_;
}
else
{
lean_object* v_tail_778_; 
v_tail_778_ = lean_ctor_get(v_x_775_, 1);
if (lean_obj_tag(v_tail_778_) == 0)
{
lean_object* v_head_779_; lean_object* v___x_780_; 
lean_dec(v_x_776_);
v_head_779_ = lean_ctor_get(v_x_775_, 0);
lean_inc(v_head_779_);
lean_dec_ref_known(v_x_775_, 2);
v___x_780_ = lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(v_head_779_);
return v___x_780_;
}
else
{
lean_object* v_head_781_; lean_object* v___x_782_; lean_object* v___x_783_; 
lean_inc(v_tail_778_);
v_head_781_ = lean_ctor_get(v_x_775_, 0);
lean_inc(v_head_781_);
lean_dec_ref_known(v_x_775_, 2);
v___x_782_ = lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(v_head_781_);
v___x_783_ = lp_nayose_List_foldl___at___00Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1_spec__4(v_x_776_, v___x_782_, v_tail_778_);
return v___x_783_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0___redArg(lean_object* v_a_784_){
_start:
{
if (lean_obj_tag(v_a_784_) == 0)
{
lean_object* v___x_785_; 
v___x_785_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__1));
return v___x_785_;
}
else
{
lean_object* v___x_786_; lean_object* v___x_787_; lean_object* v___x_788_; lean_object* v___x_789_; lean_object* v___x_790_; lean_object* v___x_791_; lean_object* v___x_792_; lean_object* v___x_793_; uint8_t v___x_794_; lean_object* v___x_795_; 
v___x_786_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__3));
v___x_787_ = lp_nayose_Std_Format_joinSep___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__1(v_a_784_, v___x_786_);
v___x_788_ = lean_obj_once(&lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5, &lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5_once, _init_lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__5);
v___x_789_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__6));
v___x_790_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_790_, 0, v___x_789_);
lean_ctor_set(v___x_790_, 1, v___x_787_);
v___x_791_ = ((lean_object*)(lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg___closed__7));
v___x_792_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_792_, 0, v___x_790_);
lean_ctor_set(v___x_792_, 1, v___x_791_);
v___x_793_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_793_, 0, v___x_788_);
lean_ctor_set(v___x_793_, 1, v___x_792_);
v___x_794_ = 0;
v___x_795_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_795_, 0, v___x_793_);
lean_ctor_set_uint8(v___x_795_, sizeof(void*)*1, v___x_794_);
return v___x_795_;
}
}
}
static lean_object* _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__7(void){
_start:
{
lean_object* v___x_809_; lean_object* v___x_810_; 
v___x_809_ = lean_unsigned_to_nat(8u);
v___x_810_ = lean_nat_to_int(v___x_809_);
return v___x_810_;
}
}
static lean_object* _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__12(void){
_start:
{
lean_object* v___x_817_; lean_object* v___x_818_; 
v___x_817_ = lean_unsigned_to_nat(10u);
v___x_818_ = lean_nat_to_int(v___x_817_);
return v___x_818_;
}
}
static lean_object* _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__14(void){
_start:
{
lean_object* v___x_820_; lean_object* v___x_821_; 
v___x_820_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__0));
v___x_821_ = lean_string_length(v___x_820_);
return v___x_821_;
}
}
static lean_object* _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__15(void){
_start:
{
lean_object* v___x_822_; lean_object* v___x_823_; 
v___x_822_ = lean_obj_once(&lp_nayose_Nayose_instReprRule_repr___redArg___closed__14, &lp_nayose_Nayose_instReprRule_repr___redArg___closed__14_once, _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__14);
v___x_823_ = lean_nat_to_int(v___x_822_);
return v___x_823_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprRule_repr___redArg(lean_object* v_x_828_){
_start:
{
lean_object* v_name_829_; uint8_t v_kind_830_; lean_object* v_groups_831_; lean_object* v___x_832_; lean_object* v___x_833_; lean_object* v___x_834_; lean_object* v___x_835_; lean_object* v___x_836_; lean_object* v___x_837_; uint8_t v___x_838_; lean_object* v___x_839_; lean_object* v___x_840_; lean_object* v___x_841_; lean_object* v___x_842_; lean_object* v___x_843_; lean_object* v___x_844_; lean_object* v___x_845_; lean_object* v___x_846_; lean_object* v___x_847_; lean_object* v___x_848_; lean_object* v___x_849_; lean_object* v___x_850_; lean_object* v___x_851_; lean_object* v___x_852_; lean_object* v___x_853_; lean_object* v___x_854_; lean_object* v___x_855_; lean_object* v___x_856_; lean_object* v___x_857_; lean_object* v___x_858_; lean_object* v___x_859_; lean_object* v___x_860_; lean_object* v___x_861_; lean_object* v___x_862_; lean_object* v___x_863_; lean_object* v___x_864_; lean_object* v___x_865_; lean_object* v___x_866_; lean_object* v___x_867_; lean_object* v___x_868_; lean_object* v___x_869_; 
v_name_829_ = lean_ctor_get(v_x_828_, 0);
lean_inc_ref(v_name_829_);
v_kind_830_ = lean_ctor_get_uint8(v_x_828_, sizeof(void*)*2);
v_groups_831_ = lean_ctor_get(v_x_828_, 1);
lean_inc(v_groups_831_);
lean_dec_ref(v_x_828_);
v___x_832_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__5));
v___x_833_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__6));
v___x_834_ = lean_obj_once(&lp_nayose_Nayose_instReprRule_repr___redArg___closed__7, &lp_nayose_Nayose_instReprRule_repr___redArg___closed__7_once, _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__7);
v___x_835_ = l_String_quote(v_name_829_);
v___x_836_ = lean_alloc_ctor(3, 1, 0);
lean_ctor_set(v___x_836_, 0, v___x_835_);
v___x_837_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_837_, 0, v___x_834_);
lean_ctor_set(v___x_837_, 1, v___x_836_);
v___x_838_ = 0;
v___x_839_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_839_, 0, v___x_837_);
lean_ctor_set_uint8(v___x_839_, sizeof(void*)*1, v___x_838_);
v___x_840_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_840_, 0, v___x_833_);
lean_ctor_set(v___x_840_, 1, v___x_839_);
v___x_841_ = ((lean_object*)(lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg___closed__2));
v___x_842_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_842_, 0, v___x_840_);
lean_ctor_set(v___x_842_, 1, v___x_841_);
v___x_843_ = lean_box(1);
v___x_844_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_844_, 0, v___x_842_);
lean_ctor_set(v___x_844_, 1, v___x_843_);
v___x_845_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__9));
v___x_846_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_846_, 0, v___x_844_);
lean_ctor_set(v___x_846_, 1, v___x_845_);
v___x_847_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_847_, 0, v___x_846_);
lean_ctor_set(v___x_847_, 1, v___x_832_);
v___x_848_ = lean_unsigned_to_nat(0u);
v___x_849_ = lp_nayose_Nayose_instReprKind_repr(v_kind_830_, v___x_848_);
v___x_850_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_850_, 0, v___x_834_);
lean_ctor_set(v___x_850_, 1, v___x_849_);
v___x_851_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_851_, 0, v___x_850_);
lean_ctor_set_uint8(v___x_851_, sizeof(void*)*1, v___x_838_);
v___x_852_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_852_, 0, v___x_847_);
lean_ctor_set(v___x_852_, 1, v___x_851_);
v___x_853_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_853_, 0, v___x_852_);
lean_ctor_set(v___x_853_, 1, v___x_841_);
v___x_854_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_854_, 0, v___x_853_);
lean_ctor_set(v___x_854_, 1, v___x_843_);
v___x_855_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__11));
v___x_856_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_856_, 0, v___x_854_);
lean_ctor_set(v___x_856_, 1, v___x_855_);
v___x_857_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_857_, 0, v___x_856_);
lean_ctor_set(v___x_857_, 1, v___x_832_);
v___x_858_ = lean_obj_once(&lp_nayose_Nayose_instReprRule_repr___redArg___closed__12, &lp_nayose_Nayose_instReprRule_repr___redArg___closed__12_once, _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__12);
v___x_859_ = lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0___redArg(v_groups_831_);
v___x_860_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_860_, 0, v___x_858_);
lean_ctor_set(v___x_860_, 1, v___x_859_);
v___x_861_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_861_, 0, v___x_860_);
lean_ctor_set_uint8(v___x_861_, sizeof(void*)*1, v___x_838_);
v___x_862_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_862_, 0, v___x_857_);
lean_ctor_set(v___x_862_, 1, v___x_861_);
v___x_863_ = lean_obj_once(&lp_nayose_Nayose_instReprRule_repr___redArg___closed__15, &lp_nayose_Nayose_instReprRule_repr___redArg___closed__15_once, _init_lp_nayose_Nayose_instReprRule_repr___redArg___closed__15);
v___x_864_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__16));
v___x_865_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_865_, 0, v___x_864_);
lean_ctor_set(v___x_865_, 1, v___x_862_);
v___x_866_ = ((lean_object*)(lp_nayose_Nayose_instReprRule_repr___redArg___closed__17));
v___x_867_ = lean_alloc_ctor(5, 2, 0);
lean_ctor_set(v___x_867_, 0, v___x_865_);
lean_ctor_set(v___x_867_, 1, v___x_866_);
v___x_868_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_868_, 0, v___x_863_);
lean_ctor_set(v___x_868_, 1, v___x_867_);
v___x_869_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_869_, 0, v___x_868_);
lean_ctor_set_uint8(v___x_869_, sizeof(void*)*1, v___x_838_);
return v___x_869_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprRule_repr(lean_object* v_x_870_, lean_object* v_prec_871_){
_start:
{
lean_object* v___x_872_; 
v___x_872_ = lp_nayose_Nayose_instReprRule_repr___redArg(v_x_870_);
return v___x_872_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprRule_repr___boxed(lean_object* v_x_873_, lean_object* v_prec_874_){
_start:
{
lean_object* v_res_875_; 
v_res_875_ = lp_nayose_Nayose_instReprRule_repr(v_x_873_, v_prec_874_);
lean_dec(v_prec_874_);
return v_res_875_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0(lean_object* v_a_876_, lean_object* v_n_877_){
_start:
{
lean_object* v___x_878_; 
v___x_878_ = lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0___redArg(v_a_876_);
return v___x_878_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0___boxed(lean_object* v_a_879_, lean_object* v_n_880_){
_start:
{
lean_object* v_res_881_; 
v_res_881_ = lp_nayose_List_repr___at___00Nayose_instReprRule_repr_spec__0(v_a_879_, v_n_880_);
lean_dec(v_n_880_);
return v_res_881_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0(lean_object* v_a_882_, lean_object* v_n_883_){
_start:
{
lean_object* v___x_884_; 
v___x_884_ = lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___redArg(v_a_882_);
return v___x_884_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0___boxed(lean_object* v_a_885_, lean_object* v_n_886_){
_start:
{
lean_object* v_res_887_; 
v_res_887_ = lp_nayose_List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0(v_a_885_, v_n_886_);
lean_dec(v_n_886_);
return v_res_887_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1(lean_object* v_a_888_, lean_object* v_n_889_){
_start:
{
lean_object* v___x_890_; 
v___x_890_ = lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___redArg(v_a_888_);
return v___x_890_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1___boxed(lean_object* v_a_891_, lean_object* v_n_892_){
_start:
{
lean_object* v_res_893_; 
v_res_893_ = lp_nayose_List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1(v_a_891_, v_n_892_);
lean_dec(v_n_892_);
return v_res_893_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2(lean_object* v_x_894_, lean_object* v_x_895_){
_start:
{
lean_object* v___x_896_; 
v___x_896_ = lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___redArg(v_x_894_);
return v___x_896_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2___boxed(lean_object* v_x_897_, lean_object* v_x_898_){
_start:
{
lean_object* v_res_899_; 
v_res_899_ = lp_nayose_Prod_repr___at___00List_repr___at___00List_repr___at___00List_repr___at___00Nayose_instReprRule_repr_spec__0_spec__0_spec__1_spec__2(v_x_897_, v_x_898_);
lean_dec(v_x_898_);
return v_res_899_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_holds_spec__0(lean_object* v_p_902_, lean_object* v_x_903_){
_start:
{
if (lean_obj_tag(v_x_903_) == 0)
{
uint8_t v___x_904_; 
lean_dec_ref(v_p_902_);
v___x_904_ = 1;
return v___x_904_;
}
else
{
lean_object* v_head_905_; lean_object* v_tail_906_; uint8_t v___x_907_; 
v_head_905_ = lean_ctor_get(v_x_903_, 0);
lean_inc(v_head_905_);
v_tail_906_ = lean_ctor_get(v_x_903_, 1);
lean_inc(v_tail_906_);
lean_dec_ref_known(v_x_903_, 2);
lean_inc_ref(v_p_902_);
v___x_907_ = lp_nayose_Nayose_Atom_fires(v_head_905_, v_p_902_);
if (v___x_907_ == 0)
{
lean_dec(v_tail_906_);
lean_dec_ref(v_p_902_);
return v___x_907_;
}
else
{
v_x_903_ = v_tail_906_;
goto _start;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_holds_spec__0___boxed(lean_object* v_p_909_, lean_object* v_x_910_){
_start:
{
uint8_t v_res_911_; lean_object* v_r_912_; 
v_res_911_ = lp_nayose_List_all___at___00Nayose_Rule_holds_spec__0(v_p_909_, v_x_910_);
v_r_912_ = lean_box(v_res_911_);
return v_r_912_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_holds_spec__1(lean_object* v_p_913_, lean_object* v_x_914_){
_start:
{
if (lean_obj_tag(v_x_914_) == 0)
{
uint8_t v___x_915_; 
lean_dec_ref(v_p_913_);
v___x_915_ = 0;
return v___x_915_;
}
else
{
lean_object* v_head_916_; lean_object* v_tail_917_; uint8_t v___x_918_; 
v_head_916_ = lean_ctor_get(v_x_914_, 0);
lean_inc(v_head_916_);
v_tail_917_ = lean_ctor_get(v_x_914_, 1);
lean_inc(v_tail_917_);
lean_dec_ref_known(v_x_914_, 2);
lean_inc_ref(v_p_913_);
v___x_918_ = lp_nayose_List_all___at___00Nayose_Rule_holds_spec__0(v_p_913_, v_head_916_);
if (v___x_918_ == 0)
{
v_x_914_ = v_tail_917_;
goto _start;
}
else
{
lean_dec(v_tail_917_);
lean_dec_ref(v_p_913_);
return v___x_918_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_holds_spec__1___boxed(lean_object* v_p_920_, lean_object* v_x_921_){
_start:
{
uint8_t v_res_922_; lean_object* v_r_923_; 
v_res_922_ = lp_nayose_List_any___at___00Nayose_Rule_holds_spec__1(v_p_920_, v_x_921_);
v_r_923_ = lean_box(v_res_922_);
return v_r_923_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_holds_spec__2(lean_object* v_p_924_, lean_object* v_x_925_){
_start:
{
if (lean_obj_tag(v_x_925_) == 0)
{
uint8_t v___x_926_; 
lean_dec_ref(v_p_924_);
v___x_926_ = 1;
return v___x_926_;
}
else
{
lean_object* v_head_927_; lean_object* v_tail_928_; uint8_t v___x_929_; 
v_head_927_ = lean_ctor_get(v_x_925_, 0);
lean_inc(v_head_927_);
v_tail_928_ = lean_ctor_get(v_x_925_, 1);
lean_inc(v_tail_928_);
lean_dec_ref_known(v_x_925_, 2);
lean_inc_ref(v_p_924_);
v___x_929_ = lp_nayose_List_any___at___00Nayose_Rule_holds_spec__1(v_p_924_, v_head_927_);
if (v___x_929_ == 0)
{
lean_dec(v_tail_928_);
lean_dec_ref(v_p_924_);
return v___x_929_;
}
else
{
v_x_925_ = v_tail_928_;
goto _start;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_holds_spec__2___boxed(lean_object* v_p_931_, lean_object* v_x_932_){
_start:
{
uint8_t v_res_933_; lean_object* v_r_934_; 
v_res_933_ = lp_nayose_List_all___at___00Nayose_Rule_holds_spec__2(v_p_931_, v_x_932_);
v_r_934_ = lean_box(v_res_933_);
return v_r_934_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Rule_holds(lean_object* v_r_935_, lean_object* v_p_936_){
_start:
{
uint8_t v_kind_937_; lean_object* v_groups_938_; uint8_t v_kind_939_; lean_object* v___x_940_; lean_object* v___x_941_; uint8_t v___x_942_; 
v_kind_937_ = lean_ctor_get_uint8(v_r_935_, sizeof(void*)*2);
v_groups_938_ = lean_ctor_get(v_r_935_, 1);
lean_inc(v_groups_938_);
lean_dec_ref(v_r_935_);
v_kind_939_ = lean_ctor_get_uint8(v_p_936_, sizeof(void*)*1);
v___x_940_ = lp_nayose_Nayose_Kind_ctorIdx(v_kind_937_);
v___x_941_ = lp_nayose_Nayose_Kind_ctorIdx(v_kind_939_);
v___x_942_ = lean_nat_dec_eq(v___x_940_, v___x_941_);
lean_dec(v___x_941_);
lean_dec(v___x_940_);
if (v___x_942_ == 0)
{
lean_dec(v_groups_938_);
lean_dec_ref(v_p_936_);
return v___x_942_;
}
else
{
uint8_t v___x_943_; 
v___x_943_ = lp_nayose_List_all___at___00Nayose_Rule_holds_spec__2(v_p_936_, v_groups_938_);
return v___x_943_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Rule_holds___boxed(lean_object* v_r_944_, lean_object* v_p_945_){
_start:
{
uint8_t v_res_946_; lean_object* v_r_947_; 
v_res_946_ = lp_nayose_Nayose_Rule_holds(v_r_944_, v_p_945_);
v_r_947_ = lean_box(v_res_946_);
return v_r_947_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_needs_spec__0(uint8_t v_f_948_, lean_object* v_l_949_, lean_object* v_x_950_){
_start:
{
if (lean_obj_tag(v_x_950_) == 0)
{
uint8_t v___x_951_; 
v___x_951_ = 0;
return v___x_951_;
}
else
{
lean_object* v_head_952_; lean_object* v_tail_953_; lean_object* v_fst_954_; lean_object* v_snd_955_; uint8_t v___x_956_; lean_object* v___x_957_; lean_object* v___x_958_; uint8_t v___x_959_; 
v_head_952_ = lean_ctor_get(v_x_950_, 0);
v_tail_953_ = lean_ctor_get(v_x_950_, 1);
v_fst_954_ = lean_ctor_get(v_head_952_, 0);
v_snd_955_ = lean_ctor_get(v_head_952_, 1);
v___x_956_ = lean_unbox(v_fst_954_);
v___x_957_ = lp_nayose_Nayose_Field_ctorIdx(v___x_956_);
v___x_958_ = lp_nayose_Nayose_Field_ctorIdx(v_f_948_);
v___x_959_ = lean_nat_dec_eq(v___x_957_, v___x_958_);
lean_dec(v___x_958_);
lean_dec(v___x_957_);
if (v___x_959_ == 0)
{
v_x_950_ = v_tail_953_;
goto _start;
}
else
{
uint8_t v___x_961_; 
v___x_961_ = lean_nat_dec_le(v_l_949_, v_snd_955_);
if (v___x_961_ == 0)
{
v_x_950_ = v_tail_953_;
goto _start;
}
else
{
return v___x_961_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_needs_spec__0___boxed(lean_object* v_f_963_, lean_object* v_l_964_, lean_object* v_x_965_){
_start:
{
uint8_t v_f_boxed_966_; uint8_t v_res_967_; lean_object* v_r_968_; 
v_f_boxed_966_ = lean_unbox(v_f_963_);
v_res_967_ = lp_nayose_List_any___at___00Nayose_Rule_needs_spec__0(v_f_boxed_966_, v_l_964_, v_x_965_);
lean_dec(v_x_965_);
lean_dec(v_l_964_);
v_r_968_ = lean_box(v_res_967_);
return v_r_968_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_needs_spec__1(uint8_t v_f_969_, lean_object* v_l_970_, lean_object* v_x_971_){
_start:
{
if (lean_obj_tag(v_x_971_) == 0)
{
uint8_t v___x_972_; 
v___x_972_ = 1;
return v___x_972_;
}
else
{
lean_object* v_head_973_; lean_object* v_tail_974_; uint8_t v___x_975_; 
v_head_973_ = lean_ctor_get(v_x_971_, 0);
v_tail_974_ = lean_ctor_get(v_x_971_, 1);
v___x_975_ = lp_nayose_List_any___at___00Nayose_Rule_needs_spec__0(v_f_969_, v_l_970_, v_head_973_);
if (v___x_975_ == 0)
{
return v___x_975_;
}
else
{
v_x_971_ = v_tail_974_;
goto _start;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_needs_spec__1___boxed(lean_object* v_f_977_, lean_object* v_l_978_, lean_object* v_x_979_){
_start:
{
uint8_t v_f_boxed_980_; uint8_t v_res_981_; lean_object* v_r_982_; 
v_f_boxed_980_ = lean_unbox(v_f_977_);
v_res_981_ = lp_nayose_List_all___at___00Nayose_Rule_needs_spec__1(v_f_boxed_980_, v_l_978_, v_x_979_);
lean_dec(v_x_979_);
lean_dec(v_l_978_);
v_r_982_ = lean_box(v_res_981_);
return v_r_982_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_needs_spec__2(uint8_t v_f_983_, lean_object* v_l_984_, lean_object* v_x_985_){
_start:
{
if (lean_obj_tag(v_x_985_) == 0)
{
uint8_t v___x_986_; 
v___x_986_ = 0;
return v___x_986_;
}
else
{
lean_object* v_head_987_; lean_object* v_tail_988_; uint8_t v___x_989_; 
v_head_987_ = lean_ctor_get(v_x_985_, 0);
v_tail_988_ = lean_ctor_get(v_x_985_, 1);
v___x_989_ = lp_nayose_List_all___at___00Nayose_Rule_needs_spec__1(v_f_983_, v_l_984_, v_head_987_);
if (v___x_989_ == 0)
{
v_x_985_ = v_tail_988_;
goto _start;
}
else
{
return v___x_989_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_needs_spec__2___boxed(lean_object* v_f_991_, lean_object* v_l_992_, lean_object* v_x_993_){
_start:
{
uint8_t v_f_boxed_994_; uint8_t v_res_995_; lean_object* v_r_996_; 
v_f_boxed_994_ = lean_unbox(v_f_991_);
v_res_995_ = lp_nayose_List_any___at___00Nayose_Rule_needs_spec__2(v_f_boxed_994_, v_l_992_, v_x_993_);
lean_dec(v_x_993_);
lean_dec(v_l_992_);
v_r_996_ = lean_box(v_res_995_);
return v_r_996_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Rule_needs(lean_object* v_r_997_, uint8_t v_f_998_, lean_object* v_l_999_){
_start:
{
lean_object* v_groups_1000_; uint8_t v___x_1001_; 
v_groups_1000_ = lean_ctor_get(v_r_997_, 1);
v___x_1001_ = lp_nayose_List_any___at___00Nayose_Rule_needs_spec__2(v_f_998_, v_l_999_, v_groups_1000_);
return v___x_1001_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Rule_needs___boxed(lean_object* v_r_1002_, lean_object* v_f_1003_, lean_object* v_l_1004_){
_start:
{
uint8_t v_f_boxed_1005_; uint8_t v_res_1006_; lean_object* v_r_1007_; 
v_f_boxed_1005_ = lean_unbox(v_f_1003_);
v_res_1006_ = lp_nayose_Nayose_Rule_needs(v_r_1002_, v_f_boxed_1005_, v_l_1004_);
lean_dec(v_l_1004_);
lean_dec_ref(v_r_1002_);
v_r_1007_ = lean_box(v_res_1006_);
return v_r_1007_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__0(lean_object* v_x_1008_){
_start:
{
if (lean_obj_tag(v_x_1008_) == 0)
{
uint8_t v___x_1009_; 
v___x_1009_ = 0;
return v___x_1009_;
}
else
{
lean_object* v_head_1010_; lean_object* v_tail_1011_; uint8_t v___x_1012_; 
v_head_1010_ = lean_ctor_get(v_x_1008_, 0);
v_tail_1011_ = lean_ctor_get(v_x_1008_, 1);
v___x_1012_ = lp_nayose_Nayose_Atom_isCorroboration(v_head_1010_);
if (v___x_1012_ == 0)
{
v_x_1008_ = v_tail_1011_;
goto _start;
}
else
{
return v___x_1012_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__0___boxed(lean_object* v_x_1014_){
_start:
{
uint8_t v_res_1015_; lean_object* v_r_1016_; 
v_res_1015_ = lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__0(v_x_1014_);
lean_dec(v_x_1014_);
v_r_1016_ = lean_box(v_res_1015_);
return v_r_1016_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_all___at___00Nayose_Rule_forcesCorroboration_spec__1(lean_object* v_x_1017_){
_start:
{
if (lean_obj_tag(v_x_1017_) == 0)
{
uint8_t v___x_1018_; 
v___x_1018_ = 1;
return v___x_1018_;
}
else
{
lean_object* v_head_1019_; lean_object* v_tail_1020_; uint8_t v___x_1021_; 
v_head_1019_ = lean_ctor_get(v_x_1017_, 0);
v_tail_1020_ = lean_ctor_get(v_x_1017_, 1);
v___x_1021_ = lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__0(v_head_1019_);
if (v___x_1021_ == 0)
{
return v___x_1021_;
}
else
{
v_x_1017_ = v_tail_1020_;
goto _start;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_all___at___00Nayose_Rule_forcesCorroboration_spec__1___boxed(lean_object* v_x_1023_){
_start:
{
uint8_t v_res_1024_; lean_object* v_r_1025_; 
v_res_1024_ = lp_nayose_List_all___at___00Nayose_Rule_forcesCorroboration_spec__1(v_x_1023_);
lean_dec(v_x_1023_);
v_r_1025_ = lean_box(v_res_1024_);
return v_r_1025_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__2(lean_object* v_x_1026_){
_start:
{
if (lean_obj_tag(v_x_1026_) == 0)
{
uint8_t v___x_1027_; 
v___x_1027_ = 0;
return v___x_1027_;
}
else
{
lean_object* v_head_1028_; lean_object* v_tail_1029_; uint8_t v___x_1030_; 
v_head_1028_ = lean_ctor_get(v_x_1026_, 0);
v_tail_1029_ = lean_ctor_get(v_x_1026_, 1);
v___x_1030_ = lp_nayose_List_all___at___00Nayose_Rule_forcesCorroboration_spec__1(v_head_1028_);
if (v___x_1030_ == 0)
{
v_x_1026_ = v_tail_1029_;
goto _start;
}
else
{
return v___x_1030_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__2___boxed(lean_object* v_x_1032_){
_start:
{
uint8_t v_res_1033_; lean_object* v_r_1034_; 
v_res_1033_ = lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__2(v_x_1032_);
lean_dec(v_x_1032_);
v_r_1034_ = lean_box(v_res_1033_);
return v_r_1034_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Rule_forcesCorroboration(lean_object* v_r_1035_){
_start:
{
lean_object* v_groups_1036_; uint8_t v___x_1037_; 
v_groups_1036_ = lean_ctor_get(v_r_1035_, 1);
v___x_1037_ = lp_nayose_List_any___at___00Nayose_Rule_forcesCorroboration_spec__2(v_groups_1036_);
return v___x_1037_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Rule_forcesCorroboration___boxed(lean_object* v_r_1038_){
_start:
{
uint8_t v_res_1039_; lean_object* v_r_1040_; 
v_res_1039_ = lp_nayose_Nayose_Rule_forcesCorroboration(v_r_1038_);
lean_dec_ref(v_r_1038_);
v_r_1040_ = lean_box(v_res_1039_);
return v_r_1040_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Veto_fires(lean_object* v_v_1041_, lean_object* v_p_1042_){
_start:
{
uint8_t v_field_1043_; lean_object* v_lo_1044_; lean_object* v_hi_1045_; lean_object* v_level_1046_; lean_object* v___x_1047_; lean_object* v___x_1048_; uint8_t v___x_1049_; 
v_field_1043_ = lean_ctor_get_uint8(v_v_1041_, sizeof(void*)*3);
v_lo_1044_ = lean_ctor_get(v_v_1041_, 1);
v_hi_1045_ = lean_ctor_get(v_v_1041_, 2);
v_level_1046_ = lean_ctor_get(v_p_1042_, 0);
lean_inc_ref(v_level_1046_);
lean_dec_ref(v_p_1042_);
v___x_1047_ = lean_box(v_field_1043_);
v___x_1048_ = lean_apply_1(v_level_1046_, v___x_1047_);
v___x_1049_ = lean_nat_dec_le(v_lo_1044_, v___x_1048_);
if (v___x_1049_ == 0)
{
lean_dec(v___x_1048_);
return v___x_1049_;
}
else
{
uint8_t v___x_1050_; 
v___x_1050_ = lean_nat_dec_le(v___x_1048_, v_hi_1045_);
lean_dec(v___x_1048_);
return v___x_1050_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Veto_fires___boxed(lean_object* v_v_1051_, lean_object* v_p_1052_){
_start:
{
uint8_t v_res_1053_; lean_object* v_r_1054_; 
v_res_1053_ = lp_nayose_Nayose_Veto_fires(v_v_1051_, v_p_1052_);
lean_dec_ref(v_v_1051_);
v_r_1054_ = lean_box(v_res_1053_);
return v_r_1054_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorIdx(uint8_t v_x_1342_){
_start:
{
switch(v_x_1342_)
{
case 0:
{
lean_object* v___x_1343_; 
v___x_1343_ = lean_unsigned_to_nat(0u);
return v___x_1343_;
}
case 1:
{
lean_object* v___x_1344_; 
v___x_1344_ = lean_unsigned_to_nat(1u);
return v___x_1344_;
}
default: 
{
lean_object* v___x_1345_; 
v___x_1345_ = lean_unsigned_to_nat(2u);
return v___x_1345_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorIdx___boxed(lean_object* v_x_1346_){
_start:
{
uint8_t v_x_boxed_1347_; lean_object* v_res_1348_; 
v_x_boxed_1347_ = lean_unbox(v_x_1346_);
v_res_1348_ = lp_nayose_Nayose_Tier_ctorIdx(v_x_boxed_1347_);
return v_res_1348_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim___redArg(lean_object* v_k_1349_){
_start:
{
lean_inc(v_k_1349_);
return v_k_1349_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim___redArg___boxed(lean_object* v_k_1350_){
_start:
{
lean_object* v_res_1351_; 
v_res_1351_ = lp_nayose_Nayose_Tier_ctorElim___redArg(v_k_1350_);
lean_dec(v_k_1350_);
return v_res_1351_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim(lean_object* v_motive_1352_, lean_object* v_ctorIdx_1353_, uint8_t v_t_1354_, lean_object* v_h_1355_, lean_object* v_k_1356_){
_start:
{
lean_inc(v_k_1356_);
return v_k_1356_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ctorElim___boxed(lean_object* v_motive_1357_, lean_object* v_ctorIdx_1358_, lean_object* v_t_1359_, lean_object* v_h_1360_, lean_object* v_k_1361_){
_start:
{
uint8_t v_t_boxed_1362_; lean_object* v_res_1363_; 
v_t_boxed_1362_ = lean_unbox(v_t_1359_);
v_res_1363_ = lp_nayose_Nayose_Tier_ctorElim(v_motive_1357_, v_ctorIdx_1358_, v_t_boxed_1362_, v_h_1360_, v_k_1361_);
lean_dec(v_k_1361_);
lean_dec(v_ctorIdx_1358_);
return v_res_1363_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim___redArg(lean_object* v_safe_1364_){
_start:
{
lean_inc(v_safe_1364_);
return v_safe_1364_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim___redArg___boxed(lean_object* v_safe_1365_){
_start:
{
lean_object* v_res_1366_; 
v_res_1366_ = lp_nayose_Nayose_Tier_safe_elim___redArg(v_safe_1365_);
lean_dec(v_safe_1365_);
return v_res_1366_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim(lean_object* v_motive_1367_, uint8_t v_t_1368_, lean_object* v_h_1369_, lean_object* v_safe_1370_){
_start:
{
lean_inc(v_safe_1370_);
return v_safe_1370_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_safe_elim___boxed(lean_object* v_motive_1371_, lean_object* v_t_1372_, lean_object* v_h_1373_, lean_object* v_safe_1374_){
_start:
{
uint8_t v_t_boxed_1375_; lean_object* v_res_1376_; 
v_t_boxed_1375_ = lean_unbox(v_t_1372_);
v_res_1376_ = lp_nayose_Nayose_Tier_safe_elim(v_motive_1371_, v_t_boxed_1375_, v_h_1373_, v_safe_1374_);
lean_dec(v_safe_1374_);
return v_res_1376_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim___redArg(lean_object* v_candidate_1377_){
_start:
{
lean_inc(v_candidate_1377_);
return v_candidate_1377_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim___redArg___boxed(lean_object* v_candidate_1378_){
_start:
{
lean_object* v_res_1379_; 
v_res_1379_ = lp_nayose_Nayose_Tier_candidate_elim___redArg(v_candidate_1378_);
lean_dec(v_candidate_1378_);
return v_res_1379_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim(lean_object* v_motive_1380_, uint8_t v_t_1381_, lean_object* v_h_1382_, lean_object* v_candidate_1383_){
_start:
{
lean_inc(v_candidate_1383_);
return v_candidate_1383_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_candidate_elim___boxed(lean_object* v_motive_1384_, lean_object* v_t_1385_, lean_object* v_h_1386_, lean_object* v_candidate_1387_){
_start:
{
uint8_t v_t_boxed_1388_; lean_object* v_res_1389_; 
v_t_boxed_1388_ = lean_unbox(v_t_1385_);
v_res_1389_ = lp_nayose_Nayose_Tier_candidate_elim(v_motive_1384_, v_t_boxed_1388_, v_h_1386_, v_candidate_1387_);
lean_dec(v_candidate_1387_);
return v_res_1389_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim___redArg(lean_object* v_none_1390_){
_start:
{
lean_inc(v_none_1390_);
return v_none_1390_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim___redArg___boxed(lean_object* v_none_1391_){
_start:
{
lean_object* v_res_1392_; 
v_res_1392_ = lp_nayose_Nayose_Tier_none_elim___redArg(v_none_1391_);
lean_dec(v_none_1391_);
return v_res_1392_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim(lean_object* v_motive_1393_, uint8_t v_t_1394_, lean_object* v_h_1395_, lean_object* v_none_1396_){
_start:
{
lean_inc(v_none_1396_);
return v_none_1396_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_none_elim___boxed(lean_object* v_motive_1397_, lean_object* v_t_1398_, lean_object* v_h_1399_, lean_object* v_none_1400_){
_start:
{
uint8_t v_t_boxed_1401_; lean_object* v_res_1402_; 
v_t_boxed_1401_ = lean_unbox(v_t_1398_);
v_res_1402_ = lp_nayose_Nayose_Tier_none_elim(v_motive_1397_, v_t_boxed_1401_, v_h_1399_, v_none_1400_);
lean_dec(v_none_1400_);
return v_res_1402_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Tier_ofNat(lean_object* v_n_1403_){
_start:
{
lean_object* v___x_1404_; uint8_t v___x_1405_; 
v___x_1404_ = lean_unsigned_to_nat(0u);
v___x_1405_ = lean_nat_dec_le(v_n_1403_, v___x_1404_);
if (v___x_1405_ == 0)
{
lean_object* v___x_1406_; uint8_t v___x_1407_; 
v___x_1406_ = lean_unsigned_to_nat(1u);
v___x_1407_ = lean_nat_dec_le(v_n_1403_, v___x_1406_);
if (v___x_1407_ == 0)
{
uint8_t v___x_1408_; 
v___x_1408_ = 2;
return v___x_1408_;
}
else
{
uint8_t v___x_1409_; 
v___x_1409_ = 1;
return v___x_1409_;
}
}
else
{
uint8_t v___x_1410_; 
v___x_1410_ = 0;
return v___x_1410_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Tier_ofNat___boxed(lean_object* v_n_1411_){
_start:
{
uint8_t v_res_1412_; lean_object* v_r_1413_; 
v_res_1412_ = lp_nayose_Nayose_Tier_ofNat(v_n_1411_);
lean_dec(v_n_1411_);
v_r_1413_ = lean_box(v_res_1412_);
return v_r_1413_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_instDecidableEqTier(uint8_t v_x_1414_, uint8_t v_y_1415_){
_start:
{
lean_object* v___x_1416_; lean_object* v___x_1417_; uint8_t v___x_1418_; 
v___x_1416_ = lp_nayose_Nayose_Tier_ctorIdx(v_x_1414_);
v___x_1417_ = lp_nayose_Nayose_Tier_ctorIdx(v_y_1415_);
v___x_1418_ = lean_nat_dec_eq(v___x_1416_, v___x_1417_);
lean_dec(v___x_1417_);
lean_dec(v___x_1416_);
return v___x_1418_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instDecidableEqTier___boxed(lean_object* v_x_1419_, lean_object* v_y_1420_){
_start:
{
uint8_t v_x_20__boxed_1421_; uint8_t v_y_21__boxed_1422_; uint8_t v_res_1423_; lean_object* v_r_1424_; 
v_x_20__boxed_1421_ = lean_unbox(v_x_1419_);
v_y_21__boxed_1422_ = lean_unbox(v_y_1420_);
v_res_1423_ = lp_nayose_Nayose_instDecidableEqTier(v_x_20__boxed_1421_, v_y_21__boxed_1422_);
v_r_1424_ = lean_box(v_res_1423_);
return v_r_1424_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprTier_repr(uint8_t v_x_1434_, lean_object* v_prec_1435_){
_start:
{
lean_object* v___y_1437_; lean_object* v___y_1444_; lean_object* v___y_1451_; 
switch(v_x_1434_)
{
case 0:
{
lean_object* v___x_1457_; uint8_t v___x_1458_; 
v___x_1457_ = lean_unsigned_to_nat(1024u);
v___x_1458_ = lean_nat_dec_le(v___x_1457_, v_prec_1435_);
if (v___x_1458_ == 0)
{
lean_object* v___x_1459_; 
v___x_1459_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_1437_ = v___x_1459_;
goto v___jp_1436_;
}
else
{
lean_object* v___x_1460_; 
v___x_1460_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_1437_ = v___x_1460_;
goto v___jp_1436_;
}
}
case 1:
{
lean_object* v___x_1461_; uint8_t v___x_1462_; 
v___x_1461_ = lean_unsigned_to_nat(1024u);
v___x_1462_ = lean_nat_dec_le(v___x_1461_, v_prec_1435_);
if (v___x_1462_ == 0)
{
lean_object* v___x_1463_; 
v___x_1463_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_1444_ = v___x_1463_;
goto v___jp_1443_;
}
else
{
lean_object* v___x_1464_; 
v___x_1464_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_1444_ = v___x_1464_;
goto v___jp_1443_;
}
}
default: 
{
lean_object* v___x_1465_; uint8_t v___x_1466_; 
v___x_1465_ = lean_unsigned_to_nat(1024u);
v___x_1466_ = lean_nat_dec_le(v___x_1465_, v_prec_1435_);
if (v___x_1466_ == 0)
{
lean_object* v___x_1467_; 
v___x_1467_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__4, &lp_nayose_Nayose_instReprKind_repr___closed__4_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__4);
v___y_1451_ = v___x_1467_;
goto v___jp_1450_;
}
else
{
lean_object* v___x_1468_; 
v___x_1468_ = lean_obj_once(&lp_nayose_Nayose_instReprKind_repr___closed__5, &lp_nayose_Nayose_instReprKind_repr___closed__5_once, _init_lp_nayose_Nayose_instReprKind_repr___closed__5);
v___y_1451_ = v___x_1468_;
goto v___jp_1450_;
}
}
}
v___jp_1436_:
{
lean_object* v___x_1438_; lean_object* v___x_1439_; uint8_t v___x_1440_; lean_object* v___x_1441_; lean_object* v___x_1442_; 
v___x_1438_ = ((lean_object*)(lp_nayose_Nayose_instReprTier_repr___closed__1));
lean_inc(v___y_1437_);
v___x_1439_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_1439_, 0, v___y_1437_);
lean_ctor_set(v___x_1439_, 1, v___x_1438_);
v___x_1440_ = 0;
v___x_1441_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_1441_, 0, v___x_1439_);
lean_ctor_set_uint8(v___x_1441_, sizeof(void*)*1, v___x_1440_);
v___x_1442_ = l_Repr_addAppParen(v___x_1441_, v_prec_1435_);
return v___x_1442_;
}
v___jp_1443_:
{
lean_object* v___x_1445_; lean_object* v___x_1446_; uint8_t v___x_1447_; lean_object* v___x_1448_; lean_object* v___x_1449_; 
v___x_1445_ = ((lean_object*)(lp_nayose_Nayose_instReprTier_repr___closed__3));
lean_inc(v___y_1444_);
v___x_1446_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_1446_, 0, v___y_1444_);
lean_ctor_set(v___x_1446_, 1, v___x_1445_);
v___x_1447_ = 0;
v___x_1448_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_1448_, 0, v___x_1446_);
lean_ctor_set_uint8(v___x_1448_, sizeof(void*)*1, v___x_1447_);
v___x_1449_ = l_Repr_addAppParen(v___x_1448_, v_prec_1435_);
return v___x_1449_;
}
v___jp_1450_:
{
lean_object* v___x_1452_; lean_object* v___x_1453_; uint8_t v___x_1454_; lean_object* v___x_1455_; lean_object* v___x_1456_; 
v___x_1452_ = ((lean_object*)(lp_nayose_Nayose_instReprTier_repr___closed__5));
lean_inc(v___y_1451_);
v___x_1453_ = lean_alloc_ctor(4, 2, 0);
lean_ctor_set(v___x_1453_, 0, v___y_1451_);
lean_ctor_set(v___x_1453_, 1, v___x_1452_);
v___x_1454_ = 0;
v___x_1455_ = lean_alloc_ctor(6, 1, 1);
lean_ctor_set(v___x_1455_, 0, v___x_1453_);
lean_ctor_set_uint8(v___x_1455_, sizeof(void*)*1, v___x_1454_);
v___x_1456_ = l_Repr_addAppParen(v___x_1455_, v_prec_1435_);
return v___x_1456_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_instReprTier_repr___boxed(lean_object* v_x_1469_, lean_object* v_prec_1470_){
_start:
{
uint8_t v_x_167__boxed_1471_; lean_object* v_res_1472_; 
v_x_167__boxed_1471_ = lean_unbox(v_x_1469_);
v_res_1472_ = lp_nayose_Nayose_instReprTier_repr(v_x_167__boxed_1471_, v_prec_1470_);
lean_dec(v_prec_1470_);
return v_res_1472_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Profile_vetoed_spec__0(lean_object* v_p_1475_, lean_object* v_x_1476_){
_start:
{
if (lean_obj_tag(v_x_1476_) == 0)
{
uint8_t v___x_1477_; 
lean_dec_ref(v_p_1475_);
v___x_1477_ = 0;
return v___x_1477_;
}
else
{
lean_object* v_head_1478_; lean_object* v_tail_1479_; uint8_t v___x_1480_; 
v_head_1478_ = lean_ctor_get(v_x_1476_, 0);
v_tail_1479_ = lean_ctor_get(v_x_1476_, 1);
lean_inc_ref(v_p_1475_);
v___x_1480_ = lp_nayose_Nayose_Veto_fires(v_head_1478_, v_p_1475_);
if (v___x_1480_ == 0)
{
v_x_1476_ = v_tail_1479_;
goto _start;
}
else
{
lean_dec_ref(v_p_1475_);
return v___x_1480_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Profile_vetoed_spec__0___boxed(lean_object* v_p_1482_, lean_object* v_x_1483_){
_start:
{
uint8_t v_res_1484_; lean_object* v_r_1485_; 
v_res_1484_ = lp_nayose_List_any___at___00Nayose_Profile_vetoed_spec__0(v_p_1482_, v_x_1483_);
lean_dec(v_x_1483_);
v_r_1485_ = lean_box(v_res_1484_);
return v_r_1485_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Profile_vetoed(lean_object* v_p_1486_){
_start:
{
lean_object* v___x_1487_; uint8_t v___x_1488_; 
v___x_1487_ = ((lean_object*)(lp_nayose_Nayose_vetoRules));
v___x_1488_ = lp_nayose_List_any___at___00Nayose_Profile_vetoed_spec__0(v_p_1486_, v___x_1487_);
return v___x_1488_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Profile_vetoed___boxed(lean_object* v_p_1489_){
_start:
{
uint8_t v_res_1490_; lean_object* v_r_1491_; 
v_res_1490_ = lp_nayose_Nayose_Profile_vetoed(v_p_1489_);
v_r_1491_ = lean_box(v_res_1490_);
return v_r_1491_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(lean_object* v_p_1492_, lean_object* v_x_1493_){
_start:
{
if (lean_obj_tag(v_x_1493_) == 0)
{
uint8_t v___x_1494_; 
lean_dec_ref(v_p_1492_);
v___x_1494_ = 0;
return v___x_1494_;
}
else
{
lean_object* v_head_1495_; lean_object* v_tail_1496_; uint8_t v___x_1497_; 
v_head_1495_ = lean_ctor_get(v_x_1493_, 0);
lean_inc(v_head_1495_);
v_tail_1496_ = lean_ctor_get(v_x_1493_, 1);
lean_inc(v_tail_1496_);
lean_dec_ref_known(v_x_1493_, 2);
lean_inc_ref(v_p_1492_);
v___x_1497_ = lp_nayose_Nayose_Rule_holds(v_head_1495_, v_p_1492_);
if (v___x_1497_ == 0)
{
v_x_1493_ = v_tail_1496_;
goto _start;
}
else
{
lean_dec(v_tail_1496_);
lean_dec_ref(v_p_1492_);
return v___x_1497_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0___boxed(lean_object* v_p_1499_, lean_object* v_x_1500_){
_start:
{
uint8_t v_res_1501_; lean_object* v_r_1502_; 
v_res_1501_ = lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(v_p_1499_, v_x_1500_);
v_r_1502_ = lean_box(v_res_1501_);
return v_r_1502_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Profile_fires(lean_object* v_rs_1503_, lean_object* v_p_1504_){
_start:
{
uint8_t v___x_1505_; 
v___x_1505_ = lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(v_p_1504_, v_rs_1503_);
return v___x_1505_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Profile_fires___boxed(lean_object* v_rs_1506_, lean_object* v_p_1507_){
_start:
{
uint8_t v_res_1508_; lean_object* v_r_1509_; 
v_res_1508_ = lp_nayose_Nayose_Profile_fires(v_rs_1506_, v_p_1507_);
v_r_1509_ = lean_box(v_res_1508_);
return v_r_1509_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Profile_tier(lean_object* v_p_1510_){
_start:
{
uint8_t v___x_1511_; 
lean_inc_ref(v_p_1510_);
v___x_1511_ = lp_nayose_Nayose_Profile_vetoed(v_p_1510_);
if (v___x_1511_ == 0)
{
lean_object* v___x_1512_; uint8_t v___x_1513_; 
v___x_1512_ = ((lean_object*)(lp_nayose_Nayose_safeRules));
lean_inc_ref(v_p_1510_);
v___x_1513_ = lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(v_p_1510_, v___x_1512_);
if (v___x_1513_ == 0)
{
lean_object* v___x_1514_; uint8_t v___x_1515_; 
v___x_1514_ = ((lean_object*)(lp_nayose_Nayose_candidateRules));
v___x_1515_ = lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(v_p_1510_, v___x_1514_);
if (v___x_1515_ == 0)
{
uint8_t v___x_1516_; 
v___x_1516_ = 2;
return v___x_1516_;
}
else
{
uint8_t v___x_1517_; 
v___x_1517_ = 1;
return v___x_1517_;
}
}
else
{
uint8_t v___x_1518_; 
lean_dec_ref(v_p_1510_);
v___x_1518_ = 0;
return v___x_1518_;
}
}
else
{
lean_object* v___x_1519_; uint8_t v___x_1520_; 
v___x_1519_ = ((lean_object*)(lp_nayose_Nayose_safeRules));
lean_inc_ref(v_p_1510_);
v___x_1520_ = lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(v_p_1510_, v___x_1519_);
if (v___x_1520_ == 0)
{
lean_object* v___x_1521_; uint8_t v___x_1522_; 
v___x_1521_ = ((lean_object*)(lp_nayose_Nayose_candidateRules));
v___x_1522_ = lp_nayose_List_any___at___00Nayose_Profile_fires_spec__0(v_p_1510_, v___x_1521_);
if (v___x_1522_ == 0)
{
uint8_t v___x_1523_; 
v___x_1523_ = 2;
return v___x_1523_;
}
else
{
uint8_t v___x_1524_; 
v___x_1524_ = 1;
return v___x_1524_;
}
}
else
{
uint8_t v___x_1525_; 
lean_dec_ref(v_p_1510_);
v___x_1525_ = 1;
return v___x_1525_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Profile_tier___boxed(lean_object* v_p_1526_){
_start:
{
uint8_t v_res_1527_; lean_object* v_r_1528_; 
v_res_1527_ = lp_nayose_Nayose_Profile_tier(v_p_1526_);
v_r_1528_ = lean_box(v_res_1527_);
return v_r_1528_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_Scored_tier(lean_object* v_s_1529_){
_start:
{
lean_object* v_profile_1530_; uint8_t v___x_1531_; 
v_profile_1530_ = lean_ctor_get(v_s_1529_, 0);
lean_inc_ref(v_profile_1530_);
lean_dec_ref(v_s_1529_);
v___x_1531_ = lp_nayose_Nayose_Profile_tier(v_profile_1530_);
return v___x_1531_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_Scored_tier___boxed(lean_object* v_s_1532_){
_start:
{
uint8_t v_res_1533_; lean_object* v_r_1534_; 
v_res_1533_ = lp_nayose_Nayose_Scored_tier(v_s_1532_);
v_r_1534_ = lean_box(v_res_1533_);
return v_r_1534_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___redArg(uint8_t v_x_1535_, uint8_t v_x_1536_, uint8_t v_x_1537_, lean_object* v_h__1_1538_, lean_object* v_h__2_1539_, lean_object* v_h__3_1540_){
_start:
{
if (v_x_1535_ == 0)
{
if (v_x_1536_ == 0)
{
lean_dec(v_h__1_1538_);
if (v_x_1537_ == 0)
{
lean_object* v___x_1541_; lean_object* v___x_1542_; 
lean_dec(v_h__3_1540_);
v___x_1541_ = lean_box(v_x_1537_);
v___x_1542_ = lean_apply_1(v_h__2_1539_, v___x_1541_);
return v___x_1542_;
}
else
{
lean_object* v___x_1543_; lean_object* v___x_1544_; lean_object* v___x_1545_; lean_object* v___x_1546_; 
lean_dec(v_h__2_1539_);
v___x_1543_ = lean_box(v_x_1536_);
v___x_1544_ = lean_box(v_x_1536_);
v___x_1545_ = lean_box(v_x_1537_);
v___x_1546_ = lean_apply_5(v_h__3_1540_, v___x_1543_, v___x_1544_, v___x_1545_, lean_box(0), lean_box(0));
return v___x_1546_;
}
}
else
{
lean_object* v___x_1547_; lean_object* v___x_1548_; 
lean_dec(v_h__3_1540_);
lean_dec(v_h__2_1539_);
v___x_1547_ = lean_box(v_x_1537_);
v___x_1548_ = lean_apply_1(v_h__1_1538_, v___x_1547_);
return v___x_1548_;
}
}
else
{
lean_dec(v_h__1_1538_);
if (v_x_1536_ == 0)
{
if (v_x_1537_ == 0)
{
lean_object* v___x_1549_; lean_object* v___x_1550_; 
lean_dec(v_h__3_1540_);
v___x_1549_ = lean_box(v_x_1535_);
v___x_1550_ = lean_apply_1(v_h__2_1539_, v___x_1549_);
return v___x_1550_;
}
else
{
lean_object* v___x_1551_; lean_object* v___x_1552_; lean_object* v___x_1553_; lean_object* v___x_1554_; 
lean_dec(v_h__2_1539_);
v___x_1551_ = lean_box(v_x_1535_);
v___x_1552_ = lean_box(v_x_1536_);
v___x_1553_ = lean_box(v_x_1537_);
v___x_1554_ = lean_apply_5(v_h__3_1540_, v___x_1551_, v___x_1552_, v___x_1553_, lean_box(0), lean_box(0));
return v___x_1554_;
}
}
else
{
lean_object* v___x_1555_; lean_object* v___x_1556_; lean_object* v___x_1557_; lean_object* v___x_1558_; 
lean_dec(v_h__2_1539_);
v___x_1555_ = lean_box(v_x_1535_);
v___x_1556_ = lean_box(v_x_1536_);
v___x_1557_ = lean_box(v_x_1537_);
v___x_1558_ = lean_apply_5(v_h__3_1540_, v___x_1555_, v___x_1556_, v___x_1557_, lean_box(0), lean_box(0));
return v___x_1558_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___redArg___boxed(lean_object* v_x_1559_, lean_object* v_x_1560_, lean_object* v_x_1561_, lean_object* v_h__1_1562_, lean_object* v_h__2_1563_, lean_object* v_h__3_1564_){
_start:
{
uint8_t v_x_29__boxed_1565_; uint8_t v_x_30__boxed_1566_; uint8_t v_x_31__boxed_1567_; lean_object* v_res_1568_; 
v_x_29__boxed_1565_ = lean_unbox(v_x_1559_);
v_x_30__boxed_1566_ = lean_unbox(v_x_1560_);
v_x_31__boxed_1567_ = lean_unbox(v_x_1561_);
v_res_1568_ = lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___redArg(v_x_29__boxed_1565_, v_x_30__boxed_1566_, v_x_31__boxed_1567_, v_h__1_1562_, v_h__2_1563_, v_h__3_1564_);
return v_res_1568_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter(lean_object* v_motive_1569_, uint8_t v_x_1570_, uint8_t v_x_1571_, uint8_t v_x_1572_, lean_object* v_h__1_1573_, lean_object* v_h__2_1574_, lean_object* v_h__3_1575_){
_start:
{
if (v_x_1570_ == 0)
{
if (v_x_1571_ == 0)
{
lean_dec(v_h__1_1573_);
if (v_x_1572_ == 0)
{
lean_object* v___x_1576_; lean_object* v___x_1577_; 
lean_dec(v_h__3_1575_);
v___x_1576_ = lean_box(v_x_1572_);
v___x_1577_ = lean_apply_1(v_h__2_1574_, v___x_1576_);
return v___x_1577_;
}
else
{
lean_object* v___x_1578_; lean_object* v___x_1579_; lean_object* v___x_1580_; lean_object* v___x_1581_; 
lean_dec(v_h__2_1574_);
v___x_1578_ = lean_box(v_x_1571_);
v___x_1579_ = lean_box(v_x_1571_);
v___x_1580_ = lean_box(v_x_1572_);
v___x_1581_ = lean_apply_5(v_h__3_1575_, v___x_1578_, v___x_1579_, v___x_1580_, lean_box(0), lean_box(0));
return v___x_1581_;
}
}
else
{
lean_object* v___x_1582_; lean_object* v___x_1583_; 
lean_dec(v_h__3_1575_);
lean_dec(v_h__2_1574_);
v___x_1582_ = lean_box(v_x_1572_);
v___x_1583_ = lean_apply_1(v_h__1_1573_, v___x_1582_);
return v___x_1583_;
}
}
else
{
lean_dec(v_h__1_1573_);
if (v_x_1571_ == 0)
{
if (v_x_1572_ == 0)
{
lean_object* v___x_1584_; lean_object* v___x_1585_; 
lean_dec(v_h__3_1575_);
v___x_1584_ = lean_box(v_x_1570_);
v___x_1585_ = lean_apply_1(v_h__2_1574_, v___x_1584_);
return v___x_1585_;
}
else
{
lean_object* v___x_1586_; lean_object* v___x_1587_; lean_object* v___x_1588_; lean_object* v___x_1589_; 
lean_dec(v_h__2_1574_);
v___x_1586_ = lean_box(v_x_1570_);
v___x_1587_ = lean_box(v_x_1571_);
v___x_1588_ = lean_box(v_x_1572_);
v___x_1589_ = lean_apply_5(v_h__3_1575_, v___x_1586_, v___x_1587_, v___x_1588_, lean_box(0), lean_box(0));
return v___x_1589_;
}
}
else
{
lean_object* v___x_1590_; lean_object* v___x_1591_; lean_object* v___x_1592_; lean_object* v___x_1593_; 
lean_dec(v_h__2_1574_);
v___x_1590_ = lean_box(v_x_1570_);
v___x_1591_ = lean_box(v_x_1571_);
v___x_1592_ = lean_box(v_x_1572_);
v___x_1593_ = lean_apply_5(v_h__3_1575_, v___x_1590_, v___x_1591_, v___x_1592_, lean_box(0), lean_box(0));
return v___x_1593_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter___boxed(lean_object* v_motive_1594_, lean_object* v_x_1595_, lean_object* v_x_1596_, lean_object* v_x_1597_, lean_object* v_h__1_1598_, lean_object* v_h__2_1599_, lean_object* v_h__3_1600_){
_start:
{
uint8_t v_x_74__boxed_1601_; uint8_t v_x_75__boxed_1602_; uint8_t v_x_76__boxed_1603_; lean_object* v_res_1604_; 
v_x_74__boxed_1601_ = lean_unbox(v_x_1595_);
v_x_75__boxed_1602_ = lean_unbox(v_x_1596_);
v_x_76__boxed_1603_ = lean_unbox(v_x_1597_);
v_res_1604_ = lp_nayose___private_Nayose_Rules_0__Nayose_Profile_tier_match__1_splitter(v_motive_1594_, v_x_74__boxed_1601_, v_x_75__boxed_1602_, v_x_76__boxed_1603_, v_h__1_1598_, v_h__2_1599_, v_h__3_1600_);
return v_res_1604_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Atom_isCorroboration_match__1_splitter___redArg(lean_object* v_x_1605_, lean_object* v_h__1_1606_, lean_object* v_h__2_1607_){
_start:
{
if (lean_obj_tag(v_x_1605_) == 0)
{
lean_object* v___x_1608_; lean_object* v___x_1609_; 
lean_dec(v_h__1_1606_);
v___x_1608_ = lean_box(0);
v___x_1609_ = lean_apply_1(v_h__2_1607_, v___x_1608_);
return v___x_1609_;
}
else
{
lean_object* v_val_1610_; lean_object* v___x_1611_; 
lean_dec(v_h__2_1607_);
v_val_1610_ = lean_ctor_get(v_x_1605_, 0);
lean_inc(v_val_1610_);
lean_dec_ref_known(v_x_1605_, 1);
v___x_1611_ = lean_apply_1(v_h__1_1606_, v_val_1610_);
return v___x_1611_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Rules_0__Nayose_Atom_isCorroboration_match__1_splitter(lean_object* v_motive_1612_, lean_object* v_x_1613_, lean_object* v_h__1_1614_, lean_object* v_h__2_1615_){
_start:
{
if (lean_obj_tag(v_x_1613_) == 0)
{
lean_object* v___x_1616_; lean_object* v___x_1617_; 
lean_dec(v_h__1_1614_);
v___x_1616_ = lean_box(0);
v___x_1617_ = lean_apply_1(v_h__2_1615_, v___x_1616_);
return v___x_1617_;
}
else
{
lean_object* v_val_1618_; lean_object* v___x_1619_; 
lean_dec(v_h__2_1615_);
v_val_1618_ = lean_ctor_get(v_x_1613_, 0);
lean_inc(v_val_1618_);
lean_dec_ref_known(v_x_1613_, 1);
v___x_1619_ = lean_apply_1(v_h__1_1614_, v_val_1618_);
return v___x_1619_;
}
}
}
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_Init(uint8_t builtin);
void lean_initialize_runtime_module();
static bool _G_initialized = false;
LEAN_EXPORT lean_object* initialize_nayose_Nayose_Rules(uint8_t builtin) {
lean_object * res;
if (_G_initialized) return lean_io_result_mk_ok(lean_box(0));
_G_initialized = true;
lean_initialize_runtime_module();
res = initialize_Init(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
res = initialize_Init(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
lp_nayose_Nayose_Lvl_missing = _init_lp_nayose_Nayose_Lvl_missing();
lean_mark_persistent(lp_nayose_Nayose_Lvl_missing);
lp_nayose_Nayose_Lvl_diff = _init_lp_nayose_Nayose_Lvl_diff();
lean_mark_persistent(lp_nayose_Nayose_Lvl_diff);
lp_nayose_Nayose_Lvl_close = _init_lp_nayose_Nayose_Lvl_close();
lean_mark_persistent(lp_nayose_Nayose_Lvl_close);
lp_nayose_Nayose_Lvl_swapped = _init_lp_nayose_Nayose_Lvl_swapped();
lean_mark_persistent(lp_nayose_Nayose_Lvl_swapped);
lp_nayose_Nayose_Lvl_looseFull = _init_lp_nayose_Nayose_Lvl_looseFull();
lean_mark_persistent(lp_nayose_Nayose_Lvl_looseFull);
lp_nayose_Nayose_Lvl_exactFull = _init_lp_nayose_Nayose_Lvl_exactFull();
lean_mark_persistent(lp_nayose_Nayose_Lvl_exactFull);
lp_nayose_Nayose_Lvl_loosePart = _init_lp_nayose_Nayose_Lvl_loosePart();
lean_mark_persistent(lp_nayose_Nayose_Lvl_loosePart);
lp_nayose_Nayose_Lvl_exactPart = _init_lp_nayose_Nayose_Lvl_exactPart();
lean_mark_persistent(lp_nayose_Nayose_Lvl_exactPart);
lp_nayose_Nayose_Lvl_near = _init_lp_nayose_Nayose_Lvl_near();
lean_mark_persistent(lp_nayose_Nayose_Lvl_near);
lp_nayose_Nayose_Lvl_dobExact = _init_lp_nayose_Nayose_Lvl_dobExact();
lean_mark_persistent(lp_nayose_Nayose_Lvl_dobExact);
lp_nayose_Nayose_Lvl_same = _init_lp_nayose_Nayose_Lvl_same();
lean_mark_persistent(lp_nayose_Nayose_Lvl_same);
lp_nayose_Nayose_Lvl_shared = _init_lp_nayose_Nayose_Lvl_shared();
lean_mark_persistent(lp_nayose_Nayose_Lvl_shared);
lp_nayose_Nayose_Lvl_noneShared = _init_lp_nayose_Nayose_Lvl_noneShared();
lean_mark_persistent(lp_nayose_Nayose_Lvl_noneShared);
lp_nayose_Nayose_Lvl_sharedOther = _init_lp_nayose_Nayose_Lvl_sharedOther();
lean_mark_persistent(lp_nayose_Nayose_Lvl_sharedOther);
lp_nayose_Nayose_Lvl_sharedUnique = _init_lp_nayose_Nayose_Lvl_sharedUnique();
lean_mark_persistent(lp_nayose_Nayose_Lvl_sharedUnique);
lp_nayose_Nayose_Lvl_variant = _init_lp_nayose_Nayose_Lvl_variant();
lean_mark_persistent(lp_nayose_Nayose_Lvl_variant);
lp_nayose_Nayose_Lvl_kanjiExact = _init_lp_nayose_Nayose_Lvl_kanjiExact();
lean_mark_persistent(lp_nayose_Nayose_Lvl_kanjiExact);
lp_nayose_Nayose_Lvl_normalized = _init_lp_nayose_Nayose_Lvl_normalized();
lean_mark_persistent(lp_nayose_Nayose_Lvl_normalized);
lp_nayose_Nayose_Lvl_orgExact = _init_lp_nayose_Nayose_Lvl_orgExact();
lean_mark_persistent(lp_nayose_Nayose_Lvl_orgExact);
lp_nayose_Nayose_Lvl_inconsistent = _init_lp_nayose_Nayose_Lvl_inconsistent();
lean_mark_persistent(lp_nayose_Nayose_Lvl_inconsistent);
lp_nayose_Nayose_Lvl_consistent = _init_lp_nayose_Nayose_Lvl_consistent();
lean_mark_persistent(lp_nayose_Nayose_Lvl_consistent);
return lean_io_result_mk_ok(lean_box(0));
}
#ifdef __cplusplus
}
#endif
