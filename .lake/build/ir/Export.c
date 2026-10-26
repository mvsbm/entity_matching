// Lean compiler output
// Module: Export
// Imports: public import Init public meta import Init public import Nayose.Rules public import Nayose.Compare
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
lean_object* lean_mk_empty_array_with_capacity(lean_object*);
lean_object* l_List_reverse___redArg(lean_object*);
lean_object* lp_nayose_Nayose_corroborationThreshold(uint8_t);
lean_object* lean_string_append(lean_object*, lean_object*);
lean_object* l_Nat_reprFast(lean_object*);
lean_object* lean_array_to_list(lean_object*);
lean_object* l_List_foldl___at___00Array_appendList_spec__0___redArg(lean_object*, lean_object*);
lean_object* lp_nayose_Nayose_arity(uint8_t);
extern lean_object* lp_nayose_Nayose_vetoRules;
extern lean_object* lp_nayose_Nayose_candidateRules;
extern lean_object* lp_nayose_Nayose_safeRules;
lean_object* l_IO_FS_writeFile(lean_object*, lean_object*);
lean_object* lean_string_length(lean_object*);
lean_object* lean_string_push(lean_object*, uint32_t);
lean_object* lean_get_stdout();
lean_object* l_List_head_x3f___redArg(lean_object*);
static const lean_string_object lp_nayose_fieldJson___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 12, .m_capacity = 12, .m_length = 11, .m_data = "\"kana_full\""};
static const lean_object* lp_nayose_fieldJson___closed__0 = (const lean_object*)&lp_nayose_fieldJson___closed__0_value;
static const lean_string_object lp_nayose_fieldJson___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 11, .m_capacity = 11, .m_length = 10, .m_data = "\"kana_sur\""};
static const lean_object* lp_nayose_fieldJson___closed__1 = (const lean_object*)&lp_nayose_fieldJson___closed__1_value;
static const lean_string_object lp_nayose_fieldJson___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 11, .m_capacity = 11, .m_length = 10, .m_data = "\"kana_giv\""};
static const lean_object* lp_nayose_fieldJson___closed__2 = (const lean_object*)&lp_nayose_fieldJson___closed__2_value;
static const lean_string_object lp_nayose_fieldJson___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 13, .m_capacity = 13, .m_length = 12, .m_data = "\"kanji_full\""};
static const lean_object* lp_nayose_fieldJson___closed__3 = (const lean_object*)&lp_nayose_fieldJson___closed__3_value;
static const lean_string_object lp_nayose_fieldJson___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 6, .m_capacity = 6, .m_length = 5, .m_data = "\"dob\""};
static const lean_object* lp_nayose_fieldJson___closed__4 = (const lean_object*)&lp_nayose_fieldJson___closed__4_value;
static const lean_string_object lp_nayose_fieldJson___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 9, .m_capacity = 9, .m_length = 8, .m_data = "\"gender\""};
static const lean_object* lp_nayose_fieldJson___closed__5 = (const lean_object*)&lp_nayose_fieldJson___closed__5_value;
static const lean_string_object lp_nayose_fieldJson___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 6, .m_capacity = 6, .m_length = 5, .m_data = "\"cif\""};
static const lean_object* lp_nayose_fieldJson___closed__6 = (const lean_object*)&lp_nayose_fieldJson___closed__6_value;
static const lean_string_object lp_nayose_fieldJson___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 8, .m_capacity = 8, .m_length = 7, .m_data = "\"ident\""};
static const lean_object* lp_nayose_fieldJson___closed__7 = (const lean_object*)&lp_nayose_fieldJson___closed__7_value;
static const lean_string_object lp_nayose_fieldJson___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 12, .m_capacity = 12, .m_length = 11, .m_data = "\"household\""};
static const lean_object* lp_nayose_fieldJson___closed__8 = (const lean_object*)&lp_nayose_fieldJson___closed__8_value;
static const lean_string_object lp_nayose_fieldJson___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 6, .m_capacity = 6, .m_length = 5, .m_data = "\"age\""};
static const lean_object* lp_nayose_fieldJson___closed__9 = (const lean_object*)&lp_nayose_fieldJson___closed__9_value;
static const lean_string_object lp_nayose_fieldJson___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 11, .m_capacity = 11, .m_length = 10, .m_data = "\"org_name\""};
static const lean_object* lp_nayose_fieldJson___closed__10 = (const lean_object*)&lp_nayose_fieldJson___closed__10_value;
static const lean_string_object lp_nayose_fieldJson___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 11, .m_capacity = 11, .m_length = 10, .m_data = "\"org_form\""};
static const lean_object* lp_nayose_fieldJson___closed__11 = (const lean_object*)&lp_nayose_fieldJson___closed__11_value;
LEAN_EXPORT lean_object* lp_nayose_fieldJson(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_fieldJson___boxed(lean_object*);
static const lean_string_object lp_nayose_kindJson___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 9, .m_capacity = 9, .m_length = 8, .m_data = "\"person\""};
static const lean_object* lp_nayose_kindJson___closed__0 = (const lean_object*)&lp_nayose_kindJson___closed__0_value;
static const lean_string_object lp_nayose_kindJson___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 6, .m_capacity = 6, .m_length = 5, .m_data = "\"org\""};
static const lean_object* lp_nayose_kindJson___closed__1 = (const lean_object*)&lp_nayose_kindJson___closed__1_value;
LEAN_EXPORT lean_object* lp_nayose_kindJson(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_kindJson___boxed(lean_object*);
static const lean_string_object lp_nayose_joinStr___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 1, .m_capacity = 1, .m_length = 0, .m_data = ""};
static const lean_object* lp_nayose_joinStr___closed__0 = (const lean_object*)&lp_nayose_joinStr___closed__0_value;
LEAN_EXPORT lean_object* lp_nayose_joinStr(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_joinStr___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_atomJson___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "["};
static const lean_object* lp_nayose_atomJson___closed__0 = (const lean_object*)&lp_nayose_atomJson___closed__0_value;
static const lean_string_object lp_nayose_atomJson___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = ","};
static const lean_object* lp_nayose_atomJson___closed__1 = (const lean_object*)&lp_nayose_atomJson___closed__1_value;
static const lean_string_object lp_nayose_atomJson___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "]"};
static const lean_object* lp_nayose_atomJson___closed__2 = (const lean_object*)&lp_nayose_atomJson___closed__2_value;
LEAN_EXPORT lean_object* lp_nayose_atomJson(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00altJson_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_altJson(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00groupJson_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_groupJson(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00ruleJson_spec__0(lean_object*, lean_object*);
static const lean_string_object lp_nayose_ruleJson___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "\""};
static const lean_object* lp_nayose_ruleJson___closed__0 = (const lean_object*)&lp_nayose_ruleJson___closed__0_value;
static const lean_string_object lp_nayose_ruleJson___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 10, .m_capacity = 10, .m_length = 9, .m_data = "{\"name\":\""};
static const lean_object* lp_nayose_ruleJson___closed__1 = (const lean_object*)&lp_nayose_ruleJson___closed__1_value;
static const lean_string_object lp_nayose_ruleJson___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 9, .m_capacity = 9, .m_length = 8, .m_data = ",\"kind\":"};
static const lean_object* lp_nayose_ruleJson___closed__2 = (const lean_object*)&lp_nayose_ruleJson___closed__2_value;
static const lean_string_object lp_nayose_ruleJson___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 12, .m_capacity = 12, .m_length = 11, .m_data = ",\"groups\":["};
static const lean_object* lp_nayose_ruleJson___closed__3 = (const lean_object*)&lp_nayose_ruleJson___closed__3_value;
static const lean_string_object lp_nayose_ruleJson___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "]}"};
static const lean_object* lp_nayose_ruleJson___closed__4 = (const lean_object*)&lp_nayose_ruleJson___closed__4_value;
LEAN_EXPORT lean_object* lp_nayose_ruleJson(lean_object*);
static const lean_string_object lp_nayose_vetoJson___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 10, .m_capacity = 10, .m_length = 9, .m_data = ",\"field\":"};
static const lean_object* lp_nayose_vetoJson___closed__0 = (const lean_object*)&lp_nayose_vetoJson___closed__0_value;
static const lean_string_object lp_nayose_vetoJson___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 7, .m_capacity = 7, .m_length = 6, .m_data = ",\"lo\":"};
static const lean_object* lp_nayose_vetoJson___closed__1 = (const lean_object*)&lp_nayose_vetoJson___closed__1_value;
static const lean_string_object lp_nayose_vetoJson___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 7, .m_capacity = 7, .m_length = 6, .m_data = ",\"hi\":"};
static const lean_object* lp_nayose_vetoJson___closed__2 = (const lean_object*)&lp_nayose_vetoJson___closed__2_value;
static const lean_string_object lp_nayose_vetoJson___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 2, .m_capacity = 2, .m_length = 1, .m_data = "}"};
static const lean_object* lp_nayose_vetoJson___closed__3 = (const lean_object*)&lp_nayose_vetoJson___closed__3_value;
LEAN_EXPORT lean_object* lp_nayose_vetoJson(lean_object*);
static const lean_ctor_object lp_nayose_allFields___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(11) << 1) | 1)),((lean_object*)(((size_t)(0) << 1) | 1))}};
static const lean_object* lp_nayose_allFields___closed__0 = (const lean_object*)&lp_nayose_allFields___closed__0_value;
static const lean_ctor_object lp_nayose_allFields___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(10) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__0_value)}};
static const lean_object* lp_nayose_allFields___closed__1 = (const lean_object*)&lp_nayose_allFields___closed__1_value;
static const lean_ctor_object lp_nayose_allFields___closed__2_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(9) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__1_value)}};
static const lean_object* lp_nayose_allFields___closed__2 = (const lean_object*)&lp_nayose_allFields___closed__2_value;
static const lean_ctor_object lp_nayose_allFields___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(8) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__2_value)}};
static const lean_object* lp_nayose_allFields___closed__3 = (const lean_object*)&lp_nayose_allFields___closed__3_value;
static const lean_ctor_object lp_nayose_allFields___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(7) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__3_value)}};
static const lean_object* lp_nayose_allFields___closed__4 = (const lean_object*)&lp_nayose_allFields___closed__4_value;
static const lean_ctor_object lp_nayose_allFields___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(6) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__4_value)}};
static const lean_object* lp_nayose_allFields___closed__5 = (const lean_object*)&lp_nayose_allFields___closed__5_value;
static const lean_ctor_object lp_nayose_allFields___closed__6_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(5) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__5_value)}};
static const lean_object* lp_nayose_allFields___closed__6 = (const lean_object*)&lp_nayose_allFields___closed__6_value;
static const lean_ctor_object lp_nayose_allFields___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(4) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__6_value)}};
static const lean_object* lp_nayose_allFields___closed__7 = (const lean_object*)&lp_nayose_allFields___closed__7_value;
static const lean_ctor_object lp_nayose_allFields___closed__8_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(3) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__7_value)}};
static const lean_object* lp_nayose_allFields___closed__8 = (const lean_object*)&lp_nayose_allFields___closed__8_value;
static const lean_ctor_object lp_nayose_allFields___closed__9_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(2) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__8_value)}};
static const lean_object* lp_nayose_allFields___closed__9 = (const lean_object*)&lp_nayose_allFields___closed__9_value;
static const lean_ctor_object lp_nayose_allFields___closed__10_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(1) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__9_value)}};
static const lean_object* lp_nayose_allFields___closed__10 = (const lean_object*)&lp_nayose_allFields___closed__10_value;
static const lean_ctor_object lp_nayose_allFields___closed__11_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_ctor_object) + sizeof(void*)*2 + 0, .m_other = 2, .m_tag = 1}, .m_objs = {((lean_object*)(((size_t)(0) << 1) | 1)),((lean_object*)&lp_nayose_allFields___closed__10_value)}};
static const lean_object* lp_nayose_allFields___closed__11 = (const lean_object*)&lp_nayose_allFields___closed__11_value;
LEAN_EXPORT const lean_object* lp_nayose_allFields = (const lean_object*)&lp_nayose_allFields___closed__11_value;
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00arityJson_spec__0(lean_object*, lean_object*);
static lean_once_cell_t lp_nayose_arityJson___closed__0_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_arityJson___closed__0;
static lean_once_cell_t lp_nayose_arityJson___closed__1_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_arityJson___closed__1;
static lean_once_cell_t lp_nayose_arityJson___closed__2_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_arityJson___closed__2;
static lean_once_cell_t lp_nayose_arityJson___closed__3_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_arityJson___closed__3;
LEAN_EXPORT lean_object* lp_nayose_arityJson;
LEAN_EXPORT lean_object* lp_nayose_corrEntry(uint8_t);
LEAN_EXPORT lean_object* lp_nayose_corrEntry___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00corroborationJson_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Init_Data_List_Impl_0__List_flatMapTR_go___at___00corroborationJson_spec__1(lean_object*, lean_object*);
static lean_once_cell_t lp_nayose_corroborationJson___closed__0_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_corroborationJson___closed__0;
static const lean_array_object lp_nayose_corroborationJson___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = sizeof(lean_array_object) + sizeof(void*)*0, .m_other = 0, .m_tag = 246}, .m_size = 0, .m_capacity = 0, .m_data = {}};
static const lean_object* lp_nayose_corroborationJson___closed__1 = (const lean_object*)&lp_nayose_corroborationJson___closed__1_value;
static lean_once_cell_t lp_nayose_corroborationJson___closed__2_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_corroborationJson___closed__2;
static lean_once_cell_t lp_nayose_corroborationJson___closed__3_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_corroborationJson___closed__3;
static lean_once_cell_t lp_nayose_corroborationJson___closed__4_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_corroborationJson___closed__4;
static lean_once_cell_t lp_nayose_corroborationJson___closed__5_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_corroborationJson___closed__5;
LEAN_EXPORT lean_object* lp_nayose_corroborationJson;
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00table_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00table_spec__1(lean_object*, lean_object*);
static const lean_string_object lp_nayose_table___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 28, .m_capacity = 28, .m_length = 27, .m_data = "{\"rules_version\":1,\"arity\":"};
static const lean_object* lp_nayose_table___closed__0 = (const lean_object*)&lp_nayose_table___closed__0_value;
static lean_once_cell_t lp_nayose_table___closed__1_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__1;
static lean_once_cell_t lp_nayose_table___closed__2_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__2;
static const lean_string_object lp_nayose_table___closed__3_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 17, .m_capacity = 17, .m_length = 16, .m_data = "\"corroboration\":"};
static const lean_object* lp_nayose_table___closed__3 = (const lean_object*)&lp_nayose_table___closed__3_value;
static lean_once_cell_t lp_nayose_table___closed__4_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__4;
static lean_once_cell_t lp_nayose_table___closed__5_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__5;
static lean_once_cell_t lp_nayose_table___closed__6_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__6;
static const lean_string_object lp_nayose_table___closed__7_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 11, .m_capacity = 11, .m_length = 10, .m_data = "\"vetoes\":["};
static const lean_object* lp_nayose_table___closed__7 = (const lean_object*)&lp_nayose_table___closed__7_value;
static lean_once_cell_t lp_nayose_table___closed__8_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__8;
static lean_once_cell_t lp_nayose_table___closed__9_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__9;
static lean_once_cell_t lp_nayose_table___closed__10_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__10;
static lean_once_cell_t lp_nayose_table___closed__11_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__11;
static const lean_string_object lp_nayose_table___closed__12_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "],"};
static const lean_object* lp_nayose_table___closed__12 = (const lean_object*)&lp_nayose_table___closed__12_value;
static lean_once_cell_t lp_nayose_table___closed__13_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__13;
static const lean_string_object lp_nayose_table___closed__14_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 9, .m_capacity = 9, .m_length = 8, .m_data = "\"safe\":["};
static const lean_object* lp_nayose_table___closed__14 = (const lean_object*)&lp_nayose_table___closed__14_value;
static lean_once_cell_t lp_nayose_table___closed__15_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__15;
static lean_once_cell_t lp_nayose_table___closed__16_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__16;
static lean_once_cell_t lp_nayose_table___closed__17_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__17;
static lean_once_cell_t lp_nayose_table___closed__18_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__18;
static lean_once_cell_t lp_nayose_table___closed__19_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__19;
static const lean_string_object lp_nayose_table___closed__20_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 14, .m_capacity = 14, .m_length = 13, .m_data = "\"candidate\":["};
static const lean_object* lp_nayose_table___closed__20 = (const lean_object*)&lp_nayose_table___closed__20_value;
static lean_once_cell_t lp_nayose_table___closed__21_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__21;
static lean_once_cell_t lp_nayose_table___closed__22_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__22;
static lean_once_cell_t lp_nayose_table___closed__23_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__23;
static lean_once_cell_t lp_nayose_table___closed__24_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__24;
static lean_once_cell_t lp_nayose_table___closed__25_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_table___closed__25;
LEAN_EXPORT lean_object* lp_nayose_table;
LEAN_EXPORT lean_object* lp_nayose_IO_print___at___00IO_println___at___00main_spec__0_spec__0(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_IO_print___at___00IO_println___at___00main_spec__0_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_IO_println___at___00main_spec__0(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_IO_println___at___00main_spec__0___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_main___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 7, .m_capacity = 7, .m_length = 6, .m_data = "wrote "};
static const lean_object* lp_nayose_main___closed__0 = (const lean_object*)&lp_nayose_main___closed__0_value;
static const lean_string_object lp_nayose_main___closed__1_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = " ("};
static const lean_object* lp_nayose_main___closed__1 = (const lean_object*)&lp_nayose_main___closed__1_value;
static lean_once_cell_t lp_nayose_main___closed__2_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_main___closed__2;
static lean_once_cell_t lp_nayose_main___closed__3_once = LEAN_ONCE_CELL_INITIALIZER;
static lean_object* lp_nayose_main___closed__3;
static const lean_string_object lp_nayose_main___closed__4_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 8, .m_capacity = 8, .m_length = 7, .m_data = " bytes)"};
static const lean_object* lp_nayose_main___closed__4 = (const lean_object*)&lp_nayose_main___closed__4_value;
static const lean_string_object lp_nayose_main___closed__5_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 11, .m_capacity = 11, .m_length = 10, .m_data = "rules.json"};
static const lean_object* lp_nayose_main___closed__5 = (const lean_object*)&lp_nayose_main___closed__5_value;
LEAN_EXPORT lean_object* lp_nayose_main___boxed__const__1;
LEAN_EXPORT lean_object* _lean_main(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_main___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_fieldJson(uint8_t v_x_13_){
_start:
{
switch(v_x_13_)
{
case 0:
{
lean_object* v___x_14_; 
v___x_14_ = ((lean_object*)(lp_nayose_fieldJson___closed__0));
return v___x_14_;
}
case 1:
{
lean_object* v___x_15_; 
v___x_15_ = ((lean_object*)(lp_nayose_fieldJson___closed__1));
return v___x_15_;
}
case 2:
{
lean_object* v___x_16_; 
v___x_16_ = ((lean_object*)(lp_nayose_fieldJson___closed__2));
return v___x_16_;
}
case 3:
{
lean_object* v___x_17_; 
v___x_17_ = ((lean_object*)(lp_nayose_fieldJson___closed__3));
return v___x_17_;
}
case 4:
{
lean_object* v___x_18_; 
v___x_18_ = ((lean_object*)(lp_nayose_fieldJson___closed__4));
return v___x_18_;
}
case 5:
{
lean_object* v___x_19_; 
v___x_19_ = ((lean_object*)(lp_nayose_fieldJson___closed__5));
return v___x_19_;
}
case 6:
{
lean_object* v___x_20_; 
v___x_20_ = ((lean_object*)(lp_nayose_fieldJson___closed__6));
return v___x_20_;
}
case 7:
{
lean_object* v___x_21_; 
v___x_21_ = ((lean_object*)(lp_nayose_fieldJson___closed__7));
return v___x_21_;
}
case 8:
{
lean_object* v___x_22_; 
v___x_22_ = ((lean_object*)(lp_nayose_fieldJson___closed__8));
return v___x_22_;
}
case 9:
{
lean_object* v___x_23_; 
v___x_23_ = ((lean_object*)(lp_nayose_fieldJson___closed__9));
return v___x_23_;
}
case 10:
{
lean_object* v___x_24_; 
v___x_24_ = ((lean_object*)(lp_nayose_fieldJson___closed__10));
return v___x_24_;
}
default: 
{
lean_object* v___x_25_; 
v___x_25_ = ((lean_object*)(lp_nayose_fieldJson___closed__11));
return v___x_25_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_fieldJson___boxed(lean_object* v_x_26_){
_start:
{
uint8_t v_x_112__boxed_27_; lean_object* v_res_28_; 
v_x_112__boxed_27_ = lean_unbox(v_x_26_);
v_res_28_ = lp_nayose_fieldJson(v_x_112__boxed_27_);
return v_res_28_;
}
}
LEAN_EXPORT lean_object* lp_nayose_kindJson(uint8_t v_x_31_){
_start:
{
if (v_x_31_ == 0)
{
lean_object* v___x_32_; 
v___x_32_ = ((lean_object*)(lp_nayose_kindJson___closed__0));
return v___x_32_;
}
else
{
lean_object* v___x_33_; 
v___x_33_ = ((lean_object*)(lp_nayose_kindJson___closed__1));
return v___x_33_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_kindJson___boxed(lean_object* v_x_34_){
_start:
{
uint8_t v_x_22__boxed_35_; lean_object* v_res_36_; 
v_x_22__boxed_35_ = lean_unbox(v_x_34_);
v_res_36_ = lp_nayose_kindJson(v_x_22__boxed_35_);
return v_res_36_;
}
}
LEAN_EXPORT lean_object* lp_nayose_joinStr(lean_object* v_sep_38_, lean_object* v_x_39_){
_start:
{
if (lean_obj_tag(v_x_39_) == 0)
{
lean_object* v___x_40_; 
v___x_40_ = ((lean_object*)(lp_nayose_joinStr___closed__0));
return v___x_40_;
}
else
{
lean_object* v_tail_41_; 
v_tail_41_ = lean_ctor_get(v_x_39_, 1);
if (lean_obj_tag(v_tail_41_) == 0)
{
lean_object* v_head_42_; 
v_head_42_ = lean_ctor_get(v_x_39_, 0);
lean_inc(v_head_42_);
lean_dec_ref_known(v_x_39_, 2);
return v_head_42_;
}
else
{
lean_object* v_head_43_; lean_object* v___x_44_; lean_object* v___x_45_; lean_object* v___x_46_; 
lean_inc(v_tail_41_);
v_head_43_ = lean_ctor_get(v_x_39_, 0);
lean_inc(v_head_43_);
lean_dec_ref_known(v_x_39_, 2);
v___x_44_ = lean_string_append(v_head_43_, v_sep_38_);
v___x_45_ = lp_nayose_joinStr(v_sep_38_, v_tail_41_);
v___x_46_ = lean_string_append(v___x_44_, v___x_45_);
lean_dec_ref(v___x_45_);
return v___x_46_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_joinStr___boxed(lean_object* v_sep_47_, lean_object* v_x_48_){
_start:
{
lean_object* v_res_49_; 
v_res_49_ = lp_nayose_joinStr(v_sep_47_, v_x_48_);
lean_dec_ref(v_sep_47_);
return v_res_49_;
}
}
LEAN_EXPORT lean_object* lp_nayose_atomJson(lean_object* v_a_53_){
_start:
{
lean_object* v_fst_54_; lean_object* v_snd_55_; lean_object* v___x_56_; uint8_t v___x_57_; lean_object* v___x_58_; lean_object* v___x_59_; lean_object* v___x_60_; lean_object* v___x_61_; lean_object* v___x_62_; lean_object* v___x_63_; lean_object* v___x_64_; lean_object* v___x_65_; 
v_fst_54_ = lean_ctor_get(v_a_53_, 0);
lean_inc(v_fst_54_);
v_snd_55_ = lean_ctor_get(v_a_53_, 1);
lean_inc(v_snd_55_);
lean_dec_ref(v_a_53_);
v___x_56_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_57_ = lean_unbox(v_fst_54_);
lean_dec(v_fst_54_);
v___x_58_ = lp_nayose_fieldJson(v___x_57_);
v___x_59_ = lean_string_append(v___x_56_, v___x_58_);
lean_dec_ref(v___x_58_);
v___x_60_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_61_ = lean_string_append(v___x_59_, v___x_60_);
v___x_62_ = l_Nat_reprFast(v_snd_55_);
v___x_63_ = lean_string_append(v___x_61_, v___x_62_);
lean_dec_ref(v___x_62_);
v___x_64_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_65_ = lean_string_append(v___x_63_, v___x_64_);
return v___x_65_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00altJson_spec__0(lean_object* v_a_66_, lean_object* v_a_67_){
_start:
{
if (lean_obj_tag(v_a_66_) == 0)
{
lean_object* v___x_68_; 
v___x_68_ = l_List_reverse___redArg(v_a_67_);
return v___x_68_;
}
else
{
lean_object* v_head_69_; lean_object* v_tail_70_; lean_object* v___x_72_; uint8_t v_isShared_73_; uint8_t v_isSharedCheck_79_; 
v_head_69_ = lean_ctor_get(v_a_66_, 0);
v_tail_70_ = lean_ctor_get(v_a_66_, 1);
v_isSharedCheck_79_ = !lean_is_exclusive(v_a_66_);
if (v_isSharedCheck_79_ == 0)
{
v___x_72_ = v_a_66_;
v_isShared_73_ = v_isSharedCheck_79_;
goto v_resetjp_71_;
}
else
{
lean_inc(v_tail_70_);
lean_inc(v_head_69_);
lean_dec(v_a_66_);
v___x_72_ = lean_box(0);
v_isShared_73_ = v_isSharedCheck_79_;
goto v_resetjp_71_;
}
v_resetjp_71_:
{
lean_object* v___x_74_; lean_object* v___x_76_; 
v___x_74_ = lp_nayose_atomJson(v_head_69_);
if (v_isShared_73_ == 0)
{
lean_ctor_set(v___x_72_, 1, v_a_67_);
lean_ctor_set(v___x_72_, 0, v___x_74_);
v___x_76_ = v___x_72_;
goto v_reusejp_75_;
}
else
{
lean_object* v_reuseFailAlloc_78_; 
v_reuseFailAlloc_78_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_78_, 0, v___x_74_);
lean_ctor_set(v_reuseFailAlloc_78_, 1, v_a_67_);
v___x_76_ = v_reuseFailAlloc_78_;
goto v_reusejp_75_;
}
v_reusejp_75_:
{
v_a_66_ = v_tail_70_;
v_a_67_ = v___x_76_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_altJson(lean_object* v_alt_80_){
_start:
{
lean_object* v___x_81_; lean_object* v___x_82_; lean_object* v___x_83_; lean_object* v___x_84_; lean_object* v___x_85_; lean_object* v___x_86_; lean_object* v___x_87_; lean_object* v___x_88_; 
v___x_81_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_82_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_83_ = lean_box(0);
v___x_84_ = lp_nayose_List_mapTR_loop___at___00altJson_spec__0(v_alt_80_, v___x_83_);
v___x_85_ = lp_nayose_joinStr(v___x_82_, v___x_84_);
v___x_86_ = lean_string_append(v___x_81_, v___x_85_);
lean_dec_ref(v___x_85_);
v___x_87_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_88_ = lean_string_append(v___x_86_, v___x_87_);
return v___x_88_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00groupJson_spec__0(lean_object* v_a_89_, lean_object* v_a_90_){
_start:
{
if (lean_obj_tag(v_a_89_) == 0)
{
lean_object* v___x_91_; 
v___x_91_ = l_List_reverse___redArg(v_a_90_);
return v___x_91_;
}
else
{
lean_object* v_head_92_; lean_object* v_tail_93_; lean_object* v___x_95_; uint8_t v_isShared_96_; uint8_t v_isSharedCheck_102_; 
v_head_92_ = lean_ctor_get(v_a_89_, 0);
v_tail_93_ = lean_ctor_get(v_a_89_, 1);
v_isSharedCheck_102_ = !lean_is_exclusive(v_a_89_);
if (v_isSharedCheck_102_ == 0)
{
v___x_95_ = v_a_89_;
v_isShared_96_ = v_isSharedCheck_102_;
goto v_resetjp_94_;
}
else
{
lean_inc(v_tail_93_);
lean_inc(v_head_92_);
lean_dec(v_a_89_);
v___x_95_ = lean_box(0);
v_isShared_96_ = v_isSharedCheck_102_;
goto v_resetjp_94_;
}
v_resetjp_94_:
{
lean_object* v___x_97_; lean_object* v___x_99_; 
v___x_97_ = lp_nayose_altJson(v_head_92_);
if (v_isShared_96_ == 0)
{
lean_ctor_set(v___x_95_, 1, v_a_90_);
lean_ctor_set(v___x_95_, 0, v___x_97_);
v___x_99_ = v___x_95_;
goto v_reusejp_98_;
}
else
{
lean_object* v_reuseFailAlloc_101_; 
v_reuseFailAlloc_101_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_101_, 0, v___x_97_);
lean_ctor_set(v_reuseFailAlloc_101_, 1, v_a_90_);
v___x_99_ = v_reuseFailAlloc_101_;
goto v_reusejp_98_;
}
v_reusejp_98_:
{
v_a_89_ = v_tail_93_;
v_a_90_ = v___x_99_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_groupJson(lean_object* v_g_103_){
_start:
{
lean_object* v___x_104_; lean_object* v___x_105_; lean_object* v___x_106_; lean_object* v___x_107_; lean_object* v___x_108_; lean_object* v___x_109_; lean_object* v___x_110_; lean_object* v___x_111_; 
v___x_104_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_105_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_106_ = lean_box(0);
v___x_107_ = lp_nayose_List_mapTR_loop___at___00groupJson_spec__0(v_g_103_, v___x_106_);
v___x_108_ = lp_nayose_joinStr(v___x_105_, v___x_107_);
v___x_109_ = lean_string_append(v___x_104_, v___x_108_);
lean_dec_ref(v___x_108_);
v___x_110_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_111_ = lean_string_append(v___x_109_, v___x_110_);
return v___x_111_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00ruleJson_spec__0(lean_object* v_a_112_, lean_object* v_a_113_){
_start:
{
if (lean_obj_tag(v_a_112_) == 0)
{
lean_object* v___x_114_; 
v___x_114_ = l_List_reverse___redArg(v_a_113_);
return v___x_114_;
}
else
{
lean_object* v_head_115_; lean_object* v_tail_116_; lean_object* v___x_118_; uint8_t v_isShared_119_; uint8_t v_isSharedCheck_125_; 
v_head_115_ = lean_ctor_get(v_a_112_, 0);
v_tail_116_ = lean_ctor_get(v_a_112_, 1);
v_isSharedCheck_125_ = !lean_is_exclusive(v_a_112_);
if (v_isSharedCheck_125_ == 0)
{
v___x_118_ = v_a_112_;
v_isShared_119_ = v_isSharedCheck_125_;
goto v_resetjp_117_;
}
else
{
lean_inc(v_tail_116_);
lean_inc(v_head_115_);
lean_dec(v_a_112_);
v___x_118_ = lean_box(0);
v_isShared_119_ = v_isSharedCheck_125_;
goto v_resetjp_117_;
}
v_resetjp_117_:
{
lean_object* v___x_120_; lean_object* v___x_122_; 
v___x_120_ = lp_nayose_groupJson(v_head_115_);
if (v_isShared_119_ == 0)
{
lean_ctor_set(v___x_118_, 1, v_a_113_);
lean_ctor_set(v___x_118_, 0, v___x_120_);
v___x_122_ = v___x_118_;
goto v_reusejp_121_;
}
else
{
lean_object* v_reuseFailAlloc_124_; 
v_reuseFailAlloc_124_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_124_, 0, v___x_120_);
lean_ctor_set(v_reuseFailAlloc_124_, 1, v_a_113_);
v___x_122_ = v_reuseFailAlloc_124_;
goto v_reusejp_121_;
}
v_reusejp_121_:
{
v_a_112_ = v_tail_116_;
v_a_113_ = v___x_122_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_ruleJson(lean_object* v_r_131_){
_start:
{
lean_object* v_name_132_; uint8_t v_kind_133_; lean_object* v_groups_134_; lean_object* v___x_135_; lean_object* v___x_136_; lean_object* v___x_137_; lean_object* v___x_138_; lean_object* v___x_139_; lean_object* v___x_140_; lean_object* v___x_141_; lean_object* v___x_142_; lean_object* v___x_143_; lean_object* v___x_144_; lean_object* v___x_145_; lean_object* v___x_146_; lean_object* v___x_147_; lean_object* v___x_148_; lean_object* v___x_149_; lean_object* v___x_150_; lean_object* v___x_151_; 
v_name_132_ = lean_ctor_get(v_r_131_, 0);
lean_inc_ref(v_name_132_);
v_kind_133_ = lean_ctor_get_uint8(v_r_131_, sizeof(void*)*2);
v_groups_134_ = lean_ctor_get(v_r_131_, 1);
lean_inc(v_groups_134_);
lean_dec_ref(v_r_131_);
v___x_135_ = ((lean_object*)(lp_nayose_ruleJson___closed__0));
v___x_136_ = ((lean_object*)(lp_nayose_ruleJson___closed__1));
v___x_137_ = lean_string_append(v___x_136_, v_name_132_);
lean_dec_ref(v_name_132_);
v___x_138_ = lean_string_append(v___x_137_, v___x_135_);
v___x_139_ = ((lean_object*)(lp_nayose_ruleJson___closed__2));
v___x_140_ = lean_string_append(v___x_138_, v___x_139_);
v___x_141_ = lp_nayose_kindJson(v_kind_133_);
v___x_142_ = lean_string_append(v___x_140_, v___x_141_);
lean_dec_ref(v___x_141_);
v___x_143_ = ((lean_object*)(lp_nayose_ruleJson___closed__3));
v___x_144_ = lean_string_append(v___x_142_, v___x_143_);
v___x_145_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_146_ = lean_box(0);
v___x_147_ = lp_nayose_List_mapTR_loop___at___00ruleJson_spec__0(v_groups_134_, v___x_146_);
v___x_148_ = lp_nayose_joinStr(v___x_145_, v___x_147_);
v___x_149_ = lean_string_append(v___x_144_, v___x_148_);
lean_dec_ref(v___x_148_);
v___x_150_ = ((lean_object*)(lp_nayose_ruleJson___closed__4));
v___x_151_ = lean_string_append(v___x_149_, v___x_150_);
return v___x_151_;
}
}
LEAN_EXPORT lean_object* lp_nayose_vetoJson(lean_object* v_v_156_){
_start:
{
lean_object* v_name_157_; uint8_t v_field_158_; lean_object* v_lo_159_; lean_object* v_hi_160_; lean_object* v___x_161_; lean_object* v___x_162_; lean_object* v___x_163_; lean_object* v___x_164_; lean_object* v___x_165_; lean_object* v___x_166_; lean_object* v___x_167_; lean_object* v___x_168_; lean_object* v___x_169_; lean_object* v___x_170_; lean_object* v___x_171_; lean_object* v___x_172_; lean_object* v___x_173_; lean_object* v___x_174_; lean_object* v___x_175_; lean_object* v___x_176_; lean_object* v___x_177_; lean_object* v___x_178_; 
v_name_157_ = lean_ctor_get(v_v_156_, 0);
lean_inc_ref(v_name_157_);
v_field_158_ = lean_ctor_get_uint8(v_v_156_, sizeof(void*)*3);
v_lo_159_ = lean_ctor_get(v_v_156_, 1);
lean_inc(v_lo_159_);
v_hi_160_ = lean_ctor_get(v_v_156_, 2);
lean_inc(v_hi_160_);
lean_dec_ref(v_v_156_);
v___x_161_ = ((lean_object*)(lp_nayose_ruleJson___closed__1));
v___x_162_ = lean_string_append(v___x_161_, v_name_157_);
lean_dec_ref(v_name_157_);
v___x_163_ = ((lean_object*)(lp_nayose_ruleJson___closed__0));
v___x_164_ = lean_string_append(v___x_162_, v___x_163_);
v___x_165_ = ((lean_object*)(lp_nayose_vetoJson___closed__0));
v___x_166_ = lean_string_append(v___x_164_, v___x_165_);
v___x_167_ = lp_nayose_fieldJson(v_field_158_);
v___x_168_ = lean_string_append(v___x_166_, v___x_167_);
lean_dec_ref(v___x_167_);
v___x_169_ = ((lean_object*)(lp_nayose_vetoJson___closed__1));
v___x_170_ = lean_string_append(v___x_168_, v___x_169_);
v___x_171_ = l_Nat_reprFast(v_lo_159_);
v___x_172_ = lean_string_append(v___x_170_, v___x_171_);
lean_dec_ref(v___x_171_);
v___x_173_ = ((lean_object*)(lp_nayose_vetoJson___closed__2));
v___x_174_ = lean_string_append(v___x_172_, v___x_173_);
v___x_175_ = l_Nat_reprFast(v_hi_160_);
v___x_176_ = lean_string_append(v___x_174_, v___x_175_);
lean_dec_ref(v___x_175_);
v___x_177_ = ((lean_object*)(lp_nayose_vetoJson___closed__3));
v___x_178_ = lean_string_append(v___x_176_, v___x_177_);
return v___x_178_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00arityJson_spec__0(lean_object* v_a_228_, lean_object* v_a_229_){
_start:
{
if (lean_obj_tag(v_a_228_) == 0)
{
lean_object* v___x_230_; 
v___x_230_ = l_List_reverse___redArg(v_a_229_);
return v___x_230_;
}
else
{
lean_object* v_head_231_; lean_object* v_tail_232_; lean_object* v___x_234_; uint8_t v_isShared_235_; uint8_t v_isSharedCheck_252_; 
v_head_231_ = lean_ctor_get(v_a_228_, 0);
v_tail_232_ = lean_ctor_get(v_a_228_, 1);
v_isSharedCheck_252_ = !lean_is_exclusive(v_a_228_);
if (v_isSharedCheck_252_ == 0)
{
v___x_234_ = v_a_228_;
v_isShared_235_ = v_isSharedCheck_252_;
goto v_resetjp_233_;
}
else
{
lean_inc(v_tail_232_);
lean_inc(v_head_231_);
lean_dec(v_a_228_);
v___x_234_ = lean_box(0);
v_isShared_235_ = v_isSharedCheck_252_;
goto v_resetjp_233_;
}
v_resetjp_233_:
{
lean_object* v___x_236_; lean_object* v___x_237_; uint8_t v___x_238_; lean_object* v___x_239_; lean_object* v___x_240_; lean_object* v___x_241_; uint8_t v___x_242_; lean_object* v___x_243_; lean_object* v___x_244_; lean_object* v___x_245_; lean_object* v___x_246_; lean_object* v___x_247_; lean_object* v___x_249_; 
v___x_236_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_237_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_238_ = lean_unbox(v_head_231_);
v___x_239_ = lp_nayose_fieldJson(v___x_238_);
v___x_240_ = lean_string_append(v___x_236_, v___x_239_);
lean_dec_ref(v___x_239_);
v___x_241_ = lean_string_append(v___x_240_, v___x_237_);
v___x_242_ = lean_unbox(v_head_231_);
lean_dec(v_head_231_);
v___x_243_ = lp_nayose_Nayose_arity(v___x_242_);
v___x_244_ = l_Nat_reprFast(v___x_243_);
v___x_245_ = lean_string_append(v___x_241_, v___x_244_);
lean_dec_ref(v___x_244_);
v___x_246_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_247_ = lean_string_append(v___x_245_, v___x_246_);
if (v_isShared_235_ == 0)
{
lean_ctor_set(v___x_234_, 1, v_a_229_);
lean_ctor_set(v___x_234_, 0, v___x_247_);
v___x_249_ = v___x_234_;
goto v_reusejp_248_;
}
else
{
lean_object* v_reuseFailAlloc_251_; 
v_reuseFailAlloc_251_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_251_, 0, v___x_247_);
lean_ctor_set(v_reuseFailAlloc_251_, 1, v_a_229_);
v___x_249_ = v_reuseFailAlloc_251_;
goto v_reusejp_248_;
}
v_reusejp_248_:
{
v_a_228_ = v_tail_232_;
v_a_229_ = v___x_249_;
goto _start;
}
}
}
}
}
static lean_object* _init_lp_nayose_arityJson___closed__0(void){
_start:
{
lean_object* v___x_253_; lean_object* v___x_254_; lean_object* v___x_255_; 
v___x_253_ = lean_box(0);
v___x_254_ = ((lean_object*)(lp_nayose_allFields));
v___x_255_ = lp_nayose_List_mapTR_loop___at___00arityJson_spec__0(v___x_254_, v___x_253_);
return v___x_255_;
}
}
static lean_object* _init_lp_nayose_arityJson___closed__1(void){
_start:
{
lean_object* v___x_256_; lean_object* v___x_257_; lean_object* v___x_258_; 
v___x_256_ = lean_obj_once(&lp_nayose_arityJson___closed__0, &lp_nayose_arityJson___closed__0_once, _init_lp_nayose_arityJson___closed__0);
v___x_257_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_258_ = lp_nayose_joinStr(v___x_257_, v___x_256_);
return v___x_258_;
}
}
static lean_object* _init_lp_nayose_arityJson___closed__2(void){
_start:
{
lean_object* v___x_259_; lean_object* v___x_260_; lean_object* v___x_261_; 
v___x_259_ = lean_obj_once(&lp_nayose_arityJson___closed__1, &lp_nayose_arityJson___closed__1_once, _init_lp_nayose_arityJson___closed__1);
v___x_260_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_261_ = lean_string_append(v___x_260_, v___x_259_);
return v___x_261_;
}
}
static lean_object* _init_lp_nayose_arityJson___closed__3(void){
_start:
{
lean_object* v___x_262_; lean_object* v___x_263_; lean_object* v___x_264_; 
v___x_262_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_263_ = lean_obj_once(&lp_nayose_arityJson___closed__2, &lp_nayose_arityJson___closed__2_once, _init_lp_nayose_arityJson___closed__2);
v___x_264_ = lean_string_append(v___x_263_, v___x_262_);
return v___x_264_;
}
}
static lean_object* _init_lp_nayose_arityJson(void){
_start:
{
lean_object* v___x_265_; 
v___x_265_ = lean_obj_once(&lp_nayose_arityJson___closed__3, &lp_nayose_arityJson___closed__3_once, _init_lp_nayose_arityJson___closed__3);
return v___x_265_;
}
}
LEAN_EXPORT lean_object* lp_nayose_corrEntry(uint8_t v_f_266_){
_start:
{
lean_object* v___x_267_; 
v___x_267_ = lp_nayose_Nayose_corroborationThreshold(v_f_266_);
if (lean_obj_tag(v___x_267_) == 0)
{
lean_object* v___x_268_; 
v___x_268_ = lean_box(0);
return v___x_268_;
}
else
{
lean_object* v_val_269_; lean_object* v___x_270_; lean_object* v___x_271_; lean_object* v___x_272_; lean_object* v___x_273_; lean_object* v___x_274_; lean_object* v___x_275_; lean_object* v___x_276_; lean_object* v___x_277_; lean_object* v___x_278_; lean_object* v___x_279_; lean_object* v___x_280_; 
v_val_269_ = lean_ctor_get(v___x_267_, 0);
lean_inc(v_val_269_);
lean_dec_ref_known(v___x_267_, 1);
v___x_270_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_271_ = lp_nayose_fieldJson(v_f_266_);
v___x_272_ = lean_string_append(v___x_270_, v___x_271_);
lean_dec_ref(v___x_271_);
v___x_273_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_274_ = lean_string_append(v___x_272_, v___x_273_);
v___x_275_ = l_Nat_reprFast(v_val_269_);
v___x_276_ = lean_string_append(v___x_274_, v___x_275_);
lean_dec_ref(v___x_275_);
v___x_277_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_278_ = lean_string_append(v___x_276_, v___x_277_);
v___x_279_ = lean_box(0);
v___x_280_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v___x_280_, 0, v___x_278_);
lean_ctor_set(v___x_280_, 1, v___x_279_);
return v___x_280_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_corrEntry___boxed(lean_object* v_f_281_){
_start:
{
uint8_t v_f_boxed_282_; lean_object* v_res_283_; 
v_f_boxed_282_ = lean_unbox(v_f_281_);
v_res_283_ = lp_nayose_corrEntry(v_f_boxed_282_);
return v_res_283_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00corroborationJson_spec__0(lean_object* v_a_284_, lean_object* v_a_285_){
_start:
{
if (lean_obj_tag(v_a_284_) == 0)
{
lean_object* v___x_286_; 
v___x_286_ = l_List_reverse___redArg(v_a_285_);
return v___x_286_;
}
else
{
lean_object* v_head_287_; lean_object* v_tail_288_; lean_object* v___x_290_; uint8_t v_isShared_291_; uint8_t v_isSharedCheck_298_; 
v_head_287_ = lean_ctor_get(v_a_284_, 0);
v_tail_288_ = lean_ctor_get(v_a_284_, 1);
v_isSharedCheck_298_ = !lean_is_exclusive(v_a_284_);
if (v_isSharedCheck_298_ == 0)
{
v___x_290_ = v_a_284_;
v_isShared_291_ = v_isSharedCheck_298_;
goto v_resetjp_289_;
}
else
{
lean_inc(v_tail_288_);
lean_inc(v_head_287_);
lean_dec(v_a_284_);
v___x_290_ = lean_box(0);
v_isShared_291_ = v_isSharedCheck_298_;
goto v_resetjp_289_;
}
v_resetjp_289_:
{
uint8_t v___x_292_; lean_object* v___x_293_; lean_object* v___x_295_; 
v___x_292_ = lean_unbox(v_head_287_);
lean_dec(v_head_287_);
v___x_293_ = lp_nayose_corrEntry(v___x_292_);
if (v_isShared_291_ == 0)
{
lean_ctor_set(v___x_290_, 1, v_a_285_);
lean_ctor_set(v___x_290_, 0, v___x_293_);
v___x_295_ = v___x_290_;
goto v_reusejp_294_;
}
else
{
lean_object* v_reuseFailAlloc_297_; 
v_reuseFailAlloc_297_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_297_, 0, v___x_293_);
lean_ctor_set(v_reuseFailAlloc_297_, 1, v_a_285_);
v___x_295_ = v_reuseFailAlloc_297_;
goto v_reusejp_294_;
}
v_reusejp_294_:
{
v_a_284_ = v_tail_288_;
v_a_285_ = v___x_295_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Init_Data_List_Impl_0__List_flatMapTR_go___at___00corroborationJson_spec__1(lean_object* v_a_299_, lean_object* v_a_300_){
_start:
{
if (lean_obj_tag(v_a_299_) == 0)
{
lean_object* v___x_301_; 
v___x_301_ = lean_array_to_list(v_a_300_);
return v___x_301_;
}
else
{
lean_object* v_head_302_; lean_object* v_tail_303_; lean_object* v___x_304_; 
v_head_302_ = lean_ctor_get(v_a_299_, 0);
lean_inc(v_head_302_);
v_tail_303_ = lean_ctor_get(v_a_299_, 1);
lean_inc(v_tail_303_);
lean_dec_ref_known(v_a_299_, 2);
v___x_304_ = l_List_foldl___at___00Array_appendList_spec__0___redArg(v_a_300_, v_head_302_);
v_a_299_ = v_tail_303_;
v_a_300_ = v___x_304_;
goto _start;
}
}
}
static lean_object* _init_lp_nayose_corroborationJson___closed__0(void){
_start:
{
lean_object* v___x_306_; lean_object* v___x_307_; lean_object* v___x_308_; 
v___x_306_ = lean_box(0);
v___x_307_ = ((lean_object*)(lp_nayose_allFields));
v___x_308_ = lp_nayose_List_mapTR_loop___at___00corroborationJson_spec__0(v___x_307_, v___x_306_);
return v___x_308_;
}
}
static lean_object* _init_lp_nayose_corroborationJson___closed__2(void){
_start:
{
lean_object* v___x_311_; lean_object* v___x_312_; lean_object* v___x_313_; 
v___x_311_ = ((lean_object*)(lp_nayose_corroborationJson___closed__1));
v___x_312_ = lean_obj_once(&lp_nayose_corroborationJson___closed__0, &lp_nayose_corroborationJson___closed__0_once, _init_lp_nayose_corroborationJson___closed__0);
v___x_313_ = lp_nayose___private_Init_Data_List_Impl_0__List_flatMapTR_go___at___00corroborationJson_spec__1(v___x_312_, v___x_311_);
return v___x_313_;
}
}
static lean_object* _init_lp_nayose_corroborationJson___closed__3(void){
_start:
{
lean_object* v___x_314_; lean_object* v___x_315_; lean_object* v___x_316_; 
v___x_314_ = lean_obj_once(&lp_nayose_corroborationJson___closed__2, &lp_nayose_corroborationJson___closed__2_once, _init_lp_nayose_corroborationJson___closed__2);
v___x_315_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_316_ = lp_nayose_joinStr(v___x_315_, v___x_314_);
return v___x_316_;
}
}
static lean_object* _init_lp_nayose_corroborationJson___closed__4(void){
_start:
{
lean_object* v___x_317_; lean_object* v___x_318_; lean_object* v___x_319_; 
v___x_317_ = lean_obj_once(&lp_nayose_corroborationJson___closed__3, &lp_nayose_corroborationJson___closed__3_once, _init_lp_nayose_corroborationJson___closed__3);
v___x_318_ = ((lean_object*)(lp_nayose_atomJson___closed__0));
v___x_319_ = lean_string_append(v___x_318_, v___x_317_);
return v___x_319_;
}
}
static lean_object* _init_lp_nayose_corroborationJson___closed__5(void){
_start:
{
lean_object* v___x_320_; lean_object* v___x_321_; lean_object* v___x_322_; 
v___x_320_ = ((lean_object*)(lp_nayose_atomJson___closed__2));
v___x_321_ = lean_obj_once(&lp_nayose_corroborationJson___closed__4, &lp_nayose_corroborationJson___closed__4_once, _init_lp_nayose_corroborationJson___closed__4);
v___x_322_ = lean_string_append(v___x_321_, v___x_320_);
return v___x_322_;
}
}
static lean_object* _init_lp_nayose_corroborationJson(void){
_start:
{
lean_object* v___x_323_; 
v___x_323_ = lean_obj_once(&lp_nayose_corroborationJson___closed__5, &lp_nayose_corroborationJson___closed__5_once, _init_lp_nayose_corroborationJson___closed__5);
return v___x_323_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00table_spec__0(lean_object* v_a_324_, lean_object* v_a_325_){
_start:
{
if (lean_obj_tag(v_a_324_) == 0)
{
lean_object* v___x_326_; 
v___x_326_ = l_List_reverse___redArg(v_a_325_);
return v___x_326_;
}
else
{
lean_object* v_head_327_; lean_object* v_tail_328_; lean_object* v___x_330_; uint8_t v_isShared_331_; uint8_t v_isSharedCheck_337_; 
v_head_327_ = lean_ctor_get(v_a_324_, 0);
v_tail_328_ = lean_ctor_get(v_a_324_, 1);
v_isSharedCheck_337_ = !lean_is_exclusive(v_a_324_);
if (v_isSharedCheck_337_ == 0)
{
v___x_330_ = v_a_324_;
v_isShared_331_ = v_isSharedCheck_337_;
goto v_resetjp_329_;
}
else
{
lean_inc(v_tail_328_);
lean_inc(v_head_327_);
lean_dec(v_a_324_);
v___x_330_ = lean_box(0);
v_isShared_331_ = v_isSharedCheck_337_;
goto v_resetjp_329_;
}
v_resetjp_329_:
{
lean_object* v___x_332_; lean_object* v___x_334_; 
v___x_332_ = lp_nayose_vetoJson(v_head_327_);
if (v_isShared_331_ == 0)
{
lean_ctor_set(v___x_330_, 1, v_a_325_);
lean_ctor_set(v___x_330_, 0, v___x_332_);
v___x_334_ = v___x_330_;
goto v_reusejp_333_;
}
else
{
lean_object* v_reuseFailAlloc_336_; 
v_reuseFailAlloc_336_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_336_, 0, v___x_332_);
lean_ctor_set(v_reuseFailAlloc_336_, 1, v_a_325_);
v___x_334_ = v_reuseFailAlloc_336_;
goto v_reusejp_333_;
}
v_reusejp_333_:
{
v_a_324_ = v_tail_328_;
v_a_325_ = v___x_334_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00table_spec__1(lean_object* v_a_338_, lean_object* v_a_339_){
_start:
{
if (lean_obj_tag(v_a_338_) == 0)
{
lean_object* v___x_340_; 
v___x_340_ = l_List_reverse___redArg(v_a_339_);
return v___x_340_;
}
else
{
lean_object* v_head_341_; lean_object* v_tail_342_; lean_object* v___x_344_; uint8_t v_isShared_345_; uint8_t v_isSharedCheck_351_; 
v_head_341_ = lean_ctor_get(v_a_338_, 0);
v_tail_342_ = lean_ctor_get(v_a_338_, 1);
v_isSharedCheck_351_ = !lean_is_exclusive(v_a_338_);
if (v_isSharedCheck_351_ == 0)
{
v___x_344_ = v_a_338_;
v_isShared_345_ = v_isSharedCheck_351_;
goto v_resetjp_343_;
}
else
{
lean_inc(v_tail_342_);
lean_inc(v_head_341_);
lean_dec(v_a_338_);
v___x_344_ = lean_box(0);
v_isShared_345_ = v_isSharedCheck_351_;
goto v_resetjp_343_;
}
v_resetjp_343_:
{
lean_object* v___x_346_; lean_object* v___x_348_; 
v___x_346_ = lp_nayose_ruleJson(v_head_341_);
if (v_isShared_345_ == 0)
{
lean_ctor_set(v___x_344_, 1, v_a_339_);
lean_ctor_set(v___x_344_, 0, v___x_346_);
v___x_348_ = v___x_344_;
goto v_reusejp_347_;
}
else
{
lean_object* v_reuseFailAlloc_350_; 
v_reuseFailAlloc_350_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_350_, 0, v___x_346_);
lean_ctor_set(v_reuseFailAlloc_350_, 1, v_a_339_);
v___x_348_ = v_reuseFailAlloc_350_;
goto v_reusejp_347_;
}
v_reusejp_347_:
{
v_a_338_ = v_tail_342_;
v_a_339_ = v___x_348_;
goto _start;
}
}
}
}
}
static lean_object* _init_lp_nayose_table___closed__1(void){
_start:
{
lean_object* v___x_353_; lean_object* v___x_354_; lean_object* v___x_355_; 
v___x_353_ = lp_nayose_arityJson;
v___x_354_ = ((lean_object*)(lp_nayose_table___closed__0));
v___x_355_ = lean_string_append(v___x_354_, v___x_353_);
return v___x_355_;
}
}
static lean_object* _init_lp_nayose_table___closed__2(void){
_start:
{
lean_object* v___x_356_; lean_object* v___x_357_; lean_object* v___x_358_; 
v___x_356_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_357_ = lean_obj_once(&lp_nayose_table___closed__1, &lp_nayose_table___closed__1_once, _init_lp_nayose_table___closed__1);
v___x_358_ = lean_string_append(v___x_357_, v___x_356_);
return v___x_358_;
}
}
static lean_object* _init_lp_nayose_table___closed__4(void){
_start:
{
lean_object* v___x_360_; lean_object* v___x_361_; lean_object* v___x_362_; 
v___x_360_ = ((lean_object*)(lp_nayose_table___closed__3));
v___x_361_ = lean_obj_once(&lp_nayose_table___closed__2, &lp_nayose_table___closed__2_once, _init_lp_nayose_table___closed__2);
v___x_362_ = lean_string_append(v___x_361_, v___x_360_);
return v___x_362_;
}
}
static lean_object* _init_lp_nayose_table___closed__5(void){
_start:
{
lean_object* v___x_363_; lean_object* v___x_364_; lean_object* v___x_365_; 
v___x_363_ = lp_nayose_corroborationJson;
v___x_364_ = lean_obj_once(&lp_nayose_table___closed__4, &lp_nayose_table___closed__4_once, _init_lp_nayose_table___closed__4);
v___x_365_ = lean_string_append(v___x_364_, v___x_363_);
return v___x_365_;
}
}
static lean_object* _init_lp_nayose_table___closed__6(void){
_start:
{
lean_object* v___x_366_; lean_object* v___x_367_; lean_object* v___x_368_; 
v___x_366_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_367_ = lean_obj_once(&lp_nayose_table___closed__5, &lp_nayose_table___closed__5_once, _init_lp_nayose_table___closed__5);
v___x_368_ = lean_string_append(v___x_367_, v___x_366_);
return v___x_368_;
}
}
static lean_object* _init_lp_nayose_table___closed__8(void){
_start:
{
lean_object* v___x_370_; lean_object* v___x_371_; lean_object* v___x_372_; 
v___x_370_ = ((lean_object*)(lp_nayose_table___closed__7));
v___x_371_ = lean_obj_once(&lp_nayose_table___closed__6, &lp_nayose_table___closed__6_once, _init_lp_nayose_table___closed__6);
v___x_372_ = lean_string_append(v___x_371_, v___x_370_);
return v___x_372_;
}
}
static lean_object* _init_lp_nayose_table___closed__9(void){
_start:
{
lean_object* v___x_373_; lean_object* v___x_374_; lean_object* v___x_375_; 
v___x_373_ = lean_box(0);
v___x_374_ = lp_nayose_Nayose_vetoRules;
v___x_375_ = lp_nayose_List_mapTR_loop___at___00table_spec__0(v___x_374_, v___x_373_);
return v___x_375_;
}
}
static lean_object* _init_lp_nayose_table___closed__10(void){
_start:
{
lean_object* v___x_376_; lean_object* v___x_377_; lean_object* v___x_378_; 
v___x_376_ = lean_obj_once(&lp_nayose_table___closed__9, &lp_nayose_table___closed__9_once, _init_lp_nayose_table___closed__9);
v___x_377_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_378_ = lp_nayose_joinStr(v___x_377_, v___x_376_);
return v___x_378_;
}
}
static lean_object* _init_lp_nayose_table___closed__11(void){
_start:
{
lean_object* v___x_379_; lean_object* v___x_380_; lean_object* v___x_381_; 
v___x_379_ = lean_obj_once(&lp_nayose_table___closed__10, &lp_nayose_table___closed__10_once, _init_lp_nayose_table___closed__10);
v___x_380_ = lean_obj_once(&lp_nayose_table___closed__8, &lp_nayose_table___closed__8_once, _init_lp_nayose_table___closed__8);
v___x_381_ = lean_string_append(v___x_380_, v___x_379_);
return v___x_381_;
}
}
static lean_object* _init_lp_nayose_table___closed__13(void){
_start:
{
lean_object* v___x_383_; lean_object* v___x_384_; lean_object* v___x_385_; 
v___x_383_ = ((lean_object*)(lp_nayose_table___closed__12));
v___x_384_ = lean_obj_once(&lp_nayose_table___closed__11, &lp_nayose_table___closed__11_once, _init_lp_nayose_table___closed__11);
v___x_385_ = lean_string_append(v___x_384_, v___x_383_);
return v___x_385_;
}
}
static lean_object* _init_lp_nayose_table___closed__15(void){
_start:
{
lean_object* v___x_387_; lean_object* v___x_388_; lean_object* v___x_389_; 
v___x_387_ = ((lean_object*)(lp_nayose_table___closed__14));
v___x_388_ = lean_obj_once(&lp_nayose_table___closed__13, &lp_nayose_table___closed__13_once, _init_lp_nayose_table___closed__13);
v___x_389_ = lean_string_append(v___x_388_, v___x_387_);
return v___x_389_;
}
}
static lean_object* _init_lp_nayose_table___closed__16(void){
_start:
{
lean_object* v___x_390_; lean_object* v___x_391_; lean_object* v___x_392_; 
v___x_390_ = lean_box(0);
v___x_391_ = lp_nayose_Nayose_safeRules;
v___x_392_ = lp_nayose_List_mapTR_loop___at___00table_spec__1(v___x_391_, v___x_390_);
return v___x_392_;
}
}
static lean_object* _init_lp_nayose_table___closed__17(void){
_start:
{
lean_object* v___x_393_; lean_object* v___x_394_; lean_object* v___x_395_; 
v___x_393_ = lean_obj_once(&lp_nayose_table___closed__16, &lp_nayose_table___closed__16_once, _init_lp_nayose_table___closed__16);
v___x_394_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_395_ = lp_nayose_joinStr(v___x_394_, v___x_393_);
return v___x_395_;
}
}
static lean_object* _init_lp_nayose_table___closed__18(void){
_start:
{
lean_object* v___x_396_; lean_object* v___x_397_; lean_object* v___x_398_; 
v___x_396_ = lean_obj_once(&lp_nayose_table___closed__17, &lp_nayose_table___closed__17_once, _init_lp_nayose_table___closed__17);
v___x_397_ = lean_obj_once(&lp_nayose_table___closed__15, &lp_nayose_table___closed__15_once, _init_lp_nayose_table___closed__15);
v___x_398_ = lean_string_append(v___x_397_, v___x_396_);
return v___x_398_;
}
}
static lean_object* _init_lp_nayose_table___closed__19(void){
_start:
{
lean_object* v___x_399_; lean_object* v___x_400_; lean_object* v___x_401_; 
v___x_399_ = ((lean_object*)(lp_nayose_table___closed__12));
v___x_400_ = lean_obj_once(&lp_nayose_table___closed__18, &lp_nayose_table___closed__18_once, _init_lp_nayose_table___closed__18);
v___x_401_ = lean_string_append(v___x_400_, v___x_399_);
return v___x_401_;
}
}
static lean_object* _init_lp_nayose_table___closed__21(void){
_start:
{
lean_object* v___x_403_; lean_object* v___x_404_; lean_object* v___x_405_; 
v___x_403_ = ((lean_object*)(lp_nayose_table___closed__20));
v___x_404_ = lean_obj_once(&lp_nayose_table___closed__19, &lp_nayose_table___closed__19_once, _init_lp_nayose_table___closed__19);
v___x_405_ = lean_string_append(v___x_404_, v___x_403_);
return v___x_405_;
}
}
static lean_object* _init_lp_nayose_table___closed__22(void){
_start:
{
lean_object* v___x_406_; lean_object* v___x_407_; lean_object* v___x_408_; 
v___x_406_ = lean_box(0);
v___x_407_ = lp_nayose_Nayose_candidateRules;
v___x_408_ = lp_nayose_List_mapTR_loop___at___00table_spec__1(v___x_407_, v___x_406_);
return v___x_408_;
}
}
static lean_object* _init_lp_nayose_table___closed__23(void){
_start:
{
lean_object* v___x_409_; lean_object* v___x_410_; lean_object* v___x_411_; 
v___x_409_ = lean_obj_once(&lp_nayose_table___closed__22, &lp_nayose_table___closed__22_once, _init_lp_nayose_table___closed__22);
v___x_410_ = ((lean_object*)(lp_nayose_atomJson___closed__1));
v___x_411_ = lp_nayose_joinStr(v___x_410_, v___x_409_);
return v___x_411_;
}
}
static lean_object* _init_lp_nayose_table___closed__24(void){
_start:
{
lean_object* v___x_412_; lean_object* v___x_413_; lean_object* v___x_414_; 
v___x_412_ = lean_obj_once(&lp_nayose_table___closed__23, &lp_nayose_table___closed__23_once, _init_lp_nayose_table___closed__23);
v___x_413_ = lean_obj_once(&lp_nayose_table___closed__21, &lp_nayose_table___closed__21_once, _init_lp_nayose_table___closed__21);
v___x_414_ = lean_string_append(v___x_413_, v___x_412_);
return v___x_414_;
}
}
static lean_object* _init_lp_nayose_table___closed__25(void){
_start:
{
lean_object* v___x_415_; lean_object* v___x_416_; lean_object* v___x_417_; 
v___x_415_ = ((lean_object*)(lp_nayose_ruleJson___closed__4));
v___x_416_ = lean_obj_once(&lp_nayose_table___closed__24, &lp_nayose_table___closed__24_once, _init_lp_nayose_table___closed__24);
v___x_417_ = lean_string_append(v___x_416_, v___x_415_);
return v___x_417_;
}
}
static lean_object* _init_lp_nayose_table(void){
_start:
{
lean_object* v___x_418_; 
v___x_418_ = lean_obj_once(&lp_nayose_table___closed__25, &lp_nayose_table___closed__25_once, _init_lp_nayose_table___closed__25);
return v___x_418_;
}
}
LEAN_EXPORT lean_object* lp_nayose_IO_print___at___00IO_println___at___00main_spec__0_spec__0(lean_object* v_s_419_){
_start:
{
lean_object* v___x_421_; lean_object* v_putStr_422_; lean_object* v___x_423_; 
v___x_421_ = lean_get_stdout();
v_putStr_422_ = lean_ctor_get(v___x_421_, 4);
lean_inc_ref(v_putStr_422_);
lean_dec_ref(v___x_421_);
v___x_423_ = lean_apply_2(v_putStr_422_, v_s_419_, lean_box(0));
return v___x_423_;
}
}
LEAN_EXPORT lean_object* lp_nayose_IO_print___at___00IO_println___at___00main_spec__0_spec__0___boxed(lean_object* v_s_424_, lean_object* v_a_425_){
_start:
{
lean_object* v_res_426_; 
v_res_426_ = lp_nayose_IO_print___at___00IO_println___at___00main_spec__0_spec__0(v_s_424_);
return v_res_426_;
}
}
LEAN_EXPORT lean_object* lp_nayose_IO_println___at___00main_spec__0(lean_object* v_s_427_){
_start:
{
uint32_t v___x_429_; lean_object* v___x_430_; lean_object* v___x_431_; 
v___x_429_ = 10;
v___x_430_ = lean_string_push(v_s_427_, v___x_429_);
v___x_431_ = lp_nayose_IO_print___at___00IO_println___at___00main_spec__0_spec__0(v___x_430_);
return v___x_431_;
}
}
LEAN_EXPORT lean_object* lp_nayose_IO_println___at___00main_spec__0___boxed(lean_object* v_s_432_, lean_object* v_a_433_){
_start:
{
lean_object* v_res_434_; 
v_res_434_ = lp_nayose_IO_println___at___00main_spec__0(v_s_432_);
return v_res_434_;
}
}
static lean_object* _init_lp_nayose_main___closed__2(void){
_start:
{
lean_object* v___x_437_; lean_object* v___x_438_; 
v___x_437_ = lp_nayose_table;
v___x_438_ = lean_string_length(v___x_437_);
return v___x_438_;
}
}
static lean_object* _init_lp_nayose_main___closed__3(void){
_start:
{
lean_object* v___x_439_; lean_object* v___x_440_; 
v___x_439_ = lean_obj_once(&lp_nayose_main___closed__2, &lp_nayose_main___closed__2_once, _init_lp_nayose_main___closed__2);
v___x_440_ = l_Nat_reprFast(v___x_439_);
return v___x_440_;
}
}
static lean_object* _init_lp_nayose_main___boxed__const__1(void){
_start:
{
uint32_t v___x_443_; lean_object* v___x_444_; 
v___x_443_ = 0;
v___x_444_ = lean_box_uint32(v___x_443_);
return v___x_444_;
}
}
LEAN_EXPORT lean_object* _lean_main(lean_object* v_args_445_){
_start:
{
lean_object* v___y_448_; lean_object* v___x_485_; 
v___x_485_ = l_List_head_x3f___redArg(v_args_445_);
lean_dec(v_args_445_);
if (lean_obj_tag(v___x_485_) == 0)
{
lean_object* v___x_486_; 
v___x_486_ = ((lean_object*)(lp_nayose_main___closed__5));
v___y_448_ = v___x_486_;
goto v___jp_447_;
}
else
{
lean_object* v_val_487_; 
v_val_487_ = lean_ctor_get(v___x_485_, 0);
lean_inc(v_val_487_);
lean_dec_ref_known(v___x_485_, 1);
v___y_448_ = v_val_487_;
goto v___jp_447_;
}
v___jp_447_:
{
lean_object* v___x_449_; lean_object* v___x_450_; 
v___x_449_ = lp_nayose_table;
v___x_450_ = l_IO_FS_writeFile(v___y_448_, v___x_449_);
if (lean_obj_tag(v___x_450_) == 0)
{
lean_object* v___x_451_; lean_object* v___x_452_; lean_object* v___x_453_; lean_object* v___x_454_; lean_object* v___x_455_; lean_object* v___x_456_; lean_object* v___x_457_; lean_object* v___x_458_; lean_object* v___x_459_; 
lean_dec_ref_known(v___x_450_, 1);
v___x_451_ = ((lean_object*)(lp_nayose_main___closed__0));
v___x_452_ = lean_string_append(v___x_451_, v___y_448_);
lean_dec_ref(v___y_448_);
v___x_453_ = ((lean_object*)(lp_nayose_main___closed__1));
v___x_454_ = lean_string_append(v___x_452_, v___x_453_);
v___x_455_ = lean_obj_once(&lp_nayose_main___closed__3, &lp_nayose_main___closed__3_once, _init_lp_nayose_main___closed__3);
v___x_456_ = lean_string_append(v___x_454_, v___x_455_);
v___x_457_ = ((lean_object*)(lp_nayose_main___closed__4));
v___x_458_ = lean_string_append(v___x_456_, v___x_457_);
v___x_459_ = lp_nayose_IO_println___at___00main_spec__0(v___x_458_);
if (lean_obj_tag(v___x_459_) == 0)
{
lean_object* v___x_461_; uint8_t v_isShared_462_; uint8_t v_isSharedCheck_467_; 
v_isSharedCheck_467_ = !lean_is_exclusive(v___x_459_);
if (v_isSharedCheck_467_ == 0)
{
lean_object* v_unused_468_; 
v_unused_468_ = lean_ctor_get(v___x_459_, 0);
lean_dec(v_unused_468_);
v___x_461_ = v___x_459_;
v_isShared_462_ = v_isSharedCheck_467_;
goto v_resetjp_460_;
}
else
{
lean_dec(v___x_459_);
v___x_461_ = lean_box(0);
v_isShared_462_ = v_isSharedCheck_467_;
goto v_resetjp_460_;
}
v_resetjp_460_:
{
lean_object* v___x_463_; lean_object* v___x_465_; 
v___x_463_ = lp_nayose_main___boxed__const__1;
if (v_isShared_462_ == 0)
{
lean_ctor_set(v___x_461_, 0, v___x_463_);
v___x_465_ = v___x_461_;
goto v_reusejp_464_;
}
else
{
lean_object* v_reuseFailAlloc_466_; 
v_reuseFailAlloc_466_ = lean_alloc_ctor(0, 1, 0);
lean_ctor_set(v_reuseFailAlloc_466_, 0, v___x_463_);
v___x_465_ = v_reuseFailAlloc_466_;
goto v_reusejp_464_;
}
v_reusejp_464_:
{
return v___x_465_;
}
}
}
else
{
lean_object* v_a_469_; lean_object* v___x_471_; uint8_t v_isShared_472_; uint8_t v_isSharedCheck_476_; 
v_a_469_ = lean_ctor_get(v___x_459_, 0);
v_isSharedCheck_476_ = !lean_is_exclusive(v___x_459_);
if (v_isSharedCheck_476_ == 0)
{
v___x_471_ = v___x_459_;
v_isShared_472_ = v_isSharedCheck_476_;
goto v_resetjp_470_;
}
else
{
lean_inc(v_a_469_);
lean_dec(v___x_459_);
v___x_471_ = lean_box(0);
v_isShared_472_ = v_isSharedCheck_476_;
goto v_resetjp_470_;
}
v_resetjp_470_:
{
lean_object* v___x_474_; 
if (v_isShared_472_ == 0)
{
v___x_474_ = v___x_471_;
goto v_reusejp_473_;
}
else
{
lean_object* v_reuseFailAlloc_475_; 
v_reuseFailAlloc_475_ = lean_alloc_ctor(1, 1, 0);
lean_ctor_set(v_reuseFailAlloc_475_, 0, v_a_469_);
v___x_474_ = v_reuseFailAlloc_475_;
goto v_reusejp_473_;
}
v_reusejp_473_:
{
return v___x_474_;
}
}
}
}
else
{
lean_object* v_a_477_; lean_object* v___x_479_; uint8_t v_isShared_480_; uint8_t v_isSharedCheck_484_; 
lean_dec_ref(v___y_448_);
v_a_477_ = lean_ctor_get(v___x_450_, 0);
v_isSharedCheck_484_ = !lean_is_exclusive(v___x_450_);
if (v_isSharedCheck_484_ == 0)
{
v___x_479_ = v___x_450_;
v_isShared_480_ = v_isSharedCheck_484_;
goto v_resetjp_478_;
}
else
{
lean_inc(v_a_477_);
lean_dec(v___x_450_);
v___x_479_ = lean_box(0);
v_isShared_480_ = v_isSharedCheck_484_;
goto v_resetjp_478_;
}
v_resetjp_478_:
{
lean_object* v___x_482_; 
if (v_isShared_480_ == 0)
{
v___x_482_ = v___x_479_;
goto v_reusejp_481_;
}
else
{
lean_object* v_reuseFailAlloc_483_; 
v_reuseFailAlloc_483_ = lean_alloc_ctor(1, 1, 0);
lean_ctor_set(v_reuseFailAlloc_483_, 0, v_a_477_);
v___x_482_ = v_reuseFailAlloc_483_;
goto v_reusejp_481_;
}
v_reusejp_481_:
{
return v___x_482_;
}
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_main___boxed(lean_object* v_args_488_, lean_object* v_a_489_){
_start:
{
lean_object* v_res_490_; 
v_res_490_ = _lean_main(v_args_488_);
return v_res_490_;
}
}
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_nayose_Nayose_Rules(uint8_t builtin);
lean_object* initialize_nayose_Nayose_Compare(uint8_t builtin);
void lean_initialize_runtime_module();
static bool _G_initialized = false;
LEAN_EXPORT lean_object* initialize_nayose_Export(uint8_t builtin) {
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
res = initialize_nayose_Nayose_Rules(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
res = initialize_nayose_Nayose_Compare(builtin);
if (lean_io_result_is_error(res)) return res;
lean_dec_ref(res);
lp_nayose_arityJson = _init_lp_nayose_arityJson();
lean_mark_persistent(lp_nayose_arityJson);
lp_nayose_corroborationJson = _init_lp_nayose_corroborationJson();
lean_mark_persistent(lp_nayose_corroborationJson);
lp_nayose_table = _init_lp_nayose_table();
lean_mark_persistent(lp_nayose_table);
lp_nayose_main___boxed__const__1 = _init_lp_nayose_main___boxed__const__1();
lean_mark_persistent(lp_nayose_main___boxed__const__1);
return lean_io_result_mk_ok(lean_box(0));
}
char ** lean_setup_args(int argc, char ** argv);
#if defined(WIN32) || defined(_WIN32)
#include <windows.h>
#endif
lean_object* run_main(int argc, char ** argv) {
    lean_object* in = lean_box(0);
    int i = argc;
    while (i > 1) {
      lean_object* n;
      i--;
      n = lean_alloc_ctor(1,2,0); lean_ctor_set(n, 0, lean_mk_string(argv[i])); lean_ctor_set(n, 1, in);
      in = n;
    }
    return _lean_main(in);
}
int main(int argc, char ** argv) {
#if defined(WIN32) || defined(_WIN32)
  SetErrorMode(SEM_FAILCRITICALERRORS);
  SetConsoleOutputCP(CP_UTF8);
#endif
  lean_object* res;
  argv = lean_setup_args(argc, argv);
  res = initialize_nayose_Export(1 /* builtin */);
  lean_io_mark_end_initialization();
  if (lean_io_result_is_ok(res)) {
    lean_dec_ref(res);
    lean_init_task_manager();
    res = lean_run_main(&run_main, argc, argv);
  }
  lean_finalize_task_manager();
  if (lean_io_result_is_ok(res)) {
    int ret = lean_unbox_uint32(lean_io_result_get_value(res));
    lean_dec_ref(res);
    return ret;
  } else {
    lean_io_result_show_error(res);
    lean_dec_ref(res);
    return 1;
  }
}
#ifdef __cplusplus
}
#endif
