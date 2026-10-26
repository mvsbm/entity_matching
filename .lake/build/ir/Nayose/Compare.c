// Lean compiler output
// Module: Nayose.Compare
// Imports: public import Init public meta import Init public import Nayose.Rules
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
lean_object* l_List_reverse___redArg(lean_object*);
uint8_t lean_string_dec_eq(lean_object*, lean_object*);
uint8_t l_List_isEmpty___redArg(lean_object*);
lean_object* lean_string_append(lean_object*, lean_object*);
lean_object* l_List_appendTR___redArg(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_uniqueTypes;
LEAN_EXPORT uint8_t lp_nayose_List_elem___at___00Nayose_sharedIdents_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_elem___at___00Nayose_sharedIdents_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_filterTR_loop___at___00Nayose_sharedIdents_spec__1(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_filterTR_loop___at___00Nayose_sharedIdents_spec__1___boxed(lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_sharedIdents(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_sharedIdents___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_hasConflict_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_hasConflict_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_hasConflict_spec__1(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_hasConflict_spec__1___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_Nayose_hasConflict(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_hasConflict___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_cifLevel(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_cifLevel___boxed(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_householdLevel(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_householdLevel___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_elem___at___00Nayose_identLevel_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_elem___at___00Nayose_identLevel_spec__0___boxed(lean_object*, lean_object*);
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_identLevel_spec__1(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_identLevel_spec__1___boxed(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_identLevel(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_identLevel___boxed(lean_object*, lean_object*);
static const lean_string_object lp_nayose_Nayose_cifKey___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 4, .m_capacity = 4, .m_length = 3, .m_data = "CIF"};
static const lean_object* lp_nayose_Nayose_cifKey___closed__0 = (const lean_object*)&lp_nayose_Nayose_cifKey___closed__0_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_cifKey(lean_object*);
static const lean_string_object lp_nayose_Nayose_hhKey___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 3, .m_capacity = 3, .m_length = 2, .m_data = "HH"};
static const lean_object* lp_nayose_Nayose_hhKey___closed__0 = (const lean_object*)&lp_nayose_Nayose_hhKey___closed__0_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_hhKey(lean_object*);
static const lean_string_object lp_nayose_Nayose_identKey___closed__0_value = {.m_header = {.m_rc = 0, .m_cs_sz = 0, .m_other = 0, .m_tag = 249}, .m_size = 4, .m_capacity = 4, .m_length = 3, .m_data = "ID:"};
static const lean_object* lp_nayose_Nayose_identKey___closed__0 = (const lean_object*)&lp_nayose_Nayose_identKey___closed__0_value;
LEAN_EXPORT lean_object* lp_nayose_Nayose_identKey(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00Nayose_corroborationKeys_spec__0(lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_corroborationKeys(lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf___lam__0(lean_object*, lean_object*, lean_object*, uint8_t);
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf___lam__0___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf(uint8_t, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf___boxed(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_cifLevel_match__1_splitter___redArg(lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_cifLevel_match__1_splitter(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___redArg(uint8_t, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___redArg___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter(lean_object*, uint8_t, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___redArg(uint8_t, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___redArg___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter(lean_object*, uint8_t, lean_object*, lean_object*, lean_object*, lean_object*);
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___boxed(lean_object*, lean_object*, lean_object*, lean_object*, lean_object*, lean_object*);
static lean_object* _init_lp_nayose_Nayose_uniqueTypes(void){
_start:
{
lean_object* v___x_1_; 
v___x_1_ = lean_box(0);
return v___x_1_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_elem___at___00Nayose_sharedIdents_spec__0(lean_object* v_a_2_, lean_object* v_x_3_){
_start:
{
if (lean_obj_tag(v_x_3_) == 0)
{
uint8_t v___x_4_; 
v___x_4_ = 0;
return v___x_4_;
}
else
{
lean_object* v_head_5_; lean_object* v_tail_6_; lean_object* v_fst_7_; lean_object* v_snd_8_; lean_object* v_fst_9_; lean_object* v_snd_10_; uint8_t v___x_11_; 
v_head_5_ = lean_ctor_get(v_x_3_, 0);
v_tail_6_ = lean_ctor_get(v_x_3_, 1);
v_fst_7_ = lean_ctor_get(v_a_2_, 0);
v_snd_8_ = lean_ctor_get(v_a_2_, 1);
v_fst_9_ = lean_ctor_get(v_head_5_, 0);
v_snd_10_ = lean_ctor_get(v_head_5_, 1);
v___x_11_ = lean_string_dec_eq(v_fst_7_, v_fst_9_);
if (v___x_11_ == 0)
{
v_x_3_ = v_tail_6_;
goto _start;
}
else
{
uint8_t v___x_13_; 
v___x_13_ = lean_string_dec_eq(v_snd_8_, v_snd_10_);
if (v___x_13_ == 0)
{
v_x_3_ = v_tail_6_;
goto _start;
}
else
{
return v___x_13_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_elem___at___00Nayose_sharedIdents_spec__0___boxed(lean_object* v_a_15_, lean_object* v_x_16_){
_start:
{
uint8_t v_res_17_; lean_object* v_r_18_; 
v_res_17_ = lp_nayose_List_elem___at___00Nayose_sharedIdents_spec__0(v_a_15_, v_x_16_);
lean_dec(v_x_16_);
lean_dec_ref(v_a_15_);
v_r_18_ = lean_box(v_res_17_);
return v_r_18_;
}
}
LEAN_EXPORT lean_object* lp_nayose_List_filterTR_loop___at___00Nayose_sharedIdents_spec__1(lean_object* v_b_19_, lean_object* v_a_20_, lean_object* v_a_21_){
_start:
{
if (lean_obj_tag(v_a_20_) == 0)
{
lean_object* v___x_22_; 
v___x_22_ = l_List_reverse___redArg(v_a_21_);
return v___x_22_;
}
else
{
lean_object* v_head_23_; lean_object* v_tail_24_; lean_object* v___x_26_; uint8_t v_isShared_27_; uint8_t v_isSharedCheck_35_; 
v_head_23_ = lean_ctor_get(v_a_20_, 0);
v_tail_24_ = lean_ctor_get(v_a_20_, 1);
v_isSharedCheck_35_ = !lean_is_exclusive(v_a_20_);
if (v_isSharedCheck_35_ == 0)
{
v___x_26_ = v_a_20_;
v_isShared_27_ = v_isSharedCheck_35_;
goto v_resetjp_25_;
}
else
{
lean_inc(v_tail_24_);
lean_inc(v_head_23_);
lean_dec(v_a_20_);
v___x_26_ = lean_box(0);
v_isShared_27_ = v_isSharedCheck_35_;
goto v_resetjp_25_;
}
v_resetjp_25_:
{
lean_object* v_idents_28_; uint8_t v___x_29_; 
v_idents_28_ = lean_ctor_get(v_b_19_, 1);
v___x_29_ = lp_nayose_List_elem___at___00Nayose_sharedIdents_spec__0(v_head_23_, v_idents_28_);
if (v___x_29_ == 0)
{
lean_del_object(v___x_26_);
lean_dec(v_head_23_);
v_a_20_ = v_tail_24_;
goto _start;
}
else
{
lean_object* v___x_32_; 
if (v_isShared_27_ == 0)
{
lean_ctor_set(v___x_26_, 1, v_a_21_);
v___x_32_ = v___x_26_;
goto v_reusejp_31_;
}
else
{
lean_object* v_reuseFailAlloc_34_; 
v_reuseFailAlloc_34_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_34_, 0, v_head_23_);
lean_ctor_set(v_reuseFailAlloc_34_, 1, v_a_21_);
v___x_32_ = v_reuseFailAlloc_34_;
goto v_reusejp_31_;
}
v_reusejp_31_:
{
v_a_20_ = v_tail_24_;
v_a_21_ = v___x_32_;
goto _start;
}
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_filterTR_loop___at___00Nayose_sharedIdents_spec__1___boxed(lean_object* v_b_36_, lean_object* v_a_37_, lean_object* v_a_38_){
_start:
{
lean_object* v_res_39_; 
v_res_39_ = lp_nayose_List_filterTR_loop___at___00Nayose_sharedIdents_spec__1(v_b_36_, v_a_37_, v_a_38_);
lean_dec_ref(v_b_36_);
return v_res_39_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_sharedIdents(lean_object* v_a_40_, lean_object* v_b_41_){
_start:
{
lean_object* v_idents_42_; lean_object* v___x_43_; lean_object* v___x_44_; 
v_idents_42_ = lean_ctor_get(v_a_40_, 1);
lean_inc(v_idents_42_);
lean_dec_ref(v_a_40_);
v___x_43_ = lean_box(0);
v___x_44_ = lp_nayose_List_filterTR_loop___at___00Nayose_sharedIdents_spec__1(v_b_41_, v_idents_42_, v___x_43_);
return v___x_44_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_sharedIdents___boxed(lean_object* v_a_45_, lean_object* v_b_46_){
_start:
{
lean_object* v_res_47_; 
v_res_47_ = lp_nayose_Nayose_sharedIdents(v_a_45_, v_b_46_);
lean_dec_ref(v_b_46_);
return v_res_47_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_hasConflict_spec__0(lean_object* v_p_48_, lean_object* v_x_49_){
_start:
{
if (lean_obj_tag(v_x_49_) == 0)
{
uint8_t v___x_50_; 
v___x_50_ = 0;
return v___x_50_;
}
else
{
lean_object* v_head_51_; lean_object* v_tail_52_; lean_object* v_fst_53_; lean_object* v_snd_54_; lean_object* v_fst_55_; lean_object* v_snd_56_; uint8_t v___x_57_; 
v_head_51_ = lean_ctor_get(v_x_49_, 0);
v_tail_52_ = lean_ctor_get(v_x_49_, 1);
v_fst_53_ = lean_ctor_get(v_p_48_, 0);
v_snd_54_ = lean_ctor_get(v_p_48_, 1);
v_fst_55_ = lean_ctor_get(v_head_51_, 0);
v_snd_56_ = lean_ctor_get(v_head_51_, 1);
v___x_57_ = lean_string_dec_eq(v_fst_53_, v_fst_55_);
if (v___x_57_ == 0)
{
v_x_49_ = v_tail_52_;
goto _start;
}
else
{
uint8_t v___x_59_; 
v___x_59_ = lean_string_dec_eq(v_snd_54_, v_snd_56_);
if (v___x_59_ == 0)
{
return v___x_57_;
}
else
{
v_x_49_ = v_tail_52_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_hasConflict_spec__0___boxed(lean_object* v_p_61_, lean_object* v_x_62_){
_start:
{
uint8_t v_res_63_; lean_object* v_r_64_; 
v_res_63_ = lp_nayose_List_any___at___00Nayose_hasConflict_spec__0(v_p_61_, v_x_62_);
lean_dec(v_x_62_);
lean_dec_ref(v_p_61_);
v_r_64_ = lean_box(v_res_63_);
return v_r_64_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_hasConflict_spec__1(lean_object* v_b_65_, lean_object* v_x_66_){
_start:
{
if (lean_obj_tag(v_x_66_) == 0)
{
uint8_t v___x_67_; 
v___x_67_ = 0;
return v___x_67_;
}
else
{
lean_object* v_head_68_; lean_object* v_tail_69_; lean_object* v_idents_70_; uint8_t v___x_71_; 
v_head_68_ = lean_ctor_get(v_x_66_, 0);
v_tail_69_ = lean_ctor_get(v_x_66_, 1);
v_idents_70_ = lean_ctor_get(v_b_65_, 1);
v___x_71_ = lp_nayose_List_any___at___00Nayose_hasConflict_spec__0(v_head_68_, v_idents_70_);
if (v___x_71_ == 0)
{
v_x_66_ = v_tail_69_;
goto _start;
}
else
{
return v___x_71_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_hasConflict_spec__1___boxed(lean_object* v_b_73_, lean_object* v_x_74_){
_start:
{
uint8_t v_res_75_; lean_object* v_r_76_; 
v_res_75_ = lp_nayose_List_any___at___00Nayose_hasConflict_spec__1(v_b_73_, v_x_74_);
lean_dec(v_x_74_);
lean_dec_ref(v_b_73_);
v_r_76_ = lean_box(v_res_75_);
return v_r_76_;
}
}
LEAN_EXPORT uint8_t lp_nayose_Nayose_hasConflict(lean_object* v_a_77_, lean_object* v_b_78_){
_start:
{
lean_object* v_idents_79_; uint8_t v___x_80_; 
v_idents_79_ = lean_ctor_get(v_a_77_, 1);
v___x_80_ = lp_nayose_List_any___at___00Nayose_hasConflict_spec__1(v_b_78_, v_idents_79_);
return v___x_80_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_hasConflict___boxed(lean_object* v_a_81_, lean_object* v_b_82_){
_start:
{
uint8_t v_res_83_; lean_object* v_r_84_; 
v_res_83_ = lp_nayose_Nayose_hasConflict(v_a_81_, v_b_82_);
lean_dec_ref(v_b_82_);
lean_dec_ref(v_a_81_);
v_r_84_ = lean_box(v_res_83_);
return v_r_84_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_cifLevel(lean_object* v_a_85_, lean_object* v_b_86_){
_start:
{
lean_object* v_cif_87_; 
v_cif_87_ = lean_ctor_get(v_a_85_, 0);
if (lean_obj_tag(v_cif_87_) == 1)
{
lean_object* v_cif_88_; 
v_cif_88_ = lean_ctor_get(v_b_86_, 0);
if (lean_obj_tag(v_cif_88_) == 1)
{
lean_object* v_val_89_; lean_object* v_val_90_; uint8_t v___x_91_; 
v_val_89_ = lean_ctor_get(v_cif_87_, 0);
v_val_90_ = lean_ctor_get(v_cif_88_, 0);
v___x_91_ = lean_string_dec_eq(v_val_89_, v_val_90_);
if (v___x_91_ == 0)
{
lean_object* v___x_92_; 
v___x_92_ = lean_unsigned_to_nat(1u);
return v___x_92_;
}
else
{
lean_object* v___x_93_; 
v___x_93_ = lean_unsigned_to_nat(2u);
return v___x_93_;
}
}
else
{
lean_object* v___x_94_; 
v___x_94_ = lean_unsigned_to_nat(0u);
return v___x_94_;
}
}
else
{
lean_object* v___x_95_; 
v___x_95_ = lean_unsigned_to_nat(0u);
return v___x_95_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_cifLevel___boxed(lean_object* v_a_96_, lean_object* v_b_97_){
_start:
{
lean_object* v_res_98_; 
v_res_98_ = lp_nayose_Nayose_cifLevel(v_a_96_, v_b_97_);
lean_dec_ref(v_b_97_);
lean_dec_ref(v_a_96_);
return v_res_98_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_householdLevel(lean_object* v_a_99_, lean_object* v_b_100_){
_start:
{
lean_object* v_household_101_; 
v_household_101_ = lean_ctor_get(v_a_99_, 2);
if (lean_obj_tag(v_household_101_) == 1)
{
lean_object* v_household_102_; 
v_household_102_ = lean_ctor_get(v_b_100_, 2);
if (lean_obj_tag(v_household_102_) == 1)
{
lean_object* v_val_103_; lean_object* v_val_104_; uint8_t v___x_105_; 
v_val_103_ = lean_ctor_get(v_household_101_, 0);
v_val_104_ = lean_ctor_get(v_household_102_, 0);
v___x_105_ = lean_string_dec_eq(v_val_103_, v_val_104_);
if (v___x_105_ == 0)
{
lean_object* v___x_106_; 
v___x_106_ = lean_unsigned_to_nat(1u);
return v___x_106_;
}
else
{
lean_object* v___x_107_; 
v___x_107_ = lean_unsigned_to_nat(2u);
return v___x_107_;
}
}
else
{
lean_object* v___x_108_; 
v___x_108_ = lean_unsigned_to_nat(0u);
return v___x_108_;
}
}
else
{
lean_object* v___x_109_; 
v___x_109_ = lean_unsigned_to_nat(0u);
return v___x_109_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_householdLevel___boxed(lean_object* v_a_110_, lean_object* v_b_111_){
_start:
{
lean_object* v_res_112_; 
v_res_112_ = lp_nayose_Nayose_householdLevel(v_a_110_, v_b_111_);
lean_dec_ref(v_b_111_);
lean_dec_ref(v_a_110_);
return v_res_112_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_elem___at___00Nayose_identLevel_spec__0(lean_object* v_a_113_, lean_object* v_x_114_){
_start:
{
if (lean_obj_tag(v_x_114_) == 0)
{
uint8_t v___x_115_; 
v___x_115_ = 0;
return v___x_115_;
}
else
{
lean_object* v_head_116_; lean_object* v_tail_117_; uint8_t v___x_118_; 
v_head_116_ = lean_ctor_get(v_x_114_, 0);
v_tail_117_ = lean_ctor_get(v_x_114_, 1);
v___x_118_ = lean_string_dec_eq(v_a_113_, v_head_116_);
if (v___x_118_ == 0)
{
v_x_114_ = v_tail_117_;
goto _start;
}
else
{
return v___x_118_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_elem___at___00Nayose_identLevel_spec__0___boxed(lean_object* v_a_120_, lean_object* v_x_121_){
_start:
{
uint8_t v_res_122_; lean_object* v_r_123_; 
v_res_122_ = lp_nayose_List_elem___at___00Nayose_identLevel_spec__0(v_a_120_, v_x_121_);
lean_dec(v_x_121_);
lean_dec_ref(v_a_120_);
v_r_123_ = lean_box(v_res_122_);
return v_r_123_;
}
}
LEAN_EXPORT uint8_t lp_nayose_List_any___at___00Nayose_identLevel_spec__1(lean_object* v_x_124_){
_start:
{
if (lean_obj_tag(v_x_124_) == 0)
{
uint8_t v___x_125_; 
v___x_125_ = 0;
return v___x_125_;
}
else
{
lean_object* v_head_126_; lean_object* v_tail_127_; lean_object* v_fst_128_; lean_object* v___x_129_; uint8_t v___x_130_; 
v_head_126_ = lean_ctor_get(v_x_124_, 0);
v_tail_127_ = lean_ctor_get(v_x_124_, 1);
v_fst_128_ = lean_ctor_get(v_head_126_, 0);
v___x_129_ = lean_box(0);
v___x_130_ = lp_nayose_List_elem___at___00Nayose_identLevel_spec__0(v_fst_128_, v___x_129_);
if (v___x_130_ == 0)
{
v_x_124_ = v_tail_127_;
goto _start;
}
else
{
return v___x_130_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_any___at___00Nayose_identLevel_spec__1___boxed(lean_object* v_x_132_){
_start:
{
uint8_t v_res_133_; lean_object* v_r_134_; 
v_res_133_ = lp_nayose_List_any___at___00Nayose_identLevel_spec__1(v_x_132_);
lean_dec(v_x_132_);
v_r_134_ = lean_box(v_res_133_);
return v_r_134_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_identLevel(lean_object* v_a_135_, lean_object* v_b_136_){
_start:
{
uint8_t v___y_138_; lean_object* v_idents_147_; uint8_t v___x_148_; 
v_idents_147_ = lean_ctor_get(v_a_135_, 1);
v___x_148_ = l_List_isEmpty___redArg(v_idents_147_);
if (v___x_148_ == 0)
{
lean_object* v_idents_149_; uint8_t v___x_150_; 
v_idents_149_ = lean_ctor_get(v_b_136_, 1);
v___x_150_ = l_List_isEmpty___redArg(v_idents_149_);
v___y_138_ = v___x_150_;
goto v___jp_137_;
}
else
{
v___y_138_ = v___x_148_;
goto v___jp_137_;
}
v___jp_137_:
{
if (v___y_138_ == 0)
{
lean_object* v___x_139_; uint8_t v___x_140_; 
lean_inc_ref(v_a_135_);
v___x_139_ = lp_nayose_Nayose_sharedIdents(v_a_135_, v_b_136_);
v___x_140_ = lp_nayose_List_any___at___00Nayose_identLevel_spec__1(v___x_139_);
if (v___x_140_ == 0)
{
if (lean_obj_tag(v___x_139_) == 0)
{
uint8_t v___x_141_; 
v___x_141_ = lp_nayose_Nayose_hasConflict(v_a_135_, v_b_136_);
lean_dec_ref(v_a_135_);
if (v___x_141_ == 0)
{
lean_object* v___x_142_; 
v___x_142_ = lean_unsigned_to_nat(2u);
return v___x_142_;
}
else
{
lean_object* v___x_143_; 
v___x_143_ = lean_unsigned_to_nat(1u);
return v___x_143_;
}
}
else
{
lean_object* v___x_144_; 
lean_dec(v___x_139_);
lean_dec_ref(v_a_135_);
v___x_144_ = lean_unsigned_to_nat(3u);
return v___x_144_;
}
}
else
{
lean_object* v___x_145_; 
lean_dec(v___x_139_);
lean_dec_ref(v_a_135_);
v___x_145_ = lean_unsigned_to_nat(4u);
return v___x_145_;
}
}
else
{
lean_object* v___x_146_; 
lean_dec_ref(v_a_135_);
v___x_146_ = lean_unsigned_to_nat(0u);
return v___x_146_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_identLevel___boxed(lean_object* v_a_151_, lean_object* v_b_152_){
_start:
{
lean_object* v_res_153_; 
v_res_153_ = lp_nayose_Nayose_identLevel(v_a_151_, v_b_152_);
lean_dec_ref(v_b_152_);
return v_res_153_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_cifKey(lean_object* v_r_155_){
_start:
{
lean_object* v_cif_156_; 
v_cif_156_ = lean_ctor_get(v_r_155_, 0);
lean_inc(v_cif_156_);
lean_dec_ref(v_r_155_);
if (lean_obj_tag(v_cif_156_) == 0)
{
lean_object* v___x_157_; 
v___x_157_ = lean_box(0);
return v___x_157_;
}
else
{
lean_object* v_val_158_; lean_object* v___x_160_; uint8_t v_isShared_161_; uint8_t v_isSharedCheck_167_; 
v_val_158_ = lean_ctor_get(v_cif_156_, 0);
v_isSharedCheck_167_ = !lean_is_exclusive(v_cif_156_);
if (v_isSharedCheck_167_ == 0)
{
v___x_160_ = v_cif_156_;
v_isShared_161_ = v_isSharedCheck_167_;
goto v_resetjp_159_;
}
else
{
lean_inc(v_val_158_);
lean_dec(v_cif_156_);
v___x_160_ = lean_box(0);
v_isShared_161_ = v_isSharedCheck_167_;
goto v_resetjp_159_;
}
v_resetjp_159_:
{
lean_object* v___x_162_; lean_object* v___x_163_; lean_object* v___x_165_; 
v___x_162_ = ((lean_object*)(lp_nayose_Nayose_cifKey___closed__0));
v___x_163_ = lean_alloc_ctor(0, 2, 0);
lean_ctor_set(v___x_163_, 0, v___x_162_);
lean_ctor_set(v___x_163_, 1, v_val_158_);
if (v_isShared_161_ == 0)
{
lean_ctor_set(v___x_160_, 0, v___x_163_);
v___x_165_ = v___x_160_;
goto v_reusejp_164_;
}
else
{
lean_object* v_reuseFailAlloc_166_; 
v_reuseFailAlloc_166_ = lean_alloc_ctor(1, 1, 0);
lean_ctor_set(v_reuseFailAlloc_166_, 0, v___x_163_);
v___x_165_ = v_reuseFailAlloc_166_;
goto v_reusejp_164_;
}
v_reusejp_164_:
{
return v___x_165_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_hhKey(lean_object* v_r_169_){
_start:
{
lean_object* v_household_170_; 
v_household_170_ = lean_ctor_get(v_r_169_, 2);
lean_inc(v_household_170_);
lean_dec_ref(v_r_169_);
if (lean_obj_tag(v_household_170_) == 0)
{
lean_object* v___x_171_; 
v___x_171_ = lean_box(0);
return v___x_171_;
}
else
{
lean_object* v_val_172_; lean_object* v___x_174_; uint8_t v_isShared_175_; uint8_t v_isSharedCheck_181_; 
v_val_172_ = lean_ctor_get(v_household_170_, 0);
v_isSharedCheck_181_ = !lean_is_exclusive(v_household_170_);
if (v_isSharedCheck_181_ == 0)
{
v___x_174_ = v_household_170_;
v_isShared_175_ = v_isSharedCheck_181_;
goto v_resetjp_173_;
}
else
{
lean_inc(v_val_172_);
lean_dec(v_household_170_);
v___x_174_ = lean_box(0);
v_isShared_175_ = v_isSharedCheck_181_;
goto v_resetjp_173_;
}
v_resetjp_173_:
{
lean_object* v___x_176_; lean_object* v___x_177_; lean_object* v___x_179_; 
v___x_176_ = ((lean_object*)(lp_nayose_Nayose_hhKey___closed__0));
v___x_177_ = lean_alloc_ctor(0, 2, 0);
lean_ctor_set(v___x_177_, 0, v___x_176_);
lean_ctor_set(v___x_177_, 1, v_val_172_);
if (v_isShared_175_ == 0)
{
lean_ctor_set(v___x_174_, 0, v___x_177_);
v___x_179_ = v___x_174_;
goto v_reusejp_178_;
}
else
{
lean_object* v_reuseFailAlloc_180_; 
v_reuseFailAlloc_180_ = lean_alloc_ctor(1, 1, 0);
lean_ctor_set(v_reuseFailAlloc_180_, 0, v___x_177_);
v___x_179_ = v_reuseFailAlloc_180_;
goto v_reusejp_178_;
}
v_reusejp_178_:
{
return v___x_179_;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_identKey(lean_object* v_p_183_){
_start:
{
lean_object* v_fst_184_; lean_object* v_snd_185_; lean_object* v___x_187_; uint8_t v_isShared_188_; uint8_t v_isSharedCheck_194_; 
v_fst_184_ = lean_ctor_get(v_p_183_, 0);
v_snd_185_ = lean_ctor_get(v_p_183_, 1);
v_isSharedCheck_194_ = !lean_is_exclusive(v_p_183_);
if (v_isSharedCheck_194_ == 0)
{
v___x_187_ = v_p_183_;
v_isShared_188_ = v_isSharedCheck_194_;
goto v_resetjp_186_;
}
else
{
lean_inc(v_snd_185_);
lean_inc(v_fst_184_);
lean_dec(v_p_183_);
v___x_187_ = lean_box(0);
v_isShared_188_ = v_isSharedCheck_194_;
goto v_resetjp_186_;
}
v_resetjp_186_:
{
lean_object* v___x_189_; lean_object* v___x_190_; lean_object* v___x_192_; 
v___x_189_ = ((lean_object*)(lp_nayose_Nayose_identKey___closed__0));
v___x_190_ = lean_string_append(v___x_189_, v_fst_184_);
lean_dec(v_fst_184_);
if (v_isShared_188_ == 0)
{
lean_ctor_set(v___x_187_, 0, v___x_190_);
v___x_192_ = v___x_187_;
goto v_reusejp_191_;
}
else
{
lean_object* v_reuseFailAlloc_193_; 
v_reuseFailAlloc_193_ = lean_alloc_ctor(0, 2, 0);
lean_ctor_set(v_reuseFailAlloc_193_, 0, v___x_190_);
lean_ctor_set(v_reuseFailAlloc_193_, 1, v_snd_185_);
v___x_192_ = v_reuseFailAlloc_193_;
goto v_reusejp_191_;
}
v_reusejp_191_:
{
return v___x_192_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_List_mapTR_loop___at___00Nayose_corroborationKeys_spec__0(lean_object* v_a_195_, lean_object* v_a_196_){
_start:
{
if (lean_obj_tag(v_a_195_) == 0)
{
lean_object* v___x_197_; 
v___x_197_ = l_List_reverse___redArg(v_a_196_);
return v___x_197_;
}
else
{
lean_object* v_head_198_; lean_object* v_tail_199_; lean_object* v___x_201_; uint8_t v_isShared_202_; uint8_t v_isSharedCheck_208_; 
v_head_198_ = lean_ctor_get(v_a_195_, 0);
v_tail_199_ = lean_ctor_get(v_a_195_, 1);
v_isSharedCheck_208_ = !lean_is_exclusive(v_a_195_);
if (v_isSharedCheck_208_ == 0)
{
v___x_201_ = v_a_195_;
v_isShared_202_ = v_isSharedCheck_208_;
goto v_resetjp_200_;
}
else
{
lean_inc(v_tail_199_);
lean_inc(v_head_198_);
lean_dec(v_a_195_);
v___x_201_ = lean_box(0);
v_isShared_202_ = v_isSharedCheck_208_;
goto v_resetjp_200_;
}
v_resetjp_200_:
{
lean_object* v___x_203_; lean_object* v___x_205_; 
v___x_203_ = lp_nayose_Nayose_identKey(v_head_198_);
if (v_isShared_202_ == 0)
{
lean_ctor_set(v___x_201_, 1, v_a_196_);
lean_ctor_set(v___x_201_, 0, v___x_203_);
v___x_205_ = v___x_201_;
goto v_reusejp_204_;
}
else
{
lean_object* v_reuseFailAlloc_207_; 
v_reuseFailAlloc_207_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v_reuseFailAlloc_207_, 0, v___x_203_);
lean_ctor_set(v_reuseFailAlloc_207_, 1, v_a_196_);
v___x_205_ = v_reuseFailAlloc_207_;
goto v_reusejp_204_;
}
v_reusejp_204_:
{
v_a_195_ = v_tail_199_;
v_a_196_ = v___x_205_;
goto _start;
}
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_corroborationKeys(lean_object* v_r_209_){
_start:
{
lean_object* v___y_211_; lean_object* v___x_221_; 
lean_inc_ref(v_r_209_);
v___x_221_ = lp_nayose_Nayose_cifKey(v_r_209_);
if (lean_obj_tag(v___x_221_) == 0)
{
lean_object* v___x_222_; 
v___x_222_ = lean_box(0);
v___y_211_ = v___x_222_;
goto v___jp_210_;
}
else
{
lean_object* v_val_223_; lean_object* v___x_224_; lean_object* v___x_225_; 
v_val_223_ = lean_ctor_get(v___x_221_, 0);
lean_inc(v_val_223_);
lean_dec_ref_known(v___x_221_, 1);
v___x_224_ = lean_box(0);
v___x_225_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v___x_225_, 0, v_val_223_);
lean_ctor_set(v___x_225_, 1, v___x_224_);
v___y_211_ = v___x_225_;
goto v___jp_210_;
}
v___jp_210_:
{
lean_object* v_idents_212_; lean_object* v___x_213_; lean_object* v___x_214_; lean_object* v___x_215_; lean_object* v___x_216_; 
v_idents_212_ = lean_ctor_get(v_r_209_, 1);
v___x_213_ = lean_box(0);
lean_inc(v_idents_212_);
v___x_214_ = lp_nayose_List_mapTR_loop___at___00Nayose_corroborationKeys_spec__0(v_idents_212_, v___x_213_);
v___x_215_ = l_List_appendTR___redArg(v___y_211_, v___x_214_);
v___x_216_ = lp_nayose_Nayose_hhKey(v_r_209_);
if (lean_obj_tag(v___x_216_) == 0)
{
lean_object* v___x_217_; 
v___x_217_ = l_List_appendTR___redArg(v___x_215_, v___x_213_);
return v___x_217_;
}
else
{
lean_object* v_val_218_; lean_object* v___x_219_; lean_object* v___x_220_; 
v_val_218_ = lean_ctor_get(v___x_216_, 0);
lean_inc(v_val_218_);
lean_dec_ref_known(v___x_216_, 1);
v___x_219_ = lean_alloc_ctor(1, 2, 0);
lean_ctor_set(v___x_219_, 0, v_val_218_);
lean_ctor_set(v___x_219_, 1, v___x_213_);
v___x_220_ = l_List_appendTR___redArg(v___x_215_, v___x_219_);
return v___x_220_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf___lam__0(lean_object* v_a_226_, lean_object* v_b_227_, lean_object* v_other_228_, uint8_t v_f_229_){
_start:
{
switch(v_f_229_)
{
case 6:
{
lean_object* v___x_230_; 
lean_dec_ref(v_other_228_);
v___x_230_ = lp_nayose_Nayose_cifLevel(v_a_226_, v_b_227_);
lean_dec_ref(v_a_226_);
return v___x_230_;
}
case 7:
{
lean_object* v___x_231_; 
lean_dec_ref(v_other_228_);
v___x_231_ = lp_nayose_Nayose_identLevel(v_a_226_, v_b_227_);
return v___x_231_;
}
case 8:
{
lean_object* v___x_232_; 
lean_dec_ref(v_other_228_);
v___x_232_ = lp_nayose_Nayose_householdLevel(v_a_226_, v_b_227_);
lean_dec_ref(v_a_226_);
return v___x_232_;
}
default: 
{
lean_object* v___x_233_; lean_object* v___x_234_; 
lean_dec_ref(v_a_226_);
v___x_233_ = lean_box(v_f_229_);
v___x_234_ = lean_apply_1(v_other_228_, v___x_233_);
return v___x_234_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf___lam__0___boxed(lean_object* v_a_235_, lean_object* v_b_236_, lean_object* v_other_237_, lean_object* v_f_238_){
_start:
{
uint8_t v_f_boxed_239_; lean_object* v_res_240_; 
v_f_boxed_239_ = lean_unbox(v_f_238_);
v_res_240_ = lp_nayose_Nayose_profileOf___lam__0(v_a_235_, v_b_236_, v_other_237_, v_f_boxed_239_);
lean_dec_ref(v_b_236_);
return v_res_240_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf(uint8_t v_kind_241_, lean_object* v_other_242_, lean_object* v_a_243_, lean_object* v_b_244_){
_start:
{
lean_object* v___f_245_; lean_object* v___x_246_; 
v___f_245_ = lean_alloc_closure((void*)(lp_nayose_Nayose_profileOf___lam__0___boxed), 4, 3);
lean_closure_set(v___f_245_, 0, v_a_243_);
lean_closure_set(v___f_245_, 1, v_b_244_);
lean_closure_set(v___f_245_, 2, v_other_242_);
v___x_246_ = lean_alloc_ctor(0, 1, 1);
lean_ctor_set(v___x_246_, 0, v___f_245_);
lean_ctor_set_uint8(v___x_246_, sizeof(void*)*1, v_kind_241_);
return v___x_246_;
}
}
LEAN_EXPORT lean_object* lp_nayose_Nayose_profileOf___boxed(lean_object* v_kind_247_, lean_object* v_other_248_, lean_object* v_a_249_, lean_object* v_b_250_){
_start:
{
uint8_t v_kind_boxed_251_; lean_object* v_res_252_; 
v_kind_boxed_251_ = lean_unbox(v_kind_247_);
v_res_252_ = lp_nayose_Nayose_profileOf(v_kind_boxed_251_, v_other_248_, v_a_249_, v_b_250_);
return v_res_252_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_cifLevel_match__1_splitter___redArg(lean_object* v_x_253_, lean_object* v_x_254_, lean_object* v_h__1_255_, lean_object* v_h__2_256_){
_start:
{
if (lean_obj_tag(v_x_253_) == 1)
{
if (lean_obj_tag(v_x_254_) == 1)
{
lean_object* v_val_257_; lean_object* v_val_258_; lean_object* v___x_259_; 
lean_dec(v_h__2_256_);
v_val_257_ = lean_ctor_get(v_x_253_, 0);
lean_inc(v_val_257_);
lean_dec_ref_known(v_x_253_, 1);
v_val_258_ = lean_ctor_get(v_x_254_, 0);
lean_inc(v_val_258_);
lean_dec_ref_known(v_x_254_, 1);
v___x_259_ = lean_apply_2(v_h__1_255_, v_val_257_, v_val_258_);
return v___x_259_;
}
else
{
lean_object* v___x_260_; 
lean_dec(v_h__1_255_);
v___x_260_ = lean_apply_3(v_h__2_256_, v_x_253_, v_x_254_, lean_box(0));
return v___x_260_;
}
}
else
{
lean_object* v___x_261_; 
lean_dec(v_h__1_255_);
v___x_261_ = lean_apply_3(v_h__2_256_, v_x_253_, v_x_254_, lean_box(0));
return v___x_261_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_cifLevel_match__1_splitter(lean_object* v_motive_262_, lean_object* v_x_263_, lean_object* v_x_264_, lean_object* v_h__1_265_, lean_object* v_h__2_266_){
_start:
{
if (lean_obj_tag(v_x_263_) == 1)
{
if (lean_obj_tag(v_x_264_) == 1)
{
lean_object* v_val_267_; lean_object* v_val_268_; lean_object* v___x_269_; 
lean_dec(v_h__2_266_);
v_val_267_ = lean_ctor_get(v_x_263_, 0);
lean_inc(v_val_267_);
lean_dec_ref_known(v_x_263_, 1);
v_val_268_ = lean_ctor_get(v_x_264_, 0);
lean_inc(v_val_268_);
lean_dec_ref_known(v_x_264_, 1);
v___x_269_ = lean_apply_2(v_h__1_265_, v_val_267_, v_val_268_);
return v___x_269_;
}
else
{
lean_object* v___x_270_; 
lean_dec(v_h__1_265_);
v___x_270_ = lean_apply_3(v_h__2_266_, v_x_263_, v_x_264_, lean_box(0));
return v___x_270_;
}
}
else
{
lean_object* v___x_271_; 
lean_dec(v_h__1_265_);
v___x_271_ = lean_apply_3(v_h__2_266_, v_x_263_, v_x_264_, lean_box(0));
return v___x_271_;
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___redArg(uint8_t v_f_272_, lean_object* v_h__1_273_, lean_object* v_h__2_274_, lean_object* v_h__3_275_, lean_object* v_h__4_276_){
_start:
{
switch(v_f_272_)
{
case 6:
{
lean_object* v___x_277_; lean_object* v___x_278_; 
lean_dec(v_h__4_276_);
lean_dec(v_h__3_275_);
lean_dec(v_h__2_274_);
v___x_277_ = lean_box(0);
v___x_278_ = lean_apply_1(v_h__1_273_, v___x_277_);
return v___x_278_;
}
case 7:
{
lean_object* v___x_279_; lean_object* v___x_280_; 
lean_dec(v_h__4_276_);
lean_dec(v_h__3_275_);
lean_dec(v_h__1_273_);
v___x_279_ = lean_box(0);
v___x_280_ = lean_apply_1(v_h__2_274_, v___x_279_);
return v___x_280_;
}
case 8:
{
lean_object* v___x_281_; lean_object* v___x_282_; 
lean_dec(v_h__4_276_);
lean_dec(v_h__2_274_);
lean_dec(v_h__1_273_);
v___x_281_ = lean_box(0);
v___x_282_ = lean_apply_1(v_h__3_275_, v___x_281_);
return v___x_282_;
}
default: 
{
lean_object* v___x_283_; lean_object* v___x_284_; 
lean_dec(v_h__3_275_);
lean_dec(v_h__2_274_);
lean_dec(v_h__1_273_);
v___x_283_ = lean_box(v_f_272_);
v___x_284_ = lean_apply_4(v_h__4_276_, v___x_283_, lean_box(0), lean_box(0), lean_box(0));
return v___x_284_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___redArg___boxed(lean_object* v_f_285_, lean_object* v_h__1_286_, lean_object* v_h__2_287_, lean_object* v_h__3_288_, lean_object* v_h__4_289_){
_start:
{
uint8_t v_f_23__boxed_290_; lean_object* v_res_291_; 
v_f_23__boxed_290_ = lean_unbox(v_f_285_);
v_res_291_ = lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___redArg(v_f_23__boxed_290_, v_h__1_286_, v_h__2_287_, v_h__3_288_, v_h__4_289_);
return v_res_291_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter(lean_object* v_motive_292_, uint8_t v_f_293_, lean_object* v_h__1_294_, lean_object* v_h__2_295_, lean_object* v_h__3_296_, lean_object* v_h__4_297_){
_start:
{
switch(v_f_293_)
{
case 6:
{
lean_object* v___x_298_; lean_object* v___x_299_; 
lean_dec(v_h__4_297_);
lean_dec(v_h__3_296_);
lean_dec(v_h__2_295_);
v___x_298_ = lean_box(0);
v___x_299_ = lean_apply_1(v_h__1_294_, v___x_298_);
return v___x_299_;
}
case 7:
{
lean_object* v___x_300_; lean_object* v___x_301_; 
lean_dec(v_h__4_297_);
lean_dec(v_h__3_296_);
lean_dec(v_h__1_294_);
v___x_300_ = lean_box(0);
v___x_301_ = lean_apply_1(v_h__2_295_, v___x_300_);
return v___x_301_;
}
case 8:
{
lean_object* v___x_302_; lean_object* v___x_303_; 
lean_dec(v_h__4_297_);
lean_dec(v_h__2_295_);
lean_dec(v_h__1_294_);
v___x_302_ = lean_box(0);
v___x_303_ = lean_apply_1(v_h__3_296_, v___x_302_);
return v___x_303_;
}
default: 
{
lean_object* v___x_304_; lean_object* v___x_305_; 
lean_dec(v_h__3_296_);
lean_dec(v_h__2_295_);
lean_dec(v_h__1_294_);
v___x_304_ = lean_box(v_f_293_);
v___x_305_ = lean_apply_4(v_h__4_297_, v___x_304_, lean_box(0), lean_box(0), lean_box(0));
return v___x_305_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter___boxed(lean_object* v_motive_306_, lean_object* v_f_307_, lean_object* v_h__1_308_, lean_object* v_h__2_309_, lean_object* v_h__3_310_, lean_object* v_h__4_311_){
_start:
{
uint8_t v_f_42__boxed_312_; lean_object* v_res_313_; 
v_f_42__boxed_312_ = lean_unbox(v_f_307_);
v_res_313_ = lp_nayose___private_Nayose_Compare_0__Nayose_profileOf_match__1_splitter(v_motive_306_, v_f_42__boxed_312_, v_h__1_308_, v_h__2_309_, v_h__3_310_, v_h__4_311_);
return v_res_313_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___redArg(uint8_t v_x_314_, lean_object* v_h__1_315_, lean_object* v_h__2_316_, lean_object* v_h__3_317_, lean_object* v_h__4_318_){
_start:
{
switch(v_x_314_)
{
case 6:
{
lean_object* v___x_319_; lean_object* v___x_320_; 
lean_dec(v_h__4_318_);
lean_dec(v_h__3_317_);
lean_dec(v_h__2_316_);
v___x_319_ = lean_box(0);
v___x_320_ = lean_apply_1(v_h__1_315_, v___x_319_);
return v___x_320_;
}
case 7:
{
lean_object* v___x_321_; lean_object* v___x_322_; 
lean_dec(v_h__4_318_);
lean_dec(v_h__3_317_);
lean_dec(v_h__1_315_);
v___x_321_ = lean_box(0);
v___x_322_ = lean_apply_1(v_h__2_316_, v___x_321_);
return v___x_322_;
}
case 8:
{
lean_object* v___x_323_; lean_object* v___x_324_; 
lean_dec(v_h__4_318_);
lean_dec(v_h__2_316_);
lean_dec(v_h__1_315_);
v___x_323_ = lean_box(0);
v___x_324_ = lean_apply_1(v_h__3_317_, v___x_323_);
return v___x_324_;
}
default: 
{
lean_object* v___x_325_; lean_object* v___x_326_; 
lean_dec(v_h__3_317_);
lean_dec(v_h__2_316_);
lean_dec(v_h__1_315_);
v___x_325_ = lean_box(v_x_314_);
v___x_326_ = lean_apply_4(v_h__4_318_, v___x_325_, lean_box(0), lean_box(0), lean_box(0));
return v___x_326_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___redArg___boxed(lean_object* v_x_327_, lean_object* v_h__1_328_, lean_object* v_h__2_329_, lean_object* v_h__3_330_, lean_object* v_h__4_331_){
_start:
{
uint8_t v_x_23__boxed_332_; lean_object* v_res_333_; 
v_x_23__boxed_332_ = lean_unbox(v_x_327_);
v_res_333_ = lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___redArg(v_x_23__boxed_332_, v_h__1_328_, v_h__2_329_, v_h__3_330_, v_h__4_331_);
return v_res_333_;
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter(lean_object* v_motive_334_, uint8_t v_x_335_, lean_object* v_h__1_336_, lean_object* v_h__2_337_, lean_object* v_h__3_338_, lean_object* v_h__4_339_){
_start:
{
switch(v_x_335_)
{
case 6:
{
lean_object* v___x_340_; lean_object* v___x_341_; 
lean_dec(v_h__4_339_);
lean_dec(v_h__3_338_);
lean_dec(v_h__2_337_);
v___x_340_ = lean_box(0);
v___x_341_ = lean_apply_1(v_h__1_336_, v___x_340_);
return v___x_341_;
}
case 7:
{
lean_object* v___x_342_; lean_object* v___x_343_; 
lean_dec(v_h__4_339_);
lean_dec(v_h__3_338_);
lean_dec(v_h__1_336_);
v___x_342_ = lean_box(0);
v___x_343_ = lean_apply_1(v_h__2_337_, v___x_342_);
return v___x_343_;
}
case 8:
{
lean_object* v___x_344_; lean_object* v___x_345_; 
lean_dec(v_h__4_339_);
lean_dec(v_h__2_337_);
lean_dec(v_h__1_336_);
v___x_344_ = lean_box(0);
v___x_345_ = lean_apply_1(v_h__3_338_, v___x_344_);
return v___x_345_;
}
default: 
{
lean_object* v___x_346_; lean_object* v___x_347_; 
lean_dec(v_h__3_338_);
lean_dec(v_h__2_337_);
lean_dec(v_h__1_336_);
v___x_346_ = lean_box(v_x_335_);
v___x_347_ = lean_apply_4(v_h__4_339_, v___x_346_, lean_box(0), lean_box(0), lean_box(0));
return v___x_347_;
}
}
}
}
LEAN_EXPORT lean_object* lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter___boxed(lean_object* v_motive_348_, lean_object* v_x_349_, lean_object* v_h__1_350_, lean_object* v_h__2_351_, lean_object* v_h__3_352_, lean_object* v_h__4_353_){
_start:
{
uint8_t v_x_42__boxed_354_; lean_object* v_res_355_; 
v_x_42__boxed_354_ = lean_unbox(v_x_349_);
v_res_355_ = lp_nayose___private_Nayose_Compare_0__Nayose_corroborationThreshold_match__1_splitter(v_motive_348_, v_x_42__boxed_354_, v_h__1_350_, v_h__2_351_, v_h__3_352_, v_h__4_353_);
return v_res_355_;
}
}
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_Init(uint8_t builtin);
lean_object* initialize_nayose_Nayose_Rules(uint8_t builtin);
void lean_initialize_runtime_module();
static bool _G_initialized = false;
LEAN_EXPORT lean_object* initialize_nayose_Nayose_Compare(uint8_t builtin) {
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
lp_nayose_Nayose_uniqueTypes = _init_lp_nayose_Nayose_uniqueTypes();
lean_mark_persistent(lp_nayose_Nayose_uniqueTypes);
return lean_io_result_mk_ok(lean_box(0));
}
#ifdef __cplusplus
}
#endif
